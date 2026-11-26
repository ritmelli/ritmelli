# Os comandos de música (`comandos.py`)

`comandos.py`: as operações de música do servidor, cada uma com a sua regra. As rotas do `server.py` leem o corpo,
chamam o comando e montam a resposta, que segue a mesma do [`API.md`](../../API.md). Quem não é rota, como os vigias
do `App`, chama o mesmo comando. Cada função recebe o `App`; a fila, o histórico e a `fila_lock` continuam nele.

| Comando | Rota | A regra que mora no comando |
| --- | --- | --- |
| `tocar` | `POST /api/play` | sem o `por_cima` no corpo, o som curto (até `CURTO_MAX_S`) toca por cima da música, só sem `start` e sem `resume`; com ele, o `por_cima` decide |
| `play_shelf_record` | `POST /api/library` com `play` de um disco que já está na prateleira | o disco que a rota achou vai para o prato do começo, mesmo o som curto (nunca por cima, nunca do `last_pos`) |
| `play_downloading` | `POST /api/library` com `play` de um vídeo fora da prateleira | toca na hora pelo stream enquanto o download segue; o arquivo substitui o stream sem cortar |
| `enfileirar` | `POST /api/queue` | com nada no prato (parado, ou o disco já acabou), o que entra toca na hora, num avanço reservado (se o fim do disco reservou antes, só guarda); pausado ainda é disco no prato |
| `tocar_da_fila` | `POST /api/queue/play` | a entrada sai da fila e toca |
| `tirar_da_fila` | `DELETE /api/queue/{qid}` | a parecida tirada pelo usuário não volta nesta sessão |
| `mover_na_fila`, `limpar_fila` | `POST /api/queue/move`, `DELETE /api/queue` | |
| `pular` | `POST /api/next` | o avanço da fila; logo depois de uma virada da passagem ainda não conciliada, a virada é o avanço, e ele devolve a entrada que acabou de entrar |
| `voltar` | `POST /api/prev` | o Anterior do `App` |
| `pausar`, `retomar`, `alternar` | `POST /api/pause`, `/api/resume`, `/api/toggle` | pausar espera o motor confirmar a pausa no limite entre blocos (sem trava e sem prender o laço do servidor) e grava a posição confirmada; o alternar pausa o que toca ou carrega e retoma o resto |
| `parar` | `POST /api/stop` | o disco parado entra no histórico, e o Anterior toca ele de novo; a posição gravada é a do instante em que ele saiu |
| `ir_para` | `POST /api/seek` | |
| `update_record` | `PATCH /api/library/{id}` | o disco da prateleira muda (o nome, o `rapido`), e a faixa do prato também, se é ele: a tela mostra o nome novo na hora |
| `volume` | `POST /api/volume`, e o `vol` do `POST /api/settings` | o limite de 0 a 1; o `/api/volume` grava só o volume da música, e o `/api/settings` grava a configuração do som inteira depois |

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

A virada pendente é conciliada num laço só, o `concilia` do `comandos.py`: a cada volta, sob a `fila_lock` e o
`_qlock`, quem chama vê a virada pendente e decide se ela fecha (ela sai do motor pelo `Engine.take_switch` no mesmo
trecho, e o `fecha_virada` a tira da fila com o `_qlock` solto) ou se para ali com o que leu. O avanço, o Anterior, o
Parar, a troca e o vigia da passagem passam por ele.

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
mudou no meio, como no Parar, fica como está); a parecida captura o prato a cada tentativa (um seek no meio não a deixa
carregando) e só para o prato com a fila vazia e sem avanço de outro em curso, conferidos no `pode` do `stop`. A troca
confere a reserva e a entrada antes de fechar a virada e tirar a passagem preparada: a que já não vale não tira a
preparada de quem vale. Os Próximos sobrepostos (o segundo chega antes de o primeiro voltar, mesmo com o primeiro já
trocando o disco) dividem o mesmo avanço (`App.proximo`), se o prato ainda é a linha dele ou a que a reserva dele
publicou: um só toca, e todos respondem a entrada dele. Se tocar falha antes de publicar, o erro vai para todos eles
(`Proximo.espera`); com a reserva já resolvida antes por outro (o Parar), o primeiro responde o mesmo que os outros, e o
erro vai para a tela (`engine.error`). O Próximo depois de um Parar segue sozinho. O avanço já em curso que o Próximo
encontra ao chegar (o do fim do disco) e a virada pendente que ele vê são o avanço dele, mesmo se terminarem antes de
ele reservar, e também o que outro começa na linha dele antes de ele reservar; o prato que muda de linha antes disso
fica como está se trocou de disco (o Parar), e com o mesmo disco (um seek) o Próximo segue, com o grupo passando para a
linha do seek. O grupo já resolvido, com o primeiro Próximo ainda gravando a posição, aceita quem chega se tocou e o
prato segue na linha que ele publicou. O Próxima com a virada pendente devolve a entrada dela; se ela já saiu da fila,
segue para a primeira. O Próximo que concilia a virada passa o grupo para a linha dela, e quem chega nesse meio se junta
a ele; o grupo só fica com a virada se a entrada dela ainda está na fila. No `_volta_fila` e no `_volta_auto`, se tocar
falhar, o erro vai para a tela (`engine.error`); em todos, a entrada quebrada sai da fila, menos quando outra reserva em
curso vai tocá-la. A gravação da posição que falha depois da troca não desfaz o avanço.

