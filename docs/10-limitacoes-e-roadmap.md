# 10. Limitações, dívidas técnicas e roadmap

## O que é aproximado (e precisa continuar dito na interface)

- **A câmera da TV não mostra o campo inteiro.** Padrões, estatísticas e movimentação usam quem aparece na imagem (e quem saiu há poucos segundos). Posições longe da bola têm menos dados; na movimentação elas aparecem como `estimated`.
- **As posições são médias de regiões, não jogadores identificados.** Os IDs recomeçam a cada corte de câmera; "LE" é a posição média de quem ocupa a lateral esquerda, não um jogador com nome.
- **Tudo que depende da bola** (posse, passes, cruzamentos, chutes, conduções) só conta quando a bola aparece de fato. Em lances com a bola escondida ou muito rápida, as contagens ficam abaixo do real.
- **Distância percorrida** fica bem abaixo da real (só quem aparece, com limites de velocidade).
- **Formação** em jogos com o time muito espalhado pode sair estranha; a contagem da linha de defesa e a escolha manual corrigem.
- **Relógio** é o do app (começa ao criar a partida), não o do jogo.

## Dívidas técnicas conhecidas

| Item | Onde | Observação |
| --- | --- | --- |
| Padrões refeitos do SQLite sem a área da câmera | `Pipeline.rebuild_patterns` | a contagem da linha de defesa e a saída de bola não voltam depois de reiniciar (só as posições); seria preciso gravar o polígono `view` por frame |
| Estado `livre` e comando `new_match` | `stats.py`, `main.py` | herança de antes do botão Criar partida; o painel não usa mais `new_match` |
| `ballArrows` com `numpy.float64` | `flows.ball_arrows` | serializa como número normal, mas vale converter para `float` |
| `summary` dos padrões disputa o GIL | `PatternStore.summary` (10 s) | k-means e casamento por frame em Python; o cache da movimentação já ajuda; se pesar, mover para processo separado |
| `test_ws.py` baixa o modelo do campo | `lifespan` cria o `PitchDetector` | seria bom injetar um detector de campo falso no teste |
| Sem testes no frontend | `frontend/` | só o `tsc`; os previews (`tools/preview`) ajudam na parte visual |
| Modelos vêm do Google Drive do roboflow/sports | `detector.py`, `pitch.py` | se o link mudar, o download quebra; considerar espelhar nos Releases (licença AGPL permite redistribuir com o código aberto) |
| Atualizações pela API do GitHub sem token | `launcher/MainWindow.cs` | limite de 60 pedidos/hora por IP |
| Instalador sem assinatura digital | release | aviso do SmartScreen na instalação |
| Licença AGPL do Ultralytics | detecção | ok para uso pessoal com código aberto; para virar produto fechado, trocar por RF-DETR (Apache 2.0) ou licença comercial |

## Ideias para as próximas fases

### IA generativa aprendendo com as partidas salvas

1. **Perfil de cada time**: ao finalizar uma partida, salvar um resumo (formações por fase, saída de bola, por onde ataca, cruzamentos × entradas, movimentação das posições) ligado à sigla do time. Na partida seguinte do mesmo time, mandar esse perfil para o LLM ("contra o PSG, o MCI costuma...") e comparar com o jogo atual.
2. **Comparação entre partidas** no relatório: o que mudou em relação aos jogos anteriores do time.
3. **Ajuste dos limiares pelos dados**: usar as partidas gravadas para calibrar limiares (linha alta, chuveirinho) por campeonato ou time.
4. **Perguntas livres**: um campo no painel para perguntar ao LLM sobre a partida, com o resumo e o histórico como contexto.

### Melhorias da análise

- Reidentificação dos jogadores entre cortes de câmera (aparência + número da camisa via OCR).
- Detectar gol e cartão automaticamente pela mudança do placar (OCR já existe).
- Gravar a área visível por frame para a retomada ficar completa.
- Exportar o relatório também em PDF direto.

### Outras áreas com o mesmo motor

O motor (detecção YOLO, tracking com IDs, cor por k-means em Lab, homografia para metros, padrões no tempo, alertas, LLM local, relatório) serve para outros vídeos com objetos que se movem num espaço medido. Ideias discutidas para a agricultura: contagem e comportamento de gado (o YOLO COCO já detecta vaca, ovelha e cavalo), maturação de frutos pela cor (café verde/cereja/passa), estimativa de safra andando na rua de plantio, falhas de plantio e daninhas por drone, contagem de pragas em armadilha adesiva, leitura de brincos/balança/placas por OCR, segurança da propriedade. A "partida" vira uma vistoria (talhão, lote) com o mesmo ciclo de criar, pausar, finalizar e relatório.
