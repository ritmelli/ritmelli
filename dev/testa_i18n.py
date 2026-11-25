"""Confere os textos da interface (i18n/ de cada tema, o plano no I18N.md do ritmelli-server) e o i18n.py.

    python dev/testa_i18n.py

Nos arquivos de cada tema e nos da galeria (gallery/, a pagina inicial): as mesmas chaves nas duas linguas e na mesma ordem, nenhum valor vazio, os mesmos {param}
nos dois lados, toda chave que o tema usa existindo e nenhuma chave sobrando. Uma chave conta como usada quando aparece
no tema entre aspas ou num data-i18n*; as que o I18N.tp usa (chave.one, chave.other) contam pela chave de base. O
texto com marcacao so tem <b> e <code>, fechados e sem um dentro do outro, os mesmos nas duas linguas, e so entra pelo
data-i18n ou pelo I18N.rico (o I18N.t e os atributos mostrariam a tag). As mensagens do servidor (i18n.msg e
i18n.Recusa no Python da raiz): cada chave server.* existe em todo tema com i18n/, com os mesmos {param} do texto em
ingles; cada chamada passa os params do texto; o texto em ingles (e o do i18n.so_texto) nao tem acento; e o tema nao
guarda chave server.* que o servidor nao manda. Os efeitos do fx.py: cada um com effect.<id>.name e .desc, e cada
grupo com effect.group.<grupo>, e nenhuma chave effect.* sobrando. As palavras do pixel art: cada lingua so com as
letras que a tabela de pixel delas tem (as placas, os mostradores do mixer, a fita da voz, os nomes dos pedais da mesa
e o visor do pedal de troca de voz). O meta.json de cada tema: o campo que vem por lingua tem as duas. No i18n.py: o leitor do .properties, a escolha da lingua, o texto
posto na pagina e a mensagem. O tema e o index.html e todos os .js e .css da pasta dele (e das de dentro), e cada bloco
marcado (o /* NOME-INICIO ... /* NOME-FIM */, e o /* nome:inicio ... /* nome:fim */ que um gerador de dev/ grava) mora
num lugar so: o que sai do index.html para um arquivo nao fica nos dois. The inline CSS and JS of the index.html stay at or
under a ceiling that only goes down (INLINE_CEILING), and the count goes to the PR summary. Sai 1 se algo falha."""
import ast
import contextlib
import io
import itertools
import json
import re
import sys
import tempfile
from html.parser import HTMLParser
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


def arquivos_do_tema(tema):
    """{caminho na pasta do tema: texto}: o index.html primeiro e depois todo .js e .css da pasta e das de dentro."""
    extras = sorted(p for p in tema.rglob("*") if p.suffix in (".js", ".css") and p.is_file())
    return {p.relative_to(tema).as_posix(): p.read_text(encoding="utf-8") for p in [tema / "index.html", *extras]}


# a marca de um bloco: /* DECK-JS-INICIO, /* DECK-JS-FIM */, /* pecas:inicio, /* pecas:fim */
MARCA_BLOCO = re.compile(r"/\*\s*(?:([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)-(INICIO|FIM)|([a-z]+):(inicio|fim))\b")


def confere_blocos(tema, arquivos):
    """Cada marca de bloco aparece uma vez so em todo o tema: o bloco que saiu do index.html para um .js ou .css e ficou
    tambem no index.html (ou foi copiado duas vezes) falha, com os lugares."""
    onde = {}
    for nome, texto in arquivos.items():
        for m in MARCA_BLOCO.finditer(texto):
            bloco, ponta = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4).upper())
            linha = texto.count("\n", 0, m.start()) + 1
            onde.setdefault((bloco, ponta), []).append(f"{nome}:{linha}")
    for (bloco, ponta), lugares in sorted(onde.items()):
        if len(lugares) > 1:
            falha(f"{tema.name}: the {ponta} mark of the block {bloco} is in {len(lugares)} places "
                  f"({', '.join(lugares)}): a block lives in one file only")
    print(f"{tema.name}: {len(arquivos)} file(s), {len({b for b, _ in onde})} marked block(s)")


# The lines of inline CSS and JS each theme's index.html has. The number only goes down: new theme code goes into a file
# of the theme folder, and a PR that moves code out of the page lowers it to the new count. A count under the ceiling
# fails too, so the ceiling follows each move and a later PR cannot spend the lines that one freed.
INLINE_CEILING = {"ritmelli": 1637}
INLINE = re.compile(r"<(style|script)\b([^>]*)>(.*?)</\1>", re.S)


