# Os temas e a galeria (`themes/`, `gallery/`)

`themes/<slug>/`: as interfaces; `gallery/index.html` lista e compara lado a lado, com as letras e as texturas do
tema `ritmelli` e os textos dela em `gallery/i18n/`, como num tema. O app abre direto no tema `ritmelli`
(`pastas.PAGINA`), e a galeria fica em `/`. Na primeira
vez, o tema abre as boas-vindas por cima (ver o `API.md`). Até a 0.6.0 o tema se chamava `vitrola`: o servidor
leva todo endereço em `/t/vitrola/` para o mesmo caminho em `/t/ritmelli/`, com a mesma query (o `tema_de_antes`
do `server.py`), porque o celular pareado, o atalho na tela inicial e os favoritos abrem o de antes.

Todo arquivo de `/t/` sai com `Cache-Control: no-cache`, como a página (o `tema_sem_guardar` do `server.py`): o
navegador confere cada um com o servidor antes de usar o que guardou, e não usa uma letra ou uma textura de antes sem
conferir (o `dev/testa_mock.py` confere a página, o 304 dela e um `.js`). O `dev/testa_i18n.py` lê o `index.html` e
todos os `.js` e `.css` da pasta do tema, e cada bloco marcado (`/* NOME-INICIO */` ... `/* NOME-FIM */`, ou o
`/* nome:inicio */` de um gerador de `dev/`) mora num arquivo só, aberto e fechado nele, nessa ordem.

Código novo do tema vai num arquivo da pasta `themes/ritmelli/` (um `.js` ou `.css`), não no `index.html`.
Texto novo da interface entra por uma chave nas duas línguas (`i18n/` do tema, `gallery/i18n/` da galeria),
não escrito direto no HTML ou no JS.
Quem muda as boas-vindas roda o `dev/fitcheck.py` também com `--boas-vindas`, num `--mock` com `--data-dir`
novo e uma `library.json` só com `[]`. A janela própria (`janela.py`) se prova no app instalado, no job `testa`
do `monta.yml`.

O `index.html` do tema, por qualquer nome do mesmo arquivo (outra caixa, o nome 8.3, ponto ou espaço no fim, barra
dobrada, `::$DATA`, um link físico numa subpasta do tema), leva por 302 à página montada em `/t/<slug>/`, com a mesma
query: o `built_page_only` do `server.py`, só nos pedidos do static, compara numa thread o arquivo pedido com o
`index.html` do tema pelo `os.path.samefile`. Essa conferência e a rota do tema passam pela mesma porta, o
`theme_of_template` do `theme_page.py`: antes de qualquer leitura do disco, o caminho pedido tem de estar, pela
escrita, dentro de `themes/`, e um `/t///host/share/...` ou um slug com `%5C` nunca faz o PC abrir um compartilhamento
de rede. O `dev/testa_mock.py` confere os nomes e esses endereços.

A página do tema chega inteira numa resposta só. O `index.html` lista os arquivos da pasta do tema, cada um no lugar em
que roda: um `<script src="arquivo.js"></script>` por script e um `<link rel="stylesheet" href="arquivo.css">` por
folha, sem outros atributos. O servidor (o `build` do `theme_page.py`, que o `server.py` chama) troca cada um por um
`<script>` ou um `<style>` com o texto do arquivo, sem a marca de ordem de bytes (BOM) do começo, e a página não pede ao
servidor nenhum script nem nenhuma folha: não existe página com um arquivo faltando. A montagem lê o modelo inteiro por
uma gramática estrita, que só aceita texto sem `<`, a tag de abertura com atributos `nome="valor"` (ou com aspas
simples, ou sem aspas, sem retorno de carro nem NUL no valor) separados por espaço ASCII, a tag de fim `</nome>`, o
comentário `<!-- texto sem -- -->` e o `<!doctype html>`; o texto do `<script>`, do `<style>`, do `<title>` e do
`<iframe>` vai até o primeiro `</nome>` exato, em ASCII. Ela não imita o navegador: o que fica fora da gramática para a
montagem, e a página responde 500 com o modelo, a linha e a coluna (`themes/ritmelli/index.html:3:5`), o que ela achou e
a forma esperada, sem pasta do PC; o log do servidor diz o mesmo.

