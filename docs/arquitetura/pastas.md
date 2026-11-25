# Onde moram os dados (`pastas.py`)

`pastas.py`: os dados de quem usa moram em `%LOCALAPPDATA%\Ritmelli`, fora da pasta do
código, porque instalado em Program Files ela não aceita escrita. Em `library/`, o áudio
baixado, a lista da biblioteca, as escolhas de volume e dispositivo e os celulares pareados;
em `logs/`, a saída e os erros do servidor. Os `.json` de lá se gravam pelo `save_json` (num
`.tmp` e troca de uma vez, para o app caindo no meio não deixar o arquivo pela metade). Os
logs das ferramentas de `dev/` (`logs/efeitos/`) seguem na pasta do código.
O ffmpeg, o ffprobe e o Deno vêm da `bin/` do app (a do executável, ou a do código), que o
instalador vai encher; sem ela, do PATH. O yt-dlp recebe os dois que acharem (`YDL` no
`server.py`). Até a 0.4.1 o app se chamava Vitrola e os dados moravam em
`%LOCALAPPDATA%\Vitrola`: o `migra()` renomeia essa pasta para a nova quando o servidor liga,
antes de qualquer módulo calcular os caminhos dele; se ela estiver presa, os dados seguem nela
naquela abertura e a troca tenta de novo na próxima.
