# Os temas e a galeria (`themes/`, `gallery/`)

`themes/<slug>/`: as interfaces; `gallery/index.html` lista e compara lado a lado, com as letras e as texturas do
tema `ritmelli` e os textos dela em `gallery/i18n/`, como num tema. O app abre direto no tema `ritmelli`
(`pastas.PAGINA`), e a galeria fica em `/`. Na primeira
vez, o tema abre as boas-vindas por cima (ver o `API.md`). Até a 0.6.0 o tema se chamava `vitrola`: o servidor
leva todo endereço em `/t/vitrola/` para o mesmo caminho em `/t/ritmelli/`, com a mesma query (o `tema_de_antes`
do `server.py`), porque o celular pareado, o atalho na tela inicial e os favoritos abrem o de antes.

Todo arquivo de `/t/` sai com `Cache-Control: no-cache`, como a página (o `tema_sem_guardar` do `server.py`): o
navegador confere cada um com o servidor antes de usar o que guardou, e não usa um `.js` ou um `.css` de antes sem
conferir (o `dev/testa_mock.py` confere a página, o 304 dela, um `.js`, um `.css`, uma fonte e uma imagem). O
`dev/testa_i18n.py` lê o `index.html` e todos os `.js` e `.css` da pasta do tema: cada bloco marcado
(`/* NOME-INICIO */` ... `/* NOME-FIM */`, ou o `/* nome:inicio */` de um gerador de `dev/`) mora num arquivo só,
aberto e fechado nele, nessa ordem, e cada `.js` e `.css` fora do `gerado/` tem exatamente um bloco.

Código novo do tema vai num arquivo da pasta `themes/ritmelli/` (um `.js` ou `.css`), não no `index.html`.
Texto novo da interface entra por uma chave nas duas línguas (`i18n/` do tema, `gallery/i18n/` da galeria),
não escrito direto no HTML ou no JS.
Quem muda as boas-vindas roda o `dev/fitcheck.py` também com `--boas-vindas`, num `--mock` com `--data-dir`
novo e uma `library.json` só com `[]`. A janela própria (`janela.py`) se prova no app instalado, no job `testa`
do `monta.yml`.
O código do tema sai aos poucos do `index.html` para arquivos `.js` na pasta do tema, um bloco marcado por arquivo, que
o `index.html` carrega por um `<script src>` no lugar em que o bloco estava, sem `defer`: os scripts rodam na mesma
ordem, e o que um deles declara no alto continua à vista dos de depois. O primeiro é o `shared.js`, carregado no
`<head>`: o estado da página (`S`), o da mesa de DJ (`MESA`) e os ajudantes de todos (o `$`, o `el`, o `clamp`, o
`reduz`, o `celular()`, o `toque()`, o `abrirMaleta()`, o `sombrear()` e o `dialogoAberto()`). Já saíram também: o `deck.js` (os toca-discos
da mesa), o `mix.js` (o mixer da mesa), o `pedal.js` (os pedais da mesa), o `maleta-vazia.js` (o aviso de vazio do A
seguir), o `letra-placa.js` (a letra de pixel das placas da mesa), o `prateleira.js` (o título e a contagem da plaqueta
da prateleira), o `maleta-tit.js` (o título da placa da maleta) e o `mesa-topo.js` (a plaqueta e as teclas do topo da
mesa em largura par). O `dj-visor.js` (o visor de DJ: a onda do disco que corre sob o ponto fixo do play), o
`voice-effects.js` (os efeitos de voz: o seletor no receptor e a gaveta de teclas), o `dj-desk.js` (os dois decks da
mesa de DJ, que se revezam como num set, no computador largo), o `search.js` (a busca e os resultados), o `queue.js` (a
fila, o A seguir) e o `ui-events.js` (o ponto que chama os binders das partes, e os ouvintes da página toda, como o
teclado e o voltar) saíram do script principal da página, que é estrito: o arquivo tirado
dele começa com `'use strict'`, como o script inline que segue depois do `<script src>` dele. Depois do `transporte.js`
vêm o `desk-scale.js` (a escala do palco da mesa: o `PALCO`, o `ajustarPalco()` e o `rectP()`), o `api.js` (o `api()`
e o texto das mensagens do servidor), o `notice.js` (o aviso rápido), o `covers.js` (as capas), o `tonearm.js` (o braço
do toca-discos), o `turntable.js` (o prato e a faixa, com os botões de tocar e a barra do tempo) e, depois do
`dj-visor.js`, o `receiver.js` (o receptor: os volumes, o Cortar e o Nivelar). Depois do `voice-effects.js` vêm o
`stage.js` (o palco do celular e a barra de baixo) e o `disc-page.js` (a página do disco no computador), e depois do
`dj-desk.js`, o `shelf.js` (a prateleira, com o arrastar de um disco até um toca-discos na mesa) e o `commands.js` (o
`tocar()`, o `cmd()`, o `alternar()` e o `ajustar()`). Depois do `search.js` vem o `options.js` (as opções de um
disco ou de um resultado), e depois do `queue.js`, o `dialogs.js` (o confirmar, o apagar, o renomear e o Sons rápidos
de um disco), o `metrics.js` (a linha dos dados de uso e erros no Microfone e fone e o aviso deles), o `devices.js` (o
Microfone e fone e o desligar), o `phone.js` (o QR, o código e os celulares conectados), o `update.js` (a versão
nova), o `caps.js` (o que a página pode, pelo caps do servidor), o `connection.js` (a conexão e o aviso de fora do ar),
o `pairing.js` (o pareamento do celular) e o `welcome.js` (as boas-vindas). Depois do `ui-events.js` vêm o
`desk-buttons.js` (os botões da mesa de DJ) e o `start.js` (a partida: monta a página e, no `DOMContentLoaded`,
carrega e conecta), que o servidor põe inline na página (o `inline-script`): eles rodam logo depois do `ui-events.js`,
sem esperar a rede, como o script em que moravam, e o pareamento aceito no meio da carga já acha o `carregar()`. Os únicos scripts escritos no próprio `index.html` são o `I18N` do `<head>` e a
linha que aplica os textos e mostra a página (o `i18n-ok`): num arquivo que não carregasse, a página, com o aviso de
fora do ar, ficaria escondida. Na página servida entram também, pelo `inline-script`, o `script-failed.js`, o
`desk-buttons.js` e o `start.js`.

