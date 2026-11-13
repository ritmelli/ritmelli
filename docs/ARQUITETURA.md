# Arquitetura

Como cada peça funciona por dentro e por que é assim. Para instalar e usar, veja o
[README](../README.md); o contrato entre o servidor e a interface está no [API.md](../API.md).

## Peças

- `engine.py`: mistura em WASAPI 48 kHz, blocos de 10 ms; ffmpeg decodifica; voz com no
  máximo ~80 ms de atraso; `MockEngine` sem áudio para teste. O Windows converte os 48 kHz
  para a taxa de cada aparelho (sem isso, um aparelho a 44,1 kHz recusava o stream). Se o
  áudio não abre ao ligar (sem o CABLE Input, por exemplo), o servidor sobe mesmo assim com o
  erro na tela e tenta de novo logo depois e quando a lista de aparelhos muda. Áudio de
  até 15 s (buzina, bordão) toca por cima da música em vez de trocar, e o posto nos Sons
  rápidos pela mão
  também, inteiro até 2 min: vários juntos, no volume da música,
  o repetido sai na hora (fica decodificado na memória), e o pausar e o parar calam todos.
- `batida.py`: andamento e grade de batidas de um trecho de música para a passagem no tempo
  (força dos ataques, autocorrelação com dois juízes contra a confusão de 3/4 do tempo, a caixa
  como terceiro juiz, o bumbo escolhendo entre batida e contratempo, pente de batidas afinado),
  com o motivo quando a medição não é firme.
- `compasso.py`: as batidas e o 1 de cada compasso de um trecho pelo beat_this (rede da JKU,
  2024) em ONNX, sem PyTorch: mel em numpy com o filtro de reamostragem igual ao do treino,
  onnxruntime em 2 threads (a rede roda fora do interpretador; o áudio do cabo não espera; só
  ABRIR o modelo segura o interpretador ~0,6 s, e por isso o motor abre ao ligar e não fecha),
  ~1,3 s para 30 s. Precisa de `pip install onnxruntime` e do modelo em
  `modelos/compasso.onnx` (~83 MB, no git), que sai do `dev/exporta_compasso.py`
  rodado no venv de dev com o torch de CPU; sem os dois, `uns()` devolve None. Por que a
  rede: o melhor juiz em numpy (bumbo contra caixa, mudança de acorde e de baixo) acertava o 1
  em 71% das janelas contra ela e só ficava sem erro em 13%.
- `andamento.py`: o andamento do começo e do fim de um disco e a ordem das parecidas do
  Automático por ele. Lê só 25 s do começo e 45 s do fim, do arquivo ou do mesmo stream do
  YouTube que toca (~1 MB por disco, sem baixar nada; no formato leve de ~50 kbps a intro da
  Riptide dava batida firme e no que toca não), e mede nos mesmos 20 s que a passagem mede (o
  `batida.py` e, sem batida firme, a rede). Roda num processo à parte com prioridade baixa
  (`vitrola.py --andamento`, o pedido em JSON na entrada), ~3 a 5 s por disco, e o endereço do
  stream ele mesmo pede ao YouTube (o `stream_yt` do `yt_fora.py`).
- `yt_fora.py`: o YouTube (yt-dlp e ytmusicapi) num processo à parte, nunca no do servidor:
  com o yt-dlp lá dentro, cada endereço de stream travava o processo do áudio em rajadas de
  30 a 45 ms num notebook e o som estalava (o callback é de 10 ms). O servidor deixa um aberto
  de reserva, com as bibliotecas carregadas, e cada pedido (stream, busca, download com o
  progresso, rádio, Mix, versão só de áudio) leva o de reserva e abre o próximo; volta só o
  que o servidor lê, em JSON, e o que o yt-dlp diz vai para o log de erros. Abre como
  `vitrola.py --yt`. O endereço de stream vai de preferência a um processo que fica vivo e
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
- `vitrola.py`: o ponto de entrada, o mesmo do executável. Sem modo, liga o servidor. Se
  outra Vitrola já está ligada na mesma porta (o atalho clicado de novo), só abre a página
  dela; se ela ainda está ligando, sai sem fazer nada, porque a página abre quando ela
  termina (uma trava do Windows marca a porta desde o começo). Com `--yt` ou `--andamento`,
  vira o processo auxiliar. No app congelado não há `python` nem
  `.py` para abrir, só o próprio executável, e o servidor abre os auxiliares por ele
  (`auxiliar` no `server.py`); no código, pelo `python vitrola.py`, o mesmo caminho. Sem
  console (o executável, ou o `pythonw`), a saída e os erros do servidor vão para os
  arquivos de log, os mesmos que o `soundboard.ps1` grava, e os da vez anterior ficam ao
  lado (`server.anterior.log`), para o motivo de uma queda não sumir quando o app reabre.
