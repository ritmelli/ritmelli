# O pedal de troca de voz (`pistavoz.py`, `pista.py`, `conversor.py`)

O pedal de troca de voz (#129): o `pistavoz.py` é o módulo dele. O `fx.py` põe o pedal "Troca de voz" no lugar do
alienígena, o `/api/effects` leva as vozes, o Estado leva o `pedal_voz` e o `POST /api/pedal_voz` troca a voz (o
contrato no API.md, "Pedal de troca de voz"). Com o pedal ligado, o módulo sobe o processo da troca de voz
(`ritmelli.py --pistavoz`, o `pista.py`): ele lê a voz crua pelo anel, junta blocos de 80 ms, converte pelo
`conversor.py` numa thread só da conta e escreve na pista da voz, com 120 ms de silêncio na frente da primeira voz
contra um bloco que demora. O `conversor.py` é o RVC refeito em numpy e ONNX Runtime (DirectML na placa de vídeo):
ContentVec e FCPE numa janela curta, o conteúdo e o tom de cada quadro congelados a 200 ms do futuro, o enc_p sobre a
frase atual e o decodificador numa janela local, com o ruído de cada instante fixo e a fase da fonte continuada, para
dois blocos seguidos gerarem a mesma onda no trecho em comum; a saída segue o volume de quem fala. O atraso do efeito é
o bloco mais os 300 ms de futuro que o modelo vê. Os modelos são os do ritmelli-voices, nas releases que o `vozes.json`
fixa (tamanho e sha256 de cada arquivo), na pasta `vozes\` do app: o instalador baixa no clique de Instalar, antes de
mexer em qualquer coisa, e só o que ainda não está lá com o hash certo (`instalador/vozes_iss.py`, o `[Code]` do
`ritmelli.iss`). Quando o app muda de pasta, o arquivo que a instalação anterior já tem vem dela, e não do GitHub: a
cópia vai para a pasta temporária do setup e o sha256 se confere nela (a pasta anterior pode não ser protegida), e o
arquivo que não confere ou que não se deixa copiar é baixado; um erro ao ler a cópia vai para o log e para o setup, como
um download que falha; pelo código, `python dev/vozes.py baixa`. Sem placa de vídeo (pelo DXGI, sem os adaptadores do
próprio Windows: o de software e os do fabricante Microsoft, o `de_verdade()`) ou sem os modelos, o `impedimento()`
deixa o pedal de fora e o Alienígena fica. O tom: o deslocamento leva o tom de quem fala (o percentil 20 dos quadros com
tom) ao `tom_hz` do `voz.json` da voz. Sem ele medido, o `pista.py` sobe no ajuste: escreve silêncio na pista enquanto
junta 8 s de fala pelo tom dos quadros que o `conversor.py` congela a cada bloco (o `tom_congelado`, a conta que ele já
faz), diz o `ouvindo` e o `medido` pela saída padrão e passa ao deslocamento medido (`ajusta_tom`, com a linha do tempo
zerada). O `pistavoz.py` põe isso no visor e guarda o tom de quem fala no `pedal_voz.json` da pasta de dados, com a voz
escolhida. No `--mock` o pedal não liga. A subida do pedal e as secas do anel da música (#137), no `dryouts.py`: o
`VoicePedalStart` do motor guarda quando o pedal ligou (o `_pedal_voz_liga` conta) e quando a pista da voz ligou. Essa
hora vem do próprio processo da voz: o `pista_liga` do `microfone/injeta.py` escreve a hora de quando ligou, em
milissegundos do `time.monotonic` (o mesmo relógio nos dois processos, no Windows), no `pista_ligou_ms` do anel, como 1
mais o resto por 2³² − 1, para o zero ficar sendo "sem carimbo" sem tirar uma hora da conta (o campo de 32 bits ao lado
do `pista_ligada`, o mesmo lugar e tamanho do antigo `pista_reservado`, que ninguém lia: o layout não muda; cada
escritor carimba a própria subida, mesmo com a pista ainda ligada no anel por um processo da voz derrubado, #288; no
`Anel` do `injeta.py` os dois são um campo só, o `pista_estado` de 64 bits (o bit baixo é a pista ligada, os 32 de cima
o carimbo), que o produtor, o único que os escreve, troca inteiro: a pista liga junto com o carimbo, e desligar zera só
o bit; o `anel.h` segue com as duas metades, e o filtro só lê o `pista_ligada`), cada subida guarda a pista como um
intervalo, do carimbo (que tem a resolução do milissegundo, então o intervalo começa meio milissegundo antes dele, e
nunca depois da leitura que o vê) até a hora em que a thread do anel vê o carimbo novo, e a ordem da pista com a seca só
sai quando o intervalo inteiro fica de um lado dela (a pista vista na mesma hora da última leitura com algo fica sem
ordem, porque o relógio pode não separar as duas); as linhas arredondam o intervalo para fora, o limite de baixo para
baixo e o de cima para cima, e a ferramenta lê esses limites, que sempre contêm a hora em que a pista subiu; e o
`Injetor`, a cada carimbo novo, refaz a hora dele com uma leitura só do relógio, depois de ler o carimbo; assim uma
pista que ligou enquanto a thread do anel estava parada sai com a hora certa, e cada carimbo novo conta como uma subida,
com a pista viva ou não (a pista desligou e religou, ou ligou e desligou, sem a thread ver); só o carimbo decide, e não
a pista ficar viva: uma pista sem carimbo não conta como subida. Com o pedal subindo, a subida da pista sai no log uma
vez, com quanto tempo depois do pedal ela veio (com a nota de que pode ter subido depois de o pedal desligar, quando a
thread do anel só a vê mais de uma folga depois dele), também quando o carimbo só é lido depois de o pedal desligar, ou
de desligar e ligar de novo, se a pista subiu antes disso (a linha é da subida em que ela subiu). O `RingDryOuts` do
`Injetor` conta cada seca entre o pedal ligar e `AFTER_TRACK_S` depois de a pista ligar (contados até a última leitura
com algo, ou, sem ela, até a que viu o anel vazio, e não até a thread voltar; a seca só fica de fora com o intervalo
inteiro da subida antes da janela, e a que só o carimbo deixa de fora conta, com a nota de que a pista pode ter subido
mais de `AFTER_TRACK_S` antes) no `secas_pedal` do `/api/state` e a põe no log com quanto tempo depois do pedal e da
pista ela veio e entre quanto e quanto depois de o pedal ligar o anel secou (arredondado para fora: o limite de baixo
para baixo e o de cima para cima; a seca só é vista quando a thread volta, e o anel secou entre a última leitura que o
viu com algo e a que o viu vazio: o `read_ring` guarda a hora de antes da primeira e a de depois da segunda, e não o que
o anel guardava, porque o leitor pode parar e só esvaziá-lo depois (quando os leitores mudam, a última leitura com algo
some, porque era dos leitores de antes); a pista que subiu antes desse intervalo veio antes da seca, a que subiu depois
dele veio depois, a que subiu dentro dele fica sem ordem (sem leitura com algo, o intervalo não tem começo: toda pista
até o vazio fica sem ordem, e todo pedal que ligou antes do vazio sai com a nota), o pedal que ligou depois dele não
conta no `secas_pedal`, o que ligou dentro dele, ou na mesma hora da última leitura com algo, sai com a nota de que pode
ter ligado depois da seca, e a linha dá só até quanto depois dele o anel secou, o que desligou dentro dele, ou na mesma
hora da última leitura com algo ou da leitura vazia, conta com a subida que acabou e com a pista dela (das
`ENDED_STARTS` últimas subidas que acabaram, a mais nova que ligou antes do vazio e desligou na última leitura com algo
ou depois dela, ou, sem ela, no vazio ou depois dele, e não só a última, porque o pedal pode ligar e desligar de novo
antes de a seca ser classificada; a pista lida tarde vai para a mais nova em que ela cabe; também a que só foi lida
depois de o pedal desligar, mesmo que outra pista suba antes de a seca ser classificada; nunca a da subida seguinte, nem
dentro da folga do fim dela: cada subida guarda a hora da própria pista, que o `track()` escreve nela, e só aceita uma
pista que subiu depois de o `liga(True)` dela sair da fila do motor, o `sent()` que a thread do pedal carimba depois de
o desligar anterior acabar, para a pista atrasada de um processo que ainda está parando não ir para a subida seguinte (a
comparação é em milissegundos inteiros, a resolução do carimbo, que o `track()` reconstrói inteiro, e a pista do mesmo
milissegundo do envio não é da subida); a latência segue contada da hora do clique; também quando o pedal desliga
enquanto a linha da pista é escrita), com a nota de que pode ter desligado antes da seca; a pista é lida de novo quando
a seca aparece, para um carimbo que chegou na mesma volta (só para a conta: a mistura da volta segue com o que o `_voz`
leu)), até `PEDAL_LINES` linhas por subida do pedal (passou disso, a seca sai como as outras, uma linha a cada
`QUIET_S`, e a conta segue; o `secas`, o `secas_pedal` e o `volta_max_ms` do `/api/state` saem juntos, logo depois de a
seca ser classificada (antes de o anel ser enchido de novo) e no fim de cada volta). As linhas saem na thread do anel,
com `print` no `stderr`, como a outra linha de seca. O `dev/testa_anel.py` confere isso com um produtor de verdade (o
`injeta.Microfone` que o `pista.py` usa), uma seca que o próprio teste faz acontecer, a thread do anel parada quando o
teste quer e o relógio dele, e o `dev/testa_pedal_voz.py` confere o que o motor guarda quando o pedal liga e desliga. O
`dev/measure_voice_pedal.py` mede isso de verdade (manual: o microfone com o filtro, a placa de vídeo e os modelos, com
o Ritmelli desligado), num servidor de verdade deste checkout, numa porta dele e com dados temporários, com quem fala
sem proxy e sem seguir redirecionamento (o `so_mock.abre`), e só com o runtime do app (o `onnxruntime-directml`): sem o
`DmlExecutionProvider`, ou com uma versão que não é a que o `instalador/travas.txt` trava, ele se recusa a rodar antes
de abrir qualquer coisa, a não ser com `--provider cpu`; `--cycles` menor que 1 e um `--on-s` que não é um número
positivo também são recusados, e o resultado leva a versão que rodou e só as linhas de seca entre o primeiro e o último
corte (pelo total que cada uma diz e pelo injetor, que cada linha também diz); uma voz que não está no `vozes.json`
também é recusada antes. Cada ciclo, com o pedal ligado por `--on-s` segundos, precisa da voz de verdade (o processo da
voz disse `pronto`, sem `erro`, e o `fim` do log dele tem blocos e, com `--provider dml`, as quatro sessões no DirectML:
o `fim` traz o `Conversor.providers()`), da linha da subida da pista no log do servidor (o intervalo dela,
`track_up_after_s`, entra na linha do ciclo, e o resultado dá, em `slowest_track_up_s`, o maior limite de baixo e o
maior de cima dos ciclos, entre os quais está a subida mais lenta; a linha leva também o `--on-s` pedido,
`requested_on_s`, e o tempo entre as respostas dos dois `POST` do pedal, `on_s_between_responses`, que mostra um pedal
ligado por mais tempo quando a ferramenta atrasou para ler o stream), de um stream de estado só, aberto depois de
escolher o microfone, que dá a base (o primeiro state com o anel aberto, um leitor e a folga já medida, antes de o pedal
ligar: o leitor sai no estado antes da primeira volta que confere a fila dele; e o `Injetor` conta e publica a seca de
uma leitura vazia antes de a folga ir a zero, e o `estado()` lê a folga antes dos contadores, então nenhum state mostra
a folga em zero sem a seca dela) e os estados de todos os ciclos: cada `tick` leva a hora da captura da volta dele (`t`,
o `time.monotonic` do servidor, o mesmo relógio da ferramenta, que sobe o servidor com o próprio Python), e o `state` de
uma volta vem logo antes do `tick` dela, então cada state tem a hora da volta; uma janela do ciclo leva as voltas até a
primeira do fim dela em diante, que fecha a janela com o que traz, e a seguinte começa depois dela, então cada volta é
de uma janela só, não importa quanto a ferramenta atrasou para ler; o fim do ciclo é o último state da janela; o `tick`
leva também o número da volta (`n`), e um salto nele (a conexão que ficou para trás pula para a volta mais nova) para a
medição, porque um state do meio pode ter mostrado o anel quebrado; o stream que fecha para a medição, de um anel que
mediu a folga e de um anel sem interrupção (leitor o tempo todo, o mesmo microfone, e contadores que não voltam; e o
mesmo `injetor` do `/api/state`, o número que cada `RingDryOuts` ganha ao nascer, que pega um `Injetor` aberto de novo,
mesmo com os mesmos contadores; e o mesmo `leitores_trocados`, porque o vazio de um leitor que acabou de chegar não
conta como seca), ou a medição para e diz qual ciclo. O `dev/test_measure_voice_pedal.py` confere a recusa e a linha de
cada ciclo. Testes: `python dev/testa_pedal_voz.py` (o contrato, com um módulo falso), `python dev/testa_vozes.py` (o
`vozes.json`, o que o instalador baixa e o `impedimento()`), `python dev/testa_pista.py` (o processo contra um anel
falso; com `RITMELLI_VOZES_TESTE=1`, também com os modelos de verdade) e `python dev/testa_conversor.py` (o motor com
modelos de mentira no processador: o tom deslocado, a onda sem degrau entre blocos, o `ajusta_tom` e o silêncio). O
motor e o `compasso.py` desligam a telemetria do ONNX Runtime (ver o PRIVACIDADE.md), e os termos da DirectML vão no
TERCEIROS pelo `instalador/terceiros.py`.
