import argparse
import asyncio
import difflib
import importlib
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
replaced by the text of its file (a stylesheet after a line with the tag's other attributes as the parser read them,
when it has any), without the block marks (/* NAME-INICIO */, /* NAME-FIM */, /* name:inicio */, /* name:fim */), the
blank lines and the bare <style> and </style> tags, and with each 'use strict'; line as [strict]. Every script, from a
file or inline, sits between a line that opens it ([script NAME], [inline-script NAME] or [script], with the tag's
other attributes when it has any) and a [/script] line, so merging two scripts or splitting one shows. <base> and
<head> are git commits (the head defaults to the working tree).

Exit 0 when the head only moves code: the two pages are the same, or every line of the base is in the head, in the
same order and in the script that matches its own (the one that holds most of its lines, with the same attributes and
the same [strict]), except blocks that only declare functions, which may go anywhere between scripts of the same
[strict]. Anything else is a change, printed, and the exit is 1: a block moved out of order or to another script, a
line with a new indentation (into a function), a line gone or new, a script whose attributes changed. Whether a block
only declares functions, and whether a new indentation falls inside a template literal (where the spaces are part of
the string, so the line is gone and new rather than moved), are asked of V8, in a headless Chrome."""

MARK = re.compile(r"/\*\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b[^*]*\*/")
INLINE_SCRIPT = re.compile(r"<!-- inline-script: ([\w-]+\.js) -->")
TAG = re.compile(r"^\s*</?(?:script|style)>\s*$")
SENTINEL = re.compile(r"^\x00(open (\d+)|close)\x00$")
JS_TYPES = (None, "", "text/javascript")
MIN_PIECE = 2
SUSPENDED = "(function* () {%s\n;eval('');\n})()"
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
SOURCE = "function () { return Function.prototype.toString.call(this); }"


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
class Script:
    header: str
    others: tuple
    js: bool
    code: list = field(default_factory=list)


@dataclass
class Page:
    lines: list
    code: list
    owner: list
    scripts: list

    def strict(self, s):
        first = self.scripts[s].code[:1]
        return bool(first) and self.code[first[0]] == "[strict]"

    def text(self, s):
        return "\n".join("'use strict';" if self.code[i] == "[strict]" else self.code[i] for i in self.scripts[s].code)


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
        elif tag == "script":
            self.found.append(("open", None, first, self.getpos(), self.get_starttag_text()))
        elif tag == "link" and (first.get("rel") or "").lower() == "stylesheet" and first.get("href"):
            first.pop("rel")
            self.found.append(("link", first.pop("href"), first, self.getpos(), self.get_starttag_text()))

    def handle_endtag(self, tag):
        if tag == "script" and self.in_src:
            self.in_src = False
        elif tag == "script":
            self.found.append(("close", None, {}, self.getpos(), None))

    def handle_comment(self, data):
        inlined = INLINE_SCRIPT.fullmatch(f"<!--{data}-->")
        if inlined:
            self.found.append(("inline-script", inlined.group(1), {}, self.getpos(), f"<!--{data}-->"))


def header(kind, name, others):
    title = " ".join(x for x in (kind, name) if x)
    return f"[{title}: {list(others.items())!r}]" if others else f"[{title}]"


def assemble(read):
    page = read("index.html").replace("\r\n", "\n")
    parser = _FileTags()
    parser.feed(page)
    parser.close()
    line_starts = [0]
    for line in page.split("\n"):
        line_starts.append(line_starts[-1] + len(line) + 1)
    opened = [x for x in parser.found if x[0] in ("script", "inline-script", "open")]
    scripts = [Script(header("script" if kind == "open" else kind, name, others), tuple(others.items()),
                      others.get("type") in JS_TYPES) for kind, name, others, _, _ in opened]
    number = {id(x): n for n, x in enumerate(opened)}
    for found in reversed(parser.found):
        kind, name, others, (line, column), text = found
        begin = line_starts[line - 1] + column
        if kind == "close":
            end = page.index(">", begin) + 1
            page = page[:begin] + "\n\x00close\x00\n" + page[end:]
            continue
        end = begin + len(text)
        if kind == "script" and page.startswith("</script>", end):
            end += len("</script>")
        if kind == "link":
            body = (f"\n{header('link', name, others)}" if others else "") + "\n" + read(name) + "\n"
        elif kind == "open":
            body = f"\n\x00open {number[id(found)]}\x00\n"
        else:
            body = f"\n\x00open {number[id(found)]}\x00\n{read(name)}\n\x00close\x00\n"
        page = page[:begin] + body + page[end:]
    lines, code, owner, current = [], [], [], None
    for line in page.split("\n"):
        sentinel = SENTINEL.match(line)
        if sentinel:
            current = int(sentinel.group(2)) if sentinel.group(2) else None
            lines.append(scripts[current].header if current is not None else "[/script]")
            continue
        line = MARK.sub("", line).rstrip()
        if not line.strip() or TAG.match(line):
            continue
        line = "[strict]" if line.strip() == "'use strict';" else line
        lines.append(line)
        if current is not None:
            scripts[current].code.append(len(code))
        code.append(line)
        owner.append(current)
    return Page(lines, code, owner, scripts)


def rebuild(read):
    return assemble(read).lines


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


def split_reindented(removed, added, kept=(frozenset(), frozenset())):
    a = [line if i in kept[0] else line.strip() for i, line in removed]
    b = [line if j in kept[1] else line.strip() for j, line in added]
    moved, gone, new = split_moves(a, b)
    moved += [(a[i1:i2], i1, j1) for tag, i1, i2, j1, _ in difflib.SequenceMatcher(None, a, b, autojunk=False)
              .get_opcodes() if tag == "equal"]
    still_gone, still_new = {i for i, _ in gone}, {j for j, _ in new}
    return ([(run, removed[i][0], added[j][0]) for run, i, j in moved],
            [x for k, x in enumerate(removed) if k in still_gone], [x for k, x in enumerate(added) if k in still_new])


class V8:
    def __init__(self, tab):
        self.tab = tab

    async def compiles(self, text):
        made = await self.tab.cmd("Runtime.compileScript", expression=text, sourceURL="", persistScript=False)
        return "exceptionDetails" not in made

    async def indentation_matters(self, text, line):
        lines = text.split("\n")

        def marked(mark):
            return "\n".join(lines[:line] + [mark + lines[line]] + lines[line + 1:])
        if not await self.compiles(text):
            return True
        if not await self.compiles(marked("#1")):
            return False
        return await self.compiles(marked("*/#1"))

    async def declares_only(self, text, strict):
        made = await self.tab.cmd("Runtime.evaluate",
                                  expression=SUSPENDED % (("'use strict';\n" if strict else "") + text))
        if "exceptionDetails" in made:
            return False
        internal = (await self.tab.cmd("Runtime.getProperties", objectId=made["result"]["objectId"],
                                       ownProperties=True)).get("internalProperties", [])
        scopes = next(p["value"]["objectId"] for p in internal if p["name"] == "[[Scopes]]")
        chain = (await self.tab.cmd("Runtime.getProperties", objectId=scopes, ownProperties=True))["result"]
        local = next(s["value"]["objectId"] for s in chain if s.get("value", {}).get("description") == "Local")
        names = (await self.tab.cmd("Runtime.getProperties", objectId=local, ownProperties=True))["result"]
        rest = text
        for p in names:
            value = p.get("value", {})
            if value.get("type") != "function" or p["name"] == "arguments":
                continue
            source = (await self.tab.cmd("Runtime.callFunctionOn", objectId=value["objectId"],
                                         functionDeclaration=SOURCE, returnByValue=True))["result"]["value"]
            if source not in rest:
                return False
            rest = rest.replace(source, "", 1)
        return not COMMENT.sub("", rest).strip(" \t\n;")


@dataclass
class Report:
    moved: list = field(default_factory=list)
    declarations: list = field(default_factory=list)
    changes: list = field(default_factory=list)


def segments(page_a, page_b, pairs):
    run = []
    for i, j in pairs:
        if run and (page_a.owner[i], page_b.owner[j]) != (page_a.owner[run[-1][0]], page_b.owner[run[-1][1]]):
            yield run
            run = []
        run.append((i, j))
    if run:
        yield run


async def compare(a, b, v8):
    report = Report()
    moved, removed, added = split_moves(a.code, b.code)
    kept = (set(), set())
    others = ({line.strip() for _, line in added}, {line.strip() for _, line in removed})
    for side, page, rows in ((0, a, removed), (1, b, added)):
        for index, line in rows:
            s = page.owner[index]
            if s is not None and page.scripts[s].js and line.strip() in others[side] and line != line.strip():
                if await v8.indentation_matters(page.text(s), page.scripts[s].code.index(index)):
                    kept[side].add(index)
    reindented, removed, added = split_reindented(removed, added, kept)
    blocks = [("equal", list(zip(range(i1, i2), range(j1, j2))))
              for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a.code, b.code, autojunk=False).get_opcodes()
              if tag == "equal"]
    blocks += [("moved", [(i + k, j + k) for k in range(len(run))]) for run, i, j in moved]
    pieces = [(kind, run) for kind, pairs in blocks for run in segments(a, b, pairs)]
    weight = {}
    for kind, run in pieces:
        edge = (a.owner[run[0][0]], b.owner[run[0][1]])
        if kind == "equal" and None not in edge:
            weight[edge] = weight.get(edge, 0) + len(run)
    main = {edge for edge in weight
            if edge == max((e for e in weight if e[0] == edge[0]), key=lambda e: (weight[e], -e[1]))
            and edge == max((e for e in weight if e[1] == edge[1]), key=lambda e: (weight[e], -e[0]))}
    for kind, run in pieces:
        sa, sb = a.owner[run[0][0]], b.owner[run[0][1]]
        lines = [a.code[i] for i, _ in run]
        where = f"base line {run[0][0] + 1} -> head line {run[0][1] + 1}"
        if kind == "equal" and (sa, sb) in main | {(None, None)}:
            continue
        if kind == "moved":
            report.moved.append((lines, where))
        title = "moved out of order" if kind == "moved" else "moved to another script"
        if sa is not None and sb is not None and a.scripts[sa].js and b.scripts[sb].js \
                and a.strict(sa) == b.strict(sb) \
                and await v8.declares_only("\n".join("'use strict';" if x == "[strict]" else x for x in lines),
                                           a.strict(sa)):
            report.declarations.append((lines, where))
        else:
            report.changes.append((f"{title}, {where}" + (f" ({a.scripts[sa].header if sa is not None else 'markup'}"
                                                          f" -> {b.scripts[sb].header if sb is not None else 'markup'})"
                                                          if kind != "moved" else ""), lines))
    for sa, sb in sorted(main):
        if (a.scripts[sa].others, a.strict(sa)) != (b.scripts[sb].others, b.strict(sb)):
            report.changes.append((f"a script changed its attributes or [strict]: {a.scripts[sa].header} -> "
                                   f"{b.scripts[sb].header}", []))
    report.changes += [(f"moved with a new indentation, base line {i + 1} -> head line {j + 1}", run)
                       for run, i, j in reindented]
    report.changes += [(f"gone, base line {i + 1}", [line]) for i, line in removed]
    report.changes += [(f"new, head line {j + 1}", [line]) for j, line in added]
    return report


def with_v8(work):
    missing_script = importlib.import_module("missing_script")

    async def run(tab):
        return await work(V8(tab))
    return asyncio.run(missing_script.with_tab(types.SimpleNamespace(base="http://127.0.0.1:9"), run))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    ap.add_argument("--theme", default="ritmelli")
    ap.add_argument("--show", action="store_true", help="print the moved blocks too")
    args = ap.parse_args(argv)
    a = assemble(reader(args.base, args.theme))
    b = assemble(reader(args.head, args.theme))
    print(f"{args.base}: {len(a.lines)} lines; {args.head or 'working tree'}: {len(b.lines)} lines")
    if a.lines == b.lines:
        print("the pages are equal")
        return 0
    report = with_v8(lambda v8: compare(a, b, v8))
    print(f"{len(report.moved)} block(s) moved ({sum(len(r) for r, _ in report.moved)} lines), "
          f"{len(report.declarations)} of them only declaring functions; {len(report.changes)} change(s)")
    if args.show:
        for lines, where in report.declarations:
            print(f"\nonly declares functions, {where}:")
            print("\n".join("  " + x for x in lines))
    for title, lines in report.changes:
        print(f"\n{title}:")
        print("\n".join("  " + x for x in lines))
    print("\nthe head only moves code" if not report.changes else
          f"\nthe head does more than move code: {len(report.changes)} change(s)")
    return 0 if not report.changes else 1


if __name__ == "__main__":
    sys.exit(main())
