# Os temas e a galeria (`themes/`, `gallery/`)

`themes/<slug>/`: as interfaces; `gallery/index.html` lista e compara lado a lado, com as letras e as texturas do
tema `ritmelli` e os textos dela em `gallery/i18n/`, como num tema. O app abre direto no tema `ritmelli`
(`pastas.PAGINA`), e a galeria fica em `/`. Na primeira
vez, o tema abre as boas-vindas por cima (ver o `API.md`). Até a 0.6.0 o tema se chamava `vitrola`: o servidor
leva todo endereço em `/t/vitrola/` para o mesmo caminho em `/t/ritmelli/`, com a mesma query (o `tema_de_antes`
do `server.py`), porque o celular pareado, o atalho na tela inicial e os favoritos abrem o de antes.

Todo arquivo de `/t/` sai com `Cache-Control: no-cache`, como a página (o `tema_sem_guardar` do `server.py`): o
navegador confere cada um com o servidor antes de usar o que guardou, e não usa um `.js` ou um `.css` de antes sem
conferir. O `dev/testa_i18n.py` lê o `index.html` e todos os `.js` e `.css` da pasta do tema, e cada bloco marcado
(`/* NOME-INICIO */` ... `/* NOME-FIM */`, ou o `/* nome:inicio */` de um gerador de `dev/`) mora num arquivo só.

O código do tema sai aos poucos do `index.html` para arquivos `.js` na pasta do tema, um bloco marcado por arquivo, que
o `index.html` carrega por um `<script src>` no lugar em que o bloco estava, sem `defer`: os scripts rodam na mesma
ordem, e o que um deles declara no alto continua à vista dos de depois. Já saíram: o `deck.js` (os toca-discos da
mesa), o `mix.js` (o mixer da mesa), o `pedal.js` (os pedais da mesa), o `maleta-vazia.js` (o aviso de vazio do A
seguir), o `letra-placa.js` (a letra de pixel das placas da mesa), o `prateleira.js` (o título e a contagem da plaqueta
da prateleira), o `maleta-tit.js` (o título da placa da maleta) e o `mesa-topo.js` (a plaqueta e as teclas do topo da
mesa em largura par).

Toda conversa do tema com o servidor passa pelo `transporte.js` (os pedidos da API, que o `api()` do `index.html`
chama, e o fluxo de eventos do SSE): o resto do tema não sabe como ela chega, e o `fetch`, o `EventSource` e o
`location.hostname` só aparecem nele. O que o tema mostra a cada um vem do `caps` que o servidor manda (no
`/api/state`, no 401 do pareamento e no começo do SSE; ver o `API.md`), e não do endereço da página: os controles do
PC (o botão Celular, a versão nova, os dados de uso, as boas-vindas) só aparecem depois de o `caps` dizer que a rota
deles abre. O 401 do pareamento põe o `caps` de antes de parear; pareado, o `/api/state` traz o do celular; o
celular desconectado no PC volta ao de antes. O endereço só fica com o texto do aviso de fora do ar da página que
nunca recebeu um `caps` (a guardada, que o navegador reabre com o Ritmelli fechado). O `transporte.js` é o único
script do tema de que a conexão depende: se a carga dele falha ao abrir a página (o servidor fora), o `conectar()` o
carrega de novo a cada 3 s, uma carga por vez, e com ele de volta a página segue a carga normal, sem recarregar. Para
ver o papel do celular sem outro aparelho, o `--mock --papel-local celular` (ver o `API.md`).

Parte do CSS do tema mora em arquivos ao lado do `index.html` (o `deck.css`, por exemplo), cada um com um bloco
marcado inteiro e carregado por um `<link rel="stylesheet">` sem `media`, no mesmo lugar em que o bloco estava: a
ordem das folhas e a cascata são as de antes, e os endereços relativos dentro do arquivo (`url(fonts/...)`) continuam
saindo da pasta do tema. O bloco que estava dentro de um `@media` do `<style>` leva o mesmo `@media` em volta no
arquivo, e o `<style>` fecha o `@media` antes do `<link>` e abre de novo depois. O que um gerador de `dev/` desenha
mora em `gerado/` (o `gerado/molduras.css`, por exemplo): o gerador grava o arquivo inteiro e não mexe no
`index.html`, e o que se muda à mão ali some na próxima vez que ele roda.

The base CSS of the theme is out of the page too, one marked block per file, in the order the page loads them:
`base.css` (the fonts, the colors and the reset), `buttons.css`, `grid.css`, `top-bar.css`, `turntable.css`,
`receiver.css`, `devices.css`, `wall.css`, `dialogs.css`, `phone.css`, `pedalboard.css`, `home.css` and
`skin-vars.css`. The CSS still inline has its blocks marked already, ready to move. The `dev/testa_i18n.py` keeps a
ceiling on the lines of inline CSS and JS left in the `index.html` (`INLINE_CEILING`): it only goes down, new theme
code goes into a file of the folder, and the count goes to the PR summary.
