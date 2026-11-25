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
saída para o jogo segue no tempo nesse meio: a Rubber Band solta o interpretador enquanto estica. Medido em 25/11 com
o `dev/mede_esticamento.py`, contra o mesmo esticamento num processo auxiliar abaixo do normal (como o `--andamento`),
com o mesmo áudio (os pares da banca que esticam: seco, fade e dois) e a mesma carga, o `Injetor` de verdade
escrevendo no `AnelFalso` num processo à parte e a folga de 30 ms do anel:

| carga (8 núcleos) | modo | passagens | secas | pior volta | plano (mediana, maior) | no tempo |
|---|---|---|---|---|---|---|
| nenhuma | local | 9 | 0 | 13,2 ms | 6,9 s, 10,4 s | 9 |
| nenhuma | auxiliar | 9 | 0 | 8,1 ms | 6,8 s, 12,2 s | 9 |
| 8 processos | local | 6 | 0 | 14,5 ms | 7,1 s, 9,9 s | 6 |
| 8 processos | auxiliar | 6 | 0 | 4,2 ms | sem resposta em 20 s | 0 |
| 16 processos | local | 3 | 0 | 5,5 ms | 3,2 s e 7,1 s nos dois que esticaram | 2 |
| 16 processos | auxiliar | 3 | 0 | 14,6 ms | sem resposta em 20 s | 0 |
| 8 processos | auxiliar na prioridade normal | 6 | 0 | 13,0 ms | 9,3 s, 17,6 s | 5 |

Nenhum modo secou o anel, então o auxiliar não tem seca a tirar, e perde o prazo do plano: abaixo do normal, com a
CPU ocupada (o jogo), ele não responde, e toda passagem fica só de volume; sem carga, numa rodada anterior, perdeu o
prazo uma vez em 9. Na prioridade normal, ele deixa o plano mais lento (divide a CPU com o jogo de igual para igual, e
o motor roda acima do normal), e o do par dois ficou pronto depois da rampa da que sai (só de volume). Por isso o esticamento fica no
processo. No dobro da carga, o par dois local ficou só de volume por outro motivo (o áudio decodificou devagar e não
deu tempo de a que sai mudar de andamento). A única seca das medidas foi na primeira passagem de cada processo, a do
par seco (uma parada de ~30 ms), com o esticamento local ou no auxiliar: é o resto do planejador na primeira vez, e
não a Rubber Band (com o par fade na frente, ela não aparece). A medida foi neste PC, com o `AnelFalso` e o
`Injetor`, sem aparelho, sem o anel `Global\` e sem o filtro registrado; num Windows de teste com o filtro e um jogo
de verdade, a ferramenta é a mesma.
