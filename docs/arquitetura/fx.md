# Os efeitos de voz (`fx.py`)

`fx.py`: efeitos de voz no estilo Voicemod (rádio de polícia com bip de câmbio, megafone,
locutor FM, eco, banheiro, catedral, robô, voz grave, esquilo, demônio, alienígena,
alto-falante estourado), aplicados na voz antes da mistura, com o volume compensado
para a troca não sumir nem estourar; o tom é mudado em casa porque o da pedalboard
atrasa 1 s. O `fx.py` é a definição de cada efeito e a referência: quem passa a voz pelo efeito
é o motor do filtro (`microfone/preset.py` -> `apo/voz.h`), no microfone pelo `micfx.dll` e no
app pelo `voz.dll`, com a mesma conta, e as etapas da pedalboard foram reescritas lá pela
fórmula de cada uma e conferidas contra ela. As salas
(banheiro, catedral e demônio) usam um reverb próprio, a `Fdn` do `fx.py` (8 linhas de atraso
com realimentação, mistura de Hadamard, tempo de reverberação no grave, no meio e no agudo,
difusor na entrada e leitura modulada bem de leve), no lugar do Reverb da pedalboard, que soava
metálico; o tempo por oitava e o seco/molhado de cada sala são os do Reverb que ela substituiu.
O `Efeito` do `fx.py` (numpy e pedalboard) só roda nos testes de paridade e nas ferramentas de
`dev/`; etapa nova precisa do seu par no `voz.h` (o `dev/testa_voz.py` falha sem ele). A
pedalboard segue no app só pelo `time_stretch` da passagem de DJ. O efeito sempre começa
desligado quando o servidor sobe. Banco de teste:
`python dev/efeitos.py` (grava um .wav por efeito em `logs/efeitos/` para ouvir).

## O pedal de um módulo de fora do repo

O pedal da mina: um módulo `mina` opcional, que não mora neste repo. Onde ele está ao lado do
código, o `fx.py` põe o pedal "Mina DJ" no lugar do alto-falante estourado e o `engine.py` o
liga e desliga com o pedal; sem ele, o app é o mesmo de sempre. O contrato: o engine chama
`mina.Mina(engine)`, `liga()`, `desliga()`, `microfone(x)` (a voz crua de quem toca, só com
a voz indo pro jogo) e `tocou(x)`; o módulo devolve a voz pelo `mina_voz` (a fila do jogo e
do fone, com 0,1 s de folga de rede), cala pelo `mina_cala` e acha a API pela `porta` do
engine. Quando a construção ou o `liga()` levantam uma `i18n.Recusa`, a mensagem dela vai para
a tela como veio; outro `ValueError` vira a `server.mina.notConfigured`, com o texto do erro no
`{reason}` (o `dev/test_external_module.py` confere). No `--mock` o pedal não liga.

Os ganchos do `engine.py` para o módulo opcional de fora do repo não crescem: nada de função,
atributo ou chamada nova para ele, e o que ele precisar daqui em diante passa pelo contrato
acima. Os que já existem ficam como estão. O `dev/testa_ganchos.py` conta esses ganchos (os
nomes do `engine.py` com o nome do módulo, o que o engine lê dele e o que chama nele) contra
o teto `engine_hooks` do `dev/garden.json`, que o `dev/garden.py` segura: falha quando a conta passa dele; quando um
gancho sai, o teto desce no mesmo PR.
Gancho com um nome que não lembra o módulo escapa da conta, e a regra vale igual.

## Filtro "Quest como SM58"

`fx.QuestComoSM58` faz o microfone do Quest (pelo Virtual Desktop) soar como o SM58 com a
boca colada: um equalizador fixo, FIR de fase mínima (atraso perto de zero, 0,05 ms de CPU
por bloco de 10 ms). Devolve o grave de proximidade que o microfone do headset não tem,
tira o som de caixa em 400 a 500 Hz e põe de volta a presença de 3 a 5 kHz. A curva saiu
de uma leitura gravada nos dois microfones ao mesmo tempo (17/10) e, numa segunda leitura
que ela não viu, deixou o Quest a 1,2 dB do SM58.

- Hoje ele entra só no "Locutor FM", que foi ajustado em cima dele.
- Para usar em outro lugar: `f = fx.QuestComoSM58()` e `y = f(bloco)`, com bloco numpy
  float32 mono a 48 kHz de qualquer tamanho; a instância guarda o estado entre blocos.
  Dentro de um efeito, entra na lista `antes=[...]` do `fx.Efeito`.
- Para calibrar outro microfone ou outro alvo: `python dev/calibra_mic.py --alvo "<entrada
  que se quer>" --mic "<entrada a corrigir>"`, lendo um texto com os dois ligados ao mesmo
  tempo; ele imprime a tupla no formato de `QuestComoSM58.CURVA`.
- Não leva removedor de sala: o Quest já limpa o fundo sozinho, e um segundo filtro que
  muda de ganho a cada instante depois dessa limpeza soou robótico (o mesmo aconteceu com
  o NVIDIA Broadcast na frente do removedor do `dev/aproximar.py`).