- `fx.py`: efeitos de voz no estilo Voicemod (rádio de polícia com bip de câmbio, megafone,
  locutor de rádio FM, eco, banheiro, catedral, robô, voz grossa, esquilo, demônio, alienígena,
  alto-falante estourado, e o locutor caricato, um modo do Locutor que fica fora da lista e o tema
  liga pelo botão CARICATO do pedal), aplicados na voz antes da mistura, com o volume compensado
  para a troca não sumir nem estourar; o tom é mudado em casa porque o da pedalboard
  atrasa 1 s. O efeito sempre começa desligado quando o servidor sobe. Banco de teste:
  `python dev/efeitos.py` (grava um .wav por efeito em `logs/efeitos/` para ouvir).
- O pedal da mina: um módulo `mina` opcional, que não mora neste repo. Onde ele está ao lado do
  código, o `fx.py` põe o pedal "Mina DJ" no lugar do alto-falante estourado e o `engine.py` o
  liga e desliga com o pedal; sem ele, o app é o mesmo de sempre. O contrato: o engine chama
  `mina.Mina(engine)`, `liga()`, `desliga()`, `microfone(x)` (a voz crua de quem toca, só com
  a voz indo pro jogo) e `tocou(x)`; o módulo devolve a voz pelo `mina_voz` (a fila do cabo e
  do fone, com 0,1 s de folga de rede), cala pelo `mina_cala` e acha a API pela `porta` do
  engine. No `--mock` o pedal não liga.
- `winvol.py`: o volume do microfone no Windows (IAudioEndpointVolume pelo comtypes); a "Voz"
  da interface é esse número, gravado e lido de volta por uma thread do engine.
- `pareamento.py`: o celular pareado. O instalador libera a entrada no firewall também em
  rede pública, e sem senha qualquer aparelho do mesmo Wi-Fi tocava no microfone do jogo e
  baixava do YouTube. O PC é quem fala pelo `127.0.0.1` (pelo endereço de quem conectou, não
  pelo Host, que quem pede escreve como quiser) e usa tudo; da rede, a API só responde com a
  chave de um celular pareado. O botão Celular mostra um código de 6 números e um QR (do
  `segno`) com o link que já leva o código. O código vale 5 min e uma vez só, e morre com 5
  tentativas erradas, quando só o PC gera outro: sem isso, quem estivesse na rede podia
  tentar até acertar. Pareado, o celular guarda a chave num cookie até o PC desconectar; o
  `celulares.json` (na pasta de dados) guarda só o hash dela; estragado, ele não impede o app
  de abrir, e os celulares pareiam de novo. O cookie vale para o IP do PC: se o roteador der
  outro IP ao PC, o celular pareia de novo. Sem HTTPS (um certificado próprio faria o celular
  avisar "não seguro"): numa Wi-Fi aberta, quem estiver na rede pode copiar o código ou o
  cookie no ar, então é para a rede de casa.
