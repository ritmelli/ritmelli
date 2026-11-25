# O protocolo da sessão remota (v1)

A sessão remota deixa quem está numa chamada mandar no Ritmelli de quem abriu a sessão, sem estar no PC dele. Pela
internet passam só os comandos e o estado; a música nunca sai do PC. O PC é o dono do estado: quem manda vê uma
projeção dele, e o que não está na projeção não existe fora do PC.

```
quem manda  <──>  relay  <──>  conector (processo auxiliar no PC)  <──>  API local (127.0.0.1, papel remoto)
```

O conector abre a conexão de saída até o relay (o PC não abre porta de entrada), recebe o comando, chama a API local
com o token do papel `remoto` ([permissao.md](arquitetura/permissao.md)) e devolve o resultado e o estado. O relay
confere o vocabulário e os argumentos, guarda a última foto da sessão e a entrega a quem conecta; o conector confere de
novo, porque o relay não é de confiança para o PC. A projeção, a âncora e o `rev` nascem no `server.py`, no processo
do motor, que os entrega ao conector pela API local do papel `remoto` (a rota ou o evento novo entra no `permissao.py`
e no `API.md` com a implementação). O conector não monta nada: confere e repassa.

Este documento é o contrato das mensagens: o que cada uma leva, a âncora da posição, o relógio, o `rev`, o
vocabulário e o mapa de cada comando para a rota local. Os esquemas (JSON Schema, draft 2020-12), o mapa e as fixtures
ficam em [`protocolo-remoto/v1/`](protocolo-remoto/v1/). Convite, identidade e presença na chamada, o transporte
(WebSocket com TLS) e como o conector nasce e morre ficam no documento do conector.

## As mensagens

Toda mensagem é um objeto JSON com `"protocolo": 1`, o `tipo` e a `sessao` (o id da sessão aceita, que não é
credencial: o token do papel `remoto` nunca sai do PC e nunca entra no protocolo).

| tipo | sentido | esquema | o que leva |
|---|---|---|---|
| `estado` | PC → relay → quem manda | [`estado.schema.json`](protocolo-remoto/v1/estado.schema.json) | `rev`, `origem` (`inicio`, `reconexao` ou `mudanca`), `agora` e a projeção inteira (`estado`) |
| `pulso` | PC → relay → quem manda | `estado.schema.json` | `rev` do último estado e `agora`, de 1 em 1 s |
| `comando` | quem manda → relay → PC | [`comando.schema.json`](protocolo-remoto/v1/comando.schema.json), com os argumentos em [`argumentos.schema.json`](protocolo-remoto/v1/argumentos.schema.json) | `id` (de quem manda, único na sessão), `comando` e `args` |
| `resultado` | PC (ou o relay, quando ele mesmo recusa) → quem mandou | [`resultado.schema.json`](protocolo-remoto/v1/resultado.schema.json) | o `id` do comando e `ok`: com `rev` e `dados`, ou o código do `erro` |

O relay acrescenta `retido_ms` (quanto tempo segurou a mensagem) ao entregar o estado, o pulso e o resultado a quem
manda; o comando chega ao PC como saiu. Nenhum esquema aceita campo a mais: campo novo é versão nova (ver "Versão").

## A projeção

A projeção sai do estado local (o mesmo do `GET /api/state`, montado no `server.py`) por lista explícita de campos.
Aparelhos, microfone, volume e efeitos da voz, atualização, erros locais, o `caps`, o arquivo e o download de cada
disco nunca saem do PC.

| na projeção | do estado local |
|---|---|
| `status` | `status` (`idle`, `buffering`, `playing`, `paused`, `ended`) |
| `faixa` | do `track`: `id`, `title`, `channel`, `duration`, `youtube_id`, `thumb` e `stream` (bool); `null` com o prato vazio |
| `fila` | de cada entrada do `queue`, as primeiras 500: `qid`, `id`, `title`, `channel`, `duration`, `youtube_id`, `thumb` e `auto` (bool) |
| `vol` | `vol`, o volume da música no jogo |
| `abaixa` | `abaixa`, o abaixamento pelo comando `abaixar`, ou `null` |
| `capacidades` | os comandos do vocabulário cujas rotas estão no `caps` do papel `remoto` |
| `ancora` | a posição (abaixo); `null` com o prato vazio |

