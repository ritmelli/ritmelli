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

## O bloco e a linha de reprodução

Cada `Deck` tem uma linha de reprodução, um contador que o `load`, o `stop`, o `seek` e o `resume` que recomeça do fim
sobem. O `_mixa` faz cada bloco em três passos. O `_captura`, sob o `_qlock`, confere a próxima preparada e a condição
da virada (e vira ali mesmo, no `_vira`), tira o bloco do prato e copia o estado da passagem (a próxima subindo, o que
sai, o eco, o ganho do disco) e o do limitador. O `_renderiza` faz o som fora da trava, só sobre as cópias. O
`_publica`, de novo sob o `_qlock`, só aplica a posição, o fim, o primeiro som, o avanço da passagem, do ganho e do
limitador se o deck e a linha do bloco ainda forem os do prato; senão, a música daquele bloco sai e nada dele vale (nem
o pedido de zerar o limitador, que fica para a linha nova). O `_gen` do leitor é outra coisa: ele só para o
decodificador substituído. A troca do stream pelo arquivo (`trocar_fonte`) sobe o `_gen` e mantém a linha, então o
bloco em curso publica, e o leitor novo começa depois do último bloco decodificado, ou depois do bloco em curso quando
a fila já está vazia.

O `load`, o `espera`, o `stop`, o `seek` e o `resume` que recomeça do fim publicam a troca sob o `_qlock`, como uma
mudança só: a faixa, a linha, a posição, o fim e a passagem desfeita. O `seek` limita a posição pela duração da faixa
e o `resume` confere o fim no mesmo trecho da trava. O `trocar_fonte` publica no mesmo trecho a faixa e o ganho novos,
na mesma linha (da espera para o stream, também a posição e a passagem desfeita; com leitor novo, a passagem preparada
na fonte de antes sai). A medida do ganho e o leitor ficam fora das travas, e o leitor que acaba só marca o fim, ou o
erro, se ainda é o leitor do deck; o Repetir e o fim do leitor se decidem no mesmo trecho do `_qlock`. O `load`, o
`espera` e o `stop` devolvem a `Captura` do que estava no prato logo antes: a posição que o servidor grava
(`remember_pos`) é a desse instante.

A pausa vale no limite entre blocos. O `pause` devolve uma `Pausa`: com um bloco do prato retirado e ainda não
publicado (o do disco, o do fim ou só o da passagem soando), ela fica pendente (o prato só pausa na confirmação) e se
confirma na publicação dele; sem bloco, na hora. O `alterna` (o botão principal) decide e age no mesmo trecho do
`_qlock`: uma pausa pendente conta como pausa, e o segundo toque a retoma. A confirmação guarda a faixa e a posição
daquele instante, e o servidor grava essa posição só se a pausa ainda vale (a mesma linha, sem retomar nem trocar de
disco no meio). O `resume`, o `load`, o `stop`, o `seek`, o fim do disco e o `close` resolvem o pedido pendente como
substituído, sem gravar nada.
