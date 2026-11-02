"""Molduras de pixel da vitrola (o toque de Habbo): contorno escuro, linha clara por dentro,
bisel e cantos em degrau, desenhados pixel a pixel e usados como border-image de 9 partes.

    python dev/molduras.py

Grava as variaveis --mold-* no bloco entre "molduras:inicio" e "molduras:fim" do themes/vitrola/index.html e
do gallery.html (a pagina inicial, que fica fora do tema e leva so as que usa).
Cada moldura e um SVG pequeno (1 unidade = 1 ponto, shape-rendering crispEdges) com a quina
inteira desenhada e o meio de cada lado esticado; a variavel ja leva o corte, a largura e o quanto a
moldura sai para fora da caixa, entao no tema basta border-image: var(--mold-objeto).

O tamanho do ponto e a variavel --px do tema (sem ela, 1px, o do celular): a tela maior pede o ponto
maior, para a moldura acompanhar as pecas desenhadas em proporcao (o braco, os knobs). As --mold-*
resolvem o --px onde sao declaradas (no .app e no que mora fora dele: menu, dialogos, aviso e fora do
ar), entao ele mora no :root ou nesses.

Por que imagem e nao box-shadow: a sombra segue o retangulo (ou o arco do border-radius), nunca o
degrau, e o recorte (clip-path) comia o proprio contorno. A sombra dura de baixo vai assada no desenho
pelo mesmo motivo: o canto dela tambem desce em degrau.

O desenho: S0 e a silhueta (o retangulo com os cantos em degrau de 3 px). Cada faixa e a diferenca
entre duas erosoes de S0 (o contorno de 0 a 3 px da borda, a linha clara de 3 a 5, o bisel de 5 a 7),
e cada pixel da faixa pega a cor do lado mais perto (em cima e a esquerda a luz, embaixo e a direita a
sombra). A quina precisa de profundidade = degrau + faixas, por isso o corte de cada lado e 13 px.
Elemento com a moldura por dentro (sai = 0) precisa de border-radius de 15 px ou mais: o fundo dele
fica dentro do degrau e o contorno cobre a sobra entre o arco e o degrau (na chapa fina, de contorno
de 2 px e degrau de 2 px, bastam 10 px).

Peca miuda ou embutida pede a moldura mais fina: contorno_px, degrau e passo (a altura de cada
fileira do degrau) mudam por moldura. A caixa que tem filhos cobrindo a beirada (o receiver, com as
laterais de madeira por cima do proprio fundo) usa duas camadas: a face (contorno, linha clara e
bisel, sem sombra) num pseudo por cima dos filhos e so a sombra (so = "sombra") num pseudo por baixo
deles, para os pes continuarem por cima da sombra.
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
TEMA = RAIZ / "themes" / "vitrola" / "index.html"
GALERIA = RAIZ / "gallery.html"
NA_GALERIA = ("objeto", "objeto-apertado", "caixa")
CONTORNO = (26, 11, 4, 1)          # #1A0B04, o --contorno do tema
LUZ = (255, 236, 214)              # marfim quente: sobre aluminio clareia, sobre madeira vira o filete aceso
DEGRAU = (6, 3)                    # de onde cada fileira de 3 px comeca, a partir da quina de fora
MEIO = 2                           # o pedaco esticado no meio de cada lado

# nome: o desenho. sai = quanto o contorno fica fora da caixa (3 = por fora, como o box-shadow de
# antes; 0 = por dentro), sombra = quantos px a sombra dura desce, cantos = quais quinas tem degrau,
# faixas = (de, ate, {lado: cor}) contados da borda de fora para dentro; contorno troca a cor do contorno;
# frente = (altura, cor, filete): a frente da caixa, faixa reta de baixo por dentro do contorno;
# arquivo = um desenho feito a mao (no dev/), com o corte e o quanto sai: o script so o grava no tema
MOLDURAS = {
    "objeto": dict(sai=3, sombra=4, cor_sombra=(20, 8, 2, .62), cantos="ab", faixas=[
        (3, 5, {"t": LUZ + (.62,), "l": LUZ + (.62,), "b": LUZ + (.3,), "r": LUZ + (.3,)}),
        (5, 7, {"b": (0, 0, 0, .24), "r": (0, 0, 0, .2)})]),
    "objeto-apertado": dict(sai=3, sombra=1, cor_sombra=(20, 8, 2, .62), cantos="ab", faixas=[
        (3, 5, {"t": LUZ + (.5,), "l": LUZ + (.5,), "b": LUZ + (.3,), "r": LUZ + (.3,)}),
        (5, 7, {"b": (0, 0, 0, .2), "r": (0, 0, 0, .16)})]),
    "caixa": dict(sai=3, sombra=5, cor_sombra=(20, 8, 2, .5), cantos="ab", faixas=[
        (3, 5, {"t": LUZ + (.55,), "l": LUZ + (.55,), "b": LUZ + (.28,), "r": LUZ + (.28,)}),
        (5, 7, {"b": (0, 0, 0, .24), "r": (0, 0, 0, .2)})]),
    # a barra do player: por dentro (o palco corta o que sai) e degrau so nas quinas de cima
    "barra": dict(sai=0, sombra=0, cor_sombra=None, cantos="a", faixas=[
        (3, 5, {"t": (255, 255, 255, .75), "l": (255, 255, 255, .6), "b": (255, 255, 255, .4), "r": (255, 255, 255, .4)}),
        (5, 7, {"b": (42, 24, 18, .2), "r": (42, 24, 18, .16)})]),
    # rebaixo escuro (a busca e o visor): o contorno e a sombra de dentro em cima e a esquerda
    "rebaixo": dict(sai=0, sombra=0, cor_sombra=None, cantos="ab", faixas=[
        (3, 6, {"t": (0, 0, 0, .55), "l": (0, 0, 0, .4)})]),
    # a busca com o foco: o contorno vira ambar em degrau (o anel do outline seria redondo)
    "rebaixo-foco": dict(sai=0, sombra=0, cor_sombra=None, cantos="ab", contorno=(243, 167, 60, 1), faixas=[
        (3, 6, {"t": (0, 0, 0, .55), "l": (0, 0, 0, .4)})]),
    # aparelhos do palco (quarta rodada). O receiver em duas camadas: a face por cima das laterais de
    # madeira e a sombra da caixa por baixo dos pes
    "caixa-face": dict(sai=3, sombra=0, cor_sombra=None, cantos="ab", faixas=[
        (3, 5, {"t": LUZ + (.55,), "l": LUZ + (.55,), "b": LUZ + (.28,), "r": LUZ + (.28,)}),
        (5, 7, {"b": (0, 0, 0, .24), "r": (0, 0, 0, .2)})]),
    "caixa-sombra": dict(sai=3, sombra=5, cor_sombra=(20, 8, 2, .5), cantos="ab", so="sombra", faixas=[
        (3, 5, {}), (5, 7, {})]),
    # embutido: o corpo do FX-12 rente ao feltro, sem sombra (18/10)
    "embutido": dict(sai=3, sombra=0, cor_sombra=None, cantos="ab", faixas=[
        (3, 5, {"t": LUZ + (.62,), "l": LUZ + (.62,), "b": LUZ + (.3,), "r": LUZ + (.3,)}),
        (5, 7, {"b": (0, 0, 0, .2), "r": (0, 0, 0, .16)})]),
    # a janela dos VUs: o contorno por fora, a linha clara colada nele, a sombra dura do rebaixo em
    # cima e o beiço claro da chapa embaixo (no lugar da sombra)
    "vu": dict(sai=3, sombra=2, cor_sombra=(255, 255, 255, .55), cantos="ab", faixas=[
        (3, 5, {"t": LUZ + (.6,), "l": LUZ + (.6,), "b": LUZ + (.35,), "r": LUZ + (.35,)}),
        (5, 8, {"t": (80, 40, 0, .2)})]),
    # chapa fina por dentro (sai 0, raio de 10 px no elemento): a chapa creme do toca-discos e o
    # painel do visor do FX-12, dentro de um aparelho que ja tem o contorno grosso
    "chapa": dict(sai=0, sombra=0, cor_sombra=None, cantos="ab", contorno_px=2, degrau=(4, 2), passo=2, faixas=[
        (2, 4, {"t": (255, 255, 255, .7), "l": (255, 255, 255, .7), "b": (255, 255, 255, .3), "r": (255, 255, 255, .3)}),
        (4, 5, {"b": (42, 24, 18, .16), "r": (42, 24, 18, .12)})]),
    # etiquetas miudas (o selo 33/45 do toca-discos e o VITROLA do FX-12): contorno de 2 px por fora e
    # a quina comida em 2 px
    "etiqueta": dict(sai=2, sombra=0, cor_sombra=None, cantos="ab", contorno_px=2, degrau=(2,), passo=2, faixas=[
        (2, 3, {"t": (255, 255, 255, .75), "l": (255, 255, 255, .75)}),
        (3, 4, {"b": (42, 24, 18, .14), "r": (42, 24, 18, .1)})]),
    "etiqueta-escura": dict(sai=2, sombra=0, cor_sombra=None, cantos="ab", contorno_px=2, degrau=(2,), passo=2, faixas=[
        (2, 3, {"t": LUZ + (.3,), "l": LUZ + (.3,)})]),
    # a fita crepe com o nome do grupo de pedais (a faixa lisa girada era a ultima peca
    # lisa da pedaleira): reta, contorno de 2 px por fora, o filete claro em cima e o escuro embaixo da
    # fita lisa de antes, a sombra dura no feltro, e as pontas recortadas em degraus desencontrados, o
    # rasgo da fita (o recorte do clip-path de antes)
    "fita": dict(sai=2, sombra=2, cor_sombra=(12, 6, 3, .45), cantos="ab", contorno_px=2, degrau=(3, 1, 2), passo=2, faixas=[
        (2, 4, {"t": (255, 250, 238, .45), "l": (255, 250, 238, .3), "b": (42, 24, 18, .14), "r": (42, 24, 18, .1)})]),
    # pedais da pedaleira: a caixa com a profundidade dos pedais de antes do pixel, desenhada a parte
    # (a frente de 8 px chapada ficou estranha) em dev/pedal.svg:
    # o degrau dos cantos de baixo repete o de cima e a parede desce de cada degrau, a borda da face em
    # tres linhas (sulco, beico aceso, dobra escura), a parede do meio vazia (a cor dela e do tema, num
    # box-shadow inset com o --cor, que a imagem nao sabe), a borracha de 2 px e a sombra dura de 5.
    # Tirados do desenho original os quadradinhos claros das quinas e a segunda linha clara da esquerda, e a
    # borracha marrom fixa do pe virou o escuro do proprio pedal (a linha marrom em
    # todos): no meio ela e o box-shadow de 3 px do tema, nos degraus um preto translucido por cima
    "pedal": dict(arquivo="pedal.svg", corte=(18, 18, 27, 18), sai=(3, 3, 8, 3)),
}


def desenha(m):
    grossura, degrau, passo = m.get("contorno_px", 3), m.get("degrau", DEGRAU), m.get("passo", 3)
    k = max([ate for _, ate, _ in m["faixas"]] + ([m.get("contorno_px", 3) + m["frente"][0] + 1] if m.get("frente") else []))
    prof = max(degrau[0] + k, k + passo * len(degrau))      # a quina inteira cabe no corte
    larg, alt_s0 = 2 * prof + MEIO, 2 * prof + MEIO
    alt = alt_s0 + m["sombra"]

    def s0(x, y):
        if not (0 <= x < larg and 0 <= y < alt_s0):
            return False
        for quina in m["cantos"]:   # a = as de cima, b = as de baixo
            yy = y if quina == "a" else alt_s0 - 1 - y
            fila = yy // passo
            if fila < len(degrau):
                if x < degrau[fila] or x >= larg - degrau[fila]:
                    return False
        return True

    def dentro(x, y, n):   # erosao de n px (vizinhanca quadrada)
        return all(s0(x + dx, y + dy) for dx in range(-n, n + 1) for dy in range(-n, n + 1)) if n else s0(x, y)

    def lado(x, y):
        d = {"t": y, "l": x, "b": alt_s0 - 1 - y, "r": larg - 1 - x}
        return min("tlbr", key=lambda s: d[s])

    px = {}
    if m["sombra"]:
        for y in range(alt):
            for x in range(larg):
                if s0(x, y - m["sombra"]) and not s0(x, y):
                    px[(x, y)] = m["cor_sombra"]
    if m.get("so") == "sombra":
        return px, larg, alt, prof
    for y in range(alt_s0):
        for x in range(larg):
            if s0(x, y) and not dentro(x, y, grossura):
                px[(x, y)] = m.get("contorno", CONTORNO)
            else:
                for de, ate, cores in m["faixas"]:
                    if dentro(x, y, de) and not dentro(x, y, ate):
                        cor = cores.get(lado(x, y))
                        if cor:
                            px[(x, y)] = cor
                if m.get("frente") and dentro(x, y, grossura):
                    # a frente da caixa: faixas retas contadas do pe para cima, por cima das outras
                    alto_f, cor_f, filete = m["frente"]
                    yb = alt_s0 - 1 - y - grossura
                    if yb < alto_f:
                        px[(x, y)] = cor_f
                    elif yb == alto_f:
                        px[(x, y)] = filete
    return px, larg, alt, prof


def svg(px, larg, alt):
    # corridas na horizontal, depois juntando as fileiras iguais na vertical, agrupadas por cor
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
            rets.setdefault(c, []).append(f"<rect x='{x0}' y='{ini}' width='{w}' height='{ant - ini + 1}'/>")
            if y is not None:
                ini = ant = y
    grupos = []
    for c, rs in rets.items():
        r, g, b, a = c
        op = "" if a >= 1 else f" fill-opacity='{a:g}'"
        grupos.append(f"<g fill='#{r:02X}{g:02X}{b:02X}'{op}>{''.join(rs)}</g>")
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{larg}' height='{alt}' viewBox='0 0 {larg} {alt}' "
            f"shape-rendering='crispEdges'>{''.join(grupos)}</svg>")


def pontos(*ns):
    """n pontos da moldura em CSS, na escala do --px."""
    return " ".join(f"calc({n} * var(--px, 1px))" if n else "0" for n in ns)


def grava(arquivo, seletor, linhas):
    bloco = ("/* molduras:inicio (gravado pelo dev/molduras.py: o desenho mora la, nao editar aqui) */\n"
             f"{seletor} {{\n" + "\n".join(linhas) + "\n}\n/* molduras:fim */")
    txt = arquivo.read_text(encoding="utf-8")
    novo, n = re.subn(r"^/\* molduras:inicio.*?/\* molduras:fim \*/", lambda _: bloco, txt, flags=re.S | re.M)
    if n != 1:
        sys.exit(f"bloco molduras:inicio/fim nao encontrado em {arquivo.name} (ou repetido)")
    if novo != txt:
        arquivo.write_text(novo, encoding="utf-8", newline="\n")
    return novo != txt


def main():
    linhas = {}
    for nome, m in MOLDURAS.items():
        if "arquivo" in m:
            desenho = " ".join((Path(__file__).parent / m["arquivo"]).read_text(encoding="utf-8").split())
            uri = "data:image/svg+xml," + quote(desenho.replace("> <", "><"), safe=" '=/:,.-")
            corte, sai = m["corte"], m["sai"]
            linhas[nome] = (f'  --mold-{nome}: url("{uri}") {" ".join(map(str, corte))} / {pontos(*corte)} / '
                            f"{pontos(*sai)} stretch;")
            continue
        px, larg, alt, prof = desenha(m)
        uri = "data:image/svg+xml," + quote(svg(px, larg, alt), safe=" '=/:,.-")
        baixo = prof + m["sombra"]
        sai, sai_b = m["sai"], m["sai"] + m["sombra"]
        linhas[nome] = (f'  --mold-{nome}: url("{uri}") {prof} {prof} {baixo} {prof} / {pontos(prof, prof, baixo, prof)} / '
                        f"{pontos(sai, sai, sai_b, sai)} stretch;")
    # fora do bloco do celular: as molduras valem nas duas telas
    mudou = grava(TEMA, ".app, .menu, dialog, .aviso, .fora", list(linhas.values()))   # esses moram fora do .app
    mudou |= grava(GALERIA, ":root", [linhas[n] for n in NA_GALERIA])
    print(f"{len(MOLDURAS)} molduras, {sum(map(len, linhas.values()))} caracteres" + ("" if mudou else " (sem mudanca)"))


if __name__ == "__main__":
    main()
