import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml as pyyaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import garden
from syntax import html
from syntax import javascript as js
from syntax import powershell as ps
from syntax import yaml

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def plain(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {("" if k is None else k): plain(v) for k, v in value.items()}
    return value


def oracle_yaml(text):
    return [plain(d) for d in pyyaml.load_all(text, Loader=pyyaml.BaseLoader)]


def our_yaml(text):
    return [plain(yaml.data(d.root)) for d in yaml.parse(text).documents]


SCALARS = ["a", "b c", "x: y", "#no", "- d", "1", "", " lead", "trail ", "multi\nline", "q'uote", 'dq"', "back\\slash",
           "ação", "tab\there", "{", "[x]", "*star", "&amp", "!bang", "%pct", "@at", "`bt", "a #b", "a#b",
           "--- m", "...", "long " * 30, "x\n\ny", "\n", "end\n", "  both  ", "k: v\nk2: v2", "?", ":", "-", "null",
           "~", "true"]
DUMPS = [{}, {"default_flow_style": True}, {"default_flow_style": False}, {"canonical": True}, {"width": 10},
         {"default_style": "'"}, {"default_style": '"'}, {"default_style": "|"}, {"default_style": ">"},
         {"explicit_start": True, "explicit_end": True}, {"indent": 4}, {"allow_unicode": True, "width": 15}]


def generated(rnd, depth=0):
    r = rnd.random()
    if depth > 3 or r < 0.4:
        return rnd.choice(SCALARS)
    if r < 0.7:
        return [generated(rnd, depth + 1) for _ in range(rnd.randint(0, 4))]
    shared = generated(rnd, depth + 1) if rnd.random() < 0.2 else None
    out = {rnd.choice(SCALARS): generated(rnd, depth + 1) for _ in range(rnd.randint(0, 4))}
    if shared is not None and isinstance(shared, (list, dict)):
        out["one"], out["two"] = shared, shared
    return out


def test_yaml():
    files = sorted((ROOT / ".github").rglob("*.yml"))
    bad = [p.name for p in files if our_yaml(p.read_text(encoding="utf-8")) != oracle_yaml(p.read_text(encoding="utf-8"))]
    check(len(files) > 3 and not bad, f"every YAML of .github reads as PyYAML reads it ({len(files)} files, {bad})")
    rnd = random.Random(7)
    count, wrong = 0, []
    for _ in range(1000):
        options = rnd.choice(DUMPS)
        text = pyyaml.dump(generated(rnd), **options)
        count += 1
        try:
            same = our_yaml(text) == oracle_yaml(text)
        except ValueError as ex:
            same = f"{ex}"
        if same is not True:
            wrong.append((options, text[:120]))
    check(not wrong, f"{count} documents written by PyYAML in every style read back as PyYAML reads them ({wrong[:2]})")


ORACLE = r"""
param([string]$In, [string]$Out)
$items = Get-Content -Raw -Encoding UTF8 $In | ConvertFrom-Json
$result = @()
foreach ($item in $items) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput([string]$item.text, [ref]$tokens, [ref]$errors)
    $L = [System.Management.Automation.Language.StringConstantExpressionAst]
    $E = [System.Management.Automation.Language.ExpandableStringExpressionAst]
    $comments = @($tokens | Where-Object { $_.Kind -eq 'Comment' } | ForEach-Object { ,@($_.Extent.StartOffset, $_.Extent.EndOffset) })
    $strings = @($ast.FindAll({ param($a) ($a -is $L -or $a -is $E) -and $a.StringConstantType -ne 'BareWord' }, $true) | ForEach-Object { ,@($_.Extent.StartOffset, $_.Extent.EndOffset) })
    $commands = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { ,@($_.Extent.StartOffset, [string]$_.GetCommandName()) })
    $loops = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.LoopStatementAst] }, $true) | ForEach-Object { ,@($_.GetType().Name, $_.Extent.StartOffset, $_.Extent.EndOffset) })
    $tries = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.TryStatementAst] }, $true) | ForEach-Object {
        $t = $_
        $catches = @($t.CatchClauses | ForEach-Object { ,@($_.Extent.StartOffset, $_.Body.Extent.StartOffset, $_.Body.Extent.EndOffset, (@($_.CatchTypes | ForEach-Object { $_.TypeName.FullName }) -join '|')) })
        $fin = -1
        if ($t.Finally) { $fin = $t.Finally.Extent.StartOffset }
        ,@($t.Extent.StartOffset, $t.Extent.EndOffset, $catches, $fin)
    })
    $functions = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) | ForEach-Object { ,@($_.Extent.StartOffset, $_.Name) })
    $assigns = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true) | ForEach-Object { ,@($_.Extent.StartOffset, $_.Extent.EndOffset, [string]$_.Operator) })
    $variables = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.VariableExpressionAst] }, $true) | ForEach-Object { ,@($_.Extent.StartOffset, $_.Extent.EndOffset, $_.VariablePath.UserPath, [bool]$_.Splatted) })
    $errs = @($errors | ForEach-Object { ,@($_.Extent.StartOffset, $_.Message) })
    $result += [pscustomobject]@{ id = $item.id; comments = $comments; strings = $strings; commands = $commands; loops = $loops; tries = $tries; functions = $functions; assigns = $assigns; variables = $variables; errors = $errs }
}
ConvertTo-Json -InputObject $result -Depth 8 -Compress | Set-Content -Encoding UTF8 $Out
"""

HARD_CASES = [
    "$text = @'\nline 'q' \"d\" $no\n  '@ not the end\n'@\n$exp = @\"\nvalue $x and $($y.Name) and $(Get-Date -Format 'yyyy')\n\"@\n",
    "switch -Regex ($value) {\n    '^a' { 'a'; break }\n    \"b$\" { 'b' }\n    { $_ -gt 5 } { 'big' }\n    default { 'o' }\n}\n",
    "trap [System.IO.IOException] { Write-Warning $_; continue }\ntrap { exit 1 }\n",
    ":outer foreach ($a in $list) {\n    :inner while ($true) {\n        if ($a) { break outer } else { continue inner }\n    }\n}\n",
    "do { $i++ } until ($i -gt 3)\ndo {\n    $j--\n} while ($j -gt 0)\nfor ($i = 0; $i -lt 3; $i++) { }\nfor (;;) { break }\n",
    "$params = @{ Path = 'x'; Force = $true }\nCopy-Item @params\nGet-Item 'x' 2>&1 | Out-Null\nGet-Item 'y' > $null 2>> e.txt\n",
    "cmd /c \"echo hi\" --% raw \"args\" | here\n& \"$env:ProgramFiles\\app.exe\" -a 1 -b:$false\n. .\\lib.ps1\n.\\s.ps1 -Name v\n",
    "$a, $b = 1, 2\n$x++\n--$y\n$h['k'].v = 3\n$s = [string]::Join(',', $a)\n$n = [int]'42' + [Math]::Max(1, 2)\n"
    "$t = [System.Collections.Generic.List[string]]::new()\n$u = [string[]]@('a', 'b')\n",
    "function Get-Thing {\n    [CmdletBinding()]\n    param(\n        [Parameter(Mandatory = $true, Position = 0)]\n"
    "        [string]$Name,\n        [int]$Count = 1\n    )\n    begin { $l = @() }\n    process { $l += $Name }\n"
    "    end { return $l }\n}\nfilter Only-Big { if ($_ -gt 10) { $_ } }\nfunction Add($a, $b = 2) { $a + $b }\n",
    "$x = if ($y) { 1 } elseif ($z) { 2 } else { 3 }\n$w = switch ($y) { 1 { 'a' } }\n$v = foreach ($k in 1..3) { $k }\n",
    "while ($true) {\n    try { Invoke-Thing; break }\n    catch [System.Net.WebException], [System.IO.IOException] { Start-Sleep 1 }\n"
    "    catch { throw }\n    finally { Write-Verbose 'done' }\n}\n",
    "#requires -Version 5\n<# block with # inside\n   more #>\nWrite-Host 'a#b' a#b # real\nGet-Item `\n    -Path x `\n    -Force\n",
    "$q = \"a`\"b\" + \"a\"\"b\" + 'it''s'\n$r = \"${env:ProgramFiles(x86)}\\x\" + \"$using:remote\" + \"$($a.b.c)\"\n"
    "$s2 = \"nested $(if ($a) { \"yes $($b)\" } else { 'no' }) end\"\n",
    "$x = $null -eq $y -and -not $z -or !$w\n$y = $a -replace 'a', 'b' -split ','\n$z = -join $p\n$c = 0x10 + 1kb + .5 + 10L\n",
    "Get-Process | Where-Object { $_.CPU -gt 100 } |\n    Sort-Object CPU -Descending |\n    Select-Object -First 5\n1..10 | % { $_ }\n",
    "Write-Output (Get-Date).Year\nWrite-Output $a.b[0].c()\nWrite-Output \"x\".Length\nWrite-Output 1,2,3\nWrite-Output a,b c\n",
    "data Messages {\n    ConvertFrom-StringData @'\nkey = value\n'@\n}\n",
    "using namespace System.IO; $a = 1 # c\n:outer\nwhile ($true) { break outer }\n:? 1\n",
    "$r = ${using:remote}\n[int]\n[string]$x = 1\ndata -SupportedCommand Foo { 'x' }\n",
    "Write-Output '" + chr(0x1F600) + "'; & \"Write-Output\" 1\n& 'Get-Date' 2\n",
]

ASSIGN_OPS = {"=": "Equals", "+=": "PlusEquals", "-=": "MinusEquals", "*=": "MultiplyEquals", "/=": "DivideEquals",
              "%=": "RemainderEquals", "??=": "QuestionQuestionEquals"}


def utf16(text):
    out, at = [], 0
    for c in text:
        out.append(at)
        at += 2 if ord(c) > 0xFFFF else 1
    return [*out, at]


def ours(text):
    script = ps.parse(text)
    nodes = list(ps.walk(script))
    u = utf16(text)
    loops = {ps.While: "WhileStatementAst", ps.For: "ForStatementAst", ps.Foreach: "ForEachStatementAst"}
    return {
        "comments": sorted([u[c.span.start], u[c.span.end]] for c in script.comments),
        "strings": sorted([u[n.span.start], u[n.span.end]] for n in nodes if isinstance(n, ps.String)),
        "commands": sorted([u[n.span.start], n.name or ""] for n in nodes if isinstance(n, ps.Command)),
        "loops": sorted([("DoUntilStatementAst" if n.until else "DoWhileStatementAst") if isinstance(n, ps.DoLoop)
                         else loops[type(n)], u[n.span.start], u[n.span.end]] for n in nodes
                        if isinstance(n, (ps.DoLoop, *loops))),
        "tries": sorted([u[n.span.start], u[n.span.end], sorted([u[c.span.start], u[c.body.span.start],
                                                                 u[c.body.span.end], "|".join(c.types)]
                                                                for c in n.catches),
                         u[n.finally_block.span.start] if n.finally_block else -1] for n in nodes
                        if isinstance(n, ps.Try)),
        "functions": sorted([u[n.span.start], n.name] for n in nodes if isinstance(n, ps.Function)),
        "assigns": sorted([u[n.span.start], u[n.span.end], ASSIGN_OPS[n.op]] for n in nodes
                          if isinstance(n, ps.Assign)),
        "variables": sorted([u[n.span.start], u[n.span.end], n.name, n.splat] for n in nodes
                            if isinstance(n, ps.Variable)),
    }


def theirs(item):
    out = {}
    for key in ("comments", "strings", "commands", "loops", "tries", "functions", "assigns", "variables"):
        value = item[key] or []
        if key == "commands":
            value = [[a, b or ""] for a, b in value]
        elif key == "variables":
            value = [[a, b, c, bool(d)] for a, b, c, d in value]
        elif key == "tries":
            value = [[a, b, sorted(c or []), d] for a, b, c, d in value]
        out[key] = sorted(value)
    return out


def powershell_corpus():
    for path, text in sorted(garden.working_tree(ROOT).items()):
        for k, piece in enumerate(garden.read_pieces(path, text)):
            if piece.language == "powershell":
                yield f"{path}#{k}", piece.text
    for k, text in enumerate(HARD_CASES):
        yield f"case {k}", text


def test_powershell():
    items = list(powershell_corpus())
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "oracle.ps1").write_text(ORACLE, encoding="utf-8-sig")
        (folder / "in.json").write_text(json.dumps([{"id": i, "text": t} for i, t in items]), encoding="utf-8")
        run = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File", str(folder / "oracle.ps1"),
                              "-In", str(folder / "in.json"), "-Out", str(folder / "out.json")],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(run.returncode == 0, f"the PowerShell parser of Windows reads the corpus ({run.stderr.strip()[:200]})")
        if run.returncode:
            return
        oracle = {o["id"]: o for o in json.loads((folder / "out.json").read_text(encoding="utf-8-sig"))}
    wrong = []
    for ident, text in items:
        item = oracle[ident]
        if item["errors"]:
            wrong.append(f"{ident}: the oracle does not read it ({item['errors'][0][1]})")
            continue
        mine, real = ours(text), theirs(item)
        keys = [k for k in real if mine[k] != real[k]]
        if keys:
            wrong.append(f"{ident}: {keys}")
    check(len(items) > 60 and not wrong, f"every PowerShell of the repo, and the hard cases, reads as the PowerShell "
                                         f"parser reads it: comments, strings, commands, loops, tries, functions, "
                                         f"assignments and variables ({len(items)} scripts, {wrong[:3]})")


