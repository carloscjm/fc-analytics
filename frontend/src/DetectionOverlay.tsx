import { useEffect, useRef } from "react";
import type { DetectionsMessage, WireBox } from "./backend";
import { pitchLines, projectToImage } from "./pitch";
import type { Rect } from "./region";

const LINES = pitchLines(32);

export const FALLBACK_TEAM_COLORS: [string, string] = ["#f5f5f5", "#3b82f6"];
export const ROLE_COLORS: Record<string, string> = {
  pessoa: "#9ca3af",
  jogador: "#22c55e",
  goleiro: "#a855f7",
  "árbitro": "#f59e0b",
  "árbitro/goleiro": "#f59e0b",
  bola: "#facc15",
};

export function teamColors(result: DetectionsMessage | null): [string, string] {
  return result?.teams?.colors ?? FALLBACK_TEAM_COLORS;
}

function colorFor(box: WireBox, colors: [string, string]): string {
  if (box.t === 0 || box.t === 1) return colors[box.t];
  return ROLE_COLORS[box.l] ?? "#e5e7eb";
}

function labelFor(box: WireBox): string {
  const id = box.id !== null && box.id !== undefined ? `#${box.id}` : "";
  switch (box.l) {
    case "bola":
      return box.e ? "bola?" : "bola";
    case "goleiro":
      return `GOL ${id}`.trim();
    case "árbitro":
      return `ÁRB ${id}`.trim();
    case "árbitro/goleiro":
      return `ÁRB/GOL ${id}`.trim();
    default:
      return id;
  }
}

/** Texto escuro em fundo claro e vice-versa, para o rótulo sempre ser legível. */
function inkFor(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#0b0d0a" : "#ffffff";
}

interface Props {
  video: HTMLVideoElement | null;
  result: DetectionsMessage | null;
  showLabels: boolean;
  showPitch: boolean;
  /** Recorte do vídeo que foi analisado (frações da imagem capturada); null = imagem inteira. */
  crop: Rect | null;
}

/** Desenha as caixas sobre o vídeo, respeitando o enquadramento (object-fit: contain). */
export function DetectionOverlay({ video, result, showLabels, showPitch, crop }: Props) {
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
      // A área analisada (o recorte) dentro do vídeo mostrado na página.
      const region = crop ?? { x: 0, y: 0, w: 1, h: 1 };
      const offX = (cw - shownW) / 2 + region.x * shownW;
      const offY = (ch - shownH) / 2 + region.y * shownH;
      const sx = (shownW * region.w) / result.width;
      const sy = (shownH * region.h) / result.height;
      if (crop) {
        ctx.save();
        ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
        ctx.setLineDash([6, 4]);
        ctx.lineWidth = 1;
        ctx.strokeRect(offX, offY, shownW * region.w, shownH * region.h);
        ctx.restore();
      }
      const colors = teamColors(result);

      // Linhas do campo projetadas pela homografia: conferem se o mapa está alinhado.
      const hInv = result.map?.hInv;
      if (showPitch && hInv) {
        ctx.strokeStyle = "rgba(236, 72, 153, 0.85)";
        ctx.lineWidth = 1.5;
        for (const line of LINES) {
          ctx.beginPath();
          let drawing = false;
          for (const [x, y] of line) {
            const pt = projectToImage(hInv, x, y);
            if (!pt) {
              drawing = false;
              continue;
            }
            const u = offX + pt[0] * sx;
            const v = offY + pt[1] * sy;
            if (drawing) ctx.lineTo(u, v);
            else ctx.moveTo(u, v);
            drawing = true;
          }
          ctx.stroke();
        }
      }

      ctx.font = "600 11px system-ui, sans-serif";
      for (const box of result.boxes) {
        const [x1, y1, x2, y2] = box.b;
        const x = offX + x1 * sx;
        const y = offY + y1 * sy;
        const w = (x2 - x1) * sx;
        const h = (y2 - y1) * sy;
        const color = colorFor(box, colors);
        const dashed = box.e || box.l === "árbitro/goleiro" || box.l === "goleiro" || box.id === null;

        ctx.strokeStyle = color;
        ctx.lineWidth = box.l === "bola" || box.l === "goleiro" ? 2.5 : 1.75;
        ctx.setLineDash(dashed ? [4, 3] : []);
        ctx.strokeRect(x, y, w, h);
        ctx.setLineDash([]);

        const text = labelFor(box);
        if (showLabels && text) {
          const tw = ctx.measureText(text).width + 6;
          ctx.fillStyle = color;
          ctx.fillRect(x, y - 14, tw, 14);
          ctx.fillStyle = inkFor(color);
          ctx.fillText(text, x + 3, y - 3);
        }
      }
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(video);
    return () => observer.disconnect();
  }, [video, result, showLabels, showPitch, crop]);

  return <canvas ref={canvasRef} className="overlay" aria-hidden="true" />;
}
