# Soundboard do VRChat: contrato da API e do tema

O `server.py` toca áudio no microfone do jogo: arquivo + voz do usuário vão para o
CABLE Input (o VRChat usa o CABLE Output como microfone) e só o arquivo vai para o fone,
para o usuário ouvir o som sem ouvir a própria voz. Enquanto o servidor roda, a voz passa
sempre, com ou sem arquivo tocando. Toda interface é um tema em `themes/<slug>/` que fala
só com esta API.

## Tema

- `themes/<slug>/index.html`, autossuficiente: HTML + CSS + JS puro, sem build. Arquivo
  extra (fonte local, svg, imagem) mora na mesma pasta e se referencia por caminho
  relativo (`./x.svg`), servido em `/t/<slug>/x.svg`.
- `themes/<slug>/meta.json`: `{"name": "...", "direction": "...", "blurb": "uma frase"}`.
- Fonte externa só do Google Fonts; script externo nenhum.
- API sempre por caminho absoluto (`/api/...`), mesma origem. Escrita é `fetch` com
  `method` e, quando tem corpo, `Content-Type: application/json`.
- Texto da interface em português do Brasil, com acentuação completa e sem travessão.
- O tema abre também no celular, pela rede de casa (`http://<ip do PC>:8799/`): nada de
  endereço `127.0.0.1` escrito no tema e nada que dependa de mouse. Pela rede, a API só
  responde ao celular pareado (ver "Celular: pareamento").

## Estado ao vivo: `GET /api/events` (SSE)

Use `new EventSource('/api/events')`. Eventos:

| evento | quando | `data` |
|---|---|---|
| `state` | ao conectar e a cada mudança | objeto Estado (abaixo) |
| `library` | ao conectar e a cada mudança | lista de Item |
| `jobs` | ao conectar e a cada mudança | lista de Job (o terminado some depois de 20 s) |
| `tick` | 15 vezes por segundo | `{"pos": s, "levels": {"mic": r, "track": r, "out": r}}` |
| `desconectado` | o PC desconectou este celular (logo depois a conexão fecha) | `{}` |

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
 "monitor_on": true, "loop": false,
 "effect": "nenhum", "voice_monitor": false, "voice_mon_vol": 0.8,
 "por_cima": [{"id": "...", "title": "..."}],
 "devices": {"mic": "default", "out": "CABLE Input", "monitor": "default"},
 "active_devices": {"mic": "Microfone (Virtual Desktop Audio)", "out": "CABLE Input (VB-Audio Virtual Cable)", "monitor": "Alto-falantes (Virtual Desktop Audio)"},
 "error": null ou "texto",
 "queue": [Entrada], "shuffle": false, "auto": false, "history": 3,
 "versao": "0.1.0"}
```
- `versao` = a versão do servidor (`versao.py`), para mostrar na tela.
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
- `monitor_on` = o arquivo toca também no fone do usuário.
- `loop` = repete o disco do prato sem parar. Vale só para esse disco: outro entrando (prateleira,
  Próxima, Anterior, fila) ou o disco saindo do prato (`POST /api/stop`) desliga, e o `loop` do
  `POST /api/play` manda sobre isso. O mesmo disco tocado de novo, a troca do stream para o arquivo
  e o som por cima não desligam. Ligado com o prato vazio, vale para o disco que entrar.
- `effect` = efeito de voz ativo (id de `/api/effects`); o servidor sempre sobe em `nenhum`.
  Aceita também `locutor-caricato`, o modo caricato do "Locutor de rádio FM", que fica fora
  de `/api/effects` para não virar outro efeito na lista: o tema que o oferece faz dele um
  modo do Locutor, e com ele ligado (escolhido de outro aparelho) marca o Locutor.
- `por_cima` = sons curtos tocando agora junto da música (ver `POST /api/play`); não mexem
  em `track`, `status` nem na barra, e o pausar e o parar calam todos.
- `voice_monitor` = a voz, já com o efeito, toca também no fone do usuário; vale mesmo com
  `mic_mute`, então serve para testar um efeito sem ninguém no jogo ouvir.
- `voice_mon_vol` = volume da própria voz no fone, 0 a 1.
- `ended` = o arquivo chegou ao fim; `resume` recomeça do zero. Falha de leitura também
  termina em `ended`, com o texto em `error`: mostre `error` sempre que vier preenchido.
- `error` já vem como frase pronta em português, com o que fazer; mostre como veio.
- Fone em "nenhum" (`active_devices.monitor` vazio) torna `monitor_on` sem efeito.

**Item** (biblioteca):
```json
{"id": "w6kKVs-h9Ns", "title": "...", "file": "w6kKVs-h9Ns.webm", "duration": 36.7,
 "youtube_id": "w6kKVs-h9Ns" ou null, "thumb": "https://i.ytimg.com/vi/<id>/mqdefault.jpg" ou null,
 "channel": "..." ou null, "added": "2026-10-17T13:34:56", "last_pos": 807, "plays": 3, "rapido": true}
