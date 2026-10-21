import { useEffect, useMemo, useState } from "react";
import type { MatchEvent, MatchEventKind, MatchStats, WindowStats } from "./backend";
import { EChart, chartTheme, type ChartOption } from "./EChart";

type WindowKey = "recentes" | "partida";
type Team = 0 | 1;

const TEAM_NAMES = ["Time A", "Time B"] as const;

const EVENT_LABELS: Record<MatchEventKind, string> = {
  gol: "Gol",
  amarelo: "Cartão amarelo",
  vermelho: "Cartão vermelho",
  substituicao: "Substituição",
  intervalo: "Intervalo",
};

const SHORT_LABELS: Record<MatchEventKind, string> = {
  gol: "Gol",
  amarelo: "Amarelo",
  vermelho: "Vermelho",
  substituicao: "Subst.",
  intervalo: "Intervalo",
};

/** Atalhos: a tecla marca para o Time A; com Shift, para o Time B. */
const TEAM_KEYS: Record<string, Exclude<MatchEventKind, "intervalo">> = {
  KeyG: "gol",
  KeyC: "amarelo",
  KeyV: "vermelho",
  KeyS: "substituicao",
};
const KEY_HINT: Record<Exclude<MatchEventKind, "intervalo">, string> = {
  gol: "G",
  amarelo: "C",
  vermelho: "V",
  substituicao: "S",
};

export type Command =
  | { type: "event"; kind: MatchEventKind; team: Team | null }
  | { type: "undo_event" }
  | { type: "new_match" };

interface Props {
  stats: MatchStats | null;
  colors: [string, string];
  send: (command: Command) => void;
}

function minuteOf(t: number): number {
  return Math.floor(t / 60) + 1;
}

function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function describe(event: MatchEvent, breaksBefore: number): string {
  if (event.kind === "intervalo") return breaksBefore % 2 === 0 ? "Intervalo" : "Começo do 2º tempo";
  return `${EVENT_LABELS[event.kind]} do ${TEAM_NAMES[event.team ?? 0]}`;
}