def inline_lines(html):
    """The lines of text inside the page's <style> and <script> elements (a <script src> brings none)."""
    total = 0
    for m in INLINE.finditer(html):
        if re.search(r"\bsrc\s*=", m.group(2)):
            continue
        body = m.group(3).strip("\n")
        total += body.count("\n") + 1 if body.strip() else 0
    return total


def check_inline_ceiling(tema, html):
    """Fails when the index.html has more or fewer inline lines than its ceiling. The count goes to the PR summary (the
    "-- summary:" line, which dev/testa_tudo.py copies)."""
    if tema.name not in INLINE_CEILING:
        return
    count, ceiling = inline_lines(html), INLINE_CEILING[tema.name]
    print(f"-- summary: {tema.name}/index.html: {count} lines of inline CSS and JS (ceiling {ceiling})")
    if count > ceiling:
        falha(f"{tema.name}: index.html has {count} lines of inline CSS and JS, over the ceiling of {ceiling}: new "
              f"theme code goes into a file of the theme folder (INLINE_CEILING in dev/testa_i18n.py only goes down)")
    elif count < ceiling:
        falha(f"{tema.name}: index.html has {count} lines of inline CSS and JS, under the ceiling of {ceiling}: lower "
              f"INLINE_CEILING in dev/testa_i18n.py to {count}")


# The file each theme loads before all its other scripts (the shared state and helpers). The onerror of every
# <script src> of its page calls the same handler, scriptFailed, which the <head> declares before the first file.
SHARED_FIRST = {"ritmelli": "shared.js"}
SCRIPT_TAG = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S)
ONERROR = "scriptFailed(this)"


class _Attrs(HTMLParser):
    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def tag_attrs(text):
    """The attributes of a <script ...> tag as the browser reads them ({name: value}, None for a bare one)."""
    parser = _Attrs()
    parser.attrs = {}
    parser.feed(f"<script{text}>")
    return parser.attrs


def page_scripts(html, arquivos):
    """The scripts of the page in the order they run: (where, first line, text) for each inline <script> and each
    <script src> (the src as written, and None for the text when the file is not in the theme folder)."""
    out = []
    for m in SCRIPT_TAG.finditer(html):
        src = tag_attrs(m.group(1)).get("src")
        if src:
            out.append((src, 1, arquivos.get(src)))
        else:
            out.append(("index.html", html.count("\n", 0, m.start(2)) + 1, m.group(2)))
    return out


def check_script_tags(tema, html):
    """Every <script src> of the page is a classic script that runs in order (no defer, async or type) and calls the
    common onerror, and the shared file is the first of them."""
    if tema.name not in SHARED_FIRST:
        return
    tags = [(tag_attrs(m.group(1)), m.group(1), html.count("\n", 0, m.start()) + 1) for m in SCRIPT_TAG.finditer(html)]
    tags = [t for t in tags if t[0].get("src")]
    for attrs, text, line in tags:
        if attrs.get("onerror") != ONERROR:
            falha(f"{tema.name}: index.html:{line}: <script{text}> has no onerror=\"{ONERROR}\": a file that does not "
                  f"load would leave the page without a connection")
        for extra in sorted({"defer", "async", "type"} & attrs.keys()):
            falha(f"{tema.name}: index.html:{line}: <script{text}> has {extra}: the scripts of the page run in order, "
                  f"each one before the parser goes on")
    first = tags[0][0]["src"] if tags else None
    if first != SHARED_FIRST[tema.name]:
        falha(f"{tema.name}: the first <script src> of the index.html is {first}, not {SHARED_FIRST[tema.name]}: the "
              f"shared state and helpers load before every other script")


REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
REGEX_AFTER_WORD = re.compile(r"(?<![\w$.])(?:return|typeof|case|in|of|void|delete|throw|new|else|do)$")


def js_code(text):
    """The text of a script with its comments, strings, template literals and regex literals blanked (the newlines stay,
    so the lines do too): the brackets left are the code's."""
    out, i, n = [], 0, len(text)
    while i < n:
        c, nxt = text[i], text[i + 1:i + 2]
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))
            i = j
            continue
        before = "".join(out[-40:]).rstrip()
        regex = c == "/" and (not before or before[-1] in REGEX_AFTER or REGEX_AFTER_WORD.search(before))
        if c in "'\"`" or regex:
            j, depth, in_class = i + 1, 0, False
            while j < n:
                d = text[j]
                if d == "\\":
                    j += 2
                    continue
                if c == "`" and d == "$" and text[j + 1:j + 2] == "{":
                    depth += 1
                elif c == "`" and d == "}" and depth:
                    depth -= 1
                elif regex and d in "[]":
                    in_class = d == "["
                elif d == c and not depth and not in_class:
                    break
                elif d == "\n" and c != "`":
                    break
                j += 1
            out.append('""' + "\n" * text.count("\n", i, j))
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


