import { useEffect, useRef, useState } from "react";

export type Status = "conectando" | "conectado" | "desconectado";

type ServerMessage =
  | { type: "hello"; version: string; serverTs: number }
  | { type: "pong"; clientTs: number; serverTs: number }
  | { type: "frame_ack"; bytes: number; serverTs: number }
  | { type: "error"; detail: string };

const WS_URL = import.meta.env.VITE_BACKEND_WS ?? "ws://localhost:8000/ws";
const PING_EVERY_MS = 2000;

/** Mantém uma conexão WebSocket com o backend, com reconexão automática e medição de latência. */
export function useBackend() {
  const [status, setStatus] = useState<Status>("conectando");
  const [version, setVersion] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closedByUs = false;
    let retryDelay = 500;
    let pingTimer: number | undefined;
    let retryTimer: number | undefined;

    const connect = () => {
      setStatus("conectando");
      const ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";
      socketRef.current = ws;

      ws.onopen = () => {
        retryDelay = 500;
        setStatus("conectado");
        setLastError(null);
        pingTimer = window.setInterval(() => {
          ws.send(JSON.stringify({ type: "ping", clientTs: performance.now() }));
        }, PING_EVERY_MS);
      };

      ws.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        const msg = JSON.parse(event.data) as ServerMessage;
        if (msg.type === "hello") setVersion(msg.version);
        if (msg.type === "pong") setLatencyMs(Math.round(performance.now() - msg.clientTs));
        if (msg.type === "error") setLastError(msg.detail);
      };

      ws.onclose = () => {
        window.clearInterval(pingTimer);
        socketRef.current = null;
        setStatus("desconectado");
        setLatencyMs(null);
        if (!closedByUs) {
          retryTimer = window.setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 8000);
        }
      };
    };

    connect();

    return () => {
      closedByUs = true;
      window.clearInterval(pingTimer);
      window.clearTimeout(retryTimer);
      socketRef.current?.close();
    };
  }, []);

  return { status, version, latencyMs, lastError, url: WS_URL };
}