- `atualizacao.py`: o aviso de versão nova e a atualização pelo instalador (o caminho A do
  atualizador). O app baixa o manifesto das versões e a assinatura dele, e só
  aceita o que a chave pública Ed25519 embutida no módulo assinou, e só para uma versão mais nova
  que a dele (um manifesto velho não volta a versão). O setup.exe novo vem com o tamanho e o hash
  conferidos e roda em modo silencioso, com o pedido de permissão do Windows: o instalador fecha
  a Vitrola, troca a pasta dela e abre de novo. Os downloads ficam em
  `%LOCALAPPDATA%\Vitrola\atualizacao`. Enquanto o endereço do manifesto e a chave estão vazios, e
  sempre que roda pelo código, nada é consultado. Teste: `python dev/testa_atualizacao.py`.
- `server.py`: aiohttp no 127.0.0.1 e no IP da rede de casa (Host fixo contra DNS
  rebinding, Origin conhecida em toda escrita contra CSRF, a API da rede só para o celular
  pareado), SSE em `/api/events`, busca e
  download pelo yt_dlp (no `yt_fora.py`). Instalar com `pip install -U "yt-dlp[default]"` (traz o yt-dlp-ejs) e
  ter um runtime de JavaScript (Node ou Deno): sem ele o YouTube esconde formatos e o stream
  falha de vez em quando. O servidor habilita o Node e o Deno nas opções do yt-dlp.
  - Tocar um vídeo que não está na prateleira começa na hora pelo stream do YouTube (o
    yt-dlp dá o endereço do áudio em 1 a 3 s e o ffmpeg toca dele), com o download seguindo
    por trás. Quando o arquivo chega, o motor passa para ele sem cortar, do ponto onde o
    áudio já decodificado termina. O stream tenta três vezes (a última aceitando qualquer
    formato de áudio) e cada falha vai para o `server.err` (nos logs, ver `pastas.py`) com o motivo; se não abrir, a
    tela avisa e o disco toca quando o download chegar. Se o endereço sai mas o ffmpeg não
    recebe nada dele (o YouTube às vezes responde 403), o prato fica carregando, sem erro,
    e toca o arquivo quando o download chega; se o download também falha, o prato para.
  - Fila (A seguir): quando o disco do prato acaba, o primeiro da fila entra, do arquivo
    ou pelo stream. O que entra na fila sem estar na prateleira já começa a baixar. O
    Repetir manda (ligado, o disco não acaba), mas vale só para o disco do prato: outro
    entrando, ou o disco saindo do prato, desliga, como o "repetir uma" do Spotify. Com
    nada no prato (parado, ou o disco já
    acabou), o que entra na fila toca na hora; pausado ainda é disco no prato, e a fila só
    guarda. A fila vive na memória: reiniciar o servidor esvazia.
  - Passagem de DJ: a 45 s do fim, o servidor prepara o primeiro da fila num segundo deck do
    motor (da prateleira, o arquivo; a parecida, o stream; o que ainda baixa, o stream do
    download). O motor mede o fim do disco e o começo do próximo. Final seco emenda tirando o
    silêncio; fade-out recebe o próximo por baixo, em até 8 s com curva de potência constante,
    e o rabo dele 20 dB abaixo do normal fica para trás. Vale para toda passagem automática;
    o Repetir, a Próxima, o Anterior e o pulo na barra seguem cortando. O log mostra cada
    medição (`passagem: ...`).
  - Passagem no tempo: o `batida.py` acha o andamento e a grade de batidas dos 20 s do fim do
    disco e dos 20 s do começo do próximo, e a fase de cada um no trecho em que os dois tocam
    juntos. Entre a batida e o contratempo quem decide é o bumbo, nos 20 s: o trecho curto só
    afina a posição em volta da batida (sozinho, ele caiu no contratempo do Overdose). Só alinha
    quando as duas medições são firmes (os dois juízes do andamento, as duas metades do trecho e
    a fase concordam, e a caixa não aponta outro andamento); senão fica a passagem só de volume.
    A caixa, que bate no 2 e no 4, é o tempo forte e segura a armadilha do 3+3+2 (tresillo,
    tamborzão do funk), em que os dois juízes caem juntos no 4/3 do pulso (o Paper Planes, de 86,
    media 114,7): com folga pequena ela só derruba a medição; com o dobro de folga, e as duas
    metades do trecho dizendo o mesmo, vale o andamento dela; com os dois juízes discordando, ela
    desempata (o começo do Paper Planes tem 5 s de intro sem caixa). Quando o baixo empata a
    batida e o contratempo (no dembow ele bate no "&"), decide o grave só de pancada, sem a nota
    que sustenta. Contra o BPM publicado de 22 músicas da prateleira e o andamento batido à mão no Bota
    Tudo Em Mim (130), 21/10, em 518 janelas de 20 s: 339 firmes certas, nenhuma firme errada, 179
    sem firmeza. A grade do próximo é a do começo dele,
    que é o que toca junto: a música pode mudar de andamento depois (o Lose Yourself vai de 65 BPM
    no piano a 86 quando entra a guitarra, aos 31 s). Quando o `batida.py` não firma, a grade
    sai das batidas da rede (`compasso.py`), medidas antes do fade (com ele junto, as batidas
    que somem puxavam o andamento 1%), 38 ms antes (o quanto elas caem depois das nossas), com o
    lado decidido pelo bumbo como no nosso; com isso 35% das passagens da prateleira ficam no
    tempo em vez de 28%. O modelo abre quando o motor liga e fica aberto (~100 MB): reabrindo a
    cada plano, o áudio estalava no meio da música (22/10). No fade-out com
    os andamentos a até 5% (a menos de oitava; 4,9% no Without Me -> Overdose passou, 6,4% no
    Hino do Grêmio já soou diferente do original), o próximo entra esticado no andamento do que
    sai, com a primeira batida em cima de uma dele. De 5% a ~7%, o que sai também anda, no
    máximo 2% e devagar (0,1% por segundo), antes da sobreposição, e o próximo fica nos 5%: com
    2% no Macetada e 3,9% no hino não se ouviu diferença dos originais, e 4,9% no que sai (a
    NWA) se ouviu. Os blocos do que sai a partir da rampa são trocados pelos reamostrados (com
    a posição do disco no rótulo, então a tela e a virada seguem certas), a batida dele na
    sobreposição é medida no áudio já mudado, e voltar a música no meio da rampa devolve o disco
    original. O servidor prepara o próximo 3 min antes do fim (com 60 s, num notebook com o VRChat aberto, o plano ficava pronto depois do começo da rampa); o log diz quanto a preparação esperou pelo áudio, quanto o plano levou e a folga até a virada. A velocidade muda como no vinil, e a Rubber
    Band (pedalboard) devolve o tom original. Os graves trocam numa batida do meio da
    sobreposição, e o próximo volta ao andamento dele devagar, como o DJ que empurra o pitch aos
    poucos: em média 0,1% por segundo, de 8 a 60 s (3,5% em 8 s soava como a música freando).
    Para caber a volta inteira, o próximo é decodificado até 75 s adiante (~29 MB, só durante a
    passagem), e o plano leva até uns 12 s para ficar pronto (a Rubber Band às vezes segura o
    interpretador uns 15 ms nesse meio, com a volta longa); se o stream não entregar esse
    trecho a tempo, a passagem fica só de volume. No final seco, a primeira batida
    do próximo cai na primeira batida do que sai depois do fim do som dele (onde a passagem de
    volume viraria), e ele entra cheio, esticado no andamento do que sai como no fade: fica nele
    por 8 batidas do que sai e volta devagar ao dele, e a batida segue sem tranco depois do corte
    (escolhida entre a passagem de antes, a esticada e uma que entrava por baixo 2
    compassos antes do corte; no Hino do Grêmio para o Bota Tudo Em Mim, a 4,3%, a de antes
    saía mais de 100 ms da batida em 4 s). Com os andamentos a mais de 5%, ou sem o começo dele
    decodificado para a volta, ele entra no andamento dele; com o começo do próximo sem batida
    firme (intro sem bateria), é a primeira nota dele que cai ali. O que a passagem de volume toca, a no tempo não
    corta: o próximo entra no máximo 1 s antes do fim do som (o Bota Tudo Em Mim tem 18 s
    baixinhos depois de 2 s de silêncio, e o plano que mirava a queda de 20 dB cortava os 20 s). A grade de mais adiante não é estendida de volta até a intro: em 9 músicas ela
    caía fora dos ataques da intro. O log diz o que fez (`passagem: no tempo: ...`) ou por que
    não alinhou.
  - Automático (a chave "Só este disco / Tocar parecidas" embaixo dos botões do toca-discos,
    salva no `config.json`): com ele ligado, a fila nunca
    acaba. O último disco escolhido à mão é a semente, e o rádio do YouTube Music dela (o
    "Iniciar rádio", pela `ytmusicapi` sem login, 50 músicas do catálogo em ~1 s, com artista
    e título separados) mantém 5 parecidas no fim da fila. Sem a
    `ytmusicapi` (`pip install ytmusicapi`), ou com ela falhando, vai o Mix do YouTube (o
    `watch?v=ID&list=RDID`, pelo yt-dlp), que mistura clipe, versão com letra e cover. Não
    entra o que já tocou na sessão nem o que foi tirado da fila, nem vídeo de menos de 1 min ou mais de
    10 min, nem a mesma música em outro vídeo (o título sem o que vem entre parênteses e sem o
    participante, sozinho e junto do artista). As parecidas tocam só pelo
    stream, sem encher a prateleira; o ⊕ da busca, na ponta da linha do canal do disco no prato, baixa a que agradar (o ✓ tira de novo).
    Contrato no `API.md`.
  - Versão só de áudio: o rádio traz de tudo, inclusive o que só existe no
    YouTube, mas a parecida que veio como vídeo (clipe com intro, vídeo com letra) toca a faixa
    do álbum quando o YouTube Music tem: uma busca de músicas com nome e artista (~0,5 s, antes
    da medida de andamento), aceita só quando o título da faixa está inteiro no do vídeo, o que
    sobra é nome de artista, um artista bate e a duração cabe (o Bota Tudo Em Mim trazia outra
    música; o "Calma (Remix)" fica no remix). Sem versão, toca o vídeo. Procurada uma vez só por
    vídeo (no `versoes_audio.json` do `--data-dir`). No rádio do Despacito, 17 de 19 viraram faixa
    de áudio e só 1 delas ficou sem batida firme no começo (com os clipes eram 11 de 21).
  - Ordem das parecidas pelo andamento: elas sobem no círculo das oitavas
    (60 e 120 BPM no mesmo lugar) a partir do fim do disco antes delas, escolhidas entre as da
    próxima 1 h da lista (as mais parecidas com a semente); quando nenhuma cabe nos ~7% que a
    passagem alinha, vai uma um pouco abaixo, senão o salto (que vai ser só de volume) fica
    para a que não tem andamento conhecido, ou para a mais baixa do resto (a volta do
    círculo). O andamento de cada disco é medido uma vez só e fica no `andamentos.json` do
    `--data-dir`; só com o Automático ligado, só depois de o disco ficar 30 s no prato (pular
    de disco em disco não lê nada, e buscar nunca mede) e nunca com a passagem sendo planejada.
    Sem medida ainda, fica a ordem da lista, e cada medida que chega ordena de novo; a primeira
    da fila não troca mais quando falta pouco para a passagem, e a parecida arrastada à mão
    fica onde foi posta. Com o Despacito no prato, as 17 da janela saíram medidas em ~70 s e a
    passagem para a primeira (90,0 BPM) foi no tempo. Duas do mesmo artista nunca vão em
    seguida enquanto houver outra na janela,
    contando o disco antes delas: artista é o do rádio, o que vem antes do " - " no título e
    quem participa ("feat."), sem o canal do vídeo de alguém. No rádio do Family Affair, o MJB
    Da MVP e o I Can Love You, que caíam colados, ficaram com três entre elas.
  - Escutas: o disco ganha uma (`plays` na biblioteca) quando toca de fato 30 s, ou 80%
    dele se for mais curto. Na vitrola a prateleira vem com as mais escutadas primeiro e as
    novas por último.
  - Transporte do Spotify: a Próxima toca o primeiro da fila; o Anterior volta ao começo do
    disco depois de 3 s, e antes disso toca o disco de antes (o servidor guarda os últimos
    50 que saíram do prato), com o atual indo para o topo da fila. O Aleatório embaralha a
    fila como o YouTube Music e, desligado, volta a ordem montada. Pausar cala também os
    sons por cima.
