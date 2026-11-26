import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
from syntax import powershell as ps
from syntax import units
from syntax import yaml
from syntax.text import Source, SyntaxProblem

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


YAML_CASES = [
    ("comments everywhere", "a: 1 # c\nb: # c2\n  - x # c3\n  # c4\n  - y\n", {"a": "1", "b": ["x", "y"]}),
    ("a plain scalar on lines", "key: this is\n  a plain\n\n  scalar\nnext: v\n",
     {"key": "this is a plain\nscalar", "next": "v"}),
    ("a sequence at the key's indent", "k:\n- a\n- b\nj: c\n", {"k": ["a", "b"], "j": "c"}),
    ("compact nodes in a sequence", "- a\n-\n  - b\n  - c\n- d: e\n  f: g\n",
     ["a", ["b", "c"], {"d": "e", "f": "g"}]),
    ("block scalars", "s: |\n  line1\n   indented\n\n  line3\n\nt: >\n  fold\n  this\n\n  para\nu: |-\n  strip\n\n\n"
                      "v: |+\n  keep\n\n\nw: x\n",
     {"s": "line1\n indented\n\nline3\n", "t": "fold this\npara\n", "u": "strip", "v": "keep\n\n\n", "w": "x"}),
    ("an indentation indicator", "a: |2\n    two extra\n  base\n", {"a": "  two extra\nbase\n"}),
    ("flow collections on lines", "f: [a, b,\n  c, {d: e,\n  f: g}, [h, i]]\ng: {x: 1, 'q': \"w\"}\n",
     {"f": ["a", "b", "c", {"d": "e", "f": "g"}, ["h", "i"]], "g": {"x": "1", "q": "w"}}),
    ("trailing commas and empty flows", "f: [a, b, ]\ng: {a: b, }\nh: [ ]\ni: { }\n",
     {"f": ["a", "b"], "g": {"a": "b"}, "h": [], "i": {}}),
    ("anchors and aliases", "a: &anc\n  x: 1\nb: *anc\nc: &s scalar\nd: [*s, *anc]\n",
     {"a": {"x": "1"}, "b": {"x": "1"}, "c": "scalar", "d": ["scalar", {"x": "1"}]}),
    ("quoted scalars that fold", "a: 'single\n  line two'\nb: \"double \\\n  continued\"\nc: \"esc \\t \\u00e9 \\x41\"\n",
     {"a": "single line two", "b": "double continued", "c": "esc \t \u00e9 A"}),
    ("explicit keys", "? complex key\n: complex value\n? other\n", {"complex key": "complex value", "other": None}),

    ("tags", "a: !!str 1\nb: !custom value\nc: !<tag:x> y\n", {"a": "1", "b": "value", "c": "y"}),
    ("empty values", "empty:\nnull_like: ~\nx: \"\"\n", {"empty": None, "null_like": "~", "x": ""}),
    ("plain scalars with : and #", "a: b:c\nd: e#f\ng: h # real\nurl: http://x:8080/p\n",
     {"a": "b:c", "d": "e#f", "g": "h", "url": "http://x:8080/p"}),
    ("a run block keeps its # lines", "list:\n  - run: |\n      echo hi\n      # not a comment\n    shell: bash\n",
     {"list": [{"run": "echo hi\n# not a comment\n", "shell": "bash"}]}),
    ("the doubled quote", "a: 'it''s'\n", {"a": "it's"}),
    ("on is a string", "on:\n  push:\n    branches: [main]\n", {"on": {"push": {"branches": ["main"]}}}),
]

YAML_ERRORS = [
    ("a repeated key", "a: 1\na: 2\n"), ("an alias with no anchor", "a: *x\n"), ("a tab in the indentation", "a:\n\tb: 1\n"),
    ("a mapping value after a value", "a: b: c\n"), ("an unclosed quote", "a: 'b\n"),
    ("a sequence entry after a key", "k: - a\n"), ("a block scalar less indented than its key", "a: |\n  x\n b\n"),
]


def test_yaml():
    for label, text, expected in YAML_CASES:
        try:
            got = [yaml.data(d.root) for d in yaml.parse(text).documents]
        except SyntaxProblem as ex:
            got = [f"error: {ex}"]
        check(got == [expected], f"yaml: {label} ({got})")
    for label, text in YAML_ERRORS:
        try:
            yaml.parse(text)
            raised = False
        except SyntaxProblem:
            raised = True
        check(raised, f"yaml refuses {label}")
    two = yaml.parse("--- |\n  top\n...\n---\n- b\n")
    check([yaml.data(d.root) for d in two.documents] == ["top\n", ["b"]], "yaml reads a stream of two documents")
    stream = yaml.parse("a: 1 # one\n# two\nb: '#no'\n")
    check([c.text for c in stream.comments] == [" one", " two"], "yaml keeps each comment, and none inside a scalar")


def test_yaml_offsets():
    checked = bad = 0
    for p in sorted((ROOT / ".github").rglob("*.yml")):
        text = p.read_text(encoding="utf-8")
        stream = yaml.parse(text)
        for d in stream.documents:
            for node in yaml.walk(d.root):
                if not isinstance(node, yaml.Scalar):
                    continue
                if len(node.offsets) != len(node.value):
                    bad += 1
                    continue
                for k, c in enumerate(node.value):
                    source = text[node.offsets[k]]
                    checked += 1
                    folded = c in " \n" and source in " \n"
                    escaped = node.style == "double" and source == "\\"
                    if not (folded or escaped or source == c):
                        bad += 1
                        break
    check(checked > 10000 and bad == 0, f"every character of every scalar of .github points at its place ({checked}, "
                                        f"{bad} off)")


