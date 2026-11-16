"""Confere os textos da interface (i18n/ de cada tema, o plano no I18N.md do ritmelli-server) e o i18n.py.

    python dev/testa_i18n.py

Nos arquivos de cada tema: as mesmas chaves nas duas linguas e na mesma ordem, nenhum valor vazio, os mesmos {param}
nos dois lados, toda chave que o tema usa existindo e nenhuma chave sobrando. Uma chave conta como usada quando aparece
no tema entre aspas ou num data-i18n*; as que o I18N.tp usa (chave.one, chave.other) contam pela chave de base. No
i18n.py: o leitor do .properties, a escolha da lingua e o texto posto na pagina. Sai 1 se algo falha."""
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import i18n  # noqa: E402

CHAVE = r"[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+"
falhas = []


def falha(msg):
    falhas.append(msg)
    print(f"FAIL {msg}")


def params(s):
    return set(re.findall(r"\{(\w+)\}", s))


def confere_tema(tema):
    pasta = tema / "i18n"
    try:
        por_lingua = {x: i18n.ler(i18n.arquivo(pasta, x)) for x in i18n.LINGUAS}
    except (OSError, ValueError) as ex:
        falha(f"{tema.name}: {ex}")
        return
    base = por_lingua[i18n.RESERVA]
    for lingua, textos in por_lingua.items():
        for k in base.keys() - textos.keys():
            falha(f"{tema.name}: {k} is missing in {lingua}")
        for k in textos.keys() - base.keys():
            falha(f"{tema.name}: {k} is in {lingua} but not in {i18n.RESERVA}")
        comuns = [k for k in textos if k in base]
        if comuns != [k for k in base if k in textos]:
            falha(f"{tema.name}: the keys of {lingua} are not in the same order as {i18n.RESERVA}")
        for k, v in textos.items():
            if not v:
                falha(f"{tema.name}: {k} is empty in {lingua}")
            if k in base and params(v) != params(base[k]):
                falha(f"{tema.name}: {k} has params {sorted(params(v))} in {lingua}, "
                      f"{sorted(params(base[k]))} in {i18n.RESERVA}")

    html = (tema / "index.html").read_text(encoding="utf-8")
    # o que o tema pede: os data-i18n* e as chaves entre aspas nas linhas que chamam o I18N.t ou o I18N.tp (pega o
    # I18N.t(cond ? 'a.b' : 'a.c'))
    pedidas = set(re.findall(rf'data-i18n(?:-[a-z-]+)?="({CHAVE})"', html))
    plurais = set()
    for linha in html.splitlines():
        if "I18N.t(" in linha or "I18N.tp(" in linha:
            pedidas |= set(re.findall(rf"['\"]({CHAVE})['\"]", linha))
            plurais |= set(re.findall(rf"I18N\.tp\(\s*['\"]({CHAVE})['\"]", linha))
    for k in sorted(pedidas - plurais):
        if k not in base:
            falha(f"{tema.name}: the theme uses {k}, which is not in the files")
    for k in sorted(plurais):
        if f"{k}.other" not in base:
            falha(f"{tema.name}: the theme uses I18N.tp('{k}'), and {k}.other is not in the files")
    # o que sobra: a chave que nao aparece entre aspas nem num data-i18n do tema
    citadas = set(re.findall(rf"['\"]({CHAVE})['\"]", html))
    for k in base:
        if k not in citadas and not any(k.startswith(p + ".") for p in plurais):
            falha(f"{tema.name}: {k} is in the files but the theme never uses it")
    print(f"{tema.name}: {len(base)} keys in {len(por_lingua)} languages, {len(pedidas)} used by the theme")


def confere_modulo():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "x.properties"
        p.write_text("﻿# comentario\n! outro\n\na.b = Olá {nome}  \nc.d=linha\\nnova = com igual\\\\\n",
                     encoding="utf-8")
        got = i18n.ler(p)
        if got != {"a.b": "Olá {nome}", "c.d": "linha\nnova = com igual\\"}:
            falha(f"ler: {got!r}")
        for ruim in ("a.b=1\na.b=2\n", "sem igual\n", "=sem chave\n"):
            p.write_text(ruim, encoding="utf-8")
            try:
                i18n.ler(p)
                falha(f"ler accepted {ruim!r}")
            except ValueError:
                pass
        p.write_bytes(b"a.b=\xff\n")
        try:
            i18n.ler(p)
            falha("ler accepted a file that is not UTF-8")
        except ValueError:
            pass

    casos = [("pt-BR", "pt_BR"), ("pt_PT", "pt_BR"), ("PT", "pt_BR"), ("en-US", "en"), ("es", None), ("", None),
             (None, None)]
    for codigo, esperado in casos:
        if i18n.lingua_de(codigo) != esperado:
            falha(f"lingua_de({codigo!r}) = {i18n.lingua_de(codigo)!r}, expected {esperado!r}")
    pref = i18n.preferidas("es;q=0.5, pt-BR, en;q=0.8, fr;q=0, de")
    if pref != ["pt-BR", "de", "en", "es"]:
        falha(f"preferidas: {pref!r}")

    detecta = i18n.DETECTA
    try:
        i18n.DETECTA = False
        for pedida, accept, esperado in [(None, "en-US", i18n.PADRAO), ("en", "", "en"), ("pt", "en", "pt_BR"),
                                         ("xx", "en", i18n.PADRAO)]:
            if (got := i18n.escolher(pedida, accept)) != esperado:
                falha(f"escolher({pedida!r}, {accept!r}) without detection = {got!r}, expected {esperado!r}")
        i18n.DETECTA = True
        for pedida, accept, esperado in [(None, "pt-BR,pt;q=0.9,en;q=0.8", "pt_BR"), (None, "es,en;q=0.5", "en"),
                                         (None, "es,pt;q=0.5,en;q=0.7", "en"), (None, "es", "en"), (None, "", "en"),
                                         ("pt_BR", "en-US", "pt_BR")]:
            if (got := i18n.escolher(pedida, accept)) != esperado:
                falha(f"escolher({pedida!r}, {accept!r}) with detection = {got!r}, expected {esperado!r}")
    finally:
        i18n.DETECTA = detecta

    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        (pasta / "i18n_en.properties").write_text("a.b=</script><b>x</b>\n", encoding="utf-8")
        (pasta / "i18n_pt_BR.properties").write_text("a.b=ação\n", encoding="utf-8")
        html = i18n.injeta(f"<head>{i18n.MARCA}</head>", pasta, "pt_BR")
        if "</script><b>" in html or "ação" not in html or '"lingua":"pt_BR"' not in html:
            falha(f"injeta: {html!r}")
        if i18n.injeta("<head></head>", pasta, "en") != "<head></head>":
            falha("injeta changed a page without the marker")
        if i18n.injeta(i18n.MARCA, pasta / "nao-existe", "en") != i18n.MARCA:
            falha("injeta changed a page whose theme has no i18n folder")
        (pasta / "i18n_en.properties").write_text("quebrado\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as log:
            html = i18n.injeta(i18n.MARCA, pasta, "en")
        if '"textos":{}' not in html or "could not read" not in log.getvalue():
            falha("injeta with a broken file should send no texts and log the error")
    print("i18n.py: parser, language choice and page injection checked")


def main():
    confere_modulo()
    temas = [d for d in sorted((RAIZ / "themes").iterdir()) if (d / "i18n").is_dir()]
    if not temas:
        falha("no theme has an i18n/ folder")
    for tema in temas:
        confere_tema(tema)
    print(f"{len(falhas)} failure(s)" if falhas else "all good")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
