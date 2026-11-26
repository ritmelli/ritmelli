# A saída para o jogo (`microfone/`)

`microfone/`: a saída para o jogo. O `apo/micfx.dll` é um efeito de áudio do Windows (APO) que
o `microfone.py` pendura nas vagas EFX e LFX de todo microfone do PC, guardando o original (e
devolvendo no remove); o Windows carrega a DLL dentro do `audiodg.exe`, uma instância por
microfone, e cada uma lê o GUID do microfone dela (PKEY_AudioEndpoint_GUID). Um anel de memória
compartilhada (`anel.h`; o lado do app é o `injeta.py`) liga as duas pontas: o app marca o
alvo (o hash do GUID do microfone escolhido) e só a instância do alvo age. Nela, a cada bloco
do microfone, a DLL copia a voz crua (mono, na taxa do microfone) para o app e soma a música
que o app deixou, bit a bit a 48 kHz e por um reamostrador sinc nas outras taxas. No motor, o
`Injetor` (uma thread com a prioridade de áudio do Windows, a MMCSS "Pro Audio") chama o misturador
(`_mixa`) e escreve no anel ~30 ms à frente do microfone, no ritmo dele; sem leitor do alvo, anda pelo relógio do PC e
a música segue no fone. A folga foi medida no `dev/mede_folga.py`: o que a gasta é a troca de música, e para caber em
30 ms o processo roda acima do normal (a thread que segura o interpretador não perde a CPU para o jogo) e o ffmpeg
morre pelo `mata` (o `kill` do `subprocess` prendia o interpretador enquanto o Windows matava o processo). Preso a
um console, o Python pergunta ao `conhost` a cada `io.open` e a cada thread nova, e com a CPU cheia isso prende o
interpretador de 10 a 25 ms: o executável e o `pythonw` (o `soundboard.ps1` sobe por ele) não têm console. O `Injetor`
mede a folga (o menor tanto no anel, as vezes que ele estava vazio e a maior volta da thread) desde que abriu, para o
`/api/state`, e a mesma medida por janela no `metricas.SaudeAudio` dele, que o evento `audio` dos dados de uso leva a
cada meia hora (com as secas no meio de uma passagem ou de uma chamada à Rubber Band, os leitores perdidos, o tempo do
efeito no filtro e da voz pelo microfone de reserva); trocar de `Injetor` começa outra janela, salvo na reabertura
do leitor perdido (`_recupera_leitor`), em que o novo continua a do de antes. A voz crua que volta (reamostrada para 48 kHz) alimenta o medidor, o ouvir a própria voz,
a mina e o efeito; o microfone que o motor abre só fica de reserva para quando ela não chega.
Sem efeito e sem corte, a voz crua segue no microfone. O efeito de voz roda no próprio filtro:
o `preset.py` lê o efeito do `fx.py` e monta o preset (as etapas, com os coeficientes
projetados pelo scipy na taxa do microfone), o `Injetor` escreve no anel e a DLL monta a
cadeia (`apo/voz.h`, numa memória separada no LockForProcess) e passa a voz por ela no mesmo
bloco, sem atraso além do do efeito, e devolve a voz com efeito ao app para o fone e o medidor.
Medido ao vivo como o app roda (sem console, o motor num processo só dele, `dev/mede_voz_ao_vivo.py`
num cabo virtual, 14/11), a voz com o Eco chegou no microfone +0,5 ms depois da crua com o efeito
no filtro, e +66 ms pelo app (na banca, `dev/mede_voz.py`, o caminho pelo app dá 30 a 40 ms). Enquanto o filtro não responde ao preset (até
200 ms) a voz crua segue; efeito com etapa que o filtro não roda na taxa do microfone, ou preset
recusado, vai pelo app: ele passa a voz crua pelo mesmo `voz.h`, no `voz.dll` a 48 kHz
(`microfone/voz.py`), manda o pulso "sem voz" e a voz dele vai no anel. No microfone sem o
filtro, a voz que o motor abre passa pelo `voz.dll` do mesmo jeito, para o ouvir a própria voz.
Sem o `voz.dll` o app sobe igual: o efeito segue no filtro, e a voz que sairia do app vai crua,
com um aviso na tela e no log. A voz cortada também
vai pelo pulso. O filtro só tira a crua e só aplica o efeito com o pulso vivo, então o Ritmelli
que cai não deixa o microfone mudo nem com a voz de robô. Com o microfone aberto por dois
programas, o Windows pode montar duas cadeias, cada uma com a sua instância do filtro: as duas
põem o efeito e a música no próprio som, mas só uma escreve a voz crua e só uma escreve a com
efeito que voltam ao app; quando a dona fecha, sai do alvo ou fica 500 ms sem bloco, a outra
assume (#70). A voz que o filtro não tem como converter no bloco dele (a de um modelo que roda
na placa de vídeo, num processo à parte) volta pela pista da voz do anel: esse processo lê a voz crua
como o app, converte e escreve na pista (`pista_liga`, `pista_escreve` e `pista_pulso` do `injeta.py`),
e o filtro põe ela no lugar da voz do microfone no mesmo ponto em que soma a música. A pista tem
escritor e folga só dela: a voz não paga os ~30 ms de folga que o misturador da música precisa, e o
app segue sendo o único que escreve a música. Sem dado, o bloco sai em silêncio (a voz do microfone
não vaza por um atraso do escritor); escritor que para de bater por 1 s, ou pista desligada, devolvem
a voz do microfone; a voz cortada no app corta a da pista também. O app lê a pista para o fone
(ouvir a própria voz) e o medidor, com uma fila própria (`PISTA_MAX` e `PISTA_ENCHE` no `engine.py`):
a voz convertida chega em rajadas do tamanho do bloco do conversor. Microfone de notebook com
cancelamento de eco e redutor de ruído do fabricante no MFX (o da Fortemedia, #49) apagaria a
música somada no EFX como ruído, e o Windows só aceita a peça de cancelamento de eco como a
última da lista de MFX (nada nosso pode vir depois dela). Ali o `microfone.py` troca o último
MFX do fabricante por um hospedeiro da mesma DLL, que carrega o APO do fabricante por dentro,
repassa tudo a ele e, no que sai, põe o efeito de voz, corta a voz quando o app pede e soma a
música; o EFX desse microfone fica só com a voz crua para o app. O efeito ia no EFX, antes do
fabricante, e o redutor apagava partes dele como ruído: o Rádio de polícia inteiro e a cauda da
Catedral (#78). Com o efeito montado, a voz cortada passa pelo fabricante e o hospedeiro corta
depois do efeito, então ouvir a própria voz com efeito segue valendo com ela cortada. O
redutor segue ligado e a música chega igual no modo normal e no RAW. Quem pendura é o
instalador (administrador, `ritmelli.exe --microfone instala-todos --tarefa`), que também cria a
tarefa do Windows `\Ritmelli\Microfone`: roda como SYSTEM o mesmo `instala-todos` no exe da
pasta de programas, e quem usa o PC só pode rodar a tarefa, não mudar. É por ela que o motor
prepara, sem UAC, um microfone que apareceu depois, e só reabre o áudio quando a tarefa acaba: o filtro
aparece no registro antes de ela reiniciar o áudio e conferir os aparelhos. Reabre mesmo quando quem usa trocou
de microfone no meio: o reinício do áudio derrubou os streams de qualquer microfone. Quando a tarefa não prepara o
microfone pedido, o `pede_tarefa` ainda espera ela acabar e o áudio voltar, e o motor reabre do mesmo jeito, sem
mensagem própria: se o microfone recusado ainda é o ativo, a conferência que a reabertura abre pede para reinstalar
(`server.mic.notReadyReinstall`). Ao desinstalar, o original de
todo microfone volta, o `remove` tenta apagar a pasta do filtro (a DLL ainda presa no `audiodg` pode deixá-la para
trás) e a tarefa, as vagas do hospedeiro e os mudos do registro saem, mesmo quando o reinício do áudio falha (o
Audiosrv que não volta ou o AudioEndpointBuilder que não reinicia: o `remove` sai com o erro depois de limpar). A
DLL e o log moram na `microfone\` da pasta do
executável (pelo código, na `%ProgramW6432%\Ritmelli`), e tudo isso só vale com essa pasta protegida
(`pastas.pasta_protegida`): o `instala` e o `instala-todos` conferem antes de tudo e recusam, e o
`instala-todos` do executável, o da tarefa, ainda apaga as duas tarefas que rodam como SYSTEM (a da
atualização e a dele), que só o setup completo cria de novo. Com a pasta reprovada, o `remove`
devolve os microfones do mesmo jeito, apaga o registro do COM e do APO pelo `winreg`, sem carregar
a DLL, e deixa a pasta como está. Depois do reinício do áudio no instalador e na tarefa, sempre
depois de a pasta passar, o `confere_aparelhos` abre ao mesmo tempo cada microfone e cada saída
ativos e conta os quadros por 2 s (o que não entregou nada tem mais 4 s, numa segunda abertura; a
conferência inteira tem 30 s): o aparelho que abre e não entrega nada (a UMC 404HD da Behringer,
até tirar o cabo, #136) vai para o registro e para o `--saida`, que o instalador mostra na página
de concluído (`instalador/mudos.iss`), com o resumo da conferência no log do setup; o motor
confere de novo, num processo à parte, e avisa quem usa. O `ok` do `--saida` decide o fim do setup: com o
`instala-todos` em erro, ou sem o arquivo, o setup sai com 9 (o `GetCustomSetupExitCode` do `mudos.iss`), e a
esteira reprova. O microfone que recusa o filtro também conta como erro: os outros recebem o filtro, e a conferência,
quando o áudio reiniciou por causa deles ou da DLL nova, vai junto no `--saida`. Ficam de fora sem erro só o aparelho
velho sem as propriedades no registro e o que não está ativo, não tem a chave `FxProperties` e em que o Windows nega
criá-la até ao administrador (`LockedInactiveEndpoint`: um aparelho que já saiu do PC). No microfone ativo, ou com a chave lá, a recusa continua erro. O AudioEndpointBuilder que não reinicia também conta como erro (o
Audiosrv volta do mesmo jeito), e o comando do Audiosrv que falha também, mesmo com o serviço rodando. O
resultado é o `--saida` e o código de saída; o diagnóstico vai para o stderr, pelo `_log`, e some sem mudar o
resultado quando não há console (o executável) ou quando o cano fechou. Na desinstalação não há conferência: não
sobra app para avisar. O `remove` com a pasta reprovada também não confere. Só a DLL nova
reinicia só o Audiosrv, sem desmontar os aparelhos. Os programas do Windows (`schtasks`, `regsvr32`, `icacls`,
`powershell`, `sc`) vão pelo caminho completo da System32: pelo nome solto, o Windows procuraria
antes na pasta do executável. O nome do microfone é o do Windows (Core Audio, casado pelo id
do aparelho): o montado do registro perde o "2- " que o Windows põe quando há dois aparelhos com
o mesmo nome. `dev/testa_microfone.py` testa o motor contra um anel falso, sem som, e a voz
com efeito que sai do app pelo `voz.dll` (e sem ele);
`dev/testa_filtro.py` roda o `micfx.cpp` de verdade fora do audiodg (a `banca_filtro.dll` do
`apo\compila.bat teste`, com o anel num nome só do teste, duas cadeias no mesmo anel e o
hospedeiro do MFX com um fabricante falso por dentro, sozinho e com o EFX na frente);
`dev/testa_mfx.py` confere as vagas de MFX num registro falso, e a pasta protegida no filtro (qual
pasta é conferida, a recusa sem mexer em nada, o desarme das tarefas e o `remove` com a pasta
reprovada) com os comandos gravados; `dev/testa_aparelho_mudo.py` confere a conferência, o aviso e
a página do instalador com um aparelho mudo de mentira; `dev/testa_voz.py` confere cada
efeito do `voz.h` (pelo `voz.dll`) contra o `fx.py`, amostra a amostra, e em outras taxas;
`dev/mede_voz_ao_vivo.py` mede ao vivo, num microfone virtual com o filtro, o atraso da voz com
efeito no filtro e pelo app (toca estalos de verdade nesse microfone).
