# As ferramentas de `dev/`

As ferramentas de `dev/` que abrem o tema ou mandam comandos (o `shot`, o `fitcheck`, o
`perfcheck`, o `celular`, o `compara`, o `previews` e o `testa_mock`) só falam com um servidor
`--mock`, pelo `dev/so_mock.py` (só da biblioteca padrão): ele responde `"mock": true` no
`/api/state`, também no 401 do pareamento, e elas recusam a porta 8799, o servidor sem o
marcador e o redirecionamento para outra origem. Os medidores que abrem o anel de verdade
(`dev/mede_folga.py`, `dev/mede_voz_ao_vivo.py`) são manuais, num Windows de teste, e saem
antes de abrir o anel quando a 8799 aceita conexão.
O `dev/mede_esticamento.py` mede, com o `AnelFalso` num processo à parte e sem aparelho, se o
esticamento da passagem seca o anel do jogo, no processo do motor e num auxiliar abaixo do normal
(manual; o resultado de 25/11 está no `engine.md`).

O `dev/testa_tudo.py` roda os testes que não usam som, aparelho nem rede externa, quatro
por vez (os do `SERIAL`, que medem tempo, um a um e sozinhos, depois dos outros), pelas listas
dele: o `STDLIB` (que a `monta.yml` roda antes de instalar), o `COMPLETO`, o `LONG_TESTS` (os
dois testes longos, a banca das passagens, o `testa_passagem`, e o `test_capture`: o comando sem opção os
roda depois do `COMPLETO`; no `testa.yml`, o job de Testes roda o `--without-long`, e cada teste longo tem
um job próprio ao lado (a Banca, `--long bench`, e a Captura, `--long capture`)) e o `MICROFONE` (este sempre um a um; o job do filtro roda com o
Inno Setup, para o setup de teste do `testa_aparelho_mudo`). No `COMPLETO` e no `LONG_TESTS`, biblioteca
ou ffmpeg faltando é falha. Todo teste do `git ls-files`, de qualquer pasta (`test*.py`, `testa*.py`,
`teste*.py` e os `test*.ps1`; todo teste novo, em inglês, nasce `test_*`), tem destino: uma lista, um
passo próprio do `testa.yml` declarado no `PASSOS` (o `--passo disco` roda o
`testa_pasta_protegida --disco`), a linha do `PS1_TESTS` para um `.ps1` (o job, o passo, o comando e a
condição dele no `monta.yml`) ou, quando só roda à mão, o
comentário `# manual: <comando> precisa de <aparelho>` no topo, antes da docstring (o
`dev/bumbo.py` tem um). Antes de rodar, o `COMPLETO`, o `--long`, o `--so-stdlib` e o `--microfone`
falham com o teste sem destino, com o arquivo que tem o `manual:` e roda nos checks, e com o modo do
`REQUIRED_MODES` que saiu do check exigido: o job, o passo, o comando, o env ou a condição de cada um,
e os passos que a condição e o env leem pelo `id` (os do `SOURCE_STEPS`, fixados do mesmo jeito). O
`dev/test_ci_workflow.py` confere o que
nenhuma execução de PR exercita: o bloco do "Testa o PR" num bash com um `gh` falso (o comentário
que o GitHub não confirma reprova dizendo isso; no push, os jobs pulados só passam com uma
execução da fila aprovada no mesmo commit), os jobs que o push pula, as chaves de cache, essa trava
(com um mutante de cada modo), o leitor de YAML dos testes (o `dev/workflow_yaml.py`, só da biblioteca
padrão, que recusa o que não conhece), os gatilhos exatos do `testa.yml`, sem filtro de caminho nem
de branch, um job só com o nome "Testa o PR" em todos os workflows, nenhum passo dele com `if:` além
do "Cancelada", com um mutante de cada, e as bibliotecas sem versão no `instalador/travas.txt` (as conhecidas, da issue #231). O
`fitcheck` e o `compara` esperam o tema pela mesma função (o `wait_ready` do `dev/fitcheck.py`), que separa o
Chrome que caiu do tema que não ficou pronto e, no segundo caso, mostra cada condição, os erros da página e as
respostas com erro (o `Network.responseReceived`). O `dev/test_compara_not_ready.py` roda o `compara` com um sinal
de pronto que nunca fecha e confere o diagnóstico, no celular e na mesa; o `dev/test_fitcheck_ready.py` faz o mesmo
no `fitcheck` e confere o relógio do aviso dos dados de uso: os 6 s contam da resposta do `GET /api/state` da página
(o aviso só abre depois do estado), e não do `Page.navigate`. Com um script do tema ou o estado atrasados de propósito
o aviso ainda passa, também na reabertura depois do Esc (cada carga conta do estado dela), e um aviso que abre 8 s
depois do estado reprova. Todo servidor de teste que o `dev/so_mock.py` sobe nasce
suspenso num job do Windows (o que ele abrir fica no job) e recebe o `--stop-on-stdin-eof`: desliga quando o teste
fecha a entrada dele, sem pedido, e o papel do celular, que o `POST /api/shutdown` recusa, desliga do mesmo jeito.
Toda parada esvazia o job. Na parada pela entrada, o servidor que não sai em 10 s, sai com erro ou deixa processo
rodando reprova a parada dizendo isso; no último caso, a recusa diz o nome de cada processo que ainda rodava no job
quando o servidor parou e se ele ainda rodava depois da espera. Um `server.py` mais velho, sem a flag (a base de um `compara`), desliga
pelo `POST /api/shutdown`, só enquanto responde como `--mock`, e o job dele também sai vazio
(`dev/testa_so_mock.py`, `dev/test_mock_stop.py`). O `dev/test_capture.py` roda o `--capture` de verdade (os prints,
a chave e o `head_cache` que o workflow lê para salvar). O `dev/test_compara_push_steps.py` roda os
passos do Compara que, no push, capturam sem calcular as áreas nem resolver a base. O
`dev/test_release_workflow.py` lê os workflows e as ações locais como YAML: toda action fixada num
commit (as duas da SignPath no mesmo), o `sparse-checkout` de cada job da `monta.yml` com o que os
scripts dele leem, a conferência do recurso de versão das DLLs depois da montagem e no job do
filtro, com os nomes e a tabela de língua do `ritmelli.exe` (`ritmelli.spec`), e o Inno Setup só
pela ação `.github/actions/inno-setup`. O `dev/test_monta_contract.py` (no STDLIB, então a própria `monta.yml`
o roda antes de montar) exige os nomes da `monta.yml` que a esteira de publicação do `ritmelli-server` lê: o
`workflow_dispatch` com os inputs `notas` e `notas_en`, que chegam ao passo do manifesto; os jobs `testa`,
`testa-atualizador`, `testa-migracao` e `testa-parcial`, pelo nome que a API mostra, cada um rodando, com os
jobs de que depende, em toda montagem que a esteira espera (com e sem parcial, sempre com versão anterior; o
`testa-parcial`, só com parcial); o passo `congela`, cuja `versao` dá nome aos artefatos, e as saídas
`anterior` e `parcial` do job `monta`, que o `if:` do `testa-migracao` e o do `testa-parcial` leem, cada uma
vinda de um passo que a grava no `GITHUB_OUTPUT` (a `parcial`, pelo `Test-Path` do
`Ritmelli-$env:VERSAO-parcial.exe` na pasta do artefato, entre aspas duplas e com o `VERSAO` do `congela`,
atribuído uma vez a uma variável que o único comando `Add-Content` do `GITHUB_OUTPUT` com essa chave grava
depois como `parcial=`; toda chave das saídas tem uma gravação só); e os artefatos `Ritmelli-<versão>` (a
pasta que o passo do `publica.py` recebe no `--saida`) e `ritmelli-exe-<versão>` (um caminho só, sem curinga,
que termina no `ritmelli.exe`), cada um uma vez na execução inteira, contados como o server conta (sem o job
ou o passo desligado), e nenhum outro artefato que a esteira tomaria pela versão (`Ritmelli-1.2.3`), nem outro
`ritmelli-exe-` seguido de uma versão, nem um nome cuja expressão poderia completar um desses dois prefixos
(`${{ format('Ritmelli-{0}', …) }}`, `Rit${{ … }}`). Os dois artefatos (que também não podem sair de um job
que deixe de rodar numa dessas montagens), o `congela`, o passo do `publica.py` e os passos das saídas
`anterior` e `parcial` não podem ter `if:`, nenhum passo antes do `publica.py` o cita, e o que está em
comentário do PowerShell não conta (no `--saida`, um comentário também reprova, porque o server o lê cru). O
`--tela` junta o `fitcheck` e o `compara` do jeito do PR (no `testa.yml` o `compara` roda num job à parte,
pelo `--compara`, com a referência da base no cache do Actions), e o `--areas` é o filtro por caminho do
`.github/workflows/testa.yml`, que roda tudo isso em todo PR e na fila de merge. A fila leva a `main` ao mesmo
commit que testou, então o push na `main` roda só a captura do `compara` desse commit para o cache (o
`--capture`), e o "Testa o PR" do push reprova se nenhuma execução da fila passou nele. As bibliotecas da CI
se instalam com as versões do `instalador/travas.txt` (`-c`), que entra na chave do cache delas e na da
captura do `compara`, e o PR que muda esse arquivo dispara todas as áreas. No PR, só abrir, reabrir e um
commit novo rodam o check: editar a descrição ou mexer numa etiqueta não roda, porque uma execução no mesmo
commit vira a suite mais nova do workflow e o check exigido sai só dela (encobriria o "Testa o PR" de quem
testou). A etiqueta `extracao-tema` e a base nova de um PR empilhado valem na fila de merge, que testa o merge
de verdade; na entrada da fila, o `compara` compara com o commit de antes do PR, o da ref da entrada
(`pr-<número>-<commit>`). No PR, a etiqueta vale no próximo commit, ao reabrir ou num re-run completo, e a
base nova só no próximo commit ou ao reabrir (o re-run repete a base do evento antigo). A etiqueta
`needs-owner` (prova que pede ação física, como plugar ou desligar um aparelho, ou decisão do dono) também
vale na fila: o passo "Verdict" do "Testa o PR" relê as etiquetas do PR pela API na hora de decidir e reprova
a entrada da fila cujo PR a tem ou cujas etiquetas não vieram, e também a que tem uma `extracao-tema` que os
jobs da tela não viram; no PR ele só avisa da `needs-owner` no resumo. Uma dessas duas etiquetas posta num PR
que está na fila tira o PR dela (o `.github/workflows/dequeue-on-label.yml`, que confere antes se a etiqueta
segue no PR), menos o PR de um fork, cujo token só lê (a issue #255). O dono faz a prova, tira a etiqueta e
põe o PR na fila. O `dev/test_needs_owner.py` roda num bash com um `gh` falso o passo das etiquetas, o
"Verdict" e o do `dequeue-on-label.yml`, também com a lista que muda entre o job das etiquetas e o veredito. A
prova de um gatilho do `testa.yml` ou do nome do check exigido se faz no próprio PR (editar a descrição, pôr e
tirar uma etiqueta e passar pela fila, com o "Testa o PR" no head). O PR que mexe na montagem (o `BUILD_PATHS`
do `dev/testa_tudo.py`: `instalador/`, os `atualiza*.py`, o `migra.py`, o `pastas.py`, o
`microfone/microfone.py`, o `microfone/apo/`, o `ritmelli.spec`, a `monta.yml` e a ação do Inno Setup) só
passa no "Testa o PR" com uma execução aprovada do "Monta o instalador" no commit do head do PR: o `--areas`
do job do filtro diz `monta=true` (na fila, contra o commit de antes do PR na entrada, a `queue_base` do job
das etiquetas, como o `compara`), e o "Verdict" procura a execução pela API (na fila, no head do PR da
entrada). Sem ela, o veredito diz o comando (`gh workflow run monta.yml --ref <branch>`); quando a execução
passa, roda-se o job de novo. O `dev/test_ci_workflow.py` roda esse trecho com o `gh` falso e confere o
caminho da resposta, do `--areas` ao "Verdict".

O placar do jardim, o `dev/garden.py` (no `STDLIB`), conta o mato do repo: as linhas de comentário de cada
linguagem e as de docstring, as supressões, as esperas do app e as de `dev/`, os timers do tema, os retries, os
`except` largos, os testes pulados, as marcas de pendência, a prosa sem issue, os nomes sem ASCII, os acessos que o
`dev/testa_ganchos.py` conta (e as escritas diretas no estado do `App` e do motor), as linhas inline do tema, as linhas dos arquivos grandes e do `AGENTS.md` e as regras
dele sem verificação. Cada número tem um teto no `dev/garden.json`: acima dele, ou abaixo sem o teto descer junto, o
check reprova, e o teto do PR nunca passa o da base (o `$env:BASE` no PR; na fila, o commit sobre o qual a entrada
foi montada, que vem no nome da ref dela, como no `compara`). Uma base sem `dev/garden.json` é medida. Cada contador
que mudou vai para o resumo do PR numa linha `-- summary:`, e o `--list <contador>` mostra onde está cada item. O passo "PR description" do job de
Testes lê a descrição do PR pela API, no PR e na fila (que pega a edição depois do verde), e reprova sem a seção de
prova ou com uma frase de justificativa sem link de issue. O `dev/test_garden.py` tem, por contador, um caso que
sobe e um que não conta.

`dev/shot.py` (print + erros de console pelo Chrome headless), `dev/fitcheck.py` (gate
de "cabe em qualquer tela", de 1024x600 a 2560x1300, no celular em pé e no celular grande
deitado; uma exceção ou um `console.error` da página também reprova; com `--metricas`, sem url, confere o aviso dos
dados de uso: sobe um `--mock --metricas-teste` por situação e por botão pelo `sobe_servidor` do `compara`, que
aceita o `config.json`, argumentos e variáveis a mais, com a rede presa num proxy de armadilha), `dev/compara.py` (gate
de "a tela não mudou", no celular e na mesa do PC, a 1920x1080: prints do tema em estados fixos,
com uma prateleira de mentira e o servidor em `--mock`, comparados pixel a pixel com os de
referência gravados antes da mudança, também de outro checkout pelo `--raiz`; sai 2 se um
print mudou e 1 se a captura não vale; o tema que não fica pronto no prazo imprime cada condição do sinal de pronto, o que ainda carrega, os erros do console e um print em `<pasta>/nao-pronto`; a pasta temporária do servidor sai mesmo quando ele recusa
subir ou o desligar dele falha), `dev/perfcheck.py`
(quanto o tema redesenha por segundo com música tocando, no celular emulado),
`dev/celular.py` (mede rolagem, puxão e abrir do palco no Chrome do celular de verdade,
por USB com adb; o emulado não reproduz o que trava lá; num `--mock --papel-local celular`, a aba pareia como o
celular, com o código lido pelo lado do PC, e é desconectada no fim), `dev/bumbo.py` (confere se a passagem
no tempo de um par da prateleira pôs bumbo em cima de bumbo e não no contratempo, com um
detector de bumbo próprio, o `dev/bumbo_mede.py`, que o `dev/testa_passagem.py` também usa; no final seco para um começo sem bumbo, confere a primeira nota
contra o bumbo do que sai: sai 0 no tempo, 1 contratempo ou fora, 3 sem plano ou sem bumbo), `dev/texturas.py` (gera as
texturas de ruído do tema em WebP a partir dos SVGs que moram nele), `dev/molduras.py`
(desenha as molduras de pixel do tema, contorno, linha clara, bisel e cantos em degrau, e
grava as variáveis `--mold-*` de border-image no `themes/ritmelli/gerado/molduras.css`, o arquivo inteiro, que o
tema carrega fora do bloco do celular, porque valem nas duas telas, com o tamanho do ponto na variável `--px`, 1px
quando o tema não a define, e no bloco `molduras:inicio` do `gallery/index.html` as que a galeria usa),
`dev/compactos.py` (desenha em pixel os compactos dos Sons rápidos, em duas
camadas paradas em volta do selo que gira, e grava as variáveis `--compacto-*` no
`themes/ritmelli/gerado/compactos.css`, o arquivo inteiro, que o tema carrega fora do bloco do celular),
`dev/pecas.py` (desenha em pixel o braço do toca-discos, já inclinado em seis ângulos, a
base e o descanso dele, os botões de tocar do palco e do mini player e o pisador, os knobs e
o LED dos pedais, a chave 110/220 do fim do disco, o trilho e o cursor das barras de tempo e volume (os da chave de correr que ela substituiu) e o salvar da parecida no prato, e grava as
variáveis `--braco-*`, `--tocar-*`, `--icone-*`, `--knob-margem` e `--led-recuo` no
`themes/ritmelli/gerado/pecas.css`, que o tema carrega fora do bloco do celular, e a `PE_SVG`, a `LED_SVG`, os `KNOBS`, a
`CHAVE_PARECIDAS` e o `SALVAR_PIXEL` no `themes/ritmelli/gerado/pecas.js`, que o tema carrega antes do script principal;
os dois arquivos inteiros) e `dev/previews.py` (gera o preview de cada tema para a galeria, um `preview_<lingua>.png` por língua no tema com textos e um `preview.png` no que não tem, com a prateleira de mentira do
`dev/compara.py`; ele entra no git porque o instalador leva a pasta do tema como ela está).
