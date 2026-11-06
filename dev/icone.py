"""O icone da Vitrola em pixel art: o toca-discos do tema visto de cima (caixa de madeira, tampo claro,
disco com as marcas do prato e o braco), desenhado por codigo em cada tamanho.

    python dev/icone.py [--instalador <pasta>]

Grava em icone/ o vitrola.ico (o do exe, do setup e da aba do navegador: 16, 20, 24, 32, 40, 48, 64 e
256 px) e o toque.png (180 px, de fundo cheio: o icone da tela inicial do celular). Com --instalador,
grava tambem as imagens do assistente do Inno Setup nessa pasta (a instalador/ do vitrola-server).

Pixel art reduzida pelo Windows fica borrada: por isso cada tamanho do .ico e desenhado no proprio
tamanho, e o de 256 e o de 64 ampliado 4 vezes. O de 16 e a mao (MAPA_16): por formula, nele o braco e
as marcas do prato viravam ruido. Mudou o desenho: muda aqui, roda de novo e confere os tamanhos.
"""
import argparse
import io
import math
import struct
from pathlib import Path

from PIL import Image

SAIDA = Path(__file__).resolve().parent.parent / "icone"


def cor(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) + (255,)


# as cores do tema (themes/vitrola/index.html e o prato do preview.png)
CORES = {
    "k": cor("#1A0B04"),  # contorno
    "v": cor("#120D0C"),  # vinil
    "b": cor("#352C29"),  # brilho do vinil
    "u": cor("#241C19"),  # sulco
    "w": cor("#F1E9D8"),  # marca clara do prato
    "e": cor("#2A221E"),  # marca escura do prato
    "p": cor("#6A3653"),  # rotulo: ceu
    "s": cor("#F7D36B"),  # rotulo: sol
    "m": cor("#4E2630"),  # rotulo: mar
    "o": cor("#F4EEDF"),  # pino e pivo
    "d": cor("#904A24"),  # madeira
    "D": cor("#B0612F"),  # madeira de cima, com luz
    "x": cor("#6B3418"),  # madeira de baixo, na sombra
    "t": cor("#D9D2C6"),  # tampo
    "T": cor("#B9B0A2"),  # tampo na sombra da madeira
    "l": cor("#E2DBCF"),  # aluminio do braco
    "L": cor("#8E8576"),  # aluminio na sombra
    "c": cor("#3D3836"),  # capsula
    "g": cor("#2B2523"),  # contrapeso
}
JACARANDA = cor("#2A1812")

MAPA_16 = """
.kkkkkkkkkkkkkk.
kDDDDDDDDDDDDggk
kdtttttttttkkggk
kdttttttttkookdk
kdttkkkkktkoLkdk
kdtkwewewkklktdk
kdkevbvvvelkttdk
kdkwvpssvwlkttdk
kdkevposvlktttdk
kdkwvmmmvlktttdk
kdkevvvbLLktttdk
kdtkwewewkttttdk
kdttkkkkktttttdk
kdttttttttttttdk
kxxxxxxxxxxxxxxk
.kkkkkkkkkkkkkk.
"""


