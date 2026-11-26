import argparse
import asyncio
import collections
import difflib
import importlib
import posixpath
import re
import subprocess
import sys
import types
from dataclasses import dataclass, field
from html.entities import html5
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

USAGE = """Proof that a change to a theme only moves code: the page put back together on two commits, compared.

The page is the index.html of the theme with every <!-- inline-script: --> made a <script> with the text of its file,
and every <script src> and <link rel="stylesheet"> replaced by the text of the file the
browser requests (the path of the URL, without the query and the fragment). Every script and stylesheet sits between a
line that opens it ([script NAME], [inline-script NAME], [script], [link NAME] or [style], with the tag's other
attributes when it has any) and a [/script] or [/style] line. <base> and <head> are git commits (the head defaults to
the working tree).

The tool refuses what the build refuses (index.html goes through theme_page.strict first), and then judges only a page
in a strict form of its own that the browser reads one way: text with no < between tags, start tags with name="value"
attributes (or a bare name), each once and in lower case outside <svg>, separated by ASCII spaces, end tags </name>,
comments <!-- ... --> with no -- inside, and <!doctype html>. The elements are the ones the theme and the gallery use,
one list for HTML and one inside <svg>. A <script> or <style> ends at its first </script> or </style>, with no <!-- in a
script and no text in a <script src>; the server puts every linked file inline, so a script file holds no </script or
<!-- and starts with no #!, and a sheet file holds no </style and passes the build's sheet check
(theme_page.sheet_problem: no @import, and outside the page's folder only plain url() values that are not relative). A
<title>, <iframe> or <select> holds no <. A script src and a stylesheet href (with rel="stylesheet" alone) are plain
paths inside the theme, like gerado/base.css, or /t/<theme>/ and a plain path, read from that theme's folder. Anything
else, and <script/>, <style/>, a <base>, a preload or prefetch <link>, a srcdoc, a NUL in a value, a & in a rel, type or
as, a & that is no whole reference in a value, a script type that is not JavaScript or JSON, an @import, @namespace or
@scope in a sheet (even escaped or in a comment), or a linked or inlined file that is not in the theme, exits 3, naming
the file (and, in index.html, the line and the place). In a sheet, only CSS whitespace and comments may sit between and
around the rules.

Exit 0 when the head only moves code: the two pages are the same, or
- every file of the theme that the page does not read (images, fonts) has the same content;
- the markup is the same, line by line and in order, with every script and stylesheet in the same place in it;
- the head has the same scripts in the same order, each loaded the same way (inline or from the same file), with the
  same attributes and the same strict mode;
- each script declares the same functions at its top level (they may move inside it: a script's function declarations
  exist before any of its statements runs, and only there), and the declarations of one name keep their order (the
  last one wins);
- every other top-level statement of the base is in the head, in the same order and in the same script;
- every style rule of the base is in the head, in the same order, under the same stylesheet attributes, in a
  stylesheet of the same folder and extension and inline or from a file as before (it may move to another linked
  stylesheet there: its relative URLs keep their target) and with the same scripts before its stylesheet
  (a script sees the rules of the stylesheets before it);
- the translation lines the server puts in the page (the i18n folder, for a page with the i18n mark) are the same,
  in the same order and as many times, split and trimmed as i18n.ler splits and trims them.
Statements and rules are compared as syntax trees (tree-sitter), with the text of every node that no child covers,
without comments and whitespace outside strings and templates: a block mark, a blank line or a new indentation is no
change, while a space inside a template literal, or a mark that joins two tokens, is. In CSS, whether a token follows
whitespace, a comment or nothing counts too (calc() needs the spaces around + and -, and a comment splits 14/**/px),
and a part the CSS grammar does not know (an @container inside @media) is compared by its tokens. A script that V8,
in a headless Chrome, does not compile, or that tree-sitter does not parse, is a change. Anything else is a change,
printed, and the exit is 1."""

