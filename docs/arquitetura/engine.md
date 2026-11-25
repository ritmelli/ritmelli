# O motor de áudio (`engine.py`)

As contas da passagem que não leem áudio moram no `transicao.py`: o fim, o começo e o corpo de cada disco pelo
nível dos blocos, a escolha entre fade e final seco, a entrada do próximo na passagem de DJ e os tempos a partir das
grades e fases já medidas (a velocidade de cada lado, a batida em que o próximo cai, a virada e a troca de grave). O
motor lê o áudio, mede a fase antes e depois de esticar, estica, põe o eco, filtra o grave e monta os blocos. O
`dev/testa_transicao.py` roda o `transicao.py` sobre as chamadas que o motor gravou nos pares da banca das passagens.

`engine.py`: mistura em WASAPI 48 kHz, blocos de 10 ms; ffmpeg decodifica; voz com no
máximo ~80 ms de atraso; `MockEngine` sem áudio para teste (o relógio de 10 ms dele chama o `_mixa`; com o
`relogio = False`, que o `server.App(..., relogio=False)` passa antes de ligar, quem chama é o teste). O Windows converte os 48 kHz
para a taxa de cada aparelho (sem isso, um aparelho a 44,1 kHz recusava o stream). Se o
áudio não abre ao ligar (sem microfone nenhum, por exemplo), o servidor sobe mesmo assim com o
erro na tela e tenta de novo logo depois e quando a lista de aparelhos muda. Com a lista parada, o vigia só reabre
o áudio quando o filtro do microfone em uso para de ler com o motor ainda capturando o mesmo microfone: depois de 10 s
sem leitor, a cada 30 s, no máximo 3 vezes, e o leitor que volta zera a conta; o microfone que nunca teve leitor (sem o
filtro), o leitor que volta sozinho, o motor fechado e a troca manual não reabrem nada. Áudio de
até 15 s (buzina, bordão) toca por cima da música em vez de trocar, e o posto nos Sons
rápidos pela mão
também, inteiro até 2 min: vários juntos, no volume da música,
o repetido sai na hora (fica decodificado na memória), e o pausar e o parar calam todos.
O `abaixa` abaixa a música no jogo por um prazo, sem gravar nada (o fone segue igual), com uma rampa de um bloco
na ida e na volta para não estalar; no fim do prazo, ela volta sozinha. O `sinal` toca um bipe curto de teste no
jogo, fora do volume da música, e nunca com a voz cortada.
O volume automático (`sonoridade.py`) leva toda música a -11 LUFS, como o Spotify: a mais alta
desce até ele, e a mais baixa sobe, no máximo +9 dB, com um ganho por deck no misturador (rampa de 6 dB/s quando a medida chega com o
disco tocando, ou quando a chave muda) e um limitador com 2 ms de antecipação que só age no que
o ganho acrescentou acima de 0 dBFS: a música que desce, mesmo a que decodifica acima de 0 dBFS (+3,6
na The Real Slim Shady), nunca passa por ele, e todas saem 2 ms atrasadas, sempre. O arquivo se mede inteiro pelo
`ebur128` do ffmpeg, num processo abaixo do normal (o cálculo no processo do servidor seguraria o
interpretador do áudio); o stream, no próprio leitor, com uma estimativa aos 8 s e aos 30 s e a
medida inteira no fim da primeira vez que toca do começo ao fim. A medida fica no `library.json`
(`lufs`) ou, sem o disco na prateleira, no `sonoridades.json` do `--data-dir`; o servidor mede
a prateleira aos poucos. Na prateleira de 14/11, as músicas iam de -19,2 a -5,3 LUFS (mediana
-9,3); o alvo de -11 (o do modo "Alto" do Spotify, que também sobe com limitador) deixa o Sultans
of Swing (+3,1 dB) com 0,2% do tempo acima de 3 dB de limitação, e em -10 seriam 2,7%.
`dev/testa_ganho.py` testa a medida, o limitador e o motor sem som.

