import type { PlaysInfo, TeamTactics } from "./backend";

interface Props {
  tactics: Record<string, TeamTactics> | undefined;
  names: [string, string];
  colors: [string, string];
}

const PLAY_ROWS: { label: string; value: (p: PlaysInfo) => string }[] = [
  { label: "Cruzamentos para a área", value: (p) => String(p.counts.cruzamento) },
  { label: "Entradas na área com a bola dominada", value: (p) => String(p.counts.entrada) },
  { label: "Chutes de fora da área", value: (p) => String(p.counts.chute_fora) },
  { label: "Chutes de dentro da área", value: (p) => String(p.counts.chute_dentro) },
  {
    label: "Pelo lado, corta para dentro (esq. / dir.)",
    value: (p) => `${p.bySide.corta_dentro.esquerda} / ${p.bySide.corta_dentro.direita}`,
  },
  {
    label: "Pelo lado, vai ao fundo (esq. / dir.)",
    value: (p) => `${p.bySide.vai_fundo.esquerda} / ${p.bySide.vai_fundo.direita}`,
  },
];

function TeamColumn({ info, name, color }: { info: TeamTactics | undefined; name: string; color: string }) {
  return (
    <div className="tactics-team">
      <h3>
        <span className="swatch big" style={{ background: color }} />
        {name}
      </h3>
      {!info ? (
        <p className="muted small">Aguardando dados.</p>
      ) : (
        <>
          <section className={`tactics-block changes ${info.changes.length ? "has" : ""}`}>
            <h4>Mudanças nos últimos 10 minutos</h4>
            {info.changes.length ? (
              <ul>
                {info.changes.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            ) : (
              <p className="muted small">Nenhuma mudança clara em relação ao começo do jogo.</p>
            )}
          </section>

          <section className="tactics-block">
            <h4>Posições</h4>
            {info.positions.length ? (
              <ul>
                {info.positions.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            ) : (
              <p className="muted small">Aparece quando houver padrão de ataque e de defesa.</p>
            )}
          </section>

          <section className="tactics-block">
            <h4>Saída de bola</h4>
            <p className="small">
              {info.buildUp.text ?? "Ainda sem lances com a defesa inteira na imagem e a bola no próprio terço."}
            </p>
          </section>

          <section className="tactics-block">
            <h4>Bola no ataque</h4>
            {info.plays.texts.length > 0 && (
              <ul>
                {info.plays.texts.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
            <table className="compare plays">
              <thead>
                <tr>
                  <th scope="col">Jogada</th>
                  <th scope="col">Partida</th>
                  <th scope="col">Últimos 10 min</th>
                </tr>
              </thead>
              <tbody>
                {PLAY_ROWS.map((row) => (
                  <tr key={row.label}>
                    <th scope="row">{row.label}</th>
                    <td>{row.value(info.plays.partida)}</td>
                    <td>{row.value(info.plays.recentes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

/** Leitura tática dos dois times, lado a lado. */
export function TacticsPanel({ tactics, names, colors }: Props) {
  return (
    <section className="card tactics-card">
      <h2>Leitura tática</h2>
      <div className="tactics-grid">
        {([0, 1] as const).map((t) => (
          <TeamColumn key={t} info={tactics?.[String(t)]} name={names[t]} color={colors[t]} />
        ))}
      </div>
      <p className="muted small">
        As posições são médias de quem ocupa cada região do campo (LE, VOL, MEI...), com o time sempre atacando para
        a direita; esquerda e direita são do ponto de vista do time. As jogadas são contadas pelo caminho da bola
        quando ela aparece na imagem, então os números são aproximados. "Últimos 10 min" compara com o que veio antes.
      </p>
    </section>
  );
}