A projeção cabe sempre no esquema, para um estado local válido nunca derrubar a foto: `title` e `channel` cortados em
400 caracteres, e `null` quando são um link (o servidor põe o endereço no título do que só tem o endereço, e ele não
sai do PC); `duration` que não é número de 0 a 86400 vira `null`; `thumb` que não é `https://` ou passa de 500
caracteres vira `null`; `youtube_id` fora dos 11 caracteres de um vídeo (o id de outro site, que o download guarda ali)
vira `null`; a fila sai com as 500 primeiras entradas (e o `mover_na_fila` só leva a um lugar que se vê, até o 499).

## A posição: a âncora

A posição não vai a cada tick. Vai como âncora: a faixa no prato, a posição dela (`pos`, em segundos do disco) num
instante de referência (`t`, no relógio do PC, em ms), se ela anda (`anda`) e os segmentos de velocidade que o prato
vai seguir dali em diante, contados em amostras de saída (`taxa`: 48000 por segundo, o relógio do som). Quem recebe
integra os segmentos até o próprio relógio, convertido no do PC (ver "O relógio"). O `t` pode estar no passado (a
descontinuidade que já tocou quando o estado saiu) ou um pouco adiante do `agora` (o bloco que já saiu do motor e ainda
espera no anel do filtro); antes do `t`, a posição é `pos`.

Um segmento tem `n` amostras de saída e a velocidade `v` do disco nelas: um número, ou o meio cosseno
`{"de", "ate", "total", "fase"}`, com a velocidade da amostra `i` (a partir de `fase`)

```
v(i) = ate + (de - ate) * (1 + cos(pi * i / total)) / 2
```

A posição depois de `m` amostras é a de começo mais `soma(v(i)) / taxa`, e a soma do meio cosseno tem forma fechada:

```
soma de i = a até b - 1 de cos(pi * i / N) = (sin(pi * (b - 1/2) / N) - sin(pi * (a - 1/2) / N)) / (2 * sin(pi / (2 * N)))
```

Só o último segmento, em velocidade constante, pode ser aberto (`n` null); o meio cosseno e o preenchimento têm `n`
finito, e no meio cosseno `fase + n <= total`. A velocidade 0 só aparece no preenchimento. Cada segmento vale de
`[começo, começo + n)`: na fronteira já vale o seguinte, e o `pos` de um segmento (a posição de começo dele, quando não
continua a do anterior) entra exatamente ali. Depois do último segmento finito, a posição fica parada. Com
`anda: false` (pausa, buffering, fim), a posição é `pos` e os segmentos vêm vazios.

### O que o PC põe na âncora

O mapa de amostras do motor são os rótulos dos blocos na fila do prato: cada bloco leva a posição do disco na primeira
amostra dele, e o motor anda dentro do bloco a velocidade 1 (o `_tira`, que rotula o resto de um bloco partido com
`t0 + n / 48000`, e o `pos` do `_mixa`, no `engine.py`). A âncora reproduz esses rótulos:

- `pos` é o rótulo do próximo bloco da fila do prato, não o `pos` do motor (que soma o bloco a velocidade 1 e, numa
  rampa, fica até `|v - 1| * 10 ms` longe do rótulo seguinte). Com a fila vazia (buffering, fim), é o `pos` do motor.
- Sem passagem marcada: a cauda da fila. O PC olha 1 s da fila adiante; cada trecho de rótulos contínuos vira um
  segmento em 1, com o `pos` dele quando o rótulo salta (a volta do Repetir que o leitor já pôs na fila), até caberem
  os 8 segmentos da âncora. O último fica aberto, salvo quando a fila acaba dentro dessa janela (ou bem no fim dela)
  com o fim do disco já lido: aí ele é finito e a posição para no fim, sem passar dele. Sem lugar para o trecho
  seguinte, o último fica aberto, e a âncora nova sai quando o prato chega a ele.