- `API.md`: contrato da API e checklist de todo tema.
- `themes/<slug>/`: as interfaces; `gallery.html` lista e compara lado a lado, com as letras e as texturas do tema
  da vitrola. O app abre direto no tema da vitrola (`pastas.PAGINA`), e a galeria fica em `/`. Na primeira
  vez, o tema abre as boas-vindas por cima (ver o `API.md`).
- `dev/shot.py` (print + erros de console pelo Chrome headless), `dev/fitcheck.py` (gate
  de "cabe em qualquer tela", de 1024x600 a 2560x1300, no celular em pé e no celular grande
  deitado), `dev/compara.py` (gate de "o celular não mudou": prints do tema em estados fixos,
  com uma prateleira de mentira e o servidor em `--mock`, comparados pixel a pixel com os de
  referência gravados antes da mudança), `dev/perfcheck.py`
  (quanto o tema redesenha por segundo com música tocando, no celular emulado),
  `dev/celular.py` (mede rolagem, puxão e abrir do palco no Chrome do celular de verdade,
  por USB com adb; o emulado não reproduz o que trava lá), `dev/bumbo.py` (confere se a passagem
  no tempo de um par da prateleira pôs bumbo em cima de bumbo e não no contratempo, com um
  detector de bumbo próprio; no final seco para um começo sem bumbo, confere a primeira nota
  contra o bumbo do que sai: sai 0 no tempo, 1 contratempo ou fora, 3 sem plano ou sem bumbo), `dev/texturas.py` (gera as
  texturas de ruído da vitrola em WebP a partir dos SVGs que moram nele), `dev/molduras.py`
  (desenha as molduras de pixel da vitrola, contorno, linha clara, bisel e cantos em degrau, e
  grava as variáveis `--mold-*` de border-image no tema, fora do bloco do celular, porque valem
  nas duas telas, com o tamanho do ponto na variável `--px`, 1px quando o tema não a define, e no
  `gallery.html` as que a galeria usa),
  `dev/compactos.py` (desenha em pixel os compactos dos Sons rápidos, em duas
  camadas paradas em volta do selo que gira, e grava as variáveis `--compacto-*` no tema, fora
  do bloco do celular),
  `dev/pecas.py` (desenha em pixel o braço do toca-discos, já inclinado em seis ângulos, a
  base e o descanso dele, os botões de tocar do palco e do mini player e o pisador, os knobs e
  o LED dos pedais, os botões de fliperama e o logo do Locutor, a chave 110/220 do fim do disco, o trilho e o cursor das barras de tempo e volume (os da chave de correr que ela substituiu) e o salvar da parecida no prato, e grava as
  variáveis `--braco-*`, `--tocar-*`, `--icone-*`, `--knob-margem`, `--led-recuo` e `--arcade-recuo` no
  tema, fora do bloco do celular, e no JS a `PE_SVG`, a `LED_SVG`, os `KNOBS`, o `ARCADE`, a `CHAVE_PARECIDAS` e o `SALVAR_PIXEL`) e `dev/previews.py` (gera `preview.png` de cada tema para a galeria, com a prateleira de mentira do
  `dev/compara.py`; ele entra no git porque o instalador leva a pasta do tema como ela está).
