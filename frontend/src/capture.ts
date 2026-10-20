/**
 * Captura da aba do jogo e envio de frames ao backend.
 *
 * - O temporizador roda num Web Worker para continuar no ritmo certo mesmo
 *   quando esta página fica em segundo plano (o navegador desacelera os
 *   temporizadores de abas ocultas).
 * - Os frames são lidos da trilha de vídeo com ImageCapture quando o navegador
 *   oferece, e do elemento <video> como alternativa.
 * - Só um frame fica "em voo" por vez: se o anterior ainda não voltou, o
 *   próximo tique é pulado. Isso impede que uma fila acumule e o atraso cresça.
 */

export const MAX_WIDTH = 1280;
export const MAX_HEIGHT = 720;
const HEADER_BYTES = 12;
const LOST_AFTER_MS = 3000;

interface ImageCaptureLike {
  grabFrame(): Promise<ImageBitmap>;
}
declare const ImageCapture: { new (track: MediaStreamTrack): ImageCaptureLike } | undefined;

export async function chooseTab(): Promise<MediaStream> {
  const options = {
    video: { frameRate: { ideal: 30 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    audio: false,
    // Sugere abas do navegador e esconde esta própria página da lista.
    preferCurrentTab: false,
    selfBrowserSurface: "exclude",
    surfaceSwitching: "include",
  } as DisplayMediaStreamOptions;
  return navigator.mediaDevices.getDisplayMedia(options);
}

export function fitSize(width: number, height: number): { width: number; height: number } {
  const scale = Math.min(MAX_WIDTH / width, MAX_HEIGHT / height, 1);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

export function packFrame(frameId: number, captureTs: number, jpeg: ArrayBuffer): ArrayBuffer {
  const out = new Uint8Array(HEADER_BYTES + jpeg.byteLength);
  const view = new DataView(out.buffer);
  view.setUint32(0, frameId, true);
  view.setFloat64(4, captureTs, true);
  out.set(new Uint8Array(jpeg), HEADER_BYTES);
  return out.buffer;
}

function createTicker(onTick: () => void): { setInterval(ms: number): void; stop(): void } {
  const source = `let t=null;onmessage=(e)=>{clearInterval(t);if(e.data>0)t=setInterval(()=>postMessage(0),e.data)}`;
  const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
  const worker = new Worker(url);
  worker.onmessage = onTick;
  return {
    setInterval: (ms) => worker.postMessage(ms),
    stop: () => {
      worker.postMessage(0);
      worker.terminate();
      URL.revokeObjectURL(url);
    },
  };
}

export interface SenderCounters {
  sent: number;
  skipped: number;
  lost: number;
}

export class FrameSender {
  quality = 0.75;
  counters: SenderCounters = { sent: 0, skipped: 0, lost: 0 };

  private nextId = 1;
  private inFlight = new Map<number, number>();
  private busy = false;
  private ticker: ReturnType<typeof createTicker> | null = null;
  private grabber: ImageCaptureLike | null = null;
  private canvas: OffscreenCanvas | HTMLCanvasElement;
  private ctx: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D;

  constructor(
    stream: MediaStream,
    private readonly video: HTMLVideoElement,
    private readonly send: (data: ArrayBuffer) => boolean,
    private intervalMs = 150,
  ) {
    const track = stream.getVideoTracks()[0];
    if (typeof ImageCapture !== "undefined" && track) this.grabber = new ImageCapture(track);
    this.canvas =
      typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(MAX_WIDTH, MAX_HEIGHT) : document.createElement("canvas");
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("canvas 2D indisponível");
    this.ctx = ctx as OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D;
  }

  start(): void {
    this.ticker = createTicker(() => void this.tick());
    this.ticker.setInterval(this.intervalMs);
  }

  stop(): void {
    this.ticker?.stop();
    this.ticker = null;
    this.inFlight.clear();
  }

  setInterval(ms: number): void {
    this.intervalMs = ms;
    this.ticker?.setInterval(ms);
  }

  /** Chamado quando o backend devolve o resultado de um frame. */
  ack(frameId: number): void {
    this.inFlight.delete(frameId);
  }

  private expireLost(now: number): void {
    for (const [id, ts] of this.inFlight) {
      if (now - ts > LOST_AFTER_MS) {
        this.inFlight.delete(id);
        this.counters.lost++;
      }
    }
  }

  private async grab(): Promise<CanvasImageSource | null> {
    if (this.grabber) {
      try {
        return await this.grabber.grabFrame();
      } catch {
        // A trilha pode estar pausada por um instante; tenta pelo <video>.
      }
    }
    return this.video.readyState >= 2 ? this.video : null;
  }

  private async tick(): Promise<void> {
    const now = performance.now();
    this.expireLost(now);
    if (this.busy || this.inFlight.size > 0) {
      this.counters.skipped++;
      return;
    }
    this.busy = true;
    try {
      const captureTs = performance.now();
      const source = await this.grab();
      if (!source) return;
      const srcW = source instanceof HTMLVideoElement ? source.videoWidth : (source as ImageBitmap).width;
      const srcH = source instanceof HTMLVideoElement ? source.videoHeight : (source as ImageBitmap).height;
      if (!srcW || !srcH) return;

      const { width, height } = fitSize(srcW, srcH);
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      this.ctx.drawImage(source, 0, 0, width, height);
      if ("close" in source && typeof source.close === "function") source.close();

      const blob =
        this.canvas instanceof HTMLCanvasElement
          ? await new Promise<Blob | null>((resolve) =>
              (this.canvas as HTMLCanvasElement).toBlob(resolve, "image/jpeg", this.quality),
            )
          : await this.canvas.convertToBlob({ type: "image/jpeg", quality: this.quality });
      if (!blob) return;

      const id = this.nextId++;
      if (this.send(packFrame(id, captureTs, await blob.arrayBuffer()))) {
        this.inFlight.set(id, captureTs);
        this.counters.sent++;
      }
    } finally {
      this.busy = false;
    }
  }
}