DECL = re.compile(r"(?:async\s+)?function\b\s*\*?\s*([A-Za-z_$][\w$]*)|class\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+")
VAR = re.compile(r"var\s+")
# a line that does not end the statement: it ends in an operator, or the next one starts with one
GOES_ON = re.compile(r"[=,(\[{+\-*/?:&|]\s*$")
GOES_ON_NEXT = re.compile(r"\s*(?:[.?:,+\-*/&|=]|\)|\])")


def pattern_names(target):
    """The names a declarator binds: the name itself, or the ones of a destructuring pattern, without its keys
    ({ key: name }) and without its default values ({ name = other })."""
    kept, depth, skipping = "", 0, None
    for k, ch in enumerate(target):
        if skipping is not None:
            depth += (ch in "{([") - (ch in "})]")
            if depth < skipping or (depth == skipping and ch == ","):
                skipping = None
                kept += ch
            continue
        if ch == "=" and target[k + 1:k + 2] not in ("=", ">") and target[k - 1:k] not in ("=", "!", "<", ">"):
            skipping = depth
            continue
        depth += (ch in "{([") - (ch in "})]")
        kept += ch
    return re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)(?![\w$]|\s*:)", kept)


def declarators(code, j):
    """(names, end): the names of the declarators that start at code[j] (after const, let or var), up to the end of the
    statement, split by the commas outside brackets."""
    n, d, part, names = len(code), 0, "", []

    def take(p):
        p = p.strip()
        if p[:1] in "{[":
            close = {"{": "}", "[": "]"}[p[0]]
            names.extend(pattern_names(p[:p.rindex(close) + 1] if close in p else p))
        elif p:
            names.extend(pattern_names(p.split("=", 1)[0]))
    while j < n:
        ch = code[j]
        d += (ch in "{([") - (ch in "})]")
        if d < 0:
            break
        if d == 0 and ch == ",":
            take(part)
            part = ""
        elif d == 0 and (ch == ";" or ch == "\n" and not GOES_ON.search(part) and not GOES_ON_NEXT.match(code, j + 1)):
            break
        else:
            part += ch
        j += 1
    take(part)
    return names, j


def top_level_names(text):
    """(name, line) for each name a script declares at its top level: function, class, const, let and var, the names
    inside a destructuring pattern and the ones after a comma too. A var counts wherever it is: in a block of the top
    level it is global too (and the theme declares with let and const)."""
    code = js_code(text)
    names, depth, i, n = [], 0, 0, len(code)
    while i < n:
        c = code[i]
        if c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
        elif c.isalpha() and (i == 0 or not (code[i - 1].isalnum() or code[i - 1] in "_$.")):
            m = DECL.match(code, i) if depth == 0 else VAR.match(code, i)
            before = code[:i].rstrip()[-1:]
            # a statement starts after a ; or a }, or on a new line after a line that ended one (no semicolon there)
            new_line = code[:i].rstrip(" \t").endswith("\n")
            starts = not before or before in ";{}" or (new_line and before not in "=(,:?&|+-*/[")
            starts = starts or (depth > 0 and before == "(" and code[:i].rstrip()[:-1].rstrip().endswith("for"))
            if m and starts:
                line = code.count("\n", 0, i) + 1
                if depth == 0 and (m.group(1) or m.group(2)):
                    names.append((m.group(1) or m.group(2), line))
                    i = m.end()
                    continue
                found, i = declarators(code, m.end())
                names += [(x, line) for x in found]
                continue
        i += 1
    return names


def check_unique_names(tema, html, arquivos):
    """No name is declared at the top level twice among the scripts of the page (the inline ones and each file): a
    second const or let stops the script that has it, and a second function silently takes the place of the first."""
    if tema.name not in SHARED_FIRST:
        return
    where = {}
    for unit, first, text in page_scripts(html, arquivos):
        for name, line in top_level_names(text or ""):
            where.setdefault(name, []).append(f"{unit}:{first + line - 1}")
    for name, places in sorted(where.items()):
        if len(places) > 1:
            falha(f"{tema.name}: {name} is declared at the top level in {len(places)} places ({', '.join(places)}): "
                  f"the scripts of a page share one scope")
    print(f"{tema.name}: {len(where)} top-level names in the scripts of the page, each declared once")