- `icone/`: o ícone da Vitrola, o toca-discos do tema visto de cima, que o `dev/icone.py` desenha
  em pixel em cada tamanho (o de 16 px a mão): o `vitrola.ico`, que é o do exe, o do setup e o da
  aba do navegador (pelo `/favicon.ico`), e o `toque.png`, o do atalho na tela inicial do celular
  (pelo `/apple-touch-icon.png`). Com `--instalador`, o script grava também as imagens do
  assistente do Inno Setup na `instalador/`.
- `pastas.py`: os dados de quem usa moram em `%LOCALAPPDATA%\Vitrola`, fora da pasta do
  código, porque instalado em Program Files ela não aceita escrita. Em `library/`, o áudio
  baixado, a lista da biblioteca, as escolhas de volume e dispositivo e os celulares pareados;
  em `logs/`, a saída e os erros do servidor. Os `.json` de lá se gravam pelo `save_json` (num
  `.tmp` e troca de uma vez, para o app caindo no meio não deixar o arquivo pela metade). Os
  logs das ferramentas de `dev/` (`logs/efeitos/`) seguem na pasta do código.
  O ffmpeg, o ffprobe e o Deno vêm da `bin/` do app (a do executável, ou a do código), que o
  instalador vai encher; sem ela, do PATH. O yt-dlp recebe os dois que acharem (`YDL` no
  `server.py`).