```
`rapido` = posto nos Sons rápidos pela mão (ausente = não); no celular ele toca por cima
da música com `por_cima`, como os de até 15 s, e o motor toca ele inteiro, até 2 min.
`last_pos` = onde parou da última vez (segundos); vale oferecer "continuar de mm:ss"
quando for maior que uns 5 s. `plays` = quantas vezes o disco foi escutado: conta quando
toca de fato 30 s (ou 80% dele, se for mais curto) desde que entrou no prato; ausente = 0
(item que nunca tocou, ou servidor antigo). A vitrola põe as mais escutadas primeiro.

**Job** (download):
```json
{"id": "ce14abe3", "kind": "download", "label": "texto ou título", "status": "running|done|error",
 "progress": 0.42, "error": null ou "texto", "item_id": null ou "id", "play": true,
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

## Comandos

Todos respondem `{"ok": true, ...}` ou `{"ok": false, "error": "texto"}` com status 4xx/5xx.

| comando | corpo | efeito |
|---|---|---|
| `POST /api/play` | `{"id": "<item>", "start": 12.5?, "resume": true?, "loop": bool?, "por_cima": bool?}` | toca o item (do zero, de `start`, ou de `last_pos` com `resume`); item de até 15 s sem `start` nem `resume` toca **por cima** da música (buzina, bordão: não troca a faixa, vários juntos, até 8) e responde `{"ok": true, "por_cima": true}`; `por_cima` força um ou outro |
| `POST /api/toggle` | - | pausa ou continua; pausar cala também os sons por cima |
| `POST /api/pause` / `POST /api/resume` | - | idem, explícito |
| `POST /api/stop` | - | descarrega o arquivo, desliga o `loop` e cala os sons por cima (a voz segue); o disco entra no `history` |
| `POST /api/next` | - | Próxima: tira o primeiro da `queue` e toca; fila vazia = 409 |
| `POST /api/prev` | - | Anterior do Spotify: com mais de 3 s de disco (ou nada antes dele), volta ao começo (`{"did": "inicio"}`); senão toca o último do `history`, e o disco do prato vai para o topo da `queue` (`{"did": "anterior"}`); nada no prato nem antes = 409 |
| `POST /api/seek` | `{"t": 90}` | pula para t segundos |
| `POST /api/settings` | qualquer de `vol`, `mon_vol`, `mic_vol`, `mic_mute`, `monitor_on`, `loop`, `shuffle`, `auto`, `effect`, `voice_monitor`, `voice_mon_vol` | ajusta ao vivo; salva `vol`, `mon_vol`, `monitor_on`, `voice_mon_vol` e `auto` (`mic_vol` vai direto para o Windows); `mic_mute`, `loop`, `shuffle`, `voice_monitor` e o efeito voltam ao padrão quando o servidor sobe |
| `GET /api/effects` | - | `[{"id","nome","grupo","descricao","latencia_ms"}]`, na ordem de exibição; `grupo` vazio é o "Sem efeito"; os grupos hoje são "Rádio e alto-falante", "Ambiente" e "Personagem" |
| `GET /api/search?q=<texto ou link>&n=8&start=0` | - | busca no YouTube (link ou id colado devolve o próprio vídeo): `[{"youtube_id","title","duration","channel","thumb","in_library","id"}]` (leva 2 a 6 s); `n` até 20 por vez, `start` pula os primeiros (o "carregar mais": o servidor pede `start+n` ao YouTube e devolve do `start` em diante, até 200; link com `start` devolve vazio) |
| `POST /api/library` | `{"youtube_id": "..."}` ou `{"url": "..."}` ou `{"query": "..."}`, mais `"play": bool`, `"title"?`, `"channel"?`, `"thumb"?`, `"duration"?` | baixa para a biblioteca (Job); com `play`, toca na hora pelo stream do YouTube enquanto baixa e responde `{"job": ..., "streaming": true}` (título, canal, capa e duração do corpo aparecem no prato desde o primeiro instante); se já existe, responde `{"item": ...}` e toca na hora; o mesmo vídeo já baixando não baixa de novo |
| `POST /api/queue` | `{"id": "<disco>"}` ou `{"youtube_id": "...", "title"?, "channel"?, "thumb"?, "duration"?}` ou `{"url": "..."}`, mais `"next": bool?` | põe na fila (no fim, ou logo a seguir com `next`); vídeo fora da prateleira já começa a baixar; com nada no prato, toca na hora em vez de entrar na fila; responde `{"entry": Entrada, "job": Job ou null, "playing": bool}` |
| `DELETE /api/queue/<qid>` | - | tira da fila (parecida do Automático tirada não volta nesta sessão) |
| `DELETE /api/queue` | - | esvazia a fila (as parecidas que estavam nela não voltam; com o Automático ligado, entram outras) |
| `POST /api/queue/move` | `{"qid": "...", "to": 0}` | muda a entrada de lugar (`to` a partir de 0) |
| `POST /api/queue/play` | `{"qid": "..."}` | tira da fila e toca agora |
| `PATCH /api/library/<id>` | `{"title": "..."}` e/ou `{"rapido": bool}` | renomeia; `rapido` põe ou tira o disco dos Sons rápidos do celular (os de até 15 s já estão lá sem isso) |
| `DELETE /api/library/<id>` | - | apaga da biblioteca (e o arquivo); o disco no prato segue tocando e o arquivo dele sai quando o motor largar |
| `GET /api/devices` | - | `{"inputs": [...], "outputs": [...], "default_input", "default_output", "current", "active"}` |
| `POST /api/devices` | `{"mic"?: nome ou "default", "monitor"?: nome, "default" ou "", "out"?: nome}` | troca dispositivo (reabre o áudio) |
| `GET /api/boas-vindas` | - | `{"mostrar": bool}`: verdadeiro na primeira vez no PC (prateleira vazia e as boas-vindas nunca fechadas); pelo celular, sempre falso |
| `POST /api/boas-vindas` | - | só no PC: as boas-vindas foram vistas e não voltam (fica no `config.json`) |
| `GET /api/themes` | - | `[{"slug","url","name","direction","blurb"}]` |
| `POST /api/shutdown` | - | desliga o servidor (a voz para de passar pelo cabo) |
| `GET /api/lan` | - | `{"url": endereço do PC na rede de casa, ou null}` |
| `POST /api/parear` | `{"codigo": "482913"}` (espaço vale) | o celular manda o código que o PC mostra; certo, responde com o cookie da chave; errado, 403 com o motivo |
| `GET /api/pareamento?caminho=/t/<slug>/` | - | só no PC: `{"url", "codigo", "vale_s", "queimado", "qr", "celulares"}` (ver "Celular: pareamento") |
| `POST /api/pareamento/codigo` | - | só no PC: troca o código (e traz um de volta depois de queimado) |
| `DELETE /api/pareamento/<id>` | - | só no PC: desconecta o celular, que volta a precisar do código |

## Celular: pareamento

O PC (quem fala pelo `127.0.0.1`) usa tudo. Pela rede de casa, as páginas dos temas, a
galeria e o `GET /api/themes` abrem para qualquer um, mas o resto da API responde **401**
`{"ok": false, "parear": true, "desconectado": bool, "error": "..."}` até o celular parear;
`desconectado` diz que ele mandou uma chave que não vale mais (o PC desconectou). O
`/api/events` também responde 401, e o `EventSource` não mostra o status: quando ele fecha de
vez, peça o `/api/state` para saber se é o 401.

- O código tem 6 números, vale 5 minutos e uma vez só, e morre com 5 tentativas erradas
  (`queimado`); aí só o `POST /api/pareamento/codigo` traz outro. O vencido e o usado dão
  lugar a outro sozinhos no próximo `GET /api/pareamento`.
- Pareado, o celular ganha a chave num cookie (`HttpOnly`, `SameSite=Strict`), que vale até o
  PC desconectar. Cada `GET /api/state` renova o prazo do cookie no navegador.
- `GET /api/pareamento`: `url` = o endereço do tema (`caminho`) na rede de casa, ou `null`
  sem rede (aí `codigo` e `qr` também vêm `null`); `codigo` = o de agora, ou `null` quando
  `queimado`; `vale_s` = quantos segundos ele ainda vale; `qr` = as linhas do QR do link
  `<url>?parear=<codigo>`, de cima para baixo, com `"1"` no módulo escuro e sem a margem
  (desenhe 4 módulos claros em volta); `celulares` = `[{"id", "nome", "desde", "visto"}]`,
  com o nome tirado do navegador ("Android · Chrome") e as datas em ISO local.
- O tema que abre com `?parear=<codigo>` no endereço manda o código sozinho se ainda não
  estiver pareado, e tira o código do endereço.

## O que todo tema cobre

1. Biblioteca como pads de disparo: um toque toca do zero; ação secundária para
   continuar de `last_pos`, renomear e apagar (apagar pede confirmação).
2. Tocando agora: título, estado, barra de progresso com seek (clique e arraste),
   tempo decorrido e total, tocar/pausar, parar, repetir. A vitrola usa o transporte do
   Spotify: aleatório, anterior, tocar/pausar, próxima (apagada com a
   fila vazia) e repetir, sem botão de parar (o pausar cala tudo; o Esc ainda para); o
   título fica numa linha e desliza para o lado quando não cabe, como no YouTube Music.
3. Volumes: "no jogo" (`vol`), "no seu fone" (`mon_vol`), voz (`mic_vol`), cortar voz
   (`mic_mute`). Sem chave "fone ligado" (o volume do fone no zero faz o
   mesmo): com `monitor_on` falso, o volume do fone aparece em 0% e subir ele manda
   `monitor_on: true` junto.
4. Medidores ao vivo pelos `tick`: voz, arquivo e saída para o jogo.
5. Busca no YouTube (texto ou link colado): resultados com capa, título, canal e
   duração; "tocar agora" e "salvar"; marca o que já está na biblioteca. A vitrola faz como
   o Spotify: tocar na linha toca, o ⊕ salva (anel enquanto baixa, ✓
   quando chega), o ... abre as opções (no celular sobem de baixo) e puxar a linha para a
   direita põe na fila; a fila (A seguir) aparece no toca-discos. Fila é opcional nos outros
   temas.
6. Downloads em andamento com progresso e erro legível.
7. Dispositivos: microfone (ou "padrão do Windows"), fone (padrão, um nome ou nenhum),
   mostrando os nomes ativos; lembrete de que no VRChat o microfone precisa ser
   "CABLE Output (VB-Audio Virtual Cable)".
8. Atalhos: espaço = tocar/pausar, 1 a 9 = pads, 0 = sem efeito de voz, Esc = parar
   (fora de campo de texto).
9. Servidor fora do ar, erro de busca, `error` no Estado: dizer o que houve e o que fazer.
10. Botão de desligar o soundboard, com confirmação.
11. Efeitos de voz (no estilo do Voicemod): a lista de `/api/effects` agrupada, com o nome
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

No celular, o que se usa com pressa no meio do jogo fica a um toque, sem rolar: tocar e pausar, cortar a voz e o volume no jogo. A vitrola faz como os apps de
música: barra fixa embaixo com o disco no prato, cortar voz e tocar; tocar nela abre o
toca-discos por cima (o voltar do Android fecha), com os volumes logo abaixo do botão
grande; e os sons curtos (até 15 s, tocam por cima) ficam em botões no alto da prateleira.

No toque, barra de volume e da faixa só muda arrastando o cursor:
encostar em outro ponto da canaleta, sem querer ao rolar a página, não muda nada. Mouse e
teclado seguem como sempre (clicar na canaleta pula para lá).

Na primeira vez no PC (`GET /api/boas-vindas`), a vitrola abre as boas-vindas: o passo a
passo do cabo (o VB-Cable, conferido pelo `GET /api/devices`, com a página oficial da VB-Audio
quando falta), do microfone e do fone, do microfone no VRChat, da busca e do celular. Fechar de
qualquer jeito manda o `POST /api/boas-vindas`. Nos outros temas, as boas-vindas são opcionais.

## Teste sem som

`python server.py --mock --port 88NN --data-dir <pasta> --no-browser` sobe tudo sem abrir
dispositivo de áudio (relógio falso, voz falsa no medidor, download fingido em 3 s), com
uma cópia da biblioteca em `<pasta>`. Print: `python dev/shot.py <url> <png> [--size
390x844] [--js "..."] [--tab N] [--reduced-motion] [--offline-ok]`, que também lista os erros
do console (`--tab` aperta Tab para o anel de foco aparecer; `--offline-ok` não conta a
reconexão do SSE com o servidor fora).
