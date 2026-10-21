/**
 * Acha onde está o vídeo dentro da aba capturada.
 *
 * Na aba do YouTube o jogo ocupa só um pedaço da tela; o resto (título,
 * recomendações, barra de busca) fica parado. Comparando alguns frames
 * seguidos em baixa resolução, a área que muda é o vídeo. Recortar só essa
 * área deixa os jogadores maiores para a detecção, o modelo do campo e o
 * tracking (a compensação do movimento da câmera não se confunde com a página
 * parada em volta).
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const SAMPLE_W = 192;
const DIFF_THRESHOLD = 14; // diferença de brilho (0-255) que conta como mudança
const ACTIVE_MIN_CHANGES = 2; // o pixel precisa mudar em pelo menos 2 comparações
const LINE_MIN_FRACTION = 0.12; // fração de pixels ativos para uma coluna/linha contar
const MIN_AREA = 0.12; // recorte menor que isso da tela inteira é descartado
const FULL_FRAME = 0.95; // recorte quase do tamanho da tela = não recorta
const SAMPLES_NEEDED = 8;

/** Maior sequência contínua de posições acima do limite (tolerando falhas de até `gap`). */
export function longestRun(values: Float32Array, threshold: number, gap = 2): [number, number] | null {
  let best: [number, number] | null = null;
  let start = -1;
  let lastHit = -1;
  for (let i = 0; i <= values.length; i++) {
    const hit = i < values.length && values[i] >= threshold;
    if (hit) {
      if (start < 0) start = i;
      lastHit = i;
    } else if (start >= 0 && (i - lastHit > gap || i === values.length)) {
      if (!best || lastHit - start > best[1] - best[0]) best = [start, lastHit];
      start = -1;
    }
  }
  return best;
}

export class VideoRegionFinder {
  private prev: Uint8Array | null = null;
  private changes: Uint16Array | null = null;
  private samples = 0;
  private w = 0;
  private h = 0;

  reset(): void {
    this.prev = null;
    this.changes = null;
    this.samples = 0;
  }

  /** Recebe um frame em tons de cinza (w x h, já reduzido). Devolve o recorte quando houver amostras suficientes. */
  addSample(gray: Uint8Array, w: number, h: number): Rect | null | undefined {
    if (w !== this.w || h !== this.h || !this.changes) {
      this.w = w;
      this.h = h;
      this.changes = new Uint16Array(w * h);
      this.prev = null;
      this.samples = 0;
    }
    if (this.prev) {
      for (let i = 0; i < gray.length; i++) {
        if (Math.abs(gray[i] - this.prev[i]) > DIFF_THRESHOLD) this.changes[i]++;
      }
      this.samples++;
    }
    this.prev = gray.slice();
    if (this.samples < SAMPLES_NEEDED) return undefined;
    const rect = this.compute();
    this.reset();
    return rect;
  }

  private compute(): Rect | null {
    const { w, h } = this;
    const changes = this.changes!;
    const active = (i: number) => changes[i] >= ACTIVE_MIN_CHANGES;

    const cols = new Float32Array(w);
    for (let x = 0; x < w; x++) {
      let n = 0;
      for (let y = 0; y < h; y++) if (active(y * w + x)) n++;
      cols[x] = n / h;
    }
    const colRun = longestRun(cols, LINE_MIN_FRACTION * 0.5);
    if (!colRun) return null;

    const rows = new Float32Array(h);
    const cw = colRun[1] - colRun[0] + 1;
    for (let y = 0; y < h; y++) {
      let n = 0;
      for (let x = colRun[0]; x <= colRun[1]; x++) if (active(y * w + x)) n++;
      rows[y] = n / cw;
    }
    const rowRun = longestRun(rows, LINE_MIN_FRACTION);
    if (!rowRun) return null;

    // Uma amostra de folga de cada lado, para não cortar a borda do vídeo.
    const x0 = Math.max(0, colRun[0] - 1);
    const x1 = Math.min(w - 1, colRun[1] + 1);
    const y0 = Math.max(0, rowRun[0] - 1);
    const y1 = Math.min(h - 1, rowRun[1] + 1);
    let rect = { x: x0 / w, y: y0 / h, w: (x1 - x0 + 1) / w, h: (y1 - y0 + 1) / h };
    rect = snapTo16x9(rect, w / h);
    const area = rect.w * rect.h;
    if (area < MIN_AREA) return null;
    if (rect.w > FULL_FRAME && rect.h > FULL_FRAME) return null;
    return rect;
  }
}

/**
 * Transmissões são 16:9. Faixas do vídeo que mudam pouco (céu, placas paradas)
 * podem encurtar a altura achada; nesse caso a altura é completada em volta do centro.
 */
export function snapTo16x9(rect: Rect, frameAspect: number): Rect {
  const aspect = (rect.w * frameAspect) / rect.h; // largura/altura em pixels
  // Só completa quando a área ficou claramente baixa demais; algumas transmissões são um pouco mais largas que 16:9.
  if (aspect <= (16 / 9) * 1.2) return rect;
  const h = Math.min(1, (rect.w * frameAspect) / (16 / 9));
  const cy = rect.y + rect.h / 2;
  const y = Math.min(Math.max(0, cy - h / 2), 1 - h);
  return { x: rect.x, y, w: rect.w, h };
}

/** Troca o recorte só quando a mudança é relevante, para ele não ficar pulando. */
export function shouldReplace(current: Rect | null, next: Rect | null): boolean {
  if (!current || !next) return current !== next;
  const d = Math.max(
    Math.abs(current.x - next.x),
    Math.abs(current.y - next.y),
    Math.abs(current.w - next.w),
    Math.abs(current.h - next.h),
  );
  return d > 0.03;
}
