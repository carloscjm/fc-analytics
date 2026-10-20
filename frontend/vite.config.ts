import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // A página fala com o backend pela mesma origem (localhost:5173/ws) e o
    // Vite repassa para o FastAPI na porta 8000. Assim funciona em qualquer
    // navegador, inclusive nos que bloqueiam conexões para outra porta.
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      "/health": { target: "http://127.0.0.1:8000" },
      "/debug": { target: "http://127.0.0.1:8000" },
    },
  },
});
