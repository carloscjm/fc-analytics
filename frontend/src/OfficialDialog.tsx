import { useEffect, useRef, useState } from "react";
import type { BackendClient, MatchStats, OfficialCandidate } from "./backend";

interface Props {
  client: BackendClient;
  stats: MatchStats | null;
  /** siglas ou nomes que o app usa para os times */
  names: [string, string];
  colors: [string, string];
  /** "finish": aberta ao finalizar (o relatório é salvo no fim); "edit": aberta pelo botão Dados oficiais */
  mode: "finish" | "edit";
  onDone: () => void;
  onClose: () => void;
}

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Conferência dos dados oficiais: acha o jogo na fonte pública, a pessoa confirma e confere os times. */
export function OfficialDialog({ client, stats, names, colors, mode, onDone, onClose }: Props) {
  const official = stats?.official ?? null;
  const [step, setStep] = useState<"search" | "check">(official ? "check" : "search");
  const [loading, setLoading] = useState(false);
  const [candidates, setCandidates] = useState<OfficialCandidate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [date, setDate] = useState("");
  const [waiting, setWaiting] = useState<string | null>(null);
  const searched = useRef(false);

  useEffect(
    () =>
      client.onMessage((msg) => {
        if (msg.type !== "official_candidates") return;
        setLoading(false);
        setCandidates(msg.candidates);
        setError(msg.error);
      }),
    [client],
  );

  const search = (q?: string, d?: string) => {
    setLoading(true);
    setError(null);
    setCandidates([]);
    if (!client.send({ type: "official_search", query: q || null, date: d || null })) {
      setLoading(false);
      setError("Sem conexão com o backend.");
    }
  };

  // Busca automática pelas siglas do placar e pelo nome da partida.
  useEffect(() => {
    if (step === "search" && !searched.current) {
      searched.current = true;
      search();
    }
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  // Esperando o backend buscar o resumo do jogo escolhido.
  useEffect(() => {
    if (!waiting) return;
    if (official?.eventId === waiting) {
      setWaiting(null);
      setStep("check");
      return;
    }
    const timer = window.setTimeout(() => {
      setWaiting(null);
      setError("A fonte demorou para responder. Tente de novo.");
    }, 25000);
    return () => window.clearTimeout(timer);
  }, [waiting, official?.eventId]);

  const choose = (c: OfficialCandidate) => {
    setError(null);
    setWaiting(c.eventId);
    client.send({ type: "official_confirm", eventId: c.eventId });
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={mode === "edit" ? onClose : undefined}>
      <div className="modal official" role="dialog" aria-modal="true" aria-labelledby="official-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="official-title">Dados oficiais da partida</h2>

        {step === "search" && (
          <>
            <p className="small muted">
              O app procura o jogo numa fonte pública e gratuita (ESPN) para usar o placar, os gols e as estatísticas
              oficiais no relatório e nos cards. A análise tática continua sendo a do vídeo.
            </p>
            {loading && <p className="small">Procurando o jogo...</p>}
            {waiting && <p className="small">Buscando os dados do jogo escolhido...</p>}
            {error && <p className="small bad-text">{error}</p>}
            {!loading && candidates.length > 0 && (
              <div className="candidates">
                <span className="small muted">É um destes? Clique no jogo certo.</span>
                {candidates.map((c) => (
                  <button key={c.eventId} className="candidate" disabled={!!waiting} onClick={() => choose(c)}>
                    <strong>
                      {c.home.name} {c.home.score ?? ""} x {c.away.score ?? ""} {c.away.name}
                    </strong>
                    <span className="small muted">
                      {[when(c.date), c.status].filter(Boolean).join(" · ")}
                      {!c.completed && " · ainda não terminou na fonte"}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <form
              className="field"
              onSubmit={(e) => {
                e.preventDefault();
                search(query.trim(), date);
              }}
            >
              Procurar por outro nome
              <div className="file-row">
                <input value={query} placeholder="Ex.: Arsenal Bayern" onChange={(e) => setQuery(e.target.value)} />
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Data do jogo" />
                <button className="btn small-btn" type="submit" disabled={loading || !query.trim()}>
                  Procurar
                </button>
              </div>
              <span className="small muted">Sem data, procura no dia em que a partida foi criada e nos dias vizinhos.</span>
            </form>
            <div className="modal-actions">
              {official && (
                <button className="btn" onClick={() => setStep("check")}>
                  Voltar
                </button>
              )}
              <button className="btn" onClick={mode === "finish" ? onDone : onClose}>
                {mode === "finish" ? "Salvar sem dados oficiais" : "Fechar"}
              </button>
            </div>
          </>
        )}

        {step === "check" && official && (
          <>
            <p className="small muted">
              {[official.league, when(official.date), official.venue].filter(Boolean).join(" · ")}
            </p>
            <p className="official-score">
              {official.teams[0].short} {official.teams[0].score} x {official.teams[1].score} {official.teams[1].short}
            </p>
            <p className="small">Confira se cada time ficou com a camisa certa:</p>
            <ul className="team-match">
              {[0, 1].map((i) => (
                <li key={i}>
                  <span className="swatch" style={{ background: colors[i] }} />
                  <span className="muted">{names[i]}</span> → <strong>{official.teams[i].name}</strong>
                </li>
              ))}
            </ul>
            <div className="modal-actions spread">
              <span className="row-gap">
                <button className="btn small-btn" onClick={() => client.send({ type: "official_swap" })}>
                  ⇄ Trocar os times
                </button>
                <button
                  className="btn small-btn"
                  onClick={() => {
                    setStep("search");
                    if (!searched.current) {
                      searched.current = true;
                      search();
                    }
                  }}
                >
                  Outro jogo
                </button>
                {mode === "edit" && (
                  <button
                    className="btn small-btn"
                    onClick={() => {
                      client.send({ type: "official_clear" });
                      onClose();
                    }}
                  >
                    Remover
                  </button>
                )}
              </span>
              <button className="btn primary" onClick={onDone}>
                {mode === "finish" ? "Está certo, salvar relatório" : "Pronto"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