JAVASCRIPT_HARD_CASES = [
    "const a = x => x * 2, b = async (y, ...z) => { await y; return z?.[0] ?? null; };\n",
    "label: for (let i = 0, j = 1; i < 3; i++, j--) { if (i) continue label; else break label; }\n",
    "for (const [k, v] of Object.entries({a: 1, 'b': 2, [c]: 3, d() {}, get e() { return 1; }, set e(v) {}, ...rest})) {}\n",
    "for (x in y) ;\n",
    "async function f() { for await (const q of r) {} }\n",
    "var re = /[/\\]]+/gi.test(s) ? a / b / c : `t${a}x${`n${b}`}`;\n",
    "tag`hello ${world}`;\n",
    "({a, b: [c, d = 1], ...e} = f);\n",
    "[a, , b = 2, ...c] = d;\n",
    "new Foo;\nnew Foo.Bar(1)(2);\n",
    "function g() { return new.target; }\n",
    "class A extends B { static #x = 1; #y; constructor() { super(); this.#y = 2; } static { init(); } "
    "get z() { return this.#y; } async *gen() { yield* other(); } }\n",
    "switch (x) { case 1: a(); break; default: b(); }\n",
    "try { a(); } catch { b(); } finally { c(); }\n",
    "try { a(); } catch ({message}) { b(message); }\n",
    "do x++; while (x < 10)\n",
    "if (a) b(); else if (c) d(); else { e(); }\n",
    "x = a ? b : c ? d : e;\n",
    "y = (a, b);\n",
    "z = a?.b.c?.(d)?.[e];\n",
    "w = void 0, typeof x === 'undefined', delete o.p, !a, ~b, -c, +d, ++e, f--;\n",
    "v = a ** b ** c;\n",
    "u = (async function* () {})();\n",
    "t = function named() {};\n",
    "s = { async a() {}, *b() {}, async *c() {}, 'd': 1, 1: 2, [e]: 3, f, async: 1, get: 2, set: 3 };\n",
    "r = a => ({ b: a });\n",
    "q = () => {};\n",
    "p = (a = 1, { b } = {}, [c] = []) => a + b + c;\n",
    "o = 0x1F + 0o17 + 0b101 + 1_000 + .5 + 5. + 1e3 + 10n;\n",
    "n = 'it\\'s' + \"a\\\"b\" + '\\u00e9\\x41\\n';\n",
    "// line comment\n/* block\n   comment */\nm = 1;\n",
    "m = a\n++b\n",
    "l = a\n(b)\n",
    "k = /=/.test(c)\n",
    "a = b\n/hi/g.exec(c)\n",
    "if (a) /re/.test(b)\n",
    "x = y / 2 / z\n",
    "x = (a) / 2\n",
    "x = a++ / 2\n",
    "x = {} / 1\n",
    "({}) / 1\n",
    "x = function () {} / 1\n",
    "let\nx = 1\n",
    "var let = 1; let[0] = 2;\n",
    "async\nfunction f() {}\n",
    "x = async\n(y) => y\n",
    "for (var i = 0 in o) ;\n",
    "for (let of of []) ;\n",
    "for (async of => 1; ;) break;\n",
    "a = b ? (c) : d => e;\n",
    "a = b ? c => d : e => f;\n",
    "x = `a${b}c${d}e`;\n",
    "x = `\n${a}\n`;\n",
    "x = '\\\n';\n",
    "x = a\n?.b\n",
    "throw new Error('x');\n",
    "x = class { [a] = 1; static async *[b]() {} };\n",
    "x = { __proto__: null, 'a b': 1 };\n",
    "x = a in b, c instanceof d;\n",
    "for (const x of a, b) ;\n",
    "x = a?.b`c`;\n",
    "while (a) if (b) break; else continue;\n",
    "x = y => z => w;\n",
    "x = (a, b) => (c, d);\n",
    "x = async x => await x;\n",
    "x = () => ({}).a;\n",
    "x = a ?? b;\n",
    "x &&= 1; y ||= 2; z ??= 3; w **= 2; v >>>= 1;\n",
    "x = <!-- y\n",
    "x = 1 // comment\n",
    "\"use strict\";\nx = 1;\n",
    "function h(a, b = a, ...c) { return c; }\n",
    "function h2(a) { 'use strict'; return a; }\n",
    "x = /[\\]/]/;\n",
    "x = a.if.class.new;\n",
    "x = { if: 1, class: 2, new: 3 };\n",
    "with (o) { a; }\n",
    "debugger;\n",
    "x = 1;;;\n",
    "{ }\n",
    "x = typeof typeof a;\n",
    "x = -(-a);\n",
    "x = a - -b;\n",
    "x = a + +b;\n",
    "x = !function () {}();\n",
    "x = new (a.b)();\n",
    "x = new a.b.c;\n",
    "x = new new a()();\n",
    "x = a[b](c)[d];\n",
    "x = (function () { return this; })();\n",
    "x = yield;\n",
    "function* g() { const y = yield; yield a, b; }\n",
    "x = await;\n",
    "x = \"\\u{1F600}\";\n",
    "x = '😀' + a;\n",
    "x = 1 /* c */ / 2;\n",
    "x = a\n/b/i\n",
    "x = [\n1,\n2,\n];\n",
    "x = { a, };\n",
    "f(a, b,);\n",
    "function k(a, b,) {}\n",
    "x = (a, b,) => a;\n",
    "x = a ? b : c\n",
    "x = (((a)));\n",
    "x = (a)(b);\n",
    "x = (a).b;\n",
    "(a) = 1;\n",
    "(a.b) = 1;\n",
    "[(a)] = b;\n",
    "({ a: (b) } = c);\n",
    'class C { static get x() { return 1; } get() {} static() {} set(v) {} static static() {} }\n',
    '{}\n/re/.test(x)\n',
    'function r1() { return\nx; }\n',
    'function* g2() { var yield2 = 1; } var yield = 1;\n',
    'var await = 1; x = await;\n',
    'x = `${ {a: 1}.a }`;\n',
    'x = a?.();\n',
    'for (var x = (a in b); ;) break;\n',
    'x = a\n.b\n.c();\n',
    'outer: while (1) { inner: for (;;) { continue outer; } }\n',
    'x = function* () { yield\na; };\n',
    'if (a) function f3() {}\n',
    'x = { get [a]() { return 1; }, set [b](v) {} };\n',
    'x = (a = 1) => a;\n',
    'x = ([a, b]) => a + b;\n',
    'x = ({a: {b}}) => b;\n',
    'x = async () => { for await (const y of z) {} };\n',
    'x = a\n++\nb\n',
    'x = /a/g\n.test(b)\n',
    'x = 1.5.toFixed(1) + 1..toString() + 1 .toString();\n',
    'x = 0.1e-5 + 0E0 + 0x0n;\n',
    "x = '\\0' + '\\x00' + '\\u{10FFFF}';\n",
    'a = ;\n',
    'if (a b) c;\n',
    'x = `unclosed;\n',
    'x = 1 2;\n',
    "x = 'unclosed\n",
    'function () {}\n',
    'return 1;\n',
    'break;\n',
    'x = { a: 1 b: 2 };\n',
    'throw\nx;\n',
    "import a from './a.js';\nimport * as b from \"b.js\";\nimport c, {d, e as f, \"g-h\" as g} from 'c.js';\n",
    "import 'side.js';\nimport x, * as y from 'z.js';\n",
    "export const a = 1, b = 2;\nexport function c() {}\nexport async function d() { await e(); }\nexport class F {}\n",
    "const a = 1, b = 2, d = 3;\nexport {a, b as c, d as default};\nexport {e} from './e.js';\nexport * from 'f.js';\nexport * as g from 'g.js';\n",
    "export default function () { return 1; }\n",
    "export default class extends A {}\n",
    "export default a ? b : c;\n",
    "export const x = await load();\nfor await (const y of z) {}\nconsole.log(import.meta.url);\n",
    "import {default as x} from 'x.js';\nexport {x as \"a b\"};\n",
    "if (a) { import b from 'b.js'; }\n",
    "export default function () {}\nexport default 1;\nexport = 2;\n",
    "import {default} from 'x.js';\n",
]


