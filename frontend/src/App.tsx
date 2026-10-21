import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BackendClient,
  type BenchmarkMessage,
  type ConnStatus,
  type DetectionsMessage,
  type PatternOption,
  type PatternsInfo,
  type PatternTransition,
  type MatchStats,
  type InsightsInfo,
  type TeamPattern,
  type StatusMessage,
} from "./backend";
import { chooseTab, FrameSender, type SenderCounters } from "./capture";
import { DetectionOverlay, ROLE_COLORS, teamColors } from "./DetectionOverlay";
import { InsightsPanel, type InsightCommand } from "./InsightsPanel";
import { MatchPanel, formatBytes, type Command } from "./MatchPanel";
import { TacticsPanel } from "./TacticsPanel";
import { FlowPitch, type FlowLayer } from "./FlowPitch";
import { PatternField3D, SECTOR_COLORS, type CameraMode, type FieldArrow, type FieldEnds, type PatternLayer } from "./PatternField3D";
import { RollingStats, type LiveStats } from "./stats";

const INTERVALS = [100, 125, 150, 175, 200];
/** Momentos que uma fase precisa para o campinho de movimentação (três etapas de 30, igual ao backend). */
const FLOW_MIN_FRAMES = 90;
const EMPTY_STATS: LiveStats = { fps: 0, latencyMeanMs: null, latencyP95Ms: null, inferMs: null, serverMs: null };
const EMPTY_COUNTERS: SenderCounters = { sent: 0, skipped: 0, lost: 0 };
interface ViewPart {
  /** chave do padrão no backend: "<time>-<fase>" */
  option: string;
  team: 0 | 1;
  /** gira o padrão para o outro lado do campo (o time que defende) */
  mirror: boolean;
  /** só marcas no chão (posições de defesa na opção defesa → ataque) */
  ghost?: boolean;
}

interface View {
  key: string;
  title: string;
  parts: ViewPart[];
  /** quem ataca nos momentos mostrados (sai do gol da esquerda) */
  attacker: 0 | 1;
  /** defesa → ataque de um time */
  transition?: 0 | 1;
}

type Names = [string, string];

/** As opções do campo, com os nomes dos times (siglas do placar ou "Time A"/"Time B"). */
function buildViews(names: Names): View[] {
  const [a, b] = names;
  // Em todas as opções o ataque vai da esquerda para a direita: quem defende fica girado, protegendo o gol da direita.
  return [
    { key: "0-ataque", title: `${a} ataca`, attacker: 0, parts: [{ option: "0-ataque", team: 0, mirror: false }] },
    { key: "0-defesa", title: `${a} defende`, attacker: 1, parts: [{ option: "0-defesa", team: 0, mirror: true }] },
    { key: "1-ataque", title: `${b} ataca`, attacker: 1, parts: [{ option: "1-ataque", team: 1, mirror: false }] },
    { key: "1-defesa", title: `${b} defende`, attacker: 0, parts: [{ option: "1-defesa", team: 1, mirror: true }] },
    {
      key: "A-x-B",
      title: `${a} ataca × ${b} defende`,
      attacker: 0,
      parts: [
        { option: "0-ataque", team: 0, mirror: false },
        { option: "1-defesa", team: 1, mirror: true },
      ],
    },
    {
      key: "B-x-A",
      title: `${b} ataca × ${a} defende`,
      attacker: 1,
      parts: [
        { option: "1-ataque", team: 1, mirror: false },
        { option: "0-defesa", team: 0, mirror: true },
      ],
    },
    ...([0, 1] as const).map((t) => ({
      key: `${t}-trans`,
      title: `${names[t]}: defesa → ataque`,
      attacker: t,
      transition: t,
      parts: [
        { option: `${t}-defesa`, team: t, mirror: false, ghost: true },
        { option: `${t}-ataque`, team: t, mirror: false },
      ],
    })),
  ];
}

const SECTOR_TEXT = { defesa: "na linha de defesa", meio: "no meio-campo", ataque: "no ataque" } as const;

