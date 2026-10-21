"""Fase 4: estatísticas da partida.

Cada frame de jogo ao vivo (tomada aberta, campo identificado) vira uma linha
com o que dá para medir naquele instante: quem está com a bola, se a bola está
no terço ofensivo de alguém, altura da linha de defesa, profundidade e largura
de cada time, corredor da bola e distância percorrida pelos jogadores visíveis.
Passes e perdas de bola saem das trocas de "dono" da bola.

Tudo é gravado num SQLite local (backend/data/partidas.sqlite), junto com as
posições de cada jogador e os eventos marcados à mão (gol, cartão,
substituição, intervalo). Se o backend reiniciar, a partida continua de onde
parou.

As métricas são calculadas em duas janelas: os últimos 5 minutos e a partida
inteira. O relógio é o do computador, a partir do começo da partida no app.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .patterns import GHOST_MAX_AGE_S, OUTFIELD_ROLES, normalize
from .pitch import LENGTH, WIDTH

OWNER_RADIUS_M = 4.0
OWNER_CONFIRM_FRAMES = 2
POSSESSION_MEMORY_S = 3.0
CHAIN_MAX_GAP_S = 5.0  # bola que troca de dono depois disso não conta como passe nem perda
PASS_MIN_DISTANCE_M = 3.0
PRESSURE_WINDOW_S = 5.0
PRESSURE_RADIUS_M = 5.0
MIN_PLAYERS_FOR_SHAPE = 6
MAX_DT_S = 0.5
MAX_SPEED_MS = 10.0
ATTACKING_THIRD_X = LENGTH * 2 / 3
RECENT_WINDOW_S = 300.0
STALE_MATCH_S = 4 * 3600.0
FLUSH_EVERY_S = 1.0

EVENT_KINDS = {"gol", "amarelo", "vermelho", "substituicao", "intervalo"}

# Colunas de cada frame. Times: 0 = Time A, 1 = Time B. None vira NULL/NaN.
FRAME_COLUMNS = (
    "t", "dt", "poss", "tilt", "corridor",
    "line0", "line1", "depth0", "depth1", "width0", "width1",
    "dist0", "dist1", "ball_x", "ball_y", "left0",
)


def default_data_dir() -> Path:
    env = os.environ.get("FCA_DATA_DIR")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY, started REAL NOT NULL, last REAL NOT NULL);
CREATE TABLE IF NOT EXISTS frames (match_id INTEGER NOT NULL, {", ".join(f"{c} REAL" for c in FRAME_COLUMNS)});
CREATE TABLE IF NOT EXISTS positions (
    match_id INTEGER NOT NULL, t REAL, pid INTEGER, team INTEGER, role TEXT, x REAL, y REAL, ghost INTEGER
);
CREATE TABLE IF NOT EXISTS plays (
    match_id INTEGER NOT NULL, t REAL, team INTEGER, kind TEXT, pressers REAL, recovered INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, t REAL, kind TEXT, team INTEGER
);
CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, wall REAL, t REAL, kind TEXT, team INTEGER, payload TEXT
);
CREATE TABLE IF NOT EXISTS match_meta (
    match_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT, PRIMARY KEY (match_id, key)
);
CREATE INDEX IF NOT EXISTS frames_match ON frames (match_id);
CREATE INDEX IF NOT EXISTS insights_match ON insights (match_id);
CREATE INDEX IF NOT EXISTS positions_match ON positions (match_id);
CREATE INDEX IF NOT EXISTS plays_match ON plays (match_id);
CREATE INDEX IF NOT EXISTS events_match ON events (match_id);
"""