class Tela:
    def __init__(s, n):
        s.n = n
        s.im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        s.px = s.im.load()

    def put(s, x, y, c):
        if 0 <= x < s.n and 0 <= y < s.n and c:
            s.px[x, y] = c

    def cada(s, f):
        """Pinta cada pixel pelo centro dele: f(x, y) devolve a cor ou None."""
        for y in range(s.n):
            for x in range(s.n):
                s.put(x, y, f(x + .5, y + .5))

    def contorno(s):
        """1 px de contorno em volta da silhueta, por fora."""
        a = [[s.px[x, y][3] > 0 for x in range(s.n)] for y in range(s.n)]
        for y in range(s.n):
            for x in range(s.n):
                if not a[y][x] and any(0 <= x + dx < s.n and 0 <= y + dy < s.n and a[y + dy][x + dx]
                                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    s.px[x, y] = CORES["k"]


def circulo(t, cx, cy, r, c, sombra=None):
    def f(x, y):
        dx, dy = x - cx, y - cy
        if math.hypot(dx, dy) > r:
            return None
        return sombra if sombra and dx + dy > r * 0.55 else c

    t.cada(f)


def linha(t, a, b, c):
    """Bresenham: a linha de 1 px sem degrau dobrado."""
    x0, y0, x1, y1 = int(a[0]), int(a[1]), int(b[0]), int(b[1])
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    e = dx + dy
    while True:
        t.put(x0, y0, c)
        if (x0, y0) == (x1, y1):
            return
        e2 = 2 * e
        if e2 >= dy:
            e += dy
            x0 += sx
        if e2 <= dx:
            e += dx
            y0 += sy


def segmento(t, a, b, w, c):
    if w < 1.5:
        return linha(t, a, b, c)
    (ax, ay), (bx, by) = a, b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy

    def f(x, y):
        k = max(0, min(1, ((x - ax) * vx + (y - ay) * vy) / L2))
        return c if math.hypot(x - ax - k * vx, y - ay - k * vy) <= w / 2 else None

    t.cada(f)


def retangulo_girado(t, cx, cy, comp, larg, ang, c):
    ux, uy = math.cos(ang), math.sin(ang)

    def f(x, y):
        dx, dy = x - cx, y - cy
        return c if abs(dx * ux + dy * uy) <= comp / 2 and abs(-dx * uy + dy * ux) <= larg / 2 else None

    t.cada(f)


def rotulo(u, v):
    """O rotulo do disco padrao do tema: ceu, o sol a direita e o mar embaixo."""
    if v > 0.36:
        return CORES["m"]
    if (u - 0.42) ** 2 + (v + 0.1) ** 2 <= 0.56 ** 2:
        return CORES["s"]
    return CORES["p"]


def marcas(t, cx, cy, R, largura):
    """As marcas do prato, claras e escuras alternadas. Contadas pelos pixels da volta de fora, e nao pelo
    angulo: assim ficam do mesmo tamanho nas diagonais."""
    n = t.n
    passo = max(1, round(n / 16))
    pix = [(x, y) for y in range(n) for x in range(n) if R - largura < math.hypot(x + .5 - cx, y + .5 - cy) <= R]
    ang = {p: math.atan2(p[1] + .5 - cy, p[0] + .5 - cx) for p in pix}
    fora = sorted((p for p in pix if math.hypot(p[0] + .5 - cx, p[1] + .5 - cy) > R - 1), key=ang.get)
    total = max(2, round(len(fora) / passo))
    total -= total % 2
    angs = [ang[p] for p in fora]
    for p in pix:
        i = min(range(len(fora)), key=lambda k: abs((angs[k] - ang[p] + math.pi) % (2 * math.pi) - math.pi))
        t.put(*p, CORES["w"] if (i * total // len(fora)) % 2 else CORES["e"])


def disco(t, cx, cy, R):
    n = t.n
    largura = max(1, round(R * 0.13))
    rr = R * 0.36

    def f(x, y):
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy)
        if d > R or d > R - largura:
            return None
        if d <= rr:
            return rotulo(dx / rr, dy / rr)
        for alvo in (-1.75, 1.39):  # as duas cunhas de brilho do prato do tema: em cima, um pouco a esquerda, e embaixo
            ux, uy = math.cos(alvo), math.sin(alvo)
            if n < 32:
                if dx * ux + dy * uy > 0 and abs(-dx * uy + dy * ux) <= 0.55:
                    return CORES["b"]
            elif abs((math.atan2(dy, dx) - alvo + math.pi) % (2 * math.pi) - math.pi) < 0.17:
                return CORES["b"]
        if n >= 48 and abs(d - (rr + (R - largura - rr) * 0.62)) < 0.5:
            return CORES["u"]
        return CORES["v"]

    t.cada(f)
    marcas(t, cx, cy, R, largura)
    circulo(t, cx, cy, max(0.8, R * 0.06), CORES["o"])


def braco(t, piv, ponta):
    """Contrapeso, pivo, haste e capsula, cada um com contorno."""
    n = t.n
    w = n * 0.05 if n >= 32 else 1.4
    rp = n * 0.085
    ang = math.atan2(ponta[1] - piv[1], ponta[0] - piv[0])
    # o contrapeso fica atras do pivo, do lado oposto ao da haste
    peso = (piv[0] - math.cos(ang) * rp * 1.25, piv[1] - math.sin(ang) * rp * 1.25)
    cab = (ponta[0] + math.cos(ang) * n * 0.03, ponta[1] + math.sin(ang) * n * 0.03)
    clen, clar = n * 0.16, max(1.6, n * 0.085)
    k = CORES["k"]
    retangulo_girado(t, *peso, rp * 1.5 + 2, rp * 1.25 + 2, ang, k)
    segmento(t, piv, ponta, w + 2, k)
    circulo(t, *piv, rp + 1, k)
    retangulo_girado(t, *cab, clen + 2, clar + 2, ang + 0.35, k)
    retangulo_girado(t, *peso, rp * 1.5, rp * 1.25, ang, CORES["g"])
    segmento(t, piv, ponta, w, CORES["l"])
    circulo(t, *piv, rp, CORES["o"], CORES["L"] if n >= 32 else None)
    retangulo_girado(t, *cab, clen, clar, ang + 0.35, CORES["c"])


def toca_discos(n):
    if n == 16:
        linhas = MAPA_16.strip().splitlines()
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        for y, ln in enumerate(linhas):
            for x, ch in enumerate(ln):
                if ch != ".":
                    im.putpixel((x, y), CORES[ch])
        return im
    t = Tela(n)
    f = max(1, round(n * 0.05))  # a madeira em volta do tampo

    def caixa(x, y):
        if not (1 <= x < n - 1 and 1 <= y < n - 1):
            return None
        if x < 1 + f or x >= n - 1 - f or y < 1 + f or y >= n - 1 - f:
            return CORES["D"] if y < 2 else CORES["x"] if y >= n - 2 else CORES["d"]
        if n >= 32 and (x < 2 + f or y < 2 + f):
            return CORES["T"]
        return CORES["t"]

    t.cada(caixa)
    R = n * 0.345
    cx, cy = max(n * 0.43, 1 + f + R + 1.5), n * 0.53
    circulo(t, cx, cy, R + 1, CORES["k"])  # no tampo claro, o prato precisa do aro escuro por fora, como no tema
    disco(t, cx, cy, R)
    if n >= 40:  # o botao do canto, o do tema
        circulo(t, n * 0.86, n * 0.83, n * 0.05, CORES["k"])
        circulo(t, n * 0.86, n * 0.83, n * 0.025, CORES["o"])
    braco(t, (n * 0.82, n * 0.22), (cx + R * 0.45, cy + R * 0.55))
    t.contorno()
    return t.im


def tamanho(n):
    return toca_discos(n) if n <= 64 else toca_discos(64).resize((n, n), Image.NEAREST)


def grava_ico(destino, tamanhos):
    """.ico com bitmap de 32 bits ate 64 px e PNG no de 256 (o que o Windows espera em cada um)."""
    dados = []
    for n in tamanhos:
        im = tamanho(n)
        if n >= 256:
            b = io.BytesIO()
            im.save(b, "PNG", optimize=True)
            dados.append(b.getvalue())
            continue
        bgra = im.tobytes("raw", "BGRA")
        linhas = [bgra[y * n * 4:(y + 1) * n * 4] for y in range(n)][::-1]  # o bitmap vai de baixo para cima
        mascara_linha = ((n + 31) // 32) * 4
        cabecalho = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, 0, 0, 0, 0, 0)
        dados.append(cabecalho + b"".join(linhas) + b"\0" * mascara_linha * n)
    saida = struct.pack("<HHH", 0, 1, len(tamanhos))
    pos = 6 + 16 * len(tamanhos)
    for n, d in zip(tamanhos, dados):
        saida += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(d), pos)
        pos += len(d)
    destino.write_bytes(saida + b"".join(dados))


def com_fundo(arte, w, h, escala, fundo=JACARANDA):
    """A arte ampliada sem borrar, no centro de um retangulo w x h."""
    a = arte.resize((arte.width * escala, arte.height * escala), Image.NEAREST)
    im = Image.new("RGBA", (w, h), fundo)
    im.alpha_composite(a, ((w - a.width) // 2, (h - a.height) // 2))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instalador", type=Path, help="grava as imagens do assistente do Inno Setup nesta pasta")
    args = ap.parse_args()
    SAIDA.mkdir(exist_ok=True)
    grava_ico(SAIDA / "vitrola.ico", [16, 20, 24, 32, 40, 48, 64, 256])
    # o iOS corta os cantos e poe preto no transparente: fundo cheio, com folga em volta
    com_fundo(toca_discos(48), 180, 180, 3).convert("RGB").save(SAIDA / "toque.png", optimize=True)
    if args.instalador:
        # a imagem pequena (no alto de cada pagina, sem fundo) e a grande (a da pagina do fim), a 100% e a
        # 200%; os tamanhos sao os da documentacao do WizardSmallImageFile e do WizardImageFile
        for w, h, e in ((55, 55, 1), (110, 106, 2)):
            com_fundo(toca_discos(48), w, h, e, (0, 0, 0, 0)).save(args.instalador / f"assistente-pequena-{w}.png",
                                                                  optimize=True)
        for w, h, e in ((164, 314, 2), (328, 628, 4)):
            com_fundo(toca_discos(64), w, h, e).convert("RGB").save(args.instalador / f"assistente-grande-{w}.png",
                                                                    optimize=True)
    for p in sorted(SAIDA.iterdir()):
        print(f"{p.name}: {p.stat().st_size // 1024 or 1} KB")


if __name__ == "__main__":
    main()
