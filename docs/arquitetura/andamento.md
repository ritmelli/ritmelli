# O andamento de cada disco (`andamento.py`)

`andamento.py`: o andamento do começo e do fim de um disco e a ordem das parecidas do
Automático por ele. Lê só 25 s do começo e 45 s do fim, do arquivo ou do mesmo stream do
YouTube que toca (~1 MB por disco, sem baixar nada; no formato leve de ~50 kbps a intro da
Riptide dava batida firme e no que toca não), e mede nos mesmos 20 s que a passagem mede (o
`batida.py` e, sem batida firme, a rede). Roda num processo à parte com prioridade baixa
(`ritmelli.py --andamento`, o pedido em JSON na entrada), ~3 a 5 s por disco, e o endereço do
stream ele mesmo pede ao YouTube (o `stream_yt` do `yt_fora.py`).
