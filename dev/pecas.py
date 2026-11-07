"""Pecas de pixel da vitrola (o toque de Habbo, mock p1): o braco do toca-discos
com a base e o descanso e o botao de tocar redondo (o grande do palco e o pequeno da barra de baixo),
e o pisador (footswitch), o knob e o LED dos pedais, os botoes de fliperama e o logo do Locutor, a chave 110/220
do fim do disco e as barras do palco, desenhados celula a celula.

    python dev/pecas.py

Grava as variaveis --braco-*, --base-braco, --descanso, --tocar-*, --icone-*, --knob-margem, --led-recuo,
--arcade-recuo, as das barras do palco (--trilho-moldura, --trilho-fundo, --trilho-aceso e --cursor-pino) e os metais da
maleta do A seguir (--maleta-canto-a a -d, --maleta-dobradica, --maleta-fecho, --maleta-alca, --maleta-meio-*,
--maleta-boca-*, o casco em perspectiva, --maleta-tampa-* e --maleta-base-*, e o recorte do disco entreaberto,
--maleta-disco-*) no
bloco entre "pecas:inicio" e "pecas:fim" do themes/vitrola/index.html, e no JS os SVGs do pisador (PE_SVG), do LED (LED_SVG), os knobs dos pedais com os ponteiros (KNOBS: o creme, o baquelite e o chicken-head), os
botoes e o logo do Locutor (ARCADE), a chave do "So este disco / Tocar parecidas" (CHAVE_PARECIDAS) e o salvar da
parecida no prato (SALVAR_PIXEL, com as --salvar-aceso-* do aro).

O braco: o tema gira o .braco em volta do pivo (o anguloPara() da o angulo do sulco; parado ele volta
ao descanso). Desenhado reto e girado ele viraria um retangulo liso; por isso o desenho e o braco
inteiro (contrapeso, tubo, cabeca com o levantador e a bola do pivo, cada um com o contorno, o bisel
de luz e a sombra dura) ja inclinado, com o degrau na tela. Um degrau desenhado num angulo e girado
muito longe dele vira serrote, entao sao seis desenhos (ANGULOS: o descanso e cinco no curso do
disco no celular, 31 a 48 graus); o JS poe a faixa do angulo no data-desenho do #braco e o tema gira
o desenho de volta em volta do pivo, sobrando no maximo 2 graus. As medidas sao as do
braco de sempre (em cqw do tampo), entao a conta do sulco nao muda.

A base do braco e o descanso nao giram: degrau de verdade, cada um num pseudo que sai do elemento o
tanto do contorno e da sombra.

O botao de tocar na lingua das teclas quadradas do lado: o contorno em degrau, a linha clara por dentro
dele, o aro liso (cinza parado, ambar tocando, como antes), a linha escura, a face creme com o filete
de luz e a faixa de sombra e a sombra dura, num pseudo por tras do botao;
apertado, a sombra encolhe e o botao desce. No grande o aro e gordo como no p1 (4 celulas, tiradas
da face: por fora o botao fica do mesmo tamanho). Os icones (tocar e pausar) tambem em degrau,
noutro pseudo.

Escala: com 2 px por celula o degrau ficou mais serrilhado que o mock (exagerado, voltou
um pouco). No braco, CELULA_BRACO cqw do tampo (1,3 px no tampo de 328 px do celular de
360, 4 px de tela no celular de densidade 3, o de teste), contorno de 1 celula. No botao grande 2 px (6 px
de tela; de 4/3 subiu em dois passos, para o pixel art do botao ficar maior), no
pequeno 4/3 px (4 px de tela: no icone pequeno voltou dois passos); contorno
de 2 celulas.
"""
import math
import re
import sys
from urllib.parse import quote

from molduras import CONTORNO, TEMA

# o descanso (reto no celular, o moverBraco()) e cinco no curso do disco, de 4 em 4 graus (o JS corta em
# 15, 34, 38, 42 e 46): sobram no maximo 2 graus de giro; com 5, a alca fina da cabeca virava zigue-zague
ANGULOS = {"repouso": 0, "a": 32, "b": 36, "c": 40, "d": 44, "e": 48}
CELULA_BRACO = .4           # cqw do tampo por celula
SOMBRA_BRACO = (20, 8, 2, .24)
VINIL = (22, 17, 15, 1)            # o contorno das pecas que ficam em cima do disco: some no preto, como no mock
METAL_CONTORNO = (56, 50, 46, 1)   # o contorno do braco no mock (amostrado): marrom grafite, mais claro que o do tema
TINTA = (42, 24, 18, 1)
VIZ = ((1, 0), (-1, 0), (0, 1), (0, -1))


def roda(x, y, graus):
    a = math.radians(graus)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def caixa(x, y, x0, x1, y0, y1, raio=0.):
    """Retangulo de cantos arredondados, no referencial dele."""
    dx, dy = max(x0 + raio - x, 0, x - (x1 - raio)), max(y0 + raio - y, 0, y - (y1 - raio))
    return x0 <= x <= x1 and y0 <= y <= y1 and dx * dx + dy * dy <= raio * raio


def bisel(cheio, cor, luz, sombra):
    """A cor de cada celula da peca: luz onde a beira olha para cima ou para a esquerda, sombra onde
    olha para baixo ou para a direita (na tela)."""
    px = {}
    for x, y in cheio:
        if (x, y - 1) not in cheio or (x - 1, y) not in cheio:
            px[(x, y)] = luz
        elif (x, y + 1) not in cheio or (x + 1, y) not in cheio:
            px[(x, y)] = sombra
        else:
            px[(x, y)] = cor
    return px


def pinta_pecas(pecas, sombra_desloc, sombra_cor, cor_contorno=CONTORNO):
    """Pinta pecas em ordem (cada uma com o contorno de 1 celula por cima das de baixo) e a sombra dura
    de tudo deslocada. pecas: lista de (celulas, {celula: cor}[, cor do contorno da peca])."""
    px, tudo = {}, set()
    for cheio, cores, *cor in pecas:
        cheio = set(cheio)
        contorno = {(x + dx, y + dy) for x, y in cheio for dx, dy in VIZ} - cheio
        for c in contorno:
            px[c] = cor[0] if cor else cor_contorno
        px.update(cores)
        tudo |= cheio | contorno
    if sombra_desloc:
        sx, sy = sombra_desloc
        for x, y in {(x + sx, y + sy) for x, y in tudo} - tudo:
            px[(x, y)] = sombra_cor
    return px


def recorta(px):
    """Encosta o desenho no canto (0, 0); devolve as celulas, a largura, a altura e o deslocamento."""
    x0, y0 = min(x for x, _ in px), min(y for _, y in px)
    x1, y1 = max(x for x, _ in px), max(y for _, y in px)
    return {(x - x0, y - y0): c for (x, y), c in px.items()}, x1 - x0 + 1, y1 - y0 + 1, x0, y0


# ---------- braco: medidas do .braco do tema, em cqw, com o pivo na origem e o braco para baixo ----------
def faixas(cels, meia, tons):
    """Cilindro em faixas pela distancia ao eixo da peca (u = x local / meia largura, de -1 a 1): o lado
    -x olha para cima e para a esquerda da tela em todos os angulos do braco, e e o da luz. tons: lista
    de (u maximo, cor), da esquerda para a direita."""
    return {c: next(cor for lim, cor in tons if u / meia <= lim) for c, (u, *_) in cels.items()}


def braco(angulo):
    """O braco do mock p1 (copiado do mock, com a mesma iluminacao), com as cores
    amostradas dele: a luz e quente, de cima a esquerda, e o metal e creme como o tampo. Tubo
    redondo (brilho no meio, beiras bege), contrapeso cinza com a faixa de brilho ao comprido, cabeca
    grafite com a alca em barrinha creme, a bola do pivo em esfera creme que escurece ate o bege
    escuro embaixo a direita, contorno marrom grafite e sombra de 1 celula (a de 2 virava uma segunda
    linha em cima da base). A bola do tamanho do mock: metade da base."""
    s, lim = CELULA_BRACO, 180

    def celulas(teste, ref=lambda x, y: (x, y)):
        """{celula: (x, y) no referencial da peca, (x, y) na tela a partir do pivo}"""
        out = {}
        for j in range(-lim, lim):
            for i in range(-lim, lim):
                # centro da celula na tela, levado ao referencial do braco (que a tela gira em angulo)
                sx, sy = (i + .5) * s, (j + .5) * s
                lx, ly = ref(*roda(sx, sy, -angulo))
                if teste(lx, ly):
                    out[(i, j)] = (lx, ly, sx, sy)
        return out

    def cabeca_ref(lx, ly):   # o referencial da cabeca: girada 24 graus em volta do topo dela
        return roda(lx, ly - 53.5, -24)

    def na_tela(hx, hy):      # do referencial da cabeca para a grade de celulas da tela
        ax, ay = roda(hx, hy, 24)
        return [v / s for v in roda(ax, ay + 53.5, angulo)]


    contrapeso = celulas(lambda x, y: caixa(x, y, -2.5, 2.5, -13, -6, .9))
    tubo = celulas(lambda x, y: caixa(x, y, -.75, .75, -6.5, 55.5))   # a grossura do mock (com 2 cqw ficou 1,5 vez a dele)
    # a cabeca mais clara que o vinil (escura como ele sumia: o contorno nao aparece no preto), estreita
    # como a do mock: o cinza que se ve dela tem uns 64 x 23 px em 730 = 8,8 x 3,2 cqw, e no vinil o
    # contorno escuro some, entao o corpo e que tem essa medida (a de 4,4 cqw dava 1,4 vez a largura);
    # a alca e a barrinha do mock, de lado, perto do tubo, com uma fresta da cabeca: o mesmo desenho
    # (ALCA) em todos os angulos, preso no mesmo ponto da cabeca. Girada com o braco, ela deitava no
    # comeco do disco e ficava comprida, e em pe no fim virava toquinho (deveria ter
    # um tamanho padrao). A cabeca e a alca, em cima do vinil, levam o contorno da cor dele (o marrom
    # grafite, mais claro que o preto, fazia um halo em volta, e no mock elas nao tem contorno a vista)
    cabeca = celulas(lambda x, y: caixa(x, y, -1.6, 1.6, 0, 8.8), cabeca_ref)
    ax, ay = (math.floor(v) for v in na_tela(2, 1.2))
    levantador = {(ax + dx, ay + dy): dy / max(y for _, y in ALCA) for dx, dy in ALCA}
    pivo = celulas(lambda x, y: x * x + y * y <= 2.4 * 2.4)   # a bola por cima do tubo

    def esfera(cels, raio):
        return {c: next(cor for lim, cor in ESFERA if math.hypot(sx + .3 * raio, sy + .3 * raio) / raio <= lim)
                for c, (_, _, sx, sy) in cels.items()}
    pecas = [
        (contrapeso, faixas(contrapeso, 2.5, ((-.75, (64, 64, 63, 1)), (-.35, (132, 131, 131, 1)), (.3, (78, 78, 78, 1)), (.7, (56, 55, 54, 1)), (9, (34, 34, 33, 1))))),
        (tubo, faixas(tubo, .75, ((-.6, (226, 220, 206, 1)), (.1, (253, 249, 238, 1)), (.6, (200, 194, 180, 1)), (9, (160, 155, 144, 1))))),
        (cabeca, faixas(cabeca, 1.6, ((-.6, (72, 72, 72, 1)), (.6, (61, 61, 61, 1)), (9, (42, 41, 42, 1)))), VINIL),
        (levantador, {c: (214, 207, 192, 1) if k > .75 else (243, 239, 228, 1) for c, k in levantador.items()}, VINIL),   # a ponta de fora na sombra
        (pivo, esfera(pivo, 2.4)),
    ]
    return recorta(pinta_pecas(pecas, (1, 1), SOMBRA_BRACO, METAL_CONTORNO))


# a alca da cabeca em celulas: 2 de largura, 5 de altura (a de 4 era um pixel mais curta que a do mock,
# um pixel a mais), um degrau (a inclinacao media dela no curso do disco); a fileira
# de baixo na sombra
ALCA = ((0, 0), (1, 0), (0, 1), (1, 1), (1, 2), (2, 2), (1, 3), (2, 3), (1, 4), (2, 4))

# a esfera do mock (amostrada na bola do pivo): distancia ao ponto de luz / raio -> cor
ESFERA = ((.25, (252, 249, 236, 1)), (.55, (244, 238, 223, 1)), (.8, (226, 218, 202, 1)), (1, (206, 198, 180, 1)),
          (1.15, (176, 168, 153, 1)), (1.3, (140, 133, 121, 1)), (9, (112, 105, 97, 1)))


# ---------- pisador (footswitch) dos pedais ----------
N_PE = 36   # 1 px css por celula, a unidade das molduras do app (3 px de tela no celular de teste)
PE_DESCE = 1   # o botao pisado fica 1 px abaixo do solto: um footswitch de verdade nao vai ao fundo (2 px era muito)
PE_MEIO_FURO = 17   # acima desta linha o botao aparece inteiro; abaixo, so sobre o fundo do furo ('h')
# as cores do pisador por letra (a paleta do mock escolhido): O contorno, W luz, C claro, K claro medio, M medio,
# e escuro, d mais escuro, h o fundo do furo, s a sombra dura
PE_COR = {"O": (28, 9, 0, 1), "W": (250, 250, 251, 1), "C": (212, 217, 223, 1), "K": (192, 197, 202, 1),
          "M": (146, 149, 153, 1), "e": (118, 121, 125, 1), "d": (86, 86, 88, 1), "h": (34, 16, 7, 1), "s": (20, 8, 0, .32)}