class MatchStore:
    """SQLite com gravação em lote: os frames vão para um buffer e são gravados a cada segundo."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._frames: list[tuple] = []
        self._positions: list[tuple] = []
        self._plays: list[tuple] = []
        self._last: tuple[int, float] | None = None
        self._last_flush = time.monotonic()

    @classmethod
    def open_default(cls) -> MatchStore:
        return cls(default_data_dir() / "partidas.sqlite")

    # ---- partidas ----

    def latest_match(self) -> tuple[int, float, float] | None:
        with self._lock:
            row = self._db.execute("SELECT id, started, last FROM matches ORDER BY id DESC LIMIT 1").fetchone()
        return (int(row[0]), float(row[1]), float(row[2])) if row else None

    def new_match(self, started: float) -> int:
        self.flush()
        with self._lock:
            cur = self._db.execute("INSERT INTO matches (started, last) VALUES (?, ?)", (started, started))
            self._db.commit()
            return int(cur.lastrowid)

    def load(self, match_id: int) -> tuple[list[tuple], list[tuple], list[tuple]]:
        with self._lock:
            frames = self._db.execute(
                f"SELECT {', '.join(FRAME_COLUMNS)} FROM frames WHERE match_id = ? ORDER BY rowid", (match_id,)
            ).fetchall()
            plays = self._db.execute(
                "SELECT t, team, kind, pressers, recovered FROM plays WHERE match_id = ? ORDER BY rowid", (match_id,)
            ).fetchall()
            events = self._db.execute(
                "SELECT id, t, kind, team FROM events WHERE match_id = ? ORDER BY t, id", (match_id,)
            ).fetchall()
        return frames, plays, events

    def load_positions(self, match_id: int) -> list[tuple]:
        """Posições gravadas da partida: (t, id, time, papel, x, y, fantasma), na ordem."""
        self.flush()
        with self._lock:
            return self._db.execute(
                "SELECT t, pid, team, role, x, y, ghost FROM positions WHERE match_id = ? ORDER BY rowid", (match_id,)
            ).fetchall()

    # ---- eventos (gravados na hora) ----

    def add_event(self, match_id: int, t: float, kind: str, team: int | None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO events (match_id, t, kind, team) VALUES (?, ?, ?, ?)", (match_id, t, kind, team)
            )
            self._db.commit()
            return int(cur.lastrowid)

    def delete_event(self, event_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM events WHERE id = ?", (event_id,))
            self._db.commit()

    # ---- dados extras da partida (nomes dos times etc.) ----

    def set_meta(self, match_id: int, key: str, value: Any) -> None:
        import json

        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO match_meta (match_id, key, value) VALUES (?, ?, ?)",
                (match_id, key, json.dumps(value, ensure_ascii=False)),
            )
            self._db.commit()

    def get_meta(self, match_id: int, key: str) -> Any:
        import json

        with self._lock:
            row = self._db.execute(
                "SELECT value FROM match_meta WHERE match_id = ? AND key = ?", (match_id, key)
            ).fetchone()
        return json.loads(row[0]) if row else None

    # ---- insights da Fase 5 (gravados na hora) ----

    def add_insight(self, match_id: int, item: dict) -> int:
        import json

        with self._lock:
            cur = self._db.execute(
                "INSERT INTO insights (match_id, wall, t, kind, team, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (match_id, item.get("wall"), item.get("t"), item.get("kind"), item.get("team"), json.dumps(item, ensure_ascii=False)),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def delete_insights(self, match_id: int, ids: list[int] | None = None) -> None:
        """Apaga itens do feed: os de `ids`, ou todos da partida."""
        with self._lock:
            if ids is None:
                self._db.execute("DELETE FROM insights WHERE match_id = ?", (match_id,))
            else:
                self._db.executemany(
                    "DELETE FROM insights WHERE match_id = ? AND id = ?", [(match_id, i) for i in ids]
                )
            self._db.commit()

    def load_insights(self, match_id: int) -> list[dict]:
        import json

        with self._lock:
            rows = self._db.execute("SELECT id, payload FROM insights WHERE match_id = ? ORDER BY id", (match_id,)).fetchall()
        return [{**json.loads(payload), "id": int(row_id)} for row_id, payload in rows]

    # ---- frames (em lote) ----

    def add_frame(self, match_id: int, row: tuple, positions: list[tuple], wall: float) -> None:
        with self._lock:
            self._frames.append((match_id, *row))
            self._positions.extend((match_id, *p) for p in positions)
            self._last = (match_id, wall)
        if time.monotonic() - self._last_flush >= FLUSH_EVERY_S:
            self.flush()

    def add_play(self, match_id: int, play: tuple) -> None:
        with self._lock:
            self._plays.append((match_id, *play))

    def flush(self) -> None:
        with self._lock:
            self._last_flush = time.monotonic()
            if not (self._frames or self._positions or self._plays or self._last):
                return
            marks = ", ".join("?" * (len(FRAME_COLUMNS) + 1))
            self._db.executemany(f"INSERT INTO frames (match_id, {', '.join(FRAME_COLUMNS)}) VALUES ({marks})", self._frames)
            self._db.executemany("INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", self._positions)
            self._db.executemany("INSERT INTO plays VALUES (?, ?, ?, ?, ?, ?)", self._plays)
            if self._last:
                self._db.execute("UPDATE matches SET last = ? WHERE id = ?", (self._last[1], self._last[0]))
            self._db.commit()
            self._frames, self._positions, self._plays, self._last = [], [], [], None

    def size_bytes(self) -> int:
        """Espaço que o banco ocupa no disco (arquivo principal e o diário WAL)."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(str(self.path) + suffix)
            except OSError:
                pass
        return total

    def wipe(self) -> int:
        """Apaga todas as partidas e devolve o espaço ao disco. Retorna quantos bytes foram liberados."""
        before = self.size_bytes()
        with self._lock:
            self._frames, self._positions, self._plays, self._last = [], [], [], None
            for table in ("positions", "frames", "plays", "events", "insights", "match_meta", "matches"):
                self._db.execute(f"DELETE FROM {table}")  # noqa: S608 (nomes fixos)
            self._db.commit()
            self._db.execute("VACUUM")
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return max(0, before - self.size_bytes())

    def close(self) -> None:
        self.flush()
        with self._lock:
            self._db.close()


