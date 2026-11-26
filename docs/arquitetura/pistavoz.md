# O pedal de troca de voz (`pistavoz.py`, `pista.py`, `conversor.py`)

O pedal de troca de voz (#129): o `pistavoz.py` é o módulo dele. O `fx.py` põe o pedal "Troca de voz" no lugar do
alienígena, o `/api/effects` leva as vozes, o Estado leva o `pedal_voz` e o `POST /api/pedal_voz` troca a voz (o
contrato no API.md, "Pedal de troca de voz"). Com o pedal ligado, o módulo sobe o processo da troca de voz
(`ritmelli.py --pistavoz`, o `pista.py`): ele lê a voz crua pelo anel, junta blocos de 80 ms, converte pelo
`conversor.py` numa thread só da conta e escreve na pista da voz, com 120 ms de silêncio na frente da primeira voz
contra um bloco que demora. O `conversor.py` é o RVC refeito em numpy e ONNX Runtime (DirectML na placa de vídeo):
ContentVec e FCPE numa janela curta, o conteúdo e o tom de cada quadro congelados a 200 ms do futuro, o enc_p
sobre a frase atual e o decodificador numa janela local, com o ruído de cada instante fixo e a fase da fonte
continuada, para dois blocos seguidos gerarem a mesma onda no trecho em comum; a saída segue o volume de quem fala.
O atraso do efeito é o bloco mais os 300 ms de futuro que o modelo vê. Os modelos são os do ritmelli-voices, nas
releases que o `vozes.json` fixa (tamanho e sha256 de cada arquivo), na pasta `vozes\` do app: o instalador baixa no
clique de Instalar, antes de mexer em qualquer coisa, e só o que ainda não está lá com o hash certo
(`instalador/vozes_iss.py`, o `[Code]` do `ritmelli.iss`). Quando o app muda de pasta, o arquivo que a instalação
anterior já tem vem dela, e não do GitHub: a cópia vai para a pasta temporária do setup e o sha256 se confere nela
(a pasta anterior pode não ser protegida), e o arquivo que não confere ou que não se deixa copiar é baixado; um
erro ao ler a cópia vai para o log e para o setup, como um download que falha; pelo código, `python dev/vozes.py baixa`. Sem placa de vídeo
(pelo DXGI, sem os adaptadores do próprio Windows: o de software e os do fabricante Microsoft, o `de_verdade()`) ou
sem os modelos, o `impedimento()` deixa o pedal de fora e o Alienígena fica. O tom: o deslocamento leva o tom de quem fala (o percentil 20 dos quadros com tom) ao `tom_hz` do `voz.json`
da voz. Sem ele medido, o `pista.py` sobe no ajuste: escreve silêncio na pista enquanto junta 8 s de fala pelo tom
dos quadros que o `conversor.py` congela a cada bloco (o `tom_congelado`, a conta que ele já faz), diz o `ouvindo` e
o `medido` pela saída padrão e passa ao deslocamento medido (`ajusta_tom`, com a linha do tempo zerada). O
`pistavoz.py` põe isso no visor e guarda o tom de quem fala no `pedal_voz.json` da pasta de dados, com a voz
escolhida. No `--mock` o pedal não liga.
A subida do pedal e as secas do anel da música (#137), no `dryouts.py`: o `VoicePedalStart` do motor guarda quando o
pedal ligou (o `_pedal_voz_liga` conta) e quando a pista da voz ligou. Essa hora vem do próprio processo da voz: o
`pista_liga` do `microfone/injeta.py` escreve a hora de quando ligou, em milissegundos do `time.monotonic` (o mesmo
relógio nos dois processos, no Windows), no `pista_ligou_ms` do anel, como 1 mais o resto por 2³² − 1, para o zero ficar
sendo "sem carimbo" sem tirar uma hora da conta (o campo de 32 bits ao lado do `pista_ligada`, o mesmo lugar e tamanho
do antigo `pista_reservado`, que ninguém lia: o layout não muda; cada escritor carimba a própria subida, mesmo com a
pista ainda ligada no anel por um processo da voz derrubado, #288), e o `Injetor`, a cada carimbo novo, refaz a hora
dele com uma leitura só do relógio, depois de ler o carimbo; assim uma pista que ligou enquanto a thread do anel estava
parada sai com a hora certa, e cada carimbo novo conta como uma subida, com a pista viva ou não (a pista desligou e
religou, ou ligou e desligou, sem a thread ver); com um carimbo válido, só ele decide, e não a pista ficar viva. Com o
pedal subindo, a subida da pista sai no log uma vez, com quanto tempo depois do pedal ela veio, também quando o carimbo
só é lido depois de o pedal desligar, ou de desligar e ligar de novo, se a pista subiu antes disso (a linha é da subida
em que ela subiu). O `RingDryOuts` do `Injetor` conta cada seca entre o pedal ligar e `AFTER_TRACK_S` depois de a pista
ligar no `secas_pedal` do `/api/state` e a põe no log com quanto tempo depois do pedal e da pista ela veio e entre
quanto e quanto depois de o pedal ligar o anel secou (arredondado para fora: o limite de baixo para baixo e o de cima
para cima; a seca só é vista quando a thread volta, e o anel secou entre a última leitura que o viu com algo e a que o
viu vazio: o `read_ring` guarda a hora de antes da primeira e a de depois da segunda, e não o que o anel guardava,
porque o leitor pode parar e só esvaziá-lo depois; a pista que subiu antes desse intervalo veio antes da seca, a que
subiu depois dele veio depois, a que subiu dentro dele fica sem ordem, o pedal que ligou depois dele não conta no
`secas_pedal`, o que ligou dentro dele sai com a nota de que pode ter ligado depois da seca, o que desligou dentro dele
conta com a subida que acabou e com a pista dela, com a nota de que pode ter desligado antes da seca, e a janela dos
`AFTER_TRACK_S` vale para o começo desse intervalo, e não para a volta da thread; a pista é lida de novo quando a seca
aparece, para um carimbo que chegou na mesma volta (só para a conta: a mistura da volta segue com o que o `_voz` leu)),
até `PEDAL_LINES` linhas por subida do pedal (passou disso, a seca sai como as outras, uma linha a cada `QUIET_S`, e a
conta segue; o `secas`, o `secas_pedal` e o `volta_max_ms` do `/api/state` saem juntos, logo depois de a seca ser
classificada (antes de o anel ser enchido de novo) e no fim de cada volta). As linhas não saem da thread do anel: vão
para uma fila de `LOG_LINES` lidas por uma thread só do log, e com a fila cheia, ou com a escrita falhando, a linha se
perde e a thread do anel não espera (a próxima linha escrita diz quantas se perderam antes dela); a thread do log nasce
com ele, e não na primeira linha. O `dev/testa_anel.py` confere isso com um produtor de verdade (o `injeta.Microfone`
que o `pista.py` usa), uma seca que o próprio teste faz acontecer, a thread do anel parada quando o teste quer e o
relógio dele, e o `dev/testa_pedal_voz.py` confere o que o motor guarda quando o pedal liga e desliga. O
`dev/measure_voice_pedal.py` mede isso de verdade (manual: o microfone com o filtro, a placa de vídeo e os modelos, com
o Ritmelli desligado), num servidor de verdade deste checkout, numa porta dele e com dados temporários, e só com o
runtime do app (o `onnxruntime-directml`): sem o `DmlExecutionProvider`, ou com uma versão que não é a que o
`instalador/travas.txt` trava, ele se recusa a rodar antes de abrir qualquer coisa, a não ser com `--provider cpu`;
`--cycles` menor que 1 e um `--on-s` que não é um número positivo também são recusados, e o resultado leva a versão que
rodou e só as linhas de seca entre o primeiro e o último corte (pelo total que cada uma diz); uma voz que não está no
`vozes.json` também é recusada antes. Cada ciclo, com o pedal ligado por `--on-s` segundos, precisa da voz de verdade (o
processo da voz disse `pronto`, sem `erro`, e o `fim` do log dele tem blocos e, com `--provider dml`, as quatro sessões
no DirectML: o `fim` traz o `Conversor.providers()`), da linha da subida da pista no log do servidor (o tempo dela entra
na linha do ciclo, e o resultado dá o mais lento, `slowest_track_up_s`), de um stream de estado só, aberto depois de
escolher o microfone, que dá a base e os estados de todos os ciclos: cada `tick` leva a hora da captura da volta dele
(`t`, o `time.monotonic` do servidor, o mesmo relógio da ferramenta, que sobe o servidor com o próprio Python), e o
`state` de uma volta vem logo antes do `tick` dela, então cada state tem a hora da volta; uma janela do ciclo leva as
voltas até a primeira do fim dela em diante, que fecha a janela com o que traz, e a seguinte começa depois dela, então
cada volta é de uma janela só, não importa quanto a ferramenta atrasou para ler; o fim do ciclo é o último state da
janela; o `tick` leva também o número da volta (`n`), e um salto nele (a conexão que ficou para trás pula para a volta
mais nova) para a medição, porque um state do meio pode ter mostrado o anel quebrado; o stream que fecha para a medição,
de um anel que mediu a folga e de um anel sem interrupção (leitor o tempo todo, o mesmo microfone, e contadores que não
voltam, o que pega um `Injetor` aberto de novo), ou a medição para e diz qual ciclo. O `dev/test_measure_voice_pedal.py`
confere a recusa e a linha de cada ciclo. Testes: `python dev/testa_pedal_voz.py` (o contrato, com um módulo falso),
`python dev/testa_vozes.py` (o `vozes.json`, o que o instalador baixa e o `impedimento()`), `python dev/testa_pista.py`
(o processo contra um anel falso; com `RITMELLI_VOZES_TESTE=1`, também com os modelos de verdade) e
`python dev/testa_conversor.py` (o motor com modelos de mentira no processador: o tom deslocado, a onda sem degrau entre
blocos, o `ajusta_tom` e o silêncio). O motor e o `compasso.py` desligam a telemetria do ONNX Runtime (ver o
PRIVACIDADE.md), e os termos da DirectML vão no TERCEIROS pelo `instalador/terceiros.py`.
