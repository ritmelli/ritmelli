# Ritmelli: contrato da API e do tema

O `server.py` toca áudio no microfone do jogo: o arquivo (e a voz da mina) vai para o filtro
do Ritmelli, que soma no microfone escolhido, dentro do áudio do Windows, e só o arquivo vai para
o fone, para o usuário ouvir o som sem ouvir a própria voz. O jogo usa o mesmo microfone. A voz
crua volta do filtro para o servidor (medidor, ouvir a própria voz): sem efeito ela segue no
microfone; o efeito de voz roda no próprio filtro, sem atraso, e a voz com efeito volta para o
fone; cortada (`mic_mute`), ou com um efeito que o filtro não roda, o servidor põe a dele no
lugar. Toda
interface é um tema em `themes/<slug>/` que fala só com esta API.

## Tema

- `themes/<slug>/index.html`, a página do tema: HTML + CSS + JS puro, sem build. Arquivo
  extra (script `.js`, fonte local, svg, imagem) mora na mesma pasta e se referencia por caminho
  relativo (`./x.svg`, `fonts/x.woff2`), servido em `/t/<slug>/x.svg`; os `.js` e os `.css` entram na página (ver
  abaixo). O `index.html` do tema, por qualquer nome do mesmo arquivo, leva à página montada, em `/t/<slug>/` (302, com a mesma query).
- Toda resposta de `/t/` sai com `Cache-Control: no-cache`: o navegador confere cada arquivo do tema com o servidor
  antes de usar o que guardou (o que não mudou volta como 304), e não usa uma letra, uma textura ou uma imagem de antes
  sem conferir.
- O slug `vitrola` é reservado: era o do tema `ritmelli` até a 0.6.0, e o servidor leva todo `/t/vitrola/...` para
  o mesmo caminho em `/t/ritmelli/` (302, com a mesma query), antes de procurar a pasta.
- `themes/<slug>/meta.json`: `{"name": "...", "direction": "...", "blurb": "uma frase"}`. Cada campo pode vir
  por língua, `{"en": "...", "pt_BR": "..."}`; a galeria mostra o da língua de quem abre (ver `GET /api/themes`).
- O ícone é do servidor, igual para todo tema: a aba do navegador pega o `/favicon.ico`
  sem nada no tema, e o atalho na tela inicial do celular pede
  `<link rel="apple-touch-icon" href="/apple-touch-icon.png">` no `<head>`.
- Nada de fora: as fontes e os scripts moram no próprio tema (as fontes em `themes/<slug>/fonts/`, com a licença ao
  lado), e nenhum script vem de outra origem.
- API sempre por caminho absoluto (`/api/...`), mesma origem. Escrita é `fetch` com
  `method` e, quando tem corpo, `Content-Type: application/json`.
- Texto da interface com acentuação completa no português e sem travessão. O servidor não
  escreve frase para a tela: manda a Mensagem (ver "Mensagens"), que o tema traduz.
- Textos traduzíveis (a interface fala pt-BR e inglês): o tema que tem a pasta
  `themes/<slug>/i18n/` guarda nela um `i18n_<lingua>.properties` por língua (`en` e `pt_BR`),
  com as mesmas chaves, e põe o comentário `<!-- i18n -->` no `<head>`, antes de qualquer
  script. A página do tema (`/t/<slug>/`) chega com esse comentário trocado por
  `window.I18N_DADOS = {"lingua": ..., "textos": {...}, "reserva": {...}}`: os textos da
  língua de quem abre e os do inglês, para a chave que faltar. A língua sai do `Accept-Language`
  do navegador: a primeira que temos na preferência dele, e o inglês quando ele não pede nenhuma
  das duas. `?lang=en` ou `?lang=pt_BR` no endereço força uma, para testar. O formato do arquivo
  está no `i18n.py`, e o `python dev/testa_i18n.py` confere os arquivos contra o tema.
- Os scripts e as folhas de estilo do tema chegam dentro da página: no `index.html`, cada um é um
  `<script src="arquivo.js"></script>` ou um `<link rel="stylesheet" href="arquivo.css">`, exatamente assim, com o
  caminho na pasta da página ou começando por `/t/` (na pasta `themes/`), e a página chega com cada um trocado por um
  `<script>` ou um `<style>` com o texto do arquivo. O `ETag` dela muda quando um arquivo muda. O arquivo que falta ou
  sai da pasta, o script com `</script` ou `<!--`, a folha com `</style` ou com `@import`, a folha de outra pasta com um
  `url()` (ou uma string de `image-set()`) que não é absoluto, `data:`, `/` ou `#`, e a tag de arquivo escrita de outro
  jeito não montam a página: a resposta é 500, com o nome do arquivo no log. A folha se lê com os escapes de CSS
  decodificados, também nos comentários e nas strings: o `@import` ou o `url()` escrito só num comentário ou numa
  string também para a montagem. O `dev/testa_mock.py` confere a troca, o `ETag`, cada recusa e o 500, e o `dev/missing_script.py`, a página
  servida.
- O tema abre também no celular, pela rede de casa (`http://<ip do PC>:8799/`): nada de
  endereço `127.0.0.1` escrito no tema e nada que dependa de mouse. Pela rede, a API só
  responde ao celular pareado (ver "Celular: pareamento"), e só no que a tabela de "Quem pode cada rota" abre para
  ele.

## Estado ao vivo: `GET /api/events` (SSE)

Use `new EventSource('/api/events')`. Eventos:

| evento | quando | `data` |
|---|---|---|
| `caps` | ao conectar, antes de todos | o que esta conexão pode fazer (ver "Quem pode cada rota") |
| `state` | ao conectar e a cada mudança | objeto Estado (abaixo) |
| `library` | ao conectar e a cada mudança | lista de Item |
| `jobs` | ao conectar e a cada mudança | lista de Job (o terminado some depois de 20 s) |
| `tick` | 15 vezes por segundo | `{"pos": s, "levels": {"mic": r, "track": r, "out": r}}` |
| `desconectado` | o PC desconectou este celular, ou a sessão remota acabou (logo depois a conexão fecha) | `{}` |

O servidor monta o `state`, a lista do `library`, a do `jobs` e o `tick` uma vez por volta (15 por segundo) e
entrega a mesma volta a todas as conexões abertas; só o `caps` e a autorização são de cada uma. O `state` e o `tick` de
uma volta saem da mesma captura: o `pos` é sempre da faixa do último `state` entregue. Uma conexão que fica para trás
(a aba em segundo plano, a rede lenta) pula para a volta mais nova, sem atrasar as outras. O `data` é JSON só em
ASCII (o que não é ASCII vai como `\uXXXX`): um texto que o UTF-8 não codifica não derruba o evento.

`levels` é RMS linear de 0 a 1, com queda suave (dBFS = 20·log10(r); -60 dB já é
silêncio). `mic` = voz (mesmo mutada, para mostrar que o microfone vive), `track` = arquivo
no mais alto dos volumes que estão soando (`vol` no jogo, ou `mon_vol` no fone quando
`monitor_on` e há fone ativo: com o jogo em zero e o fone em 15% ele ainda se mexe), `out`
= o que o jogo recebe. Se o EventSource cair, o navegador
reconecta sozinho; mostre que está reconectando.

