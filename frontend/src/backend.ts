/** Cliente WebSocket do backend: reconexão automática, ping de latência e envio de frames. */

export type ConnStatus = "conectando" | "conectado" | "desconectado";

export interface WireBox {
  b: [number, number, number, number];
  c: number;
  /** papel: jogador, goleiro, árbitro, árbitro/goleiro, pessoa ou bola */
  l: string;
  /** ID do tracking (null enquanto o tracking ainda não confirmou) */
  id?: number | null;
  /** time 0 ou 1 */
  t?: number | null;
  /** bola estimada (não detectada neste frame) */
  e?: boolean;
}

export interface TeamsInfo {
  state: "calibrando" | "pronto";
  progress: number;
  colors: [string, string] | null;
  counts: { "0": number; "1": number };
  recalibrations?: number;
}

export interface MapPlayer {
  id: number | null;
  /** metros: x de 0 a 105 (comprimento), y de 0 a 68 (largura, 0 = lateral do alto da imagem) */
  x: number;
  y: number;
  t: number | null;
  l: string;
  /** fantasma: fora da imagem, na última posição conhecida */
  g: boolean;
  age: number;
}

export interface MapInfo {
  scene: "ao vivo" | "close" | "sem campo" | "sem modelo do campo" | "procurando";
  pausedS: number;
  players: MapPlayer[];
  ball: { x: number; y: number; e: boolean } | null;
  trail: [number, number][];
  view: [number, number][] | null;
  /** homografia campo → imagem (3x3, por linha) */
  hInv: number[] | null;
  keypoints: number;
  cut: boolean;
}

export interface TrackingInfo {
  active: number;
  cutsLastMinute?: number;
  newLastMinute: number;
  avgLifeS: number | null;
}

export interface DetectionsMessage {
  type: "detections";
  frameId: number;
  captureTs: number;
  width?: number;
  height?: number;
  decodeMs?: number;
  inferMs?: number;
  serverMs?: number;
  trackMs?: number;
  pitchMs?: number | null;
  conn?: number;
  model?: string;
  imgsz?: number;
  boxes?: WireBox[];
  teams?: TeamsInfo;
  tracking?: TrackingInfo;
  map?: MapInfo | null;
  error?: string;
}

export interface StatusMessage {
  type: "status";
  state: "pronto" | "carregando" | "medindo" | "erro";
  detail: string | null;
  model: string | null;
  models: string[];
  imgsz: number;
  imgszOptions: number[];
  device: string;
  footballModel: boolean;
  pitch?: { state: "ausente" | "carregando" | "baixando" | "pronto" | "erro" | "indisponível"; error: string | null };
}

export interface BenchmarkRow {
  model: string;
  meanMs?: number;
  p95Ms?: number;
  fps?: number;
  error?: string;
}

export interface BenchmarkMessage {
  type: "benchmark";
  rows: BenchmarkRow[];
  imgsz: number;
  budgetMs: number;
  frames: number;
  recommended: string | null;
  device: string;
}

export type ServerMessage =
  | { type: "hello"; version: string; serverTs: number; conn?: number }
  | { type: "pong"; clientTs: number; serverTs: number }
  | { type: "error"; detail: string }
  | DetectionsMessage
  | StatusMessage
  | BenchmarkMessage;

export const WS_URL: string =
  import.meta.env.VITE_BACKEND_WS ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
const PING_EVERY_MS = 2000;

type Listener<T> = (value: T) => void;

export class BackendClient {
  status: ConnStatus = "conectando";
  pingMs: number | null = null;
  /** identificador desta aba no backend (os resultados vão para todas as abas) */
  conn: number | null = null;

  private ws: WebSocket | null = null;
  private messageListeners = new Set<Listener<ServerMessage>>();
  private statusListeners = new Set<Listener<ConnStatus>>();
  private running = false;
  private retryDelay = 500;
  private retryTimer: number | undefined;

  constructor(private readonly url: string = WS_URL) {}

  start(): void {
    if (this.running) return;
    this.running = true;
    this.connect();
  }

  stop(): void {
    this.running = false;
    window.clearTimeout(this.retryTimer);
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  onMessage(listener: Listener<ServerMessage>): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  onStatus(listener: Listener<ConnStatus>): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  send(message: Record<string, unknown>): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }

  sendBinary(data: ArrayBuffer): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(data);
    return true;
  }

  private setStatus(status: ConnStatus): void {
    this.status = status;
    this.statusListeners.forEach((l) => l(status));
  }

  private connect(): void {
    this.setStatus("conectando");
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    let pingTimer: number | undefined;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.retryDelay = 500;
      this.setStatus("conectado");
      pingTimer = window.setInterval(() => {
        this.send({ type: "ping", clientTs: performance.now() });
      }, PING_EVERY_MS);
    };

    ws.onmessage = (event) => {
      if (this.ws !== ws || typeof event.data !== "string") return;
      const msg = JSON.parse(event.data) as ServerMessage;
      if (msg.type === "pong") this.pingMs = Math.round(performance.now() - msg.clientTs);
      if (msg.type === "hello") this.conn = msg.conn ?? null;
      this.messageListeners.forEach((l) => l(msg));
    };

    ws.onclose = () => {
      window.clearInterval(pingTimer);
      // Uma conexão antiga (já substituída ou encerrada por stop) não mexe no estado atual.
      if (this.ws !== ws) return;
      this.ws = null;
      this.pingMs = null;
      this.setStatus("desconectado");
      if (this.running) {
        this.retryTimer = window.setTimeout(() => this.connect(), this.retryDelay);
        this.retryDelay = Math.min(this.retryDelay * 2, 8000);
      }
    };
  }
}
