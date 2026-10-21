import { useEffect, useState } from "react";
import type { BallArrow, FlowRole, TeamFlow } from "./backend";
import { LENGTH, PENALTY_SPOTS, WIDTH, pitchLines } from "./pitch";
import { SECTOR_COLORS } from "./PatternField3D";

/** Um time no campinho de movimentação. `mirror` gira para o time defender o gol da direita. */
export interface FlowLayer {
  flow: TeamFlow | null;
  color: string;
  mirror: boolean;
  name: string;
  /** passes e cruzamentos mais repetidos (só para quem ataca) */
  arrows?: BallArrow[] | null;
}

const PAD = 4;
const LINES = pitchLines(16);
const PASS_COLOR = "#f8fafc";
const CROSS_COLOR = "#fbbf24";

/**
 * Linha do tempo de uma volta (segundos): parado na 1ª etapa, anda até a 2ª, parado, anda até a 3ª,
 * parado e some para recomeçar.
 */
const HOLD_START = 1.2;
const MOVE = 2.0;
const HOLD_MID = 0.9;
const HOLD_END = 1.6;
const FADE = 0.5;
const CYCLE = HOLD_START + MOVE + HOLD_MID + MOVE + HOLD_END + FADE;

type P = [number, number];

interface Moment {
  /** posição entre as etapas: 0 = primeira, 1 = segunda, 2 = terceira */
  at: number;
  /** etapa em destaque nos rótulos */
  stage: number;
  opacity: number;
}

function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function momentAt(clock: number): Moment {
  let t = clock % CYCLE;
  if (t < HOLD_START) return { at: 0, stage: 0, opacity: Math.min(1, t / 0.3) };
  t -= HOLD_START;
  if (t < MOVE) return { at: ease(t / MOVE), stage: t / MOVE < 0.5 ? 0 : 1, opacity: 1 };
  t -= MOVE;
  if (t < HOLD_MID) return { at: 1, stage: 1, opacity: 1 };
  t -= HOLD_MID;
  if (t < MOVE) return { at: 1 + ease(t / MOVE), stage: t / MOVE < 0.5 ? 1 : 2, opacity: 1 };
  t -= MOVE;
  if (t < HOLD_END) return { at: 2, stage: 2, opacity: 1 };
  t -= HOLD_END;
  return { at: 2, stage: 2, opacity: Math.max(0, 1 - t / FADE) };
}

function reducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Relógio da animação (sem animação para quem pediu menos movimento: troca de etapa a cada 2,5 s). */
function useClock(): Moment {
  const [moment, setMoment] = useState<Moment>(() => momentAt(0));
  useEffect(() => {
    const start = performance.now();
    if (reducedMotion()) {
      const timer = window.setInterval(() => {
        const stage = Math.floor((performance.now() - start) / 2500) % 3;
        setMoment({ at: stage, stage, opacity: 1 });
      }, 250);
      return () => window.clearInterval(timer);
    }
    let frame = 0;
    const tick = (now: number) => {
      setMoment(momentAt((now - start) / 1000));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);
  return moment;
}

function place(x: number, y: number, mirror: boolean): P {
  return mirror ? [LENGTH - x, WIDTH - y] : [x, y];
}

/** Posição de uma posição do time no instante `at` (entre as etapas). */
function positionAt(flow: TeamFlow, j: number, at: number, mirror: boolean): P {
  const i = Math.min(Math.floor(at), flow.stages.length - 2);
  const f = at - i;
  const a = flow.stages[i].roles[j];
  const b = flow.stages[i + 1].roles[j];
  return place(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, mirror);
}

function sectorOf(line: number, last: number): keyof typeof SECTOR_COLORS {
  if (line === 0) return "defesa";
  return line === last ? "ataque" : "meio";
}

function Team({ layer, at }: { layer: FlowLayer; at: number }) {
  const flow = layer.flow!;
  const roles: FlowRole[] = flow.stages[0].roles;
  const pts = roles.map((_, j) => positionAt(flow, j, at, layer.mirror));
  const last = Math.max(...roles.map((r) => r.line));
  const lines = new Map<number, P[]>();
  roles.forEach((r, j) => lines.set(r.line, [...(lines.get(r.line) ?? []), pts[j]]));
  // Posição com poucos dados na etapa mais próxima fica apagada.
  const nearest = flow.stages[Math.round(at)].roles;
  return (
    <g>
      <g opacity={0.75}>
        {[...lines.entries()].map(([line, group]) =>
          group.length < 2 ? null : (
            <polyline
              key={line}
              points={[...group].sort((p, q) => p[1] - q[1]).map((p) => p.join(",")).join(" ")}
              fill="none"
              stroke={SECTOR_COLORS[sectorOf(line, last)]}
              strokeWidth={0.45}
            />
          ),
        )}
      </g>
      {roles.map((role, j) => (
        <g key={j} opacity={nearest[j].estimated ? 0.4 : 1}>
          <circle cx={pts[j][0]} cy={pts[j][1]} r={2.1} fill={layer.color} stroke="#0b130d" strokeWidth={0.45} />
          {role.name && (
            <text x={pts[j][0]} y={pts[j][1] - 3} className="flow-label">
              {role.name}
            </text>
          )}
        </g>
      ))}
    </g>
  );
}

/** Seta curva (um pouco arqueada) com a quantidade de vezes no meio. */
function Arrow({ arrow }: { arrow: BallArrow }) {
  const [x0, y0] = arrow.from;
  const [x1, y1] = arrow.to;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len = Math.hypot(dx, dy) || 1;
  const bend = Math.min(6, len * 0.15);
  const cx = (x0 + x1) / 2 - (dy / len) * bend;
  const cy = (y0 + y1) / 2 + (dx / len) * bend;
  const color = arrow.kind === "passe" ? PASS_COLOR : CROSS_COLOR;
  const width = 0.9 + Math.min(2.2, arrow.count * 0.18);
  const mx = (x0 + 2 * cx + x1) / 4;
  const my = (y0 + 2 * cy + y1) / 4;
  return (
    <g>
      <path
        d={`M${x0},${y0} Q${cx},${cy} ${x1},${y1}`}
        fill="none"
        stroke={color}
        strokeWidth={width}
        strokeLinecap="round"
        opacity={0.55}
        markerEnd={`url(#flow-head-${arrow.kind})`}
      />
      <text x={mx} y={my - 1.6} className="flow-arrow-label" style={{ fill: color }}>
        {arrow.count}×
      </text>
    </g>
  );
}

/** Campinho só de leitura: as peças andam pelas três etapas da fase, em loop. */
export function FlowPitch({ layers }: { layers: FlowLayer[] }) {
  const moment = useClock();
  const shown = layers.filter((l) => l.flow);
  const stageCount = 3;
  return (
    <div className="flow-pitch-box">
      <svg
        className="flow-pitch"
        viewBox={`${-PAD} ${-PAD} ${LENGTH + 2 * PAD} ${WIDTH + 2 * PAD}`}
        role="img"
        aria-label="Campinho animado com a movimentação do time ao longo da fase"
      >
        <defs>
          <marker id="flow-head-passe" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="2" markerHeight="2" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill={PASS_COLOR} />
          </marker>
          <marker id="flow-head-cruzamento" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="2" markerHeight="2" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill={CROSS_COLOR} />
          </marker>
        </defs>
        <rect x={-PAD} y={-PAD} width={LENGTH + 2 * PAD} height={WIDTH + 2 * PAD} fill="#0f1a12" />
        {Array.from({ length: 10 }, (_, i) => (
          <rect key={i} x={(i * LENGTH) / 10} y={0} width={LENGTH / 10} height={WIDTH} fill={i % 2 ? "#1e4a2a" : "#225230"} />
        ))}
        <g fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth={0.3}>
          {LINES.map((line, i) => (
            <polyline key={i} points={line.map((p) => p.join(",")).join(" ")} />
          ))}
        </g>
        {PENALTY_SPOTS.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={0.35} fill="rgba(255,255,255,0.6)" />
        ))}
        {shown.map((layer, i) =>
          !layer.mirror && layer.arrows?.length ? (
            <g key={`a${i}`}>
              {layer.arrows.map((arrow, k) => (
                <Arrow key={k} arrow={arrow} />
              ))}
            </g>
          ) : null,
        )}
        <g opacity={moment.opacity}>
          {shown.map((layer, i) => (
            <Team key={i} layer={layer} at={moment.at} />
          ))}
        </g>
      </svg>
      {shown.length > 0 && (
        <ol className="flow-steps" aria-hidden="true">
          {Array.from({ length: stageCount }, (_, s) => (
            <li key={s} className={moment.stage === s ? "on" : ""}>
              {shown.map((layer) => layer.flow!.stages[s].name).join(" × ")}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