Cada ouvinte mora no arquivo da parte que ele serve: os da busca (o campo, o formulário, os botões dela, o toque fora
da gaveta da busca na mesa e os resultados) no `search.js`, os dos efeitos de voz (a gaveta, o Ouvir e o botão de
desligar o efeito da barra de baixo) no `voice-effects.js`, os do toca-discos no `turntable.js` e os do receptor no
`receiver.js`, os do palco e da barra de baixo no `stage.js`, o da página do disco no `disc-page.js`, os da
prateleira no `shelf.js`, o do botão do celular no `phone.js` e os do Microfone e fone, da dica de ouvir e do desligar
no `devices.js`, os das boas-vindas no `welcome.js`, o do pareamento no `pairing.js` e os da mesa no
`desk-buttons.js`. O arquivo da parte guarda os ouvintes em funções, uma por trecho seguido de registros (o
`bindSearch()`, o `bindSearchResults()`, o `bindVoiceEffects()`, o `bindTurntable()`, o `bindReceiver()`, o
`bindMiniBar()`, o `bindStageButtons()` e o `bindStageGestures()` do palco, o `bindDiscPage()`, o `bindShelfClick()` e
o `bindShelf()`, o `bindPhoneButton()`, o `bindDeviceButtons()` e o `bindDeskButtons()`), e quem liga é o lugar em que cada trecho era registrado antes: o `ui-events.js` chama os da busca,
dos efeitos, do toca-discos, do receptor, do palco, da página do disco, da prateleira, do celular e dos
dispositivos, o `queue.js` chama o `bindSearchResults()` e o `start.js` chama o `bindDeskButtons()` antes da
partida. Com um arquivo da base faltando, o `ui-events.js` para no mesmo ponto em que parava, com os
mesmos ouvintes já registrados, e a partida não roda quando os botões da mesa param no meio (sem o `disc-page.js`, o
`dj-desk.js` ou, na mesa de DJ, o `queue.js`, de que o `montarMesa()` precisa ao montá-la), como no script único em que os dois moravam. Sem o `shared.js` (sem o `$`), o `connection.js` e o
`pairing.js` não registram os ouvintes da rede nem tira o `?parear` do endereço: na base, o bloco inteiro parava antes
deles.
Assim os controles só respondem quando os arquivos de que eles dependem já carregaram (o formulário da busca segue
`inert` até o `ui-events.js`), e cada ouvinte continua na mesma ordem dos outros no mesmo alvo (o toque fora da busca
para o evento depois de o ouvinte do `queue.js` na `window` ver o toque). A busca, os resultados e os efeitos de voz
só ligam sem nenhum arquivo faltando (`scriptsMissing()`), como antes; o toca-discos, o receptor, o palco, a página
do disco, a prateleira, o celular e os dispositivos, cujos ouvintes o `ui-events.js` registrava sempre, ligam se o próprio arquivo carregou (`scriptLoaded()`, do `script-failed.js`). Nos
dois casos o resto do arquivo que chama segue registrando os seus ouvintes até a página ir para o aviso de fora do ar. Os ajudantes de mais de uma parte (o `fmt()`, o
`mudar()` e o `ligarChave()`) moram no `shared.js`.

