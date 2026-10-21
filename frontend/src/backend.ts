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

export interface PatternRole {
  x: number;
  y: number;
  sx: number;
  sy: number;
  /** linha: 0 = defesa, a última = ataque */
  line: number;
  share: number;
}

export interface TeamPattern {
  formation: string;
  roles: PatternRole[];
  /** altura média da linha de defesa, em metros a partir do próprio gol */
  lineHeight: number;
  block: "baixo" | "médio" | "alto";
  width: number;
  depth: number;
  corridors: { esquerda: number; centro: number; direita: number } | null;
  heat: { nx: number; ny: number; cell: number; values: number[] };
  points: number;
}

export interface PatternOption {
  team: 0 | 1;
  phase: "ataque" | "defesa";
  frames: number;
  seconds: number;
  needed: number;
  pattern: TeamPattern | null;
}

export interface PatternsInfo {
  options: Record<string, PatternOption>;
  phaseSource: { bola: number; "avanço": number; "sem fase": number };
  team0DefendsLeft: boolean | null;
}

export type Pair<T> = [T, T];

export type MatchEventKind = "gol" | "amarelo" | "vermelho" | "substituicao" | "intervalo";

/** Evento marcado à mão (atalho de teclado ou botão). `t` = segundos desde o começo da partida no app. */
export interface MatchEvent {
  id: number;
  t: number;
  kind: MatchEventKind;
  team: 0 | 1 | null;
}

/** Métricas de uma janela (últimos 5 min ou partida inteira). Índice 0 = Time A, 1 = Time B. */
export interface WindowStats {
  seconds: number;
  possession: Pair<number> | null;
  possessionCoverage: number | null;
  tilt: Pair<number> | null;
  line: Pair<number | null>;
  depth: Pair<number | null>;
  width: Pair<number | null>;
  corridors: Pair<number[] | null>;
  passes: Pair<number>;
  losses: Pair<number>;
  passAccuracy: Pair<number | null>;
  pressure: Pair<number | null>;
  recoveries5s: Pair<number | null>;
  distanceKm: Pair<number>;
}

export interface MatchStats {
  matchId: number;
  startedAt: number;
  elapsedS: number;
  paused: boolean;
  period: 1 | 2;
  score: Pair<number>;
  events: MatchEvent[];
  windows: { recentes: WindowStats; partida: WindowStats };
  timeline: {
    minutes: number[];
    possession: (Pair<number> | null)[];
    line: Pair<(number | null)[]>;
  };
}

export interface InsightAnalysis {
  leitura: string;
  funcionando: string[];
  espacos: string[];
  sugestoes: string[];
}

/** Um item do feed: alerta de regra (imediato) ou análise do LLM local. */
export interface InsightItem {
  id: number;
  kind: "alerta" | "analise";
  /** horário do PC, em ms */
  wall: number;
  /** segundos desde o começo da partida no app */
  t: number;
  team: 0 | 1 | null;
  rule: string | null;
  level: "info" | "atencao";
  text: string;
  analysis?: InsightAnalysis;
  model?: string;
  seconds?: number;
}

export interface LlmInfo {
  state: "verificando" | "desligado" | "sem modelo" | "baixando" | "pronto" | "analisando" | "erro";
  model: string;
  installed: string[];
  recommended: { name: string; label: string }[];
  intervalS: number;
  intervalOptions: number[];
  nextInS: number | null;
  lastError: string | null;
  pull: { model: string; status: string; completed: number; total: number } | null;
}

export interface InsightsInfo {
  items: InsightItem[];
  llm: LlmInfo;
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
  patterns?: PatternsInfo | null;
  stats?: MatchStats | null;
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
  patterns?: PatternsInfo;
  stats?: MatchStats;
  insights?: InsightsInfo;
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
  | ({ type: "patterns" } & PatternsInfo)
  | { type: "stats"; stats: MatchStats }
  | ({ type: "insights" } & InsightsInfo)
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