O esticamento da passagem no tempo (o `esticar` e o `esticar_saida`, a velocidade como no vinil e o tom de volta pela
Rubber Band do pedalboard) fica no processo do motor, na thread do planejador. Ele leva de 2 a 8 s por passagem, e a
saída para o jogo segue no tempo nesse meio: a Rubber Band solta o interpretador quase o tempo todo enquanto estica
(a pior volta da thread do anel foi de 14 ms, com 30 ms de folga). Medido em 25/11 com o `dev/mede_esticamento.py`,
contra o mesmo esticamento num processo auxiliar abaixo do normal (como o `--andamento`), com o mesmo áudio (os pares
da banca que esticam: seco, fade e dois), a mesma carga e a mesma janela de contagem (20 s desde o `preparar`, ou até
meio segundo depois da decisão, se ela vier mais tarde). As secas são as do `Injetor` (o anel vazio quando a thread
voltou) e as faltas, as do `AnelFalso` num processo à parte (os 10 ms que o leitor não achou). O prazo do auxiliar é o
do motor: a resposta que chega a menos de 0,3 s da virada o motor já recusaria, e a passagem fica só de volume.

| carga (8 núcleos) | modo | passagens | secas | faltas | pior volta | plano (mediana, maior) | no tempo |
|---|---|---|---|---|---|---|---|
| nenhuma | local | 6 | 0 | 0 | 14,2 ms | 7,2 s, 10,2 s | 6 |
| nenhuma | auxiliar | 6 | 0 | 0 | 7,6 ms | 7,3 s, 11,9 s | 6 |
| 8 processos | local | 6 | 0 | 0 | 8,9 ms | 7,5 s, 10,7 s | 6 |
| 8 processos | auxiliar | 6 | 0 | 0 | 6,1 ms | sem resposta em ~31 s (o prazo) | 0 |
| 8 processos | auxiliar na prioridade normal | 6 | 0 | 0 | 16,9 ms | 9,0 s, 15,2 s | 4 |
| 16 processos | local | 3 | 0 | 0 | 6,1 ms | 7,2 s e 3,3 s nos dois que esticaram | 2 |
| 16 processos | auxiliar | 3 | 0 | 0 | 19,4 ms | sem resposta em ~27 s (o prazo) | 0 |

Nenhum modo secou o anel nem deixou o leitor sem som, então o auxiliar não tem seca a tirar, e perde o prazo do plano:
abaixo do normal, com a CPU ocupada (o jogo), ele não respondeu até a virada em nenhuma passagem, e toda passagem ficou
só de volume. Na prioridade normal, ele deixa o plano mais lento (divide a CPU com o jogo de igual para igual, e o
motor roda acima do normal), e o do par dois ficou pronto depois do começo da rampa da que sai nas duas vezes (só de
volume), quando o local fica pronto antes dela. Sem carga, os dois modos empatam; numa rodada anterior, o auxiliar
perdeu a rampa do par dois uma vez em 9. Por isso o esticamento fica no processo. No dobro da carga, o par dois
ficou só de volume nos dois modos por outro motivo, antes de esticar (o áudio decodificou devagar e não deu tempo de a
que sai mudar de andamento). Fora da conta, a primeira passagem de cada processo, a do par seco, parou o
interpretador ~30 ms e secou uma vez; nas rodadas anteriores, isso aconteceu também com o auxiliar na frente, então
provavelmente é o resto do planejador na primeira vez, e não a Rubber Band.

Os limites da medida: foi neste PC, com o `AnelFalso` (um leitor simulado de 480 quadros a cada 10 ms) e o `Injetor`,
sem aparelho, sem o anel `Global\` e sem o filtro registrado; a ferramenta usa o `AnelFalso` também num PC com o
filtro, então o `audiodg` e um jogo de verdade ficam de fora. E nos pares da banca a virada fica ~33 s depois do
`preparar`, e o app prepara 3 min antes do fim: lá o auxiliar abaixo do normal teria mais tempo, e isso não foi
medido (a decisão não depende disso, porque não houve seca a tirar).