INLINE_SCRIPT = re.compile(r"<!-- inline-script: ([\w-]+\.js) -->")
INLINED = "data-theme-rebuild-inline-script"
CANNOT_JUDGE = 3
TAG = r"[A-Za-z][A-Za-z0-9-]*"
START_TAG = re.compile(rf'<({TAG})((?:[ \t\n]+[A-Za-z][A-Za-z0-9_:.-]*(?:="[^"]*")?)*)[ \t\n]*(/?)>')
END_TAG = re.compile(rf"</({TAG})>")
COMMENT_TAG = re.compile(r"<!--(?![>-])((?:(?!--).)*)-->", re.S)
DOCTYPE = re.compile(r"<!doctype html>", re.I)
ATTRIBUTE = re.compile(r'([A-Za-z][A-Za-z0-9_:.-]*)(?:="([^"]*)")?')
SCRIPT_TYPES = ("", "text/javascript", "application/json")
CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|(.))", re.S)
PLAIN_PATH = re.compile(r"(?:/t/[A-Za-z0-9_-]+/)?[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.[A-Za-z0-9]+")
WHOLE_REFERENCE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);")
TEXT_ONLY = ("title", "iframe")
HTML_ELEMENTS = ("a", "b", "body", "button", "canvas", "dialog", "div", "form", "h1", "h2", "h3", "head", "header",
                 "html", "iframe", "input", "kbd", "label", "li", "link", "main", "meta", "ol", "output", "p", "script",
                 "section", "select", "small", "span", "style", "svg", "title", "ul")
SVG_ELEMENTS = ("circle", "g", "mask", "path", "rect")
TRAILING_SPACE = re.compile(r"(?<!\\)\s+$")
CSS_SPACES = re.compile(r"[ \t\n\r\f]+")
HTML_SPACE = " \t\n\r\f"
MARK = re.compile(r"/\*\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b[^*]*\*/")
SENTINEL = re.compile(r"^\x00(open (\d+)|close)\x00$")
JS_TYPES = ("", "text/javascript")
CSS_TYPES = ("", "text/css")
DECLARATIONS = ("function_declaration", "generator_function_declaration")
COMMENTS = ("comment", "html_comment")
RESTRICTED = ("return_statement", "break_statement", "continue_statement", "throw_statement", "yield_expression",
              "update_expression", "arrow_function", "function_declaration", "function_expression",
              "generator_function_declaration", "generator_function")
LINE_TERMINATORS = (b"\n", "\u2028".encode("utf-8"), "\u2029".encode("utf-8"))
JS_ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})")
STRICT = ("'use strict'", '"use strict"')
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
MIN_PIECE = 2


class Doubt(Exception):
    pass