Três avanços tentam de novo, cada um pela sua regra; os dois primeiros até `ADVANCE_TRIES` vezes:

- o enfileirar com o prato parado (`toca_se_parado`) tenta de novo quando a reserva de outro que ele esperou não tocou,
  sempre com o prato que viu ao pôr a entrada na fila: o prato que mudou de linha depois fica como está;
- a parecida sem stream (`_abre_stream`) captura o prato a cada tentativa e tenta de novo quando cedeu a vez (um seek
  no meio); com a fila vazia, para o prato pelo `pode` do `stop`, e tenta de novo se o `pode` recusou;
- o Próximo (`pular`) tenta de novo uma vez só, quando cedeu a vez com o mesmo disco no mesmo deck (um seek), e o
  grupo passa para a linha do seek.

O `POST /api/queue` põe na fila no laço do servidor, como o tocar e a prateleira (a procura do download do mesmo vídeo
e a criação de um novo não correm com outro pedido), e só o tocar na hora vai ao executor, com o prato visto no laço
logo depois de a entrada entrar: um Parar que chega antes da thread não vira um tocar.

Toda troca de disco passa pelo `App._troca`, sob a `fila_lock`: o Anterior, o Parar (que não troca, mas guarda) e o
tocar da prateleira fecham antes a virada pendente, e o Anterior guarda primeiro o que saiu nela; o Anterior escolhe
entre voltar ao começo e tocar o de antes com a faixa e a posição lidas no mesmo trecho do `_qlock` em que não há
virada, e a passagem preparada sai ali. Ele só lê o topo do histórico: a troca confere que o prato ainda é a linha que
ele viu e o topo ainda é o que ele escolheu, e o topo sai só com a troca feita; o recomeço confere a linha no `pode` do
`seek`. O que mudou no meio (um Próximo, um seek, o esquecer) faz o Anterior escolher de novo. A troca, o Parar e a
publicação da preparação pegam a `fila_lock` e o `_lock` do motor pelo `App.with_engine`, que nunca espera o `_lock`
com a `fila_lock` na mão: com o `_lock` ocupado (a reabertura do áudio, a troca de aparelho), solta a `fila_lock`, espera
fora e tenta de novo, e a leitura do estado segue respondendo enquanto um vigia ou uma rota no executor espera o `_lock`
(as rotas que trocam no laço, como o `/api/play`, ainda esperam ali, como antes). O ganho do disco que entra é medido
antes, e o leitor que começa, a onda e a medida rodam depois de soltar as duas (o `depois` do `load`, do `espera` e do
`preparar`).

## A passagem e a cabeça da fila

A volta do `_volta_passagem` guarda o deck e a linha do prato que viu. A fonte da primeira da fila e o ganho dela saem
fora das travas (o endereço do stream leva 1 a 3 s), de uma cópia da entrada tirada sob a `fila_lock`, e a publicação
(`preparar`) é sob a `fila_lock`: ela confere que a entrada ainda é a primeira e igual à cópia (a que saiu da frente,
trocou de versão e voltou não publica a fonte de antes) e, no `pode` sob o `_qlock`, que não há virada pendente nem
avanço reservado em curso nesta linha e que o prato ainda é o mesmo deck, a mesma linha e o mesmo disco, sem o Repetir,
sem ter acabado e sem nada preparado. Quem fecha a virada e troca o disco sob a `fila_lock` não vê uma preparação entrar
no meio. Toda mudança da fila (pôr, tirar, mover, limpar, a ordem do Automático, o Aleatório e o esquecer) acontece no
mesmo trecho do `_qlock` em que a passagem preparada é conferida (`_confere_preparo_sob`): a preparada para quem não é
mais a primeira sai ali, e o motor não vira para ela no meio. O Automático não reordena a primeira que um avanço
reservado vai tocar.