def check_name_reader():
    """The reader of top-level names on a made-up script, and the duplicate failing across two scripts."""
    text = ("'use strict';\nconst a = 1, b = f(2, 3), { c, d: e } = o, [g] = [];\nlet h\nfunction i() { const no1 = 1; }\n"
            "async function j() {}\nclass K {}\nconst l = () => { let no2; };\nconst s = 'function no3() {}', r = /[(]/g;\n"
            "// const no4 = 1\n/* let no5 */\nconst m = `${'}'}` + x\n  .y;\nif (a) { var t; let no6; }\nvar n = cond\n  ? 1 : 2;\n"
            "const { u = no7, v: w = no8, label: nm = no10 } = data, [z = no9] = [];\nfor (var q = 0; q < 1; q++) {}\n")
    got = [x for x, _ in top_level_names(text)]
    want = ["a", "b", "c", "e", "g", "h", "i", "j", "K", "l", "s", "r", "m", "t", "n", "u", "w", "nm", "z", "q"]
    if got != want:
        falha(f"top_level_names read {got}, expected {want}")
    antes = len(falhas)
    with contextlib.redirect_stdout(io.StringIO()):
        check_unique_names(Path("ritmelli"), '<script src = "x.js"></script><script>\nfunction dup() {}\n</script>',
                           {"x.js": "let y;\nfunction dup() {}\n"})
    if len(falhas) != antes + 1 or "dup is declared at the top level in 2 places (x.js:2, index.html:2)" not in falhas[-1]:
        falha(f"check_unique_names should fail once on dup: {falhas[antes:]}")
    else:
        del falhas[antes:]
    with contextlib.redirect_stdout(io.StringIO()):
        check_script_tags(Path("ritmelli"), '<script src="shared.js" data-onerror="scriptFailed(this)"></script>'
                          "<script src='queue.js' title='onerror=\"scriptFailed(this)\"'></script>"
                          '<script src="x.js" onerror="scriptFailed(this)" defer></script>')
    if len(falhas) != antes + 3 or "has no onerror" not in falhas[-3] or "has defer" not in falhas[-1]:
        falha(f"check_script_tags should fail on a data-onerror, an onerror in another attribute and a defer: "
              f"{falhas[antes:]}")
    else:
        del falhas[antes:]
    print("the top-level name reader and the script tag check checked")


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
            # a barra solta no fim (o "\ " cujo espaco um editor cortou) vira barra na tela: o espaco no fim se escreve \u0020
            if v.endswith("\\"):
                falha(f"{tema.name}: {k} in {lingua} ends with a lone backslash (write a trailing space as \\u0020)")
            if k in base and params(v) != params(base[k]):
                falha(f"{tema.name}: {k} has params {sorted(params(v))} in {lingua}, "
                      f"{sorted(params(base[k]))} in {i18n.RESERVA}")
            if tags(v) is None:
                falha(f"{tema.name}: {k} in {lingua} has markup other than closed <b> and <code>")
            elif k in base and tags(base[k]) is not None and tags(v) != tags(base[k]):
                falha(f"{tema.name}: {k} has the tags {tags(v)} in {lingua}, {tags(base[k])} in {i18n.RESERVA}")

    arquivos = arquivos_do_tema(tema)
    confere_blocos(tema, arquivos)
    check_inline_ceiling(tema, arquivos["index.html"])
    check_script_tags(tema, arquivos["index.html"])
    check_unique_names(tema, arquivos["index.html"], arquivos)
    html = "\n".join(arquivos.values())
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
    confere_pixel(tema, html, por_lingua)


def confere_meta(tema):
    """O meta.json de um tema traduzido: o campo que vem por lingua ({"en": ..., "pt_BR": ...}) tem todas, com texto.
    O que vem como texto so vale igual nas duas (o nome, que e marca)."""
    p = tema / "meta.json"
    if not p.exists():
        return
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as ex:
        falha(f"{tema.name}/meta.json: {ex}")
        return
    for campo, valor in meta.items():
        if isinstance(valor, dict) and (set(valor) != set(i18n.LINGUAS) or not all(isinstance(v, str) and v for v in valor.values())):
            falha(f"{tema.name}/meta.json: {campo} has {sorted(valor)}, expected a text for each of {list(i18n.LINGUAS)}")


