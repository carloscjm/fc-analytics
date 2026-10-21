import { useEffect, useState, type ReactNode } from "react";
import type { InsightItem, InsightsInfo, LlmInfo } from "./backend";

const TEAM_NAMES = ["Time A", "Time B"] as const;

export type InsightCommand =
  | { type: "llm_analyze_now" }
  | { type: "llm_pull"; model?: string }
  | { type: "llm_set_model"; model: string }
  | { type: "llm_set_interval"; seconds: number };

interface Props {
  info: InsightsInfo | null;
  colors: [string, string];
  send: (command: InsightCommand) => void;
}

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function countdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function gb(bytes: number): string {
  return (bytes / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
}

/** Contagem regressiva local até a próxima análise (o backend só manda o valor quando algo muda). */
function useCountdown(nextInS: number | null): number | null {
  const [state, setState] = useState<{ base: number | null; at: number }>({ base: nextInS, at: Date.now() });
  const [, setTick] = useState(0);
  useEffect(() => setState({ base: nextInS, at: Date.now() }), [nextInS]);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (state.base === null) return null;
  return Math.max(0, state.base - (Date.now() - state.at) / 1000);
}

function LlmStatus({ llm, send }: { llm: LlmInfo; send: Props["send"] }) {
  const next = useCountdown(llm.nextInS);
  const options = [...new Set([...llm.recommended.map((r) => r.name), ...llm.installed, llm.model])];
  const label = (name: string) => llm.recommended.find((r) => r.name === name)?.label ?? name;
  const installed = (name: string) => llm.installed.some((m) => m === name || m === `${name}:latest`);

  let line: ReactNode;
  let tone = "muted";
  switch (llm.state) {
    case "pronto":
      tone = "ok";
      line = (
        <>
          LLM pronto ({llm.model})
          {next !== null && <> · próxima análise em {countdown(next)}</>}
        </>
      );
      break;
    case "analisando":
      tone = "warn";
      line = <>Analisando com {llm.model}... pode levar até 1 minuto.</>;
      break;
    case "baixando":
      tone = "warn";
      line = <>Baixando {llm.pull?.model ?? llm.model}...</>;
      break;
    case "sem modelo":
      tone = "warn";
      line = <>O modelo {llm.model} ainda não foi baixado.</>;
      break;
    case "desligado":
      tone = "bad";
      line = <>O Ollama não está aberto. Abra o Ollama pelo menu Iniciar; o app encontra ele sozinho.</>;
      break;
    default:
      line = <>Procurando o Ollama...</>;
  }

  const pull = llm.pull;
  const pct = pull && pull.total ? Math.round((100 * pull.completed) / pull.total) : 0;

  return (
    <div className="llm">
      <p className={`llm-line ${tone}`}>
        <span className="dot" />
        <span>{line}</span>
      </p>
      {pull && (
        <div>
          <div className="progress" aria-label="Download do modelo">
            <div style={{ width: `${pct}%` }} />
          </div>
          <p className="muted small">
            {pull.total ? `${gb(pull.completed)} de ${gb(pull.total)} GB (${pct}%)` : pull.status}
          </p>
        </div>
      )}
      <div className="llm-actions">
        {llm.state === "sem modelo" && (
          <button className="btn small-btn primary" onClick={() => send({ type: "llm_pull" })}>
            Baixar {llm.model}
          </button>
        )}
        {(llm.state === "pronto" || llm.state === "analisando") && (
          <button
            className="btn small-btn"
            disabled={llm.state === "analisando"}
            onClick={() => send({ type: "llm_analyze_now" })}
          >
            Analisar agora
          </button>
        )}
      </div>
      {llm.lastError && <p className="small bad">{llm.lastError}</p>}
      <details className="llm-settings">
        <summary className="small">Modelo e frequência</summary>
        <label className="small">
          Modelo
          <select value={llm.model} onChange={(e) => send({ type: "llm_set_model", model: e.target.value })}>
            {options.map((name) => (
              <option key={name} value={name}>
                {label(name)}
                {installed(name) ? "" : " · não baixado"}
              </option>
            ))}
          </select>
        </label>
        <label className="small">
          Análise a cada
          <select
            value={llm.intervalS}
            onChange={(e) => send({ type: "llm_set_interval", seconds: Number(e.target.value) })}
          >
            {llm.intervalOptions.map((s) => (
              <option key={s} value={s}>
                {s / 60} min
              </option>
            ))}
          </select>
        </label>
      </details>
    </div>
  );
}

function Item({ item, colors }: { item: InsightItem; colors: [string, string] }) {
  const when = `${clock(item.wall)} · ${Math.floor(item.t / 60) + 1}'`;
  if (item.kind === "analise" && item.analysis) {
    const a = item.analysis;
    const sections: [string, string[]][] = [
      ["Funcionando", a.funcionando],
      ["Espaços para explorar", a.espacos],
      ["Sugestões", a.sugestoes],
    ];
    return (
      <li className="insight analise">
        <div className="insight-head">
          <span className="badge">Análise</span>
          <span className="muted small">{when}</span>
        </div>
        <p>{a.leitura}</p>
        {sections
          .filter(([, list]) => list.length)
          .map(([title, list]) => (
            <div key={title} className="insight-section">
              <strong className="small">{title}</strong>
              <ul>
                {list.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ul>
            </div>
          ))}
        <p className="muted small">
          {item.model}
          {item.seconds !== undefined && ` · ${item.seconds.toLocaleString("pt-BR")} s`}
        </p>
      </li>
    );
  }
  return (
    <li className={`insight alerta ${item.level}`}>
      <div className="insight-head">
        <span className="badge">{item.level === "atencao" ? "Atenção" : "Alerta"}</span>
        {item.team !== null && (
          <span className="small team-tag">
            <span className="swatch" style={{ background: colors[item.team] }} />
            {TEAM_NAMES[item.team]}
          </span>
        )}
        <span className="muted small">{when}</span>
      </div>
      <p>{item.text}</p>
    </li>
  );
}

/** Feed de insights: alertas por regra na hora e a análise do LLM local a cada poucos minutos. */
export function InsightsPanel({ info, colors, send }: Props) {
  const items = [...(info?.items ?? [])].reverse();
  return (
    <section className="card insights-card">
      <h2>Insights e dicas</h2>
      {info ? <LlmStatus llm={info.llm} send={send} /> : <p className="muted small">Aguardando o backend...</p>}
      {items.length === 0 ? (
        <p className="muted small insights-empty">
          Os alertas aparecem quando algo se repete por alguns minutos, como a linha de defesa alta ou o ataque
          sempre pelo mesmo lado. A análise do LLM chega a cada {info ? info.llm.intervalS / 60 : 4} minutos com jogo
          analisado.
        </p>
      ) : (
        <ol className="insights-feed" aria-live="polite">
          {items.map((item) => (
            <Item key={item.id} item={item} colors={colors} />
          ))}
        </ol>
      )}
    </section>
  );
}
