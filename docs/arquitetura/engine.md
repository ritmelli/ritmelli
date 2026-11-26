# O motor de áudio (`engine.py`)

As contas da passagem que não leem áudio moram no `transicao.py`: o fim, o começo e o corpo de cada disco pelo
nível dos blocos, a escolha entre fade e final seco, a entrada do próximo na passagem de DJ e os tempos a partir das
grades e fases já medidas (a velocidade de cada lado, a batida em que o próximo cai, a virada e a troca de grave). O
motor lê o áudio, mede a fase antes e depois de esticar, estica, põe o eco, filtra o grave e monta os blocos. Quando
a que sai acelera para casar com a próxima, o trecho em que a fase dela é medida começa mais cedo no disco, para durar
pelo menos `FASE_MIN_S` na saída já acelerada (#196): o começo dele é o `transicao.phase_excerpt_start`, que o motor
chama. O `dev/testa_transicao.py` roda o `transicao.py` sobre as chamadas que o motor gravou nos pares da banca das
passagens e roda o `phase_excerpt_start` com a que sai a `1 ± SAI_MAX`, conferindo que o trecho não entra na rampa
dela (`transicao.rampa_saida`) e dura pelo menos `FASE_MIN_S` (#208). O JSON guarda uma impressão digital da banca
(os tokens do `dev/testa_passagem.py`, sem comentários e docstrings), e o teste reprova quando a banca mudou desde a
gravação: o `--grava` regrava.

Nada pesado no processo do áudio: o bloco é de 10 ms, e o que segura o interpretador estala o som no jogo.
Biblioteca lenta ou conta longa vai para um processo auxiliar, como o `yt_fora.py` (`ritmelli.py --yt`) e o
`andamento.py` (`ritmelli.py --andamento`), que o servidor abre pelo `auxiliar` do `server.py`.

`engine.py`: mistura em WASAPI 48 kHz, blocos de 10 ms; ffmpeg decodifica; voz com no
máximo ~80 ms de atraso; `MockEngine` sem áudio para teste (o relógio de 10 ms dele chama o `_mixa`; com o
`relogio = False`, que o `server.App(..., relogio=False)` passa antes de ligar, quem chama é o teste). O Windows converte os 48 kHz
para a taxa de cada aparelho (sem isso, um aparelho a 44,1 kHz recusava o stream). Se o
áudio não abre ao ligar (sem microfone nenhum, por exemplo), o servidor sobe mesmo assim com o
erro na tela e tenta de novo logo depois e quando a lista de aparelhos muda. Com a lista parada, o vigia só reabre
o áudio quando o filtro do microfone em uso para de ler com o motor ainda capturando o mesmo microfone: depois de 10 s
sem leitor, a cada 30 s, no máximo 3 vezes, e o leitor que volta zera a conta; o microfone que nunca teve leitor (sem o
filtro), o leitor que volta sozinho, o motor fechado e a troca manual não reabrem nada. Na
primeira vez com o filtro pronto, o motor confere de novo os aparelhos que o instalador ou a tarefa
acharam mudos (#136, em `microfone.md`) e, depois de preparar um microfone novo pela tarefa,
todos: a conferência roda num processo à parte (`--microfone confere`), para não abrir aparelhos
no PortAudio dos streams do motor, e o aparelho que abre e não entrega som vira um aviso dos
aparelhos, que sai quando o áudio reabre. Áudio de
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
a prateleira aos poucos. Todo ffmpeg da medida passa pelo `mede_arquivo`, e o servidor, ao desligar, mata e espera
os que ainda medem (`stop_measurements`): nenhum fica segurando um arquivo depois que ele sai (`dev/test_mock_stop.py`). Na prateleira de 14/11, as músicas iam de -19,2 a -5,3 LUFS (mediana
-9,3); o alvo de -11 (o do modo "Alto" do Spotify, que também sobe com limitador) deixa o Sultans
of Swing (+3,1 dB) com 0,2% do tempo acima de 3 dB de limitação, e em -10 seriam 2,7%.
`dev/testa_ganho.py` testa a medida, o limitador e o motor sem som; o custo do `_mixa` com o ganho e o limitador vale
pela mediana de 400 blocos e pela média sem os 4 mais lentos (uma ou duas chamadas que a máquina segura por dezenas de
ms mexem na média, não no custo de cada bloco; uma lentidão que volta a cada poucos blocos segue reprovando).

O esticamento da passagem no tempo (o `esticar` e o `esticar_saida`, a velocidade como no vinil e o tom de volta pela
Rubber Band do pedalboard) fica no processo do motor, na thread do planejador. Ele leva de 2 a 8 s por passagem, e a
saída para o jogo segue no tempo nesse meio: a Rubber Band solta o interpretador quase o tempo todo enquanto estica
(a pior volta da thread do anel, com ela no processo, foi de 8 ms, com 30 ms de folga). Medido em 25/11 com o
`dev/mede_esticamento.py`, contra o mesmo esticamento num processo auxiliar abaixo do normal (como o `--andamento`),
com o mesmo áudio (os pares da banca que esticam: seco, fade e dois), a mesma carga e a mesma janela de contagem nos
dois modos: do `preparar` até A chegar a 0,2 s da virada que a banca calcula para o par (~32 s, pela posição de A),
depois do corte do auxiliar e antes da virada.
As secas são as do `Injetor` (o anel vazio quando a thread voltou) e as faltas, as do `AnelFalso` num processo à
parte (os 10 ms que o leitor não achou). O prazo do auxiliar é o do motor: a espera por ele só corta quando A chega a
0,3 s da virada, onde o motor já recusaria a resposta, e a passagem fica só de volume.

| carga (8 núcleos) | modo | passagens | secas | faltas | pior volta | plano (mediana, maior) | no tempo |
|---|---|---|---|---|---|---|---|
| nenhuma | local | 6 | 0 | 0 | 8,1 ms | 6,8 s, 9,2 s | 6 |
| nenhuma | auxiliar | 6 | 0 | 0 | 18,3 ms | 6,6 s, 10,2 s | 6 |
| 8 processos | local | 6 | 0 | 0 | 8,0 ms | 7,2 s, 9,7 s | 6 |
| 8 processos | auxiliar | 6 | 0 | 0 | 4,6 ms | sem resposta até o prazo (~31 s) | 0 |
| 8 processos | auxiliar na prioridade normal | 6 | 0 | 0 | 11,6 ms | 8,9 s, 13,8 s | 6 |
| 16 processos | local | 3 | 0 | 0 | 6,4 ms | 7,4 s e 3,4 s nos dois que esticaram | 2 |
| 16 processos | auxiliar | 3 | 0 | 0 | 4,0 ms | sem resposta até o prazo (~27 s) nos dois | 0 |

Nenhum modo secou o anel nem deixou o leitor sem som, então o auxiliar não tem seca a tirar, e perde o prazo do plano:
abaixo do normal, com a CPU ocupada (o jogo), ele não respondeu até a virada em nenhuma passagem, e toda passagem ficou
só de volume. Na prioridade normal, ele responde, mais devagar (divide a CPU com o jogo de igual para igual, e o motor
roda acima do normal): o plano do par dois levou 13,1 e 13,8 s, contra 9,7 s no local, e numa rodada anterior ele ficou
pronto depois do começo da rampa da que sai nas duas vezes (só de volume). Sem carga, os dois modos empatam; numa
rodada anterior, o auxiliar perdeu a rampa do par dois uma vez em 9. Por isso o esticamento fica no processo. No dobro
da carga, o par dois ficou só de volume nos dois modos por outro motivo, antes de esticar (o áudio decodificou devagar
e não deu tempo de a que sai mudar de andamento). Fora da conta, a primeira passagem de cada processo, a do par seco,
parou o interpretador ~30 ms e secou uma vez; nas rodadas anteriores, isso aconteceu também com o auxiliar na frente,
então provavelmente é o resto do planejador na primeira vez, e não a Rubber Band.

Os limites da medida: foi neste PC, com o `AnelFalso` (um leitor simulado de 480 quadros a cada 10 ms) e o `Injetor`,
sem aparelho, sem o anel `Global\` e sem o filtro registrado; a ferramenta usa o `AnelFalso` também num PC com o
filtro, então o `audiodg` e um jogo de verdade ficam de fora. E nos pares da banca a virada fica ~33 s depois do
`preparar`, e o app prepara 3 min antes do fim: lá o auxiliar abaixo do normal teria mais tempo, e isso não foi
medido (a decisão não depende disso, porque não houve seca a tirar). Nos PCs de quem usa, quem diz se isso muda é o
evento "audio" da telemetria (o `secas_esticamento`, as secas com a Rubber Band em curso): com secas ali, a medida
se repete, com a mesma ferramenta, num Windows de teste com um jogo.

A saída da Rubber Band vem alinhada com a entrada, mas só soa depois de uns 45 ms: o `esticar_saida` não mede atraso
nenhum, e os primeiros `RUBBER_BAND_WARMUP` (60 ms) dele são o próprio áudio reamostrado, que passa para o da Rubber
Band em `RUBBER_BAND_CROSSFADE`. O `dev/test_stretch_outgoing.py` confere a posição dos ataques com um tom forte por
baixo deles (#197), o tom de volta ao original depois da rampa, o nível sem buraco no começo, com ruído de banda
larga, e a entrada mais curta que o aquecimento. O mesmo nível no começo do `esticar`, o lado da próxima, que ainda
sai mudo, roda ali como falha conhecida da #264: passa a contar quando passar.

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
mudança só: a faixa, a linha, a posição, o fim e a passagem desfeita (no `load`, também o Repetir pedido: o leitor da
faixa nova já o encontra ligado; sem o pedido, o disco que entra no lugar de outro o desliga). O `seek` limita a posição
pela duração da faixa e o `resume` confere o fim no mesmo trecho da trava. O `trocar_fonte` publica no mesmo trecho a
faixa e o ganho novos, na mesma linha (da espera para o stream, também a posição e a passagem desfeita; do stream para o
arquivo, sempre com o leitor novo do arquivo, salvo o disco que já acabou, e a passagem preparada sai; o religar do
stream a mantém). A faixa nova pode vir como uma função, que o `trocar_fonte` (e o `load` e o `preparar`, para o segundo
deck) chama nesse trecho do `_qlock`: o arquivo da prateleira entra com o nome que ela tem na hora da troca, mesmo que o
disco tenha sido renomeado depois de quem pediu a troca o ler. A medida do ganho e o leitor ficam fora das travas, e o
leitor que acaba só marca o fim, ou o erro, se ainda é o leitor do deck; o Repetir e o fim do leitor se decidem no mesmo
trecho do `_qlock`. A leitura vazia de um arquivo que começou nos últimos `FILE_TAIL_S` dele é o fim do disco quando o
ffmpeg sai sem erro, e não um erro de leitura (com o Repetir, o arquivo volta do 0). O stream de um disco com download
que não dá áudio marca a espera do arquivo no deck (`file_wait`, o gen daquele leitor; o `esperando_arquivo` confere que
ainda é o do prato) e passa o disco ao servidor pelo gancho do `on_silent_stream`, sem marcar o fim; o que para antes do
fim ainda marca o fim ali, e o arquivo que chega depois fica sem leitor (#294). O `load`, o `espera` e o `stop` devolvem
a `Captura` do que estava no prato logo antes: a posição que o servidor grava (`remember_pos`) é a desse instante. O
`load`, o `espera`, o `stop`, o `seek` e o `preparar` aceitam um `pode()`, conferido sob o `_qlock` antes de mudar
qualquer coisa: falso, nada muda (o servidor confere ali a reserva de avanço, a primeira da fila, o deck e a linha que
viu; ver [comandos.md](comandos.md)). Quem chama com as travas dele na mão passa também o `ganho` já medido e uma lista
`depois`, onde fica o resto do comando (o leitor que começa, a onda, a medida), que ele roda ao soltá-las.

O servidor confere a linha pela interface do motor, e não pelos campos de dentro: o `line()` dá a `Line` (o deck e a
linha do prato, os mesmos dois campos da `Captura`), e o `on_line(t)` diz, sob o `_qlock`, se o prato ainda é a linha de
`t`. A virada que o motor fez sozinho sai pelo `take_switch` (sob o `_qlock`, só a que ainda é a pendente), a passagem
preparada pelo `drop_prepared` (sob o `_qlock`; o `cancelar_pronto` pega a trava), o ganho medido antes das travas pelo
`gain_for`, o nome novo do disco no prato e no segundo deck pelo `update_track` (no próprio dicionário de cada um, sob o
`_qlock`: quem o guarda, como o download que vai entregar o arquivo, ainda guarda o disco do prato), a faixa, a posição,
o estado e a virada de uma leitura só pelo `platter_state` e os arquivos que o motor lê pelo `tracks_in_use`. Quem
precisa do `_qlock` junto com o estado dele (o servidor e os comandos) o pega pelo `state_section()`, que segura a trava
no corpo do `with` e não a entrega; o `_lock` vem pelo `with_lock(outer, f)`, que pega a trava de fora (a `fila_lock` do
`App`) e nunca espera o `_lock` com ela na mão, na ordem de [As travas](comandos.md#as-travas). A falha de preparar a
próxima sai pelo `take_prepare_failure` (lida e limpa sob o `_qlock`), e o erro da tela entra pelo `set_error`; o aviso
do stream entra pelo `warn_on`, num lugar à parte: o `error` (só se lê) dá o erro e, sem ele, o aviso do stream, que sai
na troca para o arquivo, no `_restart` e no `stop`. O `snapshot` não traz o estado, a faixa nem a duração: o servidor lê
os três com a posição e a fila numa captura só (`App.leitura`).

A pausa vale no limite entre blocos. O `pause` devolve uma `Pausa`: com um bloco do prato retirado e ainda não
publicado (o do disco, o do fim ou só o da passagem soando), ela fica pendente (o prato só pausa na confirmação) e se
confirma na publicação dele; sem bloco, na hora. O `alterna` (o botão principal) decide e age no mesmo trecho do
`_qlock`: uma pausa pendente conta como pausa, e o segundo toque a retoma. A confirmação guarda a faixa e a posição
daquele instante, e o servidor grava essa posição só se a pausa ainda vale (a mesma linha, sem retomar nem trocar de
disco no meio). O `resume`, o `load`, o `stop`, o `seek`, o fim do disco e o `close` resolvem o pedido pendente como
substituído, sem gravar nada.
