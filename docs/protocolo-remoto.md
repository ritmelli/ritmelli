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
novo, porque o relay não é de confiança para o PC.

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

O relay acrescenta `retido_ms` (quanto tempo segurou a mensagem) ao entregar. Nenhum esquema aceita campo a mais:
campo novo é versão nova (ver "Versão").

## A projeção

A projeção sai do estado local (o do `GET /api/state`) por lista explícita de campos. Aparelhos, microfone, volume e
efeitos da voz, atualização, erros locais, o `caps`, o arquivo e o download de cada disco nunca saem do PC.

| na projeção | do estado local |
|---|---|
| `status` | `status` (`idle`, `buffering`, `playing`, `paused`, `ended`) |
| `faixa` | do `track`: `id`, `title`, `channel`, `duration`, `youtube_id`, `thumb` (só `https://`, senão `null`) e `stream` (bool); `null` com o prato vazio |
| `fila` | de cada entrada do `queue`: `qid`, `id`, `title`, `channel`, `duration`, `youtube_id`, `thumb` (idem) e `auto` (bool) |
| `vol` | `vol`, o volume da música no jogo |
| `abaixa` | `abaixa`, o abaixamento pelo comando `abaixar`, ou `null` |
| `capacidades` | os comandos do vocabulário cujas rotas estão no `caps` do papel `remoto` |
| `ancora` | a posição (abaixo); `null` com o prato vazio |

## A posição: a âncora

A posição não vai a cada tick. Vai como âncora: a faixa no prato, a posição dela (`pos`, em segundos do disco) num
instante de referência (`t`, no relógio do PC, em ms), se ela anda (`anda`) e os segmentos de velocidade que o prato
vai seguir dali em diante, contados em amostras de saída (`taxa`: 48000 por segundo, o relógio do som). Quem recebe
integra os segmentos até o próprio relógio, convertido no do PC (ver "O relógio").

Um segmento tem `n` amostras de saída (ou `null`, aberto, só no último) e a velocidade `v` do disco nelas: um número,
ou o meio cosseno `{"de", "ate", "total", "fase"}`, com a velocidade da amostra `i` (a partir de `fase`)

```
v(i) = ate + (de - ate) * (1 + cos(pi * i / total)) / 2
```

A posição depois de `m` amostras é a de começo mais `soma(v(i)) / taxa`, e a soma do meio cosseno tem forma fechada:

```
soma de i = a até b - 1 de cos(pi * i / N) = (sin(pi * (b - 1/2) / N) - sin(pi * (a - 1/2) / N)) / (2 * sin(pi / (2 * N)))
```

Cada segmento vale de `[começo, começo + n)`: na fronteira já vale o seguinte, e o `pos` de um segmento (a posição de
começo dele, quando não continua a do anterior) entra exatamente ali. Depois do último segmento finito, a posição fica
parada. Com `anda: false` (pausa, buffering, fim), a posição é `pos` e os segmentos vêm vazios.

### O que o PC põe na âncora

O mapa de amostras do motor são os rótulos dos blocos na fila do prato: cada bloco leva a posição do disco na primeira
amostra dele, e o motor anda dentro do bloco a velocidade 1 (o `_tira` e o `pos` do `_mixa`, no `engine.py`). A
âncora reproduz esses rótulos:

- `pos` é o rótulo do próximo bloco da fila do prato, não o `pos` do motor (que soma o bloco a velocidade 1 e, numa
  rampa, fica até `(v - 1) * 10 ms` longe do rótulo seguinte). Com a fila vazia (buffering, fim), é o `pos` do motor.
- Sem passagem marcada: um segmento aberto em 1.
- A rampa de saída do `_plano_dois`: a que sai vai de 1 a `sa` em meio cosseno (o `esticar_saida`) por `n_ra`
  amostras a partir do rótulo `t_r`, e segue em `sa` até o fim dos blocos esticados. O `_mede` troca a cauda da fila
  do prato por esses blocos (o `sai_q` do plano), então a âncora
  publicada ali leva três segmentos: 1 até `t_r`, o meio cosseno `{"de": 1, "ate": sa}` e `sa`. O `va` do visor
  sozinho não reconstrói o meio da rampa: o PC guarda do plano aplicado o `t_r`, o `n_ra`, o `sa` e o total de
  amostras esticadas (hoje o `n_ra` é uma conta dentro do `_plano_dois`, que a implementação passa a devolver no
  plano). A fase da curva, numa foto tirada no meio, é o total menos o que ainda está na fila a partir de `t_r`.
- A entrada esticada (o `esticar`; a mesma conta do `_visor_rampa` e do `vdjFi` do tema): `sb` por `n_sob` amostras,
  depois o meio cosseno de `1 + k` até 1 em `n_rampa`, depois 1 aberto. Os números saem do plano sem o arredondamento
  do `_visor_publico`, que corta `k` em 4 casas.
