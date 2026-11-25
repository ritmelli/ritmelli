"""Proof that a change to a theme only moves code: the page put back together on two commits, compared.

    python dev/theme_rebuild.py <base> [<head>] [--theme ritmelli] [--show]

The page is the index.html of the theme with every <script src> and <link rel="stylesheet"> replaced by the text of its
file (after a line with the tag's other attributes, when it has any), without the block marks (/* NAME-INICIO */,
/* NAME-FIM */, /* name:inicio */, /* name:fim */), the 'use strict'; lines, the blank lines and the <script> and
<style> tags themselves. <base> and <head> are git commits
(the head defaults to the working tree). The lines that differ between the two pages are split into the blocks that
only moved (a run of removed lines found whole among the added ones) and the lines that are new or gone, which are
printed. Exit 0 when nothing is new or gone (the pages are equal, or only blocks moved), 1 otherwise; --show prints
the moved blocks too.
"""
import argparse
import difflib
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

MARK = re.compile(r"/\*\s*(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-(?:INICIO|FIM)|[a-z]+:(?:inicio|fim))\b[^*]*\*/")
SCRIPT_SRC = re.compile(r'<script src="([^"]+)"([^>]*)></script>')
LINK_CSS = re.compile(r'<link rel="stylesheet" href="([^"]+)"([^>]*)>')
TAG = re.compile(r"^\s*</?(?:script|style)\b[^>]*>\s*$")
MIN_PIECE = 2   # the shortest piece of a split run that counts as moved: a lone "}" would match anywhere


def reader(rev, theme):
    """A function that reads a file of the theme folder on the commit rev (None: the working tree)."""
    folder = f"themes/{theme}/"
    if rev is None:
        return lambda name: (RAIZ / folder / name).read_text(encoding="utf-8")

    def show(name):
        out = subprocess.run(["git", "-C", str(RAIZ), "show", f"{rev}:{folder}{name}"], capture_output=True)
        if out.returncode:
            raise SystemExit(f"{rev}: {folder}{name}: {out.stderr.decode(errors='replace').strip()}")
        return out.stdout.decode("utf-8").replace("\r\n", "\n")
    return show


def rebuild(read):
    """The lines of the page put back together (see the module docstring)."""
    page = read("index.html").replace("\r\n", "\n")
    def put(kind):
        # the file in place of its tag, after a line with the other attributes of the tag, when it has any (a defer or
        # a media changes when the file applies)
        return lambda m: (f"\n[{kind} {m.group(1)}:{m.group(2).rstrip()}]" if m.group(2).strip() else "") + \
            "\n" + read(m.group(1)) + "\n"
    page = SCRIPT_SRC.sub(put("script"), page)
    page = LINK_CSS.sub(put("link"), page)
    lines = []
    for line in page.split("\n"):
        line = MARK.sub("", line).rstrip()
        if not line.strip() or line.strip() == "'use strict';" or TAG.match(line):
            continue
        lines.append(line)
    return lines


def split_moves(a, b):
    """(moved, removed, added): the runs of a removed and added back elsewhere, as (lines, where in a, where in b), and
    the lines left over on each side. A removed run that is not added back whole is split into the longest pieces
    (MIN_PIECE lines or more) that are, as when two blocks next to each other go to two files."""
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    gone = [(i1, a[i1:i2]) for tag, i1, i2, _, _ in ops if tag in ("delete", "replace")]
    new = [(j1, b[j1:j2]) for tag, _, _, j1, j2 in ops if tag in ("insert", "replace")]
    moved, used, left = [], set(), set()

    def find(run):
        """(k, pos) of the free place in the added lines that holds run, or None."""
        for k, (_, block) in enumerate(new):
            for pos in range(len(block) - len(run) + 1):
                if block[pos:pos + len(run)] == run and not any((k, pos + q) in used for q in range(len(run))):
                    return k, pos
        return None

    def take(run, i, k, pos):
        used.update((k, pos + q) for q in range(len(run)))
        moved.append((run, i, new[k][0] + pos))

    # whole runs first, the longest first, so a short run does not take the place of a longer one
    pending = []
    for i, run in sorted(gone, key=lambda x: -len(x[1])):
        place = find(run)
        if place:
            take(run, i, *place)
        else:
            pending.append((i, run))
    for i, run in pending:
        p = 0
        while p < len(run):
            for size in range(len(run) - p, MIN_PIECE - 1, -1):
                place = find(run[p:p + size])
                if place:
                    take(run[p:p + size], i + p, *place)
                    p += size
                    break
            else:
                left.add(i + p)
                p += 1
    removed = [(i, a[i]) for i in sorted(left)]
    added = [(j + p, line) for k, (j, block) in enumerate(new) for p, line in enumerate(block) if (k, p) not in used]
    # last, a line left over on both sides (the "}" that closed a block the matcher split) moved alone
    for i, line in list(removed):
        twin = next((x for x in added if x[1] == line), None)
        if twin:
            removed.remove((i, line))
            added.remove(twin)
            moved.append(([line], i, twin[0]))
    return moved, removed, added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
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
    print(f"{len(moved)} block(s) moved ({sum(len(r) for r, _, _ in moved)} lines), "
          f"{len(removed)} line(s) gone, {len(added)} line(s) new")
    if args.show:
        for run, i, j in sorted(moved, key=lambda x: x[1]):
            print(f"\nmoved, {len(run)} line(s), base line {i + 1} -> head line {j + 1}:")
            print("\n".join("  " + x for x in run))
    for title, rows, sign in (("gone", removed, "-"), ("new", added, "+")):
        if rows:
            print(f"\n{title}:")
            for n, line in rows:
                print(f"{sign}{n + 1}: {line}")
    return 1 if removed or added else 0


if __name__ == "__main__":
    sys.exit(main())
