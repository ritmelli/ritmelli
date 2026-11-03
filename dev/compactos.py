"""Compactos dos Sons rapidos da vitrola em pixel art (o toque de Habbo, mock h1): a
silhueta em degrau com o contorno, os sulcos, a borda com bisel, o brilho pixelado na diagonal e a
sombra dura, desenhados celula a celula.

    python dev/compactos.py

Grava as variaveis --compacto-base e --compacto-tampa no bloco entre "compactos:inicio" e
"compactos:fim" do themes/vitrola/index.html.

O compacto gira enquanto o som toca, e um degrau girando balanca. Por isso o desenho fica parado em
duas camadas e so o selo redondo gira entre elas (o .sete-gira com o .sete-rot, na cor do som):
- a base (::before do .sete, por baixo do selo): sombra, contorno, sulcos, borda e brilho. Sulco e
  brilho nao mudam com o giro (o sulco e um anel; o reflexo da luz nao gira com o disco);
- a tampa (::after do .sete, por cima do selo): um anel em degrau da cor do vinil que esconde a beira
  redonda do selo (o selo parece recortado em degrau), o bisel do selo, o anel claro de dentro e o
  miolo ambar com o furo. Quem mostra o giro e a risca do selo (.sete-rot::after), entre a tampa.

A beira do selo: o anel da tampa vai das celulas com centro a SELO_DE ate SELO_ATE do centro, e o
selo redondo tem raio SELO_R (em celulas). SELO_R tem que cobrir toda celula de dentro do anel e
caber inteiro nas celulas de dentro mais as do anel; o main() confere e para se nao fechar. O tema
usa o mesmo raio no inset do .sete-rot (inset = 50% - SELO_R / CELULAS * 100%).

Escala: 1 celula = 1/40 do compacto (2 px de CSS no compacto de 80 px, 6 px de tela no celular de
densidade 3). A base sai 1 celula para fora dos lados e de cima (o contorno) e 3 para baixo (contorno
e sombra); o tema posiciona o ::before com esses mesmos numeros em porcentagem.
"""
import math
import re
import sys
from urllib.parse import quote

from molduras import CONTORNO, TEMA, svg

CELULAS = 40                         # o compacto tem 40 x 40 celulas
SOMBRA = 2                           # a sombra dura desce 2 celulas (4 px, como a --duro)
SELO_DE, SELO_ATE, SELO_R = 9.1, 11.1, 10.06   # o anel de 2 celulas deixa folga de meia celula dos dois lados (o selo girando borra a beira)
SULCO = [(38, 30, 27, 1), (18, 13, 11, 1)]          # os aneis do vinil, alternando por celula
BORDA = {"luz": (64, 54, 49, 1), "meio": (30, 24, 21, 1), "sombra": (10, 7, 6, 1)}
BRILHO = [(84, 75, 69, 1), (46, 39, 35, 1)]          # o reflexo: forte no anel claro, fraco no escuro
AMBAR = {"luz": (255, 212, 138, 1), "meio": (243, 167, 60, 1), "sombra": (199, 122, 35, 1)}
FURO = {"meio": (34, 28, 25, 1), "luz": (78, 68, 62, 1)}
C = CELULAS / 2


def raio(x, y):
    return math.hypot(x + .5 - C, y + .5 - C)


def lado(x, y):
    """-1 no alto a esquerda (luz), 1 embaixo a direita (sombra), 0 nos lados."""
    d = raio(x, y) or 1
    s = ((x + .5 - C) + (y + .5 - C)) / d
    return -1 if s < -.55 else 1 if s > .55 else 0


def disco(x, y):
    return raio(x, y) < C - .1


def vinil(x, y):
    """A cor do vinil na celula: sulco, borda com bisel e o brilho nas duas diagonais."""
    r = raio(x, y)
    if r >= C - 1.1:   # a borda de fora do disco
        return BORDA[{-1: "luz", 0: "meio", 1: "sombra"}[lado(x, y)]]
    anel = int(r) % 2
    ang = math.degrees(math.atan2(y + .5 - C, x + .5 - C))
    perto = min(abs((ang - c + 180) % 360 - 180) for c in (-48, 132))
    if SELO_ATE + .4 < r < C - 2:
        if perto < 11:
            return BRILHO[anel]
        if perto < 20 and anel == 0 and (x + y) % 2 == 0:   # a beira do reflexo em xadrez
            return BRILHO[0]
    return SULCO[anel]


