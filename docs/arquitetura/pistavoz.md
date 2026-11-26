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
`pista_liga` do `microfone/injeta.py` escreve o `GetTickCount64` de quando ligou no `pista_ligou_ms` do anel (o campo de
32 bits ao lado do `pista_ligada`, o mesmo lugar e tamanho do antigo `pista_reservado`, que ninguém lia: o layout não
muda), e o `Injetor`, quando vê a pista viva, desconta quanto tempo faz; assim uma pista que ligou enquanto a thread do
anel estava parada sai com a hora certa. O `RingDryOuts` do `Injetor` conta cada seca entre o pedal ligar e
`AFTER_TRACK_S` depois de a pista ligar no `secas_pedal` do `/api/state` e a põe no log com quanto tempo depois do pedal
e da pista ela veio, até `PEDAL_LINES` linhas por subida do pedal (passou disso, a seca sai como as outras, uma linha a
cada `QUIET_S`, e a conta segue). O `dev/testa_anel.py` confere isso com um produtor de verdade (o `injeta.Microfone`
que o `pista.py` usa), uma seca que o próprio teste faz acontecer, a thread do anel parada quando o teste quer e o
relógio dele, e o `dev/testa_pedal_voz.py` confere o que o motor guarda quando o pedal liga e desliga. O
`dev/measure_voice_pedal.py` mede isso de verdade (manual: o microfone com o filtro, a placa de vídeo e os modelos, com
o Ritmelli desligado), num servidor de verdade deste checkout, numa porta dele e com dados temporários, e só com o
runtime do app (o `onnxruntime-directml`): sem o `DmlExecutionProvider`, ele se recusa a rodar antes de abrir qualquer
coisa, a não ser com `--provider cpu`. Cada ciclo precisa da voz de verdade (o processo da voz disse `pronto`, sem
`erro`, e o log dele termina num `fim` com blocos), ou a medição para e diz qual ciclo. O
`dev/test_measure_voice_pedal.py` confere a recusa e a linha de cada ciclo: uma medição com o conversor no processador,
num Python sem o runtime do app, secava o anel na subida do pedal, e com o runtime do app o mesmo PC não secou (0 em 24
ciclos).
Testes: `python dev/testa_pedal_voz.py` (o contrato, com um módulo falso), `python dev/testa_vozes.py` (o
`vozes.json`, o que o instalador baixa e o `impedimento()`), `python dev/testa_pista.py` (o processo contra um anel
falso; com `RITMELLI_VOZES_TESTE=1`, também com os modelos de verdade) e `python dev/testa_conversor.py` (o motor com
modelos de mentira no processador: o tom deslocado, a onda sem degrau entre blocos, o `ajusta_tom` e o silêncio).
O motor e o `compasso.py` desligam a telemetria do ONNX Runtime (ver o PRIVACIDADE.md), e os termos da DirectML vão
no TERCEIROS pelo `instalador/terceiros.py`.
