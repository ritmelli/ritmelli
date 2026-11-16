"""Confere os textos da interface (i18n/ de cada tema, o plano no I18N.md do ritmelli-server) e o i18n.py.

    python dev/testa_i18n.py

Nos arquivos de cada tema: as mesmas chaves nas duas linguas e na mesma ordem, nenhum valor vazio, os mesmos {param}
nos dois lados, toda chave que o tema usa existindo e nenhuma chave sobrando. Uma chave conta como usada quando aparece
no tema entre aspas ou num data-i18n*; as que o I18N.tp usa (chave.one, chave.other) contam pela chave de base. O
texto com marcacao so tem <b> e <code>, fechados e sem um dentro do outro, os mesmos nas duas linguas, e so entra pelo
data-i18n ou pelo I18N.rico (o I18N.t e os atributos mostrariam a tag). As mensagens do servidor (i18n.msg e
i18n.Recusa no Python da raiz): cada chave server.* existe em todo tema com i18n/, com os mesmos {param} do texto em
ingles; cada chamada passa os params do texto; o texto em ingles (e o do i18n.so_texto) nao tem acento; e o tema nao
guarda chave server.* que o servidor nao manda. Os efeitos do fx.py: cada um com effect.<id>.name e .desc, e cada
grupo com effect.group.<grupo>, e nenhuma chave effect.* sobrando. No i18n.py: o leitor do .properties, a escolha da lingua, o texto
posto na pagina e a mensagem. Sai 1 se algo falha."""
import ast
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import i18n  # noqa: E402

# o hifen so depois do primeiro ponto: e o id do efeito (effect.radio-policia.name)
CHAVE = r"[a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9-]+)+"
falhas = []


def falha(msg):
    falhas.append(msg)
    print(f"FAIL {msg}")


def params(s):
    return set(re.findall(r"\{(\w+)\}", s))


def tags(s):
    """As tags de um valor, na ordem; None se ha tag que o I18N.rico nao conhece ou se ela nao fecha direito."""
    achadas = re.findall(r"<[^>]*>", s)
    if any(t not in ("<b>", "</b>", "<code>", "</code>") for t in achadas) or re.search(r"<(?![/a-z])", s):
        return None
    for abre, fecha in zip(achadas[::2], achadas[1::2] + [None]):
        if fecha != abre.replace("<", "</"):
            return None
    return achadas


def chaves_do_servidor():
    """As mensagens que o Python da raiz manda: {chave: (texto em ingles, arquivo:linha)}. A chave e o texto vao
    literais no i18n.msg e no i18n.Recusa, para darem para conferir aqui."""
    achadas = {}
    for py in sorted(RAIZ.glob("*.py")):
        for no in ast.walk(ast.parse(py.read_text(encoding="utf-8"), str(py))):
            if not isinstance(no, ast.Call):
                continue
            nome = no.func.attr if isinstance(no.func, ast.Attribute) else getattr(no.func, "id", None)
            onde = f"{py.name}:{no.lineno}"
            if nome == "so_texto" and no.args:
                partes = no.args[0].values if isinstance(no.args[0], ast.JoinedStr) else [no.args[0]]
                texto = "".join(x.value for x in partes if isinstance(x, ast.Constant) and isinstance(x.value, str))
                if re.search(r"[À-ÿ]", texto):
                    falha(f"{onde}: so_texto is English only: {texto!r}")
            if nome not in ("msg", "Recusa") or py.name == "i18n.py":  # o i18n.py so repassa
                continue
            if len(no.args) < 2 or not all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in no.args[:2]):
                falha(f"{onde}: {nome}() takes the key and the English text as literal strings")
                continue
            chave, texto = no.args[0].value, no.args[1].value
            if not re.fullmatch(rf"server\.{CHAVE}", chave):
                falha(f"{onde}: the key {chave!r} must look like server.area.name")
            if re.search(r"[À-ÿ]", texto):
                falha(f"{onde}: the text of {chave} is English only: {texto!r}")
            kw = {k.arg for k in no.keywords if k.arg}
            if kw != params(texto):
                falha(f"{onde}: {chave} gets {sorted(kw)}, and its text has {sorted(params(texto))}")
            try:
                texto.format(**{x: "" for x in params(texto)})
            except (IndexError, KeyError, ValueError):
                falha(f"{onde}: the text of {chave} is not a valid format string")
            if chave in achadas and achadas[chave][0] != texto:
                falha(f"{onde}: {chave} has another text in {achadas[chave][1]}")
            achadas.setdefault(chave, (texto, onde))
    return achadas


def efeitos_do_servidor():
    """As chaves que os efeitos do fx.py pedem ao tema. O CATALOGO e lido pelo ast, porque o fx.py importa o audio:
    cada tupla (grupo, id, fabrica) dele, a da mina tambem."""
    chaves = set()
    for no in ast.walk(ast.parse((RAIZ / "fx.py").read_text(encoding="utf-8"))):
        if not (isinstance(no, ast.Assign) and any(getattr(t, "id", None) == "CATALOGO" for t in no.targets)):
            continue
        for t in ast.walk(no.value):
            if isinstance(t, ast.Tuple) and len(t.elts) == 3 and all(
                    isinstance(x, ast.Constant) and isinstance(x.value, str) for x in t.elts[:2]):
                grupo, eid = t.elts[0].value, t.elts[1].value
                chaves |= {f"effect.{eid}.name", f"effect.{eid}.desc"} | ({f"effect.group.{grupo}"} if grupo else set())
    if not chaves:
        falha("fx.py: no effect found in CATALOGO")
    return chaves


