# As batidas e o 1 do compasso pela rede (`compasso.py`)

`compasso.py`: as batidas e o 1 de cada compasso de um trecho pelo beat_this (rede da JKU,
2024) em ONNX, sem PyTorch: mel em numpy com o filtro de reamostragem igual ao do treino,
onnxruntime em 2 threads (a rede roda fora do interpretador; o áudio não espera; só
ABRIR o modelo segura o interpretador ~0,6 s, e por isso o motor abre ao ligar e não fecha),
~1,3 s para 30 s. Precisa de `pip install onnxruntime` e do modelo em
`modelos/compasso.onnx` (~83 MB, no git), que sai do `dev/exporta_compasso.py`
rodado no venv de dev com o torch de CPU; sem os dois, `uns()` devolve None. Por que a
rede: o melhor juiz em numpy (bumbo contra caixa, mudança de acorde e de baixo) acertava o 1
em 71% das janelas contra ela e só ficava sem erro em 13%.
