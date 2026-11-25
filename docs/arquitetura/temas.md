# Os temas e a galeria (`themes/`, `gallery/`)

`themes/<slug>/`: as interfaces; `gallery/index.html` lista e compara lado a lado, com as letras e as texturas do
tema `ritmelli` e os textos dela em `gallery/i18n/`, como num tema. O app abre direto no tema `ritmelli`
(`pastas.PAGINA`), e a galeria fica em `/`. Na primeira
vez, o tema abre as boas-vindas por cima (ver o `API.md`). Até a 0.6.0 o tema se chamava `vitrola`: o servidor
leva todo endereço em `/t/vitrola/` para o mesmo caminho em `/t/ritmelli/`, com a mesma query (o `tema_de_antes`
do `server.py`), porque o celular pareado, o atalho na tela inicial e os favoritos abrem o de antes.

Todo arquivo de `/t/` sai com `Cache-Control: no-cache`, como a página (o `tema_sem_guardar` do `server.py`): o
navegador confere cada um com o servidor antes de usar o que guardou, e não usa um `.js` ou um `.css` de antes sem
conferir (o `dev/testa_mock.py` confere a página, o 304 dela e um `.js`). O `dev/testa_i18n.py` lê o `index.html` e
todos os `.js` e `.css` da pasta do tema, e cada bloco marcado (`/* NOME-INICIO */` ... `/* NOME-FIM */`, ou o
`/* nome:inicio */` de um gerador de `dev/`) mora num arquivo só, aberto e fechado nele, nessa ordem.

O código do tema sai aos poucos do `index.html` para arquivos `.js` na pasta do tema, um bloco marcado por arquivo, que
o `index.html` carrega por um `<script src>` no lugar em que o bloco estava, sem `defer`: os scripts rodam na mesma
ordem, e o que um deles declara no alto continua à vista dos de depois. O primeiro é o `shared.js`, carregado no
`<head>`: o estado da página (`S`), o da mesa de DJ (`MESA`) e os ajudantes de todos (o `$`, o `el`, o `clamp`, o
`reduz`, o `celular()`, o `toque()`, o `abrirMaleta()` e o `sombrear()`). Já saíram também: o `deck.js` (os toca-discos
da mesa), o `mix.js` (o mixer da mesa), o `pedal.js` (os pedais da mesa), o `maleta-vazia.js` (o aviso de vazio do A
seguir), o `letra-placa.js` (a letra de pixel das placas da mesa), o `prateleira.js` (o título e a contagem da plaqueta
da prateleira), o `maleta-tit.js` (o título da placa da maleta) e o `mesa-topo.js` (a plaqueta e as teclas do topo da
mesa em largura par). O `dj-visor.js` (o visor de DJ: a onda do disco que corre sob o ponto fixo do play), o
`voice-effects.js` (os efeitos de voz: o seletor no receptor e a gaveta de teclas), o `dj-desk.js` (os dois decks da
mesa de DJ, que se revezam como num set, no computador largo), o `search.js` (a busca e os resultados), o `queue.js` (a
fila, o A seguir) e o `ui-events.js` (os ouvintes de clique, de tecla e de ponteiro da página) saíram do script
principal da página, que é estrito: o arquivo tirado dele começa com `'use strict'`, como o script inline que segue
depois do `<script src>` dele. Para provar que um PR só mudou código de lugar, o `dev/theme_rebuild.py <base>` monta a
página de novo nos dois commits (cada `<script src>`, `<link>` e `<!-- inline-script: -->` trocado pelo texto do
arquivo, sem as marcas, com os outros atributos da tag numa linha e cada `'use strict'` como `[strict]`) e sai 0 só com
as duas páginas iguais, linha a linha; diferentes, ela separa os blocos que só mudaram de lugar das linhas novas ou que
sumiram (um arquivo novo traz o próprio `[strict]`).

Toda conversa do tema com o servidor passa pelo `transporte.js` (os pedidos da API, que o `api()` do `index.html` chama,
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
outro como um celular sem pareamento. Para ver o papel do celular sem outro aparelho, o `--mock --papel-local celular`
(ver o `API.md`).

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
linha que esconde a página até os textos estarem no lugar. O `dev/testa_i18n.py` guarda o número de linhas de CSS e JS
inline que ainda restam no `index.html` (o `INLINE_CEILING`): ele só desce, código novo do tema vai num arquivo da
pasta, e a contagem vai para o resumo do PR. A contagem abaixo do número também falha: o PR que tira código da página
baixa o número junto.