A gramática só aceita os elementos que o tema e a galeria usam hoje, numa lista para a página e noutra para dentro do
`<svg>` (o `HTML_ELEMENTS` e o `SVG_ELEMENTS` do `theme_page.py`). Qualquer outra tag, de abertura ou de fim, para a
montagem com a linha e a coluna e o nome do elemento. Acrescentar um elemento pede um PR com um caso no
`dev/theme_page_cases.py` que o `dev/theme_page_oracle.py` confere no Chrome. Por isso o tema não tem `<table>`,
`<frameset>`, `<math>`, `<template>`, `<base>`, `<plaintext>`, `<noscript>` nem `<textarea>`: em cada um, o navegador
move, descarta ou lê como texto o que a montagem leria.

- na página: `a`, `b`, `body`, `button`, `canvas`, `dialog`, `div`, `form`, `h1`, `h2`, `h3`, `head`, `header`, `html`,
  `iframe`, `input`, `kbd`, `label`, `li`, `link`, `main`, `meta`, `ol`, `output`, `p`, `script`, `section`, `select`,
  `small`, `span`, `style`, `svg`, `title`, `ul`;
- dentro do `<svg>`: `circle`, `g`, `mask`, `path`, `rect`, e o `</svg>` que o fecha.

Depois da gramática, a montagem ainda recusa, e o que escrever no lugar:

- o arquivo que falta, a pasta no lugar dele ou o caminho que sai da pasta da página (ou de `themes/`, com `/t/`): um
  arquivo que existe ali;
- o arquivo, ou o próprio `index.html`, que não é texto UTF-8 ou que não se deixa ler: salvá-lo em UTF-8, ou fechar o
  que o segura;
- a tag de arquivo com outro atributo, outra ordem, maiúsculas ou algo antes do fim: exatamente
  `<script src="arquivo.js"></script>` ou `<link rel="stylesheet" href="arquivo.css">`;
- um `&` no `src` ou no `href` de um `<script>`, de um `<style>` ou de um `<link>` que não abre uma referência nomeada
  inteira, e toda referência numérica: o nome sem `&`, ou com `&amp;`; e um `&` no `rel`, no `type` ou no `as`: o valor
  escrito por extenso;
- o script com `</script` ou `<!--` ou que começa com `#!`, e a folha com `</style`: o texto sem eles;
- a folha, de arquivo ou escrita na página, com `@import`, mesmo num comentário ou numa string (a folha se lê com os
  escapes de CSS decodificados): uma tag de arquivo por folha;
