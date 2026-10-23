import { useEffect, useState } from "react";
import type { MatchStats } from "./backend";
import { canPickFile, pickReportFile, reportFileName, type ReportHandle } from "./reportFile";

interface Props {
  stats: MatchStats | null;
  names: [string, string];
  capturing: boolean;
  connected: boolean;
  reportHandle: ReportHandle | null;
  busy: string | null;
  onCreate: (name: string, handle: ReportHandle | null) => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onFinish: () => void;
  onExport: () => void;
  onOfficial: () => void;
  onCards: () => void;
}

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Botões da partida no cabeçalho: criar, escolher aba, pausar/retomar e finalizar. */
export function MatchControls(props: Props) {
  const { stats, names, capturing, connected, reportHandle, busy } = props;
  const state = stats?.matchState ?? "livre";
  const open = state === "ativa" || state === "pausada";
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [handle, setHandle] = useState<ReportHandle | null>(null);
  const [confirmFinish, setConfirmFinish] = useState(false);

  useEffect(() => {
    if (!confirmFinish) return;
    const timer = window.setTimeout(() => setConfirmFinish(false), 4000);
    return () => window.clearTimeout(timer);
  }, [confirmFinish]);

  const title = stats?.matchName || `${names[0]} x ${names[1]}`;
  const stateText = state === "pausada" ? "pausada" : state === "finalizada" ? "finalizada" : capturing ? "capturando" : "aguardando a aba";

  const startCreate = () => {
    setName("");
    setHandle(null);
    setCreating(true);
  };

  return (
    <div className="match-controls">
      {(open || state === "finalizada") && stats && (
        <div className={`match-chip ${state}`} title={reportHandle ? `Relatório: ${reportHandle.name}` : undefined}>
          <strong>{title}</strong>
          <span>
            {clock(stats.elapsedS)} · {stateText}
          </span>
        </div>
      )}

      {!open && (
        <button className="btn primary" onClick={startCreate} disabled={!connected}>
          Criar partida
        </button>
      )}
      {state === "finalizada" && (
        <>
          <button className="btn" onClick={props.onOfficial} disabled={!!busy || !connected}>
            {stats?.official ? "✓ Dados oficiais" : "Dados oficiais"}
          </button>
          <button className="btn" onClick={props.onCards} disabled={!!busy}>
            Cards para o Instagram
          </button>
          <button className="btn" onClick={props.onExport} disabled={!!busy}>
            Salvar relatório de novo
          </button>
        </>
      )}
      {open && (
        <button className="btn" onClick={props.onCards} disabled={!!busy} title="Prévia dos cards com o que já foi analisado">
          Cards
        </button>
      )}

      {state === "ativa" && !capturing && (
        <button className="btn primary" onClick={props.onStart} disabled={!connected}>
          Escolher aba
        </button>
      )}
      {state === "ativa" && capturing && (
        <button className="btn" onClick={props.onPause}>
          ❚❚ Pausar captura
        </button>
      )}
      {state === "pausada" && (
        <button className="btn primary" onClick={props.onResume} disabled={!connected}>
          ▶ Retomar captura
        </button>
      )}
      {open && (
        <button
          className={`btn ${confirmFinish ? "danger-btn" : ""}`}
          disabled={!!busy}
          onClick={() => {
            if (!confirmFinish) return setConfirmFinish(true);
            setConfirmFinish(false);
            props.onFinish();
          }}
        >
          {confirmFinish ? "Clique de novo para finalizar" : "Finalizar partida"}
        </button>
      )}

      {creating && (
        <div className="modal-backdrop" role="presentation" onClick={() => setCreating(false)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="create-title">Criar partida</h2>
            <p className="small muted">
              Tudo o que for capturado a partir de agora vai para esta partida: estatísticas, padrões, alertas e o
              relatório. Pause no intervalo e finalize no fim do jogo para fechar o relatório.
            </p>
            <label className="field">
              Nome da partida
              <input
                autoFocus
                value={name}
                placeholder="Ex.: Arsenal x Barcelona (em branco: as siglas do placar)"
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="field">
              Onde salvar o relatório
              {canPickFile() ? (
                <div className="file-row">
                  <button
                    className="btn small-btn"
                    onClick={async () => {
                      const picked = await pickReportFile(reportFileName(name || "Partida"));
                      if (picked) setHandle(picked);
                    }}
                  >
                    Escolher pasta e nome...
                  </button>
                  <span className="small">{handle ? handle.name : "nenhum arquivo escolhido: vai para Downloads"}</span>
                </div>
              ) : (
                <span className="small muted">Este navegador não deixa escolher: o relatório vai para Downloads.</span>
              )}
              <span className="small muted">
                O relatório é uma página (.html) que abre em qualquer navegador e pode ser impressa em PDF. Ele é gravado
                a cada pausa e ao finalizar.
              </span>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setCreating(false)}>
                Cancelar
              </button>
              <button
                className="btn primary"
                onClick={() => {
                  setCreating(false);
                  props.onCreate(name.trim(), handle);
                }}
              >
                Criar partida
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
