# AGENTS.md

O que vale para quem muda o código do Ritmelli e que o código não diz sozinho. Como cada peça funciona e as convenções
do repo: [docs/ARQUITETURA.md](docs/ARQUITETURA.md). O contrato entre o servidor e a interface: [API.md](API.md).
Instalar, rodar e contribuir: [README.md](README.md). Cada regra cita a verificação que a segura, e o arquivo fica em
até 80 linhas (o `dev/garden.py` confere as duas).

## Onde testar

- Nunca na 8799, que é o Ritmelli de quem está jogando: as ferramentas de `dev/` recusam falar com ela (a trava do
  `dev/so_mock.py`, provada pelo `dev/testa_so_mock.py`). O servidor de teste é o `--mock` noutra porta, numa pasta
  temporária (o `testa_mock` confere): `python server.py --mock --port 8801 --no-browser`.

## Regras

- O processo do servidor não carrega o `yt_fora.py` nem as bibliotecas dele (yt-dlp, ytmusicapi, requests), que rodam
  num processo auxiliar ([engine.md](docs/arquitetura/engine.md)): o `dev/test_audio_imports.py` falha se um módulo que
  esse processo carrega, também os de `microfone/`, importar um deles.
- O anel tem dois lados, o `microfone/apo/anel.h` e o espelho dele em ctypes no `microfone/injeta.py`: o `testa_filtro`
  faz o filtro de verdade ler o que o `injeta.py` escreve.
- Efeito de voz: as configurações moram no `fx.py`, e o `microfone/preset.py` as leva ao motor em C++. Etapa nova
  precisa do par no `microfone/apo/voz.h` (o `dev/testa_voz.py` falha sem ele).
- A chave escrita entre aspas num `data-i18n*` ou dentro de uma chamada do `I18N.t` existe nas duas línguas:
  `themes/ritmelli/i18n/i18n_en.properties` e `i18n_pt_BR.properties`, com as mesmas chaves na mesma ordem, e as da
  galeria em `gallery/i18n/`; a chave `server.*` de cada `i18n.msg` e `i18n.Recusa` do servidor existe em todo tema com
  `i18n/`, com os mesmos parâmetros (o `testa_i18n` confere as duas coisas).
- Rota nova do `server.py` entra na tabela do `permissao.py`, que o `guard` confere: rota fora da tabela é só do PC, e o
  `dev/testa_mock.py` falha enquanto ela não entra.