def strict(html, name):
    def refuse(at, why):
        raise Doubt(f"{name}, line {html.count(chr(10), 0, at) + 1}: {why}: {html[at:at + 60]!r}")

    at, foreign = 0, []
    while (at := html.find("<", at)) >= 0:
        tag = next((m for m in (p.match(html, at) for p in (DOCTYPE, COMMENT_TAG, END_TAG, START_TAG)) if m), None)
        if tag is None:
            refuse(at, "not a tag of the strict form")
        if tag.re is COMMENT_TAG and "--!>" in tag.group(1):
            refuse(at, "a comment with --!>")
        if tag.re in (START_TAG, END_TAG) and tag.group(1) not in (SVG_ELEMENTS if foreign else HTML_ELEMENTS) and \
                not (foreign and tag.re is END_TAG and tag.group(1) == "svg"):
            refuse(at, f"an element the theme does not use {'inside <svg>' if foreign else 'in its HTML'}")
        if tag.re is END_TAG and tag.group(1) == "svg" and foreign:
            foreign.pop()
        if tag.re is START_TAG:
            element, pairs = tag.group(1), ATTRIBUTE.findall(tag.group(2))
            attributes = dict(pairs)
            if len({k.lower() for k, _ in pairs}) < len(pairs):
                refuse(at, "an attribute written twice")
            if element != "svg" and not foreign and any(k != k.lower() for k, _ in pairs):
                refuse(at, "an attribute name in capitals")
            if element == "base" or element == "link" and {"preload", "modulepreload", "prefetch"} & set(
                    attributes.get("rel", "").lower().split()):
                refuse(at, f"a <{element}> that changes or adds what the page fetches")
            if element == "svg" and not tag.group(3):
                foreign.append(element)
            if "srcdoc" in attributes or any("\0" in v for v in attributes.values()):
                refuse(at, "a srcdoc or a NUL in a value")
            if any("&" in attributes.get(k, "") for k in ("rel", "type", "as")):
                refuse(at, "a & in a rel, type or as")
            if element == "script" and type_of(attributes) not in SCRIPT_TYPES:
                refuse(at, "a script type that is not plain JavaScript or JSON (a module can import files)")
            if loose := [v for k, v in attributes.items() if "&" in WHOLE_REFERENCE.sub(known_reference, v)]:
                refuse(at, f"a & that is not a whole reference in {loose[0]!r}")
            sheet = element == "link" and "stylesheet" in attributes.get("rel", "").lower().split()
            if sheet and attributes["rel"] != "stylesheet":
                refuse(at, "a stylesheet link whose rel is not just stylesheet")
            address = attributes.get("src") if element == "script" else attributes.get("href") if sheet else None
            if address is not None and not PLAIN_PATH.fullmatch(address):
                refuse(at, "a file address that is not a plain path inside the theme (like gerado/base.css)")
            if element in ("script", "style", "select") + TEXT_ONLY:
                if tag.group(3):
                    refuse(at, f"a <{element}/>")
                close = html.find(f"</{element}>", tag.end())
                body = html[tag.end():close] if close >= 0 else ""
                if close < 0 or body_problem(element, body, "src" in attributes):
                    refuse(at, f"a <{element}> that does not end at its first </{element}>, with no other tag in it")
                at = close + len(f"</{element}>")
                continue
        at = tag.end()


def known_reference(m):
    return "" if m.group(0)[1] == "#" or m.group(0)[1:] in html5 else m.group(0)


def body_problem(element, body, from_file):
    if element == "script":
        return from_file and body or re.search(r"</\s*script|<!--", body, re.I)
    if element == "style":
        return re.search(r"</\s*style", body, re.I) or sheet_reaches_out(body)
    return "<" in body


def sheet_reaches_out(text):
    read = css_unescape(text).lower()
    return any(rule in read for rule in ("@import", "@namespace", "@scope"))


def css_unescape(text):
    return CSS_ESCAPE.sub(lambda m: chr(min(int(m.group(1), 16), 0xFFFD)) if m.group(1) else m.group(2), text)


def text_of(data):
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def theme_path(name, theme):
    return f"themes/{name[3:]}" if name.startswith("/t/") else f"themes/{theme}/{name}"


def reader(rev, theme):
    if rev is None:
        return lambda name: (text_of((RAIZ / theme_path(name, theme)).read_bytes())
                             if (RAIZ / theme_path(name, theme)).is_file() else None)

    def show(name):
        out = subprocess.run(["git", "-C", str(RAIZ), "show", f"{rev}:{theme_path(name, theme)}"], capture_output=True)
        return None if out.returncode else text_of(out.stdout)
    return show


def git(*args, given=None):
    out = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, input=given)
    if out.returncode:
        raise SystemExit(f"git {' '.join(args)}: {out.stderr.decode(errors='replace').strip()}")
    return out.stdout.decode("utf-8")


def listing(rev, theme):
    folder = f"themes/{theme}/"
    if rev is None:
        names = [x for x in git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", folder).split("\0")
                 if x and (RAIZ / x).is_file()]
        ids = git("hash-object", "--stdin-paths", given="\n".join(names).encode("utf-8")).split()
    else:
        rows = [x.split("\t", 1) for x in git("ls-tree", "-r", "-z", rev, "--", folder).split("\0") if x]
        names, ids = [path for _, path in rows], [meta.split()[2] for meta, _ in rows]
    return {name[len(folder):]: blob for name, blob in zip(names, ids)}


