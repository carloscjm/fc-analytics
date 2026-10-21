/** Medidas oficiais do campo (metros) e suas linhas, iguais às do backend (backend/app/pitch.py). */

export const LENGTH = 105;
export const WIDTH = 68;
const PENALTY_BOX_WIDTH = 40.32;
const PENALTY_BOX_LENGTH = 16.5;
const GOAL_BOX_WIDTH = 18.32;
const GOAL_BOX_LENGTH = 5.5;
const CIRCLE_RADIUS = 9.15;
const PENALTY_SPOT = 11;
export const GOAL_WIDTH = 7.32;
export const GOAL_HEIGHT = 2.44;

export type Polyline = [number, number][];

export function pitchLines(samplesPerArc = 24): Polyline[] {
  const L = LENGTH;
  const W = WIDTH;
  const lines: Polyline[] = [
    [
      [0, 0],
      [L, 0],
      [L, W],
      [0, W],
      [0, 0],
    ],
    [
      [L / 2, 0],
      [L / 2, W],
    ],
  ];
  for (const side of [0, 1]) {
    const x = (v: number) => (side === 0 ? v : L - v);
    let top = (W - PENALTY_BOX_WIDTH) / 2;
    let bottom = (W + PENALTY_BOX_WIDTH) / 2;
    lines.push([
      [x(0), top],
      [x(PENALTY_BOX_LENGTH), top],
      [x(PENALTY_BOX_LENGTH), bottom],
      [x(0), bottom],
    ]);
    top = (W - GOAL_BOX_WIDTH) / 2;
    bottom = (W + GOAL_BOX_WIDTH) / 2;
    lines.push([
      [x(0), top],
      [x(GOAL_BOX_LENGTH), top],
      [x(GOAL_BOX_LENGTH), bottom],
      [x(0), bottom],
    ]);
    const cx = x(PENALTY_SPOT);
    const half = Math.acos((PENALTY_BOX_LENGTH - PENALTY_SPOT) / CIRCLE_RADIUS);
    const sign = side === 0 ? 1 : -1;
    const arc: Polyline = [];
    for (let i = 0; i < samplesPerArc; i++) {
      const a = -half + (2 * half * i) / (samplesPerArc - 1);
      arc.push([cx + sign * CIRCLE_RADIUS * Math.cos(a), W / 2 + CIRCLE_RADIUS * Math.sin(a)]);
    }
    lines.push(arc);
  }
  const circle: Polyline = [];
  const n = samplesPerArc * 3;
  for (let i = 0; i <= n; i++) {
    const a = (2 * Math.PI * i) / n;
    circle.push([L / 2 + CIRCLE_RADIUS * Math.cos(a), W / 2 + CIRCLE_RADIUS * Math.sin(a)]);
  }
  lines.push(circle);
  return lines;
}

export const PENALTY_SPOTS: [number, number][] = [
  [PENALTY_SPOT, WIDTH / 2],
  [LENGTH - PENALTY_SPOT, WIDTH / 2],
  [LENGTH / 2, WIDTH / 2],
];

/** Projeta pontos do campo na imagem com a homografia campo → imagem; null para pontos atrás da câmera. */
export function projectToImage(h: number[], x: number, y: number): [number, number] | null {
  const u = h[0] * x + h[1] * y + h[2];
  const v = h[3] * x + h[4] * y + h[5];
  const w = h[6] * x + h[7] * y + h[8];
  if (w <= 1e-6) return null;
  return [u / w, v / w];
}
