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
aberto e fechado nele, nessa ordem, e cada `.js` e `.css` fora do `gerado/` tem exatamente um bloco, com a marca
sozinha na linha dela (o texto que explica o bloco vai num comentário logo abaixo).

Código novo do tema vai num arquivo da pasta `themes/ritmelli/` (um `.js` ou `.css`), não no `index.html`.
Texto novo da interface entra por uma chave nas duas línguas (`i18n/` do tema, `gallery/i18n/` da galeria),
não escrito direto no HTML ou no JS.
Quem muda as boas-vindas roda o `dev/fitcheck.py` também com `--boas-vindas`, num `--mock` com `--data-dir`
novo e uma `library.json` só com `[]`. A janela própria (`janela.py`) se prova no app instalado, no job `testa`
do `monta.yml`.

O `index.html` do tema, por qualquer nome do mesmo arquivo (outra caixa, o nome 8.3, ponto ou espaço no fim, barra
dobrada, `::$DATA`, um link físico numa subpasta do tema), leva por 302 à página montada em `/t/<slug>/`, com a mesma
query: o `built_page_only` do `server.py`, só nos pedidos do static, compara numa thread o arquivo pedido com o
`index.html` do tema pelo `os.path.samefile`. Essa conferência, a rota do tema e as tags de arquivo passam pela mesma
porta, o `resolved_inside` do `theme_page.py`: antes de qualquer leitura do disco, o caminho tem de estar, pela
escrita, dentro de `themes/` (numa tag de arquivo sem `/t/`, dentro da pasta da página), e um `/t///host/share/...`,
um slug com `%5C` ou um `src="//host/share/x.js"` nunca faz o PC abrir um compartilhamento de rede. O
`dev/testa_mock.py` confere os nomes e esses endereços.

A página do tema chega inteira numa resposta só. O `index.html` lista os arquivos da pasta do tema, cada um no lugar em
que roda: um `<script src="arquivo.js"></script>` por script e um `<link rel="stylesheet" href="arquivo.css">` por
folha, sem outros atributos. O servidor (o `build` do `theme_page.py`, que o `server.py` chama) troca cada um por um
`<script>` ou um `<style>` com o texto do arquivo, sem a marca de ordem de bytes (BOM) do começo, e a página não pede ao
servidor nenhum script nem nenhuma folha: não existe página com um arquivo faltando. Um módulo entra por
`<script type="module" src="nome.js"></script>`, com o nome em minúsculas, algarismos, `-` e `/`. A montagem põe, no
lugar da primeira tag de módulo, um `<script type="importmap">` com cada módulo da página num endereço `data:` (o texto
do arquivo em base64, com uma linha `//# sourceURL=nome.js` no fim, para o erro de um módulo apontar o arquivo e a
linha, e não o endereço inteiro, e para dois módulos de texto igual terem cada um o seu endereço), e
troca cada tag de módulo por um
`<script type="module">import "nome.js";</script>`, o primeiro logo depois do mapa.
Um módulo importa o outro pelo nome (`import { glyphs } from "pixel.js";`), que o mapa resolve dentro da própria
página. A gramática lê o mapa e as linhas de import só na página montada (o `strict(html, built=True)`), e só se o mapa
for, byte a byte, o que a montagem escreveria com os mesmos módulos, sem retorno de carro (a montagem lê cada fim de
linha como `\n`). A montagem lê o modelo inteiro por
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
  `<script src="arquivo.js"></script>`, `<script type="module" src="nome.js"></script>` ou
  `<link rel="stylesheet" href="arquivo.css">`; e o mesmo módulo em duas tags: uma só;
- um `<meta http-equiv="Content-Security-Policy">` em qualquer página, que impede o navegador de rodar os scripts inline
  e os módulos `data:` da página quando não libera os dois: deixe-o de fora (o servidor não manda política, e uma num
  cabeçalho bloquearia do mesmo jeito);
- um `&` no `src` ou no `href` de um `<script>`, de um `<style>` ou de um `<link>` que não abre uma referência nomeada
  inteira, e toda referência numérica: o nome sem `&`, ou com `&amp;`; e um `&` no `rel`, no `type` ou no `as`: o valor
  escrito por extenso;
- o script com `</script` ou `<!--` ou que começa com `#!`, o módulo que começa com `#!` e a folha com `</style`: o
  texto sem eles;
