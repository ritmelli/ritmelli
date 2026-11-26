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
- a parecida que chegou com o prato parado (`auto_round`);
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
publicou: um só toca, e todos respondem a entrada dele. Se tocar falha antes de publicar, o erro vai para todos eles (o
primeiro e cada um que espera, no `Proximo.espera`, levantam um `QueuePlayFailed` causado por ele); com a reserva já
resolvida antes por outro (o Parar), o primeiro responde o mesmo que os outros, e o erro vai para a tela
(`engine.error`) se o prato segue na linha que aquele Parar deixou (o `Reserva.resolved_line`, conferido pelo
`Engine.warn_on`: sem outro disco nem outro Parar). O Próximo depois de um Parar segue sozinho. O avanço já em curso que
o Próximo encontra ao chegar (o do fim do disco) e a virada pendente que ele vê são o avanço dele, mesmo se terminarem
antes de ele reservar, e também o que outro começa na linha dele antes de ele reservar; o prato que muda de linha antes
disso fica como está se trocou de disco (o Parar), e com o mesmo disco (um seek) o Próximo segue, com o grupo passando
para a linha do seek. O grupo já resolvido, com o primeiro Próximo ainda gravando a posição, aceita quem chega se tocou
e o prato segue na linha que ele publicou. O Próxima com a virada pendente devolve a entrada dela; se ela já saiu da
fila, segue para a primeira. O Próximo que concilia a virada passa o grupo para a linha dela, e quem chega nesse meio se
junta a ele; o grupo só fica com a virada se a entrada dela ainda está na fila. No `_volta_fila` e no `auto_round`, se
tocar falhar, o erro vai para a tela (`Engine.set_error`, lido em `engine.error`); em todos, a entrada quebrada sai da
fila, menos quando outra reserva em curso vai tocá-la. A gravação da posição que falha depois da troca não desfaz o
avanço.

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
publicação da preparação pegam a `fila_lock` e o `_lock` do motor pelo `App.with_engine`, que entrega a `fila_lock` ao
`Engine.with_lock` do motor; ele nunca espera o `_lock` com a `fila_lock` na mão (o `engine_seams` do
`dev/testa_comandos.py` confere): com o `_lock` ocupado (a reabertura do áudio, a troca de aparelho), solta a `fila_lock`, espera
fora e tenta de novo, e a leitura do estado segue respondendo enquanto um vigia ou uma rota no executor espera o `_lock`
(as rotas que trocam no laço, como o `/api/play`, esperam ali). O ganho do disco que entra é medido
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
`_lock`), o `pode` dos métodos do motor que o declaram (por nome ou pela posição) e o construtor do disco que o
`trocar_fonte`, o `preparar`, o `load` e o `_restart` (e o `_troca`, que o passa ao `load`) recebem (o `_lock` e o
`_qlock`; o `espera` passa o disco dele como `lambda: track`, e o começo do `_restart` é um número, ou `None` para a
posição de agora, que ele limita sob o `_qlock`), e as funções locais que elas chamam também; e confere essas travas no
código que roda cada função (o `change_queue` chama a dele dentro do `_qlock`, e cada método público do motor que recebe
um `pode` o roda sob o `_lock` e o `_qlock`, também pelo `_restart`; o `trocar_fonte`, o `preparar` e o `load` chamam o
construtor sob as duas e publicam a própria chamada dele ali, não o que montaram na entrada), e que quem chama o
`change_queue`, o `close_switches` e o `concilia` tem a `fila_lock` na mão, subindo pelas chamadas até o ponto de
entrada (a thread, a rota); uma função local ou um `lambda` feitos com uma trava na mão não contam com ela (rodam
depois, noutra thread), salvo os que vão para as funções acima. Os ganchos que o App põe no motor (pelo
`on_silent_stream` ou atribuindo, como o `religar_stream`, o `sonoridade_de` e o `mediu`, também chamados por um nome
local) contam como o método do App que o App pôs ali, e todo gancho que o motor chama tem de achar o seu. Com a
`fila_lock`, o `_lock` ou o `_qlock` na mão, nem o código nem o que ele chama grava arquivo (`save_json`, `_save`,
`write_text`, `write_bytes`). Nenhuma trava do modelo vai para um nome local (`q = E._qlock`, o `state_section()` ou um
`with ... as`), para que cada `with` e `acquire` diga a sua. Confere também que o `_mixa` e os métodos e as funções do
`engine.py` que ele chama, das travas do modelo, só pegam o `_qlock` (o `AudioLocks` do `Locks.tla`); o `_slock` dos
sons por cima não entra no modelo. No lugar de uma dessas funções, a checagem só aceita as formas que o código usa e que
ela lê com certeza: um `lambda` sem argumento padrão, que é um escopo próprio; `None`; um disco montado ali (`dict(...)`
ou `{...}`); um condicional entre esses; e um nome. O nome só vale se a função que o liga, com as que estão dentro dela,
o liga uma vez só, e essa ligação é um `=` simples a uma dessas formas ou a `self.metodo(...)` da própria classe, quando
cada `return` dele é uma dessas formas (o `fonte_de`), um `def` sem argumento padrão, ou um parâmetro que é a vaga da
própria função (o `f` do `with_engine`, o `pode` do motor, o `source` do `_troca`). Qualquer outra ligação do mesmo nome
ali reprova: um parâmetro de `def` ou de `lambda`, `for`, `with ... as`, `except ... as`, `import ... as`, `:=`,
`nonlocal`, `global`, `del`, uma captura de `match`, uma variável de compreensão ou um segundo `=`. As outras formas que
ela reconhece reprovam também, por exemplo (um apelido de outro nome, uma tupla, um método ligado, um `partial`, a
chamada passada direto ou devolvida de outra fábrica, a mesma função em vagas com travas diferentes, um `or`, um
parâmetro repassado a uma vaga que pede travas que a sua não tem, um `**nome` ou um `*nome` numa chamada que tem vagas,
ou, na função da vaga ou em qualquer chamada feita com uma trava na mão, uma local que chama outra local, mais de um
nível), com o arquivo e a linha, a forma achada e as que valem. Com uma trava na mão, ou dentro de uma vaga, a chamada
vai a uma função do repo que a checagem resolve, a um `def` local ligado uma vez só (a local vence a função do módulo de
mesmo nome) ou a um parâmetro que é uma vaga da própria função (religado só pela própria chamada, como o `track =
track() if callable(track) else track`); um nome local ligado duas vezes, a um `lambda` ou de outro jeito, um parâmetro
que não é vaga e um `lambda` chamado ali mesmo reprovam. A checagem confere as formas desta lista e reprova as outras
que reconhece como fora dela, mas não promete pegar toda trava tomada: quem promete é a trava de depuração da
https://github.com/ritmelli/ritmelli/issues/316, que guarda as travas na mão de cada thread e falha na hora.