- `versao.py`: a versão (semver), que o servidor mostra no Estado e no `--version`; a tag da
  release tem que bater com ela.
- `i18n.py`: os textos da interface em cada língua. Os textos moram em
  `themes/vitrola/i18n/i18n_en.properties` e `i18n_pt_BR.properties`, e o tema só cita a chave
  (`data-i18n="search.clear"` na marcação, `I18N.t('search.clear')` no JS). O servidor lê os
  arquivos a cada abertura da página e põe os textos dentro dela, no lugar do `<!-- i18n -->`:
  assim eles já estão lá antes do primeiro script, sem esperar um `fetch`, e o tema não muda de
  ordem de subida. A página só aparece depois de o começo do script principal aplicar os textos
  da marcação (a classe `i18n-ok`), para não piscar a língua errada. Vão os da língua escolhida
  e os do inglês, a reserva para chave que falte; chave que falte nos dois aparece como a própria
  chave, com um aviso no console. A língua sai do `?lang=` e, quando a detecção ligar, do
  `Accept-Language` do navegador (cada aparelho na sua); até lá, sempre português. O ETag da
  página junta o tema, os textos e a língua, então a página igual volta como 304.

## Filtro "Quest como SM58"

`fx.QuestComoSM58` faz o microfone do Quest (pelo Virtual Desktop) soar como o SM58 com a
boca colada: um equalizador fixo, FIR de fase mínima (atraso perto de zero, 0,05 ms de CPU
por bloco de 10 ms). Devolve o grave de proximidade que o microfone do headset não tem,
tira o som de caixa em 400 a 500 Hz e põe de volta a presença de 3 a 5 kHz. A curva saiu
de uma leitura gravada nos dois microfones ao mesmo tempo (17/10) e, numa segunda leitura
que ela não viu, deixou o Quest a 1,2 dB do SM58.