# ---------------------------------------------------------------------------
# Medidas de cada frame
# ---------------------------------------------------------------------------


@dataclass
class Owner:
    pid: int | None
    team: int
    x: float
    y: float
    t: float


@dataclass
class PressureWindow:
    team: int  # quem perdeu a bola
    t0: float
    samples: list[int] = field(default_factory=list)
    recovered: bool = False


def shape_of(points: np.ndarray) -> tuple[float, float, float] | None:
    """Altura da linha de defesa (média dos mais recuados), profundidade e largura, já com o time atacando para a direita."""
    if len(points) < MIN_PLAYERS_FOR_SHAPE:
        return None
    xs = np.sort(points[:, 0])
    deepest = xs[: min(4, len(xs) - 2)]
    return float(np.mean(deepest)), float(xs[-1] - xs[0]), float(points[:, 1].max() - points[:, 1].min())


def corridor_of(y: float) -> int:
    """0 = esquerda, 1 = centro, 2 = direita, do ponto de vista de quem ataca para a direita."""
    return 0 if y < WIDTH / 3 else (1 if y < 2 * WIDTH / 3 else 2)


class StatsTracker:
    """Acompanha a partida frame a frame e grava tudo no SQLite."""

    def __init__(self, store: MatchStore | None, now: float | None = None) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._start(now if now is not None else time.time(), resume=True)

    # ---- partida ----

    def _start(self, now: float, resume: bool) -> None:
        self.frames: list[tuple] = []
        self.plays: list[tuple] = []  # (t, team, kind, pressers, recovered)
        self.events: list[dict[str, Any]] = []
        latest = self.store.latest_match() if (self.store and resume) else None
        if latest and now - latest[2] <= STALE_MATCH_S:
            self.match_id, self.started, _ = latest
            frames, plays, events = self.store.load(self.match_id)
            self.frames = [tuple(r) for r in frames]
            self.plays = [tuple(r) for r in plays]
            self.events = [{"id": e[0], "t": e[1], "kind": e[2], "team": e[3]} for e in events]
        else:
            self.started = now
            self.match_id = self.store.new_match(now) if self.store else 0
        self._load_lifecycle()
        self.last_wall: float | None = None
        self.prev_pos: dict[int, tuple[float, float, int, float]] = {}
        self.candidate: tuple[int | None, int] | None = None  # (pid, team)
        self.candidate_frames = 0
        self.owner: Owner | None = None
        self.pressure: list[PressureWindow] = []
        self.version = 0

    def wipe(self, now: float | None = None) -> int:
        """Apaga tudo o que foi gravado (todas as partidas) e começa uma partida nova, vazia."""
        with self._lock:
            freed = self.store.wipe() if self.store else 0
            self._start(now if now is not None else time.time(), resume=False)
            return freed

    def new_match(self, now: float | None = None) -> None:
        with self._lock:
            if self.store:
                self.store.flush()
            self._start(now if now is not None else time.time(), resume=False)

    # ---- ciclo da partida: criar, pausar, retomar, finalizar ----

    def _load_lifecycle(self) -> None:
        meta = (lambda key: self.store.get_meta(self.match_id, key)) if self.store else (lambda key: None)
        # "livre": partida antiga, de antes do botão Criar partida (grava como sempre gravou).
        self.state: str = meta("state") or "livre"
        self.name: str | None = meta("name")
        self.pause_total: float = float(meta("pause_total") or 0.0)
        self.pause_started: float | None = meta("pause_started")
        self.pauses: list[list[float]] = meta("pauses") or []
        self.finished_at: float | None = meta("finished_at")

    def _save_lifecycle(self) -> None:
        if not self.store:
            return
        for key in ("state", "name", "pause_total", "pause_started", "pauses", "finished_at"):
            self.store.set_meta(self.match_id, key, getattr(self, key))

    def clock(self, now: float) -> float:
        """Tempo de partida: desde o começo, sem contar as pausas."""
        paused_now = now - self.pause_started if self.pause_started is not None else 0.0
        end = self.finished_at if self.finished_at is not None else now
        return max(0.0, min(now, end) - self.started - self.pause_total - paused_now)

    def create_match(self, name: str | None, now: float | None = None) -> None:
        """Partida nova criada pelo botão: começa ativa, com nome (ou as siglas do placar)."""
        now = now if now is not None else time.time()
        with self._lock:
            if self.store:
                self.store.flush()
            self._start(now, resume=False)
            self.state = "ativa"
            self.name = (name or "").strip() or None
            self._save_lifecycle()
            self.version += 1

    def pause(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            if self.state not in ("ativa", "livre"):
                return
            self.state = "pausada"
            self.pause_started = now
            self.last_wall = None
            self._save_lifecycle()
            self.version += 1

    def resume(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            if self.state != "pausada":
                return
            if self.pause_started is not None:
                at = self.clock(self.pause_started)
                self.pauses.append([round(at, 1), round(now - self.pause_started, 1)])
                self.pause_total += now - self.pause_started
            self.pause_started = None
            self.state = "ativa"
            self._save_lifecycle()
            self.version += 1

    def finish(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            if self.state == "finalizada":
                return
            if self.pause_started is not None:
                self.pauses.append([round(self.clock(self.pause_started), 1), round(now - self.pause_started, 1)])
                self.pause_total += now - self.pause_started
                self.pause_started = None
            self.state = "finalizada"
            self.finished_at = now
            if self.store:
                self.store.flush()
            self._save_lifecycle()
            self.version += 1

    def set_name(self, name: str | None) -> None:
        with self._lock:
            self.name = (name or "").strip() or None
            self._save_lifecycle()
            self.version += 1

    @property
    def recording(self) -> bool:
        """Grava só com a partida ativa (ou livre) e fora do intervalo marcado."""
        return self.state in ("ativa", "livre") and not self.paused

    @property
    def paused(self) -> bool:
        """Durante o intervalo (número ímpar de marcações de intervalo), nada é gravado."""
        return sum(1 for e in self.events if e["kind"] == "intervalo") % 2 == 1

    # ---- eventos manuais ----

    def add_event(self, kind: str, team: int | None, now: float | None = None) -> dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise ValueError(f"evento desconhecido: {kind}")
        if kind != "intervalo" and team not in (0, 1):
            raise ValueError("escolha o time do evento")
        with self._lock:
            t = round(self.clock(now if now is not None else time.time()), 1)
            team = team if kind != "intervalo" else None
            event_id = self.store.add_event(self.match_id, t, kind, team) if self.store else len(self.events) + 1
            event = {"id": event_id, "t": t, "kind": kind, "team": team}
            self.events.append(event)
            self.version += 1
            return event

    def undo_event(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.events:
                return None
            event = self.events.pop()
            if self.store:
                self.store.delete_event(event["id"])
            self.version += 1
            return event

    # ---- um frame ----

    def observe(self, field_map: dict[str, Any], team0_defends_left: bool | None, now: float) -> None:
        with self._lock:
            if not self.recording:
                self.last_wall = None
                return
            t = self.clock(now)
            dt = 0.0 if self.last_wall is None else min(max(now - self.last_wall, 0.0), MAX_DT_S)
            self.last_wall = now

            players = [
                p
                for p in field_map.get("players", [])
                if p.get("t") in (0, 1) and (not p.get("g") or p.get("age", 0) <= GHOST_MAX_AGE_S)
            ]
            seen = [p for p in players if not p.get("g")]
            ball = field_map.get("ball")
            ball_ok = ball is not None and not ball.get("e")

            self._update_owner(seen, ball if ball_ok else None, t)
            poss = (
                self.owner.team
                if self.owner is not None and t - self.owner.t <= POSSESSION_MEMORY_S
                else None
            )
            self._update_pressure(seen, ball if ball_ok else None, poss, t)

            line = [None, None]
            depth = [None, None]
            width = [None, None]
            tilt = corridor = None
            if team0_defends_left is not None:
                for team in (0, 1):
                    defends_left = team0_defends_left if team == 0 else not team0_defends_left
                    pts = np.array(
                        [[p["x"], p["y"]] for p in players if p["t"] == team and p["l"] in OUTFIELD_ROLES], np.float32
                    ).reshape(-1, 2)
                    shape = shape_of(normalize(pts, defends_left)) if len(pts) else None
                    if shape:
                        line[team], depth[team], width[team] = (round(v, 2) for v in shape)
                    if ball_ok:
                        bx, by = normalize(np.array([[ball["x"], ball["y"]]], np.float32), defends_left)[0]
                        if bx >= ATTACKING_THIRD_X:
                            tilt = team
                        if poss == team:
                            corridor = corridor_of(float(by))

            dist = [0.0, 0.0]
            for p in seen:
                pid = p.get("id")
                if pid is None:
                    continue
                prev = self.prev_pos.get(pid)
                if prev is not None and prev[2] == p["t"]:
                    gap = now - prev[3]
                    step = float(np.hypot(p["x"] - prev[0], p["y"] - prev[1]))
                    if 0 < gap <= 0.6 and step <= MAX_SPEED_MS * gap + 0.5:
                        dist[p["t"]] += step
                self.prev_pos[pid] = (p["x"], p["y"], p["t"], now)
            if len(self.prev_pos) > 400:
                self.prev_pos = {k: v for k, v in self.prev_pos.items() if now - v[3] <= 5}

            row = (
                round(t, 2), round(dt, 3), poss, tilt, corridor,
                line[0], line[1], depth[0], depth[1], width[0], width[1],
                round(dist[0], 2), round(dist[1], 2),
                ball["x"] if ball_ok else None, ball["y"] if ball_ok else None,
                None if team0_defends_left is None else int(team0_defends_left),
            )
            self.frames.append(row)
            if self.store:
                positions = [
                    (round(t, 2), p.get("id"), p["t"], p.get("l"), p["x"], p["y"], int(bool(p.get("g"))))
                    for p in players
                ]
                self.store.add_frame(self.match_id, row, positions, now)
            self.version += 1

    def _update_owner(self, seen: list[dict[str, Any]], ball: dict[str, Any] | None, t: float) -> None:
        if ball is None or not seen:
            return
        d = [float(np.hypot(p["x"] - ball["x"], p["y"] - ball["y"])) for p in seen]
        i = int(np.argmin(d))
        if d[i] > OWNER_RADIUS_M:
            return
        p = seen[i]
        key = (p.get("id"), p["t"])
        if self.candidate is not None and self.candidate[1] == key[1]:
            self.candidate_frames += 1
        else:
            self.candidate_frames = 1
        self.candidate = key
        if self.candidate_frames < OWNER_CONFIRM_FRAMES:
            return
        new = Owner(pid=key[0], team=key[1], x=p["x"], y=p["y"], t=t)
        prev = self.owner
        if prev is not None and t - prev.t <= CHAIN_MAX_GAP_S:
            if new.team == prev.team:
                moved = float(np.hypot(new.x - prev.x, new.y - prev.y))
                if new.pid is not None and prev.pid is not None and new.pid != prev.pid and moved >= PASS_MIN_DISTANCE_M:
                    self._play((round(t, 2), new.team, "passe", None, None))
            else:
                self.pressure.append(PressureWindow(team=prev.team, t0=t))
        self.owner = new

    def _update_pressure(
        self, seen: list[dict[str, Any]], ball: dict[str, Any] | None, poss: int | None, t: float
    ) -> None:
        still_open = []
        for w in self.pressure:
            if t - w.t0 > PRESSURE_WINDOW_S:
                pressers = round(float(np.mean(w.samples)), 2) if w.samples else None
                self._play((round(w.t0, 2), w.team, "perda", pressers, int(w.recovered)))
                continue
            if ball is not None:
                w.samples.append(
                    sum(
                        1
                        for p in seen
                        if p["t"] == w.team and np.hypot(p["x"] - ball["x"], p["y"] - ball["y"]) <= PRESSURE_RADIUS_M
                    )
                )
            if poss == w.team and t > w.t0:
                w.recovered = True
            still_open.append(w)
        self.pressure = still_open

    def _play(self, play: tuple) -> None:
        self.plays.append(play)
        if self.store:
            self.store.add_play(self.match_id, play)

    def flush(self) -> None:
        if self.store:
            self.store.flush()

    # ---- resumo ----

    def summary(self, now: float | None = None) -> dict[str, Any]:
        with self._lock:
            now = now if now is not None else time.time()
            frames = list(self.frames)
            plays = list(self.plays)
            events = [dict(e) for e in self.events]
            started, match_id, paused = self.started, self.match_id, self.paused
            elapsed = self.clock(now)
            lifecycle = {
                "matchState": self.state,
                "matchName": self.name,
                "pauses": [list(p) for p in self.pauses],
                "pausedSince": round(self.pause_started * 1000) if self.pause_started is not None else None,
            }
        table = (
            np.array([[np.nan if v is None else v for v in row] for row in frames], dtype=np.float64)
            if frames
            else np.zeros((0, len(FRAME_COLUMNS)))
        )
        col = {name: i for i, name in enumerate(FRAME_COLUMNS)}
        recent_from = (table[-1, col["t"]] if len(table) else elapsed) - RECENT_WINDOW_S
        breaks = sum(1 for e in events if e["kind"] == "intervalo")
        return {
            "matchId": match_id,
            "startedAt": round(started * 1000),
            "elapsedS": round(elapsed, 1),
            "paused": paused,
            "period": 1 if breaks == 0 else 2,
            "score": [sum(1 for e in events if e["kind"] == "gol" and e["team"] == t) for t in (0, 1)],
            "events": events,
            "windows": {
                "recentes": window_stats(table, col, plays, recent_from),
                "partida": window_stats(table, col, plays, -np.inf),
            },
            "timeline": timeline(table, col),
            **lifecycle,
        }


# ---------------------------------------------------------------------------
# Métricas de uma janela
# ---------------------------------------------------------------------------


def _share(weights: np.ndarray, labels: np.ndarray) -> list[float] | None:
    known = ~np.isnan(labels)
    total = float(weights[known].sum())
    if total <= 0:
        return None
    return [round(100 * float(weights[known & (labels == t)].sum()) / total, 1) for t in (0, 1)]


def _wmean(values: np.ndarray, weights: np.ndarray) -> float | None:
    ok = ~np.isnan(values)
    w = weights[ok]
    if not ok.any():
        return None
    if w.sum() <= 0:
        return round(float(values[ok].mean()), 1)
    return round(float(np.average(values[ok], weights=w)), 1)


def window_stats(table: np.ndarray, col: dict[str, int], plays: list[tuple], t_from: float) -> dict[str, Any]:
    rows = table[table[:, col["t"]] >= t_from] if len(table) else table
    w = rows[:, col["dt"]] if len(rows) else np.zeros(0)
    poss = rows[:, col["poss"]] if len(rows) else np.zeros(0)
    corridors: list[list[float] | None] = []
    for team in (0, 1):
        mask = (poss == team) & ~np.isnan(rows[:, col["corridor"]]) if len(rows) else np.zeros(0, bool)
        total = float(w[mask].sum())
        corridors.append(
            [round(100 * float(w[mask & (rows[:, col["corridor"]] == c)].sum()) / total, 1) for c in range(3)]
            if total > 0
            else None
        )

    recent = [p for p in plays if p[0] >= t_from]
    passes = [sum(1 for p in recent if p[2] == "passe" and p[1] == t) for t in (0, 1)]
    losses = [sum(1 for p in recent if p[2] == "perda" and p[1] == t) for t in (0, 1)]
    pressure: list[float | None] = []
    recoveries: list[float | None] = []
    for team in (0, 1):
        mine = [p for p in recent if p[2] == "perda" and p[1] == team]
        values = [p[3] for p in mine if p[3] is not None]
        pressure.append(round(float(np.mean(values)), 1) if values else None)
        recoveries.append(round(100 * sum(1 for p in mine if p[4]) / len(mine), 0) if mine else None)

    def per_team(name: str) -> list[float | None]:
        return [_wmean(rows[:, col[f"{name}{t}"]], w) if len(rows) else None for t in (0, 1)]

    seconds = float(w.sum())
    known = float(w[~np.isnan(poss)].sum()) if len(rows) else 0.0
    return {
        "seconds": round(seconds, 1),
        "possession": _share(w, poss) if len(rows) else None,
        "possessionCoverage": round(100 * known / seconds, 0) if seconds > 0 else None,
        "tilt": _share(w, rows[:, col["tilt"]]) if len(rows) else None,
        "line": per_team("line"),
        "depth": per_team("depth"),
        "width": per_team("width"),
        "corridors": corridors,
        "passes": passes,
        "losses": losses,
        "passAccuracy": [
            round(100 * passes[t] / (passes[t] + losses[t]), 0) if passes[t] + losses[t] > 0 else None for t in (0, 1)
        ],
        "pressure": pressure,
        "recoveries5s": recoveries,
        "distanceKm": [
            round(float(np.nansum(rows[:, col[f"dist{t}"]])) / 1000, 2) if len(rows) else 0.0 for t in (0, 1)
        ],
    }


def timeline(table: np.ndarray, col: dict[str, int]) -> dict[str, Any]:
    """Por minuto da partida: posse de cada time e altura da linha de defesa."""
    if not len(table):
        return {"minutes": [], "possession": [], "line": [[], []]}
    minutes = np.floor(table[:, col["t"]] / 60).astype(int)
    last = int(minutes.max())
    out_min, out_poss, out_line = [], [], [[], []]
    for m in range(0, last + 1):
        rows = table[minutes == m]
        out_min.append(m + 1)
        if not len(rows):
            out_poss.append(None)
            out_line[0].append(None)
            out_line[1].append(None)
            continue
        w = rows[:, col["dt"]]
        share = _share(w, rows[:, col["poss"]])
        out_poss.append(share)
        for t in (0, 1):
            out_line[t].append(_wmean(rows[:, col[f"line{t}"]], w))
    return {"minutes": out_min, "possession": out_poss, "line": out_line}
