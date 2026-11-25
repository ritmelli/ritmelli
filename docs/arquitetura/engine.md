# O motor de áudio (`engine.py`)

`engine.py`: mistura em WASAPI 48 kHz, blocos de 10 ms; ffmpeg decodifica; voz com no
máximo ~80 ms de atraso; `MockEngine` sem áudio para teste. O Windows converte os 48 kHz
para a taxa de cada aparelho (sem isso, um aparelho a 44,1 kHz recusava o stream). Se o
áudio não abre ao ligar (sem microfone nenhum, por exemplo), o servidor sobe mesmo assim com o
erro na tela e tenta de novo logo depois e quando a lista de aparelhos muda. Áudio de
até 15 s (buzina, bordão) toca por cima da música em vez de trocar, e o posto nos Sons
rápidos pela mão
também, inteiro até 2 min: vários juntos, no volume da música,
o repetido sai na hora (fica decodificado na memória), e o pausar e o parar calam todos.
O `abaixa` abaixa a música no jogo por um prazo, sem gravar nada (o fone segue igual), com uma rampa de um bloco
na ida e na volta para não estalar; no fim do prazo, ela volta sozinha. O `sinal` toca um bipe curto de teste no
jogo, fora do volume da música, e nunca com a voz cortada.
O volume automático (`sonoridade.py`) leva toda música a -11 LUFS, como o Spotify: a mais alta
desce até ele, e a mais baixa sobe, no máximo +9 dB, com um ganho por deck no misturador (rampa de 6 dB/s quando a medida chega com o
disco tocando, ou quando a chave muda) e um limitador com 2 ms de antecipação que só age no que
o ganho acrescentou acima de 0 dBFS: a música que desce, mesmo a que decodifica acima de 0 dBFS (+3,6
na The Real Slim Shady), nunca passa por ele, e todas saem 2 ms atrasadas, sempre. O arquivo se mede inteiro pelo
`ebur128` do ffmpeg, num processo abaixo do normal (o cálculo no processo do servidor seguraria o
interpretador do áudio); o stream, no próprio leitor, com uma estimativa aos 8 s e aos 30 s e a
medida inteira no fim da primeira vez que toca do começo ao fim. A medida fica no `library.json`
(`lufs`) ou, sem o disco na prateleira, no `sonoridades.json` do `--data-dir`; o servidor mede
a prateleira aos poucos. Na prateleira de 14/11, as músicas iam de -19,2 a -5,3 LUFS (mediana
-9,3); o alvo de -11 (o do modo "Alto" do Spotify, que também sobe com limitador) deixa o Sultans
of Swing (+3,1 dB) com 0,2% do tempo acima de 3 dB de limitação, e em -10 seriam 2,7%.
`dev/testa_ganho.py` testa a medida, o limitador e o motor sem som.
