# Documentação técnica do FC Analytics

Esta pasta descreve o projeto por dentro, com detalhe suficiente para um agente de IA (ou uma pessoa) trabalhar no código sem precisar redescobrir tudo. O manual de uso para quem usa o app é o [`README.md`](../README.md) da raiz; as regras de trabalho para agentes estão no [`AGENTS.md`](../AGENTS.md).

## Ordem de leitura sugerida

1. [Visão geral](01-visao-geral.md): o que o produto faz, as fases em que foi construído, princípios e glossário de futebol usado no código.
2. [Arquitetura](02-arquitetura.md): os componentes, o caminho de um frame da aba até o painel e as threads de fundo.
3. [Backend](03-backend.md): módulo por módulo, com as classes, constantes e variáveis de ambiente.
4. [Algoritmos](04-algoritmos.md): como cada análise é calculada, com os limiares.
5. [Protocolo](05-protocolo.md): formato binário dos frames, todas as mensagens do WebSocket e os endpoints HTTP.
6. [Dados](06-dados.md): banco SQLite, metadados da partida, arquivos em disco e o ciclo de vida da partida.
7. [Frontend](07-frontend.md): componentes React, estado da página, captura, campo 3D, campinho animado, relatório.
8. [App do Windows e release](08-app-windows-e-release.md): app de controle, instalação, atualizações e o pipeline que publica nos Releases.
9. [Desenvolvimento](09-desenvolvimento.md): ambiente, testes, previews de tela e receitas para as mudanças mais comuns.
10. [Limitações e roadmap](10-limitacoes-e-roadmap.md): o que é aproximado, dívidas técnicas conhecidas e ideias para as próximas fases.

## Convenções desta documentação

- Nomes de arquivos, funções, constantes e mensagens aparecem como `código`, exatamente como estão no repositório.
- Valores de limiares citados aqui vêm das constantes do código no momento em que a documentação foi escrita (versão 0.8.1). Se você mudar uma constante, atualize o doc correspondente.
- "Time A" e "Time B" correspondem aos índices `0` e `1` em todo o código.
