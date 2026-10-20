import { useBackend } from "./useBackend";

export default function App() {
  const { status, version, latencyMs, lastError, url } = useBackend();

  return (
    <main className="page">
      <header>
        <h1>FC Analytics</h1>
        <p className="subtitle">Fase 0 · ambiente local</p>
      </header>

      <section className="card">
        <h2>Conexão com o backend</h2>
        <dl>
          <dt>Status</dt>
          <dd>
            <span className={`pill pill-${status}`}>{status}</span>
          </dd>
          <dt>Latência</dt>
          <dd>{latencyMs === null ? "—" : `${latencyMs} ms`}</dd>
          <dt>Versão do backend</dt>
          <dd>{version ?? "—"}</dd>
          <dt>Endereço</dt>
          <dd>
            <code>{url}</code>
          </dd>
        </dl>
        {lastError && <p className="error">Erro: {lastError}</p>}
        {status === "desconectado" && (
          <p className="hint">
            O backend não está respondendo. Abra o <code>iniciar.bat</code> na pasta do projeto.
          </p>
        )}
      </section>

      <section className="card muted">
        <h2>Próximo passo</h2>
        <p>Na Fase 1, esta página ganha o botão "Escolher aba" para capturar o jogo e enviar os frames para análise.</p>
      </section>
    </main>
  );
}