- O preenchimento: quando a virada vem antes do início da faixa de entrada, ela começa com `pad` amostras de silêncio
  (o `cabeca` do `_plano_batida` e do `_plano_dois`; no final seco com o corte no golpe, sem esticar, o `pad` passa de
  um bloco). A âncora leva um segmento `{"n": pad, "v": 1, "preenchimento": true}` a partir
  da origem que o motor rotulou, `max(0, ini - pad / 48000)` (o limite em zero vem do motor), e o seguinte com
  `"pos": ini`. Com a origem presa em zero, o motor mostra a posição andando de 0 até `pad / 48000` e voltando ao
  `ini` na fronteira; a âncora reproduz isso, e o `preenchimento` deixa quem desenha a barra segurar o zero se quiser.
  A fase na faixa que entrou são as amostras do prato desde a virada.
- A passagem cancelada (o `_cancela_passagem`) limpa a preparação e o visor, mas os blocos esticados
  ficam na fila do prato: os segmentos deles seguem na âncora até serem consumidos ou trocados.
- A volta do Repetir (o `_reader`): o leitor põe a volta na mesma fila, com o rótulo voltando a 0; a âncora nova
  sai no primeiro bloco da volta, com a faixa e o deck iguais.
- No fim natural, a âncora congela na posição final até a próxima ação ou faixa.

### Quando a âncora muda

O PC olha o prato a cada volta do estado (o tick) e publica um estado novo quando:

- a projeção muda (faixa, status, fila, volume, abaixamento, capacidades);
- a âncora de antes, adiantada até agora, deixa de bater com a de agora: o mapa mudou (passagem aplicada, trocada ou
  cancelada com blocos diferentes, seek, volta do Repetir, buffering, pausa, retomada, virada, parada);
- o prato cruza a fronteira de um segmento (começo e fim de cada rampa, fim do preenchimento). A âncora de antes ainda
  prevê a posição, mas a nova limita a deriva entre o relógio do som e o do PC (alguns ms por minuto, no pior caso).

Fora disso, nada: entre ticks sem mudança, o `rev` fica.

## O relógio

O `agora` de cada mensagem é o relógio monotônico do PC quando ela saiu, e o `t` da âncora está no mesmo relógio. Quem
recebe guarda o desvio entre o relógio dele e o do PC como o menor `chegada - agora - retido_ms` visto desde que a
conexão abriu (ou a sessão mudou), e lê a posição em `relógio_dele - desvio`. A primeira foto e a de reconexão, assim,
já valem; com a foto atrasada, a posição fica atrás o tanto do atraso dela até chegar uma mensagem mais rápida (o pulso
vem de 1 em 1 s). A foto guardada no relay chega com o `retido_ms`, e o tempo que ela passou guardada não conta.

## O `rev` e a foto

- O `rev` sobe 1 a cada estado que o PC publica na sessão; o pulso repete o do último. A sessão nova começa no 1.
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

- **Resultado.** O `ok` leva o `rev` do estado que já mostra o comando aplicado (ele chega antes ou logo depois do
  resultado). O erro leva só um código, nunca a mensagem local:
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
  prato parado e o contrário, outra taxa, velocidade zero).
- `relay.json`: a foto guardada, o `rev` antigo descartado, a reconexão, a sessão nova que troca a foto da anterior e
  o estado atrasado da sessão que acabou.
- `relogio.json`: a foto guardada no relay e a foto atrasada na rede, e o erro do relógio caindo com o pulso.
- `posicao-*.json`: os estados que o PC publica em cada cenário, rodado no motor de verdade, sem som e sem aparelho
  (o `Engine` sem o `__init__`): o `_plano_dois` e o `_plano_batida` montam a passagem (só a medida das batidas troca
  por números fixos), o `_mede` aplica, o `_vira` vira o prato, o `_cancela_passagem` cancela e o `_tira` consome a
  fila de 10 em 10 ms. Cada foto reconstrói a posição só com ela e bate com o rótulo de cada bloco consumido, a menos
  de uma amostra, da hora dela até a próxima descontinuidade:
  - `passagem-dois`: a rampa de saída e a entrada esticada, com o começo, o meio (reconexão) e o fim de cada meio
    cosseno, e o `pad` da virada com a origem presa em zero;
  - `passagem-cancelada`: cancelada no meio da rampa de saída, com a faixa no mesmo deck; reconexão no meio da rampa e
    antes de acabarem os blocos esticados, e o fim natural;
  - `final-seco` e `final-seco-sem-limite`: o final seco sem estiramento com o `pad` maior que um bloco, a origem presa
    em zero e acima dele, e a reconexão entre a virada e o início efetivo (a posição antes, na fronteira e depois);
  - `buffering`: o buffering que congela, a retomada depois dele, a pausa e a retomada;
  - `repetir`: a âncora nova no primeiro bloco da volta;
  - `fim-natural`: a posição final congelada, com o `rev` estável entre os ticks e o pulso repetindo o `rev`.

Mudou o motor, o produtor ou o protocolo: `python dev/testa_protocolo.py --gera` escreve as fixtures de novo, e o
teste diz se os estados publicados mudaram.
