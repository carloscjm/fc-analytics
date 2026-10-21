import type { FlowRole, PlaysInfo, TeamFlow } from "./backend";
import { LENGTH, PENALTY_SPOTS, WIDTH, pitchLines } from "./pitch";
import { SECTOR_COLORS } from "./PatternField3D";

/** Um time no campinho de movimentação. `mirror` gira para o time defender o gol da direita. */
export interface FlowLayer {
  flow: TeamFlow | null;
  color: string;
  mirror: boolean;
  name: string;
  /** jogadas com a bola (só para quem ataca) */
  plays?: PlaysInfo | null;
}

const PAD = 5;
const LINES = pitchLines(16);
const MIN_MOVE_M = 2;
const ARROW_W = 2;

type P = [number, number];

function place(role: FlowRole, mirror: boolean): P {
  return mirror ? [LENGTH - role.x, WIDTH - role.y] : [role.x, role.y];
}

function sectorOf(line: number, last: number): keyof typeof SECTOR_COLORS {
  if (line === 0) return "defesa";
  return line === last ? "ataque" : "meio";
}

/** Curva suave pelas três etapas (passa pelo ponto do meio), terminando antes do jogador para a ponta da seta aparecer. */
function curve([a, b, c]: P[], trim: number): string {
  // Ponto de controle que faz a quadrática passar por b no meio do caminho.
  const cx = 2 * b[0] - (a[0] + c[0]) / 2;
  const cy = 2 * b[1] - (a[1] + c[1]) / 2;
  const dx = c[0] - cx;
  const dy = c[1] - cy;
  const len = Math.hypot(dx, dy) || 1;
  const k = Math.min(trim, len * 0.5) / len;
  const ex = c[0] - dx * k;
  const ey = c[1] - dy * k;
  return `M${a[0].toFixed(1)},${a[1].toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}`;
}

function markerId(color: string): string {
  return `flow-head-${color.replace(/[^a-z0-9]/gi, "")}`;
}

/** Linhas da formação numa etapa (defesa azul, meio amarelo, ataque vermelho). */
function Shape({ roles, mirror, faded }: { roles: FlowRole[]; mirror: boolean; faded: boolean }) {
  const last = Math.max(...roles.map((r) => r.line));
  const groups = new Map<number, P[]>();
  for (const r of roles) groups.set(r.line, [...(groups.get(r.line) ?? []), place(r, mirror)]);
  return (
    <g opacity={faded ? 0.35 : 0.85}>
      {[...groups.entries()].map(([line, pts]) =>
        pts.length < 2 ? null : (
          <polyline
            key={line}
            points={[...pts].sort((p, q) => p[1] - q[1]).map((p) => p.join(",")).join(" ")}
            fill="none"
            stroke={SECTOR_COLORS[sectorOf(line, last)]}
            strokeWidth={faded ? 0.3 : 0.4}
            strokeDasharray={faded ? "1.2 1" : undefined}
          />
        ),
      )}
    </g>
  );
}

interface Track {
  pts: P[];
  name: string;
  estimated: boolean;
}

function tracks(layer: FlowLayer): Track[] {
  const stages = layer.flow!.stages;
  const last = stages[stages.length - 1].roles;
  return last.map((role, j) => ({
    pts: stages.map((s) => place(s.roles[j], layer.mirror)),
    name: role.name,
    estimated: stages.some((s) => s.roles[j].estimated),
  }));
}

/** Setas grossas e translúcidas: do começo ao fim da fase, passando pelo meio. */
function TeamArrows({ layer }: { layer: FlowLayer }) {
  return (
    <g>
      {tracks(layer).map((t, j) => {
        const [a, , c] = t.pts;
        if (Math.hypot(c[0] - a[0], c[1] - a[1]) < MIN_MOVE_M) return null;
        return (
          <g key={j} opacity={t.estimated ? 0.22 : 0.5}>
            <path
              d={curve(t.pts, 2.9)}
              fill="none"
              stroke={layer.color}
              strokeWidth={ARROW_W}
              strokeLinecap="butt"
              strokeDasharray={t.estimated ? "2.4 1.6" : undefined}
              markerEnd={`url(#${markerId(layer.color)})`}
            />
          </g>
        );
      })}
    </g>
  );
}