- A curva de um plano aplicado (a rampa de saída e a entrada) ocupa um trecho das amostras consumidas do prato,
  contadas pelo `_mixa`: antes dele, o disco anda a 1; nele, os segmentos da curva, com a fase pelo que já foi
  consumido; depois, a cauda. Ela vale para o deck e o `gen` dele em que o `_mede` a aplicou: o `_restart` (o seek,
  outro disco pelo `load`, a retomada depois do fim) e o `stop` sobem o `gen` e limpam a fila, e a curva sai junto. A
  volta do Repetir depois da curva, assim, segue a 1, e uma segunda passagem pelo `t_r` não traz a curva de volta.
- A rampa de saída do `_plano_dois`: a que sai vai de 1 a `sa` em meio cosseno (o `esticar_saida`) por `n_ra`
  amostras a partir do rótulo `t_r`, e segue em `sa` até o fim dos blocos esticados. O `_mede` troca a cauda da fila
  do prato por esses blocos (o `sai_q` do plano), então a âncora publicada ali leva 1 até `t_r`, o meio cosseno
  `{"de": 1, "ate": sa}`, `sa` e o último bloco (abaixo). O `va` do visor sozinho não reconstrói o meio da rampa: o PC guarda do plano
  aplicado o `t_r`, o `n_ra`, o `sa` e o total de amostras esticadas (hoje o `n_ra` é uma conta dentro do
  `_plano_dois`, que a implementação passa a devolver no plano); a curva começa na amostra consumida do bloco de
  rótulo `t_r`. O último bloco esticado, o do fim do arquivo, vai num segmento a 1 desde o rótulo dele, como o `pos`
  do `_mixa`: a última âncora andando para onde o motor congela no fim.
- A entrada esticada (o `esticar`; a mesma conta do `_visor_rampa` e do `vdjFi` do tema): `sb` por `n_sob` amostras,
  depois o meio cosseno de `1 + k` até 1 em `n_rampa`, depois a cauda. Os números saem do plano sem o arredondamento
  do `_visor_publico`, que corta `k` em 4 casas. A curva começa na virada; a fase são as amostras consumidas desde
  ela (pausa e buffering não contam).
- O preenchimento: quando a virada vem antes do início da faixa de entrada, ela começa com `pad` amostras de silêncio
  (o `cabeca` do `_plano_batida` e do `_plano_dois`; no final seco com o corte no golpe, o `pad` passa de um bloco). Os
  segmentos dele, marcados com `"preenchimento": true`, seguem os rótulos que o motor deu ao `cabeca`, com o limite em
  zero (`max(0, ini + (u - pad) / 48000)`, `u` a amostra do `cabeca`):
  - sem esticar, o `cabeca` é um bloco só, que o `_tira` parte: a posição anda a 1 desde a origem rotulada. Com a
    origem presa em zero, o motor mostra a posição indo de 0 até `pad / 48000` e voltando ao `ini` na fronteira, e a
    âncora reproduz isso;
  - esticado, o `cabeca` vem em blocos de 10 ms, cada um com o rótulo próprio: o bloco que o motor prendeu em zero vai
    num segmento com `"v": 0`, e o resto do `pad` a 1 desde o rótulo dele.

  Depois do preenchimento, o segmento seguinte leva `"pos": ini`. O `preenchimento` também deixa quem desenha a barra
  segurar o zero, se quiser.
- A passagem cancelada (o `_cancela_passagem`) limpa a preparação e o visor, mas os blocos esticados ficam na fila do
  prato: os segmentos deles seguem na âncora até serem consumidos ou trocados.
- A volta do Repetir (o `_reader`): o leitor põe a volta na mesma fila, com o rótulo voltando a 0. Ela entra na âncora
  quando chega à janela, e a âncora nova sai no primeiro bloco da volta, com a faixa e o deck iguais.
- No fim natural, a âncora congela na posição final até a próxima ação ou faixa.

