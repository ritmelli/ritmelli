# O ponto de entrada (`ritmelli.py`)

`ritmelli.py`: o ponto de entrada, o mesmo do executável. Sem modo, liga o servidor. Se
outro Ritmelli já está ligado na mesma porta (o atalho clicado de novo), só abre a página
dele; se ele ainda está ligando, sai sem fazer nada, porque a página abre quando ele
termina (uma trava do Windows marca a porta desde o começo). Com `--yt` ou `--andamento`,
vira o processo auxiliar. No app congelado não há `python` nem
`.py` para abrir, só o próprio executável, e o servidor abre os auxiliares por ele
(`auxiliar` no `server.py`); no código, pelo `python ritmelli.py`, o mesmo caminho. Sem
console (o executável, ou o `pythonw`), a saída e os erros do servidor vão para os
arquivos de log, os mesmos que o `soundboard.ps1` grava, e os da vez anterior ficam ao
lado (`server.anterior.log`), para o motivo de uma queda não sumir quando o app reabre.