@dataclass
class Block:
    kind: str
    header: str
    others: tuple
    code: bool
    folder: str = ""
    source: tuple = ()
    raw: list = field(default_factory=list)

    @property
    def text(self):
        return "\n".join(self.raw)


@dataclass
class Page:
    items: list
    blocks: list
    texts: tuple = ()
    read: frozenset = frozenset()
    files: dict = field(default_factory=dict)

    def view(self):
        lines = []
        for item in self.items:
            if item[0] == "open":
                lines.append(self.blocks[item[1]].header)
            elif item[0] == "close":
                lines.append(f"[/{self.blocks[item[1]].kind}]")
            elif (text := MARK.sub("", item[1]).rstrip()).strip():
                lines.append(text)
        return lines


class _FileTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.found, self.in_src, self.open = [], False, []

    def handle_starttag(self, tag, attrs):
        first = {}
        for name, value in attrs:
            first.setdefault(name, value)
        if tag == "script" and first.get("src"):
            self.in_src = True
            self.found.append(("script", first.pop("src"), first, self.getpos(), self.get_starttag_text()))
        elif tag in ("script", "style"):
            name = first.pop(INLINED, None)
            self.open.append(tag)
            self.found.append(("inline-script" if name else f"{tag}-open", name, first, self.getpos(),
                               self.get_starttag_text()))
        elif tag == "link" and (first.get("rel") or "").lower() == "stylesheet" and first.get("href"):
            first.pop("rel")
            self.found.append(("link", first.pop("href"), first, self.getpos(), self.get_starttag_text()))

    def handle_endtag(self, tag):
        if tag == "script" and self.in_src:
            self.in_src = False
        elif self.open and self.open[-1] == tag:
            self.open.pop()
            self.found.append((f"{tag}-close", None, {}, self.getpos(), None))


def header(kind, name, others):
    title = " ".join(x for x in (kind, name) if x)
    return f"[{title}: {list(others.items())!r}]" if others else f"[{title}]"


def block_of(kind, name, others):
    if kind in ("link", "style-open"):
        return Block("style", header("link" if kind == "link" else "style", name, others), tuple(others.items()),
                     type_of(others) in CSS_TYPES, posixpath.dirname(name) if kind == "link" else "",
                     source=("file", posixpath.splitext(name)[1].lower()) if kind == "link"
                     else ("inline",))
    return Block("script", header("script" if kind == "script-open" else kind, name, others), tuple(others.items()),
                 type_of(others) in JS_TYPES, source=("file" if kind == "script" else "inline", name))


def type_of(attributes):
    return (attributes.get("type") or "").strip(" \t\n\r\f").lower()