# a porca com o furo (fixa)
PE_PORCA = (
    "....................................",
    "....................................",
    "...........OOOOOOOOOOOOOO...........",
    "..........OOWWWWWWWWWWWWOO..........",
    ".........OOWCCCCCCCCCCCKKOO.........",
    "........OOWCCCCCCCCCCCCKKKOO........",
    ".......OOWCCCCCCCCCCCCCCKKKOO.......",
    "......OOWCCCCCCCOOOOCCCCCKKKOO......",
    ".....OOWCCCCCOOOOOOOOOOOCCKKKOO.....",
    "....OOWCCCCOOOOOOOOOOOOOOCCKKKOO....",
    "...OOWCCCCOOOOOOhhhhhOOOOOCKKKKOO...",
    "..OOWCCCCOOOOOhhhhhhhhhOOOOKKKKKOO..",
    ".OOWCCCCOOOOOhhhhhhhhhhhOOOOKKKKKOO.",
    ".OWCCCCKOOOOhhhhhhhhhhhhOOOOWKKKKKO.",
    ".OWCCCKKOOOOhhhhhhhhhhhhhOOOWCKKMMO.",
    ".OWCKKKKOOOhhhhhhhhhhhhhhOOOWCMMMMO.",
    ".OWCKKKKOOOhhhhhhhhhhhhhhOOOWCMMMMO.",
    ".OWCKKKKOOhhhhhhhhhhhhhhhhOOWMMMMMO.",
    ".OOWKKKKOOhhhhhhhhhhhhhhhhOOMMMMMOO.",
    ".sOOCKKKOOOhhhhhhhhhhhhhhOOOMMMMOOs.",
    "..sOCKKKKOOhhhhhhhhhhhhhhOOMMMMMOs..",
    "...OOCKKKOOOhhhhhhhhhhhhOOOMMMMOO...",
    "...sOOCKKKOOOOhhhhhhhhOOOOMMMMOOs...",
    "....sOCKKKKOOOOhhhhhhOOOOMMMMMOs....",
    ".....OOCKKKKOOOOOOOOOOOOMMMMMOO.....",
    ".....sOOCKKKKOOOOOOOOOCCMMMMOOs.....",
    "......sOCKKMMMMMMMMMMMMMMMMMOs......",
    ".......OOCKMMMMMMMMMMMMMMMMOO.......",
    ".......sOOKKKKKKKKKKKKKKKMOOs.......",
    "........sOeeeeeeeeeeeeeeedOs........",
    ".........OOeeeeeeeeeeeeeeOO.........",
    ".........sOOOOOOOOOOOOOOOOs.........",
    "..........sOOOOOOOOOOOOOOs..........",
    "...........ssssssssssssss...........",
    "....................................",
    "....................................",
)
# o botao, tampa e corpo, solto (o quadro pisado sai dele, PE_DESCE abaixo)
PE_BOTAO = (
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "...............OOOOOOO..............",
    ".............OOWWWWWWOO.............",
    "............OWWWCCCCWWOO............",
    "...........OWWCCCCCCCCCMO...........",
    "..........OWWCCCCCCCCCCMMO..........",
    ".........OOWCCCCCCCCCCCCMO..........",
    ".........OWWCCCCCCCCCCCCMOO.........",
    ".........OWWCCCCCCCCCCCCMOO.........",
    ".........OWWCCCCCCCCCCCCMOO.........",
    ".........OOWCCCCCCCCCCCCMOO.........",
    ".........OOWWCCCCCCCCCCMMOO.........",
    ".........OOWWWCCCCCCCCCMOOO.........",
    ".........OeOWWWCCCCCCCddOdO.........",
    "..........eOOMMCCCCMMMdOOd..........",
    "..........eWOOOMMMMMddOOdd..........",
    "...........eWWOOOOOOOOddd...........",
    "...........eWWCMMMMMMeddd...........",
    "............WWCMMMMMMedd............",
    ".............WCMMMMMMed.............",
    "...............MMMMMM...............",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
    "....................................",
)


def pisador_camadas():
    """As camadas do pisador em letras de PE_COR: a porca com o furo, o botao e o recorte do botao. Desenho do
    mock escolhido, decalcado em 1 px de tela e passado para a grade do app
    (nos contornos do app, alinhando os artefatos da imagem, mas
    mantendo a grossura dos tracos): a silhueta em degraus regulares, o contorno de 1 px (2 na base) como o
    das molduras, a sombra dura de 1 px e sem os pontos soltos do decalque. Retoque a mao nas letras."""
    pega = lambda arte: {(x, y): c for y, linha in enumerate(arte) for x, c in enumerate(linha) if c != "."}
    porca, botao = pega(PE_PORCA), pega(PE_BOTAO)
    recorte = {(x, y) for y in range(N_PE) for x in range(N_PE) if y < PE_MEIO_FURO or porca.get((x, y)) == "h"}
    return porca, botao, recorte


