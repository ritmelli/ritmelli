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
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

USAGE = """Proof that a change to a theme only moves code: the page put back together on two commits, compared.

The page is the index.html of the theme with every <script src>, <link rel="stylesheet"> and <!-- inline-script: -->
replaced by the text of its file. Every script and stylesheet, from a file or inline, sits between a line that opens it
([script NAME], [inline-script NAME], [script], [link NAME] or [style], with the tag's other attributes when it has
any) and a [/script] or [/style] line. <base> and <head> are git commits (the head defaults to the working tree).

Exit 0 when the head only moves code: the two pages are the same, or
- the markup is the same, line by line and in order, with every script and stylesheet in the same place in it;
- the head has the same scripts in the same order, each with the same attributes and the same strict mode;
- each script declares the same functions at its top level (they may move inside it: a script's function declarations
  exist before any of its statements runs, and only there);
- every other top-level statement of the base is in the head, in the same order and in the same script;
- every style rule of the base is in the head, in the same order, under the same stylesheet attributes and in a
  stylesheet of the same folder (it may move to another stylesheet there: its relative URLs keep their target).
Statements and rules are compared as syntax trees (tree-sitter), without comments and whitespace outside strings and
templates, so a block mark, a blank line or a new indentation is no change, while a space inside a template literal,
or a mark that joins two tokens, is. In CSS, whether a token follows whitespace counts too (calc() needs the spaces
around + and -). A part the CSS grammar does not know (an @container inside @media) is compared by its tokens too.
Declarations of one name keep their order (the last one wins). A script that V8, in a headless Chrome, does not
compile, or that tree-sitter does not parse, is a change. Anything else is a change, printed, and the exit is 1."""

INLINE_SCRIPT = re.compile(r"<!-- inline-script: ([\w-]+\.js) -->")
MARK = re.compile(r"/\*\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b[^*]*\*/")
SENTINEL = re.compile(r"^\x00(open (\d+)|close)\x00$")
JS_TYPES = (None, "", "text/javascript")
CSS_TYPES = (None, "", "text/css")
DECLARATIONS = ("function_declaration", "generator_function_declaration")
COMMENTS = ("comment", "html_comment")
STRICT = ("'use strict'", '"use strict"')
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
MIN_PIECE = 2


def reader(rev, theme):
    folder = f"themes/{theme}/"
    if rev is None:
        return lambda name: (RAIZ / folder / name).read_text(encoding="utf-8")

    def show(name):
        out = subprocess.run(["git", "-C", str(RAIZ), "show", f"{rev}:{folder}{name}"], capture_output=True)
        if out.returncode:
            raise SystemExit(f"{rev}: {folder}{name}: {out.stderr.decode(errors='replace').strip()}")
        return out.stdout.decode("utf-8").replace("\r\n", "\n")
    return show


@dataclass
class Block:
    kind: str
    header: str
    others: tuple
    code: bool
    folder: str = ""
    raw: list = field(default_factory=list)

    @property
    def text(self):
        return "\n".join(self.raw)


@dataclass
class Page:
    items: list
    blocks: list

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
        self.found, self.in_src = [], False

    def handle_starttag(self, tag, attrs):
        first = {}
        for name, value in attrs:
            first.setdefault(name, value)
        if tag == "script" and first.get("src"):
            self.in_src = True
            self.found.append(("script", first.pop("src"), first, self.getpos(), self.get_starttag_text()))
        elif tag in ("script", "style"):
            self.found.append((f"{tag}-open", None, first, self.getpos(), self.get_starttag_text()))
        elif tag == "link" and (first.get("rel") or "").lower() == "stylesheet" and first.get("href"):
            first.pop("rel")
            self.found.append(("link", first.pop("href"), first, self.getpos(), self.get_starttag_text()))

    def handle_endtag(self, tag):
        if tag == "script" and self.in_src:
            self.in_src = False
        elif tag in ("script", "style"):
            self.found.append((f"{tag}-close", None, {}, self.getpos(), None))

    def handle_comment(self, data):
        inlined = INLINE_SCRIPT.fullmatch(f"<!--{data}-->")
        if inlined:
            self.found.append(("inline-script", inlined.group(1), {}, self.getpos(), f"<!--{data}-->"))


