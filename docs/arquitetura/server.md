# O servidor (`server.py`)

`server.py`: aiohttp no 127.0.0.1 e no IP da rede de casa (Host fixo contra DNS
rebinding, Origin conhecida em toda escrita contra CSRF, e a tabela de quem pode cada rota do
[`permissao.py`](permissao.md)), SSE em `/api/events`, busca e
download pelo yt_dlp (no `yt_fora.py`). Instalar com `pip install -U "yt-dlp[default]"` (traz o yt-dlp-ejs) e
ter um runtime de JavaScript (Node ou Deno): sem ele o YouTube esconde formatos e o stream
falha de vez em quando. O servidor habilita o Node e o Deno nas opções do yt-dlp.

O `--mock` sobe só no `127.0.0.1`, sem a porta da rede de casa. Para o tema ver o papel do celular sem outro
aparelho, o `--papel-local celular` (só junto do `--mock`) faz o `do_pc` do `build` tirar o papel do PC de quem pede
pelo Host `127.0.0.1:<porta>`: ele passa pelo cookie do pareamento como o celular da rede de casa, e o
`localhost:<porta>` segue o PC. Nesse modo, o `GET /api/pareamento` gera o código com o endereço do `127.0.0.1`.

A regra dos comandos de música (tocar, enfileirar, pular, pausar, parar, a fila e o volume) mora no
[`comandos.py`](comandos.md), e o avanço da fila é uma operação só, dele: a rota do comando lê o corpo, chama o
comando e monta a resposta. O tocar da prateleira (`POST /api/library` com `play`), o nome novo do disco
(`PATCH /api/library/{id}`) e o volume da música do `POST /api/settings` também passam pelos comandos; o resto
dessas rotas (a prateleira, os downloads, as outras configurações do som) chama os métodos do `App` e do motor. A
ordem das travas está no [`comandos.md`](comandos.md#as-travas).
O `parse_target` lê o alvo do corpo e confere os campos que ele traz do vídeo (`title`, `channel`, `thumb`,
`duration` e o alvo, pelo `check_track_fields`) do mesmo jeito para todo papel e antes de olhar a prateleira, na fila
(`App.enfileirar`) e no `POST /api/library` com `play` (sem ele, só o alvo e o título), e o `PATCH /api/library`
recusa o nome em Unicode inválido. O corpo de toda rota se lê só pelo `body()`, na própria rota: o `dev/testa_mock.py` acha pelo fonte cada rota
cujo corpo chega a esses campos e manda a ela os corpos ruins, e falha com a rota que lê o corpo por outro caminho
(`request.json`, `post`, `text`, `read`, `multipart` ou `content`, nela ou numa função a que ela passa o `request`, ou o
`body()` chamado nessa função). O SSE manda o JSON só em ASCII:
um texto que o UTF-8 não codifica não quebra a volta, que é montada uma vez para todas as conexões.

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
  medição (`transition: ...`). As contas que não leem áudio (o fim, o começo e o corpo pelo
  nível dos blocos, a escolha entre fade e final seco, a entrada do próximo e os tempos a partir
  das grades e fases já medidas) moram no `transicao.py`; o `dev/testa_transicao.py` as roda sobre
  as chamadas gravadas da banca das passagens (`dev/testa_passagem.py`).
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
  caía fora dos ataques da intro. O log diz o que fez (`transition: on beat: ...`) ou por que
  não alinhou.
- Automático (a chave "Só este disco / Tocar parecidas" embaixo dos botões do toca-discos,
  salva no `config.json`, ligada na instalação nova): com ele ligado, a fila nunca
  acaba. O último disco escolhido à mão é a semente, e o rádio do YouTube Music dela (o
  "Iniciar rádio", pela `ytmusicapi` sem login, 50 músicas do catálogo em ~1 s, com artista
  e título separados) mantém 5 parecidas no fim da fila. Sem a
  `ytmusicapi` (`pip install ytmusicapi`), ou com ela falhando, vai o Mix do YouTube (o
  `watch?v=ID&list=RDID`, pelo yt-dlp), que mistura clipe, versão com letra e cover. Não
  entra o que já tocou na sessão nem o que foi tirado da fila, nem vídeo de menos de 1 min ou mais de
  10 min, nem a mesma música em outro vídeo (o título sem o que vem entre parênteses e sem o
  participante, sozinho e junto do artista). As parecidas tocam só pelo
  stream, sem encher a prateleira; o ⊕ da busca, na ponta da linha do canal do disco no prato, baixa a que agradar (o ✓ tira de novo).
  Contrato no `API.md`. A lógica mora no `automatico.py` (a classe `Automatico`, em `App.automatico`): o vigia das
  parecidas, a ordem por andamento, a versão só de áudio e o vigia da medida. O estado (a semente, o Mix, o que fica
  de fora, os andamentos e as versões) e a busca de rede (o `mix_do`) seguem no `App`, e o `App` repassa o
  `ligar_auto`, o `_busca_mix` e a `_volta_auto()` a ele. As constantes do Automático (`AUTO_FILA`, `AUTO_JANELA_S`,
  `ANDAMENTO_APOS_S` e as outras) moram no `automatico.py`, e as funções puras de música que ele e o servidor usam
  (`chaves_musica`, `autores`, `mesma_faixa`, `busca_de`, `segundos`, `thumb`) no `music.py`, onde também mora a
  expressão regular `YT_ID`. A pasta da prateleira (`LIB`) e o `save_json` ele importa do `pastas.py`; o que ainda é
  do servidor (o processo do YouTube, o processo auxiliar e o texto do erro) chega pela interface pública do `App`
  (`search_songs`, `run_helper`, `yt_error`), como as mudanças da fila (`change_queue`, `remove_from_queue`) e o
  andamento medido (`tempo_of`). O `dev/testa_automatico.py` confere a fila montada no `App` de verdade, com um
  `mix_do` falso e andamentos conhecidos.
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
  dele se for mais curto. No tema `ritmelli` a prateleira vem com as mais escutadas primeiro e as
  novas por último.
- Transporte do Spotify: a Próxima toca o primeiro da fila; o Anterior volta ao começo do
  disco depois de 3 s, e antes disso toca o disco de antes (o servidor guarda os últimos
  50 que saíram do prato), com o atual indo para o topo da fila. O Aleatório embaralha a
  fila como o YouTube Music e, desligado, volta a ordem montada. Pausar cala também os
  sons por cima.

## Limite conhecido

O Chrome segura 6 conexões por servidor; cada aba de tema aberta prende uma (SSE). Mais de
5 abas de tema abertas ao mesmo tempo travam as requisições seguintes.
