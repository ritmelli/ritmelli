import ast
import io
import sys
import tokenize
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import garden
from syntax import css, html
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
    ("an alias to an anchor of an earlier document", "---\na: &x 1\n---\nb: *x\n"),
    ("an empty entry in a flow collection", "items: [one,,two]\n"),
    ("an escape out of the range of Unicode", "a: \"\\UFFFFFFFF\"\n"),
    ("a block scalar indicator that is no ASCII digit", "a: |\u00b2\n  x\n"),
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
    try:
        crlf = yaml.loads("a: 1\r\nb: |\r\n  x\r\n")
    except SyntaxProblem as ex:
        crlf = str(ex)
    check(crlf == {"a": "1", "b": "x\n"}, f"yaml reads a file with Windows line ends ({crlf})")


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
    ("the scope of a variable", "$a = $using:remote + $env:PATH + ${env:ProgramFiles(x86)} + ${using:other}\n",
     lambda s, n: sorted(v.name for v in n if isinstance(v, ps.Variable))
     == ["a", "env:PATH", "env:ProgramFiles(x86)", "other", "remote"]),
    ("a using line ends at a semicolon and at a comment", "using namespace System.IO; $a = 1 # c\n",
     lambda s, n: [c.text for c in s.comments] == [" c"] and [v.name for v in n if isinstance(v, ps.Variable)] == ["a"]),
    ("a label on the line before its loop", ":outer\nwhile ($true) { break outer }\n",
     lambda s, n: [x.label for x in n if isinstance(x, ps.While)] == ["outer"]),
    ("a colon word that is no label is a command", ":? 1\n",
     lambda s, n: [c.name for c in n if isinstance(c, ps.Command)] == [":?"]),
    ("an attribute that starts no param block gives its text back", "[int]\n[string]$x = 1\n",
     lambda s, n: [x.span.end for x in s.block.statements] == [5, 20]),
    ("the flag of a data section is one token", "data -SupportedCommand Foo { 'x' }\n",
     lambda s, n: (5, 22, "parameter") in s.tokens),
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
    for path, text in sorted(garden.working_tree(ROOT).items()):
        for k, piece in enumerate(garden.read_pieces(path, text)):
            if piece.language == "powershell":
                yield f"{path}#{k}", piece.text


LITERAL_CASES = ["'a\\nb'", "'\\x41\\101\\N{BULLET}\\q'", "'\\u00e9\\U0001F600'", "'a\\\nb'", "r'a\\nb'", "'''a\nb'''",
                 "f'{{x}} {y!r:>{w}} {z}'", "rf'\\d{x}'", "f'{d[\"k\"]}'", "f\"{d['k']}\"", "f'{x:%H:%M}'",
                 "f'{(lambda: 1)()}'", "f'''{\nx}'''", "f'''a {1 # } b\n} c'''", "f'{x:)>5}'", "f'{x:(>5}'",
                 "f'{x:{d[\"}\"]}}'", "f'{x=}'", "f'{x = !r:>5}'", "f'{a != b} {a == b} {f(k=1)}'",
                 "f\"{f\"{x}\"}\"", "f\"{\"}\"}\"", "f'{rf\"{x}\\d\"}'", "f\"{f'{{'}\"", "f'{fr\"{\"}\"}\"}'",
                 "f'{rf\"\\{{\"}'", "f'{rf\"\\{d[\"}\"]}\"}'",
                 "f'{1 if\"{\"else 2}'", "f'{\"a\" in\"{\"}'", "f'{x or\"}\"}'"]