**Estado**:
```json
{"status": "idle|buffering|playing|paused|ended",
 "track": Item ou null, "duration": 36.7 ou null,
 "vol": 0.6, "mon_vol": 0.6, "mic_vol": 1.0, "mic_mute": false,
 "volume_auto": true, "ganho_db": 0.0,
 "monitor_on": true, "loop": false,
 "effect": "nenhum", "voice_monitor": false, "voice_mon_vol": 0.8,
 "por_cima": [{"id": "...", "title": "..."}], "abaixa": null,
 "devices": {"mic": "default", "monitor": "default"},
 "active_devices": {"mic": "Microfone (Virtual Desktop Audio)", "monitor": "Alto-falantes (Virtual Desktop Audio)"},
 "microfone": {"anel": true, "leitores": 1, "folga_min_ms": 40.0, "secas": 0, "volta_max_ms": 4.5,
               "preparando": null, "efeito_no_filtro": false},
 "error": null ou Mensagem,
 "queue": [Entrada], "shuffle": false, "auto": false, "history": 3,
 "versao": "0.1.0", "api": 1,
 "visor": {"ondas": 3, "passagens": [Passagem]},
 "atualizacao": {"nova": "0.3.0" ou null, "estado": "parado", "progresso": 0.0, "erro": null ou Mensagem},
 "caps": {"papel": "pc", "rotas": ["DELETE /api/library/{iid}", "..."]}}
```
- `caps` = o que quem pediu pode fazer (ver "Quem pode cada rota"); só no `GET /api/state` (no SSE, é o evento
  `caps`).
- `abaixa` = a música abaixada no jogo pelo `POST /api/abaixa`, `{"db", "ms"}` (o pedido), enquanto vale; `null`
  quando não há, e de novo `null` sozinho no fim do prazo.
- `versao` = a versão do servidor (`versao.py`), para mostrar na tela.
- `api` = a versão deste contrato do Estado e do SSE (`API` do `server.py`, hoje 1). Sobe só quando muda algo que um
  cliente de hoje já lê: um campo ou um evento sai, muda de nome ou de sentido. Campo, evento ou rota nova não sobe:
  quem lê ignora o que não conhece. Vem no `GET /api/state` e no `state` do SSE.
- `mock` = `true` só no servidor `--mock` (as ferramentas de `dev/` só falam com ele, `dev/so_mock.py`), no
  `GET /api/state` e no `state` do SSE; o de verdade não manda o campo.
- `atualizacao` = a versão nova (ver "Versão nova"): `nova` é o número dela, ou `null`;
  `estado` é `parado`, `consultando`, `baixando`, `pronta` (o instalador baixado e conferido) ou
  `instalando`; `progresso` vai de 0 a 1 no download; `automatica: true` quando quem atualiza é a
  tarefa do Windows (ver "Versão nova").
- `track.bpm` = o andamento do disco do prato quando já foi medido (o mesmo `bpm` da Entrada da fila: o
  do começo dele, ou o do fim); sem medida, não vem.
- `visor` = o que o visor de DJ desenha (a onda correndo, a grade de batidas e a próxima entrando no
  tempo). `ondas` sobe quando a onda de um disco da prateleira fica pronta (peça de novo o
  `GET /api/onda/<id>`). `passagens` traz até duas: a que trouxe o disco do prato (ele é o `para`
  dela), enquanto a sobreposição e a volta da velocidade ainda importam, e a medida dele para a
  próxima da fila (ele é o `de`), que aparece quando o motor termina de medir (a ~3 min do fim) e some
  se a fila muda. Pular, parar ou trocar de disco limpa as duas. **Passagem**:
  ```json
  {"de": "id do que sai", "para": "id da que entra", "no_tempo": true,
   "t0": 286.0, "ini": 0.8, "v": 285.99, "va": 1.0,
   "vb": 1.02, "sob": 8.0, "rampa": 20.4, "k": 0.02, "sai": 8.0, "entra": 8.0, "grave": [3.8, 4.1],
   "grade_de": {"bpm": 100.0, "periodo": 0.6, "fase": 279.4, "de": 274.0, "ate": 294.0},
   "grade_para": {"bpm": 98.0, "periodo": 0.61, "fase": 1.27, "de": 0.8, "ate": 20.8}}
  ```
  `t0` = onde a próxima começa, no tempo do `de`; `ini` = onde ela começa no tempo dela; `v` = onde
  os volumes começam a cruzar (até uns ms antes do `t0`); `va` = a velocidade do `de` ali (1, ou a dele
  já mudada quando os dois andamentos mudam). A velocidade da próxima, em segundos de saída (o relógio
  do som) desde o `t0`: `vb` por `sob` s, depois `1 + k·(1 + cos(π·r/rampa))/2` por `rampa` s (`r`
  desde o fim do `sob`), depois 1. `sai` e `entra` = quanto o `de` leva para calar (cosseno) e a
  próxima para subir (seno), em s de saída desde o `v`; `grave` = a troca de grave no mesmo relógio
  (até o primeiro o grave é do `de`, depois do segundo é da próxima), ou `null`. `grade_de` e
  `grade_para` = a grade de batidas de cada um no tempo do próprio disco (`fase` é uma batida), válida
  de `de` a `ate`, ou `null`. `no_tempo: false` = só o cruzamento de volume: sem grade e com o
  `motivo` (texto do log).
- `track` tocando pelo stream do YouTube (vídeo que ainda não chegou na prateleira) vem
  com `"stream": true` e `"job": "<id do download>"`; o `id` é o do vídeo, que vira o id do
  disco quando o download termina. Enquanto o endereço do stream não sai (1 a 3 s), o
  status é `buffering`. Quando o arquivo chega, o `track` vira o Item da prateleira sem
  parar o som.
- `queue` = a fila (A seguir), na ordem em que vai tocar: quando o disco do prato acaba
  (`ended`), o primeiro entra. Com `loop` ligado o disco não acaba e a fila espera. Com nada
  no prato (`idle` ou `ended`), o que entra pelo `POST /api/queue` toca na hora em vez de
  esperar; `paused` ainda é disco no prato, e a fila só guarda.
  Servidor antigo não manda `queue`: sem ele, o tema esconde a fila.
- `shuffle` = Aleatório, como no YouTube Music: ligar embaralha a
  `queue` (a ordem nova é a que vem aqui e a que toca); com ele ligado, o que entra pelo
  `POST /api/queue` cai num lugar sorteado, e o `next` segue indo logo a seguir; desligar
  volta a ordem montada, sem os que já saíram. Arrastar com ele ligado muda a ordem de tocar,
  não a montada. Volta desligado quando o servidor sobe.
- `auto` = Automático, como no YouTube Music: ligado, a fila nunca
  acaba. O último disco que o usuário escolheu (qualquer um que o Automático não pôs) é a
  semente, e o rádio do YouTube Music dela (sem ele, o Mix do YouTube) mantém 5 parecidas
  no fim da `queue`, com `"auto": true`
  e `"auto_de": "título da semente"`. O que o usuário põe na fila entra antes delas; semente nova
  troca as parecidas; o que já tocou nesta sessão e o que ele tirou da fila não voltam, nem a
  mesma música em outro vídeo; vídeo com menos de 1 min ou mais de 10 min não entra. As
  parecidas vêm em ordem de andamento (sobem no círculo das oitavas para a
  passagem cair no tempo), e a ordem delas na `queue` pode mudar sozinha enquanto as medidas
  chegam; a que o usuário arrasta fica onde ele pôs. A que veio como vídeo troca sozinha pela versão
  só de áudio quando o YouTube Music tem (a faixa do álbum, sem a intro do clipe), e então vem
  com `"tipo": "ATV"` e o vídeo de antes em `"video"`. A parecida fora da prateleira toca
  só pelo stream (o `track` vem com `"auto": true`, `"auto_de"` e `"job": null`) e não
  baixa; guardar é o `POST /api/library` de sempre. Se o YouTube não libera o áudio dela,
  pula para a seguinte. Desligar tira as parecidas da fila. Fica salvo no `config.json`.
  Servidor antigo não manda `auto`: sem ele, o tema esconde a chave.
- `history` = quantos discos o Anterior tem para trás (os que saíram do prato, até 50; o
  parado pelo `POST /api/stop` conta). Servidor antigo não manda `shuffle` nem `history`:
  sem eles, o tema esconde Aleatório, Anterior e Próxima.