Todo nome do alto de um script é declarado por um script só. O `dev/theme_scripts.py`, que o `--tela` do
`dev/testa_tudo.py` roda, abre a página num Chrome sem tela contra um `--mock` e pega cada script como o V8 o leu. Cada
um vira o corpo de um gerador que é criado e não anda (as declarações nascem e nada roda), e os nomes saem do escopo
local dele. Um nome declarado em dois scripts (função, `var`, `let`, `const` ou `class`) faz a guarda falhar. Ele
confere também que os ouvintes da busca e da gaveta são dos arquivos delas e só existem depois do arquivo que os liga,
e que o `queue.js` vê o toque que fecha a busca na mesa.

Para provar que um PR só mudou código de lugar, o `dev/theme_rebuild.py <base>` monta a página de novo nos dois commits,
com cada `<!-- inline-script: -->` virando um `<script>` com o texto do arquivo, como o servidor manda, e cada `<script
src>` e `<link>` trocado pelo texto do arquivo. Ela só julga a página escrita numa forma estrita, que o navegador lê de
um jeito só: o `index.html` inteiro é texto sem `<` entre tags; a tag de início é `<nome>` em minúsculas com atributos
`nome="valor"` (ou só o nome), cada um uma vez, em minúsculas (fora do `<svg>`, onde vale o `viewBox`), separados por
espaço, tab ou fim de linha; a de fim é `</nome>`; o comentário é `<!--` ... `-->`, sem `<!-->`, `<!--->` nem `--`
dentro; e o doctype é `<!doctype html>`. Os elementos são os que o tema e a galeria usam, uma lista para o HTML e outra
para dentro do `<svg>` (`g`, `path`, `rect`, `circle` e `mask`): qualquer outro, de início ou de fim, fica de fora (um
`<p>` ou um `</p>` tiraria o navegador do `<svg>`). Um `<script>` e um `<style>` acabam no primeiro `</script>` e
`</style>`, sem outro `</script` ou `</style` antes, sem `<!--` no script (nem nos arquivos que o servidor põe inline) e
sem texto no `<script src>`; o `<title>`, o `<iframe>` e o `<select>` não têm `<` dentro. O `src` de um script e o
`href` de uma folha (com `rel="stylesheet"` e nada mais) são um caminho simples dentro do tema, como
`gerado/molduras.css`, sem `/` no começo, `..`, busca, `#`, `%`, `&` nem `\`. Fora disso ela recusa, com o arquivo (e,
no `index.html`, a linha e o trecho), e sai 3 (não sei julgar): `<script/>` e `<style/>`, um `<base>`, um `<link>` de
preload ou de prefetch, um `srcdoc`, um NUL num valor, um `&` num `rel`, `type` ou `as`, um `&` que não é uma referência
inteira e conhecida (como `&amp;`) num valor, um script de tipo que não é JavaScript nem JSON (um módulo importa
arquivos) um `@import`, um `@namespace` ou um `@scope` numa folha, mesmo escapado ou num comentário (o primeiro busca um
arquivo que a ferramenta não lê, o prefixo do segundo só vale na folha dele e o escopo do terceiro depende do elemento
que guarda a folha), um arquivo ligado pela página que não está no tema (o navegador recebe um 404) e um arquivo que o
servidor põe inline e não está no tema (ele não monta a página). Um `\r` sozinho conta como fim de linha, como no
navegador (lido do git ou da pasta). Numa folha, entre as regras e nas pontas, só cabem os espaços do CSS e comentários:
outro caractere ali (um tab vertical antes de um seletor) é uma folha que não se lê.
Ela sai 0 quando o head só muda código de lugar:
- todo arquivo do tema que a página não lê (as imagens e as fontes) tem o mesmo conteúdo nos dois commits;
- a marcação é a mesma, na mesma ordem (sem os cinco espaços do HTML nas pontas de cada linha), com cada script e cada
  folha de estilo no mesmo lugar dela;
- os scripts são os mesmos, na mesma ordem, cada um carregado do mesmo jeito (inline ou do mesmo arquivo), com os
  mesmos atributos e o mesmo modo estrito;
- cada script declara as mesmas funções no alto, pelo nome que o V8 lê (com os escapes `\u` desfeitos); elas podem
  mudar de lugar dentro dele, porque existem antes de qualquer instrução dele rodar, e só nele;
- toda outra instrução do alto está no head, na mesma ordem e no mesmo script;
- toda regra de estilo está no head, na mesma ordem, com os mesmos atributos de folha, numa folha da mesma pasta e inline
  ou de arquivo como antes (pode mudar de folha ligada ali, com a mesma extensão: as URLs relativas dela continuam
  apontando para o mesmo arquivo, e o servidor a entrega com o mesmo tipo) e com os mesmos scripts antes da folha dela
  (um script vê as regras das folhas que vêm antes dele);
- as traduções que o servidor põe na página (a pasta `i18n/`, na página com a marca do i18n) são as mesmas linhas, na
  mesma ordem (uma linha repetida também conta: chave repetida é erro no `i18n.ler`), sem o espaço das pontas que o
  `i18n.ler` também tira (o espaço depois de uma `\` fica), com as linhas quebradas onde o `i18n.ler` as quebra (o
  `splitlines`, que também quebra num `\v`).

Instruções e regras são comparadas como árvores de sintaxe (o tree-sitter, do `requirements-dev.txt`), com o texto de
cada nó que nenhum filho cobre (o número de um `14px`), sem os comentários e os espaços fora de strings e templates. A
quebra de linha logo depois do `return`, do `break`, do `continue`, do `throw`, do `yield`, de um `++` ou `--` e no
começo de uma função ou de uma seta conta, porque ali ela muda o que o código faz (o `return` seguido de quebra devolve
`undefined`). Assim, uma marca de bloco, uma linha em branco ou uma indentação nova
não são mudança, e um espaço dentro de um template literal, ou uma marca que junta dois tokens, são. No CSS
conta também se um token vem depois de espaço (só os cinco do CSS; outro caractere no vão fica), de comentário ou de
nada (o `calc()` pede os espaços em volta do `+`
e do `-`, e um comentário parte o `14/**/px`). Declarações de
função de mesmo nome guardam a ordem (vale a última). A parte do CSS
que a gramática não conhece (um `@container` dentro de `@media`) também é comparada pelos tokens, e um script que
não analisa, ou que o V8 (num Chrome sem tela) não compila, é mudança. O resto sai 1, com cada mudança impressa. O `dev/test_theme_rebuild.py`, do COMPLETO do
`dev/testa_tudo.py`, confere o veredito em páginas pequenas e no tema com o `notice.js` trocado com o `covers.js`, com o
`desk-buttons.js` e o `start.js` antes do `ui-events.js` e com o `bindShelfClick` levado do `shelf.js` para o fim do
`start.js`.

O `dev/theme_listeners.py <base>` prova o outro lado: abre o tema
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
guardada, que o navegador reabre com o Ritmelli fechado). A conexão não depende só do `transporte.js`: o começo da
página chama funções de outros arquivos antes do `carregar()` (o `montarMesa()` e o `montarMostradores()` do
`dj-desk.js`, o `carregarEfeitos()` do `voice-effects.js`), e sem um deles ela não conecta. Por isso o `onerror` de cada
`<script src>` chama o `scriptFailed`, do `script-failed.js`, que o servidor põe dentro da página no lugar do `<!--
inline-script: script-failed.js -->` do `<head>` (ver o `API.md`), antes do primeiro arquivo, e que por isso não tem
como faltar: os pedidos da carga ao servidor só começam terminada a leitura da página (no `DOMContentLoaded`), e se
faltou um arquivo eles não começam: a página fecha o diálogo e o pedido do código que um clique abriu, mostra o aviso de
fora do ar e carrega de novo, no endereço com que abriu, assim que o arquivo responde (conferido a cada 3 s). Só o
`transporte.js`, quando é o único que falta, fica com a volta dele: o `conectar()` o carrega de novo a cada 3 s, uma
carga por vez, e com ele de volta a página segue a carga normal, sem recarregar. O `dev/missing_script.py`, que o
`--tela` do `dev/testa_tudo.py` roda, confere cada um desses casos num Chrome sem tela, contra um `--mock` como o PC e
outro como um celular sem pareamento, e que cada `<script src>` da página, menos o `transporte.js`, traz o aviso de fora
do ar quando falha, sem nenhum pedido ao servidor. Para ver o papel do celular sem outro aparelho, o `--mock
--papel-local celular` (ver o `API.md`).

Parte do CSS do tema mora em arquivos ao lado do `index.html` (o `deck.css`, por exemplo), cada um com um bloco
marcado inteiro e carregado por um `<link rel="stylesheet">` sem `media`, no mesmo lugar em que o bloco estava: a
ordem das folhas e a cascata são as de antes, e os endereços relativos dentro do arquivo (`url(fonts/...)`) continuam
saindo da pasta do tema. O bloco que estava dentro de um `@media` do `<style>` leva o mesmo `@media` em volta no
arquivo. O que um gerador de `dev/` desenha
mora em `gerado/` (o `gerado/molduras.css`, por exemplo): o gerador grava o arquivo inteiro e não mexe no
`index.html`, e o que se muda à mão ali some na próxima vez que ele roda.

Todo o CSS do tema já mora em arquivos, um bloco marcado por arquivo, e a lista de `<link>` no alto do `index.html` é
a ordem da cascata: o `base.css` (as letras, as cores e o reset) primeiro, as partes da página (`buttons.css`,
`top-bar.css`, `phone.css`, ...), a pele por cima delas (`skin-vars.css`, as folhas geradas, `skin-top.css`,
`skin-case.css`, ...), os arranjos do computador e da mesa de DJ (`desktop-library.css`, `dj-desk.css`, ...) e o
`reduced-motion.css` perto do fim, antes do `deck.css`, do `mix.css` e do `pedal.css` da mesa. No `index.html` só fica a
linha que esconde a página até os textos estarem no lugar. O `dev/garden.py` guarda o número de linhas de CSS e JS
inline que ainda restam no `index.html` (o teto `theme_inline_lines` do `dev/garden.json`): ele só desce, código novo do tema vai num arquivo da
pasta, e a contagem vai para o resumo do PR. A contagem abaixo do número também falha: o PR que tira código da página
baixa o número junto.