### Quando a âncora muda

O `t` vem do relógio do som, não do tick. O `_mixa` produz adiantado (o Injetor enche o anel do filtro até alguns
blocos à frente do leitor), então a hora da chamada não é a hora em que a amostra toca. O `_mixa` passa a contar as
amostras de saída (`u`) e as consumidas de cada deck no prato, e o Injetor anota o par da amostra que está tocando: o
`u` dela (o escrito menos o que o leitor do anel ainda não leu) e o relógio monotônico daquele instante; sem leitor, o
relógio da saída. O instante de qualquer `u` é o anotado mais a diferença de `u`, em ms, e é assim que sai todo `t`.

O `_mixa` anota também as marcas desde o último tick: o bloco que não continua o anterior (estrutural: outro disco, ou
o primeiro depois de um bloco sem disco, a retomada; ou só o rótulo que salta) e o bloco em que o prato parou (a pausa,
o buffering, o fim), com o `u`, o rótulo e as amostras consumidas. O tick do `server.py` (o `TICK`, de 1/15 s, fora da
thread do som) lê, com o `_qlock`, o rótulo do próximo bloco e o `u` em que ele vai tocar, e publica um estado novo
quando:

- a âncora de antes, adiantada em amostras até agora, deixa de bater com a que sairia agora, a menos de meia amostra:
  o mapa mudou (passagem aplicada ou trocada, seek, a volta ou o fim do disco entrando na janela, buffering, pausa,
  retomada, virada, parada). A descontinuidade que já tocou sai com o `t`, o rótulo e a fase da marca: com curva, a
  primeira marca estrutural (a curva prevê os saltos de rótulo dela); sem curva, o último salto (a fila já não tem o
  que tocou antes dele). A pausa, o buffering e o fim saem com o `t` do bloco em que o prato parou. A âncora que
  sairia igual à de antes adiantada não publica nada;
- o prato parou e voltou entre dois ticks: saem as duas transições, em ordem, cada uma no instante dela;
- a projeção muda (faixa, status, fila, volume, abaixamento, capacidades): só com a fila ou o volume, a âncora
  publicada segue igual;
- o prato cruza a fronteira de um segmento (começo e fim de cada rampa, fim do preenchimento, a volta já prevista): a
  âncora nova é a de antes adiantada até a fronteira, com o `t` da fronteira pelo relógio do som. A âncora de antes
  ainda prevê a posição, mas a nova limita a deriva entre o relógio do som e o do PC (alguns ms por minuto, no pior
  caso). No fim do último segmento finito não sai nada: o fim do disco vem logo depois.

Fora disso, nada: entre ticks sem mudança, o `rev` fica.

## O relógio

O `agora` de cada mensagem é o relógio monotônico do PC quando ela saiu, e o `t` da âncora está no mesmo relógio. Quem
recebe guarda o desvio entre o relógio dele e o do PC como o menor `chegada - agora - retido_ms` visto desde que a
conexão abriu (ou a sessão mudou), e lê a posição em `relógio_dele - desvio`. A primeira foto e a de reconexão, assim,
já valem; com a foto atrasada, a posição fica atrás o tanto do atraso dela até chegar uma mensagem mais rápida (o pulso
vem de 1 em 1 s), e uma foto atrasada depois não piora o desvio. A foto guardada no relay chega com o `retido_ms`, e o
tempo que ela passou guardada não conta.

## O `rev` e a foto

- O `rev` sobe 1 a cada estado que o PC publica na sessão; o pulso repete o do último. A sessão nova começa no 1. O
  `rev` é do `server.py` e nunca volta numa sessão: o conector que religa ou reinicia continua o dele, e a foto de
  reconexão é `rev + 1`.
- Toda mensagem de estado leva a projeção inteira (não há diferença parcial na v1). A foto do início (`inicio`) e a
  de quando o conector religa (`reconexao`) são estados completos como os outros, com a âncora refeita na hora, com a
  fase da curva.
