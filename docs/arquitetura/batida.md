# Andamento e grade de batidas (`batida.py`)

`batida.py`: andamento e grade de batidas de um trecho de música para a passagem no tempo
(força dos ataques, autocorrelação com dois juízes contra a confusão de 3/4 do tempo, a caixa
como terceiro juiz, o bumbo escolhendo entre batida e contratempo, pente de batidas afinado),
com o motivo quando a medição não é firme.

Quando a medição não firma, a grade sai da rede: o `network_beat_grid` do `batida.py` ajusta uma reta nas batidas que o
`compasso.py` devolve, na oitava lenta, com a fase presa no primeiro 1 dele (quando há) e o bumbo escolhendo o lado, e o `network_phase` dá a fase de
um trecho curto pelas mesmas batidas. As duas só valem com os intervalos regulares (`network_intervals`).
