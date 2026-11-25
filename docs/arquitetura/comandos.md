# Os comandos de música (`comandos.py`)

`comandos.py`: as operações de música do servidor, cada uma com a sua regra. As rotas do `server.py` leem o corpo,
chamam o comando e montam a resposta, que segue a mesma do [`API.md`](../../API.md). Quem não é rota, como os vigias
do `App`, chama o mesmo comando. Cada função recebe o `App`; a fila, o histórico e a `fila_lock` continuam nele.

| Comando | Rota | A regra que mora no comando |
| --- | --- | --- |
| `tocar` | `POST /api/play` | sem o `por_cima` no corpo, o som curto (até `CURTO_MAX_S`) toca por cima da música, só sem `start` e sem `resume`; com ele, o `por_cima` decide |
| `enfileirar` | `POST /api/queue` | com nada no prato (parado, ou o disco já acabou), o que entra toca na hora; pausado ainda é disco no prato |
| `tocar_da_fila` | `POST /api/queue/play` | a entrada sai da fila e toca |
| `tirar_da_fila` | `DELETE /api/queue/{qid}` | a parecida tirada pelo usuário não volta nesta sessão |
| `mover_na_fila`, `limpar_fila` | `POST /api/queue/move`, `DELETE /api/queue` | |
| `pular` | `POST /api/next` | o avanço da fila |
| `voltar` | `POST /api/prev` | o Anterior do `App` |
| `pausar`, `retomar`, `alternar` | `POST /api/pause`, `/api/resume`, `/api/toggle` | pausar grava a posição do disco; o alternar pausa o que toca ou carrega e retoma o resto |
| `parar` | `POST /api/stop` | o disco parado entra no histórico, e o Anterior toca ele de novo |
| `ir_para` | `POST /api/seek` | |
| `volume` | `POST /api/volume` | grava só o volume da música |

## O avanço da fila

O avanço é uma operação só, o `avanca`. Sem virada, a primeira da fila sai e toca. Com a virada do motor (a passagem
de DJ, em que o motor já trocou de deck sozinho), a entrada da virada só sai da fila, e o disco que saiu entra no
histórico. Passam por ele:

- o Próxima (`/api/next`);
- o fim do disco (`_volta_fila`);
- a virada da passagem (`_volta_passagem`);
- o stream da parecida que não abriu (`_abre_stream`), sem guardar no histórico;
- a parecida que chegou com o prato parado (`_volta_auto`).

No `_volta_fila` e no `_volta_auto`, a entrada sai da fila e, se tocar falhar, o erro vai para a tela
(`engine.error`).

## As travas

A ordem é a `fila_lock` do `App`, depois o `_lock` do motor (um `RLock`), depois o `_qlock` do motor, nunca ao
contrário. Com o `_qlock` na mão não se chama método do motor que pegue o `_lock`. A thread do áudio (o `_mixa`) nunca
pega a `fila_lock` nem o `_lock`. Sob a `fila_lock` não se grava arquivo: o `andamentos.json` e o
`versoes_audio.json` são copiados sob ela, gravados fora dela e só depois valem na fila, como antes.

## A leitura do estado

O `App.leitura()` devolve o estado da tela e a posição do disco da mesma captura. A faixa, a posição, o estado de
reprodução, a fila e a virada que o motor já confirmou saem juntos, sob a `fila_lock` e depois o `_qlock`. A fila
exposta já não tem a entrada da virada que o `_volta_passagem` ainda vai conciliar. O `avanca` da virada tira a
virada do motor e a entrada da fila sob a mesma `fila_lock`, então a leitura vê as duas ou nenhuma. O avanço sem virada
(o Próxima, o fim do disco) fecha antes a virada pendente, então o Anterior guarda primeiro o disco que saiu nela,
e só um dos dois concilia cada virada. O resto do motor e
a formatação ficam fora das travas.

O `/api/state` e o SSE usam essa captura. A cada volta, o SSE manda o `state` (só quando muda) e o `tick` com a
posição da mesma captura, mesmo que o motor vire no meio do envio. Cada posição é da faixa que aquela volta entregou.

## Os vigias e o teste

Cada vigia do `App` é um laço que chama a sua volta: `_volta_fila()`, `_volta_passagem()` e `_volta_auto()`. O
`server.App(..., vigias=False)` não sobe nenhuma das threads dos vigias (nem a das métricas, a da sonoridade e a das
escutas), e o `relogio=False` deixa o `MockEngine` sem o relógio de 10 ms. O `dev/testa_comandos.py` usa os dois: o
`App` de verdade no `--mock`, numa pasta temporária, com um leitor de mentira no lugar do ffmpeg. Ele mesmo chama o
`engine._mixa(BLOCK)` e cada volta, e confere os comandos, o avanço no fim do disco, a virada da passagem, a parecida
com o prato parado e o stream recusado. Confere também a leitura do estado com a virada
ainda não conciliada, com o vigia suspenso no meio da conciliação e o `/api/state` de verdade com a preparação da próxima
bloqueada, no endereço do stream e no `preparar` do motor. O `mover_na_fila` e o Próxima (`proxima`) contam a
fila que a tela vê: a entrada da virada pendente fica para o vigia. O
`dev/testa_mock.py` suspende o envio do SSE entre o `state` e o `tick` e força uma virada nesse intervalo.
