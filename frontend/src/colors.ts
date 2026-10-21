/**
 * Cor da camisa mais forte para os campinhos: a câmera devolve tons lavados (um vermelho
 * capturado sai rosado/alaranjado), então a cor ganha saturação alta e brilho médio.
 * Branco e cinza claro viram quase branco; preto e cinza escuro, grafite.
 * Igual à do relatório (backend/app/report.py).
 */
export function vivid(hex: string): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let l = (max + min) / 2;
  const d = max - min;
  let s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (s < 0.18 || d < 0.08) {
    if (l >= 0.55) return "#f5f7fa";
    if (l <= 0.3) return "#1f2329";
    return "#9aa3ad";
  }
  let h = 0;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h = (h * 60 + 360) % 360;
  s = Math.max(s, 0.85);
  l = Math.min(Math.max(l, 0.42), 0.55);
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const o = l - c / 2;
  const [r1, g1, b1] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  const to = (v: number) => Math.round((v + o) * 255).toString(16).padStart(2, "0");
  return `#${to(r1)}${to(g1)}${to(b1)}`;
}
