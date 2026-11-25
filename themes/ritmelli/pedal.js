/* PEDAL-JS-INICIO: os pedais da mesa em pixel art, tudo em celulas de 2 px (o canvas tem 1 px por celula e o
   CSS o mostra a 2x; com a celula fora de um numero inteiro de px da tela, como no palco de 1440, o canvas vai na
   resolucao da tela, ver o pintaTela), um canvas por pedal dentro do botao dele: o esmalte na cor do mock de 20/11 com
   o contorno, o bisel e a parede embaixo, os quatro parafusos, o icone (desenhado a mao, celula por celula, na rampa de
   creme e ouro com o contorno escuro; o rosto do Troca de voz com os tons de pele dele), o LED vermelho (aceso so no
   pedal ligado: o bulbo claro no aro escuro, com o brilho vermelho em volta, igual nos 13), o nome na letra condensada
   de 3 x 7 celulas (ate 3 linhas, na faixa da largura do pedal menos 14 px, cada linha pelo topo das maiusculas: o
   acento sobe sem empurrar; o contorno e do bloco todo) e o footswitch de niquel do app antigo (o PE_SVG por cima do
   canvas, na grade de 1 px: a tampa desce 1 px na pisada; no palco abaixo de 0,875 px de tela por px, como o de 1440, e
   nos multiplos de 0,75, como o do notebook, o footswitch e o icone do Troca de voz saem nos desenhos feitos a mao para
   la, 1:1 ou m x m em px de tela, ver o pecaNaTela). O Troca de voz (pistavoz, do modulo de fora; ver o API.md) e
   maior: roxo com a moldura dourada de 3 celulas e a mesma parede dos outros embaixo, o icone do mock (a cabeca com as
   duas caras, na grade de 1 px que o dono liberou para ele, num canvas por cima como o footswitch), o visor de vidro
   escuro (com a luz de fundo ambar no pedal ligado) com a voz escolhida, o FALE ALGO (piscando entre aceso e apagado) e
   o PRONTO com o visto na letra larga de LCD quando cabem, e o OUVINDO sempre na letra dos nomes com os 6 blocos da
   barra; e, embaixo, as duas vozes com o LED no meio; os rotulos sao botoes de verdade por cima, cada um com a metade
   da faixa (o escolhido em creme, o outro malva; o do mouse e o do foco do teclado com a moldura ambar em volta). Cada
   canvas so se redesenha quando o que ele mostra muda (ou a escala da tela); a chave fica no canvas (_geo; no
   footswitch em canvas e no icone do Troca de voz, _f), e o repintarCanvas a zera */