def assemble(read, files=None, theme="ritmelli"):
    names = set()

    def need(name):
        names.add(name)
        if (text := read(name)) is None:
            raise SystemExit(f"{name}: not in the theme")
        return text

    def fetch(name):
        names.add(name.removeprefix(f"/t/{theme}/"))
        text = read(name)
        return text if text is None else text.removeprefix("\ufeff")
    html = need("index.html").removeprefix("\ufeff")
    strict(html, "index.html")
    if refused := from_root("theme_page").strict(html)[1]:
        raise Doubt(f"index.html, line {refused[0]}: {refused[2]}, which the server refuses")
    for marker in INLINE_SCRIPT.finditer(html):
        inlined = marker.group(1)
        if read(inlined) is None:
            raise Doubt(f"index.html, line {html.count(chr(10), 0, marker.start()) + 1}: the inline-script {inlined} is "
                        f"not in the theme")
        if body_problem("script", need(inlined), False):
            raise Doubt(f"{inlined}: a </script or a <!-- in a script the server puts inline")
    page = INLINE_SCRIPT.sub(lambda m: f'<script {INLINED}="{m.group(1)}">\n{need(m.group(1))}</script>', html)
    parser = _FileTags()
    parser.feed(page)
    parser.close()
    line_starts = [0]
    for line in page.split("\n"):
        line_starts.append(line_starts[-1] + len(line) + 1)
    opened = [x for x in parser.found if not x[0].endswith("-close")]
    blocks = [block_of(kind, name, others) for kind, name, others, _, _ in opened]
    number = {id(x): n for n, x in enumerate(opened)}
    for found in reversed(parser.found):
        kind, name, others, (line, column), text = found
        begin = line_starts[line - 1] + column
        if kind.endswith("-close"):
            end = page.index(">", begin) + 1
            page = page[:begin] + "\n\x00close\x00\n" + page[end:]
            continue
        end = begin + len(text)
        if kind == "script":
            end += len("</script>")
        body = f"\n\x00open {number[id(found)]}\x00\n"
        if kind in ("script", "link"):
            if (text := fetch(name)) is None:
                raise Doubt(f"{name}: the page links it, and it is not in the theme (the browser gets a 404)")
            if kind == "script" and body_problem("script", text, False):
                raise Doubt(f"{name}: a </script or a <!-- in a script the server puts inline")
            if kind == "script" and text.startswith("#!"):
                raise Doubt(f"{name}: a #! at its start, which only a script file read on its own allows")
            if kind == "link" and re.search(r"</\s*style", text, re.I):
                raise Doubt(f"{name}: a </style in a sheet the server puts inline")
            outside = posixpath.dirname(theme_path(name, theme)) != f"themes/{theme}"
            if kind == "link" and (problem := from_root("theme_page").sheet_problem(text, outside)):
                raise Doubt(f"{name}: {problem}, which the server refuses")
            if kind == "link" and sheet_reaches_out(text):
                raise Doubt(f"{name}: an @import, @namespace or @scope, even escaped or in a comment, which ties the "
                            f"sheet to something outside its rules")
            body += f"{text}\n\x00close\x00\n"
        page = page[:begin] + body + page[end:]
    items, current = [], []
    for line in page.split("\n"):
        sentinel = SENTINEL.match(line)
        if sentinel and sentinel.group(2):
            current.append(int(sentinel.group(2)))
            items.append(("open", current[-1]))
        elif sentinel:
            items.append(("close", current.pop()))
        elif current:
            items.append(("line", line, current[-1], len(blocks[current[-1]].raw)))
            blocks[current[-1]].raw.append(line)
        else:
            items.append(("line", line, None, None))
    texts = translations(need, html)
    return Page(items, blocks, texts, frozenset(names), files or {})


def from_root(module):
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    return importlib.import_module(module)


def translations(read, page):
    i18n = from_root("i18n")
    if i18n.MARCA not in page:
        return ()
    return tuple((language, tuple(TRAILING_SPACE.sub("", line.lstrip())
                                  for line in read(f"i18n/i18n_{language}.properties").splitlines()
                                  if line.strip() and not line.lstrip().startswith(("#", "!"))))
                 for language in i18n.LINGUAS)


def rebuild(read):
    return assemble(read).view()


def split_moves(a, b):
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    gone = [(i1, a[i1:i2]) for tag, i1, i2, _, _ in ops if tag in ("delete", "replace")]
    new = [(j1, b[j1:j2]) for tag, _, _, j1, j2 in ops if tag in ("insert", "replace")]
    moved, used, left = [], set(), set()

    def free_place_of(run):
        for k, (_, block) in enumerate(new):
            for pos in range(len(block) - len(run) + 1):
                if block[pos:pos + len(run)] == run and not any((k, pos + q) in used for q in range(len(run))):
                    return k, pos
        return None

    def take(run, i, k, pos):
        used.update((k, pos + q) for q in range(len(run)))
        moved.append((run, i, new[k][0] + pos))

    not_whole = []
    for i, run in sorted(gone, key=lambda x: -len(x[1])):
        place = free_place_of(run)
        if place:
            take(run, i, *place)
        else:
            not_whole.append((i, run))
    for i, run in not_whole:
        p = 0
        while p < len(run):
            for size in range(len(run) - p, MIN_PIECE - 1, -1):
                place = free_place_of(run[p:p + size])
                if place:
                    take(run[p:p + size], i + p, *place)
                    p += size
                    break
            else:
                left.add(i + p)
                p += 1
    removed = [(i, a[i]) for i in sorted(left)]
    added = [(j + p, line) for k, (j, block) in enumerate(new) for p, line in enumerate(block) if (k, p) not in used]
    for i, line in list(removed):
        twin = next((x for x in added if x[1] == line), None)
        if twin:
            removed.remove((i, line))
            added.remove(twin)
            moved.append(([line], i, twin[0]))
    return moved, removed, added