## O modelo das travas (`dev/tla/`)

O modelo TLA+ descreve as travas e o estado que elas guardam, e o TLC confere todos os caminhos dele. O tempo e a
posição do disco viram escolha não determinística, e os `qid` são simétricos (`SYMMETRY`). São três configurações:

- `Races211`: o download, o stream, a troca, o mixer, a preparação da passagem, a troca pela versão de áudio, o vigia da
  passagem, o tocar de outro disco, o esquecer da prateleira, uma reserva de avanço em curso, duas trocas de lugar na
  fila (a entrada sai da frente e volta), o stream que abre sem dar áudio (o leitor dele é um processo à parte, que
  corre junto de quem abriu o stream), o que abre com áudio depois de o download ler o prato e um pulo na barra (sobe a
  linha e tira a passagem preparada), com uma ou duas entradas e um job. Confere a ordem das travas; que nenhum prato
  fica carregando com o job já terminado (em erro, ou baixado com ou sem o disco na prateleira) e o stream recusado ou
  sem áudio; que o stream recusado só para ou troca o disco daquela tentativa; que a entrega do stream sem áudio só para
  ou avisa enquanto a espera do arquivo é a da leitura do prato (depois de um pulo na barra, o leitor novo toca); que o
  download que terminou chega ao prato também quando o stream abriu no meio; que a passagem lida antes de um pulo na
  barra não é publicada depois dele; que a entrada que uma reserva em curso vai tocar segue na versão que ela leu; e que
  a entrada da virada pendente tem a mesma versão que o prato toca (as duas corridas da #211). Duas execuções mostram,
  como falhas conhecidas da #294, o stream que para antes do fim (`WithTheDrop`) e a virada para o stream de um disco
  com download (`WithTheJobSwitch`, com o download que termina depois de a preparação escolher o stream), e outras duas,
  nas mesmas configurações, conferem todas as outras propriedades. A preparação escolhe a fonte como o `fonte_de` (o
  arquivo da prateleira, o stream do download que corre, ou nenhuma), e a virada publica a que ela escolheu: com o disco
  já na prateleira antes de a preparação escolher a fonte (`DownloadEndsBeforeTheSourcePick`), a virada leva o arquivo;
  a parecida sem job que a prateleira já tem pelo `youtube_id` também leva o arquivo (`WithTheOtherOnTheShelf`, numa
  execução só). Como no `download()`, o disco entra na prateleira antes de o job marcar o fim, e o `fonte_de` já o acha
  ali. O tocar de um disco que baixa lê antes a prateleira, como o `tocar_entrada`: com o disco já ali, a troca fecha a
  virada pendente e publica o arquivo da prateleira, sem job e sem stream, e uma execução mostra que esse caminho chega
  ao prato (o `SwapLeavesTheShelfFileOff` quebra no `SwapPublishesTheFile`). O arquivo no prato, como no código, não
  leva o job (o `dict(item, path=...)` não tem a chave), e o download que termina só entrega o arquivo ao disco do job
  (`HandoverOnlyOntoTheJobsRecord`). A troca de nome na prateleira (`WithTheRename`: a prateleira, depois o
  `update_track` sob o `_qlock`) corre contra o download, o stream, a passagem e o tocar da prateleira: quando tudo
  para, o disco do prato tem o nome atual (`PlatterHasTheCurrentName`), com um mutante por caminho: o `update_track` que
  põe um dicionário novo no prato, o arquivo do download, o da passagem e o do tocar montados antes da trava, e o
  segundo deck que não recebe o nome. Três execuções mostram, como falhas conhecidas da #303, o stream que abre, o disco
  de um job tocado enquanto baixa e o stream que a passagem prepara, que levam o nome copiado antes e quebram o
  `NameIsCurrentOutsideARename` (fora de uma troca de nome em curso, o disco do prato tem o nome atual); cada uma fica
  presa à ação do seu caminho, o último passo do contraexemplo (o `action` do `Run`).
- `LocksAndSwitch`: dois Próximos (o tocar de cada um pode falhar antes de publicar), o mixer, o Parar ou uma mudança da
  fila, o vigia da passagem, uma segunda preparação da passagem e a reabertura do áudio segurando o `_lock` (o
  `with_engine` como tentativa com recuo), com duas entradas. Confere a ordem das travas, que das travas do modelo o
  mixer só pega as do `AudioLocks` (o `_qlock`, as mesmas que o `dev/test_lock_order.py` acha no `_mixa` e nos métodos e
  funções do `engine.py` que ele chama), e a falta de impasse; que a virada só vai para a cabeça da fila e que cada uma
  fecha uma vez, e todas fecham; que dois Próximos sobrepostos (o segundo chega com o prato ainda na linha do primeiro,
  ou na linha que o avanço dele publicou) dão um avanço só e o mesmo resultado, também quando o tocar falha (a entrada
  que o caminho do erro tira da fila conta como um avanço, e a virada que um Próximo toma como dele também, sem outro
  avanço depois; uma execução em que todo tocar falha, a `PlaysCanSucceed` desligada, mostra o mutante sem o agrupamento
  tirando duas); que o Anterior recebe cada disco que saiu do prato uma vez, na ordem em que saiu, e nenhum fica de
  fora; e que toda reserva resolve, com justiça fraca.
- `PassageFailure`: o vigia da passagem, o preparo que ele começa (que escolhe a fonte depois, como o `_prepara` com o
  `fonte_de`) e o motor que falha o deck preparado, com duas entradas, a cabeça que muda, a versão de áudio e o arquivo
  que chega à prateleira a qualquer hora. A falha leva a chave do preparo que a gerou (o disco, a entrada, a fonte e o
  registro da prateleira que ele escolheu, por identidade, porque um download de novo sai com o mesmo `id`, o mesmo nome
  de arquivo e às vezes o mesmo `added`, e as mudanças no registro (o nome, o `lufs`, as vezes tocadas) são no mesmo
  objeto: o `_prepara` a passa ao `Engine.preparar`, e o motor a devolve pelo `take_prepare_failure`), e o vigia guarda
  essas chaves num conjunto, as do disco que toca (a chave leva o disco por identidade, `comandos.Identity`, e não pelo
  `id`, que outro disco pode herdar), sem rotular a falha pelo que viu; ele lê a falha e tira o deck preparado para
  outra entrada no mesmo trecho do `_qlock` (`take_prepare_failure(keep=)`), e o preparo confere a fonte que escolheu
  contra o conjunto antes de abrir o stream ou o arquivo (o `fonte_de` recebe a mesma leitura da prateleira). A
  prateleira ganha, perde e troca o arquivo a qualquer hora (os `Files` do modelo são downloads do mesmo arquivo; dois
  só numa execução à parte, com uma fonte só). Confere que uma falha só bloqueia o preparo que a gerou
  (`FailureBlocksOnlyItsPrepare`) e que a fonte que falhou não começa de novo (`NoRetryOfTheFailedSource`), com oito
  mutantes: a falha só com a entrada, a falha com a chave da cabeça da fila, o preparo com a chave que o vigia pediu em
  vez da fonte que ele escolheu, uma falha só guardada (a segunda apaga a primeira), o preparo que não confere a fonte
  que escolheu, o deck de outra entrada tirado num segundo trecho do `_qlock` depois de ler a falha, o preparo que
  confere a fonte que escolheu só pela entrada (e recusa o arquivo depois que o stream falhou) e a chave com o que dois
  downloads do arquivo têm em comum, como o nome (e recusa o download que substitui um que falhou). O `dev/test_tla.py`
  exige de cada spec uma execução do código que passa conferindo todas as invariantes, e da `LocksAndSwitch` e da
  `PassageFailure` as do tamanho que o `WHOLE` pede, contando os membros distintos de cada conjunto nas constantes que
  cada execução usa (a `PassageFailure`, uma com duas entradas, duas fontes e um arquivo e outra com duas entradas, uma
  fonte e dois arquivos), que só mudam conjuntos, nunca o que liga um mutante.

O `dev/test_tla.py` roda o TLC (o `tla2tools.jar` da versão fixada, conferido pelo sha256) nas três, cada execução em
menos de 60 s (a que passa disso é parada ali e falha; a `Races211` em cinco com todas as propriedades, além das onze
acima (as três da #294 e do controle, a da parecida que a prateleira já tem, as seis da troca de nome e a do acerto na
prateleira; a troca de nome com o download, o stream e a troca roda em quatro partes, que juntas são a configuração
inteira (o `dev/test_tla.py` confere, nas execuções da lista, que as partes rodam a troca de nome e que cada escolha do
`Races211.cfg` entra uma vez): o download que falha, e o que põe o disco na prateleira com o stream que dá áudio, com o
stream calado e uma entrada na fila, e com o stream calado e duas): o download, o stream e a troca, sem as trocas de
lugar na fila, uma vez com o tocar de outro disco e outra com o esquecer da prateleira; o download, o stream e um pulo
na barra, sem as trocas de lugar e sem o tocar de outro disco, o esquecer e a reserva; as trocas de lugar, a reserva, a
preparação da passagem e a versão de áudio, sem o job; e os dois juntos, com uma troca de lugar só e sem o tocar de
outro disco, o esquecer e a reserva; o pulo na barra só entra na terceira), e roda também os mutantes: cada propriedade
tem um que desfaz o que ela protege, e o mutante tem de ser pego. Antes do TLC, ele confere que cada execução do código
que passa confere todas as invariantes da sua spec (só deixa de fora uma invariante a execução que repete a configuração
de uma falha conhecida da #294, e só a que essa falha quebra) e o deadlock, e que a de justiça confere o
`ReservationsResolve`, sem a simetria e sem a reabertura do motor. No PR, o job `tla` do `testa.yml` roda isso numa
máquina ubuntu (`python dev/testa_tudo.py --passo tla`). No PC, precisa do Java no PATH; o `TLA2TOOLS` aponta para um
`tla2tools.jar` já baixado. As duas corridas da #211 se repetem no App de verdade no `dev/test_races_211.py`, com os
passos do contraexemplo, um de cada vez.

## O que o servidor lê do motor

O servidor e os comandos leem e conferem o prato pela interface do motor, e não pelos campos de dentro dele: a
`Engine.line()` dá a linha do prato (a `Line`, com o deck e a linha, os mesmos dois campos da `Captura`, da `Reserva` e
do `Proximo`), e a `Engine.on_line(t)` confere, sob o `_qlock`, se o prato ainda é aquela linha. A virada sai do motor
pelo `take_switch`, a passagem preparada pelo `drop_prepared`, o ganho medido antes das travas pelo `gain_for`, o nome
novo do disco no prato pelo `update_track`, a leitura do estado pelo `platter_state` e os arquivos em uso pelo
`tracks_in_use`. Toda mudança da fila passa pelo `App.change_queue`, que pega o `_qlock`, muda e confere a preparada no
mesmo trecho: fora do `App`, nenhum módulo escreve nas entradas da fila ou do Mix (atribuição, `update`, subscript ou
`del`), e o `dev/test_queue_entries.py` falha se escrever, seguindo as entradas e as listas que uma função devolve e as
que ela recebe, até nada mais mudar. Ele só segue as formas que o código usa. Uma referência à fila, ao Mix, a uma fatia
deles ou a uma entrada só aparece assim: lendo um campo ou chamando um método com nome ali mesmo, nunca um dunder (o
mutador chamado conta como escrita); comparada ou testada; ligada a um nome por um `=` simples ou aos atributos da
própria fila e da entrada (`fila`, `fila_ordem`, `mix`, `_mix`, `x`, `entrada`, `historico`); passada por posição ou por
nome a uma função nomeada, ou devolvida por uma, que ele segue (também por um dict ligado a um nome só usado como
`**nome` numa chamada a uma função nomeada, e nunca numa função de dentro, pelo `args` de uma thread cujo `target` é uma
função nomeada, e por uma vaga: o parâmetro que a função chama com ela, onde um `def` passado é seguido e um `lambda` só
a devolve, compara ou testa), ou, a quem ele não segue, só a própria fila ao `len`, ao `reversed` e aos que copiam ou
percorrem (`list`, `sorted`, `tuple`, `iter`, `enumerate`, `filter`), uma cópia também ao `next`, `min`, `max`, à
`Thread` e ao `random.shuffle` (que só reordena uma lista que não pode ser a fila), e uma entrada ao `dict`, ao `id`, ao
`append`, `insert` ou `extend` de uma lista (que vira uma lista de entradas) e a uma classe do repo, com no máximo
quatro repasses seguidos, a função que recebe e passa adiante (o máximo do código: `App.tocar_entrada`,
`App.tocar_remoto`, `App._troca`, `App.release_reservation` e `Proximo.resolve`; o teste falha se a cadeia mais funda do
código não der quatro, para o teto descer junto). Nessa conta, e ao ligar a entrada ao parâmetro de quem a recebe,
`self.metodo()` só vai à própria classe e às bases dela, `modulo.f()` à função do módulo importado, e `obj.metodo()` aos
métodos com esse nome que aceitam os argumentos da chamada (todos os obrigatórios, e nenhum a mais), nunca a um método
da própria fila ou da entrada; a chamada que não chega a nenhum desses liga a entrada a toda função com esse nome; num
laço com um nome só ou com o `enumerate(...)` desempacotado em dois; desempacotada de uma chamada ou de uma tupla do
mesmo tamanho; ou copiada (`list()`, `sorted()`, uma compreensão, uma fatia, `{**x}`). As outras que ela reconhece
reprovam, com o arquivo e a linha, por exemplo: um `:=`, uma anotação, desempacotar a fila ou o Mix, um `*`, o
`getattr`, o mutador guardado ou devolvido sem a chamada, uma atribuição encadeada, guardar num atributo que não é da
fila, sob uma chave ou num dict, numa lista, numa tupla ou num conjunto, passar a uma lambda, o `enumerate` sem
desempacotar, a própria fila devolvida por uma função, um quinto repasse seguido, um dunder, entregar a quem ele não
segue fora da lista acima, e, no `App`, um nome que recebe o retorno de um método dele que devolve a própria fila. A
checagem confere as formas desta lista e reprova as outras que reconhece como fora dela, mas não promete pegar toda
escrita: quem promete é a fila e o Mix como um objeto que só muda dentro do `change_queue`, a
https://github.com/ritmelli/ritmelli/issues/316. Dentro do `App`, as entradas da fila só mudam numa função passada ao
`change_queue`, e a própria fila (atribuição, fatia, `append`, `remove` e afins, também por um apelido dela ou por quem
a recebe como argumento) só muda ali, em qualquer módulo. A versão de áudio das parecidas entra no Mix do Automático
como entradas novas (o `_troca_audio`, que não escreve nas que já existem) e na fila pelo `App.apply_audio_version`, que
muda a fila pelo `change_queue` e, no mesmo trecho do `_qlock`, deixa como estão a entrada da virada pendente (pelo
`qid`, a mesma versão que o prato toca), a primeira da fila presa e a que uma reserva em curso vai tocar
(`App.reserva`); o `tocar_da_fila` e a preparação da passagem leem a entrada numa cópia feita sob a `fila_lock`, e uma
versão de áudio que chega no meio não mistura o alvo de antes com os dados de depois. Os trechos do servidor e dos
comandos que precisam do `_qlock` (os do Próximo, da reserva, do `concilia`, da troca, do `remember_pos`, do
`release_reservation` e do `change_queue`) o pegam pelo `Engine.state_section()`, e o `_lock` só pelo
`Engine.with_lock`. A falha de preparar a próxima sai do motor pelo `take_prepare_failure`, sob o `_qlock`, com a chave
que o preparo passou ao `preparar`, e o erro da tela entra pelo `set_error` (o `error` do motor só se lê).

Os comandos e o Automático chamam o `App` só pela interface pública dele: `change_queue`, `remove_from_queue`,
`remove_if_queued`, `save_history`, `release_reservation`, `close_switches`, `with_engine`,
`search_songs`, `run_helper` e os outros; o que eles ainda escrevem direto no estado do `App` é contado
abaixo. O servidor chama o Automático pela dele (`ligar_auto`,
`run_auto_watcher`, `run_tempo_watcher`, `refuse`, chamado com o `fila_lock` na mão, e lê o `auto` e o `tempo_of`), e o estado do Automático mora nele; o `auto_round` e o `fetch_mix` são a volta do vigia das parecidas e a busca
que ela pede, que os testes chamam pelo `A.automatico`. A prateleira grava pelo `Library.save`.

O `dev/testa_ganchos.py` conta, e o `dev/garden.py` segura cada número no seu teto do `dev/garden.json`, que só
desce: os acessos aos nomes privados do motor (`engine_reaches`), do `App` (`app_reaches`) e do Automático
(`automatico_reaches`) vindos dos outros módulos da raiz, contando também os privados de módulo do `engine.py`, do
`server.py` e do `automatico.py`; os acessos aos privados da `Library` vindos do resto do `server.py`
(`library_reaches`); e as escritas diretas no estado público do `App` (`app_writes`) e do motor (`engine_writes`)
vindas de fora do módulo deles. O que conta como acesso ou escrita são os casos do próprio teste; as formas que ele
ainda não vê estão na #232.

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

Cada vigia do `App` é um laço que chama a sua volta: `_volta_fila()`, `_volta_passagem()` e `auto_round()`. O
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