function useDarkMode(): boolean {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setDark(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return dark;
}

// ---------------------------------------------------------------------------
// Linhas da tabela de comparação
// ---------------------------------------------------------------------------

const num = (v: number | null | undefined, unit = "", digits = 0) =>
  v === null || v === undefined ? "—" : `${v.toLocaleString("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: digits })}${unit}`;

function SplitBar({ values }: { values: [number, number] }) {
  return (
    <div className="split" aria-hidden="true">
      <span style={{ width: `${values[0]}%`, background: "var(--series-a)" }} />
      <span style={{ width: `${values[1]}%`, background: "var(--series-b)" }} />
    </div>
  );
}

const CORRIDOR_NAMES = ["esquerda", "centro", "direita"];

function corridorText(values: number[] | null): string {
  if (!values) return "—";
  const best = values.indexOf(Math.max(...values));
  return `${CORRIDOR_NAMES[best]} (${num(values[best], "%")})`;
}

interface Row {
  label: string;
  hint: string;
  values: [string, string];
  split?: [number, number] | null;
}

function rowsFor(w: WindowStats): Row[] {
  return [
    {
      label: "Posse de bola",
      hint: "Time do jogador mais perto da bola (até 4 m)",
      values: [num(w.possession?.[0], "%"), num(w.possession?.[1], "%")],
      split: w.possession,
    },
    {
      label: "Domínio territorial",
      hint: "Tempo com a bola no terço ofensivo de cada time",
      values: [num(w.tilt?.[0], "%"), num(w.tilt?.[1], "%")],
      split: w.tilt,
    },
    {
      label: "Passes aproximados",
      hint: "Bola trocando entre jogadores do mesmo time; entre parênteses, a precisão",
      values: [0, 1].map((t) =>
        w.passAccuracy[t] === null ? String(w.passes[t]) : `${w.passes[t]} (${num(w.passAccuracy[t], "%")})`,
      ) as [string, string],
    },
    {
      label: "Perdas de bola",
      hint: "Bola que passou direto para o adversário",
      values: [String(w.losses[0]), String(w.losses[1])],
    },
    {
      label: "Pressão pós-perda",
      hint: "Jogadores a menos de 5 m da bola nos 5 s depois de perder; entre parênteses, quantas vezes recuperou nesse tempo",
      values: [0, 1].map((t) =>
        w.pressure[t] === null ? "—" : `${num(w.pressure[t], "", 1)} jog. (${num(w.recoveries5s[t], "%")})`,
      ) as [string, string],
    },
    {
      label: "Linha de defesa",
      hint: "Distância média dos defensores mais recuados até o próprio gol",
      values: [num(w.line[0], " m"), num(w.line[1], " m")],
    },
    {
      label: "Compactação",
      hint: "Distância entre o jogador mais recuado e o mais avançado (sem o goleiro)",
      values: [num(w.depth[0], " m"), num(w.depth[1], " m")],
    },
    {
      label: "Largura",
      hint: "Distância entre os jogadores mais abertos de cada lado",
      values: [num(w.width[0], " m"), num(w.width[1], " m")],
    },
    {
      label: "Corredor no ataque",
      hint: "Por onde a bola anda quando o time tem a posse (esquerda e direita do ponto de vista do time)",
      values: [corridorText(w.corridors[0]), corridorText(w.corridors[1])],
    },
    {
      label: "Distância vista",
      hint: "Soma do que os jogadores correram enquanto apareciam na imagem; fica bem abaixo do real",
      values: [num(w.distanceKm[0], " km", 1), num(w.distanceKm[1], " km", 1)],
    },
  ];
}

// ---------------------------------------------------------------------------
// Gráficos
// ---------------------------------------------------------------------------

function eventMarks(events: MatchEvent[], muted: string) {
  let breaks = 0;
  return events
    .filter((e) => e.kind !== "substituicao")
    .map((e) => {
      const text =
        e.kind === "intervalo"
          ? breaks++ % 2 === 0
            ? "Intervalo"
            : "2º tempo"
          : `${SHORT_LABELS[e.kind]} ${e.team === 0 ? "A" : "B"}`;
      return {
        xAxis: String(minuteOf(e.t)),
        label: { formatter: text, color: muted, fontSize: 11 },
        lineStyle: { color: muted, type: "dashed" as const, width: 1 },
      };
    });
}

type Theme = ReturnType<typeof chartTheme>;

/** Tooltip com o minuto no topo e o valor de cada time (valor em destaque, nome do time depois). */
function tooltipFormatter(unit: string) {
  return (params: unknown) => {
    const items = params as { name: string; seriesName: string; value: number | null; marker: string }[];
    if (!items.length) return "";
    const rows = items
      .map(
        (p) =>
          `${p.marker}<b>${typeof p.value === "number" ? `${p.value.toFixed(0)}${unit}` : "sem dado"}</b> ${p.seriesName}`,
      )
      .join("<br/>");
    return `Minuto ${items[0].name}<br/>${rows}`;
  };
}

function baseOption(theme: Theme, minutes: number[], unit: string): ChartOption {
  return {
    animation: false,
    textStyle: { fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif" },
    grid: { left: 44, right: 16, top: 36, bottom: 30 },
    legend: {
      top: 0,
      left: 0,
      textStyle: { color: theme.text, fontSize: 12 },
      itemWidth: 14,
      itemHeight: 8,
    },
    xAxis: {
      type: "category",
      data: minutes.map(String),
      name: "min",
      nameLocation: "end",
      nameTextStyle: { color: theme.muted, fontSize: 11 },
      axisLine: { lineStyle: { color: theme.grid } },
      axisTick: { show: false },
      axisLabel: { color: theme.muted, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: theme.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.grid,
      textStyle: { color: theme.text, fontSize: 12 },
      formatter: tooltipFormatter(unit),
    },
  };
}

function possessionOption(stats: MatchStats, theme: Theme): ChartOption {
  const { minutes, possession } = stats.timeline;
  const base = baseOption(theme, minutes, "%");
  return {
    ...base,
    yAxis: { ...(base.yAxis as object), max: 100, interval: 25 },
    tooltip: { ...(base.tooltip as object), axisPointer: { type: "shadow" } },
    series: [0, 1].map((t) => ({
      name: TEAM_NAMES[t],
      type: "bar",
      stack: "posse",
      barMaxWidth: 18,
      data: possession.map((p) => (p ? p[t] : null)),
      itemStyle: {
        color: t === 0 ? theme.teamA : theme.teamB,
        borderColor: theme.surface,
        borderWidth: 1,
        borderRadius: t === 1 ? [4, 4, 0, 0] : 0,
      },
      ...(t === 0 ? { markLine: { symbol: "none", silent: true, data: eventMarks(stats.events, theme.muted) } } : {}),
    })),
  };
}

function lineOption(stats: MatchStats, theme: Theme): ChartOption {
  const { minutes, line } = stats.timeline;
  const base = baseOption(theme, minutes, " m");
  return {
    ...base,
    yAxis: { ...(base.yAxis as object), min: 0 },
    tooltip: { ...(base.tooltip as object), axisPointer: { type: "line", lineStyle: { color: theme.muted } } },
    series: [0, 1].map((t) => ({
      name: TEAM_NAMES[t],
      type: "line",
      data: line[t],
      showSymbol: minutes.length < 3,
      symbolSize: 8,
      lineStyle: { width: 2, color: t === 0 ? theme.teamA : theme.teamB },
      itemStyle: { color: t === 0 ? theme.teamA : theme.teamB },
      ...(t === 0 ? { markLine: { symbol: "none", silent: true, data: eventMarks(stats.events, theme.muted) } } : {}),
    })),
  };
}

// ---------------------------------------------------------------------------
// Painel
// ---------------------------------------------------------------------------

export function MatchPanel({ stats, colors, send }: Props) {
  const [windowKey, setWindowKey] = useState<WindowKey>("recentes");
  const [confirmNew, setConfirmNew] = useState(false);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const dark = useDarkMode();

  const paused = stats?.paused ?? false;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName))) return;
      const kind = TEAM_KEYS[e.code];
      if (kind) {
        const team: Team = e.shiftKey ? 1 : 0;
        send({ type: "event", kind, team });
        setLastAction(`${EVENT_LABELS[kind]} do ${TEAM_NAMES[team]} marcado. Z desfaz.`);
      } else if (e.code === "KeyI") {
        send({ type: "event", kind: "intervalo", team: null });
        setLastAction(paused ? "Começo do 2º tempo marcado. Z desfaz." : "Intervalo marcado: a coleta pausa até o 2º tempo.");
      } else if (e.code === "KeyZ") {
        send({ type: "undo_event" });
        setLastAction("Último evento desfeito.");
      } else {
        return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [send, paused]);

  useEffect(() => {
    if (!confirmNew) return;
    const timer = window.setTimeout(() => setConfirmNew(false), 4000);
    return () => window.clearTimeout(timer);
  }, [confirmNew]);

  const theme = useMemo(() => chartTheme(), [dark]); // eslint-disable-line react-hooks/exhaustive-deps
  const possession = useMemo(() => (stats ? possessionOption(stats, theme) : null), [stats, theme]);
  const lines = useMemo(() => (stats ? lineOption(stats, theme) : null), [stats, theme]);

  const mark = (kind: MatchEventKind, team: Team | null) => {
    send({ type: "event", kind, team });
    setLastAction(
      kind === "intervalo"
        ? paused
          ? "Começo do 2º tempo marcado."
          : "Intervalo marcado: a coleta pausa até o 2º tempo."
        : `${EVENT_LABELS[kind]} do ${TEAM_NAMES[team ?? 0]} marcado.`,
    );
  };

  const w = stats?.windows[windowKey] ?? null;
  const hasData = !!w && w.seconds > 0;
  let breaks = 0;
  const timeline = (stats?.events ?? []).map((e) => {
    const text = describe(e, breaks);
    if (e.kind === "intervalo") breaks++;
    return { ...e, text };
  });

  return (
    <section className="card match-card">
      <div className="map-head">
        <h2>Estatísticas da partida</h2>
        <div className="map-controls">
          <div className="seg" role="tablist" aria-label="Janela de tempo">
            <button className={windowKey === "recentes" ? "on" : ""} onClick={() => setWindowKey("recentes")}>
              Últimos 5 min
            </button>
            <button className={windowKey === "partida" ? "on" : ""} onClick={() => setWindowKey("partida")}>
              Partida inteira
            </button>
          </div>
          <button
            className={`link ${confirmNew ? "danger" : ""}`}
            onClick={() => {
              if (!confirmNew) return setConfirmNew(true);
              setConfirmNew(false);
              send({ type: "new_match" });
              setLastAction("Partida nova começada: estatísticas, eventos e padrões zerados.");
            }}
          >
            {confirmNew ? "Clique de novo para zerar tudo" : "Nova partida"}
          </button>
        </div>
      </div>

      <div className="scoreline">
        <div className="score">
          <span className="score-team">
            <span className="swatch big" style={{ background: colors[0] }} />
            Time A
          </span>
          <strong className="score-num">
            {stats?.score[0] ?? 0} × {stats?.score[1] ?? 0}
          </strong>
          <span className="score-team">
            Time B
            <span className="swatch big" style={{ background: colors[1] }} />
          </span>
        </div>
        <div className="muted small">
          {stats ? (
            <>
              {paused ? <span className="pill pill-conectando">Intervalo: coleta pausada</span> : `${stats.period}º tempo`} ·{" "}
              {formatClock(stats.elapsedS)} desde o começo no app
            </>
          ) : (
            "Aguardando o backend"
          )}
        </div>
      </div>

      <div className="events-bar">
        {[0, 1].map((t) => (
          <div key={t} className="events-team">
            <span className="muted small">{TEAM_NAMES[t]}</span>
            {(Object.keys(KEY_HINT) as (keyof typeof KEY_HINT)[]).map((kind) => (
              <button key={kind} className="btn small-btn ev" onClick={() => mark(kind, t as Team)}>
                {SHORT_LABELS[kind]}
                <kbd>{t === 1 ? `⇧${KEY_HINT[kind]}` : KEY_HINT[kind]}</kbd>
              </button>
            ))}
          </div>
        ))}
        <div className="events-team">
          <button className="btn small-btn ev" onClick={() => mark("intervalo", null)}>
            {paused ? "Começar 2º tempo" : "Intervalo"}
            <kbd>I</kbd>
          </button>
          <button
            className="btn small-btn ev"
            disabled={!stats?.events.length}
            onClick={() => {
              send({ type: "undo_event" });
              setLastAction("Último evento desfeito.");
            }}
          >
            Desfazer
            <kbd>Z</kbd>
          </button>
        </div>
      </div>
      <p className="muted small action-note" aria-live="polite">
        {lastAction ?? "Atalhos: a tecla marca para o Time A e, com Shift, para o Time B."}
      </p>

      {!hasData ? (
        <div className="stats-empty">
          <p>
            {windowKey === "recentes"
              ? "Sem jogo em tomada aberta nos últimos 5 minutos."
              : "As estatísticas aparecem quando o jogo é analisado em tomada aberta, com o campo identificado."}
          </p>
        </div>
      ) : (
        <>
          <table className="compare">
            <thead>
              <tr>
                <th scope="col">Métrica</th>
                <th scope="col">
                  <span className="team-head">
                    <span className="key-bar" style={{ background: "var(--series-a)" }} />
                    Time A
                  </span>
                </th>
                <th scope="col">
                  <span className="team-head">
                    <span className="key-bar" style={{ background: "var(--series-b)" }} />
                    Time B
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rowsFor(w).map((row) => (
                <tr key={row.label}>
                  <th scope="row" title={row.hint}>
                    {row.label}
                    {row.split && <SplitBar values={row.split} />}
                  </th>
                  <td>{row.values[0]}</td>
                  <td>{row.values[1]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Base: {formatClock(w.seconds)} de jogo em tomada aberta
            {w.possessionCoverage !== null && <> · posse identificada em {num(w.possessionCoverage, "%")} desse tempo</>}.
            Passe o mouse sobre o nome de cada métrica para ver como ela é calculada.
          </p>
        </>
      )}

      {stats && stats.timeline.minutes.length > 0 && possession && lines && (
        <div className="charts">
          <div>
            <h3>
              Posse por minuto <span className="muted">(%)</span>
            </h3>
            <EChart option={possession} label="Posse de bola de cada time por minuto" />
          </div>
          <div>
            <h3>
              Linha de defesa por minuto <span className="muted">(m do próprio gol)</span>
            </h3>
            <EChart option={lines} label="Altura da linha de defesa de cada time por minuto" />
          </div>
        </div>
      )}

      {timeline.length > 0 && (
        <div className="event-list">
          <h3>Eventos</h3>
          <ol>
            {[...timeline].reverse().map((e) => (
              <li key={e.id}>
                <span className="event-min">{minuteOf(e.t)}'</span>
                {e.team !== null && <span className="swatch" style={{ background: colors[e.team] }} />}
                {e.text}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