def parsers():
    import tree_sitter
    import tree_sitter_css
    import tree_sitter_javascript
    return {"script": tree_sitter.Parser(tree_sitter.Language(tree_sitter_javascript.language())),
            "style": tree_sitter.Parser(tree_sitter.Language(tree_sitter_css.language()))}


def token(kind, start, end, src, spaced):
    text = src[start:end].decode("utf-8")
    if spaced is None:
        return kind, text
    gap = src[spaced[0]:start].decode("utf-8")
    spaced[0] = end
    bare = CSS_SPACES.sub(" ", CSS_COMMENT.sub("", gap))
    return kind, text, bare or ("comment" if gap else "")


def own(start, end, src, spaced):
    if spaced is None:
        text = src[start:end].strip()
        return [("text", text.decode("utf-8"))] if text else []
    return [token("text", start + m.start(), start + m.end(), src, spaced) for m in re.finditer(rb"\S+", src[start:end])]


def shape(node, src, spaced=None):
    if not node.children:
        return token(node.type, node.start_byte, node.end_byte, src, spaced)
    parts, at = [], node.start_byte
    for child in node.children:
        parts += own(at, child.start_byte, src, spaced)
        if child.type not in COMMENTS:
            parts.append(shape(child, src, spaced))
        at = child.end_byte
    if node.type in RESTRICTED and (after := [x for x in node.children[1:] if x.type not in COMMENTS]):
        gap = src[node.children[0].end_byte:after[0].start_byte]
        parts.append(("line break", any(x in gap for x in LINE_TERMINATORS)))
    return node.type, tuple(parts + own(at, node.end_byte, src, spaced))


def syntax(pages):
    texts = sorted({x.text for page in pages for x in page.blocks if x.kind == "script" and x.code})
    missing_script = importlib.import_module("missing_script")

    async def run(tab):
        return {text: "exceptionDetails" not in await tab.cmd("Runtime.compileScript", expression=text, sourceURL="",
                                                                persistScript=False) for text in texts}
    return asyncio.run(missing_script.with_tab(types.SimpleNamespace(base="http://127.0.0.1:9"), run))


@dataclass
class Unit:
    shape: tuple
    where: int
    text: str
    name: str = ""


@dataclass
class Parsed:
    error: bool = False
    strict: bool = False
    declarations: list = field(default_factory=list)
    units: list = field(default_factory=list)


def parse(parser, block, n, compiles):
    src = block.text.encode("utf-8")
    tree = parser.parse(src)
    out = Parsed(error=block.kind == "script" and (tree.root_node.has_error or not compiles[block.text]))
    prologue = block.kind == "script"
    if block.kind == "style":
        edges = [0, *(x for node in tree.root_node.children for x in (node.start_byte, node.end_byte)), len(src)]
        out.error = any(src[a:b].strip(b" \t\n\r\f") for a, b in zip(edges[::2], edges[1::2]))
    for node in tree.root_node.children:
        if node.type in COMMENTS:
            continue
        text = src[node.start_byte:node.end_byte].decode("utf-8")
        named = [x for x in node.named_children if x.type not in COMMENTS]
        if prologue and node.type == "expression_statement" and len(named) == 1 and named[0].type == "string":
            out.strict = out.strict or src[named[0].start_byte:named[0].end_byte].decode("utf-8") in STRICT
        else:
            prologue = False
        name = node.child_by_field_name("name")
        unit = Unit(shape(node, src, [node.start_byte] if block.kind == "style" else None), n,
                    text.split("\n")[0][:120],
                    JS_ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)),
                                  src[name.start_byte:name.end_byte].decode("utf-8")) if name else "")
        (out.declarations if block.kind == "script" and node.type in DECLARATIONS else out.units).append(unit)
    return out


