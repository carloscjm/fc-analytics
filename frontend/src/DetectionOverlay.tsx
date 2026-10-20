import { useEffect, useRef } from "react";
import type { DetectionsMessage } from "./backend";

export const LABEL_COLORS: Record<string, string> = {
  pessoa: "#22c55e",
  jogador: "#22c55e",
  goleiro: "#a855f7",
  "árbitro": "#f59e0b",
  bola: "#facc15",
};

function colorFor(label: string): string {
  return LABEL_COLORS[label] ?? "#e5e7eb";
}

interface Props {
  video: HTMLVideoElement | null;
  result: DetectionsMessage | null;
  showLabels: boolean;
}

/** Desenha as caixas detectadas por cima do vídeo, respeitando o enquadramento (object-fit: contain). */
export function DetectionOverlay({ video, result, showLabels }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !video) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const cw = video.clientWidth;
      const ch = video.clientHeight;
      canvas.width = Math.round(cw * dpr);
      canvas.height = Math.round(ch * dpr);
      canvas.style.width = `${cw}px`;
      canvas.style.height = `${ch}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);

      if (!result?.boxes || !result.width || !result.height || !video.videoWidth) return;

      const scale = Math.min(cw / video.videoWidth, ch / video.videoHeight);
      const shownW = video.videoWidth * scale;
      const shownH = video.videoHeight * scale;
      const offX = (cw - shownW) / 2;
      const offY = (ch - shownH) / 2;
      const sx = shownW / result.width;
      const sy = shownH / result.height;

      ctx.font = "600 11px system-ui, sans-serif";
      for (const box of result.boxes) {
        const [x1, y1, x2, y2] = box.b;
        const x = offX + x1 * sx;
        const y = offY + y1 * sy;
        const w = (x2 - x1) * sx;
        const h = (y2 - y1) * sy;
        const color = colorFor(box.l);
        ctx.strokeStyle = color;
        ctx.lineWidth = box.l === "bola" ? 2.5 : 1.5;
        ctx.strokeRect(x, y, w, h);

        if (showLabels) {
          const text = `${box.l} ${Math.round(box.c * 100)}%`;
          const tw = ctx.measureText(text).width + 6;
          ctx.fillStyle = color;
          ctx.fillRect(x, y - 14, tw, 14);
          ctx.fillStyle = "#0b0d0a";
          ctx.fillText(text, x + 3, y - 3);
        }
      }
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(video);
    return () => observer.disconnect();
  }, [video, result, showLabels]);

  return <canvas ref={canvasRef} className="overlay" aria-hidden="true" />;
}