- O relay guarda a última foto da sessão ativa e a entrega, com o `retido_ms`, a quem conecta. Ao aceitar uma sessão
  nova, descarta a foto da anterior; descarta também o estado de outra sessão e o `rev` igual ou menor que o guardado.
- Quem recebe aplica só o estado da sessão dele com `rev` maior que o último.

## Os comandos

O vocabulário é fechado: só estes comandos, e cada um só com estes argumentos (sem campo a mais). O relay confere pelo
esquema, e o PC confere de novo. O mapa em [`comandos.json`](protocolo-remoto/v1/comandos.json) diz a rota local de
cada um: o argumento com o nome de um `{campo}` da rota vai no caminho; os outros vão no corpo, com os mesmos nomes da
API local; com mais de uma rota, vale a do argumento do `quando`. O mapa bate com a tabela do `permissao.py`: as rotas
dele e as de leitura (`GET /api/state` e `GET /api/events`) são exatamente as do papel `remoto`.

| comando | argumentos | rota local | `dados` do resultado |
|---|---|---|---|
| `tocar` | `{"id"}` (disco da prateleira) ou `{"qid"}` (entrada da fila) | `POST /api/play` ou `POST /api/queue/play` | `{}` |
| `enfileirar` | `{"id", "next"?}` ou `{"youtube_id", "title"?, "channel"?, "duration"?, "next"?}` | `POST /api/queue` | `{"qid", "tocando"}` |
| `pular` | `{}` | `POST /api/next` | `{}` |
| `pausar` | `{}` | `POST /api/pause` | `{}` |
| `retomar` | `{}` | `POST /api/resume` | `{}` |
| `tirar_da_fila` | `{"qid"}` | `DELETE /api/queue/{qid}` | `{}` |
| `mover_na_fila` | `{"qid", "to"}` | `POST /api/queue/move` | `{}` |
| `volume` | `{"vol"}` (0 a 1) | `POST /api/volume` | `{"vol"}` |
| `abaixar` | `{"db", "ms"}` (0 a 40 dB, 0 a 30000 ms inteiro) | `POST /api/abaixa` | `{"abaixa"}` |
| `sinal` | `{}` | `POST /api/sinal` | `{}` |

Mais estrito que a API local: o `tocar` não escolhe de onde toca nem se vai por cima (o disco de até 15 s segue o que o
PC decide); o `enfileirar` não manda link, capa nem disco de outro endereço; o volume fora de 0 a 1 é recusado, e não
cortado no limite.

- **Resultado.** O `ok` é a confirmação da API local, e leva o `rev` da projeção que o PC observou depois dela: o do
  estado que ele publicou por causa do comando, ou o do último publicado, quando nada que se vê mudou (o `sinal`, o
  disco curto que vai por cima, o volume igual, o abaixamento que já venceu). Os `dados` vêm numa forma só, a do
  comando do mesmo `id`. O erro leva só um código, nunca a mensagem local:
  `protocolo`, `sessao`, `fora_do_vocabulario`, `argumentos`, `id_repetido`, `sem_pc` (o PC fora do relay), `tempo`
  (o PC sem resposta no prazo), e da API local `nao_permitido` (403), `nao_encontrado` (404), `conflito` (409: a fila
  vazia no `pular`, o microfone cortado no `sinal`) e `falha_local` (o resto); o 400 vira `argumentos` e o 401,
  `sessao`.
- **Repetição pelo id.** O mesmo `id` com o mesmo comando e os mesmos argumentos recebe o resultado guardado (ou
  acompanha a execução em curso) e não executa de novo; o mesmo `id` com outro comando ou outros argumentos recebe
  `id_repetido` e não mexe em nada. Onde isso se guarda é do conector.

## Versão

O `protocolo` é 1 em toda mensagem, e os esquemas desta versão moram em `v1/`. Como nenhum esquema aceita campo a mais,
qualquer campo novo, comando novo ou mudança de sentido é a versão 2, numa pasta `v2/` ao lado, e o lado que não fala
a versão de quem pede responde o erro `protocolo`.