/** Onde cada posição começa (anel) e termina (jogador com o nome). */
function TeamMarks({ layer, startShape }: { layer: FlowLayer; startShape: boolean }) {
  const stages = layer.flow!.stages;
  return (
    <g>
      {startShape && <Shape roles={stages[0].roles} mirror={layer.mirror} faded />}
      <Shape roles={stages[stages.length - 1].roles} mirror={layer.mirror} faded={false} />
      {tracks(layer).map((t, j) => (
        <g key={j} opacity={t.estimated ? 0.45 : 1}>
          <circle cx={t.pts[0][0]} cy={t.pts[0][1]} r={1.2} fill="none" stroke={layer.color} strokeWidth={0.4} opacity={0.6} />
          <circle cx={t.pts[2][0]} cy={t.pts[2][1]} r={1.8} fill={layer.color} stroke="#0b130d" strokeWidth={0.4} />
          {t.name && (
            <text x={t.pts[2][0]} y={t.pts[2][1] - 2.7} className="flow-label">
              {t.name}
            </text>
          )}
        </g>
      ))}
    </g>
  );
}

const BALL = "#fbbf24";

/** Jogadas com a bola de quem ataca (para a direita): cruzamentos por lado, entradas e chutes de fora. */
function Plays({ plays }: { plays: PlaysInfo }) {
  const c = plays.counts;
  const crossL = plays.bySide.cruzamento.esquerda;
  const crossR = plays.bySide.cruzamento.direita;
  const width = (n: number) => 1.2 + Math.min(1.6, n * 0.12);
  return (
    <g className="flow-plays">
      {crossL > 0 && (
        <g>
          <path opacity={0.5} d="M88,5 Q99,10 96,28" fill="none" stroke={BALL} strokeWidth={width(crossL)} markerEnd="url(#flow-head-ball)" />
          <text x={84} y={-1.6} className="flow-play-label">
            {crossL} cruz.
          </text>
        </g>
      )}
      {crossR > 0 && (
        <g>
          <path opacity={0.5} d="M88,63 Q99,58 96,40" fill="none" stroke={BALL} strokeWidth={width(crossR)} markerEnd="url(#flow-head-ball)" />
          <text x={84} y={71.2} className="flow-play-label">
            {crossR} cruz.
          </text>
        </g>
      )}
      {c.entrada > 0 && (
        <g>
          <path opacity={0.5} d="M80,31 L91,31" fill="none" stroke={BALL} strokeWidth={width(c.entrada)} markerEnd="url(#flow-head-ball)" />
          <text x={79} y={29.4} className="flow-play-label">
            {c.entrada} entradas
          </text>
        </g>
      )}
      {c.chute_fora > 0 && (
        <g>
          <path
            opacity={0.5}
            d="M80,38 L103,35"
            fill="none"
            stroke={BALL}
            strokeWidth={width(c.chute_fora)}
            strokeDasharray="1.6 1"
            markerEnd="url(#flow-head-ball)"
          />
          <text x={79} y={41.2} className="flow-play-label">
            {c.chute_fora} chutes de fora
          </text>
        </g>
      )}
    </g>
  );
}

/** Campinho só de leitura: como cada posição se move ao longo da fase (três etapas). */
export function FlowPitch({ layers }: { layers: FlowLayer[] }) {
  const shown = layers.filter((l) => l.flow);
  const colors = [...new Set(shown.map((l) => l.color))];
  return (
    <svg
      className="flow-pitch"
      viewBox={`${-PAD} ${-PAD} ${LENGTH + 2 * PAD} ${WIDTH + 2 * PAD}`}
      role="img"
      aria-label="Campinho com a movimentação de cada posição ao longo da fase"
    >
      <defs>
        {colors.map((color) => (
          <marker
            key={color}
            id={markerId(color)}
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="2.2"
            markerHeight="2.2"
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 z" fill={color} />
          </marker>
        ))}
        <marker id="flow-head-ball" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="2.2" markerHeight="2.2" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill={BALL} />
        </marker>
      </defs>
      <rect x={-PAD} y={-PAD} width={LENGTH + 2 * PAD} height={WIDTH + 2 * PAD} fill="#0f1a12" />
      {Array.from({ length: 10 }, (_, i) => (
        <rect key={i} x={(i * LENGTH) / 10} y={0} width={LENGTH / 10} height={WIDTH} fill={i % 2 ? "#1e4a2a" : "#225230"} />
      ))}
      <g fill="none" stroke="rgba(255,255,255,0.55)" strokeWidth={0.3}>
        {LINES.map((line, i) => (
          <polyline key={i} points={line.map((p) => p.join(",")).join(" ")} />
        ))}
      </g>
      {PENALTY_SPOTS.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={0.35} fill="rgba(255,255,255,0.6)" />
      ))}
      {shown.map((layer, i) => (!layer.mirror && layer.plays ? <Plays key={`p${i}`} plays={layer.plays} /> : null))}
      {shown.map((layer, i) => (
        <TeamArrows key={`a${i}`} layer={layer} />
      ))}
      {shown.map((layer, i) => (
        <TeamMarks key={`m${i}`} layer={layer} startShape={shown.length === 1} />
      ))}
    </svg>
  );
}