- As travas do servidor se pegam numa ordem só: a de [comandos.md](docs/arquitetura/comandos.md#as-travas).
- O `dev/testa_ganchos.py` conta os ganchos do `engine.py` para o módulo opcional de fora do repo, as rotas do grupo
  `OUT_OF_REPO` do `permissao.py`, os acessos dos outros módulos da raiz aos privados do motor, do `App` e do
  Automático, os do resto do `server.py` aos privados da `Library` e as escritas diretas no estado do `App` e do motor;
  o `dev/garden.py` segura cada conta no seu teto ([fx.md](docs/arquitetura/fx.md),
  [comandos.md](docs/arquitetura/comandos.md)).
- As linhas dentro dos blocos `<style>` e `<script>` do `themes/ritmelli/index.html` não sobem: o teto
  `theme_inline_lines` do `dev/garden.py`.
- O PR que mexe na montagem (o `BUILD_PATHS` do `dev/testa_tudo.py`) só passa no "Testa o PR" com uma execução aprovada
  do "Monta o instalador" (`monta.yml`) no head: rode-o na branch (o "Verdict", provado pelo `dev/test_ci_workflow.py`).
  O `dev/test_monta_contract.py` exige os artefatos `Ritmelli-<versão>` e `ritmelli-exe-<versão>` em toda montagem, um
  job mostrado como `testa`, `testa-atualizador` e `testa-migracao` (ou com o sufixo de matriz, `nome (...)`) na
  montagem com a versão anterior, e o `testa-parcial` na que tem parcial: são o que a publicação procura
  ([dev.md](docs/arquitetura/dev.md#a-montagem)).

## O mapa: área, arquivos e teste

| Área | Arquivos | Teste (sem caminho, em `dev/`) |
| --- | --- | --- |
| Motor de áudio | `engine.py`, `sonoridade.py`, `transicao.py`, `batida.py` | `testa_ganho`, `testa_preabre`, `testa_congela`, `testa_microfone`, `testa_passagens`, `testa_passagem` (o motor de verdade, que usa o `batida.py`), `testa_transicao`, `test_stretch_outgoing` (o `esticar_saida` pela Rubber Band de verdade), `testa_anel`, `testa_ganchos`, `test_audio_imports` |
| Batidas e andamento | `compasso.py`, `andamento.py` | `test_compasso` (os pedaços da rede e os picos, com uma sessão falsa no lugar do modelo), `test_andamento` (a ordem das parecidas por andamento e artista) |
| Servidor e YouTube | `server.py`, `comandos.py`, `automatico.py`, `music.py` (as funções puras de música), `yt_fora.py`, `yt_erros.py` | `testa_comandos`, `testa_automatico`, `testa_adianta`, `testa_rapido`, `testa_vivo`, `testa_musica` |
| `--mock` | `server.py`, `pastas.py`, `dev/so_mock.py` (a trava que tira as ferramentas de `dev/` da 8799) | `testa_mock`, `testa_so_mock` |
| Gravação dos dados | `pastas.py` (`save_json`), o `grava_cfg` do `server.py` | `testa_grava` (o `save_json`), `test_grava_cfg` (o `grava_cfg` grava sob a trava, de várias threads) |
| Pasta protegida | `pastas.py` (`pasta_protegida`, `create_task`, `disarm`) e quem os chama (`microfone/microfone.py`, `atualizador.py`, `atualizacao.py`, `migra.py`) | `testa_pasta_protegida` (em memória; o `--disco` precisa de administrador e cria pasta em Program Files), `testa_mfx`, `testa_atualizador`, `testa_atualizacao`, `testa_migra` |
| A regra no setup | `instalador/protegida.ps1` | `testa_pasta_protegida --disco` (roda o `instalador/protegida.ps1` em cada caso e exige o mesmo veredito do `pastas.py`) |
| Pareamento e permissões | `pareamento.py`, `permissao.py`, o `guard` do `server.py` | `testa_pareamento`, `testa_mock`, `testa_protocolo` |
| Protocolo da sessão remota | `docs/protocolo-remoto.md`, `docs/protocolo-remoto/v1/` | `testa_protocolo` (`--gera` escreve as fixtures de novo) |
| Filtro e efeitos | `microfone/`, `fx.py`, `instalador/mudos.iss`, `winvol.py` | `testa_filtro`, `testa_mfx`, `testa_microfone`, `testa_anel`, `testa_aparelho_mudo` (os casos do setup de teste precisam do Inno Setup 6: sem ele, pulam no PC e reprovam no GitHub), `testa_voz` e `microfone/apo/teste/teste_reamostra.py` (este, o `testa_filtro`, o `testa_microfone` e o `testa_voz` precisam das DLLs do `microfone\apo\compila.bat teste`), `test_winvol` (o volume do microfone, com aparelhos falsos do Windows) |
| Troca de voz | `pistavoz.py`, `pista.py`, `conversor.py`, `vozes.json` | `testa_pedal_voz`, `testa_vozes`, `testa_pista`, `testa_conversor` |
| Atualizações | `atualizacao.py`, `atualizador.py`, `instalador/atualizacao/` | `testa_atualizacao`, `testa_atualizador` e `instalador/atualizacao/testa_parcial.py` |
| Textos | `i18n.py`, `themes/ritmelli/i18n/`, `gallery/i18n/` | `testa_i18n` |
| Dados de uso | `metricas.py` e o aviso deles no tema | `testa_metricas`; o aviso, `fitcheck.py --metricas` (sobe os próprios `--mock --metricas-teste`, sem rede) |
| Troca de nome | `migra.py` | `testa_migra` |
| Interface | `themes/ritmelli/` | `fitcheck.py`, `missing_script.py` e `theme_scripts.py` (o `--tela` do `testa_tudo` roda os três) contra o `--mock` |

## Antes do PR

Rode na raiz, com o venv: `$env:PYTHONUTF8 = '1'; python -m ruff check .; python dev\testa_tudo.py` (os outros modos e
onde entra teste novo: o [Contributing](README.md#contributing) do README). O check "Testa o PR" junta os jobs do
`testa.yml`: o `testes` roda o `dev/testa_tudo.py` sem os longos e o `dev/garden.py`, que também lê a descrição do PR (a
seção de prova); a mudança de print no `compara` só bloqueia com a etiqueta `extracao-tema`. A fila de merge da `main`
exige ele e o "Trusted author" (`dev/test_trusted_author.py`: PR de quem não é um dos dois mantenedores só passa
aprovado por um deles no head atual), e recusa PR com a etiqueta `needs-owner` (o passo "Verdict" do `testa.yml` e o
`dequeue-on-label.yml`, testados pelo `dev/test_needs_owner.py`). Como entrar na fila:
[dev.md](docs/arquitetura/dev.md#a-fila).
