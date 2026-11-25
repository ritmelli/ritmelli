# Os temas e a galeria (`themes/`, `gallery/`)

`themes/<slug>/`: as interfaces; `gallery/index.html` lista e compara lado a lado, com as letras e as texturas do
tema `ritmelli` e os textos dela em `gallery/i18n/`, como num tema. O app abre direto no tema `ritmelli`
(`pastas.PAGINA`), e a galeria fica em `/`. Na primeira
vez, o tema abre as boas-vindas por cima (ver o `API.md`). Até a 0.6.0 o tema se chamava `vitrola`: o servidor
leva todo endereço em `/t/vitrola/` para o mesmo caminho em `/t/ritmelli/`, com a mesma query (o `tema_de_antes`
do `server.py`), porque o celular pareado, o atalho na tela inicial e os favoritos abrem o de antes.

Todo arquivo de `/t/` sai com `Cache-Control: no-cache`, como a página (o `tema_sem_guardar` do `server.py`): o
navegador confere cada um antes de usar o que guardou e nunca junta um `.js` ou um `.css` de antes com o `index.html`
novo. O `dev/testa_i18n.py` lê o `index.html` e todos os `.js` e `.css` da pasta do tema, e cada bloco marcado
(`/* NOME-INICIO */` ... `/* NOME-FIM */`, ou o `/* nome:inicio */` de um gerador de `dev/`) mora num arquivo só.
