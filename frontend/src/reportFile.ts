/**
 * Arquivo do relatório da partida: escolhido na hora de criar a partida (Chrome e Edge deixam
 * escolher a pasta e o nome) e lembrado neste navegador por partida. Sem essa opção, o
 * relatório é baixado na pasta de downloads.
 */

interface WritableLike {
  write(data: Blob | string): Promise<void>;
  close(): Promise<void>;
}

export interface ReportHandle {
  name: string;
  createWritable(): Promise<WritableLike>;
  queryPermission?(options: { mode: "readwrite" }): Promise<PermissionState>;
  requestPermission?(options: { mode: "readwrite" }): Promise<PermissionState>;
}

type SavePicker = (options: {
  suggestedName: string;
  types: { description: string; accept: Record<string, string[]> }[];
}) => Promise<ReportHandle>;

export function canPickFile(): boolean {
  return typeof (window as unknown as { showSaveFilePicker?: SavePicker }).showSaveFilePicker === "function";
}

/** Abre a janela do Windows para escolher onde salvar; null se cancelar ou se o navegador não deixar. */
export async function pickReportFile(suggestedName: string): Promise<ReportHandle | null> {
  const picker = (window as unknown as { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
  if (!picker) return null;
  try {
    return await picker({
      suggestedName,
      types: [{ description: "Relatório da partida (página HTML)", accept: { "text/html": [".html"] } }],
    });
  } catch {
    return null; // cancelou
  }
}

export function reportFileName(title: string, when = new Date()): string {
  const day = `${String(when.getDate()).padStart(2, "0")}-${String(when.getMonth() + 1).padStart(2, "0")}-${when.getFullYear()}`;
  const clean = title.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim() || "Partida";
  return `${clean} ${day}.html`;
}

// ---------- lembrar o arquivo de cada partida (IndexedDB) ----------

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("fc-analytics", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("reportFiles");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function rememberReportFile(matchId: number, handle: ReportHandle): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("reportFiles", "readwrite");
      tx.objectStore("reportFiles").put(handle, matchId);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // sem armazenamento: o arquivo vale só enquanto a página estiver aberta
  }
}

export async function recallReportFile(matchId: number): Promise<ReportHandle | null> {
  try {
    const db = await openDb();
    return await new Promise((resolve) => {
      const req = db.transaction("reportFiles").objectStore("reportFiles").get(matchId);
      req.onsuccess = () => resolve((req.result as ReportHandle | undefined) ?? null);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

/** Pede de novo a permissão de escrever no arquivo (o Chrome pergunta depois de recarregar a página). */
export async function ensureWritable(handle: ReportHandle | null): Promise<boolean> {
  if (!handle) return false;
  try {
    if ((await handle.queryPermission?.({ mode: "readwrite" })) === "granted") return true;
    return (await handle.requestPermission?.({ mode: "readwrite" })) === "granted";
  } catch {
    return false;
  }
}

/** Grava o relatório no arquivo escolhido ou, sem ele, baixa. Devolve onde foi parar. */
export async function writeReport(handle: ReportHandle | null, writable: boolean, html: string, fallbackName: string): Promise<string> {
  if (handle && writable) {
    const out = await handle.createWritable();
    await out.write(new Blob([html], { type: "text/html" }));
    await out.close();
    return `salvo em ${handle.name}`;
  }
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = handle?.name ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  return `baixado como ${a.download} (pasta de downloads)`;
}

export async function fetchReport(): Promise<string> {
  const res = await fetch("/report.html", { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.text();
}
