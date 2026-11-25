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
dele: o `STDLIB` (que a `monta.yml` roda antes de instalar), o `COMPLETO` e o `MICROFONE` (este
sempre um a um; o job do filtro roda com o Inno Setup, para o setup de teste do
`testa_aparelho_mudo`). No `COMPLETO`, biblioteca ou ffmpeg faltando é falha. Todo `dev/testa_*.py`
tem destino: uma lista, um passo próprio do `testa.yml` declarado no `PASSOS` (o `--passo disco`
roda o `testa_pasta_protegida --disco`) ou, quando só roda à mão, o comentário `# manual:
<comando> precisa de <aparelho>` no topo, antes da docstring (o `dev/bumbo.py` tem um). Antes de
rodar, o `COMPLETO`, o `--so-stdlib` e o `--microfone` falham com o teste sem destino, com o
arquivo de `dev/` que tem o `manual:` e roda no check, e com o modo do `testa_tudo` que o
`testa.yml` deixou de chamar. O `--tela` junta o `fitcheck` e o `compara` do jeito do PR (no
`testa.yml` o `compara` roda num job à parte, pelo `--compara`, com a referência da base no
cache do Actions), e o `--areas` é o filtro por caminho do `.github/workflows/testa.yml`, que
roda tudo isso em todo PR, no push na `main` e na fila de merge. No PR, só abrir, reabrir e
um commit novo rodam o check: editar a descrição ou mexer numa etiqueta não roda, porque uma
execução no mesmo commit vira a suite mais nova do workflow e o check exigido sai só dela
(encobriria o "Testa o PR" de quem testou). A etiqueta `extracao-tema` e a base nova de um PR
empilhado valem na fila de merge, que lê as etiquetas na hora e testa o merge de verdade; no
PR, a etiqueta vale no próximo commit, ao reabrir ou num re-run completo, e a base nova só no
próximo commit ou ao reabrir (o re-run repete a base do evento antigo).
A etiqueta `needs-owner` (prova fora da CI: o filtro num Windows real, o instalador de verdade, um
gatilho do `testa.yml` ou o nome do check exigido) também vale na fila: o passo "Needs owner" do
"Testa o PR" lê a lista do job das etiquetas e reprova a entrada da fila cujo PR a tem, ou cujas
etiquetas não vieram; no PR ele só avisa no resumo, e o merge fica com o dono. O
`dev/test_needs_owner.py` roda esse passo, fora do GitHub, em cada caso, e confere os gatilhos e o
nome do check exigido.

`dev/shot.py` (print + erros de console pelo Chrome headless), `dev/fitcheck.py` (gate
de "cabe em qualquer tela", de 1024x600 a 2560x1300, no celular em pé e no celular grande
deitado; uma exceção ou um `console.error` da página também reprova; com `--metricas`, sem url, confere o aviso dos
dados de uso: sobe um `--mock --metricas-teste` por situação e por botão pelo `sobe_servidor` do `compara`, que
aceita o `config.json`, argumentos e variáveis a mais, com a rede presa num proxy de armadilha), `dev/compara.py` (gate
de "a tela não mudou", no celular e na mesa do PC, a 1920x1080: prints do tema em estados fixos,
com uma prateleira de mentira e o servidor em `--mock`, comparados pixel a pixel com os de
referência gravados antes da mudança, também de outro checkout pelo `--raiz`; sai 2 se um
print mudou e 1 se a captura não vale), `dev/perfcheck.py`
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
