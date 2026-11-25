# AGENTS.md

O que vale para quem muda o código do Ritmelli e que o código não diz sozinho. Como cada peça funciona:
[docs/ARQUITETURA.md](docs/ARQUITETURA.md). O contrato entre o servidor e a interface: [API.md](API.md). Instalar,
rodar e contribuir: [README.md](README.md). Este arquivo fica em até 80 linhas (o `dev/testa_tudo.py` confere).

## Onde testar

- Nunca no 8799, no Ritmelli instalado, com o microfone de verdade nem no Discord de quem usa: o som sai no jogo de quem
  está jogando. O servidor de teste é o `--mock` noutra porta, que por padrão trabalha numa pasta temporária, só com uma
  cópia da lista da prateleira: `python server.py --mock --port 8801 --no-browser`.
- Só num Windows de teste: o Discord (num canal fechado de teste) e o `instala-todos` e o `remove` do
  `microfone\microfone.py`, que mexem em todo microfone e no filtro do Ritmelli instalado.

## Regras

- Código novo ou mexido (nomes, comentários, docstrings, log e erro), commits e PRs em inglês; o que já existe não se
  renomeia em massa. Texto da tela, nas duas línguas pelo i18n; os docs de `docs/`, em português.
- Nada pesado no processo do áudio: o bloco é de 10 ms, e o que segura o interpretador estala o som no jogo. Biblioteca
  lenta ou conta longa vai para um processo auxiliar, como o `yt_fora.py` (`ritmelli.py --yt`) e o `andamento.py`
  (`ritmelli.py --andamento`), que o servidor abre pelo `auxiliar` do `server.py`.
- O anel tem dois lados: o `microfone/apo/anel.h` e o espelho dele em ctypes no `microfone/injeta.py`. Mudou o layout,
  muda nos dois e sobe o `MICFX_VERSAO` e o nome do mapa (`MICFX_MAPA`): a versão velha pode estar viva no `audiodg`.
- Efeito de voz: as configurações moram no `fx.py`, e o `microfone/preset.py` as leva ao motor em C++. Etapa nova
  precisa do par no `microfone/apo/voz.h` (o `dev/testa_voz.py` falha sem ele).
- Texto novo da interface nas duas línguas: `themes/ritmelli/i18n/i18n_en.properties` e `i18n_pt_BR.properties`, com
  as mesmas chaves na mesma ordem, e os da galeria em `gallery/i18n/`. O servidor não escreve frase para a tela: manda
  a Mensagem do `i18n.msg`, com uma chave `server.*`.
- Rota nova do `server.py`: quem pode chamar cada uma é a tabela do `permissao.py`, que o `guard` confere. Rota fora
  da tabela é só do PC, e o `dev/testa_mock.py` falha enquanto ela não entra; abrir para o celular ou para o remoto é
  decisão escrita no PR. Rota ou campo novo entra no `API.md`, e a linha da tabela também.
