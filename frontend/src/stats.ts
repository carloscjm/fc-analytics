/** Métricas móveis: fps de resultados e atraso de ponta a ponta. */

export interface LiveStats {
  fps: number;
  latencyMeanMs: number | null;
  latencyP95Ms: number | null;
  inferMs: number | null;
  serverMs: number | null;
}

const FPS_WINDOW_MS = 2000;
const LATENCY_SAMPLES = 60;

export class RollingStats {
  private resultTimes: number[] = [];
  private latencies: number[] = [];
  private lastInfer: number | null = null;
  private lastServer: number | null = null;

  add(now: number, latencyMs: number, inferMs?: number, serverMs?: number): void {
    this.resultTimes.push(now);
    this.latencies.push(latencyMs);
    if (this.latencies.length > LATENCY_SAMPLES) this.latencies.shift();
    if (inferMs !== undefined) this.lastInfer = inferMs;
    if (serverMs !== undefined) this.lastServer = serverMs;
  }

  reset(): void {
    this.resultTimes = [];
    this.latencies = [];
    this.lastInfer = null;
    this.lastServer = null;
  }

  snapshot(now: number): LiveStats {
    while (this.resultTimes.length && now - this.resultTimes[0] > FPS_WINDOW_MS) this.resultTimes.shift();
    const sorted = [...this.latencies].sort((a, b) => a - b);
    const mean = sorted.length ? sorted.reduce((s, v) => s + v, 0) / sorted.length : null;
    const p95 = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] : null;
    return {
      fps: this.resultTimes.length / (FPS_WINDOW_MS / 1000),
      latencyMeanMs: mean === null ? null : Math.round(mean),
      latencyP95Ms: p95 === null ? null : Math.round(p95),
      inferMs: this.lastInfer,
      serverMs: this.lastServer,
    };
  }
}
