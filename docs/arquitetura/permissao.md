# Quem pode cada rota (`permissao.py`)

`permissao.py`: a tabela `(método, rota) → papéis` que o `guard` do `server.py` confere em todo pedido, depois do
Host e da Origin. A rota é a canônica do aiohttp (`/api/library/{iid}`, sem o id), e o `HEAD` vale como o `GET`.
Rota fora da tabela é só do PC: rota nova nasce fechada, e abrir para o celular ou para o remoto é uma linha
escrita de propósito. Antes da tabela, cada rota nova da API abria sozinha para o celular pareado, e o
`/api/effects/reload` (que relê o `fx.py`) ficava ao alcance dele.

Os papéis saem de quem conectou, nunca do Host (que quem pede escreve como quiser):

- `pc`: o `127.0.0.1` sem o cabeçalho do remoto, que pode tudo;
- `celular`: da rede de casa, com a chave do pareamento (`pareamento.py`) no cookie;
- `publico`: da rede de casa, sem chave que valha: só o tema, os arquivos dele, a galeria e o pareamento;
- `remoto`: o `127.0.0.1` (só o IPv4) com o cabeçalho `X-Ritmelli-Remoto` e o token de uma sessão aceita
  (`Remotos`, um `secrets.token_urlsafe(32)` por sessão, só na memória, revogado quando ela acaba). Só o vocabulário
  fechado: tocar, enfileirar, pular, pausar, retomar, tirar e mover na fila, o volume da música, abaixar a música e
  o sinal de teste, e ler o estado; na fila, só disco da prateleira ou vídeo do YouTube, com a capa dele, para a
  sessão remota não fazer o PC baixar de outro endereço. As três rotas que o tema não usa (`/api/volume`,
  `/api/abaixa` e `/api/sinal`) ficam fechadas para o celular. Token que não vale dá 401, mesmo do `127.0.0.1`: o
  cabeçalho nunca cai no papel do PC. Por ora nenhuma sessão abre um token.

As rotas que só o módulo de fora do repo chama (`/api/tocadas`, `/api/musica` e `/api/aquece`) ficam juntas no
`OUT_OF_REPO` da tabela, só do PC, que é de onde ele conecta. O `dev/testa_ganchos.py` conta esse grupo como conta os
ganchos do `engine.py`: rota nova para o módulo passa pelas que já existem. O `POST /api/shutdown` também é só do PC:
desligado, o Ritmelli só religa no PC, e o tema mostra o Desligar pelo `caps`, não pela largura da tela.

O `caps` (`{"papel", "rotas"}`) diz a cada conexão o que ela pode: vem no `/api/state`, no 401 do pareamento e como o
primeiro evento do SSE, que fecha quando o celular é desconectado ou a sessão remota acaba. O `dev/testa_mock.py`
confere que toda rota do `server.py` está na tabela (pelo fonte e pelo roteador do aiohttp) e cada papel no `guard`
de verdade e num `--mock`, com a rede de casa feita pelo `127.0.0.2`.

O que a sessão remota manda pela internet e a rota local de cada comando estão no
[protocolo da sessão remota](../protocolo-remoto.md): o `dev/testa_protocolo.py` falha se o mapa de comandos de lá e
as rotas do `remoto` daqui não forem as mesmas.