@dataclass
class Report:
    moved: int = 0
    declarations: int = 0
    changes: list = field(default_factory=list)


def compare_sequences(report, what, a, b, place_a, place_b):
    moved, removed, added = split_moves([x[0] for x in a], [x[0] for x in b])
    for run, i, j in moved:
        report.moved += 1
        report.changes.append(("moved out of order", f"{what}, base {i + 1} -> head {j + 1}",
                               [a[i + k][2] for k in range(len(run))]))
    pairs = [(i, j) for tag, i1, i2, j1, _ in difflib.SequenceMatcher(None, [x[0] for x in a], [x[0] for x in b],
                                                                      autojunk=False).get_opcodes()
             if tag == "equal" for i, j in zip(range(i1, i2), range(j1, j1 + i2 - i1))]
    for i, j in pairs:
        if a[i][1] != b[j][1]:
            report.changes.append(("moved to another script", f"{what}, base {i + 1} -> head {j + 1}, "
                                   f"{place_a(a[i][1])} -> {place_b(b[j][1])}", [a[i][2]]))
    report.changes += [("gone", f"{what}, base {i + 1} in {place_a(a[i][1])}", [a[i][2]]) for i, _ in removed]
    report.changes += [("new", f"{what}, head {j + 1} in {place_b(b[j][1])}", [b[j][2]]) for j, _ in added]


def markup(page):
    order = {"script": 0, "style": 0}
    out = []
    for item in page.items:
        if item[0] == "open":
            kind = page.blocks[item[1]].kind
            out.append(((kind, order[kind]), None, page.blocks[item[1]].header))
            order[kind] += 1
        elif item[0] == "line" and item[2] is None and item[1].strip(HTML_SPACE):
            out.append((("line", item[1].strip(HTML_SPACE)), None, item[1].strip(HTML_SPACE)))
    return out


def compare_files(report, a, b):
    for name in sorted((set(a.files) | set(b.files)) - a.read - b.read):
        if a.files.get(name) != b.files.get(name):
            kind = "file gone" if name not in b.files else "file new" if name not in a.files else "file changed"
            report.changes.append((kind, name, []))


