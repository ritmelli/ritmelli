# Os comandos de música (`comandos.py`)

`comandos.py`: as operações de música do servidor, cada uma com a sua regra. As rotas do `server.py` leem o corpo,
chamam o comando e montam a resposta, que segue a mesma do [`API.md`](../../API.md). Quem não é rota, como os vigias
do `App`, chama o mesmo comando. Cada função recebe o `App`; a fila, o histórico e a `fila_lock` continuam nele.

| Comando | Rota | A regra que mora no comando |
| --- | --- | --- |
| `tocar` | `POST /api/play` | sem o `por_cima` no corpo, o som curto (até `CURTO_MAX_S`) toca por cima da música, só sem `start` e sem `resume`; com ele, o `por_cima` decide |
| `enfileirar` | `POST /api/queue` | com nada no prato (parado, ou o disco já acabou), o que entra toca na hora, num avanço reservado (se o fim do disco reservou antes, só guarda); pausado ainda é disco no prato |
| `tocar_da_fila` | `POST /api/queue/play` | a entrada sai da fila e toca |
| `tirar_da_fila` | `DELETE /api/queue/{qid}` | a parecida tirada pelo usuário não volta nesta sessão |
| `mover_na_fila`, `limpar_fila` | `POST /api/queue/move`, `DELETE /api/queue` | |
| `pular` | `POST /api/next` | o avanço da fila; logo depois de uma virada da passagem ainda não conciliada, a virada é o avanço, e ele devolve a entrada que acabou de entrar |
| `voltar` | `POST /api/prev` | o Anterior do `App` |
| `pausar`, `retomar`, `alternar` | `POST /api/pause`, `/api/resume`, `/api/toggle` | pausar espera o motor confirmar a pausa no limite entre blocos (sem trava e sem prender o laço do servidor) e grava a posição confirmada; o alternar pausa o que toca ou carrega e retoma o resto |
| `parar` | `POST /api/stop` | o disco parado entra no histórico, e o Anterior toca ele de novo; a posição gravada é a do instante em que ele saiu |
| `ir_para` | `POST /api/seek` | |
| `volume` | `POST /api/volume` | grava só o volume da música |

## O avanço da fila

O avanço é uma operação só, o `avanca`. Com a virada do motor (a passagem de DJ, em que o motor já trocou de deck
sozinho), a entrada da virada só sai da fila, e o disco que saiu entra no histórico. Sem virada, o avanço é reservado
na linha do prato (`Reserva`): há uma só reserva em curso por deck e linha (`App.reserva`). Passam por ele:

- o Próxima (`/api/next`);
- o fim do disco (`_volta_fila`);
- a virada da passagem (`_volta_passagem`);
- o stream da parecida que não abriu (`_abre_stream`), sem guardar no histórico;
- a parecida que chegou com o prato parado (`_volta_auto`);
- o enfileirar com o prato parado, para a entrada que acabou de entrar.

Sob a `fila_lock` e o `_qlock`, o avanço fecha antes a virada pendente e reserva a entrada para o deck e a linha do
prato, tirando a passagem preparada (o motor não vira para ela no meio). Tocar corre fora das travas, e a troca
(`App._troca`) confere de novo, sob elas, a reserva, a entrada e, no motor (o `pode` do `load` e do `espera`), o deck e
a linha: só aí a entrada sai da fila e o que saiu do prato entra no Anterior. Reserva invalidada (o prato trocou de
disco, a entrada saiu da fila) não toca nem grava histórico. Com outra reserva em curso na mesma linha, os vigias cedem
a vez (e conferem de novo na volta seguinte), e o Próxima e o enfileirar esperam o resultado dela, sem trava nenhuma,
numa thread do executor (as rotas não prendem o laço do servidor). A confirmação, o erro e a invalidação resolvem a
reserva uma vez só e liberam todos; a troca sem reserva (o tocar da prateleira, o Anterior) e o Parar soltam a reserva
em curso, e quem espera (não cede) vê a reserva de outro já em curso nesta linha antes de disputar a `fila_lock`. A
reserva segue em curso até resolver, mesmo depois de a troca dela publicar o disco numa linha nova (`Reserva.viva`). O
enfileirar e a parecida sem stream que esperaram uma reserva que não tocou tentam de novo na mesma linha do prato (a que
mudou no meio, como no Parar, fica como está); a parecida só para o prato com a fila vazia e sem avanço de outro em
curso, conferidos no `pode` do `stop`. A troca confere a reserva e a entrada antes de fechar a virada e tirar a passagem
preparada: a que já não vale não tira a preparada de quem vale. Os Próximos sobrepostos (o segundo chega antes de o
primeiro voltar, mesmo com o primeiro já trocando o disco) dividem o mesmo avanço (`App.proximo`), se o prato ainda é a
linha dele ou a que a reserva dele publicou: um só toca, e todos respondem a entrada dele. O Próximo depois de um Parar
segue sozinho. O avanço já em curso que o Próximo encontra ao chegar (o do fim do disco) e a virada pendente que ele vê
são o avanço dele, mesmo se terminarem antes de ele reservar; e o prato que muda de linha antes disso (o Parar) fica
como está. O Próxima com a virada pendente devolve a entrada dela; se ela já saiu da fila, segue para a primeira. No
`_volta_fila` e no `_volta_auto`, se tocar falhar, o erro vai para a tela (`engine.error`); em todos, a entrada quebrada
sai da fila, menos quando outra reserva em curso vai tocá-la. A gravação da posição que falha depois da troca não desfaz
o avanço.