- a folha de outra pasta com um `url()` relativo, uma `\` ou um `image-set(`: só `url()` simples, com `https://`,
  `http://`, outro esquema, `data:`, `/` ou `#`, ou a folha na pasta da página;
- o `<link rel="modulepreload">`, o `<link rel="prefetch">` e o `<link rel="preload">` de um script ou de uma folha: a
  tag de arquivo;
- o `<script>` escrito na página com um `type` que não é `text/javascript` nem `application/json` (o `module` importa
  arquivos): um `<script>` sem `type` ou com um desses dois, ou a tag de arquivo;
- toda tag dentro de um `<select>`, onde um navegador pode descartar ou mover o que a montagem leria (o Chrome de hoje
  guarda ali o `<link>` e o `<style>`; o leitor antigo do `<select>`, que outros navegadores ainda usam, descarta o
  `<link>`): o `<select>` vazio, preenchido pelo código do tema;
- o `srcdoc`, que escreve uma página num atributo: tirá-lo, e pôr no próprio tema o que ele mostrava.

O `dev/testa_mock.py` confere cada caso da lista e cada forma fora da gramática (os casos moram no
`dev/theme_page_cases.py`). O `dev/theme_page_oracle.py`, que o `--tela` do `dev/testa_tudo.py` roda, abre num Chrome
sem tela, com os scripts bloqueados pelo cabeçalho `Content-Security-Policy: script-src 'none'` (o Chrome lê a página
como com o JavaScript ligado, e o `<noscript>` como texto), o tema, a galeria e cada caso que a montagem aceita, e
reprova quando os `<script>`, `<style>` e `<link>` do DOM, com o `src`, o `href`, o `rel` e o `type`, não são, na mesma
ordem, os que a montagem leu: uma forma que a gramática aceita e o navegador lê de outro jeito vira falha de teste. O
`dev/missing_script.py`, que o `--tela` também roda, lê a página e a galeria como o servidor as manda, nas duas línguas,
de um `--mock` como o PC e de outro como o celular, pela mesma gramática da montagem (o `strict` do `theme_page.py`), e
reprova com um `<script src>` ou um `<link rel="stylesheet">` nelas ou com um pedido de script ou de folha que o Chrome
faça ao servidor. O `dev/garden.py` conta as linhas de CSS e
JS escritas no próprio `index.html` e guarda o teto delas (o `theme_inline_lines` do `dev/garden.json`), que é 0: código
novo do tema vai num arquivo da pasta, e a contagem vai para o resumo do PR.

Os scripts são clássicos, sem `defer`: rodam na ordem da lista, e o que um declara no alto fica à vista dos de depois.
No `<head>`, logo depois dos textos que o servidor põe no `<!-- i18n -->`, vêm o `i18n.js` (o `I18N`, ver o
[i18n.md](i18n.md)), o `shared.js` (o estado da página, `S`, o da mesa de DJ, `MESA`, e os ajudantes de todos: o `$`, o
`el`, o `clamp`, o `reduz`, o `celular()`, o `toque()`, o `abrirMaleta()`, o `sombrear()`, o `dialogoAberto()`, o
`fmt()`, o `mudar()` e o `ligarChave()`) e o `gerado/pecas.js` (as constantes das peças de pixel, do `dev/pecas.py`).
No fim do `<body>`, com a marcação inteira já lida, vêm: o `transporte.js` (ver abaixo); o `page-texts.js`, que aplica
os textos da marcação e mostra a página (a classe `i18n-ok`), antes de qualquer outro ler ou medir a tela; o
`desk-scale.js` (a escala do palco da mesa: o `PALCO`, o `ajustarPalco()` e o `rectP()`); o `api.js` (o `api()` e o
texto das mensagens do servidor); o `notice.js` (o aviso rápido); o `covers.js` (as capas); o `tonearm.js` (o braço do
toca-discos); o `turntable.js` (o prato e a faixa, com os botões de tocar e a barra do tempo); o `dj-visor.js` (o visor
de DJ: a onda do disco que corre sob o ponto fixo do play); o `receiver.js` (o receptor: os volumes, o Cortar e o
Nivelar); o `voice-effects.js` (os efeitos de voz: o seletor no receptor e a gaveta de teclas); o `stage.js` (o palco
do celular e a barra de baixo); o `disc-page.js` (a página do disco no computador); o `dj-desk.js` (os dois decks da
mesa de DJ, que se revezam como num set, no computador largo); o `shelf.js` (a prateleira, com o arrastar de um disco
até um toca-discos na mesa); o `commands.js` (o `tocar()`, o `cmd()`, o `alternar()` e o `ajustar()`); o `search.js` (a
busca e os resultados); o `options.js` (as opções de um disco ou de um resultado); o `queue.js` (a fila, o A seguir); o
`dialogs.js` (o confirmar, o apagar, o renomear e o Sons rápidos de um disco); o `metrics.js` (a linha dos dados de uso
e erros no Microfone e fone e o aviso deles); o `devices.js` (o Microfone e fone e o desligar); o `phone.js` (o QR, o
código e os celulares conectados); o `update.js` (a versão nova); o `caps.js` (o que a página pode, pelo `caps` do
servidor); o `connection.js` (a conexão e o aviso de fora do ar); o `pairing.js` (o pareamento do celular); o
`welcome.js` (as boas-vindas); o `ui-events.js` (o ponto que chama os binders das partes, e os ouvintes da página
toda, como o teclado e o voltar); o `desk-buttons.js` (os botões da mesa de DJ); o `start.js` (a partida: monta a
página e, no `DOMContentLoaded`, carrega e conecta); e os desenhos de pixel da mesa: o `letra-placa.js` (a letra das
placas), o `prateleira.js` (o título e a contagem da plaqueta da prateleira), o `maleta-tit.js` (o título da placa da
maleta), o `mesa-topo.js` (a plaqueta e as teclas do topo em largura par), o `deck.js` (os toca-discos), o
`maleta-vazia.js` (o aviso de vazio do A seguir), o `mix.js` (o mixer) e o `pedal.js` (os pedais).

Cada ouvinte mora no arquivo da parte que ele serve: os da busca (o campo, o formulário, os botões dela, o toque fora
da gaveta da busca na mesa e os resultados) no `search.js`, os dos efeitos de voz (a gaveta, o Ouvir e o botão de
desligar o efeito da barra de baixo) no `voice-effects.js`, os do toca-discos no `turntable.js` e os do receptor no
`receiver.js`, os do palco e da barra de baixo no `stage.js`, o da página do disco no `disc-page.js`, os da
prateleira no `shelf.js`, o do botão do celular no `phone.js` e os do Microfone e fone, da dica de ouvir e do desligar
no `devices.js`, os das boas-vindas no `welcome.js`, o do pareamento no `pairing.js` e os da mesa no
`desk-buttons.js`. O arquivo da parte guarda os ouvintes em funções, uma por trecho seguido de registros (o
`bindSearch()`, o `bindSearchResults()`, o `bindVoiceEffects()`, o `bindTurntable()`, o `bindReceiver()`, o
`bindMiniBar()`, o `bindStageButtons()` e o `bindStageGestures()` do palco, o `bindDiscPage()`, o `bindShelfClick()` e
o `bindShelf()`, o `bindPhoneButton()`, o `bindDeviceButtons()` e o `bindDeskButtons()`). Quem as chama é o
`ui-events.js` (as da busca, dos efeitos, do toca-discos, do receptor, do palco, da página do disco, da prateleira, do
celular e dos dispositivos), o `queue.js` (o `bindSearchResults()`) e o `start.js` (o `bindDeskButtons()`, antes da
partida). Cada ouvinte entra na mesma ordem dos outros no mesmo alvo: o toque fora da busca para o evento depois de o
ouvinte do `queue.js` na `window` ver o toque.

Todo nome do alto de um script é declarado por um script só. O `dev/theme_scripts.py`, que o `--tela` do
`dev/testa_tudo.py` roda, abre a página num Chrome sem tela contra um `--mock` e pega cada script como o V8 o leu,
com o nome do arquivo dele achado pelo texto. Cada um vira o corpo de um gerador que é criado e não anda (as
declarações nascem e nada roda), e os nomes saem do escopo local dele. Um nome declarado em dois scripts (função,
`var`, `let`, `const` ou `class`) faz a guarda falhar. O leitor não vê dois nomes que só um script sem `'use strict'`
aceita (um `var arguments`, um `const yield`): os dois ficam no teste como falha conhecida da issue #239. Ele confere
também que cada ouvinte das partes é do arquivo dela, que a página só passa a vigiar a própria visibilidade no
`DOMContentLoaded`, com o `carregar()` já declarado (uma aba que aparece durante a leitura da página não conecta antes
da partida), e que o `queue.js` vê o toque que fecha a busca na mesa. O `dev/theme_rebuild.py` mostra à parte os
blocos que mudaram de lugar com outra indentação (os que entraram numa dessas funções).

Para provar que um PR só mudou código de lugar, o `dev/theme_rebuild.py <base>` monta a
página de novo nos dois commits (cada `<script src>`, `<link>` e `<!-- inline-script: -->` trocado pelo texto do
arquivo, sem as marcas, com os outros atributos da tag numa linha e cada `'use strict'` como `[strict]`) e sai 0 só com
as duas páginas iguais, linha a linha; diferentes, ela separa os blocos que só mudaram de lugar das linhas novas ou que
sumiram (um arquivo novo traz o próprio `[strict]`). O `dev/theme_listeners.py <base>` prova o outro lado: abre o tema
dos dois commits num Chrome sem tela, contra um `--mock` de cada, no tamanho do PC (a mesa) e no de um celular, e
compara três tabelas. A primeira tem os ouvintes ligados no fim da carga, na ordem em que entraram (o
`getEventListeners` do DevTools), com as opções e o texto de cada função: os de cada nó, do `document`, da `window` e do
`navigator.connection`, os de cada `MediaQueryList` que a página criou e que teve um ouvinte ou uma chamada (pela
consulta, numeradas entre as da mesma consulta na ordem em que nasceram; o `onchange` e o `addListener` entram) e os
dos outros alvos em que a página pôs um ouvinte, pelo tipo. A segunda tem cada chamada de `addEventListener`,
`removeEventListener`, `addListener` e `removeListener`, e cada `onchange` posto numa `MediaQueryList` ou no
`navigator.connection`, desde o começo da página, por alvo e evento, na ordem (um nó pelo caminho da primeira chamada,
numerado quando outro nó já tinha o mesmo): um ouvinte posto e tirado antes da leitura aparece nela. A terceira tem
essas `MediaQueryList` na ordem em que nasceram, entre consultas, que é a ordem em que o navegador avisa de uma
mudança. Sai 0 só com as tabelas iguais. O
arquivo em que um ouvinte mora não entra na comparação: mudar um ouvinte de arquivo, ou para dentro de uma função,
mantém as tabelas. O `dev/test_theme_listeners.py`, que o `--tela` roda, confere a leitura numa página própria.

Toda conversa do tema com o servidor passa pelo `transporte.js` (os pedidos da API, que o `api()` do `api.js` chama,
e o fluxo de eventos do SSE): o resto do tema não sabe como ela chega, e o `fetch`, o `EventSource` e o
`location.hostname` só aparecem nele. O que o tema mostra a cada um vem do `caps` que o servidor manda (no `/api/state`,
no 401 do pareamento e no começo do SSE; ver o `API.md`), e não do endereço da página: os controles do PC (o botão
Celular, a versão nova, os dados de uso, as boas-vindas) só aparecem depois de o `caps` dizer que a rota deles abre. O
401 do pareamento põe o `caps` de antes de parear; pareado, o `/api/state` traz o do celular; o celular desconectado no
PC volta ao de antes. O endereço só fica com o texto do aviso de fora do ar da página que nunca recebeu um `caps` (a
guardada, que o navegador reabre com o Ritmelli fechado). Quando a conexão cai, a lâmpada pisca e, passados 2,5 s com
a página na tela, o `mostrarFora()` do `connection.js` abre o aviso de fora do ar com o texto do papel: no PC, que o
Ritmelli parou de responder e onde fica o log; no celular, o caminho até o computador, com o que o navegador conta da
conexão. O `dev/missing_script.py` derruba o `--mock` com a página conectada, como o PC e como um celular pareado, nas
duas línguas, e confere o título e o texto do aviso. Para ver o papel do celular sem outro aparelho, o
`--mock --papel-local celular` (ver o `API.md`).

Todo o CSS do tema mora em arquivos da pasta, um bloco marcado por arquivo, e a lista de `<link>` no alto do
`index.html` é a ordem da cascata: o `base.css` (as letras, as cores, o reset e a regra que esconde a página até os
textos estarem no lugar) primeiro, as partes da página (`buttons.css`, `top-bar.css`, `phone.css`, ...), a pele por
cima delas (`skin-vars.css`, as folhas geradas, `skin-top.css`, `skin-case.css`, ...), os arranjos do computador e da
mesa de DJ (`desktop-library.css`, `dj-desk.css`, ...) e o `reduced-motion.css` perto do fim, antes do `deck.css`, do
`mix.css` e do `pedal.css` da mesa. Como a folha chega dentro da página, os endereços relativos dela (`url(fonts/...)`)
saem do endereço da página, que é a pasta do tema; por isso a folha de `gerado/` só usa `url(data:...)`. O bloco que
vale só numa largura leva o `@media` em volta no arquivo. O que um gerador de `dev/` desenha mora em `gerado/` (o
`gerado/molduras.css`, por exemplo): o gerador grava o arquivo inteiro e não mexe no `index.html`, e o que se muda à mão
ali some na próxima vez que ele roda.