def letras_da_tabela(html, inicio, fim, chave):
    """As letras de uma tabela de pixel do tema (o bloco de inicio ate fim, cada letra como chave), ou None sem ela."""
    m = re.search(re.escape(inicio) + r"(.*?)" + re.escape(fim), html, re.S)
    return set(re.findall(chave, m.group(1))) if m else None


def larguras_pedal(html):
    """A largura em celulas que cada letra da LETRA_PEDAL (a dos nomes dos pedais da mesa e do visor do Troca de voz)
    ocupa na linha, ou None sem ela: como o avanco() do PEDAL-JS, so as 7 linhas da maiuscula contam (a ponta do agudo
    do I fica no vao da direita)."""
    m = re.search(r"const LETRA_PEDAL = \{(.*?)\n\};", html, re.S)
    if not m:
        return None
    larg = {}
    for ch, linhas in re.findall(r'\n  "(.)": (\[[^\]]*\])', m.group(1)):
        g = json.loads(linhas)
        cap = g[3:10] if len(g) - 7 == 3 else g[:7]
        larg[ch] = max((r.rfind("#") + 1 for r in cap), default=0) or len(g[0])
    return larg or None


def linhas_do_pedal(nome, larg, maxw, maxlin):
    """Como o arrumaNome do PEDAL-JS: o nome em ate maxlin linhas de ate maxw celulas, quebrando no espaco, no hifen ou no
    hifen opcional (que vira o - da quebra), no menor numero de linhas e, entre as quebras com esse numero, na mais
    equilibrada (a de linha mais larga mais estreita). None se nao cabe."""
    n = nome.upper()
    cortes = [i for i, ch in enumerate(n) if ch in " -­"]
    largura = lambda t: sum(larg.get(ch, 1) for ch in t) + max(0, len(t) - 1)
    for k in range(maxlin):
        melhor = None
        for cs in itertools.combinations(cortes, k):
            linhas, ini = [], 0
            for c in cs:
                linhas.append((n[ini:c] + ("" if n[c] == " " else "-")).replace("­", "").strip())
                ini = c + 1
            linhas.append(n[ini:].replace("­", "").strip())
            m = max(map(largura, linhas))
            if all(linhas) and m <= maxw and (melhor is None or m < melhor[0]):
                melhor = (m, linhas)
        if melhor:
            return melhor[1]
    return None


def topos_do_pedal(html):
    """O topo das maiusculas de cada linha do nome no pedal da mesa, por numero de linhas (o TOPOS do PEDAL-JS), ou None."""
    m = re.search(r"const TOPOS = \{ 1: \[(\d+)\], 2: \[(\d+), (\d+)\], 3: \[(\d+), (\d+), (\d+)\] \};", html)
    if not m:
        return None
    v = [int(x) for x in m.groups()]
    return {1: v[:1], 2: v[1:3], 3: v[3:]}


def medidas_do_pedal(html):
    """(a largura do nome no pedal da mesa, a do texto no vidro do visor do Troca de voz, a do nome do Troca de voz), em
    celulas, lidas do PEDAL-JS e do PEDAL CSS: a faixa do nome do comum e a largura dele menos a faixa (em px), no comum
    mais estreito (o de 88 do CSS; o de 98 tem mais); o vw do visor menos a moldura e 1 de margem de cada lado (o area
    do visor()); a largura do Troca de voz no CSS menos 24 px, em celulas (o arrumaNome dele). None se nao ler."""
    faixa = re.search(r"comum: \{[^}]*\bfaixa: (\d+)", html)
    comum = re.search(r"\.palco \.tecla\.ped-ok \{\s*flex: none; width: (\d+)px", html)
    vw = re.search(r"const vw = (\d+), vx =", html)
    troca = re.search(r'\.tecla\.ped-ok\[data-ef="pistavoz"\] \{ width: (\d+)px', html)
    if not faixa or not comum or not vw or not troca:
        return None
    return (int(comum.group(1)) - int(faixa.group(1))) // 2, int(vw.group(1)) - 6, (int(troca.group(1)) - 24) // 2


def larguras_g8(html):
    """A largura de cada letra do G8, a dos rotulos dos volumes e da placa do mixer da mesa (o MIX-JS), com as acentuadas
    do A8 e o cedilha na largura da letra de base, ou None sem ela."""
    m = re.search(r"const G8 = \{(.*?)\n  \};", html, re.S)
    if not m:
        return None
    larg = {ch.strip('"'): len(linha) for ch, linha in re.findall(r'\n    ([A-Z]|" "): \["([.#]+)"', m.group(1))}
    if not larg:   # o formato mudou: o confere_pixel acusa a tabela que nao deu para ler
        return {}
    a8 = re.search(r"const A8 = \{([^\n]*)\};", html)
    for acentuada, base in re.findall(r'"(.)": \["([A-Z])"', a8.group(1) if a8 else ""):
        if base in larg:
            larg[acentuada] = larg[base]
    if "C" in larg:
        larg["Ç"] = larg["C"]
    return larg