- `vol` = volume do arquivo no jogo (o que os outros ouvem), 0 a 1.
- `mon_vol` = volume do arquivo no fone do usuário, 0 a 1.
- `mic_vol` = volume do microfone em uso nas configurações de som do Windows, 0 a 1 (o mesmo número de lá): o servidor grava no Windows e lê de volta, então mudar por lá também mexe na barra. O soundboard não tem ganho próprio de voz, e o valor não vai no `config.json` (quem guarda é o Windows).
- `mic_mute` = voz cortada (o arquivo segue indo).
- `volume_auto` = o volume automático, como no Spotify: a música mais alta que -11 LUFS desce até ele, e a mais
  baixa sobe até ele, no máximo +9 dB, com um limitador que não deixa o que ela subiu passar de 0 dBFS. Ligado de
  fábrica; vai no `config.json`. `ganho_db` = quanto o disco do prato subiu (positivo) ou desceu (negativo) agora
  (0 = como veio; anda em rampa quando a medida
  chega com ele tocando, ou quando a chave muda). Servidor antigo não manda: sem eles, o tema esconde a chave.
- `monitor_on` = o arquivo toca também no fone do usuário.
- `loop` = repete o disco do prato sem parar. Vale só para esse disco: outro entrando (prateleira,
  Próxima, Anterior, fila) ou o disco saindo do prato (`POST /api/stop`) desliga, e o `loop` do
  `POST /api/play` manda sobre isso. O mesmo disco tocado de novo, a troca do stream para o arquivo
  e o som por cima não desligam. Ligado com o prato vazio, vale para o disco que entrar.
- `effect` = efeito de voz ativo (id de `/api/effects`); o servidor sempre sobe em `nenhum`.
- `pedal_voz` = só onde há o pedal de troca de voz (ver "Pedal de troca de voz"): `{"voz": "mina", "visor": null,
  "progresso": null}`. Sem o pedal, o campo não vem.
- `por_cima` = sons curtos tocando agora junto da música (ver `POST /api/play`); não mexem
  em `track`, `status` nem na barra, e o pausar e o parar calam todos.
- `voice_monitor` = a voz, já com o efeito, toca também no fone do usuário; vale mesmo com
  `mic_mute`, então serve para testar um efeito sem ninguém no jogo ouvir.
- `voice_mon_vol` = volume da própria voz no fone, 0 a 1.
- `ended` = o arquivo chegou ao fim; `resume` recomeça do zero. Falha de leitura também
  termina em `ended`, com a Mensagem em `error`: mostre `error` sempre que vier preenchido.
- `error` é uma Mensagem (ver "Mensagens"): o que houve e o que fazer. Também traz avisos, como o
  microfone escolhido que sumiu e o que entrou no lugar.
- Fone em "nenhum" (`active_devices.monitor` vazio) torna `monitor_on` sem efeito.
- `microfone` = o filtro no microfone em uso: `anel` = a memória do filtro aberta, `leitores` =
  quantos filtros do microfone em uso estão lendo (0 = a música não chega nele), `folga_min_ms` =
  o menor tanto de música que o anel teve desde que o áudio abriu (`null` antes do primeiro leitor),
  `secas` = quantas vezes ele estava vazio (o jogo ouviu um buraco), `volta_max_ms` = a maior demora
  da thread que escreve nele, `preparando` =
  o microfone que o Windows está preparando para o Ritmelli agora (a tarefa do instalador; o som
  do PC some uns segundos), ou `null`; `efeito_no_filtro` = o efeito de voz ativo roda no filtro
  (sem atraso); `false` com efeito ligado = ele vai pelo servidor, com ~30 ms de atraso.

**Item** (biblioteca):
```json
{"id": "w6kKVs-h9Ns", "title": "...", "file": "w6kKVs-h9Ns.webm", "duration": 36.7,
 "youtube_id": "w6kKVs-h9Ns" ou null, "thumb": "https://i.ytimg.com/vi/<id>/mqdefault.jpg" ou null,
 "channel": "..." ou null, "added": "2026-10-17T13:34:56", "last_pos": 807, "plays": 3, "rapido": true,
 "lufs": -14.1}
```
`rapido` = posto nos Sons rápidos pela mão (ausente = não); no celular ele toca por cima
da música com `por_cima`, como os de até 15 s, e o motor toca ele inteiro, até 2 min.
`last_pos` = onde parou da última vez (segundos); vale oferecer "continuar de mm:ss"
quando for maior que uns 5 s. `plays` = quantas vezes o disco foi escutado: conta quando
toca de fato 30 s (ou 80% dele, se for mais curto) desde que entrou no prato; ausente = 0
(item que nunca tocou, ou servidor antigo). O tema `ritmelli` põe as mais escutadas primeiro.
`lufs` = a sonoridade do disco inteiro (LUFS integrado, EBU R128), que o volume automático usa; o servidor mede a
prateleira aos poucos, então ausente = ainda não medido.

**Job** (download):
```json
{"id": "ce14abe3", "kind": "download", "label": "texto ou título", "status": "running|done|error",
 "progress": 0.42, "error": null ou Mensagem, "item_id": null ou "id", "play": true,
 "alvo": "id do vídeo, ou o link ou texto quando não há id"}
```

**Entrada** (fila):
```json
{"qid": "4f1c2a9b", "id": "id do disco" ou null, "youtube_id": "..." ou null, "url": null ou "link",
 "title": "...", "channel": "..." ou null, "thumb": "..." ou null, "duration": 233 ou null,
 "job": null ou "id do download que a fila começou",
 "auto": true e "auto_de": "título da semente", só nas parecidas do Automático,
 "bpm": 96.0, o andamento do começo dela, só quando já foi medido}
```

Estado inicial sem SSE: `GET /api/state` (Estado + `pos` + `levels`), `GET /api/library`,
`GET /api/jobs`.

## Mensagens

O servidor não escreve frase para a tela. Todo erro e aviso que a tela pode mostrar (o `error` do
Estado, o do Job e o das respostas, e o `erro` da versão nova) vem como **Mensagem**:
```json
{"key": "server.download.failed", "params": {"reason": "HTTP Error 403: Forbidden"},
 "text": "The download failed (HTTP Error 403: Forbidden). Check the link or try another video."}
```
- `key` e `params`: mostre o texto da chave nos arquivos do tema (`themes/<slug>/i18n/`), com os
  `{param}` trocados. As chaves começam com `server.`; a lista, com o texto de cada uma, está nos
  `.properties` do tema `ritmelli`, e o `python dev/testa_i18n.py` confere que todo tema com a pasta
  `i18n/` tem todas, com os mesmos params.
- Um param pode ser outra Mensagem: o motivo que já é nosso, como o aparelho que sumiu dentro do
  "não consegui abrir o áudio". Traduza ela também.
- `text`: a mesma mensagem em inglês, para o log e para quem chama a API sem tema. A Mensagem sem
  `key` é a que nenhuma tela deveria ver (o pedido feito errado, a rota que só outro programa
  chama): mostre o `text`.
- O detalhe técnico (o motivo do yt-dlp, o erro do Windows) vai como veio, num param, em geral o
  `reason`. Ele pode trazer o caminho inteiro de um arquivo; o tema `ritmelli` mostra só o nome.

## Comandos

Todos respondem `{"ok": true, ...}` ou `{"ok": false, "error": Mensagem}` com status 4xx/5xx.