- As travas do servidor se pegam numa ordem só: a de [comandos.md](docs/arquitetura/comandos.md#as-travas).
- O `engine.py` não ganha gancho novo para o módulo opcional de fora do repo: o que ele precisa passa pelo que já
  existe ([fx.md](docs/arquitetura/fx.md)), e o `dev/testa_ganchos.py` falha com um a mais. O mesmo vale para as rotas
  só dele: o grupo `OUT_OF_REPO` do `permissao.py`, que o `testa_ganchos` também conta.
- Código novo do tema vai num arquivo da pasta `themes/ritmelli/` (um `.js` ou `.css`), não no `index.html`.
- Mexeu em `instalador/`, nos `atualiza*.py`, no `migra.py`, no `pastas.py`, no `microfone/microfone.py` ou no
  `ritmelli.spec`: rode o "Monta o instalador" (`monta.yml`) na branch. Na CI, só ele compila o `.iss` e roda a parcial,
  a migração e o atualizador. Os nomes dos artefatos dele (`Ritmelli-<versão>` e `ritmelli-exe-<versão>`) e dos jobs
  `testa`, `testa-atualizador`, `testa-migracao` e `testa-parcial` são contrato com a esteira de publicação do
  `ritmelli-server`, que acha a execução por eles: renomear um quebra a publicação; muda junto com o server.
- Mudou uma peça, muda o arquivo dela em `docs/arquitetura/`.

## As superfícies de uma mudança

Toda mudança tem de cobrir as que toca, e o PR diz quais: o servidor (`server.py`) e o contrato no `API.md`; o tema no
PC e no celular (a pasta `themes/ritmelli/`, com o layout do celular abaixo de 900 px); i18n, nas duas línguas; o
filtro (`microfone/`); o instalador (`instalador/ritmelli.iss`) e a migração de quem já tem o app (`migra.py`); a
galeria (`gallery/index.html`, com os previews do `dev/previews.py`).

## O mapa: área, arquivos e teste

| Área | Arquivos | Teste (sem caminho, em `dev/`) |
| --- | --- | --- |
| Motor de áudio | `engine.py`, `sonoridade.py`, `transicao.py`, `batida.py` | `testa_ganho`, `testa_preabre`, `testa_congela`, `testa_microfone`, `testa_passagens`, `testa_passagem` (o motor de verdade, que usa o `batida.py`), `testa_transicao`, `testa_anel`, `testa_ganchos` |
| Servidor e YouTube | `server.py`, `comandos.py`, `automatico.py`, `music.py` (as funções puras de música), `yt_fora.py`, `yt_erros.py` | `testa_comandos`, `testa_automatico`, `testa_adianta`, `testa_rapido`, `testa_vivo`, `testa_musica` |
| `--mock` | `server.py`, `pastas.py`, `dev/so_mock.py` (a trava que tira as ferramentas de `dev/` da 8799) | `testa_mock`, `testa_so_mock` |
| Gravação dos dados | `pastas.py` (`save_json`) | `testa_grava` (só o `save_json`; o `grava_cfg` do `server.py` não tem teste próprio) |
| Pasta protegida | `pastas.py` (`pasta_protegida`, `create_task`, `disarm`) e quem os chama (`microfone/microfone.py`, `atualizador.py`, `atualizacao.py`, `migra.py`) | `testa_pasta_protegida` (em memória; o `--disco` precisa de administrador e cria pasta em Program Files: só num Windows de teste), `testa_mfx`, `testa_atualizador`, `testa_atualizacao`, `testa_migra` |
| A regra no setup | `instalador/protegida.ps1`, `instalador/ritmelli.iss` | `testa_pasta_protegida --disco` (roda o `instalador/protegida.ps1` em cada caso e exige o mesmo veredito do `pastas.py`); o `.iss`, só a instalação do `.github/workflows/monta.yml` |
| Pareamento e permissões | `pareamento.py`, `permissao.py`, o `guard` do `server.py` | `testa_pareamento`, `testa_mock`, `testa_protocolo` |
| Protocolo da sessão remota | `docs/protocolo-remoto.md`, `docs/protocolo-remoto/v1/` | `testa_protocolo` (`--gera` escreve as fixtures de novo) |
| Filtro e efeitos | `microfone/`, `fx.py`, `instalador/mudos.iss` | `testa_filtro`, `testa_mfx`, `testa_microfone`, `testa_anel`, `testa_aparelho_mudo` (os casos do setup de teste precisam do Inno Setup 6: sem ele, pulam no PC e reprovam no GitHub), `testa_voz` e `microfone/apo/teste/teste_reamostra.py` (este, o `testa_filtro`, o `testa_microfone` e o `testa_voz` precisam das DLLs do `microfone\apo\compila.bat teste`, com o Ritmelli desligado: o `--mock` também segura a DLL dos efeitos) |
| Troca de voz | `pistavoz.py`, `pista.py`, `conversor.py`, `vozes.json` | `testa_pedal_voz`, `testa_vozes`, `testa_pista`, `testa_conversor` |
| Atualizações | `atualizacao.py`, `atualizador.py`, `instalador/atualizacao/` | `testa_atualizacao`, `testa_atualizador` e `instalador/atualizacao/testa_parcial.py` |
| Textos | `i18n.py`, `themes/ritmelli/i18n/`, `gallery/i18n/` | `testa_i18n` |
| Dados de uso | `metricas.py` e o aviso deles no tema | `testa_metricas`; o aviso, `fitcheck.py --metricas` (sobe os próprios `--mock --metricas-teste`, sem rede) |
| Troca de nome | `migra.py` | `testa_migra` |
| Interface | `themes/ritmelli/`, `gallery/` | `fitcheck.py` e `missing_script.py` (o `--tela` do `testa_tudo` roda os dois) contra o `--mock`; mudou as boas-vindas, também com `--boas-vindas`, num `--mock` com `--data-dir` novo e uma library.json só com `[]` |
| Sem teste | `compasso.py`, `andamento.py`, `janela.py`, `winvol.py` | o PR diz como conferiu |

## Antes do PR

Rode na raiz, com o venv: `$env:PYTHONUTF8 = '1'; python -m ruff check .; python dev\testa_tudo.py` (os outros modos e
onde entra teste novo: o [Contributing](README.md#contributing) do README). O check "Testa o PR" roda o mesmo; print
mudado no `compara` só bloqueia com a etiqueta `extracao-tema` (sem ela, fica no artefato). A fila de merge da `main`
exige ele e o "Trusted author": PR de quem não é um dos dois mantenedores só passa aprovado por um deles no head atual.
Sem bypass nem `--admin`; `gh pr merge` cai no auto-merge, vedado: é o GraphQL `enqueuePullRequest`, `expectedHeadOid`.
A fila recusa PR com a etiqueta `needs-owner` (o passo "Needs owner" do `testa.yml`, testado pelo
`dev/test_needs_owner.py`): ela marca a prova que pede ação física ou decisão do dono, e o dono a tira depois de provar.
