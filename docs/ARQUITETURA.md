# Arquitetura

Como cada peça funciona por dentro e por que é assim. Para instalar e usar, veja o
[README](../README.md); o contrato entre o servidor e a interface está no [API.md](../API.md).

Cada peça tem o seu arquivo em `arquitetura/`: quem muda uma peça muda só o arquivo dela.

- [`engine.py`](arquitetura/engine.md): o motor de áudio, a mistura e o volume automático (`sonoridade.py`).
- [`microfone/`](arquitetura/microfone.md): a saída para o jogo, o filtro (APO), o anel e a pista da voz.
- [`batida.py`](arquitetura/batida.md): andamento e grade de batidas para a passagem no tempo.
- [`compasso.py`](arquitetura/compasso.md): as batidas e o 1 de cada compasso pela rede (ONNX).
- [`andamento.py`](arquitetura/andamento.md): o andamento do começo e do fim de cada disco.
- [`yt_fora.py`](arquitetura/yt_fora.md): o YouTube num processo à parte.
- [`ritmelli.py`](arquitetura/ritmelli.md): o ponto de entrada e os processos auxiliares.
- [`fx.py`](arquitetura/fx.md): os efeitos de voz, o pedal de um módulo de fora do repo e o filtro "Quest como SM58".
- [`pistavoz.py`](arquitetura/pistavoz.md): o pedal de troca de voz (`pista.py`, `conversor.py`, `vozes.json`).
- [`winvol.py`](arquitetura/winvol.md): o volume do microfone no Windows.
- [`pareamento.py`](arquitetura/pareamento.md): o celular pareado.
- [`atualizacao.py`](arquitetura/atualizacao.md): o aviso de versão nova e a atualização pelo instalador.
- [`server.py`](arquitetura/server.md): o servidor, a fila, as passagens, o Automático e o limite de abas.
- [`API.md`](../API.md): contrato da API e checklist de todo tema.
- [`themes/` e `gallery/`](arquitetura/temas.md): as interfaces e a galeria.
- [`dev/`](arquitetura/dev.md): as ferramentas de print, de tela e de pixel art.
- [`icone/`](arquitetura/icone.md): o ícone do app.
- [`pastas.py`](arquitetura/pastas.md): onde moram os dados de quem usa, o ffmpeg e o Deno.
- [`migra.py`](arquitetura/migra.md): a troca de nome de Vitrola para Ritmelli.
- [`versao.py`](arquitetura/versao.md): a versão.
- [`i18n.py`](arquitetura/i18n.md): os textos da interface em cada língua.
