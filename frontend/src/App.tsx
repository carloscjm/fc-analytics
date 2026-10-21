import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BackendClient,
  type BenchmarkMessage,
  type ConnStatus,
  type DetectionsMessage,
  type StatusMessage,
} from "./backend";
import { chooseTab, FrameSender, type SenderCounters } from "./capture";
import { DetectionOverlay, ROLE_COLORS, teamColors } from "./DetectionOverlay";
import { RollingStats, type LiveStats } from "./stats";

const INTERVALS = [100, 125, 150, 175, 200];
const EMPTY_STATS: LiveStats = { fps: 0, latencyMeanMs: null, latencyP95Ms: null, inferMs: null, serverMs: null };
const EMPTY_COUNTERS: SenderCounters = { sent: 0, skipped: 0, lost: 0 };

function fmt(value: number | null | undefined, unit = "ms"): string {
  return value === null || value === undefined ? "—" : `${Math.round(value)} ${unit}`;
}

export default function App() {
  const client = useMemo(() => new BackendClient(), []);
  const senderRef = useRef<FrameSender | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const statsRef = useRef(new RollingStats());

  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [conn, setConn] = useState<ConnStatus>(client.status);
  const [server, setServer] = useState<StatusMessage | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [intervalMs, setIntervalMs] = useState(150);
  const [showLabels, setShowLabels] = useState(true);
  const [result, setResult] = useState<DetectionsMessage | null>(null);
  const [stats, setStats] = useState<LiveStats>(EMPTY_STATS);
  const [counters, setCounters] = useState<SenderCounters>(EMPTY_COUNTERS);
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkMessage | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const offStatus = client.onStatus(setConn);
    const offMessage = client.onMessage((msg) => {
      if (msg.type === "status") setServer(msg);
      if (msg.type === "benchmark") setBenchmark(msg);
      if (msg.type === "error") setNotice(msg.detail);
      if (msg.type === "detections") {
        // Resultado que chega depois de parar a captura é descartado.
        if (!senderRef.current) return;
        senderRef.current.ack(msg.frameId);
        if (msg.error) {
          setNotice(`Erro na detecção: ${msg.error}`);
          return;
        }
        const now = performance.now();
        statsRef.current.add(now, now - msg.captureTs, msg.inferMs, msg.serverMs);
        setResult(msg);
      }
    });
    client.start();
    const refresh = window.setInterval(() => {
      setStats(statsRef.current.snapshot(performance.now()));
      setCounters({ ...(senderRef.current?.counters ?? EMPTY_COUNTERS) });
      setPingMs(client.pingMs);
    }, 250);
    return () => {
      offStatus();
      offMessage();
      window.clearInterval(refresh);
      client.stop();
    };
  }, [client]);

  const stopCapture = useCallback(() => {
    senderRef.current?.stop();
    senderRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (video) video.srcObject = null;
    statsRef.current.reset();
    setResult(null);
    setCapturing(false);
  }, [video]);

  const startCapture = useCallback(async () => {
    if (!video) return;
    setNotice(null);
    let stream: MediaStream;
    try {
      stream = await chooseTab();
    } catch (err) {
      const name = err instanceof DOMException ? err.name : "";
      setNotice(name === "NotAllowedError" ? "Compartilhamento cancelado." : `Não foi possível capturar: ${String(err)}`);
      return;
    }
    streamRef.current = stream;
    video.srcObject = stream;
    await video.play().catch(() => undefined);
    stream.getVideoTracks()[0]?.addEventListener("ended", () => stopCapture());

    // Captura nova: tracking, times e bola recomeçam do zero no backend.
    client.send({ type: "reset_session" });
    const sender = new FrameSender(stream, video, (data) => client.sendBinary(data), intervalMs);
    senderRef.current = sender;
    statsRef.current.reset();
    sender.start();
    setCapturing(true);
  }, [client, intervalMs, stopCapture, video]);

  useEffect(() => () => senderRef.current?.stop(), []);

  const changeInterval = (ms: number) => {
    setIntervalMs(ms);
    senderRef.current?.setInterval(ms);
  };

  const colors = teamColors(result);
  const counts = useMemo(() => {
    const out = new Map<string, { n: number; color: string }>();
    for (const box of result?.boxes ?? []) {
      const key = box.t === 0 || box.t === 1 ? `time ${box.t === 0 ? "A" : "B"}` : box.l;
      const color = box.t === 0 || box.t === 1 ? colors[box.t] : (ROLE_COLORS[box.l] ?? "#e5e7eb");
      const prev = out.get(key);
      out.set(key, { n: (prev?.n ?? 0) + 1, color });
    }
    return [...out.entries()].sort((a, b) => b[1].n - a[1].n);
  }, [result, colors]);
  const teams = result?.teams;
  const tracking = result?.tracking;

  const ready = conn === "conectado" && server?.state === "pronto";
  const busyText = server?.detail ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>FC Analytics</h1>
          <p className="subtitle">Fase 2 · tracking e times</p>
        </div>
        <div className="controls">
          {capturing ? (
            <button className="btn" onClick={stopCapture}>
              Parar captura
            </button>
          ) : (
            <button className="btn primary" onClick={startCapture} disabled={conn !== "conectado"}>
              Escolher aba
            </button>
          )}
          <label>
            Intervalo
            <select value={intervalMs} onChange={(e) => changeInterval(Number(e.target.value))}>
              {INTERVALS.map((ms) => (
                <option key={ms} value={ms}>
                  {ms} ms
                </option>
              ))}
            </select>
          </label>
          <label>
            Modelo
            <select
              value={server?.model ?? ""}
              disabled={!ready}
              onChange={(e) => client.send({ type: "set_model", name: e.target.value })}
            >
              {(server?.models ?? []).map((m) => (
                <option key={m} value={m}>
                  {m.replace(/\.pt$/, "")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Resolução
            <select
              value={server?.imgsz ?? 960}
              disabled={!ready}
              onChange={(e) => client.send({ type: "set_imgsz", imgsz: Number(e.target.value) })}
            >
              {(server?.imgszOptions ?? [640, 960, 1280]).map((s) => (
                <option key={s} value={s}>
                  {s} px
                </option>
              ))}
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />
            Rótulos
          </label>
        </div>
      </header>

      {(notice || busyText) && <div className={`banner ${server?.state === "erro" ? "bad" : ""}`}>{notice ?? busyText}</div>}

      <main className="layout">
        <section className="stage">
          <video ref={setVideo} muted playsInline className="video" />
          <DetectionOverlay video={video} result={result} showLabels={showLabels} />
          {!capturing && (
            <div className="placeholder">
              <p>Clique em <strong>Escolher aba</strong> e selecione a aba com o jogo.</p>
              <p className="small">
                Dica: abra esta página numa janela separada, ao lado do jogo. Assim você vê as caixas enquanto assiste.
              </p>
              <p className="small">
                No YouTube, deixe o vídeo em modo teatro (tecla T) ou tela cheia (tecla F). Com os jogadores maiores na
                captura, a detecção, o tracking e os times ficam bem melhores.
              </p>
            </div>
          )}
        </section>

        <aside className="panel">
          <section className="card">
            <h2>Desempenho</h2>
            <dl>
              <dt>Fps de análise</dt>
              <dd className="big">{stats.fps.toFixed(1)}</dd>
              <dt>Atraso médio</dt>
              <dd>{fmt(stats.latencyMeanMs)}</dd>
              <dt>Atraso p95</dt>
              <dd>{fmt(stats.latencyP95Ms)}</dd>
              <dt>Inferência</dt>
              <dd>{fmt(stats.inferMs)}</dd>
              <dt>Tracking e times</dt>
              <dd>{fmt(result?.trackMs)}</dd>
              <dt>Tempo no backend</dt>
              <dd>{fmt(stats.serverMs)}</dd>
              <dt>Rede (ping)</dt>
              <dd>{fmt(pingMs)}</dd>
              <dt>Frames enviados</dt>
              <dd>{counters.sent}</dd>
              <dt>Pulados (fila)</dt>
              <dd>{counters.skipped}</dd>
            </dl>
          </section>

          <section className="card">
            <h2>Último frame</h2>
            {counts.length ? (
              <ul className="counts">
                {counts.map(([label, { n, color }]) => (
                  <li key={label}>
                    <span className="swatch" style={{ background: color }} />
                    {label}
                    <strong>{n}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Nenhuma detecção ainda.</p>
            )}
            {result?.width && (
              <p className="muted small">
                Frame {result.width}×{result.height} · {result.model?.replace(/\.pt$/, "")} · {result.imgsz} px
              </p>
            )}
          </section>

          <section className="card">
            <h2>Times</h2>
            {!teams ? (
              <p className="muted small">Começa a calibrar quando a captura ligar.</p>
            ) : teams.state === "calibrando" ? (
              <>
                <p className="small">
                  Calibrando pelas cores dos uniformes... {Math.round(teams.progress * 100)}%
                </p>
                <div className="progress">
                  <div style={{ width: `${Math.round(teams.progress * 100)}%` }} />
                </div>
                <p className="muted small">
                  Usa só as tomadas abertas, com os dois times em campo. Closes e replays não contam.
                </p>
              </>
            ) : (
              <ul className="counts">
                {[0, 1].map((t) => (
                  <li key={t}>
                    <span className="swatch big" style={{ background: colors[t] }} />
                    Time {t === 0 ? "A" : "B"}
                    <strong>{teams.counts[t === 0 ? "0" : "1"]} em campo</strong>
                  </li>
                ))}
              </ul>
            )}
            {teams?.recalibrations ? (
              <p className="muted small">Recalibrado {teams.recalibrations} vez(es) nesta captura.</p>
            ) : null}
            <button
              className="btn small-btn"
              disabled={!capturing}
              onClick={() => client.send({ type: "recalibrate_teams" })}
            >
              Recalibrar times
            </button>
          </section>

          <section className="card">
            <h2>Tracking</h2>
            <dl>
              <dt>IDs ativos</dt>
              <dd>{tracking?.active ?? "—"}</dd>
              <dt>Novos IDs no último minuto</dt>
              <dd>{tracking?.newLastMinute ?? "—"}</dd>
              <dt>Vida média de um ID</dt>
              <dd>{tracking?.avgLifeS === null || tracking?.avgLifeS === undefined ? "—" : `${tracking.avgLifeS} s`}</dd>
            </dl>
            <p className="muted small">
              IDs estáveis aparecem como vida média alta e poucos IDs novos por minuto. Cortes de câmera e replays
              geram IDs novos; isso é tratado na Fase 3.
            </p>
          </section>

          <section className="card">
            <h2>Conexão</h2>
            <dl>
              <dt>Backend</dt>
              <dd>
                <span className={`pill pill-${conn}`}>{conn}</span>
              </dd>
              <dt>Dispositivo</dt>
              <dd>{server?.device ?? "—"}</dd>
            </dl>
          </section>

          <section className="card">
            <h2>Modelo de futebol (opcional)</h2>
            {server?.footballModel ? (
              <p className="small">
                Instalado. Escolha <strong>football-player-detection</strong> em Modelo para separar jogador, goleiro,
                árbitro e bola direto na detecção.
              </p>
            ) : (
              <>
                <p className="muted small">
                  Modelo YOLOv8x treinado em transmissões de futebol pelo projeto roboflow/sports. Reconhece goleiro e
                  árbitro separadamente e costuma achar melhor a bola. Gratuito (AGPL-3.0), cerca de 130 MB, baixado do
                  Google Drive indicado no próprio projeto.
                </p>
                <button
                  className="btn small-btn"
                  disabled={!ready}
                  onClick={() => client.send({ type: "download_football_model" })}
                >
                  Baixar modelo de futebol
                </button>
              </>
            )}
          </section>

          <section className="card">
            <h2>Escolher o tamanho do modelo</h2>
            <p className="muted small">
              Mede cada tamanho do YOLO26 na sua placa. Com a captura ligada, usa frames reais do jogo. Na primeira vez,
              baixa os modelos que faltam (cerca de 200 MB no total).
            </p>
            <button
              className="btn"
              disabled={!ready}
              onClick={() => {
                setBenchmark(null);
                client.send({ type: "benchmark" });
              }}
            >
              {server?.state === "medindo" ? "Medindo..." : "Medir modelos"}
            </button>
            {benchmark && (
              <>
                <table className="bench">
                  <thead>
                    <tr>
                      <th>Modelo</th>
                      <th>Média</th>
                      <th>p95</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {benchmark.rows.map((row) => (
                      <tr key={row.model} className={row.model === benchmark.recommended ? "rec" : ""}>
                        <td>{row.model.replace(/\.pt$/, "")}</td>
                        {row.error ? (
                          <td colSpan={3} className="bad">
                            {row.error}
                          </td>
                        ) : (
                          <>
                            <td>{fmt(row.meanMs)}</td>
                            <td className={row.p95Ms! <= benchmark.budgetMs ? "" : "bad"}>{fmt(row.p95Ms)}</td>
                            <td>
                              <button
                                className="link"
                                disabled={server?.model === row.model}
                                onClick={() => client.send({ type: "set_model", name: row.model })}
                              >
                                {server?.model === row.model ? "em uso" : "usar"}
                              </button>
                            </td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="small">
                  {benchmark.recommended ? (
                    <>
                      Recomendado: <strong>{benchmark.recommended.replace(/\.pt$/, "")}</strong>, o maior que fica abaixo
                      de {benchmark.budgetMs} ms (p95) em {benchmark.imgsz} px. Isso deixa folga para o tracking e o campo
                      das próximas fases.
                    </>
                  ) : (
                    <>Nenhum modelo ficou abaixo de {benchmark.budgetMs} ms. Tente a resolução 640 px.</>
                  )}
                </p>
                <p className="muted small">
                  {benchmark.device} · {benchmark.frames} frame(s) de amostra
                </p>
              </>
            )}
          </section>
        </aside>
      </main>
    </div>
  );
}