def header(kind, name, others):
    title = " ".join(x for x in (kind, name) if x)
    return f"[{title}: {list(others.items())!r}]" if others else f"[{title}]"


def block_of(kind, name, others):
    if kind in ("link", "style-open"):
        return Block("style", header("link" if kind == "link" else "style", name, others), tuple(others.items()),
                     others.get("type") in CSS_TYPES, posixpath.dirname(name) if kind == "link" else "")
    return Block("script", header("script" if kind == "script-open" else kind, name, others), tuple(others.items()),
                 others.get("type") in JS_TYPES)


def assemble(read):
    page = read("index.html").replace("\r\n", "\n")
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
        if kind == "script" and page.startswith("</script>", end):
            end += len("</script>")
        body = f"\n\x00open {number[id(found)]}\x00\n"
        if kind in ("script", "inline-script", "link"):
            body += f"{read(name)}\n\x00close\x00\n"
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
    return Page(items, blocks)


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


def shape(node, src, spaced=None):
    if not node.children:
        token = node.type, src[node.start_byte:node.end_byte].decode("utf-8")
        if spaced is None:
            return token
        gap = CSS_COMMENT.sub("", src[spaced[0]:node.start_byte].decode("utf-8"))
        spaced[0] = node.end_byte
        return *token, any(x.isspace() for x in gap)
    return node.type, tuple(shape(x, src, spaced) for x in node.children if x.type not in COMMENTS)


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
                    src[name.start_byte:name.end_byte].decode("utf-8") if name else "")
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
        elif item[0] == "line" and item[2] is None and item[1].strip():
            out.append((("line", item[1].strip()), None, item[1].strip()))
    return out


def compare(a, b, compiles):
    report = Report()
    found = parsers()
    sides = []
    for page in (a, b):
        scripts = [n for n, x in enumerate(page.blocks) if x.kind == "script"]
        parsed = {n: parse(found[x.kind], x, n, compiles) for n, x in enumerate(page.blocks) if x.code}
        sides.append((scripts, parsed))
    (scripts_a, parsed_a), (scripts_b, parsed_b) = sides
    compare_sequences(report, "markup", markup(a), markup(b), lambda _: "the page", lambda _: "the page")
    if len(scripts_a) != len(scripts_b):
        report.changes.append(("scripts", f"the base has {len(scripts_a)} and the head {len(scripts_b)}", []))
    for page, parsed in ((a, parsed_a), (b, parsed_b)):
        report.changes += [("does not parse", page.blocks[n].header, []) for n, x in parsed.items() if x.error]
    for k, (x, y) in enumerate(zip(scripts_a, scripts_b)):
        bx, by = a.blocks[x], b.blocks[y]
        sx, sy = parsed_a[x].strict if x in parsed_a else None, parsed_b[y].strict if y in parsed_b else None
        if (bx.others, sx) != (by.others, sy):
            report.changes.append(("attributes or strict mode", f"script {k + 1}: {bx.header} (strict: {sx}) -> "
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
            units.append([((u.shape, page.blocks[n].others, page.blocks[n].folder) if kind == "style" else u.shape,
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
    a = assemble(reader(args.base, args.theme))
    b = assemble(reader(args.head, args.theme))
    print(f"{args.base}: {len(a.view())} lines; {args.head or 'working tree'}: {len(b.view())} lines")
    if a == b:
        print("the pages are equal")
        return 0
    report = compare(a, b, syntax([a, b]))
    print(f"{report.declarations} top-level function declaration(s) compared by script; {report.moved} block(s) "
          f"moved out of order; {len(report.changes)} change(s)")
    for kind, where, lines in report.changes:
        print(f"\n{kind}, {where}:")
        print("\n".join("  " + x for x in lines))
    print("\nthe head only moves code" if not report.changes else
          f"\nthe head does more than move code: {len(report.changes)} change(s)")
    return 0 if not report.changes else 1


if __name__ == "__main__":
    sys.exit(main())