O `POST /api/queue` põe na fila no laço do servidor, como o tocar e a prateleira (a procura do download do mesmo vídeo
e a criação de um novo não correm com outro pedido), e só o tocar na hora vai ao executor, com o prato visto no laço
logo depois de a entrada entrar: um Parar que chega antes da thread não vira um tocar.

Toda troca de disco passa pelo `App._troca`, sob a `fila_lock`: o Anterior, o Parar (que não troca, mas guarda) e o
tocar da prateleira fecham antes a virada pendente, e o Anterior guarda primeiro o que saiu nela; o Anterior escolhe
entre voltar ao começo e tocar o de antes com a faixa e a posição lidas no mesmo trecho do `_qlock` em que não há
virada, e a passagem preparada sai ali. A troca, o Parar e a publicação da preparação pegam a `fila_lock` e o `_lock` do
motor pelo `App._com_motor`, que nunca espera o `_lock` com a `fila_lock` na mão: com o `_lock` ocupado (a reabertura do
áudio, a troca de aparelho), solta a `fila_lock`, espera fora e tenta de novo, e a leitura do estado segue respondendo
enquanto um vigia ou uma rota no executor espera o `_lock` (as rotas que trocam no laço, como o `/api/play`, ainda
esperam ali, como antes). O ganho do disco que entra é medido antes, e o leitor que começa, a onda e a medida rodam
depois de soltar as duas (o `depois` do `load`, do `espera` e do `preparar`).

## A passagem e a cabeça da fila

A volta do `_volta_passagem` guarda o deck e a linha do prato que viu. A fonte da primeira da fila e o ganho dela saem
fora das travas (o endereço do stream leva 1 a 3 s), e a publicação (`preparar`) é sob a `fila_lock`: ela confere que
a entrada ainda é a primeira e, no `pode` sob o `_qlock`, que não há virada pendente nem avanço reservado em curso
nesta linha e que o prato ainda é o mesmo deck, a mesma linha e o mesmo disco, sem o Repetir, sem ter acabado e sem
nada preparado. Quem fecha a virada e troca o disco sob a `fila_lock` não vê uma preparação entrar no meio. Toda
mudança da fila (pôr, tirar, mover, limpar, a ordem do Automático, o Aleatório e o esquecer) acontece no mesmo trecho
do `_qlock` em que a passagem preparada é conferida (`_confere_preparo_sob`): a preparada para quem não é mais a
primeira sai ali, e o motor não vira para ela no meio. O Automático não reordena a primeira que um avanço reservado
vai tocar.

## As travas

A ordem é a `fila_lock` do `App`, depois o `_lock` do motor (um `RLock`), depois o `_qlock` do motor, nunca ao
contrário. Com o `_qlock` na mão não se chama método do motor que pegue o `_lock`. A thread do áudio (o `_mixa`) nunca
pega a `fila_lock` nem o `_lock`. Sob a `fila_lock` não se grava arquivo: o `andamentos.json` e o
`versoes_audio.json` são copiados sob ela e gravados fora dela. A medida entra na memória mesmo se a gravação falha
(quem lê esses dicionários depois a vê); a troca das parecidas da fila pela versão de áudio e o `andamentos_versao`,
que faz o Automático reordenar, só vêm com a gravação feita, como antes.

## A leitura do estado

