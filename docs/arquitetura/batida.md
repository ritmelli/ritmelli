# Andamento e grade de batidas (`batida.py`)

`batida.py`: andamento e grade de batidas de um trecho de música para a passagem no tempo
(força dos ataques, autocorrelação com dois juízes contra a confusão de 3/4 do tempo, a caixa
como terceiro juiz, o bumbo escolhendo entre batida e contratempo, pente de batidas afinado),
com o motivo quando a medição não é firme.

Quando a medição não firma, a grade sai da rede: o `network_beat_grid` do `batida.py` ajusta uma reta nas batidas que o
`compasso.py` devolve, na oitava lenta, com a fase presa no primeiro 1 dele (quando há) e o bumbo escolhendo o lado, e o `network_phase` dá a fase de
um trecho curto pelas mesmas batidas. As duas só valem com os intervalos regulares (`network_intervals`: 90% deles
a 8% da mediana, o `REDE_REGULAR`). Com a rede, 35% das passagens da prateleira saíam no tempo em vez de 28%. As
batidas da rede caem cerca de 38 ms depois das do `medir` (a mediana de 9853 batidas, 21/10), e é o `REDE_ATRASO`
que a grade tira. O número de cada batida sai da soma dos intervalos arredondados, e não da distância ao começo
dividida pela mediana: presa nos quadros de 20 ms da rede, a mediana fazia a 40ª batida virar a 41ª. Entre a batida e
o contratempo quem decide é o bumbo, como no `medir` (o Overdose, 21/10): na intro falada da NWA, a rede punha a
batida no meio tempo do bumbo, e ela entrava no contratempo do Stay With Me.
