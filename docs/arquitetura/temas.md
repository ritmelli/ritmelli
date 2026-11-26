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

A página do tema chega inteira numa resposta só. O `index.html` lista os arquivos da pasta do tema, cada um no lugar em
que roda: um `<script src="arquivo.js"></script>` por script e um `<link rel="stylesheet" href="arquivo.css">` por
folha, sem outros atributos. O servidor (o `build` do `theme_page.py`, que o `server.py` chama) troca cada um por um `<script>` ou um `<style>`
com o texto do arquivo, e a página não pede ao servidor nenhum script nem nenhuma folha: não existe página com um
arquivo faltando. O arquivo que falta ou que sai da pasta, o que traz o que fecharia o elemento em volta dele (`</script`
ou `<!--` num script, `</style` ou `@import` numa folha), a folha de outra pasta com um `url()` relativo (que a página
leria a partir da pasta dela) e a tag de arquivo escrita de outro jeito param a montagem no servidor, que responde 500
e põe no log o nome do arquivo. A folha se lê com os escapes de CSS decodificados, também nos comentários e nas
strings, e o `@import` ou o `url()` relativo que aparece em qualquer lugar dela, mesmo só num comentário ou numa
string, para a montagem: o que a montagem não distingue com certeza de uma busca, ela recusa; o `dev/testa_mock.py` confere cada um desses casos. O
`dev/missing_script.py`, que o `--tela` do `dev/testa_tudo.py` roda, lê a página e a galeria como o servidor as manda,
nas duas línguas, de um `--mock` como o PC e de outro como o celular, e reprova com um `<script src>` ou um
`<link rel="stylesheet">` nelas. O `dev/garden.py` conta as linhas de CSS e JS escritas no próprio `index.html` e
guarda o teto delas (o `theme_inline_lines` do `dev/garden.json`), que é 0: código novo do tema vai num arquivo da
pasta, e a contagem vai para o resumo do PR.

Os scripts são clássicos, sem `defer`: rodam na ordem da lista, e o que um declara no alto fica à vista dos de depois.
No `<head>`, logo depois dos textos que o servidor põe no `<!-- i18n -->`, vêm o `i18n.js` (o `I18N`, ver o
[i18n.md](i18n.md)), o `shared.js` (o estado da página, `S`, o da mesa de DJ, `MESA`, e os ajudantes de todos: o `$`, o
`el`, o `clamp`, o `reduz`, o `celular()`, o `toque()`, o `abrirMaleta()`, o `sombrear()`, o `dialogoAberto()`, o
`fmt()`, o `mudar()` e o `ligarChave()`) e o `gerado/pecas.js` (as constantes das peças de pixel, do `dev/pecas.py`).
No fim do `<body>`, com a marcação inteira já lida, vêm: o `transporte.js` (ver abaixo); o `page-texts.js`, que aplica os
textos da marcação e mostra a página (a classe `i18n-ok`), antes de qualquer outro ler ou medir a tela; o
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
duas línguas, e confere o título e o texto do aviso. Para ver o papel do celular sem outro aparelho, o `--mock
--papel-local celular` (ver o `API.md`).

Todo o CSS do tema mora em arquivos da pasta, um bloco marcado por arquivo, e a lista de `<link>` no alto do
`index.html` é a ordem da cascata: o `base.css` (as letras, as cores, o reset e a regra que esconde a página até os
textos estarem no lugar) primeiro, as partes da página (`buttons.css`, `top-bar.css`, `phone.css`, ...), a pele por
cima delas (`skin-vars.css`, as folhas geradas, `skin-top.css`, `skin-case.css`, ...), os arranjos do computador e da
mesa de DJ (`desktop-library.css`, `dj-desk.css`, ...) e o `reduced-motion.css` perto do fim, antes do `deck.css`, do
`mix.css` e do `pedal.css` da mesa. Como a folha chega dentro da página, os endereços relativos dela (`url(fonts/...)`)
saem do endereço da página, que é a pasta do tema; por isso a folha de `gerado/` só usa `url(data:...)`. O bloco que vale só numa largura leva o `@media` em volta no
arquivo. O que um gerador de `dev/` desenha mora em `gerado/` (o `gerado/molduras.css`, por exemplo): o gerador grava o
arquivo inteiro e não mexe no `index.html`, e o que se muda à mão ali some na próxima vez que ele roda.