# a largura de uma palavra dos rotulos dos volumes da mesa, em pixels do G8 (com os 2 entre as letras): a coluna embaixo
# de cada mostrador tem 92,7 do palco, e no Windows a 125% o pixel da letra vale 2 (o RECORD e o PHONES tem 46)
ROTULO_MX = 46
FADERS_MX = ("mixer.recordInGame", "mixer.recordInHeadphonesShort", "mixer.voice")


CAP_PEDAL, ACENTO_PEDAL, CAUDA_PEDAL = 7, 3, 2   # a maiuscula da LETRA_PEDAL, o acento em cima dela e a cauda do Ç embaixo
# o visor, como o PEDAL-JS: o OUVINDO na letra dos nomes, 3 de folga e os 6 blocos de 3 x 5 (2 de folga e blocos de 2 x 5
# se nao couber); o PRONTO com o visto (7 de largura na letra dos nomes) 4 celulas depois; a letra de LCD so entra se
# couber, entao a conta e a da letra dos nomes, a mais estreita. Os nomes dos pedais e o vidro vem do medidas_do_pedal
VISOR_EXTRA = {"effects.voicePedal.say": 0, "effects.voicePedal.listening": 2 + 6 * 3 - 1,   # a folga e os blocos de 2 de largura
               "effects.voicePedal.ready": 4 + 7}


ACENTUADAS = set("ÁÀÂÃÉÊÍÓÔÕÚÜ")   # as que a LETRA_PEDAL desenha com o acento em cima (o Ç pendura embaixo)