const LETRA_PEDAL = {   // 3 x 7 celulas (M e W com 5, N e Q com 4, I com 1, hifen 2, espaco 1); a acentuada com 3 linhas em cima, o Ç com 2 embaixo
  "A": [".#.", "#.#", "#.#", "###", "#.#", "#.#", "#.#"],
  "B": ["##.", "#.#", "#.#", "##.", "#.#", "#.#", "##."],
  "C": [".##", "#..", "#..", "#..", "#..", "#..", ".##"],
  "D": ["##.", "#.#", "#.#", "#.#", "#.#", "#.#", "##."],
  "E": ["###", "#..", "#..", "##.", "#..", "#..", "###"],
  "F": ["###", "#..", "#..", "##.", "#..", "#..", "#.."],
  "G": [".##", "#..", "#..", "#.#", "#.#", "#.#", ".##"],
  "H": ["#.#", "#.#", "#.#", "###", "#.#", "#.#", "#.#"],
  "I": ["#", "#", "#", "#", "#", "#", "#"],
  "J": ["..#", "..#", "..#", "..#", "..#", "#.#", ".#."],
  "K": ["#.#", "#.#", "##.", "#..", "##.", "#.#", "#.#"],
  "L": ["#..", "#..", "#..", "#..", "#..", "#..", "###"],
  "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
  "N": ["#..#", "##.#", "##.#", "#.##", "#.##", "#..#", "#..#"],
  "O": [".#.", "#.#", "#.#", "#.#", "#.#", "#.#", ".#."],
  "P": ["##.", "#.#", "#.#", "##.", "#..", "#..", "#.."],
  "Q": [".##.", "#..#", "#..#", "#..#", "#..#", "#.#.", ".#.#"],
  "R": ["##.", "#.#", "#.#", "##.", "#.#", "#.#", "#.#"],
  "S": [".##", "#..", "#..", ".#.", "..#", "..#", "##."],
  "T": ["###", ".#.", ".#.", ".#.", ".#.", ".#.", ".#."],
  "U": ["#.#", "#.#", "#.#", "#.#", "#.#", "#.#", "###"],
  "V": ["#.#", "#.#", "#.#", "#.#", "#.#", ".#.", ".#."],
  "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
  "X": ["#.#", "#.#", ".#.", ".#.", ".#.", "#.#", "#.#"],
  "Y": ["#.#", "#.#", "#.#", ".#.", ".#.", ".#.", ".#."],
  "Z": ["###", "..#", "..#", ".#.", "#..", "#..", "###"],
  "0": [".#.", "#.#", "#.#", "#.#", "#.#", "#.#", ".#."],
  "1": [".#", "##", ".#", ".#", ".#", ".#", ".#"],
  "2": ["##.", "..#", "..#", ".#.", "#..", "#..", "###"],
  "3": ["##.", "..#", "..#", ".#.", "..#", "..#", "##."],
  "4": ["#.#", "#.#", "#.#", "###", "..#", "..#", "..#"],
  "5": ["###", "#..", "#..", "##.", "..#", "..#", "##."],
  "6": [".##", "#..", "#..", "##.", "#.#", "#.#", ".#."],
  "7": ["###", "..#", "..#", ".#.", ".#.", ".#.", ".#."],
  "8": [".#.", "#.#", "#.#", ".#.", "#.#", "#.#", ".#."],
  "9": [".#.", "#.#", "#.#", ".##", "..#", "..#", "##."],
  "-": ["..", "..", "..", "##", "..", "..", ".."],
  " ": [".", ".", ".", ".", ".", ".", "."],
  "'": ["#", "#", ".", ".", ".", ".", "."],
  ".": [".", ".", ".", ".", ".", ".", "#"],
  "Á": ["..#", ".#.", "...", ".#.", "#.#", "#.#", "###", "#.#", "#.#", "#.#"],
  "À": ["#..", ".#.", "...", ".#.", "#.#", "#.#", "###", "#.#", "#.#", "#.#"],
  "Â": [".#.", "#.#", "...", ".#.", "#.#", "#.#", "###", "#.#", "#.#", "#.#"],
  "Ã": [".##", "##.", "...", ".#.", "#.#", "#.#", "###", "#.#", "#.#", "#.#"],
  "É": ["..#", ".#.", "...", "###", "#..", "#..", "##.", "#..", "#..", "###"],
  "Ê": [".#.", "#.#", "...", "###", "#..", "#..", "##.", "#..", "#..", "###"],
  "Ó": ["..#", ".#.", "...", ".#.", "#.#", "#.#", "#.#", "#.#", "#.#", ".#."],
  "Ô": [".#.", "#.#", "...", ".#.", "#.#", "#.#", "#.#", "#.#", "#.#", ".#."],
  "Õ": [".##", "##.", "...", ".#.", "#.#", "#.#", "#.#", "#.#", "#.#", ".#."],
  "Ú": ["..#", ".#.", "...", "#.#", "#.#", "#.#", "#.#", "#.#", "#.#", "###"],
  "Ü": ["#.#", "...", "...", "#.#", "#.#", "#.#", "#.#", "#.#", "#.#", "###"],
  "Í": [".#", "#.", "..", "#.", "#.", "#.", "#.", "#.", "#.", "#."],
  "Ç": [".##", "#..", "#..", "#..", "#..", "#..", ".##", ".#.", "#.."]
};
const LETRA_LCD = {   // a do visor do Troca de voz, 4 x 9 celulas (M, W, T, V, X e Y com 5, I com 1, espaco 2); so maiusculas sem acento
  "A": [".##.", "#..#", "#..#", "#..#", "####", "#..#", "#..#", "#..#", "#..#"],
  "B": ["###.", "#..#", "#..#", "#..#", "###.", "#..#", "#..#", "#..#", "###."],
  "C": [".###", "#...", "#...", "#...", "#...", "#...", "#...", "#...", ".###"],
  "D": ["###.", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#", "###."],
  "E": ["####", "#...", "#...", "#...", "###.", "#...", "#...", "#...", "####"],
  "F": ["####", "#...", "#...", "#...", "###.", "#...", "#...", "#...", "#..."],
  "G": [".###", "#...", "#...", "#...", "#.##", "#..#", "#..#", "#..#", ".###"],
  "H": ["#..#", "#..#", "#..#", "#..#", "####", "#..#", "#..#", "#..#", "#..#"],
  "I": ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
  "J": ["...#", "...#", "...#", "...#", "...#", "...#", "#..#", "#..#", ".##."],
  "K": ["#..#", "#..#", "#.#.", "#.#.", "##..", "#.#.", "#.#.", "#..#", "#..#"],
  "L": ["#...", "#...", "#...", "#...", "#...", "#...", "#...", "#...", "####"],
  "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#", "#...#", "#...#"],
  "N": ["#..#", "#..#", "##.#", "##.#", "#.##", "#.##", "#..#", "#..#", "#..#"],
  "O": [".##.", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#", ".##."],
  "P": ["###.", "#..#", "#..#", "#..#", "###.", "#...", "#...", "#...", "#..."],
  "Q": [".##.", "#..#", "#..#", "#..#", "#..#", "#..#", "#.##", "#..#", ".###"],
  "R": ["###.", "#..#", "#..#", "#..#", "###.", "#.#.", "#..#", "#..#", "#..#"],
  "S": [".###", "#...", "#...", "#...", ".##.", "...#", "...#", "...#", "###."],
  "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
  "U": ["#..#", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#", ".##."],
  "V": ["#...#", "#...#", "#...#", "#...#", ".#.#.", ".#.#.", ".#.#.", "..#..", "..#.."],
  "W": ["#...#", "#...#", "#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
  "X": ["#...#", "#...#", ".#.#.", ".#.#.", "..#..", ".#.#.", ".#.#.", "#...#", "#...#"],
  "Y": ["#...#", "#...#", ".#.#.", ".#.#.", "..#..", "..#..", "..#..", "..#..", "..#.."],
  "Z": ["####", "...#", "...#", "..#.", ".##.", ".#..", "#...", "#...", "####"],
  " ": ["..", "..", "..", "..", "..", "..", "..", "..", ".."]
};
const LETRA_LCD_VOZ = {   // a voz no visor do Troca de voz: 6 x 9 (M, W, T, V, X e Y com 7, I com 1), passo 7, espaco 2 (o fino 1)
  "A": [".####.", "#....#", "#....#", "#....#", "######", "#....#", "#....#", "#....#", "#....#"],
  "B": ["#####.", "#....#", "#....#", "#....#", "#####.", "#....#", "#....#", "#....#", "#####."],
  "C": [".#####", "#.....", "#.....", "#.....", "#.....", "#.....", "#.....", "#.....", ".#####"],
  "D": ["#####.", "#....#", "#....#", "#....#", "#....#", "#....#", "#....#", "#....#", "#####."],
  "E": ["######", "#.....", "#.....", "#.....", "#####.", "#.....", "#.....", "#.....", "######"],
  "F": ["######", "#.....", "#.....", "#.....", "#####.", "#.....", "#.....", "#.....", "#....."],
  "G": [".#####", "#.....", "#.....", "#.....", "#..###", "#....#", "#....#", "#....#", ".#####"],
  "H": ["#....#", "#....#", "#....#", "#....#", "######", "#....#", "#....#", "#....#", "#....#"],
  "I": ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
  "J": [".....#", ".....#", ".....#", ".....#", ".....#", ".....#", "#....#", "#....#", ".####."],
  "K": ["#....#", "#...#.", "#..#..", "#.#...", "##....", "#.#...", "#..#..", "#...#.", "#....#"],
  "L": ["#.....", "#.....", "#.....", "#.....", "#.....", "#.....", "#.....", "#.....", "######"],
  "M": ["#.....#", "##...##", "#.#.#.#", "#..#..#", "#.....#", "#.....#", "#.....#", "#.....#", "#.....#"],
  "N": ["#....#", "##...#", "#.#..#", "#.#..#", "#..#.#", "#..#.#", "#...##", "#....#", "#....#"],
  "O": [".####.", "#....#", "#....#", "#....#", "#....#", "#....#", "#....#", "#....#", ".####."],
  "P": ["#####.", "#....#", "#....#", "#....#", "#####.", "#.....", "#.....", "#.....", "#....."],
  "Q": [".####.", "#....#", "#....#", "#....#", "#....#", "#....#", "#..#.#", "#...#.", ".###.#"],
  "R": ["#####.", "#....#", "#....#", "#....#", "#####.", "#..#..", "#...#.", "#....#", "#....#"],
  "S": [".#####", "#.....", "#.....", "#.....", ".####.", ".....#", ".....#", ".....#", "#####."],
  "T": ["#######", "...#...", "...#...", "...#...", "...#...", "...#...", "...#...", "...#...", "...#..."],
  "U": ["#....#", "#....#", "#....#", "#....#", "#....#", "#....#", "#....#", "#....#", ".####."],
  "V": ["#.....#", "#.....#", "#.....#", ".#...#.", ".#...#.", "..#.#..", "..#.#..", "...#...", "...#..."],
  "W": ["#.....#", "#.....#", "#.....#", "#.....#", "#..#..#", "#..#..#", "#.#.#.#", "##...##", "#.....#"],
  "X": ["#.....#", ".#...#.", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", ".#...#.", "#.....#"],
  "Y": ["#.....#", ".#...#.", ".#...#.", "..#.#..", "...#...", "...#...", "...#...", "...#...", "...#..."],
  "Z": ["######", ".....#", "....#.", "....#.", "...#..", "..#...", ".#....", "#.....", "######"],
  " ": ["..", "..", "..", "..", "..", "..", "..", "..", ".."],
  "\u2009": [".", ".", ".", ".", ".", ".", ".", ".", "."]
};
const LETRA_LCD_FRASE = {   // o FALE ALGO e o PRONTO no visor: 5 x 9 (I com 1), passo 6, espaco 2 (o fino 1)
  "A": [".###.", "#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#...#"],
  "B": ["####.", "#...#", "#...#", "#...#", "####.", "#...#", "#...#", "#...#", "####."],
  "C": [".####", "#....", "#....", "#....", "#....", "#....", "#....", "#....", ".####"],
  "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
  "E": ["#####", "#....", "#....", "#....", "####.", "#....", "#....", "#....", "#####"],
  "F": ["#####", "#....", "#....", "#....", "####.", "#....", "#....", "#....", "#...."],
  "G": [".####", "#....", "#....", "#....", "#..##", "#...#", "#...#", "#...#", ".####"],
  "H": ["#...#", "#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#", "#...#"],
  "I": ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
  "J": ["....#", "....#", "....#", "....#", "....#", "....#", "#...#", "#...#", ".###."],
  "K": ["#...#", "#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#", "#...#"],
  "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#....", "#....", "#####"],
  "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#", "#...#", "#...#"],
  "N": ["#...#", "##..#", "##..#", "#.#.#", "#.#.#", "#..##", "#..##", "#...#", "#...#"],
  "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  "P": ["####.", "#...#", "#...#", "#...#", "####.", "#....", "#....", "#....", "#...."],
  "Q": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", "#..##", "#...#", ".####"],
  "R": ["####.", "#...#", "#...#", "#...#", "####.", "#..#.", "#...#", "#...#", "#...#"],
  "S": [".####", "#....", "#....", "#....", ".###.", "....#", "....#", "....#", "####."],
  "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
  "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  "V": ["#...#", "#...#", "#...#", "#...#", ".#.#.", ".#.#.", ".#.#.", "..#..", "..#.."],
  "W": ["#...#", "#...#", "#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
  "X": ["#...#", "#...#", ".#.#.", ".#.#.", "..#..", ".#.#.", ".#.#.", "#...#", "#...#"],
  "Y": ["#...#", "#...#", ".#.#.", ".#.#.", "..#..", "..#..", "..#..", "..#..", "..#.."],
  "Z": ["#####", "....#", "....#", "...#.", "..#..", ".#...", "#....", "#....", "#####"],
  " ": ["..", "..", "..", "..", "..", "..", "..", "..", ".."],
  "\u2009": [".", ".", ".", ".", ".", ".", ".", ".", "."]
};
(() => {
  const ICONES_PEDAL = {
    'radio-policia': { pal: ["#1A0B04", "#754D1C", "#D9A942", "#EED26C"], rows: ["..............................aaa.....", ".............................addca....", ".............................accba....", ".............................aacaa....", "..............................aca.....", "..............................aca.....", "..............................aca.....", "...aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa...", "..adddddddddddddddddddddddddddddddda..", ".adccccccccccccccccccccccccccccccccda.", "adccbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbccda", "adcbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbdcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbadcadcadcadcadcadcadcadcadcaddcba", "adcbbddddddddddddddddddddddddddddddcba", "adccddddddddddddddddddddddddddddddccba", "abcccccccaadccccccccccccccccaadcccccba", ".abccccccddcccccccccccccccccddcccccba.", "..abbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbba..", "...aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa..."] },
    'megafone': { pal: ["#1A0B04", "#754D1C", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: [".........................a...", "........................aea..", ".....................aaaedea.", "...................aafcaedba.", "................aaaffcaedbbba", "..............aafffffcaedbbba", "...........aaafffffffcaedbbba", "..........affffffffffcaebbbba", "........aafffffffffffcaebbbba", ".....aaaeeaffffffffffcaebbbba", ".aaaaccaebaffffffffffcaebbbba", "aeeeeacaebaffffffffffcaebbbba", "aeddbacaebaffffffffffcaebbbba", "aeddbacaebaffffffffffcaebbbba", "aeddbacaebaffffffffffcaebbbba", "aeddbacaebaffffffffffcaebbbba", "abbbbacaebaffffffffffcaebbbba", ".aaaaacaebaffffffffffcaebbbba", "......aabbaffffffffffcaebbbba", "........aaaccffffffffcaebbbba", "........aeeaaccffffffcaebbbba", "........aedeaaaccffffcaeddbba", ".......aeddba..aaccffcaedbbba", ".......aeddba....aacccaddbbba", ".......abbbba......aaccaddda.", "........aaaa.........aaabdba.", "........................aba..", ".........................a..."] },
    'locutor': { pal: ["#1A0B04", "#754D1C", "#B98D4E", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: [".......aaaaaa.......", "......agggggda......", ".....agggggggda.....", "....adddddddddda....", "...adccccccccccda...", "...agggggggggggda...", ".aaagdddddddddddaaa.", "affadccccccccccdaffa", "afbagggggggggggdafba", "afbagdddddddddddafba", "afbadccccccccccdafba", "afbagggggggggggdafba", "afbaddddddddddddafba", "afbaaccccccccccaafba", "abba.adggggggda.abba", ".aaaaaaddddddaaaaaa.", "affffffaaaaaaffffffa", "abbbbbbffaaffbbbbbba", ".aaaaaaaaffaaaaaaaa.", "........afba........", "........afba........", "........afba........", "........afba........", "........abba........", ".....aaaaaaaaaa.....", "...aaffffffffffaa...", "..affeeeeeeeeeeffa..", ".afeeeeeeeeeeeeeefa.", "..abbeeeeeeeeeebba..", "...aabbbbbbbbbbaa...", ".....aaaaaaaaaa....."] },
    'eco': { pal: ["#1A0B04", "#CFB884", "#F4ECBC"], rows: ["..............aaaa.................", "...........aaacccba................", ".........aacccbbbba................", "........accbbbaaaa.................", ".......acbbaaa.....................", "......acbaa...aaaa.........aa......", ".....acba...aacccba.......abba.....", "....acba...accbbbba........aa......", "...acba...acbbaaaa.................", "..acba...acbaa.........aa..........", "..acba..acba...aaa....abba.........", ".acba..acba...accba....aa..........", ".acba.acba...acbbba................", ".acba.acba..acbaaa.................", "acba.acba..acba....................", "acba.acba.acba..aaa................", "acba.acba.acba.accba..aa...aa...aa.", "acba.acba.acba.accba.acba.acba.acba", "acba.acba.acba.abbba.acba.acba.acba", "acba.acba.abba..aaa..acba.acba.acba", "abba.abba..abba.....acba..acba.acba", ".acba.abba..abbaaaaacba..acba.acba.", ".acba.abba...abcccccba...acba.acba.", ".abba..abba...abbbbba...acba..acba.", "..abba..abba...aaaaa...acba..acba..", "..abba...abbaa.......aacba...acba..", "...abba...abbbaaaaaaaccba...acba...", "....abba...abbcccccccbba...acba....", ".....abba...aabbbbbbbaa...acba.....", "......abbaa...aaaaaaa...aacba......", ".......abbbaaa.......aaaccba.......", "........abbccbaaaaaaacccbba........", ".........aabbbcccccccbbbaa.........", "...........aaabbbbbbbaaa...........", "..............aaaaaaa.............."] },
    'banheiro': { pal: ["#1A0B04", "#CFB884", "#D9A942", "#F4ECBC"], rows: ["...............aaaaaaaaaaa..", "..............addddddddddba.", ".............abdddddddddddba", "..............abbbbbbbbbbba.", "...............aaaaaaaaaaa..", "..............addddbbddddba.", "..............adddbccddddba.", "..............adddbccddddba.", "..............addddddddddba.", "..............addddddddddba.", "..............addddddddddba.", "..............abbbbbbbbddba.", "..aaaaaaaaaaaaaaaaaaaaabdba.", ".addddddddddddddddddddbabba.", "abdddddddddddddddddddddbaa..", ".abbbbbbbbbbbbbbbbbbbbbaba..", "abaaaaaaaaaaaaaaaaaaaaadba..", ".adddddddddddddddddddddba...", ".abddddddddddddddddddddba...", "..abbddddddddddddddddbba....", "...aabbddddddddddddbbaa.....", ".....aabbbbbbbbbbbbaa.......", ".......aaaaaaaaaaaa.........", "......adddddddddddba........", "......abbbbbbbbbbbba........", "......aaaaaaaaaaaaaa........", ".....adddddddddddddba.......", "....abddddddddddddddba......", ".....abbbbbbbbbbbbbba.......", "......aaaaaaaaaaaaaa........"] },
    'catedral': { pal: ["#1A0B04", "#754D1C", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: ["...............aa..............", "..............affa.............", ".............aaffaa............", "............affffffa...........", ".............aaffaa............", "..............affa.............", "..............affa.............", ".............aeeeea............", "............aeddddea...........", "............aeddddba...........", "....aa.....aebbbbbbba....aa....", "...aeea.....aaaaaaaa....aeea...", "..aeddea...afffccffca..aeddea..", ".aeddddea..affcaacfca.aeddddea.", ".aeddddba..afcaaaafca.aeddddba.", "aebbbbbbba.afcaeeafcaaebbbbbbba", ".aaaaaaaa..afcaaaafca.aaaaaaaa.", "afffffffca.affcaaffcaafffffffca", "afffffffca.afffffffcaafffffffca", "afffccffcaaafffffffcaafffccffca", "affcaacfcacafffffffcaaffcaacfca", "afcaaaafcacafffffffcaafcaaaafca", "afcaaaafcacaffccccfcaafcaaaafca", "afcaaaafcacafcaaaafcaafcaaaafca", "afcaaaafcacafcaaaaccaafcaaaafca", "afcaaaafcacacaaaaaacaafcaaaafca", "afffffffcacacaaaaaacaafffffffca", "afffffffcacacaaaaaacaafffffffca", "afffffffcacacaaaaaacaafffffffca", "afffffffcacacaaaaaacaafffffffca", "afffffffcacacaaaaaacaafffffffca", "accccccccacacaaaaaacaacccccccca", ".aaaaaaaa.a.a......a..aaaaaaaa."] },
    'robo': { pal: ["#1A0B04", "#754D1C", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: ["................aaaa................", "...............aeeeea...............", "...............aeddba...............", "..............aedbbdda..............", "...............abaaba...............", "................aeea................", "........aaaaaaaaaaaaaaaaaaaa........", ".......afffffffffffffffffffca.......", "......afffffffffffffffffffffca......", ".....afffffcccffffffffcccffffca.....", ".....affffcaaacffffffcaaacfffca.....", "..aaaafffcaaaaacffffcaaaaacffcaaaa..", ".aeeeaffcaacccaacffcaacccaacfcaeeea.", "aeddbafcaacffccaafcaacffccaafcaeddea", "aeddbafcaacfcccaafcaacfcccaafcaeddba", "aeddbafcaacccccaafcaacccccaafcaeddba", "aeddbaffcaacccaafffcaacccaaffcaeddba", "aeddbafffcaaaaafffffcaaaaafffcaeddba", "aeddbaffffcaaafffffffcaaaffffcaeddba", "abddbafffffccccccccccccccffffcaeddba", ".abbbaffffcaaaaaaaaaaaaaaffffcabbba.", "..aaaaffffcaaccaccaccaccaffffcaaaa..", ".....affffcaaccaccaccaccaffffca.....", ".....affffcaaaaaaaaaaaaaaffffca.....", ".....acffffffffffffffffffffffca.....", "......acfffffffccccccfffffffca......", ".......acccccccaaaaaaccccccca.......", "........aaaaaaaeeeeeeaaaaaaa........", ".............aeddddddea.............", ".............abddddddba.............", "..............abbbbbba..............", "...............aaaaaa..............."] },
    'voz-grossa': { pal: ["#1A0B04", "#754D1C", "#B98D4E", "#CFB884", "#EED26C", "#F4ECBC"], rows: ["..........aaaaa....................", ".......aaafffffaaa.................", ".....aaffffffffffda................", "....afffffffffffffda...............", "...afffffffffffffffda..............", "..afffffffffffffffffda.............", ".affffffffffffdddddffda............", ".afffffffffffdcccccffda............", ".afffffffffffffffddfffda...........", ".affffffffffffffdaafffda.....aa....", "afffffffdfffffffdaafffda....aeea...", "affffffdddfffffffffffffda..aaaeea..", "afffffdddddfffffffffffffdaaeeaaea..", "affffdddccdffffffffffffddaaaeeaeea.", "affffdddcddfffffffffffdaaeeabbaaea.", ".afffdddcddffffffffffdddabbaaeaaea.", ".affffdddcffffffffffdaaa.aeeaeeaeea", ".afffffddfffffffffffda...aebaebaeba", "..afffffffffffffffffda...aebaebaeba", "..afffffffffffffffffdaaa.aebaebaeba", "..affffffffffffffffffffdaebaaeaaea.", "..affffffffffffffffffffdabbaebaaea.", "..affffffffffffffffffffdaaaaebaeea.", "..affffffffffffffffffdda..aebaaea..", "..affffffffffffddddddaa....aaaeba..", "..afffffffffffdaaaaaa.......aeba...", "..afffffffffffda.............aa....", "..afffffffffffda...................", "..adddddddddddda...................", "...aaaaaaaaaaaa...................."] },
    'esquilo': { pal: ["#1A0B04", "#754D1C", "#B98D4E", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: ["..................a...a.........", "..........a.....aagaaagaaa......", ".........ada...agggggggggda.....", ".........ada..agggggggggggda....", "........aggda.aggggggggggggda...", ".......aaddda.agggggggggggggda..", "....aaagdaaa..agggggggggggggda..", "...agggggggda.agggggdddddggggda.", "..agggddggggdaaggggdcccccdgggda.", ".agggdaagggggdagggdccggdccdggda.", ".agggdaagggggdaggdccggggdccgggda", "addggggggggggdadgdcggggggdcgggda", ".aaggggggggggdaadccggggggdccggda", ".adddddgggggdagdadgggggggdccggda", "..abbbbggdddagggdagggggggdcgggda", "..abbbbddaaaggggdadgggggdccgggda", "..affffaaggggggggdagggddccggggda", ".afeeeefaggggggggdaggdcccgggggda", ".abeeeebaggggggggdadgggggggggda.", "..abeebaggggggggggdagggggggggda.", "...abbaggggggggggdaggggggggggda.", "....aagggggggggggdagggggggggda..", ".....adggdddddddddagggggggggda..", "......addaaaaaaaaadggggggggda...", ".......aaggggggggaadggggggda....", "......agggggggggggdaddgddda.....", ".....adggggggggggggdaadaaa......", "......addggggggggdda..a.........", ".......aaddddddddaa.............", ".........aaaaaaaa..............."] },
    'demonio': { pal: ["#1A0B04", "#754D1C", "#B98D4E", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: ["...aaa.................aaa....", "..afffa...............afffa...", "..afeba...............afeba...", "..afeba...............afeba...", "..afeba...............afeba...", "..aeeba...............afeba...", "...aeefa....aaaaaa...afeba....", "...abeefa.aaggggggaaafeeba....", "....abeefagggggggggdabeba.....", ".....abbagggggggggggdaba......", ".a....aagggggggggggggda.....a.", "agaa..agggggggggggggggda..aada", ".agda.agddggggggggggddda.agda.", ".adgdagdaaddggggggddaagdaggda.", "..agdagggdaaddggddaagggdagda..", "..addagggdddaagdaadddggdada...", "...adaggdaaddggggddaaggdada...", "....aaggdaaffgggdffaaggdaa....", ".....agggggggggggggggggda.....", ".....aggggggggddgggggggda.....", ".....agggggggdccgggggggda.....", "......agdggggggggggggdda......", "......adaddddddddddddada......", ".......adaaaaaaaaaaaada.......", "........adagaaaaaagada........", ".........adgaaaaaagda.........", "..........aagggggdaa..........", "...........adggggda...........", "............adggda............", ".............adda.............", "..............aa.............."] },
    'pistavoz': { pal: ["#1A0B04", "#51203E", "#7E3B4A", "#A65A34", "#C8987A", "#E2CB9C", "#E39A50", "#E8C69C", "#F7DCB6", "#F8D44A", "#FAD087", "#FFF6C4"], rows: ["............................aaaaaaaaaaa..........................................", ".........................aaakkkkkkkkkkkaaaa......................................", ".......................aaggkbbgggggggggkkkkaa........aa..........................", "......................aggbbbbbbbbbbbbbbggbbkgaa.....akka.........................", "....................aagbbbbbbbbbbbbbbbbbbbbbbgga...akkgga........................", "...................aggbbbbbbbbbbbbbbbbbbbbbbbbbga..agggda........................", "..................agbbbbbbbbbbbbbbbbbbbbbbbbbbbbga..agda.........................", ".................agbbbbbbbbbbbbbbbbbbbbbbbbbbbkbkga..aa..........................", ".................agbbbbbbbbbbbbbbbbbbbbbbbbbkkgkgba..............................", "................agbbbbbbbbbbbbbbbbbbbbbbbbkkggagaba..............................", "...............agbbbbbbbbbbbbbbbbbbbbbbkkkggaaaaha...............................", "...............agbbbbbbbbbbbbbbbbbbbbkkgggaaaaiiha...............................", "...............agbbbbbbbbbbbbbbbbbbbkggaaaaaiiiiha...............................", "..............agbbbbbbbbbbbbbbbbbbkkgaaaaaiiiiiiha...............................", "......cc......agbbbbbbbbbbbbbbbbkkggaaaiiiiiiiiiha...............................", "..............agbbbbbbbbbbbbbbkkggaaaiiiiiiiiiiiha...................aaa.........", "...........cc.agbbbbbbbbbbbbkkggaaaaiiiiiiiiiiiiiha.................alffa........", "...........c..agbbbbbbbbbbbkggaaaaiiiiiiiiiiiiiiiha.................allffa.......", "...........c..abbbbbbbbbbbkgaaaaiiiiiiiiiiiiiiiiiha.................alllfa.......", "...........c..abbbbbbbbbbkgaaaiiiiiiiiiiiiiiiiiiiha..................alllfa......", "..........c....abbbbbbbbdgaaiiiiiiiiiiiiieeeeiiiiha...................alllfa.....", "..........c....abbbbbbbddaaiiiiiiiiiiiiieiiiiiiiiha.............aa.....alllfa....", "..........c.....abbbbbddaaiiiiiiiiiiiiaiiiiiiiiiiha............alfa.....allfa....", "..........c......abbbddaaiiiiiiiiiiiiiiaaaaaaiiiiiha..........alllfa....alllfa...", "..........c......abbbdaiiiiiiiiiiiiiiiiialaaaaiiiiha...........alllfa....allfa...", ".jj.......c.......abaaiiiiiiiiiiiiiiiiiiiaaaiiiiiiha............alllfa....allfa..", ".jj.......c........aiiiiiiiiiiiiiiiiiiiiiieeiiiiiiiha............allfa....allfa..", ".........c.........aiiiiiaiiiiiiiiiiiiiiiiiiiiiiiiiha.....aaa....alllfa...alllfa.", ".........c........aaaaaaaiiiiiiiiiiiiiiiiiiiiiiiiiiiha...allfa....allfa....allfa.", ".j.......c.......aaaaalaiiiiiiiiiiiiiiiiiiiiiiiiiiiiha...alllfa....allfa...allfa.", "jjjccccccc.......aiiaaaiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha...allfa....allfa....allfa", ".j.......c......aiiieeiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha....allfa...allla....allfa", ".........c......aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiieeha....allfa....allfa...allfa", ".........c......aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiihaa......allfa...allfa...allfa", "..........c....aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha........allfa...allfa...allfa", "..........c....aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha........allfa...allfa...allfa", "..........c...aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha.........allla...allla....alla", "..........c...aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiieea..........alla....alla....alla", ".j........c...aheeiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha..........alla....alla....alla", "jjj.......c....aaiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha.........allla...allla....alla", ".j........c.....aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha..........allfa...allfa...allfa", "..........c.....aiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha..........allfa...allfa...allfa", "...........c....aeeiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha..........allfa...allfa...allfa", ".jj........c....ahiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiha.........allfa....allfa...allfa", ".jj........c.....aiiiiiiiiiiiiiiiiiiiiiiiiiiihhha..........allfa...allla....allfa", "...........c....aiiiiiiiiiiiiiiiiiiiiiiihhhhhaaa..........allfa....allfa....allfa", "...........c....aiiiiiiiiiiiiiiiiiieeeeeaaaaa............alllfa....allfa...allfa.", "...jj.......c...aiiiiiiiiiiiiiiiiiiieeaa................alllfa....allfa....allfa.", "...jj.......c...ahiiiiiiiiiiiiiiiiiiiha.................allfa....alllfa...alllfa.", ".............c...ahhhhiiiiiiiiiiiiiiiha..................aaa.....allfa....allfa..", ".............c....aaaaeeeeeeiiiiiiiiiha.........................alllfa....allfa..", ".....jj.......c.......aeeehhiiiiiiiiiha........................alllfa....allfa...", ".....jj.......cc.......ahhhhiiiiiiiiiha.......................alllfa....alllfa...", "........j......c.......aiiiiiiiiiiiiiha.......................allfa.....allfa....", ".......jjj......c......aiiiiiiiiiiiiiiha......................alfa.....alllfa....", "........j..j.....c.....aiiiiiiiiiiiiiiha.......................aa.....alllfa.....", "..........jjj.jj.......aiiiiiiiiiiiiiiha.............................alllfa......", "...........j..jj.......aiiiiiiiiiiiiiiiha...........................alllfa.......", "......................aiiiiiiiiiiiiiiiiiha.........................alllffa.......", "......................aiiiiiiiiiiiiiiiiiiha.......................alllffa........", "......................aiiiiiiiiiiiiiiiiiiiia......................allffa.........", ".......................aaaaaaaaaaaaaaaaaaaa.......................alfaa..........", "...................................................................aa............"], fino: 1 },
    'estourado': { pal: ["#1A0B04", "#754D1C", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: ["............................aa...", ".....................a.....adda..", "...aa.........aa....aea....adda..", "..accaaa.....aeea..aedea....aa...", "..accaccaa...addea.aedba...aa....", ".acafcafffaa..aedeaeddbaaaaeea...", ".acafcafffffaaabddedddbaeeeba....", "..aafcafffffffaabbbbbbbedddba....", "..aafcafffffffffaaaaaaabddba.....", ".aaafcacfffffffffcafffcabdba.....", "acaaffcafffffffffcaffffcaedeaaaa.", "acaaffcafffffffffcaffffcaeddeeeea", "acaaffcafffffffffcaffffcaedddbba.", "acaaffcafffffffffcaffffcaeddbaa..", "acaaffcafffffffffcaffffcaedba....", "acaaffcafffffffffcaffffcaedba....", "acaaffcafffffffffcaffffcaeddea...", ".aaafcafffffffffccaccccaeddddea..", "..aafcafffffffccaaaaaaaedbbbbbea.", "..aafcafffffccaaeeeeeeedbaaaaaa..", ".acafcafffccaaeeaedddbddba.......", ".acafcafccaaaaaaaeddbabdba.......", "..afcaccaa..a...aedba.abdda...aa.", "..accaaa........abdba..abba..adda", "...aa............aba....aa...adda", "..................a...........aa."] },
    'alien': { pal: ["#1A0B04", "#754D1C", "#CFB884", "#D9A942", "#EED26C", "#F4ECBC"], rows: ["..aa................aa..", ".aeea..............aeea.", "aeddea............aeddea", "aeddba............aeddba", "abddbaa..........aabddba", ".abbaeeaaaaaaaaaaeeabba.", "..aa.aaffffffffffaa.aa..", "....afffffffffffffca....", "...afffffffffffffffca...", "..afffffffffffffffffca..", ".afffffffffffffffffffca.", ".afffffffffffffffffffca.", "afffffffffffffffffffffca", "afccccccffffffffccccccca", "acaaaaaacffffffcaaaaaaca", "accaaffaacffffcaaaffafca", "accaaaaaaacffcaaaaaaafca", ".acaaaaaaaafcaaaaaaafca.", ".accaaaaaaafcaaaaaaafca.", "..accaaaaaafcaaaaaafca..", "...accaaaaafcaaaaafca...", "....afcaaaafcaaaafca....", "....acffffffffffffca....", ".....afffffffffffca.....", ".....afffffffffffca.....", "......afffffffffca......", "......acfffffffca.......", ".......acffffffca.......", "........acccccca........", ".........aaaaaa........."] },
    'generico': { pal: ["#1A0B04", "#CFB884", "#F4ECBC"], rows: ["...........aaa...........", "..........accba..........", "..........accba..........", "..........accba..........", "..........accba..........", "..........accba..........", "......aaa.accba..........", ".....accbaaccba..........", ".....accbaaccba.aaa......", ".....accbaaccbaaccba.....", ".....accbaaccbaaccba.....", ".....accbaaccbaaccba.....", ".aaa.accbaaccbaaccba.....", "accbaaccbaaccbaaccba.....", "accbaaccbaaccbaaccba.aaa.", "accbaaccbaaccbaaccbaaccba", "accbaaccbaaccbaaccbaaccba", "accbaaccbaaccbaaccbaaccba", "accbaaccbaaccbaaccbaaccba", "accbaaccbaaccbaaccbaaccba", "accbaaccbaaccbaaccbaaccba", "abbbaabbbaabbbaabbbaabbba", ".aaa..aaa..aaa..aaa..aaa."] },
    'pistavoz-1440': { pal: ["#FAD087", "#A65A34", "#E39A50", "#51203E", "#1A0B04", "#F7DCB6", "#E8C69C", "#C8987A", "#E2CB9C", "#FFF6C4", "#F8D44A", "#7E3B4A"], rows: [".......................eeee..................................", "...................eeeeaaaaeeeee.............................", ".................eecaaaccccaaaaaee......e....................", "................eccddddddddccccdacee...eae...................", "...............ecdddddddddddddddddcce.eacbe..................", "..............ecddddddddddddddddddddae.ebe...................", ".............ecdddddddddddddddddddaacce.e....................", "............ecddddddddddddddddddaaccede......................", "............ecddddddddddddddddaacceege.......................", "...........ecdddddddddddddddaacceeffge.......................", "...........ecdddddddddddddaacceeffffge.......................", ".....l.....ecdddddddddddaacceeffffffge.......................", ".........lecdddddddddddacceeffffffffge..............ee.......", ".........lecdddddddddaaceeffffffffffge.............ejie......", "........l..eddddddddaccefffffffffffffge............ejjie.....", "........l..edddddddaceeffffffffhhhfffge.............ejjie....", "........l..edddddbbceffffffffffffffffge.........ee...ejjie...", "........l...edddbbbefffffffffefffffffge........ejie...ejje...", ".......l....edddbeefffffffffffeeeeeffge........ejjie..ejjie..", ".kk....l.....eddeffffffffffffffejeefffge........ejje...ejje..", ".kk....l......eeffffffffffffffffhhffffge.........ejie...ejie.", ".......l......effffefffffffffffffffffffge...ee...ejjie..ejje.", ".k.....l.....eeeeeeffffffffffffffffffffge..ejie...ejje..ejje.", "kkklllll.....eeejeffffffffffffffffffffffge.ejjie..ejje...ejie", ".k.....l....effhhfffffffffffffffffffffffge..ejje...ejie..ejie", ".......l....efffffffffffffffffffffffffhge....ejie..ejje..ejje", ".......l...efffffffffffffffffffffffffgee.....ejje..ejje..ejje", ".......l...efffffffffffffffffffffffffge......ejje..ejje..ejje", ".k.....l..efffffffffffffffffffffffffhhe......ejje..ejje..ejje", "kkk.....l.egghfffffffffffffffffffffffge......ejje..ejje..ejje", ".k......l..eeffffffffffffffffffffffffge......ejje..ejje..ejje", "........l..egfffffffffffffffffffffffge.......ejje..ejje..ejje", "........l...ehhfffffffffffffffffffffge.......ejie..ejje..ejje", ".kk.....l...efffffffffffffffffffffffge......ejjie..ejie..ejje", ".kk.....l...efffffffffffffffffgggggge.......ejje...ejie..ejie", ".........l..efffffffffffffhhhheeeeee.......ejje...ejje...ejie", "..kk.....l..egffffffffffffffhe............ejjie...ejie..ejje.", "..kk.....ll..egggfffffffffffge.............eie...ejje...ejie.", "..........l...eeehhhhfffffffge..............e...ejjie..ejjie.", "...kk.....l......ehhgfffffffge.................ejjie...ejie..", "...kk.k....l.....egggfffffffge................ejjie...ejjie..", ".....kkk....l....effffffffffge................ejie...ejjie...", "......k..k...l...effffffffffge.................ee....ejje....", "........kkk......efffffffffffge.....................ejje.....", ".........k..kk...effffffffffffge...................ejjie.....", "............kk...effffffffffffffe...................eie......", "..................eeeeeeeeeeeeee.....................e......."], fino: 1 },
  };
  ICONES_PEDAL.mina = ICONES_PEDAL.estourado;   // a Mina DJ entra no lugar do alto-falante estourado
  // o esmalte de cada pedal, a cor do mock (a do celular segue no PEDAIS)
  const COR_PEDAL = {
    'radio-policia': [36, 88, 122], megafone: [212, 136, 24], locutor: [112, 58, 32], eco: [30, 100, 46],
    banheiro: [58, 124, 106], catedral: [124, 34, 46], robo: [156, 134, 114], 'voz-grossa': [82, 46, 28],
    esquilo: [220, 104, 36], demonio: [134, 32, 50], alien: [96, 124, 50], pistavoz: [88, 34, 80],
    estourado: [178, 42, 30], mina: [178, 42, 30],
  };
  const O = [26, 11, 4], CREME = [248, 236, 208], SOMBRA = [12, 5, 2];
  // a moldura do Troca de voz, de 3 celulas da de fora para a de dentro (revisao da r05): em cima e a esquerda pegando a
  // luz, a de fora clara; embaixo e a direita a rampa invertida, a de fora escura e a de dentro pegando a luz, como a
  // beira do feltro (revisao da r06). Os cantos de baixo a esquerda e de cima a direita ficam com o lado claro
  const OURO_LUZ = [[255, 240, 154], [242, 193, 74], [181, 132, 31]], OURO_SOMBRA = [[128, 92, 22], [181, 132, 31], [242, 193, 74]];
  // o visor: o vidro quase preto com a borda de dentro mais escura e, no pedal ligado, o miolo com a luz de fundo ambar
  // escura (revisao da r04); a letra acesa em ambar vivo, a do pedal desligado e o aro dos blocos vazios em ambar apagado
  const VIDRO = [26, 13, 5], VIDRO_BORDA = [6, 3, 1], VIDRO_ACESO = [67, 28, 8];
  // AMBAR_VAZIO: as casas vazias da barra de blocos de 2 (o LISTENING), mais escuras que o ambar apagado (revisao da
  // r14: a 3,2:1 das acesas a barra com 3 de 6 lia cheia)
  const AMBAR = [255, 178, 46], AMBAR_OFF = [150, 88, 30], AMBAR_VAZIO = [110, 58, 18];
  const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const mix = (a, b, t) => [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * t));
  const mul = (a, k) => a.map(v => Math.max(0, Math.min(255, Math.round(v * k))));
  const hs = (x, y, s) => { const v = Math.sin(x * 127.1 + y * 311.7 + s * 74.7) * 43758.5453; return v - Math.floor(v); };
  const ICONES_RGB = new Map();
  const corDoIcone = ic => { let p = ICONES_RGB.get(ic); if (!p) { p = ic.pal.map(rgb); ICONES_RGB.set(ic, p); } return p; };

  // a tela em celulas (1 px do canvas = 1 celula)
  function tela(W, H) {
    const u = new Uint8ClampedArray(W * H * 4);
    const T = {
      W, H, u,
      px(x, y, c, a = 1) {
        if (x < 0 || y < 0 || x >= W || y >= H) return;
        const i = (y * W + x) * 4, b = u[i + 3] / 255;
        if (a >= 1 || !b) { u[i] = c[0]; u[i + 1] = c[1]; u[i + 2] = c[2]; u[i + 3] = a >= 1 ? 255 : Math.round(a * 255); return; }
        const s = a + b * (1 - a);
        for (let k = 0; k < 3; k++) u[i + k] = Math.round((c[k] * a + u[i + k] * b * (1 - a)) / s);
        u[i + 3] = Math.round(s * 255);
      },
    };
    return T;
  }

  // ---- as letras: a dos nomes (3 x 7) e as do visor (as de LCD, 9 de altura, so maiusculas sem acento): a de 4 de
  // largura e as largas da revisao da r06, a da voz (6, passo de 7) e a das frases (5, passo de 6), as duas com o espaco
  // de 2 (4 celulas entre as palavras) e o fino de 1 (3 celulas). A largura conta 1 celula entre as letras; a escrita leva o contorno de 1 celula
  // (os nomes) ou nenhum (o visor) e corta no lim
  const PED = { g: LETRA_PEDAL, cap: 7, id: 'p' }, LCD = { g: LETRA_LCD, cap: 9, id: 'l' };
  const LCD_VOZ = { g: LETRA_LCD_VOZ, cap: 9, id: 'v' }, LCD_FRASE = { g: LETRA_LCD_FRASE, cap: 9, id: 'f' };
  const glifo = (ch, F) => F.g[ch] || F.g[' '];
  const temTudo = (s, F) => [...s].every(ch => F.g[ch]);
  const acento = (g, F) => g.length - F.cap === 3;
  // a largura que a letra ocupa na linha: a das linhas da maiuscula (o agudo inclinado do I sai para o vao da direita)
  const AVANCO = new Map();
  function avanco(ch, F) {
    const k = F.id + ch;
    let a = AVANCO.get(k);
    if (a === undefined) {
      const g = glifo(ch, F), i0 = acento(g, F) ? 3 : 0;
      a = Math.max(0, ...g.slice(i0, i0 + F.cap).map(r => r.lastIndexOf('#') + 1)) || g[0].length;
      AVANCO.set(k, a);
    }
    return a;
  }
  function largura(s, F = PED) {
    let w = 0, n = 0;
    for (const ch of s) { w += avanco(ch, F); n++; }
    return w + Math.max(0, n - 1);
  }
  // as letras que saem do T quando a celula nao cai num numero inteiro de px da tela (o palco de 1440: 1,5 px; revisao
  // da r09): cada texto guarda os glifos dele, e o pintaTela os pinta depois na resolucao da tela; null = no T
  let FORA = null;
  // os glifos de um texto: a origem de cada letra em celulas (a mesma conta do celulas) e as linhas dela
  function glifos(s, x0, yCap, F = PED) {
    const out = [];
    let x = x0;
    for (const ch of s) {
      const g = glifo(ch, F);
      out.push({ x, y: yCap, rows: g, acc: acento(g, F) });
      x += avanco(ch, F) + 1;
    }
    return out;
  }
  // as celulas [x, y] da letra de um texto
  function celulas(s, x0, yCap, F = PED, lim = [-1e9, 1e9]) {
    const out = [];
    let x = x0;
    for (const ch of s) {
      const g = glifo(ch, F), topo = yCap - (acento(g, F) ? 3 : 0);
      g.forEach((row, j) => { for (let i = 0; i < row.length; i++) if (row[i] === '#' && x + i >= lim[0] && x + i < lim[1]) out.push([x + i, topo + j]); });
      x += avanco(ch, F) + 1;
    }
    return out;
  }
  function escreve(T, s, x0, yCap, cor, contorno, F = PED, lim = [0, T.W]) {
    const on = new Set(celulas(s, x0, yCap, F, lim).map(([x, y]) => y * T.W + x));
    if (contorno) for (const k of on) {
      const px = k % T.W, py = (k - px) / T.W;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++)
        if (px + dx >= 0 && px + dx < T.W && !on.has((py + dy) * T.W + px + dx)) T.px(px + dx, py + dy, contorno);
    }
    if (FORA) {   // a letra vai por cima depois; no T fica o contorno por baixo dela (ou o fundo, sem contorno)
      if (contorno) for (const k of on) T.px(k % T.W, (k - k % T.W) / T.W, contorno);
      FORA.push({ glifos: glifos(s, x0, yCap, F), cor, placa: contorno, lim });
      return;
    }
    for (const k of on) T.px(k % T.W, (k - k % T.W) / T.W, cor);
  }
  // o nome no pedal: no menor numero de linhas que cabe (ate maxLin), quebrando no espaco, no hifen ou no hifen opcional,
  // com as linhas mais parecidas; nao cabendo, uma linha so (cortada pela beira do pedal)
  function arrumaNome(nome, maxW, maxLin = 3) {
    const N = nome.toUpperCase(), sem = s => s.replace(/­/g, '').trim();
    const cortes = [];
    for (let i = 0; i < N.length; i++) if (N[i] === ' ' || N[i] === '-' || N[i] === '­') cortes.push(i);
    const linhas = cs => {
      const out = [];
      let ini = 0;
      for (const c of cs) { out.push(sem(N.slice(ini, c) + (N[c] === ' ' ? '' : '-'))); ini = c + 1; }
      out.push(sem(N.slice(ini)));
      return out;
    };
    const combos = n => n === 0 ? [[]] : n === 1 ? cortes.map(c => [c]) : cortes.flatMap((a, i) => cortes.slice(i + 1).map(b => [a, b]));
    for (let n = 0; n < maxLin; n++) {
      let melhor = null;
      for (const cs of combos(n)) {
        const l = linhas(cs), m = Math.max(...l.map(s => largura(s)));
        if (l.every(s => s) && m <= maxW && (!melhor || m < melhor.m)) melhor = { m, l };
      }
      if (melhor) return melhor.l;
    }
    return [sem(N)];
  }
  // o topo das maiusculas de cada linha (revisao da r02): uma linha na mesma altura nos doze; duas com passo de 13 (revisao
  // da r05: com 12 o contorno do acento da de baixo encostava no da de cima, o I de POLICIA colava no O de RADIO; o
  // bloco subiu 1, e o icone mais alto, o radio com a antena, acaba 5 celulas antes do contorno do acento); tres com
  // passo de 9. O bloco fica a 4 celulas ou mais do icone e do LED. Na r09 tudo 2 celulas mais baixo (o pedal 14 px
  // mais alto, revisao da r08: 4 px a mais acima do icone)
  const TOPOS = { 1: [51], 2: [46, 59], 3: [41, 50, 59] };
  const linhasNome = (l, cx, topos) => l.map((s, k) => [s, Math.round(cx - largura(s) / 2), topos[Math.min(k, topos.length - 1)]]);
  // o nome inteiro de uma vez (revisao da r05): o contorno e o do bloco (as letras de todas as linhas e a volta de 8
  // delas), e o furo de 1 celula que sobra dentro dele (3 ou 4 dos vizinhos de cima, de baixo e dos lados no bloco) vira
  // contorno: no de 3 linhas sobravam celulas de esmalte soltas entre as linhas. Uma segunda passada fecha o que a
  // primeira cercou (revisao da r09: a celula de esmalte solta na baia do C de ECO, LOCUTOR FM, CATEDRAL, POLICIA e TROCA
  // DE VOZ, com os 4 vizinhos ja no bloco). A fresta de 1 celula entre duas linhas, com 2 vizinhos, fica aberta
  function escreveNome(T, l, cx, topos, cor, contorno) {
    const on = new Set(), bloco = new Set(), chave = (x, y) => y * T.W + x;
    for (const [s, x, y] of linhasNome(l, cx, topos)) for (const [a, b] of celulas(s, x, y)) if (a >= 0 && a < T.W) on.add(chave(a, b));
    for (const k of on) {
      const x = k % T.W, y = (k - x) / T.W;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (x + dx >= 0 && x + dx < T.W) bloco.add(chave(x + dx, y + dy));
    }
    const dentro = (x, y) => x >= 0 && x < T.W && bloco.has(chave(x, y));
    const furos = [];
    for (const k of bloco) {
      const x = k % T.W, y = (k - x) / T.W;
      for (const [fx, fy] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {
        if (fx < 0 || fx >= T.W || bloco.has(chave(fx, fy))) continue;
        if ([[1, 0], [-1, 0], [0, 1], [0, -1]].filter(([i, j]) => dentro(fx + i, fy + j)).length >= 3) furos.push(chave(fx, fy));
      }
    }
    for (const k of furos) bloco.add(k);
    const cercados = [];
    for (const k of bloco) {
      const x = k % T.W, y = (k - x) / T.W;
      for (const [fx, fy] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]])
        if (fx >= 0 && fx < T.W && !bloco.has(chave(fx, fy)) && [[1, 0], [-1, 0], [0, 1], [0, -1]].every(([i, j]) => dentro(fx + i, fy + j)))
          cercados.push(chave(fx, fy));
    }
    for (const k of cercados) bloco.add(k);
    // o esmalte preso dentro da placa (a calha de 1 x 5 entre o L e o A de FALANTE: as passadas de cima so viam a ponta
    // dela): o que nao chega a beira da caixa do bloco andando por fora dele vira contorno; a fresta entre as linhas e
    // o recorte aberto para fora seguem abertos
    let xa = Infinity, xb = -Infinity, ya = Infinity, yb = -Infinity;
    for (const k of bloco) { const x = k % T.W, y = (k - x) / T.W; xa = Math.min(xa, x); xb = Math.max(xb, x); ya = Math.min(ya, y); yb = Math.max(yb, y); }
    const solto = new Set(), fila = [];
    for (let y = ya; y <= yb; y++) for (let x = xa; x <= xb; x++)
      if ((x === xa || x === xb || y === ya || y === yb) && !bloco.has(chave(x, y))) { solto.add(chave(x, y)); fila.push([x, y]); }
    while (fila.length) {
      const [x, y] = fila.pop();
      for (const [i, j] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const X = x + i, Y = y + j, c = chave(X, Y);
        if (X >= xa && X <= xb && Y >= ya && Y <= yb && !bloco.has(c) && !solto.has(c)) { solto.add(c); fila.push([X, Y]); }
      }
    }
    for (let y = ya; y <= yb; y++) for (let x = xa; x <= xb; x++) if (!solto.has(chave(x, y))) bloco.add(chave(x, y));
    for (const k of bloco) if (FORA || !on.has(k)) T.px(k % T.W, (k - k % T.W) / T.W, contorno);
    if (FORA) {   // as letras vao por cima depois, linha a linha; no T fica a placa inteira
      for (const [t, x, y] of linhasNome(l, cx, topos)) FORA.push({ glifos: glifos(t, x, y), cor, placa: contorno, lim: [0, T.W] });
      return;
    }
    for (const k of on) T.px(k % T.W, (k - k % T.W) / T.W, cor);
  }
  // ---- a tela na resolucao da tela (revisao da r09): com s px de tela por celula fora de um inteiro (1,5 no palco de
  // 1440), o T mostrado pelo navegador saia com a mesma letra em traco de 1 ou de 2 px conforme a fase (o O de VOZ GRAVE
  // lia 0, o U de ESTOURADO com pernas diferentes). Aqui a celula i do T vai para os px [round(i*s), round((i+1)*s)), e
  // as letras saem glifo a glifo, cada linha de glifos num passo fixo em px (as colunas do glifo e o vao), centrada na
  // conta das celulas, e cada glifo no topo inteiro round(topo*s), com a largura de cada coluna e de cada linha tirada so
  // do tamanho do glifo: a mesma letra com os mesmos px em todo pedal
  //
  // a largura em px de cada uma das n celulas de um glifo, simetrica: de fora para dentro, cada uma pelo arredondamento
  // mais perto da conta exata, e no empate (o 1,5) fina nas colunas e no acento e grossa nas linhas (com 1,5: colunas
  // 3 = 1 2 1, 4 = 1 2 2 1, 5 = 1 2 1 2 1; linhas 7 = 2 1 2 1 2 1 2, as 9 do LCD = 2 1 2 1 2 1 2 1 2; o acento 1 2 1,
  // para cima; com s perto de 2,63, a janela maximizada de 2560 x 1440, colunas 3 = 3 2 3). A soma pode passar da conta
  // exata (3 colunas com 2,63 = 8 px, contra 7,9): a placa em volta cobre a sobra. Entre 1,75 e 2,5 (a janela maximizada
  // de 1920 x 1080, 1,94) as letras nao passam aqui: saem nativas (o nativo, abaixo)
  const FAIXAS = new Map();
  function faixas(n, s, grossa) {
    const k = n + '|' + s + '|' + grossa;
    let t = FAIXAS.get(k);
    if (!t) {
      const f = v => Math.round(Math.round(v * 1e6) / 1e6 + (grossa ? 1e-3 : -1e-3)), w = new Array(n), o = [0];
      for (let j = 0; j < n / 2; j++) w[j] = w[n - 1 - j] = f((j + 1) * s) - f(j * s);
      for (let j = 0; j < n; j++) o.push(o[j] + w[j]);
      t = { w, o };
      FAIXAS.set(k, t);
    }
    return t;
  }
  // as pecas nativas (revisao da r12): entre 0,875 e 1,25 px de tela por px do palco fora da escala inteira (a janela
  // maximizada, 0,97), os icones de 2 px, as placas de nome, os rotulos MINA e LIRA, o LED (aceso e apagado) e o
  // conteudo do visor (a palavra com a barra do OUVINDO ou o visto do PRONTO) saem no
  // tamanho de 1920, 2 px de tela por celula, em px inteiro e centrados na caixa de cada um: com a celula de 1,94 px a
  // grade das celulas comia 1 coluna e 1 linha dos icones e 1 linha do bulbo do LED, e abria vaos de 1, 3 e 5 px nos
  // nomes. O nativo desenha a peca numa tela propria (as mesmas celulas do T, com as letras celula a celula) e a guarda
  // com a caixa dela (a dada, ou a das celulas pintadas); o pintaTela a pinta por cima do T, que fica sem ela. Fora dessa
  // faixa (NATIVO null), a peca vai direto no T, como sempre
  let NATIVO = null;
  function nativo(T, caixa, fn) {
    if (!NATIVO) { fn(T); return; }
    const P = tela(T.W, T.H), fora = FORA;
    FORA = null;
    try { fn(P); } finally { FORA = fora; }
    if (!caixa) {
      let xa = Infinity, ya = Infinity, xb = -1, yb = -1;
      for (let j = 0; j < P.H; j++) for (let i = 0; i < P.W; i++)
        if (P.u[(j * P.W + i) * 4 + 3]) { xa = Math.min(xa, i); xb = Math.max(xb, i); ya = Math.min(ya, j); yb = Math.max(yb, j); }
      if (xb < 0) return;
      caixa = [xa, ya, xb - xa + 1, yb - ya + 1];
    }
    NATIVO.push({ P, caixa });
  }
  function pintaTela(cv, T, s, ped) {
    const W = Math.round(T.W * s), H = Math.round(T.H * s), u = new Uint8ClampedArray(W * H * 4);
    const para = (n, N) => {   // o px de tela -> a celula dele
      const m = new Int32Array(N);
      for (let i = 0; i < n; i++) for (let p = Math.round(i * s), b = Math.min(N, Math.round((i + 1) * s)); p < b; p++) m[p] = i;
      return m;
    };
    const mx = para(T.W, W), my = para(T.H, H), de = new Uint32Array(T.u.buffer), em = new Uint32Array(u.buffer);
    for (let y = 0; y < H; y++) for (let x = 0, a = my[y] * T.W, b = y * W; x < W; x++) em[b + x] = de[a + mx[x]];
    const pinta = (i, c) => { u[i * 4] = c[0]; u[i * 4 + 1] = c[1]; u[i * 4 + 2] = c[2]; u[i * 4 + 3] = 255; };
    // as pecas nativas por cima do T: cada celula em 2 x 2 px, a caixa centrada onde as celulas a punham
    for (const { P, caixa: [bx, by, bw, bh] } of NATIVO || []) {
      const X0 = Math.round((bx + bw / 2) * s - bw), Y0 = Math.round((by + bh / 2) * s - bh);
      for (let j = 0; j < P.H; j++) for (let i = 0; i < P.W; i++) {
        const a = (j * P.W + i) * 4, al = P.u[a + 3] / 255;
        if (!al) continue;
        for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) {
          const X = X0 + 2 * (i - bx) + dx, Y = Y0 + 2 * (j - by) + dy;
          if (X < 0 || Y < 0 || X >= W || Y >= H) continue;
          const q = (Y * W + X) * 4;
          for (let c = 0; c < 3; c++) u[q + c] = Math.round(P.u[a + c] * al + u[q + c] * (1 - al));
          u[q + 3] = Math.max(u[q + 3], P.u[a + 3]);
        }
      }
    }
    // o vao de 1 celula entre dois glifos em px inteiros, o mesmo na linha toda (2 com 1,5; 3 com 2,63)
    const vao = faixas(1, s, true).w[0];
    for (const txt of FORA) {
      const x0 = Math.round(txt.lim[0] * s), x1 = Math.round(txt.lim[1] * s), feitos = new Set();
      // a origem de cada glifo em px: a do anterior mais as colunas dele em px e o vao; a fila inteira centrada onde as
      // celulas a punham (a origem de cada um em round(x * s) deixava o vao com 1 ou 2 px conforme a fase: o vao
      // depois do N em 1440)
      const gs = txt.glifos, ox = [0];
      for (let i = 1; i < gs.length; i++) {
        const a = gs[i - 1], na = Math.max(...a.rows.map(r => r.length));
        ox.push(ox[i - 1] + faixas(na, s, false).o[Math.min(na, gs[i].x - a.x - 1)] + vao);
      }
      const ini = gs.length ? Math.round(gs[0].x * s + ((gs[gs.length - 1].x - gs[0].x) * s - ox[ox.length - 1]) / 2) : 0;
      for (const [i, gl] of gs.entries()) {
        const corpo = gl.acc ? gl.rows.slice(3) : gl.rows, n = Math.max(...gl.rows.map(r => r.length));
        const C = faixas(n, s, false), L = faixas(corpo.length, s, true), A = faixas(3, s, false);
        const gx = ini + ox[i], gy = Math.round(gl.y * s);
        gl.rows.forEach((r, j) => {
          // a linha j em px: no corpo, de cima para baixo a partir do topo das maiusculas; no acento, para cima dele
          const [ya, yb] = gl.acc && j < 3 ? [gy - A.o[3] + A.o[j], gy - A.o[3] + A.o[j + 1]] : (k => [gy + L.o[k], gy + L.o[k + 1]])(gl.acc ? j - 3 : j);
          for (let i = 0; i < r.length; i++) {
            const c = r[i] === '#' ? txt.cor : r[i] === '+' ? txt.cor2 : null;
            if (!c) continue;
            for (let y = Math.max(0, ya); y < Math.min(H, yb); y++)
              for (let x = Math.max(x0, gx + C.o[i]); x < Math.min(x1, W, gx + C.o[i + 1]); x++) { pinta(y * W + x, c); feitos.add(y * W + x); }
          }
        });
      }
      // a placa cresce onde a letra encostou na beira dela: o contorno nunca abre e fica com a largura de 1 celula da tela
      // (1 px com 1,5, como na r10; 2 com 2,63)
      const g = Math.max(1, Math.round(s - .25));
      if (txt.placa) for (const k of feitos) {
        const x = k % W, y = (k - x) / W;
        for (let dy = -g; dy <= g; dy++) for (let dx = -g; dx <= g; dx++) {
          const X = x + dx, Y = y + dy, q = Y * W + X;
          if (X < 0 || Y < 0 || X >= W || Y >= H || feitos.has(q)) continue;
          if (u[q * 4] !== txt.placa[0] || u[q * 4 + 1] !== txt.placa[1] || u[q * 4 + 2] !== txt.placa[2] || u[q * 4 + 3] !== 255) pinta(q, txt.placa);
        }
      }
      // o realce do mouse e do foco (txt.realce, a moldura ambar do rotulo da voz): em volta da letra como ela saiu aqui,
      // 2 celulas da letra ate a moldura nos quatro lados, como em 1920, e o traco de 1 celula da tela; na grade das
      // celulas do T a letra posta glifo a glifo ficava fora do meio dela (o MINA de 1440: 2 px ate a moldura a esquerda
      // e 4 a direita, o traco com 2 px de um lado e 1 do outro)
      if (txt.realce && feitos.size) {
        let xa = W, xb = -1, ya = H, yb = -1;
        for (const k of feitos) { const x = k % W, y = (k - x) / W; xa = Math.min(xa, x); xb = Math.max(xb, x); ya = Math.min(ya, y); yb = Math.max(yb, y); }
        const d = Math.round(2 * s) + g;
        for (let y = ya - d; y <= yb + d; y++) for (let x = xa - d; x <= xb + d; x++)
          if ((x < xa - d + g || x > xb + d - g || y < ya - d + g || y > yb + d - g) && x >= 0 && y >= 0 && x < W && y < H) pinta(y * W + x, txt.realce);
      }
    }
    const fx = ped ? folga(W, 1, s / 2) : 0, fy = ped ? folga(H, 1, s / 2) : 0;
    cv.width = W + fx; cv.height = H + fy;
    cv.getContext('2d').putImageData(new ImageData(u, W, H), 0, 0);
    // exatamente 1 px do canvas por px da tela: o tamanho CSS e o 2 * T.W de sempre menos a fracao do round, que cai na
    // margem transparente da sombra (sem isso o navegador comia 1 coluna no pedal de 98, 51 celulas = 76,5 px). Com o ped
    // (fora da grade de 1/4 de px da tela, a janela maximizada) a origem vai para o px inteiro mais perto, como a das
    // pecas de 1 px: na origem fracionaria a amostra do navegador dobrava 1 coluna de letra aqui e ali. Na grade (o palco
    // de 1440, 0,75: a origem em meio px ou inteira) ele ja amostra certo, e o canvas fica onde estava
    if (ped) pecaNaTela(ped, cv, W, H, W / s, H / s, W + fx, H + fy);
    else Object.assign(cv.style, { left: '', top: '', width: 2 * W / s + 'px', height: 2 * H / s + 'px' });
  }
  // as celulas perto da letra, que o brilho do LED nao pinta: a letra, o contorno dela e mais 1 celula de esmalte em volta
  function pertoDe(cels) {
    const perto = new Set();
    for (const [x, y] of cels) for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) perto.add((x + dx) + ',' + (y + dy));
    return (x, y) => perto.has(x + ',' + y);
  }
  // a moldura de 1 celula (o realce do mouse e do foco do teclado no rotulo da voz)
  function moldura(T, x0, y0, w, h, cor) {
    for (let i = 0; i < w; i++) { T.px(x0 + i, y0, cor); T.px(x0 + i, y0 + h - 1, cor); }
    for (let j = 1; j < h - 1; j++) { T.px(x0, y0 + j, cor); T.px(x0 + w - 1, y0 + j, cor); }
  }

  // ---- as pecas
  // liso: a caixa do icone, que com 1 celula de margem fica sem o salpico do esmalte (o detalhe fino em cima do liso)
  function corpo(T, cw, ch, base, ouro, seed, liso) {
    const luz = mix(base, [255, 250, 236], .24), esc = mul(base, .56), parede = mul(base, .64), junta = mix(base, O, .5);
    // os cantos cortados numa escada de 45 graus de 3 celulas (revisao da r07: com 2 o pedal lia como cartao): o
    // contorno, o bisel, a sombra e, no Troca de voz, a moldura seguem o corte
    const dentro = (x, y) => x >= 0 && y >= 0 && x < cw && y < ch && Math.min(x, cw - 1 - x) + Math.min(y, ch - 1 - y) >= 4;
    for (let y = 0; y < ch + 2; y++) for (let x = 0; x < cw + 1; x++)   // a sombra dura no feltro, 1 celula a direita e 2 abaixo
      if (!dentro(x, y) && dentro(x - 1, y - 2)) T.px(x, y, SOMBRA, .5);
    const noLiso = (x, y) => liso && x >= liso[0] - 1 && x <= liso[0] + liso[2] && y >= liso[1] - 1 && y <= liso[1] + liso[3];
    const face = (x, y) => {
      const h = noLiso(x, y) ? .5 : hs(x, y, seed), k = (1.05 - .1 * y / ch) * (h < .07 ? .9 : h > .95 ? 1.08 : 1);
      return mul(base, k);
    };
    for (let y = 0; y < ch; y++) for (let x = 0; x < cw; x++) {
      const ex = Math.min(x, cw - 1 - x), ey = Math.min(y, ch - 1 - y), d = Math.min(ex, ey), s = ex + ey;
      if (s < 4) continue;
      const cimaEsq = ey <= ex ? y < ch / 2 : x < cw / 2;
      let c;
      if (d === 0 || s === 4) c = O;
      else if (ouro && y < ch - 4) {
        // a moldura do Troca de voz, de 3 celulas (revisao da r05), por dentro do contorno e fechando logo acima da parede
        // da frente, que e a mesma dos outros (revisao da r05); a camada e a distancia a beira (nos cantos de cima, ao
        // chanfro), e a luz vem de cima a esquerda (revisao da r04)
        const k = Math.min(ex, y, ch - 4 - y, s - 4);
        if (k <= 3) c = ((x < cw / 2 && ex <= 3) || (y < ch / 2 && y <= 3) ? OURO_LUZ : OURO_SOMBRA)[k - 1];
        else c = face(x, y);
      } else if (d === 1 || s === 5) c = cimaEsq ? luz : esc;
      else if (y >= ch - 4) c = y === ch - 4 ? junta : parede;
      else c = face(x, y);
      T.px(x, y, c);
    }
  }
  // parafuso de latao de 3 x 3 celulas, a fenda no meio, e a sombra na linha de baixo
  const PARAFUSO = ['abc', 'bxd', 'cdd'];
  const COR_PARAFUSO = { a: [255, 236, 170], b: [230, 190, 96], c: [182, 132, 48], d: [112, 72, 24], x: [70, 42, 14] };
  function parafuso(T, x0, y0) {
    PARAFUSO.forEach((r, j) => { for (let i = 0; i < 3; i++) T.px(x0 + i, y0 + j, COR_PARAFUSO[r[i]]); });
    T.px(x0 + 1, y0 + 3, O, .35); T.px(x0 + 2, y0 + 3, O, .35);
  }
  // o lugar do icone (centrado na faixa de y0 a y1, em celulas) e o desenho dele ali. O icone fino (fino: 1, o do Troca
  // de voz: a cabeca do mock com as duas caras, na grade de 1 px que o dono liberou para elas lerem) ocupa as celulas
  // que cobre e vai por cima do canvas, no iconeFino
  function caixaIcone(ic, cx, y0, y1) {
    const f = ic.fino ? 2 : 1, h = Math.ceil(ic.rows.length / f), w = Math.ceil(ic.rows[0].length / f);
    return [Math.round(cx - w / 2), y0 + Math.max(0, Math.floor((y1 - y0 - h) / 2)), w, h];
  }
  function icone(T, ic, [xa, ya]) {
    const pal = corDoIcone(ic), w = ic.rows[0].length;
    ic.rows.forEach((r, j) => { for (let i = 0; i < w; i++) { const k = r.charCodeAt(i) - 97; if (k >= 0) T.px(xa + i, ya + j, pal[k]); } });
  }
  // as pecas na grade de 1 px (o icone fino e o footswitch) conforme os px de tela por px do palco (kd, revisao da r10):
  // num inteiro, e acima de 1 fora dos multiplos de 0,75, como sempre (em px do palco); de 0,875 a 1, o mesmo desenho
  // 1:1 em px de tela; abaixo de 0,875 (o palco de 1440, 0,75: a escala perdia 1 linha de cada 4, e a lisa borrava), o
  // desenho feito a mao para la, tambem 1:1; num multiplo inteiro de 0,75 (o notebook dele, 1,5): o desenho de 0,75 em
  // m x m px de tela por px. Fora do primeiro caso a peca fica centrada no ponto de sempre, com a origem num px inteiro
  // da tela, e o footswitch vai em canvas tambem de 0,875 a 1 (o SVG escalado pelo palco saia borrado)
  const inteiro = v => Math.abs(v - Math.round(v)) < 1e-6;
  const regime = kd => inteiro(kd) || (kd > 1 && !inteiro(kd / .75)) ? { rg: 0, m: 1 }
    : inteiro(kd / .75) ? { rg: 2, m: Math.round(kd / .75) } : { rg: kd < .875 - 1e-6 ? 2 : 1, m: 1 };
  // pe el (w x h px de tela) centrado em (cx, cy), em px do pedal b, com a origem num px inteiro da tela; pw x ph e o
  // tamanho do canvas com a folga (abaixo), que fica a direita e embaixo, transparente
  function pecaNaTela(b, el, w, h, cx, cy, pw = w, ph = h) {
    const r = b.getBoundingClientRect(), k = PALCO.k, d = devicePixelRatio || 1;
    const X = Math.round((r.left + cx * k) * d - w / 2), Y = Math.round((r.top + cy * k) * d - h / 2);
    Object.assign(el.style, { left: (X / d - r.left) / k + 'px', top: (Y / d - r.top) / k + 'px', width: pw / (k * d) + 'px', height: ph / (k * d) + 'px' });
  }
  // a folga de um canvas de n px de desenho mostrados a m x m px de tela por px, com kd px de tela por px do palco: os px
  // transparentes a mais (a direita ou embaixo) que poem o tamanho css (m * n / kd) num multiplo de 1/64 de px, o passo
  // do layout do navegador. Fora dele o navegador guardava o tamanho um pouco menor e cortava o ultimo px de tela: no
  // notebook (kd 1,5) o icone do Troca de 61 px, 122 px de tela, pedia 81,333 px css, ficava com 81,328 e perdia a
  // ultima coluna; com 63 px (84 px css) ela fica. Sem folga possivel ate 16 px (a janela maximizada, kd 1009 / 1040), 0
  function folga(n, m, kd) {
    for (let f = 0; f < 16; f++) { const v = m * (n + f) / kd * 64; if (Math.abs(v - Math.round(v)) < 1e-6) return f; }
    return 0;
  }
  // um canvas com um desenho de 1 px por pixel (rows: as linhas; cor: a cor de cada letra, ou a da paleta do icone)
  function pecaCanvas(c, rows, cor, fx = 0, fy = 0) {
    const w = rows[0].length, h = rows.length, T = tela(w, h);
    rows.forEach((r, j) => { for (let i = 0; i < w; i++) { const q = cor(r[i]); if (q) T.px(i, j, q, q[3] === undefined ? 1 : q[3]); } });
    telaNoCanvas(c, T, fx, fy);
  }
  // o T no canvas, no canto de cima a esquerda, com fx x fy px transparentes a mais (a folga)
  function telaNoCanvas(c, T, fx = 0, fy = 0) {
    c.width = T.W + fx; c.height = T.H + fy;
    c.getContext('2d').putImageData(new ImageData(T.u, T.W, T.H), 0, 0);
  }
  // o icone fino: um canvas de 1 px por pixel; no regime 0 no canto de cima a esquerda da caixa dele, em px do palco, e
  // nos outros centrado nela em px de tela (m x m por px do desenho); o desenho e o de 1920, ou o de 1440 no regime 2
  // (abaixo de 0,875 e nos multiplos inteiros de 0,75), repintado so quando muda
  function iconeFino(b, ic, [xa, ya], kd) {
    let c = b.querySelector(':scope > canvas.ico-fino');
    if (!ic.fino) { if (c) c.remove(); return; }
    if (!c) {
      c = document.createElement('canvas');
      c.className = 'ico-fino'; c.setAttribute('aria-hidden', 'true');
      b.append(c);
    }
    const { rg, m } = regime(kd), d = rg === 2 && ICONES_PEDAL['pistavoz-1440'] || ic;
    const dw = d.rows[0].length, dh = d.rows.length, f = rg ? [folga(dw, m, kd), folga(dh, m, kd)] : [0, 0];
    if (c._ic !== d || c._f !== f.join()) {
      const pal = corDoIcone(d);
      pecaCanvas(c, d.rows, ch => { const k = ch.charCodeAt(0) - 97; return k >= 0 ? pal[k] : null; }, ...f);
      c._ic = d; c._f = f.join();
    }
    const w = ic.rows[0].length, h = ic.rows.length;
    if (rg === 0) Object.assign(c.style, { left: 2 * xa + 'px', top: 2 * ya + 'px', width: '', height: '' });
    else pecaNaTela(b, c, m * dw, m * dh, 2 * xa + w / 2, 2 * ya + h / 2, m * c.width, m * c.height);
  }
  // o LED de 8 x 8 celulas. Apagado, a cupula escura com o aro e o reflexo. Aceso, a variante E da folha de 21/11, que o
  // dono escolheu entre 5 (decisao fechada: as revisoes pediam o oposto a cada rodada): o aro de 1 celula em vermelho
  // escuro #a8200f nas mesmas celulas do aro do apagado, o miolo da r08 (o corpo #ff4a1c, o realce de 2 x 2 quase branco
  // no alto a esquerda cercado de #ffb070 e a sombra #e44618 por dentro do aro embaixo e a direita) e, em volta, o
  // pontilhado #ff6034 em xadrez ate 7,1 celulas do meio. Tudo opaco e pelas coordenadas do proprio LED: o mesmo desenho
  // nos 13. O brilho desvia das letras (evita: o nome, os rotulos, o visor)
  const LED_ACESO = { aro: [168, 32, 15], corpo: [255, 74, 28], realce: [255, 230, 176], volta: [255, 176, 112],
    sombra: [228, 70, 24], brilho: [255, 96, 52] };
  const naBola = (i, j) => i >= 0 && j >= 0 && i < 8 && j < 8 && Math.hypot(i - 3.5, j - 3.5) <= 4.1;
  const noAro = (i, j) => naBola(i, j) && Math.hypot(i - 3.5, j - 3.5) > 3.2;
  function led(T, x0, y0, aceso, evita = () => false) {
    if (aceso) {
      const A = LED_ACESO;
      for (let j = -4; j < 12; j++) for (let i = -4; i < 12; i++) {
        const r = Math.hypot(i - 3.5, j - 3.5), x = x0 + i, y = y0 + j;
        if (r > 4.1 && r <= 7.1 && (i + j) % 2 === 0 && !evita(x, y)) T.px(x, y, A.brilho);
      }
      const realce = (i, j) => (i === 2 || i === 3) && (j === 2 || j === 3);
      for (let j = 0; j < 8; j++) for (let i = 0; i < 8; i++) {
        if (!naBola(i, j)) continue;
        const c = noAro(i, j) ? A.aro : realce(i, j) ? A.realce
          : realce(i + 1, j) || realce(i - 1, j) || realce(i, j + 1) || realce(i, j - 1) ? A.volta
            : i === 6 || j === 6 ? A.sombra : A.corpo;   // a sombra: a linha 6 e a coluna 6, por dentro do aro
        T.px(x0 + i, y0 + j, c);
      }
      return;
    }
    const P = [[150, 104, 96], [84, 26, 22], [64, 18, 15], [42, 11, 9], [104, 44, 38]];
    for (let j = 0; j < 8; j++) for (let i = 0; i < 8; i++) {
      const dx = i - 3.5, dy = j - 3.5, r = Math.hypot(dx, dy);
      if (r > 4.1) continue;
      const c = r > 3.2 ? O : (i === 2 && j === 2) || (i === 3 && j === 2) || (i === 2 && j === 3) ? P[0]
        : dx + dy > 2.6 ? P[3] : dx + dy > .6 ? P[2] : Math.hypot(dx + .5, dy + .5) < 1.2 ? P[4] : P[1];
      T.px(x0 + i, y0 + j, c);
    }
  }
  // o visor do Troca de voz (revisao da r02): o contorno, a borda de dentro escura, o vidro quase preto (no pedal ligado,
  // o miolo com a luz de fundo ambar) e, embaixo dele, a beira do rebaixo pegando a luz. A letra sem contorno (o halo
  // embolava as letras), tudo centrado: a voz na de LCD larga (passo de 7), o FALE ALGO e o PRONTO na de passo 6 (revisao
  // da r06), com 4 celulas entre as palavras, cada uma quando cabe com 2 celulas de margem no vidro; senao na de LCD de
  // 4 e, se nem ela couber, na dos nomes; o visto 4 celulas depois. O OUVINDO na dos nomes, 3 celulas de folga e os 6
  // blocos de 3 x 5 com 1 entre eles (o cheio em ambar, o vazio vazado: o aro apagado e o vidro dentro), ou, quando a
  // palavra nao deixa (o LISTENING), 2 de folga e blocos de 2 x 5 com o vazio cheio no AMBAR_VAZIO: o vazado precisa de
  // 3 celulas de largura, e o LISTENING (33) com a barra vazada (2 de folga, 6 de 3 e 5 vaos) da 58 celulas, contra as
  // 54 do vidro (revisao da r05)
  const VISTO = { 7: ['.....##', '....##.', '##.##..', '.###...', '..#....'],
                  9: ['.......##', '......##.', '.....##..', '##..##...', '.####....', '..##.....'] };
  function visor(T, x0, y0, w, h, cont, aceso, base) {
    const fundo = aceso ? VIDRO_ACESO : VIDRO;   // aceso: a faixa de dentro escura e o miolo com a luz de fundo
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      const d = Math.min(i, j, w - 1 - i, h - 1 - j);
      T.px(x0 + i, y0 + j, d === 0 ? O : d === 1 ? VIDRO_BORDA : d === 2 ? VIDRO : fundo);
    }
    for (let i = 1; i < w - 1; i++) T.px(x0 + i, y0 + h, mix(base, [255, 240, 220], .3));
    if (!cont) return;
    const cor = aceso && !cont.apagado ? AMBAR : AMBAR_OFF, area = w - 6, lim = [x0 + 2, x0 + w - 2];
    let F = PED, q = 0, extra = 0, folga = 0, txt = cont.txt;
    if (cont.barra != null) {   // os blocos de 3 x 5 (revisao da r04); de 2 x 5 se a palavra nao deixa
      q = largura(txt, PED) + 3 + 6 * 4 - 1 <= area ? 3 : 2;
      folga = q === 3 ? 3 : 2;
      extra = folga + 6 * (q + 1) - 1;
    } else {
      // a letra larga com 4 celulas entre as palavras (o espaco dela tem 2: com 2 de vao o FALE ALGO lia FALEALGO, revisao
      // da r07), ou com 3 (o espaco fino) se nao couber com 4; senao a de LCD de 4; senao a dos nomes
      const ext = G => cont.visto ? 4 + VISTO[G.cap][0].length : 0, larga = cont.frase ? LCD_FRASE : LCD_VOZ;
      const cabe = (t, G, margem) => temTudo(t, G) && largura(t, G) + ext(G) <= area - 2 * margem, fino = txt.replace(/ /g, '\u2009');
      if (cabe(txt, larga, 2)) F = larga;
      else if (cabe(fino, larga, 2)) { F = larga; txt = fino; }
      else if (cabe(txt, LCD, 0)) F = LCD;
      extra = ext(F);
    }
    const tw = largura(txt, F), x = Math.max(lim[0], Math.round(x0 + (w - tw - extra) / 2));
    const yCap = y0 + 2 + Math.floor((h - 4 - F.cap) / 2);
    // os blocos da barra e o visto como glifos ('#' na cor, '+' na cor2, abaixo): no T, ou com as letras na tela fina,
    // onde os 6 blocos saem com a mesma largura
    const extras = [];
    if (cont.barra != null) {
      const n = Math.round(clamp(cont.barra, 0, 1) * 6), bx = x + tw + folga, by = yCap + 1, alt = F.cap - 2;
      for (let k = 0; k < 6; k++) {   // o vazio: o aro, o miolo e o fundo; o de 2 de largura, cheio (no AMBAR_VAZIO)
        const rows = Array.from({ length: alt }, (_, j) => Array.from({ length: q }, (_, i) =>
          k < n ? '#' : q === 2 || i === 0 || j === 0 || i === q - 1 || j === alt - 1 ? '+' : '.').join(''));
        extras.push({ x: bx + k * (q + 1), y: by, rows, acc: false });
      }
    }
    if (cont.visto) extras.push({ x: x + tw + 4, y: yCap + 1, rows: VISTO[F.cap], acc: false });
    // a palavra, a barra e o visto juntos: entre 0,875 e 1,25 uma peca nativa so (revisao da r13: a palavra e a barra,
    // cada uma centrada na sua conta, ficavam a 1 px de onde o 1920 as poe uma da outra)
    nativo(T, null, D => {
      escreve(D, txt, x, yCap, cor, null, F, lim);
      // o '+': o aro apagado do vazado (os blocos de 3) ou, nos blocos de 2, a casa vazia cheia no ambar mais escuro
      const cor2 = q === 2 ? AMBAR_VAZIO : AMBAR_OFF;
      if (FORA) { if (extras.length) FORA.push({ glifos: extras, cor, cor2, placa: null, lim }); return; }
      for (const e of extras) e.rows.forEach((r, j) => {
        for (let i = 0; i < r.length; i++) if (r[i] !== '.') D.px(e.x + i, e.y + j, r[i] === '#' ? cor : cor2);
      });
    });
  }

  // ---- o pedal inteiro
  const estado = new WeakMap();
  const nomeVoz = v => String(v || '').toUpperCase();
  const nomeLido = v => { const s = String(v || ''); return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase(); };   // o leitor de tela soletraria a maiuscula
  function contVisor(pv, vozes, pisca) {
    if (!pv) return { txt: nomeVoz(vozes[0]) };
    if (pv.visor === 'fale') return { txt: I18N.t('effects.voicePedal.say').toUpperCase(), apagado: !pisca, frase: true };
    if (pv.visor === 'ouvindo') return { txt: I18N.t('effects.voicePedal.listening').toUpperCase(), barra: pv.progresso || 0 };
    if (pv.visor === 'pronto') return { txt: I18N.t('effects.voicePedal.ready').toUpperCase(), visto: true, frase: true };
    return { txt: nomeVoz(pv.voz || vozes[0]) };
  }
  // o pedal comum (88 ou 98 x 222: o desenho e o mesmo, centrado, e so o esmalte em volta cresce) e o Troca de voz
  // (148 x 240): onde fica cada peca, em celulas; a faixa do nome do comum e a largura do pedal menos 14 px (a regra da
  // r01: 37 celulas no de 88 e 42 no de 98, onde o MEGAPHONE de 38 cabe numa linha; revisao da r06). Na r09 (revisao da
  // r08) o comum cresceu 14 px: 4 acima do icone, 4 entre o LED e o footswitch e 6 abaixo dele; o Troca 8. Na r10 (revisao
  // da r09) o Troca cresce mais 4 embaixo, com o footswitch descendo os mesmos 4 (16 abaixo do dos vizinhos) e o
  // nome, o visor, os rotulos e o LED onde estavam: ele desce 18 alem dos vizinhos (148 x 240). O pe e onde o
  // footswitch do mock ficava (16 celulas de altura): o do app antigo, de 36 px, fica centrado no mesmo lugar
  const LAYOUT = {
    comum: { icone: [7, 40], led: 70, pe: 86, topos: TOPOS, faixa: 14 },
    voz: { icone: [8, 39], nome: 47, visor: [58, 16], led: 79, rotulo: 80, pe: 94 },
  };
  // o footswitch do app antigo redesenhado a mao para o regime 2 (abaixo de 0,875 e nos multiplos inteiros de 0,75: o de
  // 1440 tem 27 x 27 px de tela, contra os 36 x 36 do PE_SVG; o notebook o mostra a 2 x 2), com as cores dele, o
  // contorno de 1 px e a luz de cima a esquerda: a porca sextavada, o aro do furo, a tampa e a saia; s e a sombra, a
  // 32%. Dois quadros: solto e pisado (a tampa 1 px abaixo)
  const PE_1440 = {
    cor: { o: [28, 9, 0], W: [250, 250, 251], c: [212, 217, 223], m: [192, 197, 202], e: [146, 149, 153], d: [118, 121, 125],
      D: [86, 86, 88], s: [20, 8, 0, .32] },
    solto: [
      '...........................',
      '........ooooooooooo........',
      '.......oWWWWWWWWWWWo.......',
      '......oWcccooooocmmmo......',
      '.....oWcccoWWWWWommmmo.....',
      '....oWcccoWWcccWWommmmo....',
      '...oWcccoWWcccccceommmmo...',
      '..oWcccoWccccccccceommmmo..',
      '.oWccccoWccccccccceoommmmo.',
      '.oWcccooWccccccccceoommmmo.',
      '.oWccmooWWccccccceeooWmmmo.',
      '.oWcmmooWWcccccceDDooWceeo.',
      '.oWcmmoodWcccceeDDoooWceeo.',
      '.ooWmmoodoeeeeeDDooooeeeoo.',
      '.socmmoodWoooooooDoooeeeos.',
      '.socmmoodWceeeeeDDooeeeeos.',
      '..socmmooWceeeedDDoeeeeos..',
      '...socmooooooooooooeeeos...',
      '...socmmoooooooooooeeeos...',
      '....socmmmoooooocceeeos....',
      '.....socmeeeeeeeeeeeos.....',
      '......sommmmmmmmmmeos......',
      '.......soddddddddDos.......',
      '.......sooooooooooos.......',
      '........sooooooooos........',
      '.........sssssssss.........',
      '...........................',
    ],
    pisado: [
      '...........................',
      '........ooooooooooo........',
      '.......oWWWWWWWWWWWo.......',
      '......oWcccccccccmmmo......',
      '.....oWccccooooocmmmmo.....',
      '....oWccccoWWWWWocmmmmo....',
      '...oWccccoWWcccWWocmmmmo...',
      '..oWccccoWWcccccceocmmmmo..',
      '.oWccccoWccccccccceocmmmmo.',
      '.oWccccoWccccccccceoommmmo.',
      '.oWccmooWccccccccceooWmmmo.',
      '.oWcmmooWWccccccceeooWceeo.',
      '.oWcmmooWWcccccceDDooWceeo.',
      '.ooWmmoodWcccceeDDoooeeeoo.',
      '.socmmoodoeeeeeDDooooeeeos.',
      '.socmmoodWoooooooDoooeeeos.',
      '..socmmooWceeeedDDoeeeeos..',
      '...socmooooooooooooeeeos...',
      '...socmmoooooooooooeeeos...',
      '....socmmmoooooocceeeos....',
      '.....socmeeeeeeeeeeeos.....',
      '......sommmmmmmmmmeos......',
      '.......soddddddddDos.......',
      '.......sooooooooooos.......',
      '........sooooooooos........',
      '.........sssssssss.........',
      '...........................',
    ],
  };
  // o PE_SVG em grade de 36 x 36 (o quadro de baixo e a tampa solta ou a pisada), lido dos retangulos do proprio SVG
  function peGrade(tampa) {
    const T = tela(36, 36), base = PE_SVG.replace(/<g class="tampa[\s\S]*$/, '');
    const g = (PE_SVG.match(new RegExp('<g class="' + tampa + '">([\\s\\S]*?)</g>')) || [])[1] || '';
    let n = 0;   // a rede: se o PE_SVG mudar de forma e nada for lido, null (o peSvg fica no SVG)
    for (const trecho of [base, g]) for (const m of trecho.matchAll(/<path fill="(#[0-9A-Fa-f]{6})"(?: fill-opacity="([\d.]+)")? d="([^"]*)"/g))
      for (const r of m[3].matchAll(/M(\d+) (\d+)h(\d+)v(\d+)/g))
        for (let y = +r[2]; y < +r[2] + +r[4]; y++) for (let x = +r[1]; x < +r[1] + +r[3]; x++) { T.px(x, y, rgb(m[1]), m[2] ? +m[2] : 1); n++; }
    return n ? T : null;
  }
  const PE_GRADE = {};
  // o footswitch do app antigo (o PE_SVG do dev/pecas.py, 36 x 36 na grade de 1 px, ordem do dono): por cima do canvas,
  // centrado onde o do mock ficava; a pisada troca a tampa pelo CSS (.pisando), sem redesenhar o canvas. Fora do regime
  // 0 os dois quadros vao em canvas em px inteiro da tela (o CSS mostra o da pisada no lugar do SVG): no regime 1 (de
  // 0,875 a 1) o proprio PE_SVG em grade, 1:1; no regime 2 o PE_1440, m x m por px
  function peSvg(b, x, y, kd) {
    let p = b.querySelector(':scope > .pe-mesa');
    if (!p) {
      p = document.createElement('span');
      p.className = 'pe-mesa'; p.setAttribute('aria-hidden', 'true'); p.innerHTML = PE_SVG;
      b.append(p);
    }
    if (p.style.left !== x + 'px' || p.style.top !== y + 'px') Object.assign(p.style, { left: x + 'px', top: y + 'px' });
    const { rg, m } = regime(kd);
    const grade = rg === 1 && (PE_GRADE.solto ??= peGrade('tampa')) && (PE_GRADE.pisado ??= peGrade('tampa-pisada'));
    let q = [...b.querySelectorAll(':scope > canvas.pe-px')];
    if (!rg || (rg === 1 && !grade)) { for (const c of q) c.remove(); if (rg) console.error('pedal: PE_SVG sem a grade'); return; }
    if (!q.length) q = ['solto', 'pisado'].map(n => {
      const c = document.createElement('canvas');
      c.className = 'pe-px ' + n; c.setAttribute('aria-hidden', 'true');
      b.append(c);
      return c;
    });
    const dw = rg === 2 ? PE_1440.solto[0].length : PE_GRADE.solto.W, dh = rg === 2 ? PE_1440.solto.length : PE_GRADE.solto.H;
    const f = [folga(dw, m, kd), folga(dh, m, kd)];
    for (const c of q) {
      const n = c.classList.contains('pisado') ? 'pisado' : 'solto';
      if (c._rg !== rg || c._f !== f.join()) {
        if (rg === 2) pecaCanvas(c, PE_1440[n], ch => PE_1440.cor[ch] || null, ...f);
        else telaNoCanvas(c, PE_GRADE[n], ...f);
        c._rg = rg; c._f = f.join();
      }
      pecaNaTela(b, c, m * dw, m * dh, x + 18, y + 18, m * c.width, m * c.height);
    }
  }
  function desenha(b, pv, pisca) {
    const id = b.dataset.ef, ef = S.efeitos ? S.efeitos.find(x => x.id === id) : null;
    let q = estado.get(b);
    if (!q) {
      const cv = document.createElement('canvas');
      cv.className = 'ped-px'; cv.setAttribute('aria-hidden', 'true');
      b.prepend(cv);
      q = { cv };
      estado.set(b, q);
      b.classList.add('ped-ok');
    }
    const w = b.offsetWidth, h = b.offsetHeight;
    if (w < 40 || h < 80) return;
    const aceso = b.getAttribute('aria-pressed') === 'true', voz = id === 'pistavoz';
    // os px de tela por celula: inteiro (1920 a 100%, 1536 a 125%), o canvas de sempre; senao o fino (o pintaTela)
    const s = 2 * PALCO.k * (devicePixelRatio || 1), fino = Math.abs(s - Math.round(s)) > 1e-6;
    // fora da grade de 1/4 de px da tela (a janela maximizada) o canvas e as pecas de 1 px vao para o px inteiro mais perto
    // da origem do pedal: o lugar dele na tela entra na chave (o pedal assenta depois do primeiro quadro, e o canvas
    // ficava em meio px, dobrando ou comendo 1 coluna de letra)
    const solta = Math.abs(2 * s - Math.round(2 * s)) > 1e-6, rb = solta ? b.getBoundingClientRect() : null;
    const vozes = voz && ef && Array.isArray(ef.vozes) ? ef.vozes : [];
    const nome = ef ? nomePedal(ef) : id;
    const pvv = voz ? (pv || null) : null;
    // o de voz: o lugar e o rotulo sob o mouse tambem, para os botoes das vozes acompanharem
    const chave = [id, w, h, s, solta ? Math.round(rb.left * 64) + ',' + Math.round(rb.top * 64) : '', aceso, nome, voz ? [JSON.stringify(pvv), vozes.join(), pvv && pvv.visor === 'fale' ? pisca : '',
      b.offsetLeft, b.offsetTop, b.dataset.vozSob || '', b.dataset.vozFoco || ''].join(',') : ''].join('|');
    if (chave === q.cv._geo) return;
    q.cv._geo = chave;
    // o meio do pedal em celula inteira, com o mesmo arredondamento do icone e do nome (Math.round): no de 98, de 49
    // celulas, tudo fica no mesmo eixo, a meia celula para a direita do meio; no de 88 e no Troca de voz e o meio exato
    const cw = w / 2, ch = h / 2, meio = Math.round(cw / 2), T = tela(cw + 2, ch + 3), base = COR_PEDAL[id] || [86, 96, 120];
    // a placa dos nomes e dos rotulos no tom do pedal (revisao da r14): o meio do esmalte e do contorno #1a0b04, uma borda
    // fina no tom dele em volta da letra creme; a placa quase preta parecia etiqueta colada nos esmaltes claros
    const placa = base.map((v, i) => Math.round((v + O[i]) / 2));
    FORA = fino ? [] : null;
    NATIVO = fino && s / 2 >= .875 - 1e-6 && s / 2 < 1.25 - 1e-6 ? [] : null;   // as pecas no tamanho de 1920 (o nativo)
    const L = voz ? LAYOUT.voz : LAYOUT.comum, ic = voz ? ICONES_PEDAL.pistavoz : ICONES_PEDAL[id] || ICONES_PEDAL.generico;
    const cxIc = caixaIcone(ic, cw / 2, L.icone[0], L.icone[1]);
    corpo(T, cw, ch, base, voz, hashTxt(id) % 97, cxIc);
    // os parafusos: acima da parede em todos; no de voz, 2 celulas para dentro da moldura dourada
    const m = voz ? 6 : 3, mb = voz ? 9 : 7;
    for (const [x, y] of [[m, m], [cw - m - 3, m], [m, ch - mb - 3], [cw - m - 3, ch - mb - 3]]) parafuso(T, x, y);
    if (!ic.fino) nativo(T, cxIc, D => icone(D, ic, cxIc));
    iconeFino(b, ic, cxIc, s / 2);
    if (!voz) {
      const l = arrumaNome(nome, (w - L.faixa) / 2), topos = L.topos[Math.min(l.length, 3)];
      const perto = pertoDe(linhasNome(l, cw / 2, topos).flatMap(([t, x, y]) => celulas(t, x, y)));
      nativo(T, [meio - 4, L.led, 8, 8], D => led(D, meio - 4, L.led, aceso, perto));
      nativo(T, null, D => escreveNome(D, l, cw / 2, topos, CREME, placa));
    } else {
      // as duas vozes: o rotulo da escolhida em creme, o outro malva (a cor so diz o estado); o LED do pedal no meio, e os
      // rotulos longe dele: o brilho acaba antes da moldura do realce (revisao da r03)
      const ledX = meio - 4, escolhida = pvv && pvv.voz ? pvv.voz : vozes[0];
      const rotulos = vozes.slice(0, 2).map((v, k) => { const t = nomeVoz(v), tw = largura(t); return [t, k === 0 ? ledX - 8 - tw : ledX + 8 + 8]; });
      const perto = pertoDe(rotulos.flatMap(([t, x]) => celulas(t, x, L.rotulo))), fimVisor = L.visor[0] + L.visor[1];
      nativo(T, [ledX, L.led, 8, 8], D => led(D, ledX, L.led, aceso, (x, y) => y <= fimVisor + 1 || perto(x, y)));
      nativo(T, null, D => escreveNome(D, arrumaNome(nome, (w - 24) / 2, 1), cw / 2, [L.nome], CREME, placa));
      const vw = 60, vx = Math.round((cw - vw) / 2);
      visor(T, vx, L.visor[0], vw, L.visor[1], contVisor(pvv, vozes, pisca), aceso, base);
      // a area de clique de cada voz e a metade da faixa entre o visor e o footswitch, do lado dela (o LED com 2 celulas
      // de margem fica do pedal): errar a palavra por pouco nao liga nem desliga o efeito (revisao da r04)
      // O mouse em cima e o foco do teclado tem o mesmo sinal (revisao da r05): a moldura ambar de 1 celula em volta do
      // rotulo, 1 celula fora do contorno das letras e fora do brilho do LED; o texto fica na cor do estado
      const caixas = [], topo = fimVisor + 2, baixo = L.pe - 1, marcada = b.dataset.vozFoco || b.dataset.vozSob || '';
      vozes.slice(0, 2).forEach((v, k) => {
        const [t, x] = rotulos[k];
        // o rotulo e a moldura do realce na mesma caixa: entre 0,875 e 1,25 (pecas nativas) os dois saem no mesmo passo
        // de 2 px, com 1 celula entre o contorno e a moldura dos quatro lados
        const cxR = [x - 3, L.rotulo - 3, largura(t) + 6, 7 + 6];
        nativo(T, cxR, D => escreve(D, t, x, L.rotulo, v === escolhida ? CREME : mix(base, CREME, .55), placa));
        if (v === marcada) {
          // com a letra na tela fina sem as pecas nativas (o palco de 1440) a moldura sai com ela no pintaTela, em volta
          // da letra como ela saiu; senao na mesma caixa do rotulo
          if (FORA && !NATIVO) FORA[FORA.length - 1].realce = AMBAR;
          else nativo(T, cxR, D => moldura(D, ...cxR, AMBAR));
        }
        const ini = k === 0 ? 6 : ledX + 10, fim = k === 0 ? ledX - 2 : cw - 6;
        caixas.push([2 * ini, 2 * topo, 2 * (fim - ini), 2 * (baixo - topo)]);
      });
      vozesDom(b, vozes, escolhida, caixas);
    }
    peSvg(b, 2 * meio - 18, 2 * L.pe - 2, s / 2);   // 36 px centrados nas 16 celulas do pe do mock: 2 px acima e 2 abaixo
    if (FORA) { pintaTela(q.cv, T, s, solta ? b : null); FORA = NATIVO = null; return; }
    q.cv.width = T.W; q.cv.height = T.H; q.cv.style.left = q.cv.style.top = '';
    q.cv.style.width = 2 * T.W + 'px'; q.cv.style.height = 2 * T.H + 'px';
    q.cv.getContext('2d').putImageData(new ImageData(T.u, T.W, T.H), 0, 0);
  }
  /* os botoes das vozes: irmaos do pedal (botao dentro de botao nao vale), logo depois dele (o Tab passa do pedal para
     as vozes), por cima dos rotulos pintados; o mouse por cima e o foco do teclado poem a moldura no rotulo, a dica do
     tema diz o que fazem (qual e a mais grave e qual a mais aguda: o modulo manda as vozes nessa ordem, ver o API.md);
     o nome de cada um para o leitor de tela e fixo (a voz, e se e a mais grave ou a mais aguda) e o estado vai no
     aria-pressed (o passo do visor vai pelo #passo-voz do tema, em todo layout) */
  const DICA_VOZ = { escolher: ['effects.voicePedal.choose', 'effects.voicePedal.chooseLow', 'effects.voicePedal.chooseHigh'],
    escolhida: ['effects.voicePedal.chosen', 'effects.voicePedal.chosenLow', 'effects.voicePedal.chosenHigh'],
    nome: ['effects.voicePedal.voice', 'effects.voicePedal.voiceLow', 'effects.voicePedal.voiceHigh'] };
  function vozesDom(b, vozes, escolhida, caixas) {
    let d = b.nextElementSibling;
    if (!d || !d.classList.contains('vozes-pedal')) {
      d = el('div', 'vozes-pedal');
      b.after(d);
    }
    if (d.dataset.vozes !== vozes.join()) {
      d.dataset.vozes = vozes.join();
      const duas = vozes.length > 1;
      d.replaceChildren(...vozes.slice(0, 2).map((v, k) => {
        const bt = el('button', 'voz-pedal', nomeLido(v));
        bt.type = 'button'; bt.dataset.voz = v;
        bt.setAttribute('aria-label', I18N.t(DICA_VOZ.nome[duas ? k + 1 : 0], { name: nomeLido(v) }));
        bt.addEventListener('click', e => { e.stopPropagation(); escolheVoz(v); });
        bt.addEventListener('pointerenter', () => { b.dataset.vozSob = v; });
        bt.addEventListener('pointerleave', () => { if (b.dataset.vozSob === v) delete b.dataset.vozSob; });
        // o foco do teclado (so o visivel, como o :focus-visible) desenha a mesma moldura do mouse no canvas
        bt.addEventListener('focus', () => { if (bt.matches(':focus-visible')) b.dataset.vozFoco = v; });
        bt.addEventListener('blur', () => { if (b.dataset.vozFoco === v) delete b.dataset.vozFoco; });
        return bt;
      }));
    }
    // a dica de cada voz: a de escolher, ou, na escolhida, que ela ja e a escolhida; a dica aberta acompanha a escolha
    const duas = vozes.length > 1;
    d.querySelectorAll('.voz-pedal').forEach((bt, k) => {
      const c = caixas[k]; if (!c) return;
      Object.assign(bt.style, { left: b.offsetLeft + c[0] + 'px', top: b.offsetTop + c[1] + 'px', width: c[2] + 'px', height: c[3] + 'px' });
      const ja = bt.dataset.voz === escolhida;
      bt.setAttribute('aria-pressed', ja ? 'true' : 'false');
      const dica = I18N.t(DICA_VOZ[ja ? 'escolhida' : 'escolher'][duas ? k + 1 : 0], { name: nomeLido(bt.dataset.voz) });
      if (bt.dataset.dica !== dica) {
        bt.dataset.dica = dica;
        if (dicaAlvo === bt) dicaDoPedal(bt);
      }
    });
  }
  /* a voz clicada vale na tela ate a resposta do servidor (revisao da r02): o estado do SSE que chega no meio ainda
     traz a voz de antes, e sem isso o visor piscava entre as duas */
  let vozPendente = null;
  const comPendente = pv => pv && vozPendente && pv.voz !== vozPendente ? { ...pv, voz: vozPendente } : pv;
  async function escolheVoz(v) {
    if (!S.state) return;
    vozPendente = v;
    try {
      const r = await api('POST', '/api/pedal_voz', { voz: v });
      if (vozPendente === v && r && r.pedal_voz && S.state) S.state.pedal_voz = r.pedal_voz;
    } catch (e) {
      console.error('pedal_voz', e.message);
      avisar(e.status === 0 ? e.message : I18N.t('effects.voicePedal.failed'), true);
    } finally {
      if (vozPendente === v) vozPendente = null;
    }
  }
  function quadro() {
    if (document.body.classList.contains('mesa-dj')) {
      // o FALE ALGO pisca entre aceso e apagado (parado aceso com o movimento reduzido)
      const pv = comPendente(S.state ? S.state.pedal_voz : null), pisca = reduz.matches || Math.floor(performance.now() / 520) % 2 === 0;
      for (const b of document.querySelectorAll('.palco .banco .tecla[data-ef]')) try { desenha(b, pv, pisca); } catch (e) { console.error('pedal', e); }
    }
    requestAnimationFrame(quadro);
  }
  requestAnimationFrame(quadro);
})();
/* PEDAL-JS-FIM */
