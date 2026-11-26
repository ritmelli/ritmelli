import argparse
import asyncio
import collections
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
trailing spaces, the blank lines and the bare <style> and </style> tags. Every script, from a file or inline, sits
between a line that opens it ([script NAME], [inline-script NAME] or [script], with the tag's other attributes when it
has any) and a [/script] line. <base> and <head> are git commits (the head defaults to the working tree).

Exit 0 when the head only moves code: the two pages are the same, or
- the head has the same scripts in the same order, each with the same attributes and the same strict mode;
- each script declares the same functions at its top level (they may move inside it: a script's function declarations
  exist before any of its lines runs, and only there);
- every other line of the base is in the head, in the same order and in the same script.
Anything else is a change, printed, and the exit is 1: a script more or less, a function declaration that went to
another script, a line moved out of order or to another script, a line with a new indentation (into a function), a line
gone or new. V8, in a headless Chrome, tells what a line diff cannot: a script's strict mode, its top-level function
declarations, and whether a line starts inside a template literal, where the spaces, a blank line and a block mark are
part of the string and are kept as they are."""

MARK = re.compile(r"/\*\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b[^*]*\*/")
INLINE_SCRIPT = re.compile(r"<!-- inline-script: ([\w-]+\.js) -->")
TAG = re.compile(r"^\s*</?(?:script|style)>\s*$")
SENTINEL = re.compile(r"^\x00(open (\d+)|close)\x00$")
END_OF_DECLARATION = re.compile(r"\s*;?\s*$")
JS_TYPES = (None, "", "text/javascript")
MIN_PIECE = 2
SUSPENDED = "(function* () {%s\n;eval('');\n})()"
SOURCE = "function () { return Function.prototype.toString.call(this); }"
SLOPPY_ONLY = "\n;with ({}) {}"


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
    raw: list = field(default_factory=list)

    @property
    def text(self):
        return "\n".join(self.raw)


@dataclass
class Page:
    items: list
    scripts: list

    def view(self, texts=None, skip=frozenset()):
        lines, content = [], []
        for item in self.items:
            if item[0] == "open":
                lines.append(self.scripts[item[1]].header)
                continue
            if item[0] == "close":
                lines.append("[/script]")
                continue
            _, raw, s, k = item
            text = None if (s, k) in skip else (texts or {}).get((s, k), shown(raw))
            if text is not None:
                lines.append(text)
                content.append((text, s, k))
        return lines, content


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
    items, current = [], None
    for line in page.split("\n"):
        sentinel = SENTINEL.match(line)
        if sentinel:
            current = int(sentinel.group(2)) if sentinel.group(2) else None
            items.append(("open", current) if current is not None else ("close", None))
        elif current is not None:
            items.append(("line", line, current, len(scripts[current].raw)))
            scripts[current].raw.append(line)
        else:
            items.append(("line", line, None, None))
    return Page(items, scripts)


def rebuild(read):
    return assemble(read).view()[0]


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
        self.debugging = False

    async def compiles(self, text):
        made = await self.tab.cmd("Runtime.compileScript", expression=text, sourceURL="", persistScript=False)
        return "exceptionDetails" not in made

    async def starts_inside(self, text, line):
        lines = text.split("\n")

        def marked(mark):
            return "\n".join(lines[:line] + [mark + lines[line]] + lines[line + 1:])
        return await self.compiles(marked("#1")) and await self.compiles(marked("*/#1"))

    async def strict(self, text):
        return not await self.compiles(text + SLOPPY_ONLY)

    async def code_at(self, text, offset):
        return not await self.compiles(text[:offset] + "#1" + text[offset:])

    async def statements(self, lines):
        if not self.debugging:
            await self.tab.cmd("Debugger.enable")
            self.debugging = True
        made = await self.tab.cmd("Runtime.compileScript", expression="\n".join(text for text, _ in lines),
                                  sourceURL="", persistScript=True)
        if "scriptId" not in made:
            return None
        found = await self.tab.cmd("Debugger.getPossibleBreakpoints", restrictToFunction=True,
                                   start={"scriptId": made["scriptId"], "lineNumber": 0, "columnNumber": 0})
        return [(lines[x["lineNumber"]][1], x["columnNumber"], x.get("type")) for x in found["locations"]]

    async def declarations(self, text):
        made = await self.tab.cmd("Runtime.evaluate", expression=SUSPENDED % text)
        if "exceptionDetails" in made:
            return []
        internal = (await self.tab.cmd("Runtime.getProperties", objectId=made["result"]["objectId"],
                                       ownProperties=True)).get("internalProperties", [])
        scopes = next(p["value"]["objectId"] for p in internal if p["name"] == "[[Scopes]]")
        chain = (await self.tab.cmd("Runtime.getProperties", objectId=scopes, ownProperties=True))["result"]
        local = next(s["value"]["objectId"] for s in chain if s.get("value", {}).get("description") == "Local")
        names = (await self.tab.cmd("Runtime.getProperties", objectId=local, ownProperties=True))["result"]
        return [(await self.tab.cmd("Runtime.callFunctionOn", objectId=p["value"]["objectId"],
                                    functionDeclaration=SOURCE, returnByValue=True))["result"]["value"]
                for p in names if p.get("value", {}).get("type") == "function" and p["name"] != "arguments"]


@dataclass
class Facts:
    strict: object = None
    spans: list = field(default_factory=list)
    inside: dict = None


async def facts_of(v8, script):
    text = script.text
    if not script.js:
        return Facts(inside={})
    if not await v8.compiles(text):
        return Facts(strict="a script that does not compile")
    spans = []
    for source in await v8.declarations(text):
        if text.count(source) != 1:
            continue
        start = text.index(source)
        end = start + len(source)
        line_end = text.find("\n", end)
        if text[text.rfind("\n", 0, start) + 1:start].strip() \
                or not END_OF_DECLARATION.fullmatch(text[end:line_end if line_end >= 0 else len(text)]):
            continue
        spans.append((text.count("\n", 0, start), text.count("\n", 0, end)))
    return Facts(await v8.strict(text), sorted(spans), {})


async def starts_inside(v8, script, facts, line):
    if facts.inside is None:
        return True
    if not script.js or line >= len(script.raw):
        return False
    if line not in facts.inside:
        facts.inside[line] = await v8.starts_inside(script.text, line)
    return facts.inside[line]


async def texts_of(v8, page, facts):
    texts = {}
    for s, script in enumerate(page.scripts):
        if not script.js:
            continue
        offset = 0
        for k, raw in enumerate(script.raw):
            text = raw
            if (not raw.strip() or raw != raw.rstrip() or MARK.search(raw)) \
                    and not await starts_inside(v8, script, facts[s], k + 1):
                for mark in reversed(list(MARK.finditer(raw))):
                    if facts[s].inside is not None and await v8.code_at(script.text, offset + mark.start()):
                        text = text[:mark.start()] + text[mark.end():]
                text = text.rstrip() if text.strip() else None
            texts[(s, k)] = text
            offset += len(raw) + 1
    return texts


async def joins_hold(v8, script, f):
    if not script.js or not f.spans or f.inside is None:
        return True
    starts = {first: last for first, last in f.spans}
    with_holes, without, k = [], [], 0
    while k < len(script.raw):
        if k in starts:
            with_holes.append((";", None))
            k = starts[k] + 1
            continue
        line = (script.raw[k], k)
        with_holes.append(line)
        without.append(line)
        k += 1
    return await v8.statements(with_holes) == await v8.statements(without)


def declared(page, facts, texts):
    found = collections.defaultdict(collections.Counter)
    for s, f in enumerate(facts):
        for first, last in f.spans:
            found[s][tuple(text for k in range(first, last + 1) if (text := texts.get((s, k))) is not None)] += 1
    return found


def shown(raw):
    text = MARK.sub("", raw).rstrip()
    return text if text.strip() and not TAG.match(text) else None


@dataclass
class Report:
    moved: list = field(default_factory=list)
    declarations: int = 0
    changes: list = field(default_factory=list)


def title(page, s):
    return page.scripts[s].header if s is not None else "the page"


async def compare(a, b, v8):
    report = Report()
    facts = ([await facts_of(v8, x) for x in a.scripts], [await facts_of(v8, x) for x in b.scripts])
    texts = (await texts_of(v8, a, facts[0]), await texts_of(v8, b, facts[1]))
    skip = tuple({(s, k) for s, f in enumerate(side) for first, last in f.spans for k in range(first, last + 1)}
                 for side in facts)
    ca, cb = a.view(texts[0], skip[0])[1], b.view(texts[1], skip[1])[1]
    if len(a.scripts) != len(b.scripts):
        report.changes.append(("scripts", f"the base has {len(a.scripts)} and the head {len(b.scripts)}", []))
    for s, (x, y) in enumerate(zip(a.scripts, b.scripts)):
        if (x.others, facts[0][s].strict) != (y.others, facts[1][s].strict):
            report.changes.append(("attributes or strict mode", f"script {s + 1}: {x.header} (strict: "
                                   f"{facts[0][s].strict}) -> {y.header} (strict: {facts[1][s].strict})", []))
    for side, page in ((0, a), (1, b)):
        for s, script in enumerate(page.scripts):
            if not await joins_hold(v8, script, facts[side][s]):
                report.changes.append(("declaration between lines that join", f"{('base', 'head')[side]}, "
                                       f"{script.header}: without its function declarations the script's "
                                       "statements change", []))
    ours, theirs = declared(a, facts[0], texts[0]), declared(b, facts[1], texts[1])
    report.declarations = sum(sum(c.values()) for c in ours.values())
    for s in sorted(set(ours) | set(theirs)):
        for lines in (ours[s] - theirs[s]).elements():
            report.changes.append(("declaration left its script", title(a, s), list(lines)))
        for lines in (theirs[s] - ours[s]).elements():
            report.changes.append(("declaration came into the script", title(b, s), list(lines)))
    moved, removed, added = split_moves([x[0] for x in ca], [x[0] for x in cb])
    kept = (set(), set())
    others = ({line.strip() for _, line in added}, {line.strip() for _, line in removed})
    for side, page, lines, rows in ((0, a, ca, removed), (1, b, cb, added)):
        for index, line in rows:
            _, s, k = lines[index]
            if s is not None and line.strip() in others[side] and line != line.strip() \
                    and await starts_inside(v8, page.scripts[s], facts[side][s], k):
                kept[side].add(index)
    reindented, removed, added = split_reindented(removed, added, kept)
    blocks = [("equal", list(zip(range(i1, i2), range(j1, j2))))
              for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [x[0] for x in ca], [x[0] for x in cb],
                                                                 autojunk=False).get_opcodes() if tag == "equal"]
    blocks += [("moved", [(i + k, j + k) for k in range(len(run))]) for run, i, j in moved]
    for kind, pairs in blocks:
        if kind == "moved":
            report.moved.append(pairs)
            report.changes.append(("moved out of order", f"base line {pairs[0][0] + 1} -> head line {pairs[0][1] + 1}",
                                   [ca[i][0] for i, _ in pairs]))
            continue
        run = []
        for i, j in pairs + [(None, None)]:
            if run and (i is None or (ca[i][1], cb[j][1]) != (ca[run[0][0]][1], cb[run[0][1]][1])):
                sa, sb = ca[run[0][0]][1], cb[run[0][1]][1]
                if sa != sb:
                    report.changes.append(("moved to another script", f"base line {run[0][0] + 1} -> head line "
                                           f"{run[0][1] + 1}, {title(a, sa)} -> {title(b, sb)}",
                                           [ca[x][0] for x, _ in run]))
                run = []
            if i is not None:
                run.append((i, j))
    report.changes += [("moved with a new indentation", f"base line {i + 1} -> head line {j + 1}", run)
                       for run, i, j in reindented]
    report.changes += [("gone", f"base line {i + 1}", [line]) for i, line in removed]
    report.changes += [("new", f"head line {j + 1}", [line]) for j, line in added]
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
    args = ap.parse_args(argv)
    a = assemble(reader(args.base, args.theme))
    b = assemble(reader(args.head, args.theme))
    print(f"{args.base}: {len(a.view()[0])} lines; {args.head or 'working tree'}: {len(b.view()[0])} lines")
    if a.items == b.items and a.scripts == b.scripts:
        print("the pages are equal")
        return 0
    report = with_v8(lambda v8: compare(a, b, v8))
    print(f"{report.declarations} top-level function declaration(s) compared by script; {len(report.moved)} block(s) "
          f"moved out of order; {len(report.changes)} change(s)")
    for kind, where, lines in report.changes:
        print(f"\n{kind}, {where}:")
        print("\n".join("  " + x for x in lines))
    print("\nthe head only moves code" if not report.changes else
          f"\nthe head does more than move code: {len(report.changes)} change(s)")
    return 0 if not report.changes else 1


if __name__ == "__main__":
    sys.exit(main())
