import argparse
import difflib
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

USAGE = """Proof that a change to a theme only moves code: the page put back together on two commits, compared.

The page is the index.html of the theme with every <script src>, <link rel="stylesheet"> and <!-- inline-script: -->
replaced by the text of its file (after a line with the tag's other attributes as the parser read them, when it has
any), without the block marks (/* NAME-INICIO */, /* NAME-FIM */, /* name:inicio */, /* name:fim */), the blank lines
and the bare <script>, <style>, </script> and </style> tags (one with attributes stays), and with each 'use strict';
line as [strict], so moving code into a new strict file shows one [strict] line more. <base> and <head> are git commits (the head defaults to the working tree). Exit 0 only
when the two pages are the same, line by line and in order. When they are not, the lines that differ are split into
the runs that only moved, whole or in pieces of MIN_PIECE lines or more (two blocks next to each other that went to two
files), the runs that moved with a new indentation (into a function), and the lines that are new or gone, which are
printed, and the exit is 1."""

MARK = re.compile(r"/\*\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b[^*]*\*/")
INLINE_SCRIPT = re.compile(r"<!-- inline-script: ([\w-]+\.js) -->")
TAG = re.compile(r"^\s*</?(?:script|style)>\s*$")
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


class _FileTags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.found = []

    def handle_starttag(self, tag, attrs):
        first = {}
        for name, value in attrs:
            first.setdefault(name, value)
        if tag == "script" and first.get("src"):
            self.found.append(("script", first.pop("src"), first, self.getpos(), self.get_starttag_text()))
        elif tag == "link" and (first.get("rel") or "").lower() == "stylesheet" and first.get("href"):
            first.pop("rel")
            self.found.append(("link", first.pop("href"), first, self.getpos(), self.get_starttag_text()))

    def handle_comment(self, data):
        inlined = INLINE_SCRIPT.fullmatch(f"<!--{data}-->")
        if inlined:
            self.found.append(("inline-script", inlined.group(1), {}, self.getpos(), f"<!--{data}-->"))


def rebuild(read):
    page = read("index.html").replace("\r\n", "\n")
    parser = _FileTags()
    parser.feed(page)
    parser.close()
    line_starts = [0]
    for line in page.split("\n"):
        line_starts.append(line_starts[-1] + len(line) + 1)
    for kind, name, others, (line, column), text in reversed(parser.found):
        begin = line_starts[line - 1] + column
        end = begin + len(text)
        if kind == "script" and page.startswith("</script>", end):
            end += len("</script>")
        head = f"\n[{kind} {name}: {list(others.items())!r}]" if others else ""
        page = page[:begin] + head + "\n" + read(name) + "\n" + page[end:]
    lines = []
    for line in page.split("\n"):
        line = MARK.sub("", line).rstrip()
        if not line.strip() or TAG.match(line):
            continue
        lines.append("[strict]" if line.strip() == "'use strict';" else line)
    return lines


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


def split_reindented(removed, added):
    a, b = [line.strip() for _, line in removed], [line.strip() for _, line in added]
    moved, gone, new = split_moves(a, b)
    moved += [(a[i1:i2], i1, j1) for tag, i1, i2, j1, _ in difflib.SequenceMatcher(None, a, b, autojunk=False)
              .get_opcodes() if tag == "equal"]
    still_gone, still_new = {i for i, _ in gone}, {j for j, _ in new}
    return ([(run, removed[i][0], added[j][0]) for run, i, j in moved],
            [x for k, x in enumerate(removed) if k in still_gone], [x for k, x in enumerate(added) if k in still_new])


def main(argv=None):
    ap = argparse.ArgumentParser(description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("head", nargs="?")
    ap.add_argument("--theme", default="ritmelli")
    ap.add_argument("--show", action="store_true", help="print the moved blocks too")
    args = ap.parse_args(argv)
    a = rebuild(reader(args.base, args.theme))
    b = rebuild(reader(args.head, args.theme))
    head = args.head or "working tree"
    print(f"{args.base}: {len(a)} lines; {head}: {len(b)} lines")
    if a == b:
        print("the pages are equal")
        return 0
    moved, removed, added = split_moves(a, b)
    reindented, removed, added = split_reindented(removed, added)
    print(f"{len(moved)} block(s) moved ({sum(len(r) for r, _, _ in moved)} lines), {len(reindented)} block(s) moved "
          f"with a new indentation ({sum(len(r) for r, _, _ in reindented)} lines), {len(removed)} line(s) gone, "
          f"{len(added)} line(s) new")
    if args.show:
        for title, runs in (("moved", moved), ("moved with a new indentation", reindented)):
            for run, i, j in sorted(runs, key=lambda x: x[1]):
                print(f"\n{title}, {len(run)} line(s), base line {i + 1} -> head line {j + 1}:")
                print("\n".join("  " + x for x in run))
    for title, rows, sign in (("gone", removed, "-"), ("new", added, "+")):
        if rows:
            print(f"\n{title}:")
            for n, line in rows:
                print(f"{sign}{n + 1}: {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