| comando | corpo | efeito |
|---|---|---|
| `POST /api/play` | `{"id": "<item>", "start": 12.5?, "resume": true?, "loop": bool?, "por_cima": bool?}` | toca o item (do zero, de `start`, ou de `last_pos` com `resume`); item de até 15 s sem `start` nem `resume` toca **por cima** da música (buzina, bordão: não troca a faixa, vários juntos, até 8) e responde `{"ok": true, "por_cima": true}`; `por_cima` força um ou outro |
| `POST /api/toggle` | - | pausa ou continua; pausar cala também os sons por cima |
| `POST /api/pause` / `POST /api/resume` | - | idem, explícito |
| `POST /api/stop` | - | descarrega o arquivo, desliga o `loop` e cala os sons por cima (a voz segue); o disco entra no `history` |
| `POST /api/next` | - | Próxima: tira o primeiro da `queue` e toca, e responde `{"entry": ...}` com a entrada que tocou; logo depois de uma passagem automática, a entrada que acabou de entrar nela; dois sobrepostos podem dividir o avanço, e aí tocam uma só e respondem a mesma quando a espera do segundo devolve a entrada (a regra em [Dois Próximos juntos](#dois-próximos-juntos)); fila vazia, ou o prato que trocou de disco no meio, = 409 |
| `POST /api/prev` | - | Anterior do Spotify: com mais de 3 s de disco (ou nada antes dele), volta ao começo (`{"did": "inicio"}`); senão toca o último do `history`, e o disco do prato vai para o topo da `queue` (`{"did": "anterior"}`); nada no prato nem antes = 409 |
| `POST /api/seek` | `{"t": 90}` | pula para t segundos |
| `POST /api/volume` | `{"vol": 0.5}` | só o volume da música no jogo, de 0 a 1 (fora disso, o limite), com a mesma validação do `vol` do `/api/settings`, e grava só ele no `config.json`; responde `{"ok": true, "vol": 0.5}`; sem número, 400. É o volume que o remoto pode mudar |
| `POST /api/abaixa` | `{"db": 12, "ms": 3000}` | abaixa a música no jogo `db` decibéis (até 40) por `ms` milissegundos (um inteiro, até 30000), sem gravar nada, e ela volta sozinha no prazo (o fone de quem toca segue igual); um pedido novo troca o de antes, e zero em qualquer um tira o abaixamento na hora; responde `{"ok": true, "abaixa": {"db", "ms"} ou null}`; fora da faixa, 400 |
| `POST /api/sinal` | - | um bipe curto de teste (0,4 s, 880 Hz, -18 dBFS) no microfone, no que o jogo ouve, sem passar pelo volume da música; responde `{"ok": true}`; com a voz cortada (`mic_mute`), não toca (e o que tocava para) e responde 409 |
| `POST /api/effects/reload` | - | só no PC: lê o `fx.py` de novo sem reiniciar o servidor nem cortar a música; responde `{"ok": true, "effects": n, "effect": "<id>"}` |
| `POST /api/settings` | qualquer de `vol`, `mon_vol`, `mic_vol`, `mic_mute`, `monitor_on`, `loop`, `shuffle`, `auto`, `effect`, `voice_monitor`, `voice_mon_vol`, `volume_auto` | ajusta ao vivo (`vol`, `mon_vol` e `voice_mon_vol` de 0 a 1, e fora disso o limite; o que não é número responde 400 e nada muda); salva `vol`, `mon_vol`, `monitor_on`, `voice_mon_vol`, `auto` e `volume_auto` (`mic_vol` vai direto para o Windows); `mic_mute`, `loop`, `shuffle`, `voice_monitor` e o efeito voltam ao padrão quando o servidor sobe |
| `GET /api/onda/<id>` | - | a onda do disco para o visor de DJ: `{"id", "passo": 0.04, "n", "completa", "fonte": "arquivo" ou "stream", "versao", "onda"}`, `onda` em base64 de `n` colunas de 3 bytes (grave até 200 Hz, médio até 2 kHz, agudo até 6 kHz), cada uma de `passo` s do disco, em dB de -60 (0) a 0 (255); ~24 KB para 4 min. O motor lê a do disco da prateleira inteira quando ele entra no prato ou na passagem; a do stream só chega até onde o áudio já foi decodificado (`completa: false`: peça de novo). 404 = ainda não tem |
| `GET /api/effects` | - | `[{"id","grupo","latencia_ms"}]`, na ordem de exibição; `grupo` é o id do grupo, vazio no "Sem efeito"; os grupos hoje são `radio` (Rádio e alto-falante), `ambiente` e `personagem`. O nome e a descrição de cada efeito e o nome de cada grupo são textos do tema, nas línguas dele: `effect.<id>.name`, `effect.<id>.desc` e `effect.group.<grupo>` (o `python dev/testa_i18n.py` confere que todo tema com a pasta `i18n/` tem os de todos os efeitos do `fx.py`). O item `pistavoz` (o pedal de troca de voz, quando existe) traz também `"vozes": ["mina", "lira"]` |
| `POST /api/pedal_voz` | `{"voz": "lira"}` | escolhe a voz do pedal de troca de voz (uma das `vozes` do item `pistavoz` de `/api/effects`); responde `{"ok": true, "pedal_voz": {...}}`. Sem o pedal, 404; voz que não é dele, 400; o módulo sem resposta em 15 s, 504; um erro do módulo, 500 com o motivo. Ligar e desligar o pedal é o `effect` de sempre |
| `GET /api/search?q=<texto ou link>&n=8&start=0` | - | busca no YouTube (link ou id colado devolve o próprio vídeo): `[{"youtube_id","title","duration","channel","thumb","in_library","id"}]` (leva 2 a 6 s); `n` até 20 por vez, `start` pula os primeiros (o "carregar mais": o servidor pede `start+n` ao YouTube e devolve do `start` em diante, até 200; link com `start` devolve vazio) |
| `GET /api/musica?q=<pedido>&n=3` | - | busca de música no YouTube Music, a do pedido falado: com o melhor resultado sendo um artista e o pedido só o nome dele, as mais tocadas dele ("Raul" -> Metamorfose Ambulante); senão, as músicas e vídeos da busca. Mesmo formato do `/api/search`; até 4 s, senão 502 (quem pede cai no `/api/search`) |
| `POST /api/aquece` | - | alguém vai pedir (a mina chama quando uma fala começa): renova as conexões com o YouTube paradas há mais de 180 s no processo do endereço e nas reservas (o YouTube fecha a parada aos ~240 s) e abre o processo do endereço que está vazio; responde na hora `{"ok": true, "aquecidos": n}` |
| `POST /api/library` | `{"youtube_id": "..."}` ou `{"url": "..."}` ou `{"query": "..."}`, mais `"play": bool`, `"title"?`, `"channel"?`, `"thumb"?`, `"duration"?` | baixa para a biblioteca (Job); com `play`, toca na hora pelo stream do YouTube enquanto baixa e responde `{"job": ..., "streaming": true}` (título, canal, capa e duração do corpo aparecem no prato desde o primeiro instante); se já existe, responde `{"item": ...}` e toca na hora; o mesmo vídeo já baixando não baixa de novo; com `play`, o corpo segue a regra do `POST /api/queue`, conferida antes de olhar a prateleira, como lá (`title`, `channel` e `thumb` como texto ou `null`, `duration` em segundos, de 0 a 86400, ou `null`, e o alvo e os textos em Unicode válido, senão 400; a `duration` de mais de um dia, com a mensagem `server.queue.tooLong`); sem `play`, só o alvo e o `title`, que é o rótulo do download |
| `POST /api/queue` | `{"id": "<disco>"}` ou `{"youtube_id": "...", "title"?, "channel"?, "thumb"?, "duration"?}` ou `{"url": "..."}`, mais `"next": bool?` | põe na fila (no fim, ou logo a seguir com `next`); vídeo fora da prateleira já começa a baixar; com nada no prato, toca na hora em vez de entrar na fila (se o fim do disco já estava avançando para outra, só entra na fila, com `playing: false`); de qualquer papel, `title`, `channel` e `thumb` vão como texto ou `null` (o `thumb` do remoto não vale: a capa é a do vídeo), `duration` em segundos (de 0 a 86400) ou `null`, e o alvo e os textos em Unicode válido (UTF-8), senão 400 (a `duration` de mais de um dia, com a mensagem `server.queue.tooLong`); responde `{"entry": Entrada, "job": Job ou null, "playing": bool}` |
| `DELETE /api/queue/<qid>` | - | tira da fila (parecida do Automático tirada não volta nesta sessão) |
| `DELETE /api/queue` | - | esvazia a fila (as parecidas que estavam nela não voltam; com o Automático ligado, entram outras) |
| `POST /api/queue/move` | `{"qid": "...", "to": 0}` | muda a entrada de lugar (`to` a partir de 0) |
| `POST /api/queue/play` | `{"qid": "..."}` | tira da fila e toca agora |
| `PATCH /api/library/<id>` | `{"title": "..."}` e/ou `{"rapido": bool}` | renomeia (o `title` em Unicode inválido é 400); `rapido` põe ou tira o disco dos Sons rápidos do celular (os de até 15 s já estão lá sem isso) |
| `DELETE /api/library/<id>` | - | apaga da biblioteca (e o arquivo); o disco no prato segue tocando e o arquivo dele sai quando o motor largar |
| `GET /api/devices` | - | `{"inputs": [...], "outputs": [...], "default_input", "default_output", "current", "active", "filtro"}`; `filtro` é `{"filtro": bool, "melhorias": bool}` do microfone em uso (o filtro pendurado nele, e as melhorias de áudio do Windows ligadas, sem as quais ele não carrega), ou null se não deu para ler |
| `POST /api/devices` | `{"mic"?: nome ou "default", "monitor"?: nome, "default" ou ""}` | troca dispositivo (reabre o áudio); microfone sem o filtro (apareceu depois da instalação) é preparado pela tarefa do instalador, sem UAC (ver `microfone.preparando`) |
| `GET /api/boas-vindas` | - | `{"mostrar": bool}`: verdadeiro na primeira vez no PC (prateleira vazia e as boas-vindas nunca fechadas); pelo celular, sempre falso |
| `POST /api/boas-vindas` | - | só no PC: as boas-vindas foram vistas e não voltam (fica no `config.json`) |
| `GET /api/metricas` | - | só no PC: `{"situacao", "politica", "texto", "texto_atual"}`, os dados de uso e os erros (`metricas.py`, o [PRIVACIDADE.md](PRIVACIDADE.md)): `situacao` é `"ligada"`, `"desligada"`, `"decidir"` (ninguém escolheu: o tema mostra o aviso) ou `"fora"` (pelo código ou no `--mock` sem o `--metricas-teste`, nunca envia); `politica` é o endereço da política; `texto` é a versão do texto em que a escolha que vale foi feita (a do app, senão a do instalador; 1 para a escolha de antes das versões, 0 sem escolha ou com `"fora"`) e `texto_atual`, a de agora: com `"ligada"` e `texto` menor, o tema mostra o aviso de novo |
| `POST /api/metricas` | `{"ligar": bool}` | só no PC: a escolha de quem usa, que vale sobre a da página do instalador; grava no `config.json` o `metricas` e o `metricas_texto` (o `texto_atual`) juntos; responde como o `GET`; com `"fora"`, 409 |
| `GET /api/themes` | `?lang` (opcional) | `[{"slug","url","name","direction","blurb"}]`, cada texto na língua de quem pede (o `?lang=` ou o `Accept-Language`), quando o `meta.json` traz por língua |
| `POST /api/shutdown` | - | desliga o servidor (a música para de tocar no microfone; a voz segue normal, sem efeito); a janela própria fecha junto |
| `POST /api/janela/foco` | - | só no PC: traz a janela própria (`janela.py`) para a frente, restaurada se estava minimizada; 404 quando o Ritmelli abriu no navegador (sem o WebView2, ou com `--no-browser`). É o que o Ritmelli aberto de novo pede ao que já está ligado |
| `GET /api/lan` | - | `{"url": endereço do PC na rede de casa, ou null}` |
| `POST /api/parear` | `{"codigo": "482913"}` (espaço vale) | o celular manda o código que o PC mostra; certo, responde com o cookie da chave; errado, 403 com o motivo |
| `GET /api/pareamento?caminho=/t/<slug>/` | - | só no PC: `{"url", "codigo", "vale_s", "queimado", "qr", "celulares"}` (ver "Celular: pareamento") |
| `POST /api/pareamento/codigo` | - | só no PC: troca o código (e traz um de volta depois de queimado) |
| `DELETE /api/pareamento/<id>` | - | só no PC: desconecta o celular, que volta a precisar do código |
| `GET /api/atualizacao` | - | só no PC: `{"ativa", "versao", "estado", "progresso", "erro", "consultada", "nova": {"versao", "data", "notas", "tamanho", "parcial"} ou null}`, e `"automatica": true` com a tarefa do Windows (ver "Versão nova"); `notas` é `{"pt_BR": [...], "en": [...]}`, as da versão em cada língua (a lista pode vir vazia: mostre a da outra) |
| `POST /api/atualizacao/consultar` | - | só no PC: consulta agora e responde como o `GET` |
| `POST /api/atualizacao/baixar` | - | só no PC: começa o download do instalador da versão nova; sem versão nova, 409 |
| `POST /api/atualizacao/instalar` | - | só no PC: abre o instalador baixado, com o pedido de permissão do Windows, e o servidor desliga; automática, o servidor desliga, a tarefa instala e o Ritmelli abre de novo; recusado ou ainda não baixado, 409 com o motivo |

### Dois Próximos juntos

Dois `POST /api/next` podem dividir um avanço enquanto o grupo do primeiro está aberto; quando dividem, tocam uma
entrada só e respondem a mesma quando a espera do segundo devolve a entrada (abaixo). O que conta é quando cada comando
roda (no executor do servidor), não quando o pedido chegou: o primeiro registra o grupo dos Próximos logo no começo do
comando e o retira ao terminar, depois de gravar a posição do disco que saiu, e a resposta dele sai logo depois.
Enquanto o grupo ainda espera o avanço, inclusive com a troca do disco publicando, o segundo se junta a ele se o prato
segue na linha do primeiro (o mesmo disco, sem pulo na barra) ou na linha que o avanço dele está publicando. Se o
primeiro está conciliando uma passagem automática, o grupo passa para a linha da virada, e o segundo que se junta recebe
a entrada da passagem, se ela ainda estava na fila, ou a primeira da fila, que o primeiro toca, se já tinha saído.
Depois que o grupo tem o resultado, só se junta quem chega se ele tocou uma entrada e o prato segue na linha que ele
publicou. Fora disso, o segundo abre o próprio grupo, como um Próximo novo; se outro avanço reservar primeiro na linha
dele (o do primeiro, depois de um pulo na barra, ou o do fim do disco), o segundo espera o resultado dessa reserva e
responde a entrada que ela tocar, e quando a reserva é a do primeiro os dois respondem a mesma entrada, mesmo em grupos
distintos, quando a espera do segundo devolve a entrada (o [comandos.md](docs/arquitetura/comandos.md) descreve cada
caso). O segundo que espera o avanço de outro (o que se junta ao grupo, ou o que recebe a reserva de outro) espera até 5
s e responde 409 se a espera terminar sem uma entrada: passado o prazo (o primeiro, que fez o avanço, ainda responde a
entrada que tocou), ou com o avanço sem tocar nada:

| o segundo roda | o prato entre os dois | o primeiro responde | o segundo responde |
|---|---|---|---|
| depois de o primeiro abrir o grupo, antes de ele reservar o avanço | nada mudou | a primeira da fila | a mesma |
| depois de o primeiro abrir o grupo, antes de ele reservar o avanço | parou | 409 | a primeira da fila, que toca no prato parado |
| com o primeiro trocando o disco | não muda: a troca segura o motor | a primeira da fila | a mesma |
| com o primeiro gravando a posição | nada mudou | a primeira da fila | a mesma, na hora |
| com o primeiro gravando a posição | parou, pulou na barra ou trocou de disco | a primeira da fila | a seguinte, que ele toca |
| depois de o comando do primeiro terminar | | a primeira da fila | a seguinte |
| depois de o primeiro achar a fila vazia, antes de ele terminar | uma entrada entrou na fila | 409 | a entrada que entrou, que ele toca |

O `dev/testa_comandos.py` confere cada linha desta tabela.

## Pedal de troca de voz

O pedal que troca a voz de quem fala pela de uma das vozes do
[ritmelli-voices](https://github.com/ritmelli/ritmelli-voices), no lugar do Alienígena (`alien`). Quem faz é o módulo
`pistavoz` (o `pistavoz.py`, ao lado do código; o `fx.py` o acha pelo `importlib.util.find_spec("pistavoz")`). Módulo
que não importa, que quebra ao importar ou que não cumpre o contrato abaixo conta como ausente, com o motivo no log, e
o Alienígena volta. O contrato com o módulo:

- `pistavoz.impedimento()` (opcional): o `fx.py` chama ao carregar o módulo; `None` com o pedal pronto para aparecer,
  ou o motivo de ele ficar de fora (sem placa de vídeo, sem as vozes baixadas), que vai para o log, e o Alienígena volta.
- `pistavoz.dados(pasta)` (opcional): o servidor chama ao subir, com a pasta de dados dele (a do `library.json`; no
  `--mock`, a temporária). O módulo guarda ali o que é de quem usa (a voz escolhida e o tom medido de quem fala).

- `pistavoz.VOZES`: a lista de ids das vozes, da mais grave para a mais aguda (ex. `["mina", "lira"]`); vai para o
  `vozes` do item `pistavoz` de `/api/effects`. O pedal mostra as duas primeiras, e o leitor de tela diz qual é a mais
  grave e qual a mais aguda por essa ordem.
- `pistavoz.estado()`: `{"voz": <id>, "visor": None | "fale" | "ouvindo" | "pronto", "progresso": 0..1 | None}`; vai
  para o `pedal_voz` do Estado (e do SSE). `visor` é o passo do ajuste que o pedal mostra no visor em vez da voz: `fale`
  (pede para a pessoa falar), `ouvindo` (com o `progresso` de 0 a 1, que o servidor arredonda em passos de 1/12) e
  `pronto`; `null` = o visor mostra a voz. O `estado()` roda no laço do servidor uma vez a cada volta do SSE (a mesma
  para todas as páginas abertas) e a cada `GET /api/state`: tem de responder na hora, sem disco nem rede, e aguentar um
  `escolhe()` ou `liga()` chegando de outra thread.
  Uma voz que não é das `VOZES` sai como a primeira; um erro sai como a primeira voz sem passo, e vai para o log uma vez.
- `pistavoz.escolhe(voz)`: troca a voz, e a voz que já está escolhida refaz o ajuste do tom (o clique nela de novo);
  chamado pelo `POST /api/pedal_voz`, fora do laço, numa thread só dele e na
  ordem dos pedidos; tem de voltar em até 15 s (depois disso o pedido responde 504, e o que ainda está na fila não
  chega ao módulo); um erro dele volta para quem pediu como 500, com o motivo.
- `pistavoz.liga(ligado)`: chamado a cada troca de efeito, `True` ao entrar no `pistavoz` e `False` ao sair dele (pode
  repetir o mesmo valor), e `False` também quando o app fecha (o fechar espera por ele até 2 s). Roda numa thread só
  dele, na ordem das trocas, nunca no laço do servidor; um erro dele vai para o log. O servidor sobe em `nenhum`,
  então o módulo começa desligado. No `--mock` o engine não chama o `liga()`.

O efeito `pistavoz` em si não mexe na voz do lado do Ritmelli (como o `nenhum`): quem troca a voz é o módulo, entre o
`liga(True)` e o `liga(False)`. O `pistavoz.py` sobe o processo da troca de voz (`ritmelli.py --pistavoz`, o
`pista.py`), que lê a voz crua pelo anel do filtro, converte pelo `conversor.py` (o RVC em ONNX, no DirectML) e
escreve na pista da voz, que o filtro põe no lugar da voz do microfone. Os modelos são os das releases que o
`vozes.json` fixa, com o tamanho e o sha256 de cada arquivo: o instalador baixa para a pasta `vozes\` do app, e quem roda
pelo código baixa com `python dev/vozes.py baixa`.

O tom: cada voz traz no `voz.json` da release dela o tom em que soa certa (`tom_hz`, aprovado de ouvido), e o
deslocamento leva o tom de quem fala até ele. O tom de quem fala é o percentil 20 dos quadros com tom, que quase não
muda quando a pessoa se anima, e se mede uma vez: sem ele guardado, ligar o pedal sobe o processo no ajuste, com o
microfone mudo (a voz de verdade não vaza), e o visor passa por `fale`, `ouvindo` (o `progresso` é o tempo de fala
medido, 8 s ao todo) e `pronto`, que fica 1,5 s antes de o visor voltar para a voz. Uma medida serve para todas as
vozes; clicar na voz escolhida mede de novo, e sair do pedal no meio do ajuste não guarda nada.

O tema mostra o pedal com o visor e as vozes (o rótulo da escolhida aceso) e manda
`POST /api/pedal_voz` no clique de cada uma. Textos do tema: `effect.pistavoz.name`, `effect.pistavoz.desc` e os do
visor.

## Quem pode cada rota

O `guard` do servidor confere o Host e a Origin de sempre e depois a tabela do `permissao.py`:
`(método, rota) → papéis`, com a rota como o aiohttp a escreve (`/api/library/{iid}`, sem o id) e o `HEAD`
valendo como o `GET`. Rota fora da tabela é só do PC. Os papéis:

- `pc`: quem conecta pelo `127.0.0.1` sem o cabeçalho do remoto. Pode tudo.
- `celular`: da rede de casa, com a chave do pareamento no cookie (ver "Celular: pareamento").
- `publico`: da rede de casa, sem chave que valha: só o tema, os arquivos dele, a galeria, o `GET /api/themes` e o
  `POST /api/parear`. O resto que o celular pode responde 401 (o do pareamento); o que é só do PC, 403.
- `remoto`: quem conecta pelo `127.0.0.1` (só o IPv4) com o cabeçalho `X-Ritmelli-Remoto: <token>`, o token de uma
  sessão remota aceita (`secrets.token_urlsafe(32)`, gerado a cada sessão e revogado quando ela acaba). O cabeçalho
  com token errado, vencido ou vindo de fora do `127.0.0.1` responde 401, mesmo do `127.0.0.1`: quem manda o
  cabeçalho nunca cai no papel do PC. Comando fora da lista dele, 403; no `POST /api/queue`, ele só põe o `id` de um
  disco da prateleira ou um vídeo do YouTube (`youtube_id` ou link), com a capa do próprio disco ou vídeo, e
  `title`, `channel`, `thumb` e `duration` seguem a regra de todo papel (ver o `POST /api/queue`); o resto é 400. A sessão que acaba enquanto o corpo do pedido chega também dá 401. Por ora nenhuma
  sessão abre um token. O que a sessão remota manda e recebe pela internet está no
  [protocolo da sessão remota](docs/protocolo-remoto.md).

| rota | `pc` | `celular` | `remoto` | `publico` |
|---|---|---|---|---|
| as páginas e os arquivos dos temas (`/t/...`), a galeria (`/`), os ícones, `GET /api/themes`, `POST /api/parear` | sim | sim | 403 | sim |
| `GET /api/state`, `GET /api/events` | sim | sim | sim | 401 |
| `POST /api/play`, `POST /api/queue` (o remoto, só disco da prateleira ou vídeo do YouTube), `POST /api/queue/play`, `POST /api/next`, `POST /api/pause`, `POST /api/resume`, `DELETE /api/queue/<qid>`, `POST /api/queue/move` | sim | sim | sim | 401 |
| `POST /api/volume`, `POST /api/abaixa`, `POST /api/sinal` | sim | 403 | sim | 403 |
| `GET /api/onda/<id>`, `GET /api/library`, `GET /api/jobs`, `GET /api/search`, `POST /api/library`, `PATCH` e `DELETE /api/library/<id>`, `DELETE /api/queue`, `POST /api/prev`, `POST /api/toggle`, `POST /api/stop`, `POST /api/seek`, `POST /api/settings`, `GET /api/effects`, `POST /api/pedal_voz`, `GET` e `POST /api/devices`, `GET /api/boas-vindas` | sim | sim | 403 | 401 |
| `GET /api/tocadas`, `GET /api/musica`, `POST /api/aquece` (o grupo `OUT_OF_REPO`: só o módulo de fora do repo chama, do PC) | sim | 403 | 403 | 403 |
| `POST /api/shutdown`, `GET /api/lan`, `POST /api/effects/reload`, `POST /api/boas-vindas`, `POST /api/janela/foco`, `/api/metricas`, `/api/atualizacao/...`, `/api/pareamento/...`, e toda rota fora da tabela | sim | 403 | 403 | 403 |

`caps` = `{"papel": "pc" | "celular" | "remoto" | "publico", "rotas": ["POST /api/play", ...]}`: as rotas da API que
esse papel alcança, em ordem, no formato `"<MÉTODO> <rota>"`. Vem no `GET /api/state`, no 401 do pareamento (o do
`publico`) e como o primeiro evento do `GET /api/events`. O papel não muda numa conexão do SSE: o celular
desconectado e a sessão remota encerrada recebem o `desconectado` e a conexão fecha.

## Celular: pareamento

O PC (quem fala pelo `127.0.0.1`) usa tudo. Pela rede de casa, as páginas dos temas, a
galeria e o `GET /api/themes` abrem para qualquer um, mas o resto da API que o celular pode usar responde **401**
`{"ok": false, "parear": true, "desconectado": bool, "error": Mensagem, "caps": {...}}` até o celular parear;
`desconectado` diz que ele mandou uma chave que não vale mais (o PC desconectou); `caps` é o do pré-pareamento (ver
"Quem pode cada rota"); no `--mock`, vem também `"mock": true`. O que é só do PC responde 403, pareado ou não. O
`/api/events` também responde 401, e o `EventSource` não mostra o status: quando ele fecha de
vez, peça o `/api/state` para saber se é o 401.

- O código tem 6 números, vale 5 minutos e uma vez só, e morre com 5 tentativas erradas
  (`queimado`); aí só o `POST /api/pareamento/codigo` traz outro. O vencido e o usado dão
  lugar a outro sozinhos no próximo `GET /api/pareamento`.
- Pareado, o celular ganha a chave num cookie (`HttpOnly`, `SameSite=Strict`), que vale até o
  PC desconectar. Cada `GET /api/state` renova o prazo do cookie no navegador.
- `GET /api/pareamento`: `url` = o endereço do tema (`caminho`) na rede de casa (no
  `--mock --papel-local celular`, o do `127.0.0.1`), ou `null` sem rede (aí `codigo` e `qr`
  também vêm `null`); `codigo` = o de agora, ou `null` quando
  `queimado`; `vale_s` = quantos segundos ele ainda vale; `qr` = as linhas do QR do link
  `<url>?parear=<codigo>`, de cima para baixo, com `"1"` no módulo escuro e sem a margem
  (desenhe 4 módulos claros em volta); `celulares` = `[{"id", "nome", "desde", "visto"}]`,
  com o nome tirado do navegador ("Android · Chrome") e as datas em ISO local.
- O tema que abre com `?parear=<codigo>` no endereço manda o código sozinho se ainda não
  estiver pareado, e tira o código do endereço.

## Versão nova

O app consulta o manifesto das versões uns 30 s depois de abrir e de 6 em 6 horas
(`atualizacao.py`). Uma consulta que não chega ao manifesto (sem rede, tempo esgotado) se repete
em 2, 5, 15, 30 e 60 minutos, antes de voltar às 6 horas. Sem a janela própria (no navegador),
fechar a aba não fecha o Ritmelli: por isso, a página do PC que abre de novo (o `GET /api/events` vindo do `127.0.0.1`) também
consulta, se a última consulta tem mais de 5 minutos e nada está baixando. Só vale o manifesto assinado por uma das chaves do Ritmelli (o `CHAVES` do `atualizacao.py`), e só para uma versão
mais nova que a que está rodando. As versões ficam nas Releases do repo público
`ritmelli/ritmelli-releases`. Pelo código (`python server.py`), nada é consultado e `ativa`
vem `false`.

- `nova.tamanho` é o que vai ser baixado: a atualização parcial (`nova.parcial` = `true`), só
  com os arquivos que mudaram (uns 15 MB), quando o resto do que está instalado bate com o
  manifesto, ou o instalador completo (uns 160 MB). O app confere de novo, pelo hash, antes de
  baixar a parcial; se algo não bater, baixa o completo, e o `tamanho` muda.
- O `estado` anda assim: `parado` (com ou sem `nova`), `baixando`, `pronta` e, depois do
  `POST /api/atualizacao/instalar`, `instalando`. Um download que para no meio continua sozinho
  de onde parou, ainda em `baixando`; ele só volta para `parado`, com a Mensagem do motivo em `erro`, depois
  de algumas tentativas seguidas sem avançar, ou quando o arquivo não confere.
- O instalador roda em silêncio: o Windows pede a permissão, o instalador fecha o Ritmelli, troca
  a pasta dele e abre de novo, sem abrir outra aba. A página que estava aberta perde a conexão e
  deve recarregar quando ele voltar, porque o tema também pode ter mudado.
- Do celular, os quatro respondem 403: a versão nova se instala no PC.

**Automática** (`automatica: true`, o app instalado com a tarefa "Ritmelli Atualiza" do Windows,
`atualizador.py`): quem consulta, baixa e instala é a tarefa, como SYSTEM, sem o pedido de
permissão, no logon, de 4 em 4 horas e uns 30 s depois de o app abrir. Com o Ritmelli aberto, a
versão nova fica `pronta` e entra quando ele fecha. O app só mostra o estado da tarefa:
`consultar` e `baixar` pedem uma rodada a ela, e o `instalar` desliga o servidor para a tarefa
instalar, e o Ritmelli abre de novo sozinho. Sem nada para instalar agora, a tela pode só dizer
que a versão entra quando o Ritmelli fechar; o `erro` vem quando a tarefa parou (o instalador de
uma versão falhou duas vezes, por exemplo, e ela espera a próxima).

## O que todo tema cobre

1. Biblioteca como pads de disparo: um toque toca do zero; ação secundária para
   continuar de `last_pos`, renomear e apagar (apagar pede confirmação).
2. Tocando agora: título, estado, barra de progresso com seek (clique e arraste),
   tempo decorrido e total, tocar/pausar, parar, repetir. O tema `ritmelli` usa o transporte do
   Spotify: aleatório, anterior, tocar/pausar, próxima (apagada com a
   fila vazia) e repetir, sem botão de parar (o pausar cala tudo; o Esc ainda para); o
   título fica numa linha e desliza para o lado quando não cabe, como no YouTube Music.
3. Volumes: "no jogo" (`vol`), "no seu fone" (`mon_vol`), voz (`mic_vol`), cortar voz
   (`mic_mute`). Sem chave "fone ligado" (o volume do fone no zero faz o
   mesmo): com `monitor_on` falso, o volume do fone aparece em 0% e subir ele manda
   `monitor_on: true` junto.
4. Medidores ao vivo pelos `tick`: voz, arquivo e saída para o jogo.
5. Busca no YouTube (texto ou link colado): resultados com capa, título, canal e
   duração; "tocar agora" e "salvar"; marca o que já está na biblioteca. O tema `ritmelli` faz como
   o Spotify: tocar na linha toca, o ⊕ salva (anel enquanto baixa, ✓
   quando chega), o ... abre as opções (no celular sobem de baixo) e puxar a linha para a
   direita põe na fila; a fila (A seguir) aparece no toca-discos. Fila é opcional nos outros
   temas.
6. Downloads em andamento com progresso e erro legível.
7. Dispositivos: microfone (ou "padrão do Windows"), fone (padrão, um nome ou nenhum),
   mostrando os nomes ativos e se a música chega no microfone (`filtro`, `microfone`);
   lembrete de que o jogo e o Discord usam o mesmo microfone (no Discord, o perfil Estúdio).
8. Atalhos: espaço = tocar/pausar, 1 a 9 = pads, 0 = sem efeito de voz, Esc = parar
   (fora de campo de texto).
9. Servidor fora do ar, erro de busca, `error` no Estado: dizer o que houve e o que fazer.
10. Botão de desligar o soundboard, com confirmação.
11. Efeitos de voz (no estilo do Voicemod): a lista de `/api/effects` agrupada, com o nome (o texto do tema pelo id)
    (e a descrição onde couber; no celular só o nome) e o ativo marcado;
    trocar é um toque, e voltar para "Sem efeito" também (atalho 0, fora de campo de texto;
    tocar de novo no efeito ligado desliga, como no Voicemod);
    o efeito ativo aparece perto do medidor da voz (no celular, numa etiqueta na barra de
    baixo, que desliga com um toque), para o usuário saber de relance que está com a voz alterada;
    nada com cara de menu que só rola até a lista. "Ouvir minha voz" (`voice_monitor`) diz que funciona mesmo com a voz
    cortada, para testar sem ninguém ouvir, e não tem volume próprio: ligar manda
    `voice_mon_vol: 1` junto, porque em 100% o teste sai no mesmo nível que vai para o jogo.
12. Celular: no PC, um botão mostra o QR, o endereço e o código, e a lista dos celulares
    conectados, cada um com o botão de desconectar; no celular sem pareamento (o 401), uma tela
    por cima de tudo pede o código e explica onde achar.
13. Versão nova: no PC, com `atualizacao.nova`, um botão que mostra a versão, as notas (na língua da tela) e o
    tamanho, baixa com o progresso e instala; enquanto o instalador roda, a tela diz que o
    Ritmelli volta sozinho, e a página recarrega quando ele volta. Automática, a versão já chega
    baixada, e a tela diz que ela entra quando o Ritmelli fechar.

Cabe em qualquer tela: no computador (largura de 900 px ou mais) a
página nunca rola, nem de lado; o que não cabe rola por dentro de um painel (lista,
prateleira, grade). No celular e no tablet em pé, rolar na vertical vale, de lado nunca.
O gate é `python dev/fitcheck.py <url do tema>`, com tamanhos de 1024x600 a 2560x1300,
mais 390x844 e 768x1024; todos têm que dar OK. Foco de teclado visível;
`prefers-reduced-motion` respeitado.

Rolagem lisa no celular com música tocando (18/10): o que anda a cada quadro (agulha,
disco, barra de nível) gira ou desliza como camada própria (`transform` num elemento com
`will-change: transform`), nunca mudando atributo ou linha dentro de um `svg`, que redesenha
a página inteira; o que gira leva recorte no pai (`contain: paint`); o laço de
`requestAnimationFrame` para quando nada se mexe; e o tick só escreve no DOM o que mudou.
A medida é `python dev/perfcheck.py <url do tema> --play <id>`, que conta pinturas e
rasterizações por segundo e aponta o elemento que muda a cada quadro.

No celular, o que se usa com pressa no meio do jogo fica a um toque, sem rolar: tocar e pausar, cortar a voz e o volume no jogo. O tema `ritmelli` faz como os apps de
música: barra fixa embaixo com o disco no prato, cortar voz e tocar; tocar nela abre o
toca-discos por cima (o voltar do Android fecha), com os volumes logo abaixo do botão
grande; e os sons curtos (até 15 s, tocam por cima) ficam em botões no alto da prateleira.

No toque, barra de volume e da faixa só muda arrastando o cursor:
encostar em outro ponto da canaleta, sem querer ao rolar a página, não muda nada. Mouse e
teclado seguem como sempre (clicar na canaleta pula para lá).

Na primeira vez no PC (`GET /api/boas-vindas`), o tema `ritmelli` abre as boas-vindas: o passo a
passo do microfone e do fone, do mesmo microfone no jogo e nas chamadas (no Discord, o perfil
Estúdio), da primeira música e do celular. Fechar de
qualquer jeito manda o `POST /api/boas-vindas`. Nos outros temas, as boas-vindas são opcionais.

Os dados de uso e os erros (`GET /api/metricas`), no PC: com `"decidir"`, e com `"ligada"` e o `texto`
menor que o `texto_atual` (quem ligou num texto que não falava do que vai agora), todo tema mostra uma vez o
que vai (o texto do `PRIVACIDADE.md`, ou um resumo com o link da `politica`) e os botões Enviar e
Não enviar, que mandam o `POST /api/metricas`; fechar sem escolher pergunta de novo na próxima vez,
e nada sai antes (com `"ligada"` e o texto de antes, só o que esse texto dizia). Com `"ligada"` ou `"desligada"`, o tema mostra a situação e o botão de trocar
junto da escolha de microfone e fone. Ligar por esse botão com o `texto` menor que o `texto_atual` mostra antes o
aviso (o texto de agora), e o `POST` sai do Enviar dele; com o texto de agora, liga direto. A SignPath pede que a
pessoa possa desligar.

## Teste sem som

`python server.py --mock --port 88NN --no-browser` sobe tudo sem abrir
dispositivo de áudio (relógio falso, voz falsa no medidor, download fingido em 3 s), com
uma cópia da biblioteca numa pasta temporária, apagada quando o servidor fecha, ou em
`--data-dir <pasta>`. A pasta de quem usa o `--mock` recusa: o download fingido copia o disco
mais curto com outro nome, e lá viraria disco falso na prateleira. No `--mock`, os dados de uso ficam em `"fora"`;
com `--metricas-teste` (só junto do `--mock`), o aviso e a escolha funcionam, sem ler a escolha do instalador, e o que
sairia fica só na memória do servidor, sem rede nenhuma. Com `--papel-local celular` (só junto do `--mock`), o
`http://127.0.0.1:<porta>` faz o papel do celular da rede de casa: o 401 do pareamento com o `caps` do pré-pareamento,
o cookie do `POST /api/parear`, o `caps` do celular e a revogação fechando o SSE, como de outro aparelho; o
`http://localhost:<porta>`, com os cookies separados no navegador, segue o PC, e nele o `GET /api/pareamento` gera o
código com o `url` em `http://127.0.0.1:<porta>`. Print: `python dev/shot.py <url> <png> [--size
390x844] [--js "..."] [--tab N] [--reduced-motion] [--offline-ok]`, que também lista os erros
do console (`--tab` aperta Tab para o anel de foco aparecer; `--offline-ok` não conta a
reconexão do SSE com o servidor fora).
