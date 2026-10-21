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

type P = [number, number];

function place(role: FlowRole, mirror: boolean): P {
  return mirror ? [LENGTH - role.x, WIDTH - role.y] : [role.x, role.y];
}

function sectorOf(line: number, last: number): keyof typeof SECTOR_COLORS {
  if (line === 0) return "defesa";
  return line === last ? "ataque" : "meio";
}

/** Curva suave pelas três etapas (passa pelo ponto do meio). */
function curve([a, b, c]: P[]): string {
  // Ponto de controle que faz a quadrática passar por b no meio do caminho.
  const cx = 2 * b[0] - (a[0] + c[0]) / 2;
  const cy = 2 * b[1] - (a[1] + c[1]) / 2;
  return `M${a[0].toFixed(1)},${a[1].toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${c[0].toFixed(1)},${c[1].toFixed(1)}`;
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

function TeamPaths({ layer, startShape }: { layer: FlowLayer; startShape: boolean }) {
  const stages = layer.flow!.stages;
  const first = stages[0].roles;
  const last = stages[stages.length - 1].roles;
  return (
    <g>
      {startShape && <Shape roles={first} mirror={layer.mirror} faded />}
      <Shape roles={last} mirror={layer.mirror} faded={false} />
      {first.map((_, j) => {
        const pts = stages.map((s) => place(s.roles[j], layer.mirror));
        const role = last[j];
        const estimated = stages.some((s) => s.roles[j].estimated);
        const moved = Math.hypot(pts[2][0] - pts[0][0], pts[2][1] - pts[0][1]) >= MIN_MOVE_M;
        const d = curve(pts);
        return (
          <g key={j} opacity={estimated ? 0.5 : 1}>
            {moved && (
              <>
                <path d={d} fill="none" stroke="rgba(0,0,0,0.55)" strokeWidth={1.3} strokeLinecap="round" />
                <path
                  d={d}
                  fill="none"
                  stroke={layer.color}
                  strokeWidth={0.7}
                  strokeLinecap="round"
                  strokeDasharray={estimated ? "1.4 1" : undefined}
                  markerEnd={`url(#${markerId(layer.color)})`}
                />
              </>
            )}
            <circle cx={pts[0][0]} cy={pts[0][1]} r={1.3} fill="none" stroke={layer.color} strokeWidth={0.45} />
            <circle cx={pts[1][0]} cy={pts[1][1]} r={0.55} fill={layer.color} />
            <circle cx={pts[2][0]} cy={pts[2][1]} r={1.9} fill={layer.color} stroke="#0b130d" strokeWidth={0.4} />
            {role.name && (
              <text x={pts[2][0]} y={pts[2][1] - 2.8} className="flow-label">
                {role.name}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

const BALL = "#fbbf24";

/** Jogadas com a bola de quem ataca (para a direita): cruzamentos por lado, entradas e chutes de fora. */
function Plays({ plays }: { plays: PlaysInfo }) {
  const c = plays.counts;
  const crossL = plays.bySide.cruzamento.esquerda;
  const crossR = plays.bySide.cruzamento.direita;
  const width = (n: number) => 0.35 + Math.min(1.1, n * 0.08);
  return (
    <g className="flow-plays" opacity={0.8}>
      {crossL > 0 && (
        <g>
          <path d="M88,5 Q99,10 96,28" fill="none" stroke={BALL} strokeWidth={width(crossL)} markerEnd="url(#flow-head-ball)" />
          <text x={84} y={-1.6} className="flow-play-label">
            {crossL} cruz.
          </text>
        </g>
      )}
      {crossR > 0 && (
        <g>
          <path d="M88,63 Q99,58 96,40" fill="none" stroke={BALL} strokeWidth={width(crossR)} markerEnd="url(#flow-head-ball)" />
          <text x={84} y={71.2} className="flow-play-label">
            {crossR} cruz.
          </text>
        </g>
      )}
      {c.entrada > 0 && (
        <g>
          <path d="M80,31 L91,31" fill="none" stroke={BALL} strokeWidth={width(c.entrada)} markerEnd="url(#flow-head-ball)" />
          <text x={79} y={29.4} className="flow-play-label">
            {c.entrada} entradas
          </text>
        </g>
      )}
      {c.chute_fora > 0 && (
        <g>
          <path
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
            markerWidth="3.2"
            markerHeight="3.2"
            orient="auto-start-reverse"
          >
            <path d="M0,1 L9,5 L0,9 z" fill={color} stroke="#0b130d" strokeWidth={0.8} />
          </marker>
        ))}
        <marker id="flow-head-ball" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="3" markerHeight="3" orient="auto">
          <path d="M0,1 L9,5 L0,9 z" fill={BALL} />
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
        <TeamPaths key={i} layer={layer} startShape={shown.length === 1} />
      ))}
    </svg>
  );
}