- a folha, de arquivo ou escrita na página, com `@import`, mesmo num comentário ou numa string (a folha se lê com os
  escapes de CSS decodificados): uma tag de arquivo por folha;
- a folha de outra pasta com um `url()` relativo, uma `\` ou um `image-set(`: só `url()` simples, com `https://`,
  `http://`, outro esquema, `data:`, `/` ou `#`, ou a folha na pasta da página;
- o `<link rel="modulepreload">`, o `<link rel="prefetch">` e o `<link rel="preload">` de um script ou de uma folha: a
  tag de arquivo;
- o `<script>` escrito na página com um `type` que não é `text/javascript` nem `application/json` (o `module` importa
  arquivos), e o `importmap` e o módulo escritos no modelo: um `<script>` sem `type` ou com um desses dois, a tag de
  arquivo ou a tag de módulo;
- toda tag dentro de um `<select>`, onde um navegador pode descartar ou mover o que a montagem leria (o Chrome de hoje
  guarda ali o `<link>` e o `<style>`; o leitor antigo do `<select>`, que outros navegadores ainda usam, descarta o
  `<link>`): o `<select>` vazio, preenchido pelo código do tema;
- o `srcdoc`, que escreve uma página num atributo: tirá-lo, e pôr no próprio tema o que ele mostrava;
- a marca `<!-- i18n -->` fora de um comentário só dela (num atributo, num `<style>` ou num `<script>`) ou dentro de um
  `<svg>` ou de um `<select>`, onde o `<script>` dos textos não entra, e a marca antes do `<!doctype html>`, onde esse
  `<script>` poria a página em quirks mode: a marca sozinha, como comentário, no `<head>`.

O `dev/testa_mock.py` confere cada caso da lista e cada forma fora da gramática (os casos moram no
`dev/theme_page_cases.py`). O `dev/theme_page_oracle.py`, que o `--tela` do `dev/testa_tudo.py` roda, abre num Chrome
sem tela, com os scripts bloqueados pelo cabeçalho `Content-Security-Policy: script-src 'none'` (o Chrome lê a página
como com o JavaScript ligado, e o `<noscript>` como texto), o tema, a galeria e cada caso que a montagem aceita, e
reprova quando os `<script>`, `<style>` e `<link>` do DOM, com o `src`, o `href`, o `rel` e o `type`, não são, na mesma
ordem, os que a montagem leu: uma forma que a gramática aceita e o navegador lê de outro jeito vira falha de teste.
Ele abre também uma página montada com módulos, um importando o outro, dois que só diferem por um espaço no fim, dois
de texto igual e um que lê a própria pilha, com os scripts da página e os `data:` liberados, e reprova se eles não rodam todos, se a pilha
não traz o nome do arquivo ou se o Chrome pede ao servidor qualquer coisa além da página. Na mesma página, dois módulos
que declaram `arguments` e `yield`, o que um clássico pode, não rodam (o modo estrito, #239) e os outros rodam; e a
página com um `<meta>` de `Content-Security-Policy` roda o clássico e não os módulos, e a montagem a recusa. O
`dev/missing_script.py`, que o `--tela` também roda, lê a página e a galeria como o servidor as manda, nas duas línguas,
de um `--mock` como o PC e de outro como o celular, pela mesma gramática da montagem (o `strict` do `theme_page.py`), e
reprova com um `<script src>` ou um `<link rel="stylesheet">` nelas ou com um pedido de script ou de folha que o Chrome
faça ao servidor. O `dev/test_theme_modules.py` lê o tema pela árvore de sintaxe:
- a conferência desce na árvore por um leitor só, que pula os comentários e tira os parênteses de uma expressão (o
  `(zz) = 1` é a escrita no `zz`, e o `x['load']` é o `x.load`), e nenhuma regra decide a forma pelo texto de um nó;
  cada caso do teste, reescrito com um comentário entre cada dois tokens e com parênteses em volta de cada expressão nos
  lugares que a conferência lê (o valor, o alvo de uma escrita e o lado esquerdo do `for…of`, o devolvido, a chamada, o
  membro, os operandos e os argumentos), dá o mesmo veredito;
- cada import e cada export ficam no alto do módulo; cada import tem a forma `import { a, b } from "arquivo.js"`, com
  pelo menos um nome, nomes simples e sem `as`, e cada export é um `export const` de nomes simples ou um `export
  function`; outra forma (o `default`, o `* as`, o `as`, a reexportação, o `export { }`, o `export let`, o `export
  class`, o import só pelo efeito, o `import {}`, os atributos) reprova, com o arquivo e a linha, como forma que a
  conferência não julga. Cada import nomeia um módulo da página e um nome que ele exporta, e nenhum módulo importa ou
  exporta o mesmo nome duas vezes; num clássico, um import, um export ou um `import.meta` reprova;
- cada nome importado é usado e não é declarado de novo, e um módulo não escreve no import nem num nome que ninguém
  declara (o modo estrito lança erro nos dois); cada nome se resolve pelos escopos em volta dele, e uma atribuição por
  desestruturação não declara nada; um módulo não liga `yield` nem outra palavra que o modo estrito reserva, nem no
  import, e não repete um parâmetro (o clássico pode); um módulo não tem `await` fora de função, que o
  `DOMContentLoaded` não espera;
- cada export é importado por outro arquivo do tema;
- um módulo que exporta função não exporta um dado que ele não usa e que um arquivo só importa (o dado fica nesse
  arquivo);
- nos lugares onde um nome é ligado ou escrito, só cabem os nós que a conferência lê (o nome, os padrões de objeto e de
  lista, o valor padrão, o resto, e na escrita também o membro de um objeto); outro nó ali reprova, com o arquivo e a
  linha, como forma que ela não julga, e o trecho se reescreve numa forma da lista; também não julga, e reprova, um nome
  que não é ASCII simples (letra, `_` ou `$`, depois letras, dígitos, `_` ou `$`), como o escrito com escape, e o valor
  padrão de um parâmetro que lê um nome que o corpo da função declara ou um parâmetro de depois, uma `class` (declaração
  ou expressão, com o bloco estático, os campos e os nomes privados dela), um método de nome computado, num objeto ou
  numa classe, uma função ou um generator declarado dentro de um bloco (fora do alto do arquivo e do alto do corpo de
  uma função), o nome de um valor do objeto global (`undefined`, `NaN`, `Infinity`, `arguments` ou `eval`) ligado,
  importado ou escrito, e um `with`, num clássico ou num módulo;
- cada script se analisa sem erro, nenhum script, clássico ou módulo, usa `import()`, e nenhum arquivo lê um nome que
  só outro módulo declara (um módulo chega a ele só pelo import);
- nenhum arquivo escreve de novo uma função que um módulo exporta (com os nomes ligados dentro dela trocados), e só o
  `pixel.js` carrega as fontes do motor (o `fontesProntas`);
- a regra do objeto montado à mão promete isto: num arquivo que não é o da função, um literal de objeto só de pares e de
  nomes, com todas as chaves (pelo menos três) do literal que uma função exportada devolve (num `return` do corpo dela,
  fora das funções e dos métodos de dentro, entre parênteses ou não), reprova, a não ser que o valor de cada uma dessas
  chaves seja o nome que a desestruturação de topo da chamada à função importada liga pela mesma chave (com aspas ou
  sem, e com os escapes da chave lidos). Ela não promete pegar o objeto montado por atribuição de campo, por `...` ou
  por `Object.assign`, o que tem chave computada ou numérica, o de menos de três chaves, nem a função que devolve o
  objeto por um nome. Numa chave entre aspas, ela lê os escapes `\n`, `\t`, `\r`, `\b`, `\f`, `\v`, `\xHH`, `\uHHHH` (o
  par substituto escrito assim vira um caractere só), `\u{…}` até `10FFFF`, o octal antigo (`\165`) e a barra antes da
  quebra de linha; outro caractere depois da barra vale ele mesmo, e um `\u{…}` acima de `10FFFF` fica como está;
- nenhuma sequência de 8 linhas não triviais aparece em dois `.js` do tema.

O `dev/garden.py` conta as linhas de CSS e
JS escritas no próprio `index.html` e guarda o teto delas (o `theme_inline_lines` do `dev/garden.json`), que é 0: código
novo do tema vai num arquivo da pasta, e a contagem vai para o resumo do PR.

Os scripts clássicos, sem `defer`, rodam na ordem da lista, e o que um declara no alto fica à vista dos de depois. Os
módulos rodam depois de todos os clássicos e antes do `DOMContentLoaded`, cada um com o escopo dele e no modo estrito:
um módulo lê o que os clássicos declaram, mas um clássico não importa de um módulo. Por isso um arquivo vira módulo
quando nenhum clássico lê os nomes dele, e o `i18n.js` e o `shared.js`, que todos leem, são os últimos.
No `<head>`, logo depois dos textos que o servidor põe no `<!-- i18n -->`, vêm o `i18n.js` (o `I18N`, ver o
[i18n.md](i18n.md)), o `browser-check.js` (no navegador sem import map, que não rodaria os módulos, para a leitura da
página com o `window.stop()` e mostra o aviso `app.noImportMap`, antes de qualquer outro script rodar), o `shared.js` (o
estado da página, `S`, o da mesa de DJ, `MESA`, e os ajudantes de todos: o `$`, o `el`, o `clamp`, o `reduz`, o
`celular()`, o `toque()`, o `abrirMaleta()`, o `sombrear()`, o `dialogoAberto()`, o `fmt()`, o `mudar()` e o
`ligarChave()`) e o `gerado/pecas.js` (as constantes das peças de pixel, do `dev/pecas.py`).
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
página e, no `DOMContentLoaded`, carrega e conecta). Depois vêm os desenhos de pixel da mesa, que são módulos: o
`letters.js` (as letras das placas, dos pedais e da plaquinha do toca-discos), o `pixel.js` (o motor de pixel: as
cores comuns, o ruído, o pincel, as caixas, os discos, as esferas, o carimbo de um desenho, a espera das fontes e as
letras 5x7 e de bitmap, que o `glyphs()` monta com um cache por quem chama, com os glifos próprios dele), o
`prateleira.js` (o título e a contagem da plaqueta da prateleira), o `maleta-tit.js` (o título
da placa da maleta), o `mesa-topo.js` (a plaqueta e as teclas do topo em largura par), o `deck.js` (os toca-discos, que
exporta a letra deles, o `deckGlyphs`), o `maleta-vazia.js` (o aviso de vazio do A seguir, na letra do `deck.js`), o
`mix.js` (o mixer) e o `pedal.js` (os pedais). O `deck.js`, o `mix.js` e o `prateleira.js` começam no
`DOMContentLoaded`, depois do ouvinte do `start.js`, que se registrou antes deles.

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
`dev/testa_tudo.py` roda, abre a página num Chrome sem tela contra um `--mock` e pega cada script como o V8 o leu, com o
nome do arquivo dele achado pelo texto. Cada um vira o corpo de um gerador que é criado e não anda (as declarações
nascem e nada roda), e os nomes saem do escopo local dele. Um nome declarado em dois scripts (função, `var`, `let`,
`const` ou `class`) faz a guarda falhar. O leitor não vê dois nomes que só um script sem `'use strict'` aceita (um `var
arguments`, um `const yield`): os dois ficam no teste como falha conhecida da issue #239. Ele confere também que cada
ouvinte das partes é do arquivo dela, que a página só passa a vigiar a própria visibilidade no `DOMContentLoaded`, com o
`carregar()` já declarado (uma aba que aparece durante a leitura da página não conecta antes da partida), que o
`queue.js` vê o toque que fecha a busca na mesa, que cada módulo do mapa da página roda (o `import()` de cada nome dele,
com o erro de quem falha), que um navegador sem import map (o `HTMLScriptElement.supports` tirado, ou trocado por um que
recusa o `importmap`, antes da página) recebe o aviso e nenhum ouvinte, e que os canvas dos rótulos do mixer, do
monitor, dos pads, da sombra do deck, do título da maleta, da contagem da prateleira e do aviso de vazio, limpos, ficam
limpos até um `repinta-canvas` e então se pintam de novo (o canvas que o navegador devolve em branco, #119).

Para provar que um PR só mudou código de lugar, o `dev/theme_rebuild.py <base>` monta a página de novo nos dois commits
como o servidor a monta: cada `<script src="..."></script>` e `<link rel="stylesheet" href="...">` trocado pelo texto
do arquivo, e a marca do i18n, na página que tem uma e no tema com a pasta `i18n/`, pelo `<script>` dos textos (a
pasta com uma língua só sai 3), que conta entre os scripts antes de
cada folha. A ferramenta lê o `index.html` com o leitor da própria montagem (o `Template` do `theme_page.py`), então o
que a montagem recusa sai 3, com a linha e o motivo dela. O `src` de um script e o `href` de uma folha são, além disso,
um caminho simples dentro do tema, como `gerado/molduras.css`, ou `/t/<tema>/` seguido de um caminho simples, lido da
pasta daquele tema, sem `..`, busca, `#`, `%`, `&` nem `\`. Como o servidor põe todo arquivo ligado na página, um script
ligado não tem `</script`, `<!--` nem `#!` no começo, e uma folha ligada não tem `</style` e passa pela conferência de
folha da montagem (o `sheet_problem` do `theme_page.py`). Fora disso ela recusa, com o arquivo (e, no `index.html`, a
linha), e sai 3 (não sei julgar): um `@namespace` ou um `@scope` numa folha, mesmo escapado ou num comentário (o
prefixo do primeiro só vale na folha dele e o escopo do segundo depende do elemento que guarda a folha), um arquivo
ligado pela página que não está no tema (o servidor não monta a página), um arquivo que não é texto em UTF-8 e um
comentário `<!-- inline-script: -->`, que os servidores de antes do `theme_page.py` trocavam por um arquivo e o de agora deixa como comentário. Um `import()` em
qualquer script (o nome nu dele só se resolve pelo mapa, que a página tem a partir da primeira tag de módulo) e, num
módulo, um import cujo texto não é o nome de um módulo que a página marca (um escape nele também) saem 3: a ordem em
que os módulos rodam vem só dos imports escritos. Cada `<script type="module" src="nome.js"></script>` é um bloco
`[module nome.js]`, com o texto do arquivo (o mapa de imports que o servidor escreve não é marcação do modelo). Um `\r` sozinho
conta como fim de linha, como no navegador (lido do git ou da pasta).
Numa folha, entre as regras e nas pontas, só cabem os espaços do CSS e comentários: outro caractere ali (um tab vertical
antes de um seletor) é uma folha que não se lê.
Ela sai 0 quando o head só muda código de lugar:
- todo arquivo do tema que a página não lê (as imagens e as fontes) tem o mesmo conteúdo nos dois commits;
- a marcação é a mesma, na mesma ordem (sem os cinco espaços do HTML nas pontas de cada linha), com cada script e cada
  folha de estilo no mesmo lugar dela e com o mesmo entre ela e o texto de cada lado: nada, os mesmos espaços do HTML,
  ou espaços do HTML com uma quebra de linha;
- os scripts são os mesmos, na mesma ordem, cada um carregado do mesmo jeito (inline ou do mesmo arquivo), com os
  mesmos atributos e o mesmo modo estrito;
- cada script declara as mesmas funções no alto, pelo nome que o V8 lê (com os escapes `\u` desfeitos); elas podem
  mudar de lugar dentro dele, porque existem antes de qualquer instrução dele rodar, e só nele;
- toda outra instrução do alto está no head, na mesma ordem e no mesmo script;
- toda regra de estilo está no head, na mesma ordem, com os mesmos atributos de folha, numa folha da mesma pasta e inline
  ou de arquivo como na base (pode mudar de folha ligada ali, com a mesma extensão: as URLs relativas dela continuam
  apontando para o mesmo arquivo) e com os mesmos scripts antes da folha dela
  (um script vê as regras das folhas que vêm antes dele; um módulo roda depois de todos os clássicos e da marcação
  inteira, e não conta);
- os módulos são os mesmos e rodam na mesma ordem, a do navegador: em profundidade, a partir da ordem das tags, cada um
  depois dos que ele importa; e cada módulo, pelo nome, declara as mesmas funções e tem toda outra instrução do alto da
  base, na mesma ordem (os nomes de um módulo são dele, então nada muda de um módulo para outro);
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
`desk-buttons.js` e o `start.js` antes do `ui-events.js`, com o `bindShelfClick` levado do `shelf.js` para o fim do
`start.js`, com a tag do `deck.js` depois da do `mix.js` e com o `pincel` levado do `pixel.js` para o `deck.js`; a tag
do `maleta-vazia.js` antes da do `deck.js` sai 0, porque o `maleta-vazia.js` importa o `deck.js`, que por isso roda
antes dele.

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

Num PR com a etiqueta `extracao-tema`, o job Tela roda as duas provas da base contra o head, nos passos "Only moves
code" (`dev/testa_tudo.py --passo theme-rebuild --base`) e "Same listeners" (`--passo theme-listeners`), e reprova se
uma delas não sai 0. A base é a do PR, e na fila o commit logo antes da entrada (a mesma do Compara). O
`dev/test_ci_workflow.py` confere os dois passos, a condição deles, a base e o comando.

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