## As travas

A ordem é a `fila_lock` do `App`, depois o `_lock` do motor (um `RLock`), depois o `_qlock` do motor, nunca ao
contrário. Duas outras vêm logo antes do `_qlock` e nunca ficam na mão junto da `fila_lock` nem do `_lock`: a
`proximo_lock` do `App` (os Próximos sobrepostos, no `pular`) e a trava da prateleira (`Library.lock`: o
`App.remember_pos` pega ela, depois o `_qlock`, e grava o arquivo com o `_qlock` já solto). Com o `_qlock` na mão não se
chama método do motor que pegue o `_lock`. A thread do áudio (o `_mixa`) nunca pega a `fila_lock` nem o `_lock`. Sob a
`fila_lock` não se grava arquivo: o `andamentos.json` e o `versoes_audio.json` são copiados sob ela e gravados fora
dela. A medida entra na memória mesmo se a gravação falha (quem lê esses dicionários depois a vê); a troca das parecidas
da fila pela versão de áudio e o `andamentos_versao`, que faz o Automático reordenar, só vêm com a gravação feita.

A ordem está declarada no modelo (`dev/tla/Locks.tla`, o `LockOrder` e o `BeforeQlockOnly`), e o
`dev/test_lock_order.py` compara com ela cada `with` das travas (e o `_lock.acquire`) do `comandos.py`, do `server.py`,
do `automatico.py` e do `engine.py`, pela árvore de sintaxe, e também cada chamada feita com uma trava na mão a um
método do `App`, da `Engine`, do `Automatico`, da prateleira ou do `comandos.py` (com o `_qlock` na mão, nenhum método
que pegue o `_lock` ou o próprio `_qlock`); com a `fila_lock` na mão, o `_lock` só se tenta, com
`acquire(blocking=False)` (o `with_engine`). As funções que outro roda com as travas na mão contam com elas: as do
`change_queue`, do `close_switches` e do `concilia` (a `fila_lock` e o `_qlock`), a do `with_engine` (a `fila_lock` e o
`_lock`) e o `pode` dos métodos do motor (o `_lock` e o `_qlock`), e as funções locais que elas chamam também. Com a
`fila_lock` na mão, nem o código nem o que ele chama grava arquivo (`save_json`, `_save`, `write_text`, `write_bytes`).
Confere também que o `_mixa` e os métodos e as funções do `engine.py` que ele chama, das travas do modelo, só pegam o
`_qlock` (o `AudioLocks` do `Locks.tla`); o `_slock` dos sons por cima não entra no modelo.

## O modelo das travas (`dev/tla/`)

O modelo TLA+ descreve as travas e o estado que elas guardam, e o TLC confere todos os caminhos dele. O tempo e a
posição do disco viram escolha não determinística, e os `qid` são simétricos (`SYMMETRY`). São duas configurações:

- `Races211`: o download, o stream, a troca, o mixer, a preparação da passagem, a troca pela versão de áudio, o vigia da
  passagem, o tocar de outro disco, o esquecer da prateleira e duas trocas de lugar na fila (a entrada sai da frente e
  volta), com uma ou duas entradas e um job. Confere a ordem das travas; que nenhum prato fica carregando com o job já
  terminado (em erro, ou baixado com ou sem o disco na prateleira) e o stream recusado; que o stream recusado só para ou
  troca o disco daquela tentativa; e que a entrada da virada pendente tem a mesma versão que o prato toca (as duas
  corridas da #211).
- `LocksAndSwitch`: dois Próximos (o tocar de cada um pode falhar antes de publicar), o mixer, o Parar ou uma mudança da
  fila, o vigia da passagem, uma segunda preparação da passagem e a reabertura do áudio segurando o `_lock` (o
  `with_engine` como tentativa com recuo), com duas entradas. Confere a ordem das travas, que das travas do modelo o
  mixer só pega as do `AudioLocks` (o `_qlock`, as mesmas que o `dev/test_lock_order.py` acha no `_mixa` e nos métodos e
  funções do `engine.py` que ele chama), e a falta de impasse; que a virada só vai para a cabeça da fila e que cada uma
  fecha uma vez, e todas fecham; que dois Próximos sobrepostos (o segundo chega com o prato ainda na linha do primeiro,
  ou na linha que o avanço dele publicou) dão um avanço só e o mesmo resultado, também quando o tocar falha; que o
  Anterior recebe cada disco que saiu do prato uma vez, na ordem em que saiu, e nenhum fica de fora; e que toda reserva
  resolve, com justiça fraca.

O `dev/test_tla.py` roda o TLC (o `tla2tools.jar` da versão fixada, conferido pelo sha256) nas duas, cada execução em
menos de 60 s, e roda também os mutantes: cada propriedade tem um que desfaz o que ela protege, e o mutante tem de ser
pego. No PR, o job `tla` do `testa.yml` roda isso numa máquina ubuntu (`python dev/testa_tudo.py --passo tla`). No PC,
precisa do Java no PATH; o `TLA2TOOLS` aponta para um `tla2tools.jar` já baixado. As duas corridas da #211 se repetem no
App de verdade no `dev/test_races_211.py`, com os passos do contraexemplo, um de cada vez.

## O que o servidor lê do motor

O servidor e os comandos leem e conferem o prato pela interface do motor, e não pelos campos de dentro dele: a
`Engine.line()` dá a linha do prato (a `Line`, com o deck e a linha, os mesmos dois campos da `Captura`, da `Reserva`
e do `Proximo`), e a `Engine.on_line(t)` confere, sob o `_qlock`, se o prato ainda é aquela linha. A virada sai do
motor pelo `take_switch`, a passagem preparada pelo `drop_prepared` (o `cancelar_pronto` é o mesmo, pegando o
`_qlock`), o ganho medido antes das travas pelo `gain_for`, o nome novo do disco no prato pelo `update_track`, a
leitura do estado pelo `platter_state` e os arquivos em uso pelo `tracks_in_use`. Toda mudança da fila passa pelo
`App.change_queue`, que pega o `_qlock`, muda e confere a preparada no mesmo trecho: fora do `App`, nenhum módulo
escreve nas entradas da fila ou do Mix (atribuição, `update`, subscript ou `del`), e o `dev/test_queue_entries.py`
falha se escrever. Dentro do `App`, as entradas da fila só mudam numa função passada ao `change_queue`, e a própria
fila (atribuição, fatia, `append`, `remove` e afins, também por um apelido dela ou por quem a recebe como argumento) só
muda ali, em qualquer módulo. A versão de áudio das parecidas entra pelo `App.apply_audio_version`, que muda a fila pelo
`change_queue` e, no mesmo trecho do `_qlock`, deixa como estão a entrada da virada pendente (pelo `qid`, a mesma versão
que o prato toca) e a primeira da fila presa. O que ainda pega as travas do motor por fora (o `_qlock` dos trechos do
Próximo, da reserva, do `concilia`, da troca, do `remember_pos`, do
`release_reservation` e do `change_queue`, e o `_lock` do `with_engine`) é contado pelo `dev/testa_ganchos.py`, que
falha se o número muda: acima do teto entrou acesso novo; abaixo, o PR que tirou um baixa o teto junto. Os nomes
privados do motor saem da árvore de sintaxe do `engine.py` (os métodos e os `self._x` que a `Engine` e a `MockEngine`
definem), e o `getattr` com o nome escrito também conta.

Os comandos e o Automático mexem no `App` só pela interface pública dele. O que eles chamavam por privados virou
público com estes nomes: `change_queue`, `remove_from_queue`, `remove_if_queued`, `save_history`,
`release_reservation`, `close_switches`, `with_engine` e `tempo_of`; e o que o Automático lia do servidor pelo
`sys.modules` chega por `search_songs`, `run_helper` e `yt_error`. O mesmo `dev/testa_ganchos.py` conta os acessos
aos privados do `App` fora do `server.py`, pela mesma regra, contra o `APP_CEILING`, que hoje é zero.

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
publicada e por confirmar, e depois de um Parar; o enfileirar com o Parar logo depois; e o Anterior, o Parar, o tocar da
prateleira e o Próximo com a virada pendente.