## As fixtures e a conferência

As fixtures ficam em [`protocolo-remoto/v1/fixtures/`](protocolo-remoto/v1/fixtures/), e o `dev/testa_protocolo.py`
(na lista `COMPLETO` do `dev/testa_tudo.py`, com o `jsonschema` do `requirements-dev.txt`) confere tudo:

- `comandos.json`: comandos válidos de todo o vocabulário, com o pedido local de cada um, e inválidos (fora do
  vocabulário, argumento a mais ou a menos, fora da faixa, outra versão, o token num campo); resultados válidos e
  inválidos (a mensagem local, código fora da lista); a repetição pelo id.
- `estados.json`: um estado local completo e a projeção que sai dele, e estados que o esquema recusa (microfone,
  aparelhos, atualização e erro local na projeção, campo da faixa ou da fila fora da lista, âncora andando com o
  prato parado e o contrário, outra taxa, velocidade zero fora do preenchimento, cosseno e preenchimento abertos); a
  projeção corta o texto, a capa, a duração e o id de vídeo fora dos limites, e tira o link do título.
- `relay.json`: a foto guardada, o `rev` antigo descartado, a reconexão, a sessão nova que troca a foto da anterior e
  o estado atrasado da sessão que acabou.
- `relogio.json`: a primeira foto guardada no relay e atrasada na rede, o erro do relógio caindo com o pulso, e uma
  foto atrasada depois que não piora.
- `posicao-*.json`: os estados que o PC publica em cada cenário, rodado no motor de verdade, sem som e sem aparelho
  (o `Engine` sem o `__init__`): o `_plano_dois` e o `_plano_batida` montam a passagem (só a medida das batidas troca
  por números fixos), o `_mede` aplica, o `_vira` vira o prato, o `_cancela_passagem` cancela e o `_tira` consome a
  fila de 10 em 10 ms; o produtor olha o prato de 7 em 7 blocos, como o tick. Cada foto reconstrói a posição só com
  ela e bate com o rótulo de cada bloco consumido, a menos de uma amostra, do `t` dela até o da foto seguinte:
  - `passagem-dois`: a rampa de saída e a entrada esticada, com o começo, o meio (reconexão) e o fim de cada meio
    cosseno, e o `pad` da virada com a origem presa em zero;
  - `passagem-cancelada`: cancelada no meio da rampa de saída, com a faixa no mesmo deck; reconexão no meio da rampa e
    antes de acabarem os blocos esticados, e o fim natural onde a última âncora parou;
  - `cancelada-repetir`: a mesma, com o Repetir: a volta depois dos blocos esticados segue a 1, com reconexão logo
    depois dela;
  - `seek-na-rampa`: o seek no meio da rampa de saída, que tira a curva junto com o `gen`;
  - `final-seco` e `final-seco-sem-limite`: o final seco sem estiramento com o `pad` maior que um bloco, a origem presa
    em zero e acima dele, e a reconexão entre a virada e o início efetivo (a posição antes, na fronteira e depois);
  - `final-seco-esticado`: o mesmo corte no golpe com a próxima esticada, o `pad` em blocos de 10 ms presos em zero;
  - `buffering`: o buffering que congela, a retomada depois dele, a pausa e a retomada, cada uma no instante em que o
    prato parou ou voltou, e uma pausa de 30 ms entre dois ticks, com as duas transições;
  - `repetir`: a volta no meio de um callback (o último bloco do arquivo é curto), prevista quando chega à fila e com a
    âncora nova no primeiro bloco dela;
  - `repetir-curto`: um som de 100 ms no Repetir, com mais voltas na janela do que cabem nos 8 segmentos;
  - `fim-natural`: a posição que para no fim sem passar dele, congelada depois, com o `rev` estável entre os ticks e o
    pulso repetindo o `rev`.

O produtor, o relay e quem recebe de referência moram no teste. Mudou o motor, o produtor ou o protocolo:
`python dev/testa_protocolo.py --gera` escreve as fixtures de novo, e o teste diz se os estados publicados mudaram.
