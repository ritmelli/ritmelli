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

A regra da pasta protegida (`pasta_protegida`): as duas tarefas do Windows que rodam como SYSTEM o
`ritmelli.exe` da pasta do app (a do filtro de microfone e a da atualização) só usam uma pasta que
apenas o sistema e os administradores conseguem alterar. A pasta fica dentro da Program Files de 64
bits, sem ponto de reanálise no caminho nem dentro dela, sem nome curto 8.3 no caminho e sem nome
que o Windows não abre como está (terminado em ponto ou espaço, ou num caminho de 260 caracteres ou
mais, contados em UTF-16); o dono dela e de tudo dentro é SYSTEM, Administradores ou
TrustedInstaller; e nenhuma ACE dá a outro principal escrita, criação, exclusão, `WRITE_DAC` ou
`WRITE_OWNER`, nela, em tudo dentro dela e nos pais até a raiz
(das só de herança, só a do CREATOR OWNER fica de fora). A exceção é a `microfone\log`, onde o
LocalService (o `audiodg.exe`) grava o log do filtro. A leitura abre cada objeto sem seguir ponto
de reanálise (`_le_disco`), e a avaliação é separada dela, para o teste em memória
(`dev/testa_pasta_protegida.py`; o `--disco` confere o mesmo no disco, como administrador). O
instalador tem a mesma regra em PowerShell (`instalador\protegida.ps1`), e o `--disco` exige o
mesmo veredito das duas em cada caso. O `do_windows` dá o caminho completo de um programa da
System32. As duas tarefas que rodam como SYSTEM (a do filtro e a da atualização) nascem pelo
`create_task` e saem pelo `disarm`, que, com a pasta reprovada, apaga as duas (a outra antes da
que está rodando, uma mesmo se a outra falhar) e confere depois.