def confere_tema(tema, servidor, efeitos):
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
            if tags(v) is None:
                falha(f"{tema.name}: {k} in {lingua} has markup other than closed <b> and <code>")
            elif k in base and tags(base[k]) is not None and tags(v) != tags(base[k]):
                falha(f"{tema.name}: {k} has the tags {tags(v)} in {lingua}, {tags(base[k])} in {i18n.RESERVA}")

    html = (tema / "index.html").read_text(encoding="utf-8")
    # o que o tema pede: os data-i18n* e as chaves entre aspas nas linhas que chamam o I18N.t, o I18N.tp ou o
    # I18N.rico (pega o I18N.t(cond ? 'a.b' : 'a.c'))
    pedidas = set(re.findall(rf'data-i18n(?:-[a-z-]+)?="({CHAVE})"', html))
    # onde a tag apareceria escrita: os atributos e as linhas do I18N.t sem o I18N.rico
    sem_marcacao = set(re.findall(rf'data-i18n-[a-z-]+="({CHAVE})"', html))
    plurais = set()
    for linha in html.splitlines():
        if "I18N.t(" in linha or "I18N.tp(" in linha or "I18N.rico(" in linha:
            nela = set(re.findall(rf"['\"]({CHAVE})['\"]", linha))
            pedidas |= nela
            plurais |= set(re.findall(rf"I18N\.tp\(\s*['\"]({CHAVE})['\"]", linha))
            if "I18N.rico(" not in linha:
                sem_marcacao |= nela
    for k in sorted(sem_marcacao):
        if tags(base.get(k, "")):
            falha(f"{tema.name}: {k} has markup, so it goes through data-i18n or I18N.rico, not I18N.t or an attribute")
    for k in sorted(efeitos - base.keys()):
        falha(f"{tema.name}: the effects in fx.py need {k}, which is not in the files")
    for k, (texto, onde) in sorted(servidor.items()):
        if k not in base:
            falha(f"{tema.name}: the server sends {k} ({onde}), which is not in the files")
        elif params(base[k]) != params(texto):
            falha(f"{tema.name}: {k} has params {sorted(params(base[k]))}, and the server sends {sorted(params(texto))}")
    for k in sorted(pedidas - plurais):
        if k not in base:
            falha(f"{tema.name}: the theme uses {k}, which is not in the files")
    for k in sorted(plurais):
        if f"{k}.other" not in base:
            falha(f"{tema.name}: the theme uses I18N.tp('{k}'), and {k}.other is not in the files")
    # o que sobra: a chave que nao aparece entre aspas nem num data-i18n do tema
    citadas = set(re.findall(rf"['\"]({CHAVE})['\"]", html))
    for k in base:
        if k.startswith("server."):
            if k not in servidor:
                falha(f"{tema.name}: {k} is in the files but the server never sends it")
        elif k.startswith("effect."):
            if k not in efeitos:
                falha(f"{tema.name}: {k} is in the files but fx.py has no such effect or group")
        elif k not in citadas and not any(k.startswith(p + ".") for p in plurais):
            falha(f"{tema.name}: {k} is in the files but the theme never uses it")
    print(f"{tema.name}: {len(base)} keys in {len(por_lingua)} languages, {len(pedidas)} used by the theme")


def confere_modulo():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "x.properties"
        p.write_text("﻿# comentario\n! outro\n\na.b = Olá {nome}  \nc.d=linha\\nnova = com igual\\\\\n"
                     "e.f = rótulo:\\ \ng.h=\\ resto\n", encoding="utf-8")
        got = i18n.ler(p)
        if got != {"a.b": "Olá {nome}", "c.d": "linha\nnova = com igual\\", "e.f": "rótulo: ", "g.h": " resto"}:
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

    m = i18n.msg("server.x.y", "Got {n} from {who}.", n=3, who="ana")
    if m != {"key": "server.x.y", "params": {"n": 3, "who": "ana"}, "text": "Got 3 from ana."}:
        falha(f"msg: {m!r}")
    try:
        raise i18n.Recusa("server.x.z", "No {name}.", name="mic")
    except ValueError as ex:  # a Recusa e um ValueError: quem ja pegava o ValueError segue pegando
        dentro = i18n.msg("server.x.w", "Failed ({reason}).", reason=i18n.motivo(ex))
        if str(ex) != "No mic." or dentro["params"]["reason"] != ex.msg or dentro["text"] != "Failed (No mic.).":
            falha(f"Recusa inside msg: {dentro!r}")
    if i18n.motivo(RuntimeError("x" * 300), 10) != "x" * 10 or i18n.so_texto("Hi.") != {"text": "Hi."}:
        falha("motivo or so_texto")
    print("i18n.py: parser, language choice, page injection and messages checked")


def main():
    confere_modulo()
    temas = [d for d in sorted((RAIZ / "themes").iterdir()) if (d / "i18n").is_dir()]
    if not temas:
        falha("no theme has an i18n/ folder")
    servidor, efeitos = chaves_do_servidor(), efeitos_do_servidor()
    print(f"server: {len(servidor)} message keys, {len(efeitos)} effect keys")
    for tema in temas:
        confere_tema(tema, servidor, efeitos)
    print(f"{len(falhas)} failure(s)" if falhas else "all good")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
