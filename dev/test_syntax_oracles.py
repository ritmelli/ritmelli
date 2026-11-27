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


test_yaml()
test_powershell()
print(f"{len(failures)} failure(s)" if failures else "ok    the readers agree with the oracles")
sys.exit(1 if failures else 0)