PS_CASES = [
    ("comments", "$a = 'x # y' # real\n<# block\n#>\nWrite-Host a#b\n",
     lambda s, n: [c.text for c in s.comments] == [" real", " block\n"]),
    ("here-strings", "$t = @'\nline 'q' \"d\" $no\n  '@ not the end\n'@\n$e = @\"\nv $x and $($y.N)\n\"@\n",
     lambda s, n: [x.kind for x in n if isinstance(x, ps.String)] == ["here-single", "here-double"]
     and sorted(v.name for v in n if isinstance(v, ps.Variable)) == ["e", "t", "x", "y"]),
    ("a command and its parameters", "Get-Item x -ErrorAction:Stop -Force 2>&1 | Out-Null\n",
     lambda s, n: [c.name for c in n if isinstance(c, ps.Command)] == ["Get-Item", "Out-Null"]
     and [p.name for c in n if isinstance(c, ps.Command) for p in c.parameters()] == ["ErrorAction", "Force"]),
    ("a try with typed catches", "try { f } catch [IO.IOException], [System.Net.WebException] { } finally { g }\n",
     lambda s, n: [c.types for t in n if isinstance(t, ps.Try) for c in t.catches]
     == [["IO.IOException", "System.Net.WebException"]]),
    ("the loops", "do { $i++ } until ($i -gt 3)\nfor (;;) { break }\nforeach ($x in 1..3) { }\nwhile ($true) { }\n",
     lambda s, n: [type(x).__name__ for x in n if isinstance(x, (ps.DoLoop, ps.For, ps.Foreach, ps.While))]
     == ["DoLoop", "For", "Foreach", "While"]),
    ("a param block with attributes", "param([ValidateSet('a', 'b')][string]$Cmd = 'a', [int]$Port = 8799)\n",
     lambda s, n: [p.variable.name for p in s.block.params.params] == ["Cmd", "Port"]),
    ("--% stops parsing until the pipe", "cmd /c --% raw \"args\" | here\n",
     lambda s, n: [c.name for c in n if isinstance(c, ps.Command)] == ["cmd", "here"]),
    ("a dot path is a command", ". .\\lib.ps1\n.\\script.ps1 -Name v\n",
     lambda s, n: [(c.invocation, c.name) for c in n if isinstance(c, ps.Command)]
     == [(".", ".\\lib.ps1"), (None, ".\\script.ps1")]),
    ("a cast chain and a static member", "$r = [int][IO.FileAttributes]::ReparsePoint\n",
     lambda s, n: any(isinstance(x, ps.Cast) for x in n)),
    ("the scope of a variable", "$a = $using:remote + $env:PATH + ${env:ProgramFiles(x86)}\n",
     lambda s, n: sorted(v.name for v in n if isinstance(v, ps.Variable))
     == ["a", "env:PATH", "env:ProgramFiles(x86)", "remote"]),

]

PS_ERRORS = [("an unclosed block", "if ($a) {\n"), ("an unclosed string", "'abc\n"),
             ("an expression after a pipe", "Get-Item | 1\n"), ("a try with no catch", "try { f }\n")]


def test_powershell():
    for label, text, ok in PS_CASES:
        try:
            script = ps.parse(text)
            nodes = list(ps.walk(script))
            check(ok(script, nodes), f"powershell: {label}")
        except SyntaxProblem as ex:
            check(False, f"powershell: {label} ({ex})")
    for label, text in PS_ERRORS:
        try:
            ps.parse(text)
            raised = False
        except SyntaxProblem:
            raised = True
        check(raised, f"powershell refuses {label}")


def powershell_texts():
    for p in sorted([*ROOT.rglob("*.ps1"), *ROOT.rglob("*.psd1")]):
        if ".git" not in p.parts:
            yield p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    for p in sorted((ROOT / ".github").rglob("*.yml")):
        rel = p.relative_to(ROOT).as_posix()
        for piece in units.yaml_pieces(rel, p.read_text(encoding="utf-8"), re.compile("^$")):
            if piece.language == "powershell":
                yield f"{rel}:{piece.run_line}", piece.text


def test_lossless():
    count, bad = 0, []
    for name, text in powershell_texts():
        count += 1
        script = ps.parse(text, name)
        pos = 0
        for start, end, _ in script.tokens:
            gap = text[pos:start]
            if start < pos or gap.strip(" \t\n\r\f\v\u00a0;"):
                bad.append(f"{name}:{Source(text).line(start)}")
                break
            pos = end
        if text[pos:].strip(" \t\n\r\f\v\u00a0;"):
            bad.append(f"{name}: the end")
    check(count > 50 and not bad, f"the tokens of every PowerShell of the repo cover its text with no overlap ({count} "
                                  f"scripts, {bad[:3]})")


test_yaml()
test_yaml_offsets()
test_powershell()
test_lossless()
print(f"{len(failures)} failure(s)" if failures else "ok    all syntax cases")
sys.exit(1 if failures else 0)
