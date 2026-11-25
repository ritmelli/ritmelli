# AGENTS.md

O que vale para quem muda o código do Ritmelli e que o código não diz sozinho. Como cada peça funciona:
[docs/ARQUITETURA.md](docs/ARQUITETURA.md). O contrato entre o servidor e a interface: [API.md](API.md). Instalar,
rodar e contribuir: [README.md](README.md). Código, comentários e commits em português do Brasil; issues e PRs em
português ou inglês.

## Onde testar

- Nunca no 8799, no Ritmelli instalado nem com o microfone de verdade: o som sai no jogo de quem está jogando. O
  servidor de teste é o `--mock` noutra porta, que por padrão trabalha numa pasta temporária, só com uma cópia da
  lista da prateleira:
  `python server.py --mock --port 8801 --no-browser`.
- Nunca no Discord de quem usa; só num canal fechado de teste e num Windows de teste.
- O `microfone\microfone.py instala-todos` e o `remove` mexem em todo microfone do PC e no filtro do Ritmelli
  instalado: só num Windows de teste.

## Regras

- Nada pesado no processo do áudio: o bloco é de 10 ms, e o que segura o interpretador estala o som no jogo. Biblioteca
  lenta ou conta longa vai para um processo auxiliar, como o `yt_fora.py` (`ritmelli.py --yt`) e o `andamento.py`
  (`ritmelli.py --andamento`), que o servidor abre pelo `auxiliar` do `server.py`.
- O anel tem dois lados: o `microfone/apo/anel.h` e o espelho dele em ctypes no `microfone/injeta.py`. Mudou o layout,
  muda nos dois e sobe o `MICFX_VERSAO` e o nome do mapa (`MICFX_MAPA`): a versão velha pode estar viva no `audiodg`
  durante a troca.
- Efeito de voz: as configurações moram no `fx.py`, e o `microfone/preset.py` as leva ao motor em C++. Etapa nova
  precisa do par no `microfone/apo/voz.h` (o `dev/testa_voz.py` falha sem ele).
- Todo texto novo da interface nas duas línguas: `themes/ritmelli/i18n/i18n_en.properties` e `i18n_pt_BR.properties`,
  com as mesmas chaves na mesma ordem, e os da galeria em `gallery/i18n/`. O servidor não escreve frase para a tela:
  manda a Mensagem do `i18n.msg`, com uma chave `server.*`. Log e erro técnico ficam em inglês.
- Rota nova do `server.py`: quem pode chamar cada uma é a tabela do `permissao.py`, que o `guard` confere. Rota fora
  da tabela é só do PC, e o `dev/testa_mock.py` falha enquanto ela não entra; abrir para o celular ou para o remoto é
  decisão escrita no PR. Rota ou campo novo entra no `API.md`, e a linha da tabela também.
- O `engine.py` não ganha gancho novo para o módulo opcional de fora do repo: o que ele precisa passa pelo que já
  existe ([fx.md](docs/arquitetura/fx.md)), e o `dev/testa_ganchos.py` falha com um a mais.
- Mudou uma peça, muda o arquivo dela em `docs/arquitetura/`.

## As superfícies de uma mudança

Toda mudança tem de cobrir as que toca, e o PR diz quais:

- o servidor (`server.py`) e o contrato no `API.md`;
- o tema no PC e no celular: o mesmo `themes/ritmelli/index.html`, com o layout do celular abaixo de 900 px;
- i18n: os textos nas duas línguas;
- o filtro (`microfone/`);
- o instalador (`instalador/ritmelli.iss`) e a migração de quem já tem o app (`migra.py`);
- a galeria (`gallery/index.html`, com os previews do `dev/previews.py`).

## O mapa: área, arquivos e teste

| Área | Arquivos | Teste (sem caminho, em `dev/`) |
| --- | --- | --- |
| Motor de áudio | `engine.py`, `sonoridade.py` | `testa_ganho`, `testa_preabre`, `testa_congela`, `testa_microfone`, `testa_passagens`, `testa_anel`, `testa_ganchos` |
| Servidor e YouTube | `server.py`, `comandos.py`, `yt_fora.py`, `yt_erros.py` | `testa_comandos`, `testa_adianta`, `testa_rapido`, `testa_vivo`, `testa_musica` |
| `--mock` | `server.py`, `pastas.py` | `testa_mock` |
| Gravação dos dados | `pastas.py` (`save_json`), o `grava_cfg` do `server.py` | `testa_grava` |
| Pasta protegida | `pastas.py` (`pasta_protegida`), `instalador/protegida.ps1` e quem os chama (`microfone/microfone.py`, `atualizador.py`, `atualizacao.py`, `migra.py`, `instalador/ritmelli.iss`) | `testa_pasta_protegida` (em memória; o `--disco` precisa de administrador e cria pasta em Program Files: só num Windows de teste), `testa_mfx`, `testa_atualizador`, `testa_atualizacao`, `testa_migra` |
| Pareamento e permissões | `pareamento.py`, `permissao.py`, o `guard` do `server.py` | `testa_pareamento`, `testa_mock` |
| Filtro e efeitos | `microfone/`, `fx.py` | `testa_filtro`, `testa_mfx`, `testa_microfone`, `testa_anel`, `testa_voz` e `microfone/apo/teste/teste_reamostra.py` |
| Troca de voz | `pistavoz.py`, `pista.py`, `conversor.py`, `vozes.json` | `testa_pedal_voz`, `testa_vozes`, `testa_pista`, `testa_conversor` |
| Atualizações | `atualizacao.py`, `atualizador.py`, `instalador/atualizacao/` | `testa_atualizacao`, `testa_atualizador` e `instalador/atualizacao/testa_parcial.py` |
| Textos | `i18n.py`, `themes/ritmelli/i18n/`, `gallery/i18n/` | `testa_i18n` |
| Dados de uso | `metricas.py` | `testa_metricas` |
| Troca de nome | `migra.py` | `testa_migra` |
| Interface | `themes/ritmelli/`, `gallery/` | `fitcheck.py` contra o `--mock`; mudou as boas-vindas, também com `--boas-vindas`, num `--mock` com `--data-dir` novo e um `library.json` com `[]` |
| Sem teste | `batida.py`, `compasso.py`, `andamento.py`, `janela.py`, `winvol.py` | o PR diz como conferiu |

O `testa_filtro`, o `testa_microfone`, o `testa_voz` e o `teste_reamostra.py` precisam das DLLs do
`microfone\apo\compila.bat teste`, com o Ritmelli desligado (`--mock` incluído, que segura o `voz.dll`).

## Antes do PR

Todo PR roda o `.github/workflows/testa.yml`, e o check "Testa o PR" só passa com tudo verde: o ruff do
`pyproject.toml` (só as regras que pegam erro), o `dev/testa_tudo.py` e, quando o PR mexe na área deles, os testes do
filtro e a tela (o `fitcheck` nas duas línguas e o `compara` contra a base). O resumo sai num comentário do PR. Rode o
mesmo antes, na raiz do repo, com o venv:

```powershell
$env:PYTHONUTF8 = '1'; python -m ruff check .; python dev\testa_tudo.py
```

O `--microfone` roda os do filtro (depois do `microfone\apo\compila.bat teste`), o `--tela --base origin/main` a tela
e o `--so-stdlib` só os da biblioteca padrão, que a `monta.yml` (só à mão) roda antes de montar. Teste novo de `dev/`
entra numa lista do `testa_tudo.py`, sem som, aparelho nem rede externa, ou o `testa_tudo` falha.
