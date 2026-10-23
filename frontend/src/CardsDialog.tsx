import { useEffect, useState } from "react";
import { canPickFolder, fetchCards, pickFolder, saveCards, type CardsPayload } from "./cards";

interface Props {
  title: string;
  hasOfficial: boolean;
  onClose: () => void;
  onNotice: (text: string) => void;
}

/** Prévia dos cards do Instagram e botões para salvar as imagens (PNG 1080 × 1350). */
export function CardsDialog({ title, hasOfficial, onClose, onNotice }: Props) {
  const [payload, setPayload] = useState<CardsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchCards()
      .then((p) => alive && setPayload(p))
      .catch((err) => alive && setError(String(err)));
    return () => {
      alive = false;
    };
  }, []);

  const save = async (only?: number) => {
    if (!payload) return;
    // A janela da pasta precisa abrir direto no clique, antes de gerar as imagens.
    const folder = !only && canPickFolder() ? await pickFolder() : null;
    if (!only && canPickFolder() && !folder) return; // cancelou
    setBusy(true);
    try {
      onNotice(await saveCards(payload, title, folder, only));
    } catch (err) {
      onNotice(`Não foi possível salvar os cards: ${String(err)}`);
    }
    setBusy(false);
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className="modal cards-modal" role="dialog" aria-modal="true" aria-labelledby="cards-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="cards-title">Cards para o Instagram</h2>
        <p className="small muted">
          Carrossel vertical (1080 × 1350) com o resumo da partida.
          {hasOfficial
            ? " Placar, gols e estatísticas são os oficiais; a parte tática vem da análise do vídeo."
            : " Sem dados oficiais: o placar e as contagens vêm só do que o app marcou e viu. Use Dados oficiais para conferir."}
        </p>
        {error && <p className="small bad-text">Não foi possível montar os cards: {error}</p>}
        {!payload && !error && <p className="small">Montando os cards...</p>}
        {payload && (
          <>
            {payload.fontCss && <style>{payload.fontCss}</style>}
            <div className="cards-grid">
              {payload.cards.map((svg, i) => (
                <figure key={i}>
                  <div className="card-svg" dangerouslySetInnerHTML={{ __html: svg }} />
                  <figcaption>
                    <span className="small muted">
                      {i + 1}/{payload.cards.length}
                    </span>
                    <button className="btn small-btn" disabled={busy} onClick={() => void save(i + 1)}>
                      Baixar
                    </button>
                  </figcaption>
                </figure>
              ))}
            </div>
          </>
        )}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Fechar
          </button>
          <button className="btn primary" disabled={!payload || busy || !payload.cards.length} onClick={() => void save()}>
            {busy ? "Salvando..." : canPickFolder() ? "Salvar todos numa pasta..." : "Baixar todos"}
          </button>
        </div>
      </div>
    </div>
  );
}