def base():
    px = {}
    dentro = {(x, y) for y in range(CELULAS) for x in range(CELULAS) if disco(x, y)}
    contorno = {(x + dx, y + dy) for x, y in dentro for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} - dentro
    corpo = dentro | contorno
    for x, y in {(x, y + k) for x, y in corpo for k in range(1, SOMBRA + 1)} - corpo:
        px[(x + 1, y + 1)] = (20, 8, 2, .62)
    for x, y in contorno:
        px[(x + 1, y + 1)] = CONTORNO
    for x, y in dentro:
        px[(x + 1, y + 1)] = vinil(x, y)
    return px, CELULAS + 2, CELULAS + 2 + SOMBRA


def tampa():
    px = {}
    for y in range(CELULAS):
        for x in range(CELULAS):
            r = raio(x, y)
            if SELO_DE <= r < SELO_ATE:
                px[(x, y)] = vinil(x, y)
            elif r < SELO_DE:
                beira = any(SELO_DE <= raio(x + dx, y + dy) < SELO_ATE for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                if beira and lado(x, y) == -1:
                    px[(x, y)] = (255, 250, 235, .32)
                elif beira and lado(x, y) == 1:
                    px[(x, y)] = (40, 18, 0, .2)
                elif 6.6 <= r < 7.5:
                    px[(x, y)] = (255, 250, 235, .14)
                elif 5 <= r < 5.8:
                    px[(x, y)] = (60, 24, 0, .34)
                elif 3 <= r < 5:
                    px[(x, y)] = AMBAR[{-1: "luz", 0: "meio", 1: "sombra"}[lado(x, y)]] if 4.1 <= r else AMBAR["meio"]
                elif r < 3:   # o furo com um risco de luz na diagonal, como o vinil
                    px[(x, y)] = FURO["luz"] if x - C == -(y + 1 - C) and r > 1 and x > C else FURO["meio"]
    return px, CELULAS, CELULAS


def confere_selo():
    """O selo redondo de raio SELO_R fica escondido sob o anel e enche as celulas de dentro."""
    longe = max(max(math.hypot(x + i - C, y + j - C) for i in (0, 1) for j in (0, 1))
                for y in range(CELULAS) for x in range(CELULAS) if raio(x, y) < SELO_DE)
    perto = min(math.hypot(min(max(C, x), x + 1) - C, min(max(C, y), y + 1) - C)
                for y in range(CELULAS) for x in range(CELULAS) if raio(x, y) >= SELO_ATE)
    if not longe + .1 <= SELO_R <= perto - .1:
        sys.exit(f"o selo de raio {SELO_R} nao fecha com o anel: precisa ficar entre {longe:.3f} e {perto:.3f} (com folga de .1)")


def main():
    confere_selo()
    linhas = []
    for nome, (px, larg, alt) in (("base", base()), ("tampa", tampa())):
        uri = "data:image/svg+xml," + quote(svg(px, larg, alt), safe=" '=/:,.-")
        linhas.append(f'  --compacto-{nome}: url("{uri}");')
    bloco = ("/* compactos:inicio (gravado pelo dev/compactos.py: o desenho mora la, nao editar aqui) */\n"
             ".app {\n" + "\n".join(linhas) + "\n}\n/* compactos:fim */")
    txt = TEMA.read_text(encoding="utf-8")
    novo, n = re.subn(r"^/\* compactos:inicio.*?/\* compactos:fim \*/", lambda _: bloco, txt, flags=re.S | re.M)
    if n != 1:
        sys.exit("bloco compactos:inicio/fim nao encontrado no tema (ou repetido)")
    if novo != txt:
        TEMA.write_text(novo, encoding="utf-8", newline="\n")
    print(f"selo de raio {SELO_R} celulas (inset {50 - SELO_R / CELULAS * 100:.2f}%), {sum(len(x) for x in linhas)} caracteres"
          + ("" if novo != txt else " (sem mudanca)"))


if __name__ == "__main__":
    main()