JAVASCRIPT_ORACLE = r"""
const fs = require("fs");
const acorn = require("internal/deps/acorn/acorn/dist/acorn");
const out = [];
for (const item of JSON.parse(fs.readFileSync(process.argv[2], "utf8"))) {
  const comments = [];
  try {
    const read = (sourceType) => acorn.parse(item.text, {ecmaVersion: 2022, sourceType, allowHashBang: true,
                                                         allowReturnOutsideFunction: item.body, onComment: comments});
    let tree;
    if (item.module === null) {
      try {
        tree = read("script");
      } catch (e) {
        if (!String(e.message).includes("sourceType: module")) throw e;
        comments.length = 0;
        tree = read("module");
      }
    } else {
      tree = read(item.module ? "module" : "script");
    }
    const nodes = [];
    const visit = (node) => {
      if (!node || typeof node.type !== "string") return;
      nodes.push([node.type, node.start, node.end]);
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) value.forEach(visit);
        else if (value && typeof value === "object" && typeof value.type === "string") visit(value);
      }
    };
    visit(tree);
    out.push({id: item.id, nodes, comments: comments.map(c => [c.type === "Block", c.start, c.end])});
  } catch (e) {
    out.push({id: item.id, error: String(e.message)});
  }
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""


def our_javascript(text, body, module):
    script = js.parse(text, function_body=body, module=module)
    u = utf16(text)
    return (sorted([n.type, u[n.start], u[n.end]] for n in js.walk(script.program)),
            sorted([c.block, u[c.span.start], u[c.span.end]] for c in script.comments))


def javascript_corpus():
    files = garden.working_tree(ROOT)
    kinds = garden.Tree(files).script_kinds()
    for path, text in sorted(files.items()):
        if path.endswith(".js"):
            yield path, text, False, kinds.get(path)
        elif path.endswith(".html"):
            document = html.parse(text, path)
            for k, (tag, content) in enumerate(document.scripts):
                yield f"{path} script {k}", content.value, False, html.script_type(tag) == "module"
            for k, (_, attribute) in enumerate(document.handlers):
                yield f"{path} {attribute.name} {k}", attribute.value.value, True, False
    for k, text in enumerate(JAVASCRIPT_HARD_CASES):
        yield f"case {k}", text, False, None


def test_javascript():
    items = list(javascript_corpus())
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "oracle.js").write_text(JAVASCRIPT_ORACLE, encoding="utf-8")
        (folder / "in.json").write_text(json.dumps([{"id": i, "text": t, "body": b, "module": m} for i, t, b, m in items]),
                                        encoding="utf-8")
        run = subprocess.run(["node", "--expose-internals", str(folder / "oracle.js"), str(folder / "in.json"),
                              str(folder / "out.json")], capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        check(run.returncode == 0, f"acorn, the JavaScript parser of Node, reads the corpus ({run.stderr.strip()[:200]})")
        if run.returncode:
            return
        oracle = {o["id"]: o for o in json.loads((folder / "out.json").read_text(encoding="utf-8"))}
    wrong, refused = [], []
    for ident, text, body, module in items:
        item = oracle[ident]
        try:
            mine = our_javascript(text, body, module)
        except js.JavaScriptError as ex:
            mine = str(ex)
        if "error" in item or isinstance(mine, str):
            if "error" in item and isinstance(mine, str) and ident.startswith("case "):
                refused.append(ident)
            else:
                wrong.append(f"{ident}: {item.get('error') or mine}")
            continue
        if mine != (sorted(map(list, item["nodes"])), sorted(map(list, item["comments"]))):
            wrong.append(ident)
    check(len(items) > 200 and not wrong, f"every JavaScript of the repo, the scripts and event attributes of its "
                                          f"pages, and the hard cases read as acorn reads them: every node with its "
                                          f"type and place, and the comments, in UTF-16 ({len(items)} pieces, "
                                          f"{wrong[:3]})")
    check(len(refused) == 18, f"the 18 invalid hard cases are refused by both readers ({len(refused)})")


test_yaml()
test_powershell()
test_javascript()
print(f"{len(failures)} failure(s)" if failures else "ok    the readers agree with the oracles")
sys.exit(1 if failures else 0)
