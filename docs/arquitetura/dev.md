# As ferramentas de `dev/`

As ferramentas de `dev/` que abrem o tema ou mandam comandos (o `shot`, o `fitcheck`, o
`perfcheck`, o `celular`, o `compara`, o `previews` e o `testa_mock`) só falam com um servidor
`--mock`, pelo `dev/so_mock.py` (só da biblioteca padrão): ele responde `"mock": true` no
`/api/state`, também no 401 do pareamento, e elas recusam a porta 8799, o servidor sem o
marcador e o redirecionamento para outra origem. Os medidores que abrem o anel de verdade
(`dev/mede_folga.py`, `dev/mede_voz_ao_vivo.py`) são manuais, num Windows de teste, e saem
antes de abrir o anel quando a 8799 aceita conexão.

O `dev/testa_tudo.py` roda os testes que não usam som, aparelho nem rede externa, um por
vez, pelas listas dele: o `STDLIB` (que a `monta.yml` roda antes de instalar), o `COMPLETO` e
o `MICROFONE`. No `COMPLETO`, biblioteca ou ffmpeg faltando é falha, e teste de `dev/` fora
das listas também. O `--tela` junta o `fitcheck` e o `compara` do jeito do PR, e o `--areas`
é o filtro por caminho do `.github/workflows/testa.yml`, que roda tudo isso em todo PR.

`dev/shot.py` (print + erros de console pelo Chrome headless), `dev/fitcheck.py` (gate
de "cabe em qualquer tela", de 1024x600 a 2560x1300, no celular em pé e no celular grande
deitado; uma exceção ou um `console.error` da página também reprova), `dev/compara.py` (gate
de "a tela não mudou", no celular e na mesa do PC, a 1920x1080: prints do tema em estados fixos,
com uma prateleira de mentira e o servidor em `--mock`, comparados pixel a pixel com os de
referência gravados antes da mudança, também de outro checkout pelo `--raiz`; sai 2 se um
print mudou e 1 se a captura não vale), `dev/perfcheck.py`
(quanto o tema redesenha por segundo com música tocando, no celular emulado),
`dev/celular.py` (mede rolagem, puxão e abrir do palco no Chrome do celular de verdade,
por USB com adb; o emulado não reproduz o que trava lá), `dev/bumbo.py` (confere se a passagem
no tempo de um par da prateleira pôs bumbo em cima de bumbo e não no contratempo, com um
detector de bumbo próprio; no final seco para um começo sem bumbo, confere a primeira nota
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
tema, fora do bloco do celular, e no JS a `PE_SVG`, a `LED_SVG`, os `KNOBS`, a `CHAVE_PARECIDAS` e o `SALVAR_PIXEL`) e `dev/previews.py` (gera o preview de cada tema para a galeria, um `preview_<lingua>.png` por língua no tema com textos e um `preview.png` no que não tem, com a prateleira de mentira do
`dev/compara.py`; ele entra no git porque o instalador leva a pasta do tema como ela está).