def literal_view(raw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        node = ast.parse(raw, mode="eval").body
    out = []
    for v in node.values if isinstance(node, ast.JoinedStr) else [node]:
        out += list(v.value) if isinstance(v, ast.Constant) else [v.format_spec is not None]
    return out


def python_literals():
    for k, raw in enumerate(LITERAL_CASES):
        yield f"case {k}", raw
    for path, text in sorted(garden.working_tree(ROOT).items()):
        if garden.suffix(path) in garden.PYTHON:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            for line, raw in units.string_parts(tokens, text, (1, 0), (len(text) + 1, 0)):
                yield f"{path}:{line}", raw


def test_python_literals():
    count, wrong = 0, []
    for name, raw in python_literals():
        try:
            chars = units.literal_chars(raw, 1)
        except (IndexError, ValueError) as ex:
            wrong.append(f"{name} ({type(ex).__name__})")
            continue
        if chars is None:
            continue
        count += 1
        if [item.spec if isinstance(item, units.Field) else item for item, _ in chars] != literal_view(raw):
            wrong.append(name)
    check(count > 1000 and not wrong, f"the string reader decodes every Python string of the repo as Python does "
                                      f"({count} strings, {wrong[:3]})")
    rows = [row for _, row in units.literal_chars("f'''x\\n{\nn}\ny'''", 1)]
    check(rows == [1, 1, 1, 2, 3], f"each character keeps the line it is written on ({rows})")


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


def handler(document, k=0):
    return document.handlers[k][1].value


HTML_CASES = [
    ("a script keeps the offsets of its text", "<p>\n<script>\nlet a = 1;\n</script>\n",
     lambda d, t: d.scripts[0][1].value == "\nlet a = 1;\n" and d.scripts[0][1].offset(1) == t.index("let")),
    ("an entity in an event attribute is decoded and keeps its place", "<b onclick=\"f(&quot;x&quot;)\">",
     lambda d, t: handler(d).value == "f(\"x\")" and handler(d).offset(2) == t.index("&quot;")
     and handler(d).offset(3) == t.index("x&")),
    ("a comment keeps its text", "<!-- a -- b -->\n", lambda d, t: [c.text for c in d.comments] == [" a -- b "]),
    ("a script of another type is no JavaScript", "<script type=\"application/json\">{\"a\": 1}</script>\n",
     lambda d, t: d.scripts == []),
    ("a module is JavaScript", "<script type=\"module\">x();</script>\n", lambda d, t: len(d.scripts) == 1),
    ("a closing tag in another case closes the script", "<SCRIPT>x();</Script>\n",
     lambda d, t: [c.value for _, c in d.scripts] == ["x();"]),
    ("a style and a style attribute", "<style>a { b: c }</style><p style=\"color: red\">",
     lambda d, t: len(d.styles) == 1 and [a.value.value for _, a in d.style_attributes] == ["color: red"]),
    ("only an on attribute is an event", "<p onclick=\"f()\" title=\"g()\" one=\"h()\">",
     lambda d, t: [a.name for _, a in d.handlers] == ["onclick", "one"]),
    ("an unquoted attribute", "<p onclick=f()>", lambda d, t: handler(d).value == "f()"),
]
HTML_ERRORS = [("a comment that is never closed", "<p>\n<!-- x\n"),
               ("an attribute value that is never closed", "<p title=\"x>\n"),
               ("a script that is never closed", "<script>\nx();\n")]
CSS_CASES = [
    ("a comment keeps its text", "a { b: c } /* why */\n", lambda s: [c.text for c in s.comments] == [" why "]),
    ("a comment in a string is no comment", "a { content: '/* no */'; }\n", lambda s: s.comments == []),
    ("a url without quotes keeps its slashes", "a { b: url(//x/y) }\n", lambda s: s.comments == []),
    ("blocks inside blocks", "@media x { a { b: c } }\n", lambda s: s.comments == []),
]
CSS_ERRORS = [("a block that is never closed", "a { b: c\n"), ("a block closed twice", "a { b: c } }\n"),
              ("a comment that is never closed", "/* x\n"), ("a string that runs into the end of the line", "a { b: 'x\n }\n")]


def test_web():
    for label, text, ok in HTML_CASES:
        try:
            check(ok(html.parse(text), text), f"html: {label}")
        except SyntaxProblem as ex:
            check(False, f"html: {label} ({ex})")
    for label, text, ok in CSS_CASES:
        try:
            check(ok(css.parse(text)), f"css: {label}")
        except SyntaxProblem as ex:
            check(False, f"css: {label} ({ex})")
    for reader, cases in ((html, HTML_ERRORS), (css, CSS_ERRORS)):
        for label, text in cases:
            try:
                reader.parse(text)
                raised = False
            except SyntaxProblem:
                raised = True
            check(raised, f"{reader.__name__.split('.')[-1]} refuses {label}")
    piece = units.web_piece("a.html", "<p>\n<button onclick=\"f() // why\n\">\n<!-- page -->\n<script>\n/* a\n b */ x();\n"
                                      "</script>\n", "html")
    check(sorted(c[:3] for c in piece.comments) == [(2, 2, " why"), (4, 4, " page "), (6, 7, " a\n b ")],
          f"the comments of a page, of its scripts and of its event attributes sit on their lines ({piece.comments})")
    check(sorted(piece.code_lines) == [1, 2, 3, 5, 7, 8], f"the code of a page is its tags and its scripts, "
                                                           f"without the comments ({piece.code_lines})")

    piece = units.web_piece("a.html", "<b onclick=\"f() // a &amp;\">\n", "html")
    check(piece.code_lines.get(1, "").split() == ["<b", "onclick=\"f()", '">'],
          f"a comment that ends in an entity is cut out whole ({piece.code_lines})")


def test_web_files():
    count, bad = 0, []
    for path, text in sorted(garden.working_tree(ROOT).items()):
        if garden.suffix(path) not in garden.WEB:
            continue
        count += 1
        piece = units.web_piece(path, text, garden.WEB[garden.suffix(path)])
        if piece.problem:
            bad.append(piece.problem)
            continue
        if garden.suffix(path) == ".html":
            continue
        covered = set(piece.code_lines)
        for first, last, _, _ in piece.comments:
            covered |= set(range(first, last + 1))
        missing = [n for n, line in enumerate(text.splitlines(), 1) if line.strip() and n not in covered]
        if missing:
            bad.append(f"{path}:{missing[0]}")
    check(count > 60 and not bad, f"every JavaScript, sheet and page of the repo reads, and the code and the comments "
                                  f"of each JavaScript and sheet cover every line ({count} files, {bad[:3]})")


test_yaml()
test_yaml_offsets()
test_powershell()
test_lossless()
test_python_literals()
test_web()
test_web_files()
print(f"{len(failures)} failure(s)" if failures else "ok    all syntax cases")
sys.exit(1 if failures else 0)
