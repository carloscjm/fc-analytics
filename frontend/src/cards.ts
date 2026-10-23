/**
 * Cards do Instagram: o backend monta cada card em SVG (1080 × 1350) e a página
 * transforma em PNG, com as fontes embutidas, para postar como está.
 */

export interface CardsPayload {
  ready: boolean;
  fontCss?: string;
  cards: string[];
}

export async function fetchCards(): Promise<CardsPayload> {
  const res = await fetch("/cards.json", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as CardsPayload;
}

/** PNG de um card. As fontes vão dentro do SVG, senão a imagem sai com a fonte padrão. */
export async function cardPng(svg: string, fontCss: string): Promise<Blob> {
  const withFonts = svg.replace(/^<svg([^>]*)>/, `<svg$1><style>${fontCss}</style>`);
  const img = new Image();
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(withFonts)}`;
  await img.decode();
  await new Promise((r) => window.setTimeout(r, 150)); // dá tempo de as fontes entrarem
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1350;
  canvas.getContext("2d")?.drawImage(img, 0, 0, 1080, 1350);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("não deu para gerar a imagem"))), "image/png"),
  );
}

export function cardFileName(base: string, index: number): string {
  const clean = base.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim() || "partida";
  return `${clean} - card ${String(index).padStart(2, "0")}.png`;
}

interface DirHandle {
  name: string;
  getFileHandle(name: string, options: { create: boolean }): Promise<{
    createWritable(): Promise<{ write(data: Blob): Promise<void>; close(): Promise<void> }>;
  }>;
}

type DirPicker = (options?: { mode?: "readwrite"; id?: string }) => Promise<DirHandle>;

export function canPickFolder(): boolean {
  return typeof (window as unknown as { showDirectoryPicker?: DirPicker }).showDirectoryPicker === "function";
}

/** Pede a pasta (precisa ser chamado direto no clique). null se cancelar. */
export async function pickFolder(): Promise<DirHandle | null> {
  const picker = (window as unknown as { showDirectoryPicker?: DirPicker }).showDirectoryPicker;
  if (!picker) return null;
  try {
    return await picker({ mode: "readwrite", id: "fca-cards" });
  } catch {
    return null;
  }
}

export function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** Grava os PNG na pasta escolhida ou, sem ela, baixa um por um. Devolve onde foram parar. */
export async function saveCards(
  payload: CardsPayload,
  base: string,
  folder: DirHandle | null,
  only?: number,
): Promise<string> {
  const indexes = only ? [only] : payload.cards.map((_, i) => i + 1);
  for (const i of indexes) {
    const blob = await cardPng(payload.cards[i - 1], payload.fontCss ?? "");
    const name = cardFileName(base, i);
    if (folder) {
      const file = await folder.getFileHandle(name, { create: true });
      const out = await file.createWritable();
      await out.write(blob);
      await out.close();
    } else {
      download(blob, name);
      await new Promise((r) => window.setTimeout(r, 300));
    }
  }
  const what = indexes.length === 1 ? "Card salvo" : `${indexes.length} cards salvos`;
  return folder ? `${what} na pasta ${folder.name}.` : `${what} na pasta de downloads.`;
}