function TransitionStats({ transition, name }: { transition: PatternTransition; name: string }) {
  const moves = [...transition.moves].sort((m1, m2) => m2.dx - m1.dx);
  return (
    <div className="transition">
      <ul className="highlights">
        {transition.highlights.map((h, i) => (
          <li key={i}>{h}</li>
        ))}
      </ul>
      <table className="compare moves">
        <caption className="muted small">
          Quanto cada posição do {name} se move quando o time passa da defesa para o ataque
        </caption>
        <thead>
          <tr>
            <th scope="col">Posição</th>
            <th scope="col">Avança</th>
            <th scope="col">Para o lado</th>
            <th scope="col">No ataque fica</th>
          </tr>
        </thead>
        <tbody>
          {moves.map((m, i) => (
            <tr key={i}>
              <th scope="row">{m.name}</th>
              <td>
                {m.dx >= 0 ? "+" : ""}
                {Math.round(m.dx)} m
              </td>
              <td>
                {Math.abs(m.dy) < 3 ? "—" : `${Math.round(Math.abs(m.dy))} m para a ${m.dy > 0 ? "direita" : "esquerda"}`}
              </td>
              <td>{m.attackSector ? SECTOR_TEXT[m.attackSector] : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function backLineText(option: PatternOption): string | null {
  const back = option.backLine;
  if (!back || back.total === 0) return null;
  const top = Object.entries(back.counts).sort((a, b) => b[1] - a[1])[0];
  return `${top[0]} atrás em ${Math.round((100 * top[1]) / back.total)}% de ${back.total} lances com a defesa toda na imagem`;
}

function PatternStats({
  option,
  pattern,
  heading,
  formations,
  onFormation,
}: {
  option: PatternOption;
  pattern: TeamPattern;
  heading?: string;
  formations: string[];
  onFormation: (formation: string | null) => void;
}) {
  const counted = backLineText(option);
  const source =
    pattern.formationSource === "manual"
      ? "escolhida por você"
      : pattern.formationSource === "linha"
        ? `pela linha de defesa: ${counted}`
        : counted
          ? `pelas posições médias (linha de defesa: ${counted}; ainda pouco para decidir)`
          : "pelas posições médias";
  return (
    <div className="stats-group">
      {heading && <p className="stats-heading">{heading}</p>}
      <div className="stats">
        <div className="stat formation-stat">
          <span className="muted small">Formação</span>
          <strong className="huge">{pattern.formation}</strong>
          <span className="muted small">{source}</span>
          <select
            aria-label="Corrigir a formação"
            value={option.override ?? ""}
            onChange={(e) => onFormation(e.target.value || null)}
          >
            <option value="">Automática</option>
            {formations.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
        <div className="stat">
          <span className="muted small">Linha de defesa</span>
          <strong>{Math.round(pattern.lineHeight)} m do próprio gol</strong>
          <span className="muted small">bloco {pattern.block}</span>
        </div>
        <div className="stat">
          <span className="muted small">Largura</span>
          <strong>{Math.round(pattern.width)} m</strong>
          <span className="muted small">de um lado ao outro</span>
        </div>
        <div className="stat">
          <span className="muted small">Profundidade</span>
          <strong>{Math.round(pattern.depth)} m</strong>
          <span className="muted small">da defesa ao ataque</span>
        </div>
        {option.phase === "ataque" && pattern.corridors && (
          <div className="stat">
            <span className="muted small">No último terço</span>
            <strong>
              {pattern.corridors.esquerda >= pattern.corridors.direita ? "mais pela esquerda" : "mais pela direita"}
            </strong>
            <span className="muted small">
              esq. {Math.round(pattern.corridors.esquerda * 100)}% · centro {Math.round(pattern.corridors.centro * 100)}% ·
              dir. {Math.round(pattern.corridors.direita * 100)}%
            </span>
          </div>
        )}
        <div className="stat">
          <span className="muted small">Base</span>
          <strong>{fmtDuration(option.seconds)}</strong>
          <span className="muted small">{option.frames} momentos analisados</span>
        </div>
      </div>
    </div>
  );
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s de jogo`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s de jogo`;
}

function fmt(value: number | null | undefined, unit = "ms"): string {
  return value === null || value === undefined ? "—" : `${Math.round(value)} ${unit}`;
}

export default function App() {
  const client = useMemo(() => new BackendClient(), []);
  const sendCommand = useCallback((command: Command | InsightCommand) => client.send(command), [client]);
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
  const [cameraMode, setCameraMode] = useState<CameraMode>("top");
  const [showHeat, setShowHeat] = useState(false);
  const [showRoles, setShowRoles] = useState(true);
  const [selected, setSelected] = useState<string>("0-ataque");
  const [patterns, setPatterns] = useState<PatternsInfo | null>(null);
  const [matchStats, setMatchStats] = useState<MatchStats | null>(null);
  const [insights, setInsights] = useState<InsightsInfo | null>(null);
  // Coluna dos insights larga ou estreita; lembrada neste navegador.
  const [insightsWide, setInsightsWide] = useState<boolean>(() => {
    try {
      return localStorage.getItem("fca-insights-wide") === "1";
    } catch {
      return false;
    }
  });
  const toggleInsightsWide = useCallback(() => {
    setInsightsWide((wide) => {
      try {
        localStorage.setItem("fca-insights-wide", wide ? "0" : "1");
      } catch {
        // sem armazenamento: só não lembra a escolha
      }
      return !wide;
    });
  }, []);
  const [showPitch, setShowPitch] = useState(true);
  const [autoCrop, setAutoCrop] = useState(true);

  useEffect(() => {
    const offStatus = client.onStatus(setConn);
    const offMessage = client.onMessage((msg) => {
      if (msg.type === "status") {
        setServer(msg);
        if (msg.patterns) setPatterns(msg.patterns);
        if (msg.stats) setMatchStats(msg.stats);
        if (msg.insights) setInsights(msg.insights);
      }
      if (msg.type === "insights") setInsights(msg);
      if (msg.type === "patterns") setPatterns(msg);
      if (msg.type === "stats") setMatchStats(msg.stats);
      if (msg.type === "wiped") setNotice(`Dados apagados: ${formatBytes(msg.freedBytes)} liberados no disco.`);
      if (msg.type === "benchmark") setBenchmark(msg);
      if (msg.type === "error") setNotice(msg.detail);
      if (msg.type === "detections") {
        const mine = msg.conn === undefined || msg.conn === client.conn;
        if (mine) {
          // Resultado que chega depois de parar a captura é descartado.
          if (!senderRef.current) return;
          senderRef.current.ack(msg.frameId);
        }
        if (msg.stopCapture) {
          if (mine) {
            stopRef.current();
            setNotice(msg.error ?? "Outra aba começou a capturar.");
          }
          return;
        }
        if (msg.error) {
          if (mine) setNotice(`Erro na detecção: ${msg.error}`);
          return;
        }
        if (mine) {
          const now = performance.now();
          statsRef.current.add(now, now - msg.captureTs, msg.inferMs, msg.serverMs);
        }
        // Resultados de outra aba (captura numa janela, mapa em outra) também atualizam o mapa.
        setResult(msg);
        if (msg.patterns) setPatterns(msg.patterns);
        if (msg.stats) setMatchStats(msg.stats);
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

  const stopRef = useRef(stopCapture);
  stopRef.current = stopCapture;

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
    sender.setAutoCrop(autoCrop);
    senderRef.current = sender;
    statsRef.current.reset();
    sender.start();
    setCapturing(true);
  }, [autoCrop, client, intervalMs, stopCapture, video]);

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
  const field = result?.map ?? null;
  const pitchState = server?.pitch?.state;

  const names: Names = matchStats?.teamNames ?? ["Time A", "Time B"];
  const teamName = (team: 0 | 1) => names[team];
  const views = buildViews(names);
  const view = views.find((v) => v.key === selected) ?? views[0];
  const viewParts = view.parts.map((part) => ({ part, option: patterns?.options[part.option] ?? null }));
  const layers: PatternLayer[] = useMemo(
    () =>
      view.parts.map((part) => ({
        pattern: patterns?.options[part.option]?.pattern ?? null,
        color: colors[part.team],
        mirror: part.mirror,
        ghost: part.ghost,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view.key, patterns, colors],
  );
  const transition = view.transition !== undefined ? (patterns?.transitions?.[String(view.transition)] ?? null) : null;
  const arrows: FieldArrow[] = useMemo(
    () => (transition ? transition.moves.map((m) => ({ from: m.from, to: m.to })) : []),
    [transition],
  );
  const missing = viewParts.filter(({ option }) => !option?.pattern);
  const attacker = view.attacker;
  const defender: 0 | 1 = attacker === 0 ? 1 : 0;
  const ends: FieldEnds = useMemo(
    () => ({
      left: { label: `gol do ${names[attacker]}`, color: colors[attacker] },
      right: { label: `gol do ${names[defender]}`, color: colors[defender] },
      center:
        view.transition !== undefined
          ? `${names[attacker]}: anéis = defendendo  →  jogadores = atacando`
          : `${names[attacker]} ataca  →  ${names[defender]} defende`,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attacker, defender, colors, names[0], names[1], view.transition],
  );
  const duo = view.parts.length > 1 && view.transition === undefined;

  let fieldNote = "Aguardando a captura";
  if (pitchState === "baixando") fieldNote = "Baixando o modelo do campo (cerca de 140 MB, só na primeira vez)...";
  else if (pitchState === "carregando") fieldNote = "Carregando o modelo do campo...";
  else if (pitchState === "erro")
    fieldNote = `Modelo do campo indisponível (${server?.pitch?.error ?? "erro"}). Feche e abra o app para tentar de novo.`;
  else if (field?.scene === "ao vivo") fieldNote = "Coletando: jogo em tomada aberta";
  else if (field?.scene === "close") fieldNote = "Pausado: close ou replay";
  else if (field?.scene === "sem campo") fieldNote = "Pausado: campo não identificado na imagem";

  const source = patterns?.phaseSource;
  const sourceTotal = source ? source.bola + source["avanço"] + source["sem fase"] : 0;
  const pct = (v: number) => (sourceTotal ? Math.round((100 * v) / sourceTotal) : 0);

  // Campinho de movimentação: as partes da opção escolhida (na defesa → ataque, só o ataque).
  const flowParts = view.parts
    .filter((part) => !part.ghost)
    .map((part) => ({ part, flow: patterns?.flows?.[part.option] ?? null, option: patterns?.options[part.option] ?? null }));
  const flowLayers: FlowLayer[] = flowParts.map(({ part, flow }) => ({
    flow,
    color: colors[part.team],
    mirror: part.mirror,
    name: names[part.team],
    arrows: part.option.endsWith("ataque") ? (patterns?.ballArrows?.[String(part.team)] ?? null) : null,
  }));
  const flowMissing = flowParts.filter(({ flow }) => !flow);
  const flowCard = (
    <section className="card flow-card">
      <div className="map-head">
        <h2>Movimentação: {view.transition !== undefined ? `como o ${names[view.transition]} ataca` : view.title}</h2>
      </div>
      <div className="flow-wrap">
        <FlowPitch layers={flowLayers} />
        {flowMissing.length > 0 && (
          <div className="map-empty">
            {flowMissing.map(({ part, option }) => (
              <p key={part.option}>
                Coletando: {option?.frames ?? 0} de {FLOW_MIN_FRAMES} momentos com o {teamName(part.team)}{" "}
                {part.option.endsWith("ataque") ? "atacando" : "defendendo"}.
              </p>
            ))}
            <p className="small">A movimentação aparece quando a fase tem momentos suficientes para dividir em três etapas.</p>
          </div>
        )}
      </div>
      <div className="flow-legend muted small">
        <span>As peças andam do começo ao fim da fase e recomeçam.</span>
        <span>
          <span className="bar pass" /> passes que mais se repetem
        </span>
        <span>
          <span className="bar ball" /> cruzamentos que mais se repetem
        </span>
        <span>o número na seta é quantas vezes aconteceu</span>
      </div>
      <div className={flowParts.length > 1 ? "stats-duo" : ""}>
        {flowParts.map(({ part, flow }) =>
          flow ? (
            <div key={part.option} className="flow-notes">
              <p className="stats-heading">
                <span className="swatch" style={{ background: colors[part.team] }} />
                {teamName(part.team)} {part.option.endsWith("ataque") ? "atacando" : "defendendo"}
              </p>
              <ol className="flow-stages">
                {flow.stages.map((stage) => (
                  <li key={stage.name}>
                    <strong>{stage.name}</strong>
                    <span className="muted small">
                      time a {Math.round(stage.height)} m do próprio gol · {stage.frames} momentos
                    </span>
                  </li>
                ))}
              </ol>
              <ul className="highlights">
                {flow.notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
      </div>
      <p className="muted small map-foot">
        Os momentos de cada fase são divididos em três etapas pela altura do time no campo
        {flowParts.some(({ part }) => part.option.endsWith("defesa")) ? " (na defesa: da pressão alta ao bloco baixo)" : ""}, e
        cada peça mostra onde aquela posição fica em cada etapa. Peças apagadas são posições que a câmera quase não mostrou
        naquela etapa. As setas só aparecem para passes repetidos 3 vezes ou mais (entre zonas diferentes do campo) e
        cruzamentos repetidos 2 vezes ou mais. Mesmo sentido do campo de cima: o ataque vai da esquerda para a direita.
      </p>
    </section>
  );

  const patternCard = (
    <section className="card map-card">
      <div className="map-head">
        <h2>Padrões dos times</h2>
        <div className="map-controls">
          <div className="seg">
            <button className={cameraMode === "top" ? "on" : ""} onClick={() => setCameraMode("top")}>
              Vista de cima
            </button>
            <button className={cameraMode === "3d" ? "on" : ""} onClick={() => setCameraMode("3d")}>
              Vista 3D
            </button>
          </div>
          <label className="check">
            <input type="checkbox" checked={showRoles} onChange={(e) => setShowRoles(e.target.checked)} />
            Posições
          </label>
          <label className="check">
            <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} />
            Mapa de calor
          </label>
          <button className="link" onClick={() => client.send({ type: "reset_patterns" })}>
            Zerar padrões
          </button>
        </div>
      </div>

      <div className="options" role="tablist">
        {views.map((v) => {
          const opts = v.parts.map((part) => patterns?.options[part.option]);
          const progress = Math.min(...opts.map((o) => (o ? Math.min(1, o.frames / o.needed) : 0)));
          const done = opts.every((o) => o?.pattern);
          return (
            <button
              key={v.key}
              role="tab"
              aria-selected={selected === v.key}
              className={`option ${selected === v.key ? "on" : ""}`}
              onClick={() => setSelected(v.key)}
            >
              <span className="swatches">
                {v.parts.map((part) => (
                  <span key={part.option} className="swatch big" style={{ background: colors[part.team] }} />
                ))}
              </span>
              <span className="option-text">
                <strong>{v.title}</strong>
                <span className="muted small">
                  {!done
                    ? `coletando ${Math.round(progress * 100)}%`
                    : v.transition !== undefined
                      ? opts.map((o) => o!.pattern!.formation).join(" → ")
                      : opts.map((o) => o!.pattern!.formation).join(" × ")}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="map-wrap">
        <PatternField3D
          layers={layers}
          mode={cameraMode}
          showHeat={showHeat}
          ends={ends}
          showRoles={showRoles}
          arrows={arrows}
        />
        <div className="legend">
          {view.transition !== undefined ? (
            <span>
              <span className="swatch" style={{ background: colors[view.transition] }} />
              {teamName(view.transition)}: ○ defendendo → atacando
            </span>
          ) : (
            view.parts.map((part) => (
              <span key={part.option}>
                <span className="swatch" style={{ background: colors[part.team] }} />
                {teamName(part.team)} {part.mirror ? "defendendo o gol da direita" : "atacando →"}
              </span>
            ))
          )}
        </div>
        <div className="legend sectors">
          {(Object.entries(SECTOR_COLORS) as [string, string][]).map(([name, color]) => (
            <span key={name}>
              <span className="bar" style={{ background: color }} />
              {name}
            </span>
          ))}
        </div>
        <div className="scene-badge">
          <span className="dot" />
          {fieldNote}
        </div>
        {missing.length > 0 && (
          <div className="map-empty">
            {patterns ? (
              missing.map(({ part, option }) => (
                <p key={part.option}>
                  Coletando dados: {option?.frames ?? 0} de {option?.needed ?? 40} momentos com o {teamName(part.team)}{" "}
                  {part.option.endsWith("ataque") ? "atacando" : "defendendo"}.
                </p>
              ))
            ) : (
              <p>Os padrões aparecem depois de alguns minutos de jogo analisado.</p>
            )}
            <p className="small">O padrão só usa as tomadas abertas, com o campo identificado.</p>
          </div>
        )}
      </div>

      {missing.length === 0 && view.transition !== undefined && transition && (
        <TransitionStats transition={transition} name={teamName(view.transition)} />
      )}

      {missing.length === 0 && view.transition === undefined && (
        <div className={duo ? "stats-duo" : ""}>
          {viewParts.map(({ part, option }) => (
            <PatternStats
              key={part.option}
              option={option!}
              pattern={option!.pattern!}
              formations={patterns?.formationOptions ?? []}
              onFormation={(formation) =>
                client.send({ type: "set_formation", team: part.team, phase: option!.phase, formation })
              }
              heading={duo ? `${teamName(part.team)} ${part.mirror ? "defendendo" : "atacando"}` : undefined}
            />
          ))}
        </div>
      )}

      <p className="muted small map-foot">
        O ataque vai sempre da esquerda para a direita: o gol da esquerda é de quem ataca e o da direita é de quem
        defende (as faixas atrás dos gols têm a cor do dono). Nos números, esquerda e direita são do ponto de vista
        de cada time.{" "}
        {duo && "Os dois padrões vêm dos mesmos momentos do jogo. "}
        Cada jogador é uma posição média do time naquela fase. A câmera da TV não mostra o campo
        inteiro, então é uma aproximação que melhora com mais minutos de jogo.
        {sourceTotal > 0 && (
          <>
            {" "}
            Quem ataca foi decidido pela bola em {pct(source!.bola)}% dos momentos e pelo avanço dos times em{" "}
            {pct(source!["avanço"])}%.
          </>
        )}
      </p>
    </section>
  );

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>FC Analytics</h1>
          <p className="subtitle">Padrões de ataque e defesa</p>
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
          <label className="check">
            <input type="checkbox" checked={showPitch} onChange={(e) => setShowPitch(e.target.checked)} />
            Linhas do campo
          </label>
          <label className="check" title="Analisa só a área do vídeo dentro da aba, ignorando o resto da página">
            <input
              type="checkbox"
              checked={autoCrop}
              onChange={(e) => {
                setAutoCrop(e.target.checked);
                senderRef.current?.setAutoCrop(e.target.checked);
              }}
            />
            Recorte automático
          </label>
        </div>
      </header>

      {(notice || busyText) && <div className={`banner ${server?.state === "erro" ? "bad" : ""}`}>{notice ?? busyText}</div>}

      <main className={`layout ${insightsWide ? "wide-insights" : ""}`}>
        <div className="main-col">
        {patternCard}
        {flowCard}
        <TacticsPanel tactics={patterns?.tactics} names={names} colors={colors} />
        <MatchPanel stats={matchStats} colors={colors} send={sendCommand} />
        <section className="stage">
          <video ref={setVideo} muted playsInline className="video" />
          <DetectionOverlay
            video={video}
            result={result}
            showLabels={showLabels}
            showPitch={showPitch}
            crop={result && result.conn === client.conn ? (senderRef.current?.cropFor(result.frameId) ?? null) : null}
          />
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
        </div>

        <aside className="panel">
          <InsightsPanel
            info={insights}
            colors={colors}
            names={names}
            send={sendCommand}
            wide={insightsWide}
            onToggleWide={toggleInsightsWide}
          />
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
              <dt>Campo (pontos-chave)</dt>
              <dd>{fmt(result?.pitchMs)}</dd>
              <dt>Tracking, times e mapa</dt>
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
              IDs estáveis aparecem como vida média alta e poucos IDs novos por minuto. A cada corte de câmera o
              tracking recomeça, por isso os IDs mudam depois de replays e closes.
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