def pisador_quadros():
    """Os dois quadros do botao, ja recortados pelo furo: solto e pisado (PE_DESCE celulas abaixo). No pisado,
    celula do botao cercada de contorno nos quatro lados vira contorno: sao as pontas das linhas cinza das
    laterais do cilindro que o furo corta, e sobrariam como pixel solto."""
    porca, botao, recorte = pisador_camadas()
    solto = {k: c for k, c in botao.items() if k in recorte}
    desce = {(x, y + PE_DESCE): c for (x, y), c in botao.items() if (x, y + PE_DESCE) in recorte}
    junto = {**porca, **desce}
    ilhada = lambda x, y: all(junto.get((x + dx, y + dy)) == "O" for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    pisado = {(x, y): "O" if ilhada(x, y) else c for (x, y), c in desce.items()}
    return porca, solto, pisado


def pisador():
    """O footswitch dos pedais em pixel,
    pelos quadros do pisador_quadros(), em vetor (um path por cor): a porca fixa, o g.tampa (solto) e o
    g.tampa-pisada, que o tema troca ao pisar como dois quadros de sprite, sem transform no SVG. Aspas
    duplas, para morar numa string de JS."""
    n = N_PE
    porca, solto, pisado = pisador_quadros()
    vetor = lambda px: "".join(caminhos({c: PE_COR[v] for c, v in px.items()}, n, n, '"'))
    return (f'<svg viewBox="0 0 {n} {n}" shape-rendering="crispEdges">{vetor(porca)}'
            f'<g class="tampa">{vetor(solto)}</g><g class="tampa-pisada">{vetor(pisado)}</g></svg>')


def disco_pixel(raio, cx, cy, n):
    """Celulas de um circulo de raio (em celulas) com centro em (cx, cy) num quadro n x n."""
    return {(x, y) for y in range(n) for x in range(n) if math.hypot(x + .5 - cx, y + .5 - cy) < raio}


# ---------- knob creme dos pedais ----------
KN_R = (14.5, 14.5)  # raios do tampo com o contorno: 29 celulas (impar, para o risco do meio e o ponteiro de pe terem
                     # 1 celula); redondo como no mock (a elipse de 26 de altura ficou achatada demais)
KN_SAIA = 5          # linhas da saia a vista abaixo do tampo (o mock mostra mais cilindro que as 4 do knob liso)
KN_ESCALA_DESCE = 4  # o centro da escala abaixo do centro do tampo: o arco abraca o tampo e a saia
KN_ARCO = 20         # raio do arco da escala: o menor com folga em cima do tampo redondo e os riscos das pontas fora da saia
KN_RISCO = (.4, 4)   # cada risco sai do arco em T e anda 4 celulas para fora (cruzando, como no mock B, os da diagonal davam no)
KN_TRACO = (2, 2)    # a linha preta do knob, para dentro: em cima, na divisa do tampo com a saia e na base, e nos lados
                     # da metade do tampo para baixo (as de 1 e 2 ficavam finas demais; com 3 nos
                     # lados, o anel do tampo e o da saia viravam um bloco preto e a saia sumia)
KN_PASSO = 27.3      # graus entre os 11 riscos (273 graus de curso, de -136,5 a 136,5, os da escala de antes)
KN_PONTEIRO = (2, 10.5)     # o miolo do ponteiro, do raio de dentro ao de fora: da beira ate perto do centro, como no mock A e no de antes
KN_CENTRO = (17.5, 14.5)   # onde o centro do tampo cai na caixa de 34 x 38 do .p-grande (o de antes era 17, 14)
# as cores do knob por letra (as do knob liso de antes, mais o escuro da saia do mock escolhido): O contorno,
# W luz, F face, A aro, L/T/E a saia da luz a sombra, P o miolo do ponteiro, s a sombra dura
KN_COR = {"O": (26, 11, 4, 1), "W": (255, 248, 234, 1), "F": (234, 220, 196, 1), "A": (185, 161, 130, 1),
          "L": (216, 198, 170, 1), "T": (156, 132, 105, 1), "E": (122, 103, 82, 1), "P": (90, 69, 53, 1),
          "s": (12, 6, 3, .42)}


def sem_cantos(cels):
    """Tira os cantos em L de um traco de 1 celula (a celula com vizinho do lado e em cima ou embaixo):
    os dois vizinhos seguem ligados pela quina, e o traco fica com 1 celula de grossura."""
    for x, y in sorted(cels, key=lambda c: (c[1], c[0])):
        h = (x - 1, y) in cels or (x + 1, y) in cels
        v = (x, y - 1) in cels or (x, y + 1) in cels
        if h and v:
            cels.discard((x, y))
    return cels


RETOS = (0, 18.43, 26.57, 45, 63.43, 71.57, 90)   # as inclinacoes de degrau regular: em pe, 1:3, 1:2, 1:1, 2:1, 3:1, deitada


def reto(graus):
    """O angulo levado a inclinacao de degrau regular mais perto (a do meio do caminho dava um degrau solto
    no meio do traco, um ziguezague)."""
    base = math.floor(graus / 90) * 90
    return base + min(RETOS, key=lambda r: abs(graus - base - r))


def linha_pixel(cx, cy, graus, r0, r1):
    """Celulas de uma linha de 1 celula do raio r0 ao r1, no angulo (0 para cima, horario), saindo da celula
    do centro (cx, cy no meio dela): um passo inteiro por celula no eixo que mais anda, entao o degrau de
    uma inclinacao de RETOS sai igual do comeco ao fim."""
    dx, dy = math.sin(math.radians(graus)), -math.cos(math.radians(graus))
    x0, y0 = math.floor(cx), math.floor(cy)
    if abs(dx) >= abs(dy):
        s, m = math.copysign(1, dx), dy / abs(dx)
        return {(x0 + int(s * i), math.floor(y0 + .5 + m * i - 1e-6)) for i in range(math.ceil(r0 * abs(dx)), math.floor(r1 * abs(dx)) + 1)}
    s, m = math.copysign(1, dy), dx / abs(dy)
    return {(math.floor(x0 + .5 + m * i - 1e-6), y0 + int(s * i)) for i in range(math.ceil(r0 * abs(dy)), math.floor(r1 * abs(dy)) + 1)}


def arco_pixel(cx, cy, raio, de, ate, n):
    """Arco de 1 celula: as celulas a meia celula do raio, sem os cantos em L que engrossam a curva."""
    ang = lambda x, y: math.degrees(math.atan2(x + .5 - cx, -(y + .5 - cy)))
    return sem_cantos({(x, y) for y in range(n) for x in range(n)
                       if abs(math.hypot(x + .5 - cx, y + .5 - cy) - raio) < .5 and de <= ang(x, y) <= ate})


def knob_camadas():
    """O knob creme dos pedais em letras de KN_COR, no desenho do knob liso de antes e do mock escolhido: o tampo redondo com o contorno de
    KN_TRACO, a luz em crescente em cima a esquerda e o aro escuro embaixo a direita; a saia de KN_SAIA
    linhas, clara a esquerda e escura a direita; a sombra dura embaixo. A escala e os ponteiros vem a parte
    (celulas): a escala o tema pinta na cor da letra do pedal, e o ponteiro e um quadro por risco.
    Devolve (corpo {celula: letra}, riscos, arco, [ponteiro {celula: letra} por risco], centro do tampo)."""
    n = 64
    cx, cy = n / 2 + .5, 28.5
    rx, ry = KN_R
    elipse = lambda ax, ay, y0: {(x, y) for y in range(n) for x in range(n) if ((x + .5 - cx) / ax) ** 2 + ((y + .5 - y0) / ay) ** 2 < 1}
    fino, grosso = KN_TRACO
    tampo = elipse(rx, ry, cy)
    miolo = elipse(rx - fino - 2, ry - fino - 2, cy)    # dentro do contorno e da faixa de 2 celulas da luz e do aro
    cilindro = lambda dx, dy: set().union(*(elipse(rx - dx, ry - dy, cy + k) for k in range(KN_SAIA + 1)))
    corpo = cilindro(0, 0)
    # a linha preta: o anel entre cada silhueta e ela encolhida para dentro; nos lados da metade do tampo para
    # baixo, o grosso (os lados pesam, como no mock e no knob de antes; na base o grosso comia a saia)
    contorno = ((corpo - cilindro(fino, fino)) | (tampo - elipse(rx - fino, ry - fino, cy))
                | {(x, y) for x, y in corpo - cilindro(grosso, fino) if y + .5 >= cy})
    px = {(x, y + 2): "s" for x, y in corpo}
    for x, y in corpo:
        nx, ny = (x + .5 - cx) / rx, (y + .5 - cy) / ry
        if (x, y) in contorno:
            px[(x, y)] = "O"
        elif (x, y) in miolo:
            px[(x, y)] = "F"
        elif (x, y) in tampo:
            ang = math.degrees(math.atan2(nx, -ny))   # 0 em cima, horario: a luz das 8h a 1h30, o aro das 2h30 as 7h30
            px[(x, y)] = "W" if -100 <= ang <= 45 else "A" if ang >= 75 or ang <= -135 else "F"
        else:
            px[(x, y)] = "L" if nx < -.45 else "T" if nx < .2 else "E"
    ex, ey = cx, cy + KN_ESCALA_DESCE
    meio = KN_PASSO * 5
    arco = arco_pixel(ex, ey, KN_ARCO, -meio, meio, n) - set(px)   # termina no ultimo risco (passar dele fazia um Y)
    # os riscos das pontas atravessam o arco (2 celulas para dentro): o arco acaba no meio deles, como um fim de
    # curso; em T, a ponta do arco e o risco faziam uma seta
    riscos = set().union(*(linha_pixel(ex, ey, reto(k * KN_PASSO), KN_ARCO - (2.4 if abs(k) == 5 else KN_RISCO[0]), KN_ARCO + KN_RISCO[1])
                           for k in range(-5, 6))) - set(px)
    arco -= riscos
    ponteiros = []
    for k in range(-5, 6):   # o ponteiro deita com o tampo: o angulo da escala achatado na altura da elipse
        a = math.radians(k * KN_PASSO)
        risco = linha_pixel(cx, cy, reto(math.degrees(math.atan2(math.sin(a), math.cos(a) * ry / rx))), *KN_PONTEIRO)
        borda = {(x + dx, y + dy) for x, y in risco for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - risco   # em volta toda: a mesma grossura em todo angulo
        ponteiros.append({**{c: "O" for c in borda}, **{c: "P" for c in risco}})
    return px, riscos, arco, ponteiros, (cx, cy)


# ---------- knob de cada familia pela silhueta
# (do mock E1): o de baquelite escuro com o ponteiro creme no Ambiente e o chicken-head
# creme no Radio e alto-falante; o Personagem segue com o creme. A escala e a mesma dos tres ----------
# o baquelite: o tampo e a saia do creme em marrom quase preto, a saia frisada e o ponteiro creme de 2 celulas
KB_COR = {"O": (26, 11, 4, 1), "W": (120, 78, 54, 1), "F": (78, 47, 31, 1), "A": (52, 30, 19, 1),
          "L": (98, 61, 41, 1), "T": (70, 42, 28, 1), "E": (47, 27, 17, 1), "P": (238, 224, 198, 1),
          "s": (12, 6, 3, .42)}
KB_PONTEIRO = (4.5, 11.5)   # do miolo ate a beira da luz: o traco do mock, que sai da beira e para antes do centro
KB_FRISO = 22.5             # graus entre os frisos da saia (no cilindro visto de frente eles apertam nos lados)
# o chicken-head do Megafone do mock E1 (a versao do chicken-head do mock do
# megafone): o knob creme redondo com uma ponta saindo de um lado, na gota (o circulo do corpo e o da ponta),
# a parede de KN_SAIA linhas embaixo seguindo a mesma forma e o traco escuro da ponta ate perto do centro. O
# knob inteiro gira para o risco, as linhas e as cores sao as do creme. Grande como no mock (aqui tinha ficado pequeno): o corpo com o raio do creme e a ponta a ~18
# celulas do centro. No lugar do creme e com a parede dele (mais para cima e com
# a parede): em cima a escala fica mais perto que a ponta, e a ponta passa por cima dela, como o knob de verdade
# sobre o painel e a Policia do mock
KF_CORPO = 14.      # raio do corpo redondo, no centro do knob
KF_PONTA = (16.8, 1.0)  # o circulo da ponta: centro no eixo e raio (a ponta do mock)
KF_SOBRE = True     # a ponta passa por cima da escala onde chega nela; False = recua ate a folga
KF_FOLGA = 2        # onde nao chega: distancia minima (em celulas, na diagonal tambem) a escala, 1 celula vazia
KF_TRACO = (2, 2.5)     # o traco escuro do ponteiro: do raio de dentro ate esta distancia antes da ponta
KF_COR = KN_COR


def knob_baquelite_camadas():
    """O knob de baquelite: o desenho do creme (tampo, saia, contorno e sombra) nas cores de KB_COR, a saia
    com os frisos verticais (a coluna de cada friso um tom abaixo, mais juntos nos lados como num cilindro), e
    o ponteiro creme de 2 celulas, sem contorno (no escuro o creme ja separa)."""
    px, riscos, arco, _, (cx, cy) = knob_camadas()
    rx = KN_R[0] - KN_TRACO[1]
    frisos = {math.floor(cx + rx * math.sin(math.radians(a))) for a in [i * KB_FRISO for i in range(-3, 4)]}
    escuro = {"L": "T", "T": "E", "E": "O"}
    for (x, y), v in px.items():
        if v in escuro and x in frisos:
            px[(x, y)] = escuro[v]
    ponteiros = []
    for k in range(-5, 6):
        g = reto(k * KN_PASSO)
        risco = linha_pixel(cx, cy, g, *KB_PONTEIRO)
        lado = (0, 1) if 45 < abs(g) % 180 < 135 else (1, 0)   # deitado engrossa para baixo, em pe para a direita
        ponteiros.append({c: "P" for c in risco | {(x + lado[0], y + lado[1]) for x, y in risco}})
    return px, riscos, arco, ponteiros, (cx, cy)


def gota(px_, py_, r1, r2, h):
    """Distancia com sinal a gota (o fecho convexo de dois circulos no eixo y: raio r1 em 0, r2 em h)."""
    px_ = abs(px_)
    b = (r1 - r2) / h
    a = math.sqrt(1 - b * b)
    k = -b * px_ + a * py_
    if k < 0:
        return math.hypot(px_, py_) - r1
    if k > a * h:
        return math.hypot(px_, py_ - h) - r2
    return a * px_ + b * py_ - r1


KF_CHAPEU = (6., 3., 14.5)    # (r16) ponta de 3: o miolo creme cabe na ponta tambem na horizontal (o MEGAFONE virava toco preto). (r15) ponta de 2,5: o bico que passa da saia com recheio creme por dentro do contorno (com 1,5 era so contorno). (madrugada r09) o chapeu em gota por cima da saia: raio de tras, raio da ponta, distancia da ponta
KF_SOBE = 0                 # o chapeu acima do tampo da saia (r11: chato; a parede de 2 virava uma faixa preta de 3 css)
# a saia na mesma paleta do chapeu: um tom abaixo (o tampo dela no aro) escurecia o knob e ele lia como duas pecas
# empilhadas; no mesmo creme ele segue da familia dos outros e a gota se le pelo contorno
KF_SAIA_LETRA = {"W": "F", "F": "L", "A": "A", "L": "A", "T": "T", "E": "E"}   # (r15) a face redonda em (216,198,170), entre o creme e o taupe da r14 (no mostarda do MEGAFONE o taupe sumia); a parede segue nos dois tons de sombra


def _frango_camada(graus, cx, cy, n, r1, r2, h, saia, letra=None):
    """Uma camada do chicken-head (a saia redonda ou o chapeu em gota) apontada para graus, com o tampo em cy e a
    parede de saia linhas embaixo: a linha preta de KN_TRACO por dentro da beira e na divisa do tampo com a parede,
    a luz em crescente em cima a esquerda e o aro escuro embaixo a direita, a parede clara a esquerda e escura a
    direita. letra (opcional) troca as letras da camada."""
    sx, sy = math.sin(math.radians(graus)), -math.cos(math.radians(graus))

    def tampo(x, y, desce=0):
        dx, dy = x + .5 - cx, y + .5 - (cy + desce)
        if h <= 0:
            return math.hypot(dx, dy) - r1
        u, v = dx * sx + dy * sy, dx * -sy + dy * sx
        return gota(v, u, r1, r2, h)

    fino, grosso = KN_TRACO
    px = {}
    for y in range(n):
        for x in range(n):
            ks = [k for k in range(saia + 1) if tampo(x, y, k) < 0]
            if not ks:
                continue
            solido, topo = min(tampo(x, y, k) for k in range(saia + 1)), tampo(x, y)
            if solido >= -(grosso if ks[0] > 0 else fino) or -fino <= topo < 0:
                px[(x, y)] = "O"
            elif topo < 0:
                gx, gy = tampo(x + .2, y) - tampo(x - .2, y), tampo(x, y + .2) - tampo(x, y - .2)
                ang = math.degrees(math.atan2(gx, -gy))
                perto = topo > -fino - 2
                # (r16) a luz de cima a esquerda pega o flanco de normal ate -125 graus (com -100 o bico apontado para as 11h
                # ficava sem o filete claro no flanco esquerdo)
                px[(x, y)] = "W" if perto and -125 <= ang <= 45 else "A" if perto and (ang >= 75 or ang <= -150) else "F"
            else:
                k = ks[0]
                gx, gy = tampo(x + .2, y, k) - tampo(x - .2, y, k), tampo(x, y + .2, k) - tampo(x, y - .2, k)
                nx = gx / (math.hypot(gx, gy) or 1)
                px[(x, y)] = "L" if nx < -.45 else "T" if nx < .2 else "E"
    if letra:
        px = {c: letra.get(v, v) for c, v in px.items()}
    return px


def knob_frango_quadro(graus, cx, cy, n, recuo=0.):
    """Um quadro do chicken-head apontado para graus (0 para cima, horario), em letras de KF_COR. (r09) Em duas
    camadas, como o de verdade: a saia redonda do raio do creme (KF_CORPO), na mesma paleta, com a parede de
    KN_SAIA linhas; e por cima dela o chapeu em gota (KF_CHAPEU), KF_SOBE linhas mais alto, mais estreito que a
    saia e com a ponta passando dela: de qualquer angulo a ponta le contra o redondo de baixo (a gota do
    tamanho da saia, de antes, lia como knob redondo nos angulos oblíquos). O traco escuro do ponteiro com o
    contorno vai do centro ate perto da ponta, e a sombra dura embaixo. recuo encurta a ponta (celulas)."""
    r1, r2, h = KF_CHAPEU
    h -= recuo
    px = _frango_camada(graus, cx, cy, n, KF_CORPO, KF_CORPO, 0, KN_SAIA, KF_SAIA_LETRA)
    saia = dict(px)
    chapeu = _frango_camada(graus, cx, cy - KF_SOBE, n, r1, r2, h, KF_SOBE)
    # (r12) uma silhueta so: o contorno preto so por fora (a saia e o bico que passa dela); o contorno do chapeu por
    # dentro do tampo da saia vira o degrau de sombra (A), sem o segundo anel escuro
    # (r14) a gota creme inteira, com o contorno e a luz dela, por cima da face redonda baixada um tom (KF_SAIA_LETRA):
    # o formato de bico se le pela cor e pelo contorno, e a ponta creme passa da saia
    px.update(chapeu)
    # (r15) a sombra da gota na face: 1 px (T) embaixo e a direita do contorno dela, longe da luz (cima a esquerda)
    face = {c for c, v in _frango_camada(graus, cx, cy, n, KF_CORPO, KF_CORPO, 0, KN_SAIA).items() if v in ("W", "F", "A")}
    for x, y in chapeu:
        if (x + 1, y + 1) in face and (x + 1, y + 1) not in chapeu:
            px[(x + 1, y + 1)] = "T"
    # o ponteiro: 1 px escuro no eixo, so por dentro do bico (a ponta creme contornada e a extremidade dele)
    risco = linha_pixel(cx, cy - KF_SOBE, graus, KF_TRACO[0], h + r2 - 3)
    px.update({c: "O" for c in risco if chapeu.get(c) not in (None, "O")})
    for x, y in list(px):
        if (x, y + 2) not in px:
            px[(x, y + 2)] = "s"
    return px


def knob_frango_camadas():
    """O chicken-head: o corpo e so a escala (o knob inteiro gira, entao cada risco tem o seu quadro) e os
    11 quadros. Mesmo quadro de celulas, centro e escala do creme, para a margem do .p-grande servir aos tres. Em
    cima a escala chega mais perto (o centro dela fica abaixo do do knob): com KF_SOBRE a ponta que chega nela passa
    por cima (a escala some embaixo do knob); a que so encostaria, sem passar, recua ate a celula vazia de KF_FOLGA,
    como em volta do creme (encostada parecia colada no risco)."""
    _, riscos, arco, _, (cx, cy) = knob_camadas()
    escala = riscos | arco
    folga = lambda q: min(max(abs(x - u), abs(y - v)) for (x, y), l in q.items() if l != "s" for u, v in escala)
    quadros = []
    for k in range(-5, 6):
        recuo = 0.
        while True:
            q = knob_frango_quadro(reto(k * KN_PASSO), cx, cy, 64, recuo)
            if (KF_SOBRE and escala & {c for c, l in q.items() if l != "s"}) or folga(q) >= KF_FOLGA:
                break
            recuo += .1
        quadros.append(q)
    # a escala inteira, sem tirar o que os quadros cobrem: ela e uma so para os 11, e o quadro, desenhado depois dela,
    # ja tapa o pedaco embaixo do knob (e deixa a escala a vista, escurecida, embaixo da sombra)
    return {}, riscos, arco, quadros, (cx, cy)


# ---------- botoes de fliperama do Locutor (o fliperama 3 do mock, levado para o tema):
# o unico controle de verdade da pedaleira (os knobs sao enfeite), sem o footswitch e sem o LED: dois botoes de capa
# transparente, NATURAL em cima e CARICATO embaixo, e o logo "Locutor FM" numa linha no meio. O botao: o contorno, a
# caixa escura, a capa em chanfro (a luz em cima e a esquerda) com os reflexos nos cantos e o miolo com a palavra;
# apagado creme com a palavra escura e a sombra dura, aceso vermelho com a palavra clara e o brilho em degraus.
# Desligado e o estado sem luz, sem "OFF". Quadrado como o do mock (mais quadrados,
# com mais espaco em cima e a COMP mais para baixo): a caixa escura de 1 deixa o CARICATO caber no miolo ----------
ARC_BOTAO = (52, 52)   # o botao com o contorno
ARC_CAIXA = 1          # a caixa escura entre o contorno e a capa
ARC_MARGEM = 5         # o quadro sai do botao o tanto do brilho (4) e da sombra (2)
ARC_LARG = 68          # a largura das listras embaixo do logo: o miolo do pedal de 80 px da tela de 360
# a letra estreita das palavras, 10 de altura (a dos nomes grandes tem 11) e traco de 1: o CARICATO cabe no miolo
ARC_LETRA = {
    "A": [".XX.", "X..X", "X..X", "X..X", "X..X", "XXXX", "X..X", "X..X", "X..X", "X..X"],
    "C": [".XX.", "X..X", "X...", "X...", "X...", "X...", "X...", "X...", "X..X", ".XX."],
    "I": ["XXX", ".X.", ".X.", ".X.", ".X.", ".X.", ".X.", ".X.", ".X.", "XXX"],
    "L": ["X...", "X...", "X...", "X...", "X...", "X...", "X...", "X...", "X...", "XXXX"],
    "N": ["X..X", "XX.X", "XX.X", "XX.X", "X.XX", "X.XX", "X.XX", "X..X", "X..X", "X..X"],
    "O": [".XX.", "X..X", "X..X", "X..X", "X..X", "X..X", "X..X", "X..X", "X..X", ".XX."],
    "R": ["XXX.", "X..X", "X..X", "X..X", "XXX.", "X.X.", "X.X.", "X..X", "X..X", "X..X"],
    "T": ["XXX", ".X.", ".X.", ".X.", ".X.", ".X.", ".X.", ".X.", ".X.", ".X."],
    "U": ["X..X", "X..X", "X..X", "X..X", "X..X", "X..X", "X..X", "X..X", "X..X", ".XX."],
}
# a letra do logo, 11 de altura e traco de 2, as minusculas da linha 3; inclinada 1 celula a cada 4 linhas. O o, o c
# e o u com 6 de largura e o furo de 2 (com o furo de 1 ficavam dificeis de ler no celular): o logo
# enche os 68 px do miolo do pedal
ARC_LOGO = {
    "L": ["XX...", "XX...", "XX...", "XX...", "XX...", "XX...", "XX...", "XX...", "XX...", "XXXXX", "XXXXX"],
    "o": [None, None, None, ".XXXX.", "XX..XX", "XX..XX", "XX..XX", "XX..XX", "XX..XX", "XX..XX", ".XXXX."],
    "c": [None, None, None, ".XXXX.", "XX..XX", "XX....", "XX....", "XX....", "XX....", "XX..XX", ".XXXX."],
    "u": [None, None, None, "XX..XX", "XX..XX", "XX..XX", "XX..XX", "XX..XX", "XX..XX", "XX..XX", ".XXXXX"],
    "t": [None, ".XX.", ".XX.", "XXXX", ".XX.", ".XX.", ".XX.", ".XX.", ".XX.", ".XX.", "..XX"],
    "r": [None, None, None, "XX.XX", "XXXX.", "XXX..", "XX...", "XX...", "XX...", "XX...", "XX..."],
    "F": ["XXXXX", "XXXXX", "XX...", "XX...", "XXXX.", "XXXX.", "XX...", "XX...", "XX...", "XX...", "XX..."],
    "M": ["XX....XX", "XXX..XXX", "XXXXXXXX", "XX.XX.XX", "XX.XX.XX", "XX....XX", "XX....XX", "XX....XX", "XX....XX",
          "XX....XX", "XX....XX"],
    " ": [None] * 11,
}
ARC_ESPACO = 2
# fliperama velho (o novo tinha cara de botao novo, nao de fliperama amarelado):
# a capa de plastico amarelada, e mais nas laterais, que somam plastico; o miolo e a etiqueta de dentro, encapsulada,
# que amarela menos, num fundo marcado pela linha da borda do plastico e a sombra
# dela em cima e a esquerda (sem o fundo, desligado ele parecia uma tecla de computador gigante). Proporcao dele:
# a capa no amarelado cheio e o miolo a 40% dele, sobre o creme escuro em que a letra de 1 px se le no celular
ARC_FACETA = {   # a capa transparente: cima, esquerda, direita, baixo
    "apagado": [(232, 220, 176, 1), (212, 198, 152, 1), (172, 156, 112, 1), (138, 124, 88, 1)],
    "aceso": [(255, 196, 150, 1), (246, 148, 104, 1), (204, 78, 44, 1), (160, 46, 26, 1)],
}
ARC_COR = {"contorno": (26, 11, 4, 1), "caixa_luz": (88, 62, 48, 1), "caixa": (50, 32, 24, 1), "caixa_sombra": (30, 18, 12, 1),
           "miolo": (214, 203, 176, 1), "letra": (38, 18, 10, 1),
           "aceso": (214, 36, 23, 1), "aceso_meio": (243, 62, 40, 1), "letra_acesa": (255, 235, 190, 1),
           "reflexo": (255, 255, 255, .95), "sombra": (12, 6, 3, .42), "brilho": (255, 70, 34)}
ARC_FUNDO = {   # o miolo no fundo da capa: a linha da borda do plastico e as duas linhas da sombra dela
    "apagado": ((150, 132, 90, 1), (188, 178, 156, 1), (202, 193, 172, 1)),
    "aceso": ((176, 60, 30, 1), (196, 34, 24, 1), (214, 44, 30, 1)),
}
# o reflexo da luz na capa, no canto de cima a esquerda (o de baixo a direita e ele girado): um risco de 2 celulas na
# diagonal (com o de 3 celulas soltas quase nao se via no celular)
ARC_REFLEXO = ["...XX", "..XX.", ".XX..", "XX...", "X...."]
ARC_BRILHO = (.4, .27, .15, .07)   # o brilho do aceso, da beira do botao para fora
ARC_LISTRAS = ((58, 24, 12, 1), (224, 104, 42, 1), (240, 168, 48, 1))   # embaixo do logo, como no mock


def texto_pixel(fonte, s, vao=1):
    """As celulas do texto numa letra de ARC_LETRA ou ARC_LOGO, com o canto de cima a esquerda em (0, 0), e a largura."""
    cels, x = set(), 0
    for ch in s:
        g = fonte[ch]
        larg = max((len(r) for r in g if r), default=ARC_ESPACO)
        cels |= {(x + i, y) for y, r in enumerate(g) if r for i, v in enumerate(r) if v == "X"}
        x += larg + vao
    return cels, x - vao


def retangulo_degrau(x0, y0, x1, y1, corte):
    """As celulas de [x0, x1) x [y0, y1) com os cantos cortados em degrau (corte[i] celulas na linha i do canto)."""
    cels = set()
    for y in range(y0, y1):
        i = min(y - y0, y1 - 1 - y)
        c = corte[i] if i < len(corte) else 0
        cels |= {(x, y) for x in range(x0 + c, x1 - c)}
    return cels


def dilata(cels, n=1):
    out = set(cels)
    for _ in range(n):
        out |= {(x + dx, y + dy) for x, y in out for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    return out


def arcade_botao(palavra):
    """O SVG de um botao (aspas duplas, para morar numa string de JS) com as duas camadas, o g.arc-apagado e o
    g.arc-aceso, que o tema troca pelo modo ligado. O quadro sai do botao ARC_MARGEM celulas de cada lado."""
    bw, bh = ARC_BOTAO
    m, c = ARC_MARGEM, ARC_COR
    k = 1 + ARC_CAIXA   # onde comeca a capa
    mi = k + 3          # onde comeca o miolo (a capa tem 3)
    fora = retangulo_degrau(0, 0, bw, bh, [2, 1])
    caixa = retangulo_degrau(1, 1, bw - 1, bh - 1, [1])
    capa = retangulo_degrau(k, k, bw - k, bh - k, [1])
    miolo = {(x, y) for x in range(mi, bw - mi) for y in range(mi, bh - mi)}
    letras, tw = texto_pixel(ARC_LETRA, palavra)
    # (r16) centrado na area clara da etiqueta (sem a borda e a sombra de 1 na esquerda): o C do CARICATO encostava no chanfro
    ox, oy = mi + 2 + (bw - 2 * mi - 3 - tw) // 2, mi + (bh - 2 * mi - 10) // 2
    camadas = {}
    for estado in ("apagado", "aceso"):
        aceso = estado == "aceso"
        px = {}
        if aceso:   # o brilho em degraus em volta, mais fraco a cada celula
            for d, a in enumerate(ARC_BRILHO, 1):
                for cel in dilata(fora, d) - dilata(fora, d - 1):
                    px[cel] = c["brilho"] + (a,)
        else:
            for x, y in fora:
                for k in (1, 2):
                    if (x, y + k) not in fora:
                        px[(x, y + k)] = c["sombra"]
        for cel in fora - caixa:
            px[cel] = c["contorno"]
        for x, y in caixa - capa:
            px[(x, y)] = c["caixa_luz"] if y < k else c["caixa_sombra"] if y >= bh - k else c["caixa"]
        for x, y in capa - miolo:   # cada celula do chanfro no tom do lado mais perto
            lado = min(range(4), key=lambda i: (y - k, x - k, bw - 1 - k - x, bh - 1 - k - y)[i])
            px[(x, y)] = ARC_FACETA[estado][lado]
        borda, sombra1, sombra2 = ARC_FUNDO[estado]
        for x, y in miolo:
            if x in (mi, bw - mi - 1) or y in (mi, bh - mi - 1):   # a borda do plastico em volta da etiqueta
                px[(x, y)] = borda
            elif y == mi + 1 or x == mi + 1:   # a sombra da borda em cima e a esquerda
                px[(x, y)] = sombra1
            elif y == mi + 2:
                px[(x, y)] = sombra2
            elif aceso:
                px[(x, y)] = c["aceso_meio"] if mi + 2 <= x < bw - mi - 2 and mi + 2 <= y < bh - mi - 2 else c["aceso"]
            else:
                px[(x, y)] = c["miolo"]
        for x, y in letras:
            px[(ox + x, oy + y)] = c["letra_acesa" if aceso else "letra"]
        for dy, linha in enumerate(ARC_REFLEXO):   # a luz batendo no plastico: branca nos dois estados, nao amarela com a capa
            for dx, v in enumerate(linha):
                if v == "X":
                    px[(mi + 1 + dx, mi + 1 + dy)] = px[(bw - mi - 2 - dx, bh - mi - 2 - dy)] = c["reflexo"]
        camadas[estado] = "".join(caminhos({(x + m, y + m): v for (x, y), v in px.items()}, bw + 2 * m, bh + 2 * m, '"'))
    w, h = bw + 2 * m, bh + 2 * m
    return (f'<svg class="arcade" viewBox="0 0 {w} {h}" width="{w}" height="{h}" shape-rendering="crispEdges">'
            f'<g class="arc-apagado">{camadas["apagado"]}</g><g class="arc-aceso">{camadas["aceso"]}</g></svg>')


def arcade_logo():
    """O SVG do logo "Locutor FM": a letra creme inclinada com o contorno escuro e a sombra em degrau (marrom e
    laranja) para baixo e a direita, e as tres listras embaixo, na largura do miolo do pedal."""
    letras, _ = texto_pixel(ARC_LOGO, "Locutor FM")
    alt = len(ARC_LOGO["L"])
    cheio = {(x + (alt - 1 - y) // 4, y) for x, y in letras}
    contorno = dilata(cheio) - cheio
    tudo = cheio | contorno
    sombra1 = {(x + 1, y + 1) for x, y in tudo} - tudo
    sombra2 = {(x + 2, y + 2) for x, y in tudo} - tudo - sombra1
    px = {cel: (224, 104, 42, 1) for cel in sombra2}
    px.update({cel: (58, 24, 12, 1) for cel in sombra1})
    px.update({cel: ARC_COR["contorno"] for cel in contorno})
    px.update({cel: (250, 238, 210, 1) for cel in cheio})
    x0, y0 = min(x for x, _ in px), min(y for _, y in px)
    lw, lh = max(x for x, _ in px) - x0 + 1, max(y for _, y in px) - y0 + 1
    dx = (ARC_LARG - lw) // 2 - x0
    px = {(x + dx, y - y0): v for (x, y), v in px.items()}
    for i, cor in enumerate(ARC_LISTRAS):
        for x in range(4, ARC_LARG - 4):
            px[(x, lh + 1 + 2 * i)] = cor
    w, h = ARC_LARG, lh + 2 * len(ARC_LISTRAS)
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" shape-rendering="crispEdges">'
            + "".join(caminhos(px, w, h, '"')) + "</svg>")


# o trilho e o pino da chave de correr que o fim do disco teve ate 22/10 (na lingua das teclas do lado: contorno de 2
# celulas, cantos em degrau, bisel duro e sombra dura de 3 celulas), hoje o trilho e o cursor das barras do palco. A
# chave e 45 x 24 celulas de 4/3 px (4 de tela no celular de teste): 60 x 32 px, inteiros, para o degrau cair na grade da
# tela
CH_TAM = (45, 24)
CH_PINO = (18, 20)
CH_COR = {"contorno": (26, 11, 4, 1), "pino": (230, 223, 211, 1), "luz": (255, 255, 255, 1),
          "sombra": (166, 157, 142, 1), "risco": (138, 128, 113, 1), "sombra_dura": (20, 8, 2, .62),
          "beira": (255, 236, 214, .22),
          # o fundo do trilho de cima para baixo, apagado e aceso: a beira de cima faz sombra e a de baixo pega luz
          "trilho": ((18, 12, 9, 1), (30, 24, 21, 1), (46, 38, 34, 1), (46, 38, 34, 1), (46, 38, 34, 1), (64, 53, 46, 1)),
          "aceso": ((138, 74, 18, 1), (232, 144, 42, 1), (255, 200, 103, 1), (243, 167, 60, 1), (243, 167, 60, 1),
                    (217, 133, 42, 1))}


def degrau(x0, y0, w, h, corte):
    """As celulas de um retangulo com os cantos em degrau (corte celulas na diagonal de cada canto)."""
    return {(x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h)
            if min(x - x0, x0 + w - 1 - x) + min(y - y0, y0 + h - 1 - y) >= corte}


def aneis(forma):
    """{celula: quantas celulas da beirada} pela vizinhanca de 4: o contorno e o bisel acompanham o degrau."""
    resto, out, i = set(forma), {}, 0
    while resto:
        beira = {(x, y) for x, y in resto if not {(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)} <= resto}
        out.update({c: i for c in beira})
        resto -= beira
        i += 1
    return out


def pino_px(kx=0):
    """O pino creme com a beira esquerda em kx: o contorno, o bisel duro, os tres riscos de pegar e a sombra dura de 3
    celulas embaixo (o cursor das barras do palco)."""
    c, (pw, ph) = CH_COR, CH_PINO
    px = {}
    pino = degrau(kx, 0, pw, ph, 2)
    px.update({(x, y + 3): c["sombra_dura"] for x, y in pino if (x, y + 3) not in pino})
    for (x, y), i in aneis(pino).items():
        if i < 2:
            px[(x, y)] = c["contorno"]
        elif i == 2:   # o bisel: luz em cima e a esquerda, sombra embaixo e a direita
            px[(x, y)] = c["luz"] if min(y, x - kx) <= min(ph - 1 - y, kx + pw - 1 - x) else c["sombra"]
        else:
            px[(x, y)] = c["pino"]
    for dx in (5, 8, 11):   # os riscos de pegar, fundos: a parede escura e a beira acesa do lado
        px.update({(kx + dx, y): c["risco"] for y in range(6, ph - 6)})
        px.update({(kx + dx + 1, y): c["luz"] for y in range(6, ph - 6)})
    return px


# a chave do fim do disco ("So este disco", a chave e "Tocar parecidas" embaixo dos botoes do
# toca-discos, sem caixa), a 110/220 de aparelho desde 22/10 (a de correr parecia as barras; como as chaves
# de 110/220, pela foto de uma de verdade: o cursor e quadrado e sobra um espaco pequeno so para o numero,
# 110 ou 220, 220 no automatico): a chapa no marrom das teclas do lado (escolhido entre preta, marrom e latao),
# com o contorno de 2 celulas, os cantos em degrau, o bisel e a sombra dura delas, um parafuso em cada ponta e a janela
# no meio, cheia do plastico vermelho. O pegador quadrado, com o risco no meio, vai para o lado escolhido (a
# posicao do pegador diz mais que o numero) e no vermelho que sobra aparece a voltagem, 110 desligada e 220 ligada
CV_CHAPA = (0, 0, 45, 21)
CV_PARAF = ((5.5, 10.5), (39.5, 10.5), 2.8)   # os centros e o raio
CV_JANELA = (10, 4, 25, 13)   # com o contorno de 1
CV_PEGADOR = 10
CV_DIGITO = {"1": [".X.", "XX.", ".X.", ".X.", "XXX"], "2": ["XX.", "..X", ".X.", "X..", "XXX"],
             "0": [".X.", "X.X", "X.X", "X.X", ".X."]}
CV_COR = {"chapa": (102, 48, 26, 1), "luz": (195, 165, 144, 1), "sombra": (66, 30, 15, 1), "beira": (150, 100, 72, 1),
          "plastico": (206, 42, 30, 1), "plastico_sombra": (150, 24, 16, 1),
          "pegador": (228, 62, 44, 1), "pegador_luz": (255, 120, 94, 1), "pegador_sombra": (156, 26, 18, 1),
          "risco": (120, 16, 10, 1), "numero": (255, 236, 214, 1),
          "metal": ((236, 238, 240, 1), (190, 194, 199, 1), (128, 131, 136, 1)), "fenda": (46, 40, 38, 1)}


def chave_camadas(ligada):
    """As celulas da chave: 110 com o pegador na esquerda ou, ligada, 220 com ele na direita."""
    c, k, px = CH_COR, CV_COR, {}
    w, h = CH_TAM
    x0, y0, cw, chh = CV_CHAPA
    chapa = degrau(x0, y0, cw, chh, 2)
    px.update({(x, y + 3): c["sombra_dura"] for x, y in chapa if (x, y + 3) not in chapa})
    for (x, y), i in aneis(chapa).items():
        if i < 2:
            px[(x, y)] = c["contorno"]
        elif i == 2:   # o bisel: luz em cima e a esquerda, sombra embaixo e a direita
            px[(x, y)] = k["luz"] if min(y - y0, x - x0) <= min(y0 + chh - 1 - y, x0 + cw - 1 - x) else k["sombra"]
        else:
            px[(x, y)] = k["chapa"]
    # os parafusos: o contorno, a cabeca de metal com a luz em cima a esquerda e a fenda inclinada
    *centros, r = CV_PARAF
    for cx, cy in centros:
        for x in range(w):
            for y in range(h):
                d = math.hypot(x + .5 - cx, y + .5 - cy)
                if d < r:
                    lado = (x + .5 - cx) + (y + .5 - cy)
                    px[(x, y)] = (c["contorno"] if d >= r - 1 else k["metal"][0] if lado < -1.2
                                  else k["metal"][2] if lado > 1.2 else k["metal"][1])
        px.update({(math.floor(cx - .5) + t, math.floor(cy - .5) - t): k["fenda"] for t in (-1, 0, 1)})
    # a janela: o contorno de 1, o plastico com a sombra da chapa na linha de cima e, embaixo, o corte da chapa no escuro
    jx, jy, jw, jh = CV_JANELA
    janela = {(x, y) for x in range(jx, jx + jw) for y in range(jy, jy + jh)}
    px.update({(x, jy + jh): k["beira"] for x in range(jx + 1, jx + jw - 1)})
    for (x, y), i in aneis(janela).items():
        px[(x, y)] = c["contorno"] if i < 1 else k["plastico_sombra"] if y == jy + 1 else k["plastico"]
    # o pegador: quadrado, da altura da janela, com o bisel, o risco no meio e a sombra dele no plastico do lado
    iy, ih = jy + 1, jh - 2
    kx = jx + jw - 1 - CV_PEGADOR if ligada else jx + 1
    if not ligada:
        px.update({(kx + CV_PEGADOR, y): k["plastico_sombra"] for y in range(iy, iy + ih)})
    for x in range(kx, kx + CV_PEGADOR):
        for y in range(iy, iy + ih):
            borda_lt = x == kx or y == iy
            borda_rb = x == kx + CV_PEGADOR - 1 or y == iy + ih - 1
            px[(x, y)] = k["pegador_sombra"] if borda_rb else k["pegador_luz"] if borda_lt else k["pegador"]
    meio = kx + CV_PEGADOR // 2 - 1
    px.update({(meio, y): k["risco"] for y in range(iy + 2, iy + ih - 2)})
    px.update({(meio + 1, y): k["pegador_luz"] for y in range(iy + 2, iy + ih - 2)})
    # a voltagem no vermelho que sobra, no meio dele
    numero = "220" if ligada else "110"
    cels, larg = set(), 0
    for ch in numero:
        g = CV_DIGITO[ch]
        cels |= {(larg + i, y) for y, linha in enumerate(g) for i, v in enumerate(linha) if v == "X"}
        larg += len(g[0]) + 1
    larg -= 1
    livre0 = jx + 1 if ligada else kx + CV_PEGADOR
    livre1 = kx if ligada else jx + jw - 1
    nx, ny = livre0 + (livre1 - livre0 - larg) // 2, iy + (ih - 5) // 2
    px.update({(nx + x, ny + y): k["numero"] for x, y in cels})
    return px


def chave_parecidas():
    """O SVG da chave (aspas duplas, para morar numa string de JS) com as duas camadas, o g.ch-des e o g.ch-lig,
    que o tema troca pelo aria-checked do botao."""
    w, h = CH_TAM
    camadas = {ligada: "".join(caminhos(chave_camadas(ligada), w, h, '"')) for ligada in (False, True)}
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" shape-rendering="crispEdges">'
            f'<g class="ch-des">{camadas[False]}</g><g class="ch-lig">{camadas[True]}</g></svg>')


# ---------- as barras do palco (tempo e volumes) ----------
# no estilo da chave de correr que o fim do disco tinha (o slider da musica e dos volumes no estilo
# do botao antigo): o trilho dela numa border-image de 9 partes (o contorno de 2 celulas com os
# cantos em degrau e, embaixo, a beira acesa: fatias 2 2 3 2 de 6 x 7 celulas), o fundo e o ambar em faixas de 1
# celula (4/3 px; o tema pinta o ambar ate o centro do cursor) e o pino dela como cursor
def trilho_moldura():
    c = CH_COR
    t = degrau(0, 0, 6, 6, 2)
    px = {(x, y + 1): c["beira"] for x, y in t if (x, y + 1) not in t}
    px.update({cel: c["contorno"] for cel, i in aneis(t).items() if i < 2})
    return uri(px, 6, 7)


def faixas_css(cores):
    """As faixas de 1 celula de cima para baixo num linear-gradient de paradas duras (as iguais juntas)."""
    paradas, n = [], 0
    for i, (r, g, b, _) in enumerate(cores):
        n += 4
        if i + 1 < len(cores) and cores[i + 1] == cores[i]:
            continue
        paradas.append(f"#{r:02X}{g:02X}{b:02X} 0 calc({n}px / 3)")
    return "linear-gradient(" + ", ".join(paradas) + ")"


# ---------- o salvar da parecida no prato ----------
# o ⊕ que poe a parecida na prateleira: o botao de tocar em
# miniatura, 24 celulas de 4/3 px (32 px): o contorno, a linha clara, o aro cinza, a linha escura e a face creme com
# o + em tinta. Baixando, o aro acende em ambar celula a celula no sentido do relogio (o JS liga as `on` na ordem dos
# rect); na prateleira, o aro inteiro ambar, como o tocar tocando, e o visto no lugar do +. A sombra dura e outro SVG,
# que o tema poe 2 celulas abaixo e o apertado cobre
SV_MEDIDA = (7, 3, 1, 1)   # face, aro (com a linha clara), linha escura e filete: 2 x (7 + 3 + 2 de contorno) = 24
SV_VISTO = ((7.5, 12.5), (10.5, 15.5), (16.5, 9.5))   # o visto: da ponta curta, pela quina, a ponta longa (centros)


def salvar_pixel():
    """O HTML do botao (aspas duplas, para morar numa string de JS): a sombra e o botao, cada um no seu span, e as
    cores acesas do aro para o tema."""
    face, anel, linha, filete = SV_MEDIDA
    px, w, h, _, _ = botao(face, anel, linha, ANEIS["parado"], contorno=2, filete=filete)
    meio, luz, escuro = ANEIS["parado"]
    papel = {luz: "l", meio: "m", escuro: "e"}
    c = w // 2
    relogio = lambda cel: math.degrees(math.atan2(cel[0] + .5 - c, -(cel[1] + .5 - c))) % 360
    aro = sorted((cel for cel, cor in px.items() if cor in papel), key=relogio)
    rects = "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#{px[(x, y)][0]:02X}{px[(x, y)][1]:02X}'
                    f'{px[(x, y)][2]:02X}" class="{papel[px[(x, y)]]}"/>' for x, y in aro)
    base = {cel: cor for cel, cor in px.items() if cor not in papel}
    mais = {(x, y) for x in range(c - 4, c + 4) for y in (c - 1, c)} | {(x, y) for y in range(c - 4, c + 4) for x in (c - 1, c)}

    def perto(p, a, b):   # distancia do centro da celula ao segmento a-b
        (ax, ay), (bx, by) = a, b
        t = max(0., min(1., ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
        return math.hypot(p[0] - ax - t * (bx - ax), p[1] - ay - t * (by - ay))
    visto = {(x, y) for x in range(w) for y in range(h)
             if min(perto((x + .5, y + .5), *seg) for seg in zip(SV_VISTO, SV_VISTO[1:])) < .95}
    vet = lambda cels: "".join(caminhos(cels, w, h, '"'))
    sombra, sw, sh, _, _ = silhueta(face, anel, (20, 8, 2, .58), contorno=2)
    svg = lambda corpo, sw=w, sh=h: (f'<svg viewBox="0 0 {sw} {sh}" width="{sw}" height="{sh}" shape-rendering="crispEdges"'
                                     f' aria-hidden="true">{corpo}</svg>')
    html = (f'<span class="px-sombra">{svg(vet(sombra), sw, sh)}</span><span class="px-botao">'
            + svg(f'{vet(base)}<g class="sv-aro">{rects}</g><g class="sv-mais">{vet({x: TINTA for x in mais})}</g>'
                  f'<g class="sv-visto">{vet({x: TINTA for x in visto})}</g>') + "</span>")
    acesas = dict(zip(("m", "l", "e"), ANEIS["tocando"]))
    return html, acesas, len(aro)


# ---------- a maleta do A seguir ----------
# o A seguir do celular e uma maleta de discos, como no mock da maleta (a maleta
# do mock anterior; a primeira versao ficou longe do mock). Os metais sao os do mock escolhido (23/10, entre o de hoje
# e dois mocks), 2 px por celula, com o contorno de 1 celula, o bisel duro e
# a sombra dura: os cantos de latao, os fechos da tampa, as juntas da cintura, as cantoneiras da boca, os dois fechos da
# frente e a alca em U com as presilhas. O casco e em perspectiva, como no mock (a perspectiva
# do mock levada para o codigo): a tampa aberta afina de cima ate a cintura e a
# caixa de baixo abre de novo da cintura ate a frente, as paredes de couro em degraus de 1 px
LATAO = ((214, 166, 72, 1), (252, 222, 140, 1), (142, 96, 34, 1))   # a cor, a luz e a sombra
REBITE = (92, 58, 18, 1)
COURO = ((132, 66, 30, 1), (186, 110, 60, 1), (78, 36, 14, 1))      # a alca de couro curvada com volume
COSTURA = (226, 184, 122, 1)
SOMBRA_MALETA = (20, 8, 2, .45)

# o casco, em px de tela (1 celula = 1 px, a unidade das molduras): a tampa vai da beira de cima ate a cintura, no pe do
# disco de tras (o tema poe a cintura nesta altura, --m-tampa); em cima ela fica um recuo para dentro da frente e afina
# ate a cintura. Sao duas tampas (23/10: entreaberta como no modelo da plaqueta fina; aberta, a tampa
# fica maior, como no modelo de plaquinha mais grossa): a entreaberta, curta, e a aberta,
# mais alta, com o mesmo topo e a mesma cintura (a aberta mais em pe, afinando 6, ficou ruim; vale o
# mesmo angulo da tampa nos dois modos). A caixa de baixo comeca CINTURA para dentro e abre ate a frente, um degrau
# por px
TAMPA_ENTREABERTA = (122, 2, 12)   # altura (26 de beira e forro, a plaqueta de 32, 12, o disco de tras de 52), recuo, afina
TAMPA_ABERTA = (138, 2, 12)        # a mesma plaqueta no mesmo lugar, com 16 de forro a mais embaixo dela
CINTURA = 14
COURO_CLARO = (184, 116, 66, 1)
COURO_CASCO = (122, 63, 30, 1)
# as faixas das paredes, de fora para dentro: o contorno, a beira clara, o couro, a junta escura e a face de dentro da
# parede, que se ve de cima; depois o forro da tampa ou o fundo da caixa
TAMPA_CIMA = ((2, CONTORNO), (2, COURO_CLARO), (8, COURO_CASCO), (2, CONTORNO), (6, (78, 36, 14, 1)))
TAMPA_LADO = ((2, CONTORNO), (2, COURO_CLARO), (6, COURO_CASCO), (2, CONTORNO), (4, (78, 36, 14, 1)))
FORRO = (38, 17, 7, 1)
BASE_LADO = ((2, CONTORNO), (2, COURO_CLARO), (6, COURO_CASCO), (2, CONTORNO), (3, (58, 26, 10, 1)))
COSTURA_PAREDE = 6   # a costura no couro das paredes: 2 px a esta distancia da beira de fora, 5 de linha e 4 de vao
FUNDO = (36, 16, 7, 1)


def rebite(px, x, y):
    """O rebite de 2 x 2 celulas: a cabeca escura com o ponto de luz em cima a esquerda."""
    px.update({(x, y): LATAO[1], (x + 1, y): REBITE, (x, y + 1): REBITE, (x + 1, y + 1): REBITE})


def maleta_canto(direita, baixo):
    """O canto de latao do mock: cantoneira em L arredondada que abraca a quina da maleta, com dois rebites e degrau
    interno, espelhada para cada canto."""
    n = 12
    forma = ({(x, y) for x in range(n) for y in range(n) if x + y <= 13}
             - {(0, 0), (1, 0), (0, 1), (2, 0), (0, 2)})
    esp = lambda x, y: (n - 1 - x if direita else x, n - 1 - y if baixo else y)
    cheio = {esp(x, y) for x, y in forma}
    px = bisel(cheio, *LATAO)
    for rx, ry in ((2, 5), (5, 2)):
        ex, ey = esp(rx, ry)
        rebite(px, min(ex, ex - 1 if direita else ex), min(ey, ey - 1 if baixo else ey))
    return recorta(pinta_pecas([(cheio, px)], (0, 1), SOMBRA_MALETA))


def maleta_dobradica():
    """O fecho de cima na tampa aberta: a base presa na beira da tampa e a lingueta que desce por cima da moldura da
    plaqueta creme, como no mock aberto."""
    base = {(x, y) for x in range(0, 9) for y in range(0, 5)} - {(0, 0), (8, 0)}
    aba = {(x, y) for x in range(1, 8) for y in range(4, 10)} - {(1, 9), (7, 9)}
    pb = bisel(base, *LATAO)
    pa = bisel(aba, *LATAO)
    for x in range(2, 7):
        pa[(x, 4)] = LATAO[2]
    rebite(pa, 3, 6)
    return recorta(pinta_pecas([(base, pb), (aba, pa)], (0, 1), SOMBRA_MALETA))


def maleta_meio(direita):
    """A junta de latao na cintura da maleta aberta, onde a tampa termina e a caixa de baixo comeca: as duas chapas e o
    pino da dobradica no meio. Da largura da parede, para caber nela sem sair da maleta (23/10: a
    dobradica era maior que a maleta; a de 6 celulas saia 8 px para fora)."""
    w = 5
    esp = lambda x, y: (w - 1 - x if direita else x, y)
    cima = {esp(x, y) for x in range(w) for y in range(0, 5) if not (x == w - 1 and y in (0, 4))}
    baixo = {esp(x, y) for x in range(w) for y in range(5, 10) if not (x == w - 1 and y in (5, 9))}
    pino = {esp(x, y) for x in range(0, 3) for y in range(4, 6)}
    pc = bisel(cima, *LATAO)
    pb = bisel(baixo, *LATAO)
    pp = bisel(pino, *LATAO)
    rebite(pc, 2 if direita else 1, 1)
    rebite(pb, 2 if direita else 1, 6)
    return recorta(pinta_pecas([(cima, pc), (baixo, pb), (pino, pp)], (0, 1), SOMBRA_MALETA))


def maleta_boca(direita, aba=True):
    """A cantoneira de latao na quina de cima da frente (.maleta-pe), onde a parede do lado vira a beira da frente. Sem a
    aba de cima (aba=False) para a maleta sem a caixa de baixo a vista (fechada, ou aberta com um disco so): ali a aba
    ficaria no ar ao lado da tampa, e a camera, de cima e da frente, nao a ve (23/10)."""
    w = 9
    esp = lambda x, y: (w - 1 - x if direita else x, y)
    aba_cima = {esp(x, y) for x in range(0, 5) for y in range(0, 7)} - {esp(0, 0), esp(4, 0)}
    corpo = ({esp(x, y) for x in range(0, 9) for y in range(6, 13)}
             - {esp(8, 6), esp(7, 12), esp(8, 12), esp(8, 11)})
    pa = bisel(aba_cima, *LATAO)
    pc = bisel(corpo, *LATAO)
    rebite(pa, (w - 3) if direita else 1, 2)
    rebite(pc, (w - 4) if direita else 2, 8)
    rebite(pc, (w - 7) if direita else 5, 9)
    return recorta(pinta_pecas([(aba_cima, pa), (corpo, pc)] if aba else [(corpo, pc)], (0, 1), SOMBRA_MALETA))


def maleta_fecho():
    """O fecho da frente do mock: a cabeca presa na beira de cima da frente, a chapa com rebites embaixo e a lingueta do
    meio com a trava."""
    topo = {(x, y) for x in range(1, 12) for y in range(0, 6)} - {(1, 0), (11, 0)}
    chapa = {(x, y) for x in range(0, 13) for y in range(5, 14)} - {(0, 13), (12, 13)}
    lingueta = {(x, y) for x in range(3, 10) for y in range(3, 19)} - {(3, 18), (9, 18)}
    pt = bisel(topo, *LATAO)
    pc = bisel(chapa, *LATAO)
    pl = bisel(lingueta, *LATAO)
    for y in range(6, 11):
        pl[(5, y)] = pl[(7, y)] = LATAO[2]
        pl[(6, y)] = REBITE
    rebite(pl, 5, 13)
    return recorta(pinta_pecas([(chapa, pc), (topo, pt), (lingueta, pl)], (0, 1), SOMBRA_MALETA))


def maleta_alca():
    """A alca da frente do mock: as duas presilhas de latao em cima, presas na frente, e a alca de couro grossa que desce
    e faz a curva em U por baixo."""
    presilhas = (
        {(x, y) for x in list(range(0, 12)) + list(range(56, 68)) for y in range(0, 8)}
        - {(0, 0), (11, 0), (0, 7), (11, 7), (56, 0), (67, 0), (56, 7), (67, 7)}
        | {(x, y) for x in list(range(3, 9)) + list(range(59, 65)) for y in range(8, 12)}
    )
    pp = bisel(presilhas, *LATAO)
    for rx in (2, 8, 58, 64):
        rebite(pp, rx, 2)
    for rx in (5, 61):
        rebite(pp, rx, 8)
    # o U desce das presilhas e faz a curva na barra de baixo
    arco = (
        {(x, y) for x in list(range(3, 10)) + list(range(58, 65)) for y in range(10, 18)}
        | {(x, y) for x in list(range(4, 12)) + list(range(56, 64)) for y in range(15, 21)}
        | {(x, y) for x in range(8, 60) for y in range(16, 23)}
        - {(4, 20), (5, 20), (62, 20), (63, 20), (8, 22), (9, 22), (58, 22), (59, 22)}
    )
    px_arco = bisel(arco, *COURO)
    # a luz na curva de cima da pega e a sombra na barriga de baixo
    for x in range(11, 57):
        px_arco[(x, 16)] = COURO[1]
        px_arco[(x, 17)] = COURO[1]
        px_arco[(x, 21)] = COURO[2]
    return recorta(pinta_pecas([(presilhas, pp), (arco, px_arco)], (0, 1), SOMBRA_MALETA))


def faixa(dist, faixas):
    """O indice da faixa da parede a esta distancia da beira de fora (None depois da ultima)."""
    for i, (larg, _) in enumerate(faixas):
        if dist < larg:
            return i
        dist -= larg
    return None


def espelha(px, larg):
    return {(larg - 1 - x, y): c for (x, y), c in px.items()}


def maleta_tampa(altura, recuo, afina):
    """A metade esquerda da tampa (o tema espelha para a direita): a beira de cima reta e a parede do lado em degraus,
    de recuo na beira de cima ate recuo + afina - 1 na cintura, um degrau por px. Onde a faixa de cima encontra a do
    lado vale a de fora (a quina em esquadro, que o canto de latao cobre). Do tamanho da tampa, sem esticar; a largura
    e a mesma nas duas tampas (recuo + afina igual)."""
    larg = recuo + afina + sum(w for w, _ in TAMPA_LADO) + 2
    px = {}
    for y in range(altura):
        beira = recuo + afina * y // altura
        for x in range(beira, larg):
            fs = [i for i in (faixa(x - beira, TAMPA_LADO), faixa(y, TAMPA_CIMA)) if i is not None]
            px[(x, y)] = TAMPA_CIMA[min(fs)][1] if fs else FORRO
        if y >= sum(w for w, _ in TAMPA_CIMA) and y % 9 < 5:   # a costura do lado, abaixo da beira de cima
            px[(beira + COSTURA_PAREDE, y)] = px[(beira + COSTURA_PAREDE + 1, y)] = COSTURA
    return px, larg, altura


def maleta_base():
    """A metade esquerda da caixa de baixo, uma linha por degrau: CINTURA + 1 degraus, da cintura (CINTURA para dentro)
    ate a frente (0). A caixa cresce com os discos, entao o tema estica o desenho na altura (preserveAspectRatio none):
    na largura os degraus seguem de 1 px, so ficam mais compridos."""
    larg = CINTURA + sum(w for w, _ in BASE_LADO) + 2
    px = {}
    for k in range(CINTURA + 1):
        beira = CINTURA - k
        for x in range(beira, larg):
            i = faixa(x - beira, BASE_LADO)
            px[(x, k)] = BASE_LADO[i][1] if i is not None else FUNDO
    return px, larg, CINTURA + 1


def costura_base(direita):
    """A costura da parede da caixa de baixo: uma linha so que desce os degraus (o tracejado continua de um degrau para
    o outro). Com vector-effect non-scaling-stroke o traco e o tracejado ficam em px de tela quando o desenho estica."""
    larg = CINTURA + sum(w for w, _ in BASE_LADO) + 2
    x = lambda k: CINTURA - k + COSTURA_PAREDE + 1   # o meio do traco de 2 px
    xs = [larg - x(k) if direita else x(k) for k in range(CINTURA + 1)]
    d = f"M{xs[0]} 0" + "".join(f"V{k}H{xs[k]}" for k in range(1, CINTURA + 1)) + f"V{CINTURA + 1}"
    r, g, b, _ = COSTURA
    return (f"<path d='{d}' fill='none' stroke='#{r:02X}{g:02X}{b:02X}' stroke-width='2' stroke-dasharray='5 4' "
            "vector-effect='non-scaling-stroke'/>")


DISCO_ENTREABERTO = 16   # o disco da maleta entreaberta recua 1 px a cada 16 de altura (o aberto, ~1 a cada 8)


def disco_entreaberto(lado, topo, canto=2):
    """O recorte do disco da maleta entreaberta (clip-path, em px a partir do topo do quadrado da capa): as laterais 1 px
    para dentro a cada DISCO_ENTREABERTO px de altura, entre o do disco aberto e o reto (23/10, entre seis mocks de
    1 a cada 8 a reto: primeiro a cada 12, depois a cada 16; antes era ligado a parede da tampa aberta, e
    essa relacao saiu), e o degrauzinho de pixel nas quinas de cima. 'lado' e 'topo' sao o recuo do contorno (0), do
    papelao (2) e da foto (4, 5); o pe fica atras da frente da maleta, entao os degraus vao ate 300 px e o fundo e reto."""
    ys = list(range(DISCO_ENTREABERTO, 300, DISCO_ENTREABERTO))
    L, T, c = lado, topo, canto
    px = lambda v: f"{v}px" if v else "0"
    dx = lambda v: f"calc(100% - {v}px)" if v else "100%"
    y = lambda v: f"min({v}px, 100%)"
    pts = [f"{px(L + c)} {px(T)}", f"{dx(L + c)} {px(T)}"]
    for i in range(c):
        pts += [f"{dx(L + c - i)} {px(T + i + 1)}", f"{dx(L + c - i - 1)} {px(T + i + 1)}"]
    for k, yk in enumerate(ys, 1):
        pts += [f"{dx(L + k - 1)} {y(yk)}", f"{dx(L + k)} {y(yk)}"]
    n = len(ys)
    pts += [f"{dx(L + n)} 100%", f"{px(L + n)} 100%"]
    for k in range(n, 0, -1):
        pts += [f"{px(L + k)} {y(ys[k - 1])}", f"{px(L + k - 1)} {y(ys[k - 1])}"]
    for i in range(c - 1, -1, -1):
        pts += [f"{px(L + c - i - 1)} {px(T + i + 1)}", f"{px(L + c - i)} {px(T + i + 1)}"]
    return "polygon(" + ", ".join(pts) + ")"


def uri_esticada(px, larg, alt, extra=""):
    """O uri() com o desenho livre para esticar na caixa do background-size (e um traco a mais por cima)."""
    s = svg(px, larg, alt).replace(" shape-rendering=", " preserveAspectRatio='none' shape-rendering=", 1)
    s = s.replace("</svg>", extra + "</svg>")
    return 'url("data:image/svg+xml,' + quote(s, safe=" '=/:,.-") + '")'


def knob():
    """Os SVGs dos tres knobs (aspas duplas, para morar numa string de JS), cada um com PONTEIRO no lugar do
    ponteiro e a lista dos 11 ponteiros (paths; no chicken-head, o knob inteiro), e a margem que poe o centro do
    tampo em KN_CENTRO na caixa do .p-grande. O quadro de celulas e um so para os tres, o que cobre todos."""
    tipos = {"creme": (knob_camadas(), KN_COR), "baquelite": (knob_baquelite_camadas(), KB_COR),
             "frango": (knob_frango_camadas(), KF_COR)}
    tudo = set()
    for (px, riscos, arco, ponteiros, _), _ in tipos.values():
        tudo |= set(px) | riscos | arco | set().union(*(set(p) for p in ponteiros))
    cx, cy = tipos["creme"][0][4]
    x0, y0 = min(x for x, _ in tudo), min(y for _, y in tudo)
    w, h = max(x for x, _ in tudo) - x0 + 1, max(y for _, y in tudo) - y0 + 1
    move = lambda cels: {(x - x0, y - y0): v for (x, y), v in (cels.items() if isinstance(cels, dict) else ((c, 1) for c in cels))}
    saida = {}
    for nome, ((px, riscos, arco, ponteiros, _), cor) in tipos.items():
        vetor = lambda cels: "".join(caminhos({c: cor[v] for c, v in move(cels).items()}, w, h, '"'))
        corpo = (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" shape-rendering="crispEdges"><g class="escala">'
                 f'<path class="riscos" d="{retangulos(set(move(riscos)), w, h)}"/><path class="arco" d="{retangulos(set(move(arco)), w, h)}"/></g>'
                 f'{vetor(px)}PONTEIRO</svg>')
        saida[nome] = (corpo, [vetor(p) for p in ponteiros])
    esq, topo = round(KN_CENTRO[0] - (cx - x0)), round(KN_CENTRO[1] - (cy - y0))
    margem = f"{topo}px {34 - w - esq}px {38 - h - topo}px {esq}px"
    return saida, margem


# ---------- LED dos pedais ----------
LED_N = 8            # o vidro: 8 celulas de 1 px, o tamanho do LED liso de antes
LED_BRILHO = (4, 7)  # os dois aneis do brilho aceso, em celulas alem do vidro (os do LED liso de antes)
LED_SOMBRA = 2       # a sombra dura do apagado, para baixo
# LED vermelho, como o dos pedais de verdade: O contorno,
# B vidro, b vidro na sombra, M miolo aceso, W ponto de luz, G/g os aneis do brilho, s a sombra dura
LED_COR = {
    "apagado": {"O": (26, 11, 4, 1), "B": (92, 26, 21, 1), "b": (66, 17, 14, 1), "W": (255, 236, 214, .5), "s": (12, 6, 3, .45)},
    "aceso": {"O": (61, 12, 8, 1), "B": (228, 42, 31, 1), "b": (184, 26, 19, 1), "M": (255, 112, 86, 1), "W": (255, 228, 214, 1),
              "G": (255, 54, 38, .5), "g": (255, 54, 38, .2)},
}


def led():
    """O LED dos pedais em pixel, as duas camadas num SVG so (aspas duplas, para morar
    numa string de JS): o g.led-apagado e o g.led-aceso, que o tema troca pela classe acesa. O vidro redondo
    de LED_N celulas com o contorno de 1; apagado, vermelho escuro com o ponto de luz em cima a esquerda e
    a sombra dura embaixo; aceso, o vermelho com o miolo claro e o brilho em dois aneis de degrau em volta.
    O quadro vai do brilho de fora de um lado ao do outro, com o vidro no meio."""
    m = LED_BRILHO[1]
    n = LED_N + 2 * m
    c = n / 2
    vidro = disco_pixel(LED_N / 2, c, c, n)
    contorno = {(x + dx, y + dy) for x, y in vidro for dx, dy in VIZ} - vidro
    tudo = vidro | contorno
    sombra = {(x, y + LED_SOMBRA) for x, y in tudo} - tudo
    ponto = {(m + 2, m + 2), (m + 3, m + 2), (m + 2, m + 3)}   # o ponto de luz: 3 celulas em L, em cima a esquerda
    lado = lambda x, y: (x + .5 - c) + (y + .5 - c)            # > 0 embaixo a direita
    camadas = {}
    for estado, cores in LED_COR.items():
        px = {cel: "O" for cel in contorno}
        for x, y in vidro:
            px[(x, y)] = "b" if lado(x, y) > 3 else "B"
        if estado == "aceso":
            for cel in disco_pixel(2.2, c - .5, c - .5, n):
                px[cel] = "M"
            for cel in disco_pixel(LED_N / 2 + LED_BRILHO[1], c, c, n) - tudo:
                px[cel] = "g"
            for cel in disco_pixel(LED_N / 2 + LED_BRILHO[0], c, c, n) - tudo:
                px[cel] = "G"
        else:
            for cel in sombra:
                px[cel] = "s"
        for cel in ponto:
            px[cel] = "W"
        camadas[estado] = "".join(caminhos({k: cores[v] for k, v in px.items()}, n, n + LED_SOMBRA, '"'))
    return (f'<svg viewBox="0 0 {n} {n + LED_SOMBRA}" width="{n}" height="{n + LED_SOMBRA}" shape-rendering="crispEdges">'
            f'<g class="led-apagado">{camadas["apagado"]}</g><g class="led-aceso">{camadas["aceso"]}</g></svg>'), m


def base_braco():
    """A base do pivo do tamanho do mock (10 cqw = 25 celulas; com o contorno, 10,8% do aparelho, como
    os 79 px dele em 730): o prato creme com a luz do mock, clara em cima a esquerda e bege escuro
    embaixo a direita, e a sombra."""
    n = 25
    m = n / 2
    base = disco_pixel(m, m, m, n)
    tons = ((-.5, (240, 234, 218, 1)), (-.1, (229, 222, 205, 1)), (.25, (214, 206, 189, 1)), (.55, (190, 182, 166, 1)),
            (.8, (158, 150, 137, 1)), (9, (128, 121, 111, 1)))
    px = {(x, y): next(cor for lim, cor in tons if ((x + .5 - m) + (y + .5 - m)) / (2 ** .5 * m) <= lim) for x, y in base}
    return recorta(pinta_pecas([(base, px)], (0, 3), (20, 8, 2, .4), METAL_CONTORNO))


def descanso():
    """O descanso do braco (4.4 cqw = 7 celulas): o aro escuro gordo (com o contorno, 2 celulas, como o
    anel de antes; so o contorno de 1 celula lia como um icone de liga/desliga) e a fenda escura."""
    n = 12
    d = disco_pixel(6, 6, 6, n)
    px = bisel(d, (207, 200, 187, 1), (245, 241, 234, 1), (160, 152, 139, 1))
    for c in d - disco_pixel(4.4, 6, 6, n):
        px[c] = (58, 42, 31, 1)
    for c in {(x, y) for x in (5, 6) for y in range(4, 8)}:
        px[c] = CONTORNO
    return recorta(pinta_pecas([(d, px)], (0, 2), (20, 8, 2, .4)))


# ---------- botao de tocar ----------
ANEIS = {"parado": ((155, 146, 131, 1), (222, 215, 203, 1), (111, 102, 90, 1)),     # o aro, a linha clara, o escuro de baixo
         "tocando": ((243, 167, 60, 1), (255, 222, 160, 1), (199, 122, 35, 1))}


FACE = (238, 231, 218, 1)
FACE_LUZ = (255, 252, 244, 1)
FACE_SOMBRA = (212, 202, 185, 1)


def botao(face, anel, linha, cores, contorno=2, filete=2):
    """O botao de tocar na lingua das teclas quadradas do lado (molduras do tema): o contorno escuro de
    `contorno` celulas, a linha clara de 1 celula por dentro dele (a moldura dupla), o aro de cor lisa
    (`anel` celulas contando a linha clara) com 1 celula escura embaixo a direita, a linha escura de
    `linha` celulas e a face creme com o filete de luz em cima a esquerda e a faixa de sombra embaixo
    a direita, de `filete` celulas (o miolo de botao do p1). Cor lisa por zona, nada de degrade: o aro
    de bisel em tres faixas (luz, meio, escuro) parecia um botao 3D, nao Habbo.
    Sem sombra dura: ela e a silhueta(), outra camada que o tema desce (solto) ou sobe (apertado)."""
    r = face + anel
    n = 2 * (r + contorno)
    c = n / 2
    cheio = disco_pixel(r, c, c, n)
    meio, luz, escuro = cores
    px = {}
    for x, y in cheio:
        d = math.hypot(x + .5 - c, y + .5 - c)
        lado = ((x + .5 - c) + (y + .5 - c)) / (d or 1)
        if d >= r - 1:                      # a linha clara da moldura dupla, em volta toda
            px[(x, y)] = luz
        elif d >= face:                     # o aro liso, e a celula de baixo dele escura embaixo a direita
            px[(x, y)] = escuro if d >= r - 2 and lado > .5 else meio
        elif d >= face - linha:             # a linha escura entre o aro e a face
            px[(x, y)] = CONTORNO
        elif d >= face - linha - filete and lado < -.4:
            px[(x, y)] = FACE_LUZ
        elif d >= face - linha - filete and lado > .4:
            px[(x, y)] = FACE_SOMBRA
        else:
            px[(x, y)] = FACE
    borda = set(cheio)
    for _ in range(contorno):
        borda |= {(x + dx, y + dy) for x, y in borda for dx, dy in VIZ}
    for cel in borda - cheio:
        px[cel] = CONTORNO
    return recorta(px)


def silhueta(face, anel, cor, contorno=1):
    """A silhueta do botao (com o contorno) numa cor so: a sombra dura, por baixo da face."""
    r = face + anel
    n = 2 * (r + contorno)
    tudo = disco_pixel(r, n / 2, n / 2, n)
    for _ in range(contorno):
        tudo |= {(x + dx, y + dy) for x, y in tudo for dx, dy in VIZ}
    return recorta({c: cor for c in tudo})


ICONES = {   # quadro (celulas), triangulo (x da base, x da ponta, meia altura), barras (largura, altura, vao)
    "grande": (16, (4.3, 15.3, 6.5), (5, 12, 2)),   # o tocar do tamanho do pausar
    "mini": (18, (5.2, 16.5, 6.5), (4, 14, 4)),   # o tocar do tamanho do pausar, como no grande
}


def icone(tipo, nome, cor):
    """Tocar (triangulo) e pausar (duas barras retas, gordas como no p1) no quadro de ICONES[nome],
    nas medidas do icone de sempre (o triangulo um pouco a direita, para o centro de massa ficar no
    meio do botao)."""
    n, (x0, x1, meia), (larg, alt, vao) = ICONES[nome]
    px = {}
    if tipo == "tocar":
        for y in range(n):
            for x in range(n):
                cx, cy = x + .5, y + .5
                if x0 <= cx <= x1 and abs(cy - n / 2) <= meia * (x1 - cx) / (x1 - x0):
                    px[(x, y)] = cor
    else:
        x0 = (n - 2 * larg - vao) // 2
        y0 = (n - alt) // 2
        for bx in (x0, x0 + larg + vao):
            for y in range(y0, y0 + alt):
                for x in range(bx, bx + larg):
                    px[(x, y)] = cor
    return px, n, n


def svg(px, larg, alt):
    """Como o do molduras.py, mas cada cor vira um path so (M x y h w v h h -w z por retangulo): o
    braco e os botoes tem muita corrida curta e um rect por corrida pesava o dobro."""
    corridas = {}
    for y in range(alt):
        x = 0
        while x < larg:
            c = px.get((x, y))
            if c is None:
                x += 1
                continue
            x0 = x
            while x < larg and px.get((x, y)) == c:
                x += 1
            corridas.setdefault((x0, x - x0, c), []).append(y)
    rets = {}
    for (x0, w, c), ys in corridas.items():
        ini = ant = ys[0]
        for y in ys[1:] + [None]:
            if y is not None and y == ant + 1:
                ant = y
                continue
            rets.setdefault(c, []).append(f"M{x0} {ini}h{w}v{ant - ini + 1}h-{w}z")
            if y is not None:
                ini = ant = y
    grupos = []
    for c, rs in rets.items():
        r, g, b, a = c
        op = "" if a >= 1 else f" fill-opacity='{a:g}'"
        grupos.append(f"<path fill='#{r:02X}{g:02X}{b:02X}'{op} d='{''.join(rs)}'/>")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{larg}' height='{alt}' viewBox='0 0 {larg} {alt}' "
            f"shape-rendering='crispEdges'>{''.join(grupos)}</svg>")


def retangulos(celulas, larg, alt):
    """As corridas de celulas de uma cor so, juntadas na vertical, como um d de path."""
    corridas = {}
    for y in range(alt):
        x = 0
        while x < larg:
            if (x, y) not in celulas:
                x += 1
                continue
            x0 = x
            while x < larg and (x, y) in celulas:
                x += 1
            corridas.setdefault((x0, x - x0), []).append(y)
    rs = []
    for (x0, w), ys in corridas.items():
        ini = ant = ys[0]
        for y in ys[1:] + [None]:
            if y is not None and y == ant + 1:
                ant = y
                continue
            rs.append(f"M{x0} {ini}h{w}v{ant - ini + 1}h-{w}z")
            if y is not None:
                ini = ant = y
    return "".join(rs)


def caminhos(px, larg, alt, aspas="'"):
    """Um path por cor (as celulas daquela cor), para o SVG que mora no JS (o do pisador)."""
    q = aspas
    por_cor = {}
    for c, cor in px.items():
        por_cor.setdefault(cor, set()).add(c)
    out = []
    for (r, g, b, a), cels in por_cor.items():
        op = "" if a >= 1 else f" fill-opacity={q}{a:g}{q}"
        out.append(f"<path fill={q}#{r:02X}{g:02X}{b:02X}{q}{op} d={q}{retangulos(cels, larg, alt)}{q}/>")
    return out


def uri(px, larg, alt):
    return 'url("data:image/svg+xml,' + quote(svg(px, larg, alt), safe=" '=/:,.-") + '")'


def main():
    linhas = []
    s = CELULA_BRACO
    for nome, ang in ANGULOS.items():
        pb, w, h, x0, y0 = braco(ang)
        linhas += [f"  --braco-{nome}-arte: {uri(pb, w, h)};",
                   f"  --braco-{nome}-esq: {x0 * s:.2f}cqw; --braco-{nome}-topo: {y0 * s:.2f}cqw; --braco-{nome}-larg: {w * s:.2f}cqw; --braco-{nome}-alt: {h * s:.2f}cqw;",
                   f"  --braco-{nome}-origem: {-x0 * s:.2f}cqw {-y0 * s:.2f}cqw; --braco-{nome}-desfaz: {-ang}deg;"]
    pb, w, h, x0, y0 = base_braco()
    linhas.append(f"  --base-braco: {uri(pb, w, h)};   /* {w} x {h} celulas, o prato em ({-x0}, {-y0}) */")
    pb, w, h, x0, y0 = descanso()
    linhas.append(f"  --descanso: {uri(pb, w, h)};   /* {w} x {h} celulas, o descanso em ({-x0}, {-y0}) */")
    # o grande: 40 celulas de 2 px = 80 px; o pequeno: 40 de 4/3 px = 53,3 px (o tema centra), com o
    # filete da face de 1 celula
    for nome, face, anel, linha, filete in (("grande", 14, 4, 1, 2), ("mini", 14, 4, 1, 1)):
        for estado in ("parado", "tocando"):
            pb, w, h, x0, y0 = botao(face, anel, linha, ANEIS[estado], contorno=2, filete=filete)
            linhas.append(f"  --tocar-{nome}-{estado}: {uri(pb, w, h)};   /* {w} x {h} celulas */")
        linhas.append(f"  --tocar-{nome}-sombra: {uri(*silhueta(face, anel, (20, 8, 2, .58), contorno=2)[:3])};")
        for tipo in ("tocar", "pausar"):
            linhas.append(f"  --icone-{nome}-{tipo}: {uri(*icone(tipo, nome, TINTA))};")
        linhas.append(f"  --icone-{nome}-tocar-apagado: {uri(*icone('tocar', nome, TINTA[:3] + (.35,)))};")
    knobs, margem = knob()
    linhas.append(f"  --knob-margem: {margem};   /* poe o centro do tampo do knob em {KN_CENTRO} na caixa do .p-grande */")
    svg_led, recuo = led()
    linhas.append(f"  --led-recuo: -{recuo}px;   /* o desenho do LED sai da caixa de {LED_N} px o tanto do brilho */")
    linhas.append(f"  --arcade-recuo: -{ARC_MARGEM}px;   /* o desenho dos botoes do Locutor sai do botao o tanto do brilho */")
    linhas.append(f"  --trilho-moldura: {trilho_moldura()};   /* 6 x 7 celulas: fatias 2 2 3 2 */")
    linhas.append(f"  --trilho-fundo: {faixas_css(CH_COR['trilho'])};")
    linhas.append(f"  --trilho-aceso: {faixas_css(CH_COR['aceso'])};")
    pb, w, h, _, _ = recorta(pino_px())
    linhas.append(f"  --cursor-pino: {uri(pb, w, h)};   /* {w} x {h} celulas, com a sombra dura */")
    salvar, acesas, n_aro = salvar_pixel()
    linhas.append("  " + " ".join(f"--salvar-aceso-{k}: #{r:02X}{g:02X}{bl:02X};" for k, (r, g, bl, _) in acesas.items())
                  + f"   /* o aro do salvar aceso ({n_aro} celulas) */")
    for nome, (direita, baixo) in (("a", (False, False)), ("b", (True, False)), ("c", (False, True)), ("d", (True, True))):
        pb, w, h, _, _ = maleta_canto(direita, baixo)
        linhas.append(f"  --maleta-canto-{nome}: {uri(pb, w, h)};   /* {w} x {h} celulas */")
    for nome, desenho in (("dobradica", maleta_dobradica), ("fecho", maleta_fecho), ("alca", maleta_alca)):
        pb, w, h, _, _ = desenho()
        linhas.append(f"  --maleta-{nome}: {uri(pb, w, h)};   /* {w} x {h} celulas */")
    for lado, direita in (("esq", False), ("dir", True)):
        for nome, desenho in (("meio", maleta_meio), ("boca", maleta_boca), ("boca-curta", lambda d: maleta_boca(d, aba=False))):
            pb, w, h, _, _ = desenho(direita)
            linhas.append(f"  --maleta-{nome}-{lado}: {uri(pb, w, h)};   /* {w} x {h} celulas */")
    for nome, tampa in (("tampa", TAMPA_ENTREABERTA), ("tampa-aberta", TAMPA_ABERTA)):
        pb, w, h = maleta_tampa(*tampa)
        for lado, p in (("esq", pb), ("dir", espelha(pb, w))):
            linhas.append(f"  --maleta-{nome}-{lado}: {uri(p, w, h)};   /* {w} x {h} px */")
    for nome, lado, topo in (("borda", 0, 0), ("papel", 2, 2), ("foto", 4, 5)):
        linhas.append(f"  --maleta-disco-{nome}: {disco_entreaberto(lado, topo)};")
    pb, w, h = maleta_base()
    for lado, p, direita in (("esq", pb, False), ("dir", espelha(pb, w), True)):
        linhas.append(f"  --maleta-base-{lado}: {uri_esticada(p, w, h, costura_base(direita))};   /* {w} px x {h} degraus, esticada na altura */")
    # fora do bloco do celular: as pecas valem nas duas telas
    bloco = ("/* pecas:inicio (gravado pelo dev/pecas.py: o desenho mora la, nao editar aqui) */\n"
             ".app {\n" + "\n".join(linhas) + "\n}\n/* pecas:fim */")
    txt = TEMA.read_text(encoding="utf-8")
    novo, n = re.subn(r"^/\* pecas:inicio.*?/\* pecas:fim \*/", lambda _: bloco, txt, flags=re.S | re.M)
    if n != 1:
        sys.exit("bloco pecas:inicio/fim nao encontrado no tema (ou repetido)")
    novo, n = re.subn(r"const PE_SVG = '[^\n]*';(\nconst LED_SVG = '[^\n]*';)?",
                      lambda _: f"const PE_SVG = '{pisador()}';\nconst LED_SVG = '{svg_led}';", novo)
    if n != 1:
        sys.exit("const PE_SVG nao encontrada no tema (ou repetida)")
    js = ",\n".join(f"  {nome}: ['{corpo}', [{', '.join(repr(p) for p in ponteiros)}]]" for nome, (corpo, ponteiros) in knobs.items())
    novo, n = re.subn(r"const KNOBS = \{\n(?:  [^\n]*\n)*\};", lambda _: f"const KNOBS = {{\n{js}\n}};", novo)
    if n != 1:
        sys.exit("const KNOBS nao encontrada no tema (ou repetida)")
    js = f"  natural: '{arcade_botao('NATURAL')}',\n  caricato: '{arcade_botao('CARICATO')}',\n  logo: '{arcade_logo()}'"
    novo, n = re.subn(r"const ARCADE = \{\n(?:  [^\n]*\n)*\};", lambda _: f"const ARCADE = {{\n{js}\n}};", novo)
    if n != 1:
        sys.exit("const ARCADE nao encontrada no tema (ou repetida)")
    novo, n = re.subn(r"const CHAVE_PARECIDAS = '[^\n]*';", lambda _: f"const CHAVE_PARECIDAS = '{chave_parecidas()}';", novo)
    if n != 1:
        sys.exit("const CHAVE_PARECIDAS nao encontrada no tema (ou repetida)")
    novo, n = re.subn(r"const SALVAR_PIXEL = '[^\n]*';", lambda _: f"const SALVAR_PIXEL = '{salvar}';", novo)
    if n != 1:
        sys.exit("const SALVAR_PIXEL nao encontrada no tema (ou repetida)")
    if novo != txt:
        TEMA.write_text(novo, encoding="utf-8", newline="\n")
    print(f"braco a {list(ANGULOS.values())} graus, {sum(len(x) for x in linhas)} caracteres" + ("" if novo != txt else " (sem mudanca)"))


if __name__ == "__main__":
    main()