- Hoje ele entra só nos dois modos do "Locutor de rádio FM": no natural, que foi ajustado em
  cima dele, e no caricato, que foi comparado no ouvido com ele na frente.
- Para usar em outro lugar: `f = fx.QuestComoSM58()` e `y = f(bloco)`, com bloco numpy
  float32 mono a 48 kHz de qualquer tamanho; a instância guarda o estado entre blocos.
  Dentro de um efeito, entra na lista `antes=[...]` do `fx.Efeito`.
- Para calibrar outro microfone ou outro alvo: `python dev/calibra_mic.py --alvo "<entrada
  que se quer>" --mic "<entrada a corrigir>"`, lendo um texto com os dois ligados ao mesmo
  tempo; ele imprime a tupla no formato de `QuestComoSM58.CURVA`.
- Não leva removedor de sala: o Quest já limpa o fundo sozinho, e um segundo filtro que
  muda de ganho a cada instante depois dessa limpeza soou robótico (o mesmo aconteceu com
  o NVIDIA Broadcast na frente do removedor do `dev/aproximar.py`).

## Limite conhecido

O Chrome segura 6 conexões por servidor; cada aba de tema aberta prende uma (SSE). Mais de
5 abas de tema abertas ao mesmo tempo travam as requisições seguintes.
