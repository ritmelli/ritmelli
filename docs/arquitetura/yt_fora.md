# O YouTube num processo à parte (`yt_fora.py`)

`yt_fora.py`: o YouTube (yt-dlp e ytmusicapi) num processo à parte, nunca no do servidor:
com o yt-dlp lá dentro, cada endereço de stream travava o processo do áudio em rajadas de
30 a 45 ms num notebook e o som estalava (o callback é de 10 ms). O servidor deixa um aberto
de reserva, com as bibliotecas carregadas, e cada pedido (stream, busca, download com o
progresso, rádio, Mix, versão só de áudio) leva o de reserva e abre o próximo; volta só o
que o servidor lê, em JSON, e o que o yt-dlp diz vai para o log de erros. Abre como
`ritmelli.py --yt`. O endereço de stream vai de preferência a um processo que fica vivo e
atende um pedido por linha com o mesmo `YoutubeDL`, que guarda o player do YouTube já lido
(no notebook, 0,80 s por endereço em vez de 1,48 s); são `VIVOS` deles (2: o endereço do
palpite errado da mina não segura o do pedido certo): o pedido vai ao livre que já tem
processo quente antes do livre vazio, e com todos ocupados vai pelo de reserva. Cada um sai
no erro, no estouro do limite, depois de `VIVO_MAX` pedidos e de `VIVO_MAX_S` (o
`VIVO_MAX = 0` desliga); o erro do próprio vídeo (indisponível, privado, com idade:
`yt_erros.py`, que o servidor e o `yt_fora.py` leem, sem o yt-dlp) não troca o vivo, não
conta no disjuntor do caminho rápido e não ganha as outras tentativas do stream. O YouTube
fecha a conexão parada aos ~240 s; o `POST /api/aquece` (quem vai pedir avisa antes: a mina,
quando alguém começa a falar) manda um `{"op": "aquece"}` ao vivo e à reserva parados há mais
de `AQUECE_OCIOSA_S`, que renovam as conexões sem responder nada, e já abre o vivo vazio com
o `YoutubeDL` do endereço (`Fora.prepara`). O endereço do primeiro resultado da busca de música (`/api/musica`) sai
logo atrás dela (`ADIANTA`), antes de a mina pôr na fila: o tocar usa o que já está pronto ou a
caminho (no "outra", o do primeiro que não toca, não está na fila, não tocou e não é outra versão
da que toca, como a mina escolhe); o adiantado usado deixa a marca por `ADIANTA_S`, e a busca
que chega depois (a do cérebro, a do lote) não pede de novo o endereço do disco que já toca. E sai pelo caminho rápido (`ENDERECO_RAPIDO`): só o cliente visionos, sem a página do
vídeo, com o visitor id do YouTube Music (0,15 s em vez de 0,8 s); falhou, o de sempre. O
rápido não traz o canal: ele vem do YouTube Music depois de o disco já tocar (`canal_depois`).
Assim que o endereço adiantado sai, o motor já abre o ffmpeg dele e guarda 2 s do começo
(`PREABRE` no `engine.py`): o disco entra no prato e o som sai sem esperar o ffmpeg. A busca de
música, o adiantado e o canal correm num executor próprio (`pool_rapido`), fora do dos
downloads. Ficam dois processos de reserva (`RESERVAS`), e a busca de até 3 resultados tenta
antes a sugestão do YouTube Music (`SUGESTAO`, ~0,1 s), que só vale se for uma música com
todas as palavras do pedido. No pedido de 3 palavras ou mais (`PARALELO_PALAVRAS`), onde a
sugestão quase nunca acerta, a busca sai junto com ela, numa thread, pela segunda conexão
que a reserva já deixa aberta (`pre_conecta`); a sugestão que acerta segue valendo e a
busca é descartada.