O `App.leitura()` devolve o estado da tela e a posição do disco da mesma captura. A faixa, a posição, o estado de
reprodução, a fila e a virada que o motor já confirmou saem juntos, sob a `fila_lock` e depois o `_qlock`. A fila
exposta já não tem a entrada da virada que o `_volta_passagem` ainda vai conciliar. O `avanca` da virada tira a virada
do motor e a entrada da fila sob a mesma `fila_lock`, então a leitura vê as duas ou nenhuma. O avanço sem virada fecha
antes a virada pendente, sob a mesma `fila_lock` em que reserva a próxima, então o Anterior guarda primeiro o disco que
saiu nela, e só um concilia cada virada. Quem concilia guarda o histórico e limpa a marca do prato parado ainda sob a
mesma `fila_lock`. O resto do motor e a formatação ficam fora das travas.

O `/api/state` e o SSE usam essa captura, com o `"api"` (a versão do contrato, `API` do `server.py`) e o `"mock"`
por cima. A volta do SSE é a unidade de publicação: o `Voltas` do `server.py` monta uma a cada `TICK`, só enquanto há
conexão aberta, com a captura, a prateleira e os jobs já em bytes, e entrega a mesma a todas as conexões. Cada conexão
manda o `state` (só quando muda desde o que ela entregou), a prateleira e os jobs que mudaram, e o `tick` com a posição
da mesma captura, mesmo que o motor vire no meio do envio. Cada posição é da faixa que aquela volta entregou. O `caps`
e a conferência da autorização (o celular desconectado, a sessão remota que acabou) seguem de cada conexão. A conexão
com o envio parado segura a sua volta inteira e, ao voltar, pula para a mais nova; as outras não esperam por ela.

## Os vigias e o teste

Cada vigia do `App` é um laço que chama a sua volta: `_volta_fila()`, `_volta_passagem()` e `_volta_auto()`. O
`server.App(..., vigias=False)` não sobe nenhuma das threads dos vigias (nem a das métricas, a da sonoridade e a das
escutas), e o `relogio=False` deixa o `MockEngine` sem o relógio de 10 ms. O `dev/testa_comandos.py` usa os dois: o
`App` de verdade no `--mock`, numa pasta temporária, com um leitor de mentira no lugar do ffmpeg. Ele mesmo chama o
`engine._mixa(BLOCK)` e cada volta, e confere os comandos, o avanço no fim do disco, a virada da passagem, a parecida
com o prato parado e o stream recusado. Confere também a leitura do estado com a virada ainda não conciliada, com o
vigia suspenso no meio da conciliação e o `/api/state` de verdade com a preparação da próxima bloqueada, no endereço
do stream e no `preparar` do motor. O `mover_na_fila` conta a fila que a tela vê (a entrada da virada pendente não se
move e fica para o vigia), e o Próxima com a virada pendente a fecha e devolve a entrada dela. O
`dev/testa_mock.py` liga dois PCs ao SSE, suspende o envio de um entre o `state` e o `tick` e força uma virada nesse
intervalo: o outro recebe a virada enquanto o primeiro está parado, cada posição é da faixa da volta dela nos dois, e
a captura é lida uma vez por volta, não uma por conexão.

O bloco do motor (ver [engine.md](engine.md)) também passa pelo teste: o `_mixa` parado depois de retirar um bloco,
enquanto um `seek`, um `load`, um `resume` do fim, uma troca de deck ou a troca do stream pelo arquivo passam, e a
pausa pelo `/api/pause` e pelo `/api/toggle` esperando a publicação dele.

A reserva de avanço também (a função `avanco`): o fim do disco e o enfileirar com o prato parado, cada um reservando
primeiro; a entrada removida entre a preparação e a virada; a preparação que publica tarde, com a fila ou o prato
mudando enquanto a fonte sai e já dentro do `preparar`, e com o Parar no meio; o motor que ia virar bem quando a entrada
sai da fila; dois Próximos juntos, com o `/api/state` respondendo enquanto o segundo espera, o segundo chegando com o
primeiro já no `load`, e a reserva que falha ou é invalidada liberando quem esperava; o Próximo esperando o `_lock` do
motor com o `/api/state` respondendo; a reserva velha que falha com uma nova na mesma entrada; a gravação da posição que
falha; o enfileirar e a parecida sem stream que esperaram uma reserva que não tocou; o Próximo com a troca do vigia já
publicada e por confirmar, e depois de um Parar; o enfileirar com o Parar logo depois; e o Anterior, o Parar, o tocar
da prateleira e o Próximo com a virada pendente.