def confere_pixel(tema, html, por_lingua):
    """As palavras que o pixel art desenha com letras proprias: cada lingua so pode usar as letras que a tabela tem
    (a que falta some ou leva o texto para o HTML). Os titulos das placas na negrita da LETRA_PLACA e as contagens na
    regular dela, os nomes dos mostradores no NOMEV do mixer, os rotulos dos volumes e a placa dele no G8 (cada palavra
    dos rotulos cabendo na coluna), a fita da voz no LETRAS_FITA, e os nomes dos pedais da mesa e o visor do pedal de
    troca de voz na LETRA_PEDAL (cada nome cabendo no pedal em ate 3 linhas, o do Troca de voz numa, e cada passo do
    visor cabendo no vidro, o OUVINDO com a barra). Em tema sem a tabela, nada a conferir; a tabela que o
    tema tem e daqui nao deu para ler, ou a chave daqui que sumiu dos arquivos, falha (senao passaria sem conferir)."""
    placa = re.search(r"const LETRA_PLACA = \{\n  negrita: (\{.*?\}),\n  regular: (\{.*?\}),\n", html)
    g8 = larguras_g8(html)
    pedal = larguras_pedal(html)
    topos = topos_do_pedal(html)
    if pedal and topos is None:
        falha(f"{tema.name}: couldn't read TOPOS (the name lines of the desk pedal) in the theme "
              f"(update topos_do_pedal)")
    medidas = medidas_do_pedal(html) if pedal else None
    if pedal and medidas is None:
        falha(f"{tema.name}: couldn't read the name width, the display width or the voice changer width (PEDAL CSS) of "
              f"the desk pedal in the theme (update medidas_do_pedal)")
    nome_pedal, visor_pedal, nome_troca = medidas or (0, 0, 0)
    tabelas = {
        "G8": set(g8) if g8 else None,
        "negrita": set(json.loads(placa.group(1))) | {" "} if placa else None,
        "regular": set(json.loads(placa.group(2))) | set("0123456789") if placa else None,
        "NOMEV": letras_da_tabela(html, "const NOMEV = {", "\n  };", r"\b([A-Z]): \["),
        "LETRAS_FITA": (lambda s: s | {" "} if s else s)(letras_da_tabela(html, "const LETRAS_FITA = {", "\n};", r"\n  ([A-Z]): \[")),
        "PEDAL": set(pedal) | {"­"} if pedal else None,
    }
    # a tabela que o tema tem e a leitura daqui nao achou (o formato dela mudou) falha: sem isso, as palavras dela
    # passariam sem conferir nada
    DECLARACAO = {"G8": "const G8 = {", "negrita": "const LETRA_PLACA", "regular": "const LETRA_PLACA",
                  "NOMEV": "const NOMEV", "LETRAS_FITA": "const LETRAS_FITA", "PEDAL": "const LETRA_PEDAL"}
    for nome, tabela in tabelas.items():
        if DECLARACAO[nome] in html and not tabela:
            falha(f"{tema.name}: couldn't read the pixel font {nome} in the theme "
                  f"(its format changed? update confere_pixel)")
    if all(t is None for t in tabelas.values()):
        return
    # (chave, tabela, o texto como a tela desenha)
    PALAVRAS = [("nav.shelf", "negrita", str), ("queue.title", "negrita", str),
                ("shelf.count.one", "regular", lambda s: s.replace("{n}", "")), ("shelf.count.other", "regular", lambda s: s.replace("{n}", "")),
                ("queue.count.one", "regular", lambda s: s.replace("{n}", "")), ("queue.count.other", "regular", lambda s: s.replace("{n}", "")),
                ("mixer.meter.voice", "NOMEV", str.upper), ("mixer.meter.record", "NOMEV", str.upper),
                ("mixer.meter.game", "NOMEV", str.upper), ("effects.tape.voice", "LETRAS_FITA", str),
                ("mixer.autoTransition", "G8", str.upper)] + [(k, "G8", str.upper) for k in FADERS_MX] + [
                (k, "PEDAL", str.upper) for k in ("effects.voicePedal.say", "effects.voicePedal.listening", "effects.voicePedal.ready")]
    # os nomes dos efeitos no pedal da mesa, em maiuscula (o hifen opcional vira o - da quebra)
    PALAVRAS += [(k, "PEDAL", lambda s: s.upper().replace("­", "-")) for k in sorted(por_lingua.get(i18n.RESERVA, {}))
                 if re.fullmatch(r"effect\.[a-z-]+\.name", k)]
    # a chave daqui que sumiu dos arquivos (renomeada) falha, em vez de a palavra dela passar sem conferir
    base = por_lingua.get(i18n.RESERVA, {})
    for chave, tab, _ in PALAVRAS:
        if tabelas[tab] and chave not in base:
            falha(f"{tema.name}: confere_pixel checks {chave}, which is not in the files (renamed? update PALAVRAS)")
    vistas = 0
    for lingua, textos in por_lingua.items():
        for chave, tab, como in PALAVRAS:
            if tabelas[tab] is None or chave not in textos:
                continue
            vistas += 1
            falta = sorted(set(como(textos[chave])) - tabelas[tab])
            if falta:
                falha(f"{tema.name}: {chave} in {lingua} uses {''.join(falta)!r}, which the pixel font {tab} doesn't have")
        for chave in FADERS_MX:
            if g8 is None or chave not in textos:
                continue
            for p in textos[chave].upper().split():
                larg = sum(g8.get(ch, g8.get(" ", 3)) for ch in p) + 2 * (len(p) - 1)
                if larg > ROTULO_MX:
                    falha(f"{tema.name}: {chave} in {lingua} has {p!r}, {larg} pixels wide in G8: the desk mixer fits "
                          f"{ROTULO_MX} per word (use a shorter word)")
        if pedal is None or medidas is None:
            continue
        # o nome no pedal da mesa: ate 3 linhas de nome_pedal celulas (o do Troca de voz, mais largo, numa so), na quebra
        # que a tela escolhe; e a altura: cada linha tem o topo fixo (TOPOS), e o acento de uma linha de baixo (3 linhas
        # acima da maiuscula) nao pode encostar, contorno com contorno, no pe da de cima (a maiuscula, ou a cauda do Ç)
        for chave, texto in textos.items():
            m = re.fullmatch(r"effect\.([a-z-]+)\.name", chave)
            if not m:
                continue
            linhas = linhas_do_pedal(texto, pedal, *((nome_troca, 1) if m.group(1) == "pistavoz" else (nome_pedal, 3)))
            if not linhas:
                falha(f"{tema.name}: {chave} in {lingua} ({texto!r}) doesn't fit the desk pedal in the pixel font PEDAL "
                      f"(use a shorter name or a soft hyphen)")
                continue
            if topos and len(linhas) > 1:
                t = topos[len(linhas)]
                for k in range(1, len(linhas)):
                    topo = t[k] - (ACENTO_PEDAL if any(ch in ACENTUADAS for ch in linhas[k]) else 0)
                    pe = t[k - 1] + CAP_PEDAL - 1 + (CAUDA_PEDAL if "Ç" in linhas[k - 1] else 0)
                    if topo - pe <= 2:   # o contorno de baixo da de cima (pe + 1) encosta no de cima desta (topo - 1)
                        falha(f"{tema.name}: {chave} in {lingua} ({texto!r}): line {k + 1} touches line {k} on the desk "
                              f"pedal ({len(linhas)} lines {t[k] - t[k - 1]} cells apart, with the accent and the cedilla; "
                              f"use a soft hyphen elsewhere or a shorter name)")
        # o passo do visor do Troca de voz numa linha do vidro (VISOR_EXTRA: a barra do OUVINDO com os blocos de 2 de
        # largura, a menor que a tela usa, e o visto do PRONTO)
        for chave, extra in VISOR_EXTRA.items():
            if chave in textos and linhas_do_pedal(textos[chave].replace("-", " "), pedal, visor_pedal - extra, 1) is None:
                falha(f"{tema.name}: {chave} in {lingua} ({textos[chave]!r}) doesn't fit the voice pedal display in the "
                      f"pixel font PEDAL (use a shorter word)")
    print(f"{tema.name}: {vistas} pixel art words checked against their fonts")


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

    # o navegador decide, o ?lang= passa na frente, e o que nao temos cai no ingles
    for pedida, accept, esperado in [(None, "pt-BR,pt;q=0.9,en;q=0.8", "pt_BR"), (None, "en-US,en;q=0.9", "en"),
                                     (None, "es,en;q=0.5", "en"), (None, "es,pt;q=0.5,en;q=0.7", "en"),
                                     (None, "es,pt;q=0.5", "pt_BR"), (None, "es", "en"), (None, "", "en"),
                                     ("pt_BR", "en-US", "pt_BR"), ("en", "pt-BR", "en"), ("xx", "pt-BR", "pt_BR")]:
        if (got := i18n.escolher(pedida, accept)) != esperado:
            falha(f"escolher({pedida!r}, {accept!r}) = {got!r}, expected {esperado!r}")
    for valor, lingua, esperado in [("Ritmelli", "pt_BR", "Ritmelli"), ({"en": "a", "pt_BR": "b"}, "pt_BR", "b"),
                                    ({"en": "a", "pt_BR": "b"}, "en", "a"), ({"en": "a"}, "pt_BR", "a"),
                                    ({"pt_BR": "b"}, "en", "b"), ({}, "en", "")]:
        if (got := i18n.na_lingua(valor, lingua)) != esperado:
            falha(f"na_lingua({valor!r}, {lingua!r}) = {got!r}, expected {esperado!r}")

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
        # um arquivo quebrado nao leva o outro junto
        (pasta / "i18n_pt_BR.properties").write_text("a.b=ação\na.b=de novo\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as log:
            html = i18n.injeta(i18n.MARCA, pasta, "pt_BR")
        if '"lingua":"en"' not in html or '"textos":{"a.b":"\\u003c/script>' not in html or "i18n_pt_BR" not in log.getvalue():
            falha(f"injeta with a broken pt_BR file should send the page in English and log it: {html!r}")
        (pasta / "i18n_pt_BR.properties").write_text("a.b=ação\n", encoding="utf-8")
        (pasta / "i18n_en.properties").write_text("quebrado\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as log:
            html = i18n.injeta(i18n.MARCA, pasta, "pt_BR")
        if '"lingua":"pt_BR"' not in html or '"textos":{"a.b":"ação"}' not in html or '"reserva":{}' not in html:
            falha(f"injeta with a broken en file should still send the pt_BR texts: {html!r}")
        with contextlib.redirect_stderr(io.StringIO()) as log:
            html = i18n.injeta(i18n.MARCA, pasta, "en")
        if '"textos":{}' not in html or "could not read" not in log.getvalue():
            falha("injeta with the page's only file broken should send no texts and log the error")

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
    check_name_reader()
    temas = [d for d in sorted((RAIZ / "themes").iterdir()) if (d / "i18n").is_dir()]
    if not temas:
        falha("no theme has an i18n/ folder")
    servidor, efeitos = chaves_do_servidor(), efeitos_do_servidor()
    print(f"server: {len(servidor)} message keys, {len(efeitos)} effect keys")
    for tema in temas:
        confere_tema(tema, servidor, efeitos)
        confere_meta(tema)
    # a galeria (a pagina inicial) tem a pasta i18n/ como um tema, mas nao mostra mensagem do servidor nem efeito
    confere_tema(RAIZ / "gallery", {}, set())
    print(f"{len(falhas)} failure(s)" if falhas else "all good")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