def compare(a, b, compiles):
    report = Report()
    compare_files(report, a, b)
    found = parsers()
    sides = []
    for page in (a, b):
        scripts = [n for n, x in enumerate(page.blocks) if x.kind == "script"]
        parsed = {n: parse(found[x.kind], x, n, compiles) for n, x in enumerate(page.blocks) if x.code}
        sides.append((scripts, parsed))
    (scripts_a, parsed_a), (scripts_b, parsed_b) = sides
    compare_sequences(report, "markup", markup(a), markup(b), lambda _: "the page", lambda _: "the page")
    for (language, mine), (_, theirs) in zip(a.texts or [(None, ())] * len(b.texts), b.texts or [(None, ())] * len(a.texts)):
        gone, new = collections.Counter(mine) - collections.Counter(theirs), collections.Counter(theirs) - collections.Counter(mine)
        report.changes += [("translation gone", language, [x]) for x in gone.elements()]
        report.changes += [("translation new", language, [x]) for x in new.elements()]
        if mine != theirs and not gone and not new:
            report.changes.append(("translations in another order", language, []))
    if len(scripts_a) != len(scripts_b):
        report.changes.append(("scripts", f"the base has {len(scripts_a)} and the head {len(scripts_b)}", []))
    for page, parsed in ((a, parsed_a), (b, parsed_b)):
        report.changes += [("does not parse", page.blocks[n].header, []) for n, x in parsed.items() if x.error]
    for k, (x, y) in enumerate(zip(scripts_a, scripts_b)):
        bx, by = a.blocks[x], b.blocks[y]
        sx, sy = parsed_a[x].strict if x in parsed_a else None, parsed_b[y].strict if y in parsed_b else None
        if (bx.source, bx.others, sx) != (by.source, by.others, sy):
            report.changes.append(("script tag or strict mode", f"script {k + 1}: {bx.header} (strict: {sx}) -> "
                                   f"{by.header} (strict: {sy})", []))
        if not bx.code and [r.strip() for r in bx.raw if r.strip()] != [r.strip() for r in by.raw if r.strip()]:
            report.changes.append(("script content", f"script {k + 1}: {bx.header}", []))
        mine, theirs = collections.defaultdict(list), collections.defaultdict(list)
        for unit in (parsed_a.get(x) or Parsed()).declarations:
            mine[unit.name].append(unit)
        for unit in (parsed_b.get(y) or Parsed()).declarations:
            theirs[unit.name].append(unit)
        report.declarations += sum(len(v) for v in mine.values())
        for name in sorted(set(mine) | set(theirs)):
            before, after = [u.shape for u in mine[name]], [u.shape for u in theirs[name]]
            texts = {u.shape: u.text for u in mine[name] + theirs[name]}
            left, came = collections.Counter(before) - collections.Counter(after), collections.Counter(after) - collections.Counter(before)
            report.changes += [("declaration left its script", bx.header, [texts[s]]) for s in left.elements()]
            report.changes += [("declaration came into the script", by.header, [texts[s]]) for s in came.elements()]
            if before != after and not left and not came:
                report.changes.append(("declarations of one name in another order", f"{by.header}: {name}", []))
    for kind, what in (("script", "statement"), ("style", "style rule")):
        units = []
        for page, scripts, parsed in ((a, scripts_a, parsed_a), (b, scripts_b, parsed_b)):
            rank = {n: k for k, n in enumerate(scripts)}
            units.append([((u.shape, page.blocks[n].others, page.blocks[n].folder, page.blocks[n].source,
                             sum(x < n for x in scripts)) if kind == "style" else u.shape,
                           rank[n] if kind == "script" else None, u.text)
                          for n, p in sorted(parsed.items()) if page.blocks[n].kind == kind for u in p.units])
        compare_sequences(report, what, *units,
                          lambda k: a.blocks[scripts_a[k]].header if k is not None else "the stylesheets",
                          lambda k: b.blocks[scripts_b[k]].header if k is not None else "the stylesheets")
    return report


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    ap.add_argument("--theme", default="ritmelli")
    args = ap.parse_args(argv)
    try:
        a = assemble(reader(args.base, args.theme), listing(args.base, args.theme), args.theme)
        b = assemble(reader(args.head, args.theme), listing(args.head, args.theme), args.theme)
    except Doubt as unsure:
        print(f"cannot judge, the browser may read this otherwise: {unsure}")
        return CANNOT_JUDGE
    print(f"{args.base}: {len(a.view())} lines; {args.head or 'working tree'}: {len(b.view())} lines")
    return judge(a, b)


def judge(a, b, compiles=None, say=print):
    if a == b:
        say("the pages are equal")
        return 0
    report = compare(a, b, compiles or syntax([a, b]))
    say(f"{report.declarations} top-level function declaration(s) compared by script; {report.moved} block(s) "
        f"moved out of order; {len(report.changes)} change(s)")
    for kind, where, lines in report.changes:
        say(f"\n{kind}, {where}:")
        say("\n".join("  " + x for x in lines))
    say("\nthe head only moves code" if not report.changes else
          f"\nthe head does more than move code: {len(report.changes)} change(s)")
    return 0 if not report.changes else 1


if __name__ == "__main__":
    sys.exit(main())
