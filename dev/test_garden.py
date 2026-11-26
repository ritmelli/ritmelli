import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
_spec = importlib.util.spec_from_file_location("garden", ROOT / "dev" / "garden.py")
garden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(garden)
import workflow_yaml

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


ENGINE = "try:\n    import fora\nexcept ImportError:\n    fora = None\n\n\nclass Engine:\n    def _inside(self):\n        pass\n"
PERMISSAO = 'OUT_OF_REPO = (\n    ("GET", "/api/a"),\n)\n'
SERVER = "class App:\n    def _state(self):\n        pass\n"
HOOKS_BASE = {"engine.py": ENGINE, "permissao.py": PERMISSAO, "server.py": SERVER, "comandos.py": "x = 1\n"}
WORKFLOW = ("name: W\non:\n  push:\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - name: S\n"
            "        shell: python3 {0}\n        run: |\n          try:\n              pass\n{handler}")
INDEX = "<html>\n<script>\nlet a = 1;\n</script>\n</html>\n"
AGENTS_OK = "# AGENTS.md\n\n- A rule that `testa_i18n` holds.\n"

CASES = {
    "comment_lines": [
        ("python", {"a.py": "x = '#not a comment'\n"}, {"a.py": "x = 1  # a comment\n"}),
        ("python shebang and encoding", {"a.py": "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nx = 1\n"},
         {"a.py": "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n# why\nx = 1\n"}),
        ("python manual line", {"dev/a.py": "# manual: python dev/a.py precisa de um microfone\n"},
         {"dev/a.py": "# manual: python dev/a.py precisa de um microfone\n# and more\n"}),
        ("js", {"a.js": "const u = 'http://x'; const r = /a\\/\\/b/;\n"}, {"a.js": "const u = 1; // why\n"}),
        ("js block", {"a.js": "const t = `/* not */`;\n"}, {"a.js": "/* one\n   two */\nconst t = 1;\n"}, 2),
        ("js block marker", {"a.js": "/* DECK-JS-INICIO */\nx();\n/* DECK-JS-FIM */\n"},
         {"a.js": "/* DECK-JS-INICIO */\nx(); /* why */\n/* DECK-JS-FIM */\n"}),
        ("css", {"a.css": "a { content: '/* no */'; }\n"}, {"a.css": "a { color: red; } /* why */\n"}),
        ("css generated block", {"a.css": "/* molduras:inicio (gravado) */\na {}\n/* molduras:fim */\n"},
         {"a.css": "/* molduras:inicio (gravado) */\n/* hand */\na {}\n/* molduras:fim */\n"}),
        ("powershell", {"a.ps1": "$a = 'x # y'\n$b = \"#$a\"\n"}, {"a.ps1": "$a = 1 # why\n"}),
        ("powershell block", {"a.ps1": "$a = @'\n# inside a here-string\n'@\n"}, {"a.ps1": "<#\n why\n#>\n$a = 1\n"}, 3),
        ("psd1", {"a.psd1": "@{ A = '#' }\n"}, {"a.psd1": "# why\n@{ A = 1 }\n"}),
        ("yml", {"a.yml": "a: 'b # c'\n"}, {"a.yml": "a: b  # why\n"}),
        ("yml pin", {"a.yml": "steps:\n  - uses: o/r@" + "a" * 40 + " # v3.2\n"},
         {"a.yml": "steps:\n  - uses: o/r@v3 # why\n"}),
        ("yml run block in bash", {"a.yml": "jobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n"
                                            "          echo \"## title\"\n"},
         {"a.yml": "jobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n          # why\n"
                   "          echo hi\n"}),
        ("yml run block in python", {"a.yml": "steps:\n  - shell: python3 {0}\n    run: |\n      x = '# no'\n"},
         {"a.yml": "steps:\n  - shell: python3 {0}\n    run: |\n      x = 1  # why\n"}),
        ("cpp", {"a.cpp": "#pragma once\n#include <x>\nconst char* s = \"// no\";\n"},
         {"a.cpp": "int a = 1; // why\n"}),
        ("h", {"a.h": "#pragma once\n"}, {"a.h": "#pragma once\n/* why */\n"}),
        ("rc", {"a.rc": "#pragma code_page(65001)\n#include \"v.h\"\n"}, {"a.rc": "// why\n#include \"v.h\"\n"}),
        ("iss", {"a.iss": "#define A \"x\"\n[Setup]\nAppName=A\n[Code]\nvar S: String;\nbegin S := '{#A}'; end;\n"},
         {"a.iss": "; why\n#define A \"x\"\n[Setup]\nAppName=A\n[Code]\nvar S: String;\nbegin S := '{#A}'; end;\n"}),
        ("iss pascal brace", {"a.iss": "[Code]\nbegin end;\n"}, {"a.iss": "[Code]\nbegin { why } end;\n"}),
        ("iss pascal line", {"a.iss": "[Code]\nbegin S := 'a // b'; end;\n"}, {"a.iss": "[Code]\nbegin end; // why\n"}),
        ("isl", {"a.isl": "[Messages]\nA=b ; c\n"}, {"a.isl": "; why\n[Messages]\n"}),
        ("bat", {"a.bat": "@echo off\necho remove\n"}, {"a.bat": "@echo off\nrem why\n"}),
        ("bat double colon", {"a.bat": "echo a::b\n"}, {"a.bat": ":: why\necho a::b\n"}),
        ("html", {"a.html": "<!-- inline-script: a.js -->\n<p>x</p>\n"}, {"a.html": "<!-- why -->\n<p>x</p>\n"}),
        ("html inline js and css", {"a.html": "<script>\nlet a = '//';\n</script>\n<style>\na {}\n</style>\n"},
         {"a.html": "<script>\nlet a = 1; // why\n</script>\n<style>\na {} /* why */\n</style>\n"}, 2),
        ("spec", {"a.spec": "a = Analysis(['x'])\n"}, {"a.spec": "# why\na = Analysis(['x'])\n"}),
        ("sh", {"a.sh": "#!/usr/bin/env bash\necho \"#x\"\n"}, {"a.sh": "#!/usr/bin/env bash\necho x # why\n"}),
        ("toml", {"a.toml": "a = \"#b\"\n"}, {"a.toml": "# why\na = 1\n"}),
    ],
    "docstring_lines": [
        ("a function", {"a.py": "def f():\n    return '''not a docstring'''\n"},
         {"a.py": "def f():\n    '''Why.'''\n    return 1\n"}),
    ],
    "suppressions": [
        ("noqa", {"a.py": "x = 'noqa'\n"}, {"a.py": "x = 1  # noqa: E501\n"}),
        ("type: ignore", {"a.py": "x: int = 1\n"}, {"a.py": "x: int = 'a'  # type: ignore\n"}),
        ("pragma: no cover", {"a.py": "def f():\n    pass\n"}, {"a.py": "def f():  # pragma: no cover\n    pass\n"}),
        ("eslint-disable", {"a.js": "const eslint = 1;\n"}, {"a.js": "// eslint-disable-next-line\nconst a = 1;\n"}),
        ("pragma warning", {"a.cpp": "#pragma once\n"}, {"a.cpp": "#pragma warning(disable: 4996)\n"}),
        ("continue-on-error", {"a.yml": "steps:\n  - run: echo continue-on-error\n"},
         {"a.yml": "steps:\n  - run: echo\n    continue-on-error: true\n"}),
        ("SilentlyContinue", {"a.ps1": "$ProgressPreference = 'SilentlyContinue'\n"},
         {"a.ps1": "Get-Item x -ErrorAction SilentlyContinue\n"}),
        ("SilentlyContinue in a Python string", {"a.py": "ps = 'Get-Item x'\n"},
         {"a.py": "ps = 'Get-Item x -ErrorAction SilentlyContinue'\n"}),
    ],
    "sleeps_app": [
        ("time.sleep", {"a.py": "import time\ntime.perf_counter()\n"}, {"a.py": "import time\ntime.sleep(1)\n"}),
        ("an alias", {"a.py": "import time as t\nt.monotonic()\n"}, {"a.py": "import time as t\nt.sleep(1)\n"}),
        ("from time import sleep", {"a.py": "from time import monotonic\n"},
         {"a.py": "from time import sleep\nsleep(1)\n"}),
        ("asyncio.sleep", {"a.py": "import asyncio\n"}, {"a.py": "import asyncio\nawait asyncio.sleep(1)\n"}),
        ("Start-Sleep", {"a.ps1": "# Start-Sleep in a comment\n"}, {"a.ps1": "Start-Sleep 1\n"}),
        ("in microfone/", {"dev/a.py": "import time\ntime.sleep(1)\n"},
         {"dev/a.py": "import time\ntime.sleep(1)\n", "microfone/a.py": "import time\ntime.sleep(1)\n"}),
    ],
    "sleeps_dev": [
        ("in dev/", {"a.py": "import time\ntime.sleep(1)\n"},
         {"a.py": "import time\ntime.sleep(1)\n", "dev/a.py": "import time\ntime.sleep(1)\n"}),
        ("a test", {"instalador/a.ps1": "Start-Sleep 1\n"},
         {"instalador/a.ps1": "Start-Sleep 1\n", "instalador/testa-x.ps1": "Start-Sleep 1\n"}),
    ],
    "theme_timers": [
        ("setTimeout", {"themes/t/a.js": "// setTimeout(f, 1)\nconst s = 'setTimeout(';\n"},
         {"themes/t/a.js": "setTimeout(f, 1);\n"}),
        ("setInterval in index.html", {"themes/t/index.html": "<script>\nf();\n</script>\n"},
         {"themes/t/index.html": "<script>\nsetInterval(f, 1);\n</script>\n"}),
        ("requestIdleCallback", {"gallery/a.js": "setTimeout(f, 1);\n"}, {"themes/t/a.js": "requestIdleCallback(f);\n"}),
    ],
    "theme_animation_frames": [
        ("requestAnimationFrame", {"themes/t/a.js": "setTimeout(f, 1);\n"}, {"themes/t/a.js": "requestAnimationFrame(f);\n"}),
    ],
    "retries": [
        ("a loop with try and a sleep", {"a.py": "import time\nwhile True:\n    try:\n        f()\n    except OSError:\n"
                                                 "        return\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile True:\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        time.sleep(1)\n"}),
        ("the sleep in a nested function", {"a.py": "import time\nfor x in y:\n    try:\n        f()\n    except OSError:\n"
                                                    "        pass\n    def g():\n        time.sleep(1)\n"},
         {"a.py": "import time\nfor x in y:\n    try:\n        f()\n    except OSError:\n        pass\n    time.sleep(1)\n"}),
        ("an outer loop around a retry", {"a.py": "import time\nfor a in b:\n    x = 1\n"},
         {"a.py": "import time\nfor a in b:\n    while True:\n        try:\n            f()\n        except OSError:\n"
                  "            time.sleep(1)\n"}),
        ("powershell", {"a.ps1": "for ($i = 0; $i -lt 3; $i++) { Start-Sleep 1 }\n"},
         {"a.ps1": "for ($i = 0; $i -lt 3; $i++) { try { f } catch { }; Start-Sleep 1 }\n"}),
        ("powershell in a Python string", {"a.py": "ps = 'do{Start-Sleep 1}while($a)'\n"},
         {"a.py": "ps = 'do{Start-Sleep 1;try{f}catch{}}while($a)'\n"}),
    ],
    "broad_excepts": [
        ("except Exception", {"a.py": "try:\n    f()\nexcept OSError:\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept Exception:\n    pass\n"}),
        ("a bare except", {"a.py": "try:\n    f()\nexcept (OSError, ValueError):\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept:\n    pass\n"}),
        ("a tuple with Exception", {"a.py": "try:\n    f()\nexcept (OSError, ValueError):\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept (OSError, Exception):\n    pass\n"}),
        ("BaseException", {"a.py": "x = BaseException\n"}, {"a.py": "try:\n    f()\nexcept BaseException:\n    raise\n"}),
        ("the Python of a workflow", {".github/workflows/w.yml": WORKFLOW.replace("{handler}", "          except OSError:\n"
                                                                                       "              pass\n")},
         {".github/workflows/w.yml": WORKFLOW.replace("{handler}", "          except Exception:\n              pass\n")}),
        ("pascal", {"a.iss": "[Setup]\nA=except\n[Code]\nbegin end;\n"},
         {"a.iss": "[Code]\nbegin try f; except end; end;\n"}),
    ],
    "skipped_tests": [
        ("skipIf", {"dev/t.py": "import unittest\n@unittest.skipIf(X, 'no X (#12)')\nclass T: pass\n"},
         {"dev/t.py": "import unittest\n@unittest.skipIf(X, 'no X')\nclass T: pass\n"}),
        ("skipTest", {"dev/t.py": "skip = 1\n"}, {"dev/t.py": "def t(self):\n    self.skipTest('no')\n"}),
        ("expectedFailure", {"dev/t.py": "from unittest import TestCase\n"},
         {"dev/t.py": "from unittest import expectedFailure\n@expectedFailure\ndef t():\n    pass\n"}),
        ("ficou de fora", {"dev/t.py": "print('--   o guard ficou de fora: #12')\nr = r'^--\\s.*ficou de fora'\n"},
         {"dev/t.py": "print(f'--   o guard ficou de fora: {e}')\n"}),
        ("ficou de fora in a workflow", {"a.yml": "steps:\n  - run: echo ok\n"},
         {"a.yml": "steps:\n  - run: echo 'o pedal ficou de fora'\n"}),
    ],
    "todo_markers": [
        ("in a comment", {"a.py": "PIXELS = ['XXX', '.X.']\n", "a.md": "o METODO e o MÉTODO\n"},
         {"a.py": "x = 1  # TODO later\n"}),
        ("in a .md", {"a.md": "TODOS os casos\n"}, {"a.md": "FIXME: this\n"}),
    ],
    "prose_justifications": [
        ("in a comment", {"a.py": "print('using the old one for now')\n"}, {"a.py": "x = 1  # for now\n"}),
        ("in a docstring", {"a.py": "def f():\n    '''Accepted risk: #12.'''\n"},
         {"a.py": "def f():\n    '''Accepted risk.'''\n"}),
        ("in a .md", {"a.md": "Sem teste: issue #5\n"}, {"a.md": "Sem teste.\n"}),
    ],
    "non_ascii_identifiers": [
        ("a name", {"a.py": "x = 'laço'\n"}, {"a.py": "laço = 1\n"}),
        ("an argument", {"a.py": "def f(a):\n    pass\n"}, {"a.py": "def f(ação):\n    pass\n"}),
    ],
    "engine_hooks": [
        ("a new hook", HOOKS_BASE, {**HOOKS_BASE, "engine.py": ENGINE + "\n\ndef fora_extra():\n    pass\n"}),
    ],
    "out_of_repo_routes": [
        ("a new route", {**HOOKS_BASE, "server.py": SERVER + "R = ('GET', '/api/c')\n"},
         {**HOOKS_BASE, "permissao.py": PERMISSAO.replace("),\n)", "),\n    (\"GET\", \"/api/b\"),\n)")}),
    ],
    "engine_reaches": [
        ("a reach from another module", HOOKS_BASE, {**HOOKS_BASE, "comandos.py": "def f(e):\n    return e._inside\n"}),
    ],
    "app_reaches": [
        ("a reach from another module", HOOKS_BASE, {**HOOKS_BASE, "comandos.py": "def f(a):\n    return a._state\n"}),
    ],
    "theme_inline_lines": [
        ("an inline line", {"themes/ritmelli/index.html": INDEX},
         {"themes/ritmelli/index.html": INDEX.replace("let a = 1;\n", "let a = 1;\nlet b = 2;\n")}),
        ("a style block", {"themes/ritmelli/index.html": INDEX + "<script src=\"b.js\"></script>\n"},
         {"themes/ritmelli/index.html": INDEX + "<style>\na {}\n</style>\n"}),
    ],
    "engine_py_lines": [("a line", {"engine.py": "x = 1\n"}, {"engine.py": "x = 1\ny = 2\n"})],
    "server_py_lines": [("a line", {"server.py": "x = 1\n"}, {"server.py": "x = 1\ny = 2\n"})],
    "index_html_lines": [("a line", {"themes/ritmelli/index.html": "<p>\n"},
                          {"themes/ritmelli/index.html": "<p>\n<p>\n"})],
    "agents_md_lines": [("a line", {"AGENTS.md": "# A\n"}, {"AGENTS.md": "# A\nB\n"})],
    "agents_rules_without_check": [
        ("a rule with a name that is no check", {"AGENTS.md": AGENTS_OK},
         {"AGENTS.md": AGENTS_OK + "- A rule about `yt_fora.py` and `monta.yml`.\n"}),
        ("a paragraph", {"AGENTS.md": AGENTS_OK + "\nA paragraph that `dev/garden.py` holds.\n"},
         {"AGENTS.md": AGENTS_OK + "\nA paragraph with no check.\n"}),
        ("a job of the testa.yml", {"AGENTS.md": AGENTS_OK + "- The `Testa o PR` check.\n",
                                    ".github/workflows/testa.yml": "on:\n  push:\njobs:\n  x:\n    name: Testa o PR\n"},
         {"AGENTS.md": AGENTS_OK + "- The `Testa o PR` check.\n"}),
    ],
}

KNOWN_MISSES_ISSUE = "garden: count the catch-all handlers of PowerShell and JavaScript"
KNOWN_MISSES = [
    ("broad_excepts", "a PowerShell catch with no type", {"a.ps1": "try { f } catch { }\n"}),
    ("broad_excepts", "a JavaScript catch", {"a.js": "try { f(); } catch (e) { }\n"}),
    ("retries", "a JavaScript callback that reschedules itself after a failure",
     {"themes/t/a.js": "function go() { fetch(u).catch(() => setTimeout(go, 3000)); }\n"}),
]


def count(name, files):
    return garden.count_of(garden.COUNTERS[name](garden.Tree(files)))


EXPECTED_HARMLESS = {"theme_inline_lines": 1, "engine_py_lines": 1, "server_py_lines": 1, "index_html_lines": 1,
                     "agents_md_lines": 1}


def test_counters():
    check(set(CASES) == set(garden.COUNTERS), f"every counter has its cases (missing: "
          f"{sorted(set(garden.COUNTERS) - set(CASES))}, unknown: {sorted(set(CASES) - set(garden.COUNTERS))})")
    for name, cases in CASES.items():
        for label, harmless, weedy, *delta in cases:
            before, after = count(name, harmless), count(name, weedy)
            expected = count(name, HOOKS_BASE) if harmless is HOOKS_BASE or name in (
                "engine_hooks", "out_of_repo_routes", "engine_reaches", "app_reaches") else EXPECTED_HARMLESS.get(name, 0)
            check(before == expected, f"{name}, {label}: the harmless case counts {expected} ({before})")
            step = delta[0] if delta else 1
            check(after == before + step, f"{name}, {label}: the weed counts {step} ({before} -> {after})")


def test_known_misses():
    for name, label, files in KNOWN_MISSES:
        check(count(name, files) == 0, f"known miss ({KNOWN_MISSES_ISSUE}): {name} does not count {label}; when it "
              f"does, move the case to CASES")


def test_check():
    ok, _ = garden.check({"a": [("x.py", 1)]}, {"a": 1}, {"a": 1})
    check(ok == [], "the count equal to the ceiling passes")
    over, _ = garden.check({"a": [("x.py", 1), ("x.py", 2)]}, {"a": 1}, {"a": 1}, {"x.py": {2}})
    check(len(over) == 1 and over[0].startswith("a: 2, over the ceiling of 1") and "x.py:2" in over[0],
          f"over the ceiling fails with the counter's name and the new item ({over})")
    under, _ = garden.check({"a": []}, {"a": 1}, {"a": 1})
    check(len(under) == 1 and "lower \"a\"" in under[0], f"under the ceiling fails until it is lowered ({under})")
    raised, _ = garden.check({"a": [("x.py", 1), ("x.py", 2)]}, {"a": 2}, {"a": 1})
    check(len(raised) == 1 and "went up from 1 to 2" in raised[0],
          f"a ceiling raised with the weeds fails against the base ({raised})")
    new, _ = garden.check({"a": 3}, {}, None)
    check(len(new) == 1 and "no ceiling" in new[0], "a counter with no ceiling fails")
    stale, _ = garden.check({}, {"gone": 1}, None)
    check(len(stale) == 1 and "for no counter" in stale[0], "a ceiling with no counter fails")
    _, summary = garden.check({"a": [("x.py", 1)] * 3, "b": 2, "c": 5}, {"a": 3, "b": 2, "c": 5},
                              {"a": 4, "b": 2, "c": 4})
    check(summary == ["-- summary: garden a: 3 (-1 against the base)", "-- summary: garden c: 5 (+1 against the base)"],
          f"one summary line per counter that changed, against the base ({summary})")
    _, quiet = garden.check({"a": 1}, {"a": 1}, {"a": 1})
    check(quiet == ["-- summary: garden: no counter changed against the base (1 counters)"],
          f"with no change, one line says so ({quiet})")


def test_acceptance():
    files = {"a.py": "import time\n\n\ndef f():\n    try:\n        g()\n    except OSError:\n        pass\n"}
    weedy = {"a.py": "import time\n\n\ndef f():\n    # wait for it\n    time.sleep(1)\n    try:\n        g()\n"
                     "    except Exception:\n        pass\n"}
    counts = garden.scoreboard(files)
    ceilings = {k: garden.count_of(v) for k, v in counts.items()}
    failures_found, _ = garden.check(garden.scoreboard(weedy), ceilings, ceilings, {"a.py": {5, 6, 9}})
    names = {f.split(":")[0] for f in failures_found}
    check(names == {"comment_lines", "sleeps_app", "broad_excepts"},
          f"a comment, a time.sleep and an except Exception fail with the three names ({sorted(names)})")
    raised = dict(ceilings, comment_lines=ceilings["comment_lines"] + 1)
    names = {f.split(":")[0] for f in garden.check(garden.scoreboard(weedy), raised, ceilings, {})[0]}
    check("comment_lines" in names, "the ceiling raised along with the comment still fails")


def test_description():
    good = "The problem.\n\n**How it was proven**\n- `python dev/garden.py` fails on the base.\n"
    check(garden.description_problems(good) == [], "a description with a proof section passes")
    check(garden.description_problems("Proof: `python x.py` passes.") == [], "a proof line with its content passes")
    check(garden.description_problems("## Proof\n\nIt works.\n") != [], "a proof section with no run, test or print fails")
    check(garden.description_problems("The problem.\n") != [], "a description with no proof section fails")
    prose = good + "\nThe rest stays for now.\n"
    check(any("for now" in p for p in garden.description_problems(prose)), "a prose phrase with no issue fails")
    check(garden.description_problems(good + "\nThe rest stays for now (#250).\n") == [],
          "a prose phrase with its issue passes")
    check(garden.pr_number("pull_request", {"pull_request": {"number": 7}}) == 7, "the PR number of a pull_request")
    check(garden.pr_number("merge_group", {"merge_group": {"head_ref": "refs/heads/gh-readonly-queue/main/pr-246-"
                                                           + "a" * 40}}) == 246, "the PR number of a merge_group entry")
    check(garden.pr_number("push", {}) is None, "no PR on a push")


def workflow_problems(text):
    try:
        doc = workflow_yaml.loads(text, name="testa.yml")
    except workflow_yaml.YamlError as ex:
        return [f"the workflow does not read: {ex}"]
    job = (doc.get("jobs") or {}).get("testes") or {}
    step = workflow_yaml.find_step(job, "PR description")
    if step is None:
        return ["the testes job has no single \"PR description\" step"]
    problems = []
    if "python dev/garden.py --pr-description" not in (step.get("run") or ""):
        problems.append("the step does not run dev/garden.py --pr-description")
    if step.get("if") not in (None, "${{ !cancelled() }}"):
        problems.append(f"the step skips on some event ({step.get('if')})")
    if (step.get("env") or {}).get("GH_TOKEN") != "${{ github.token }}":
        problems.append("the step has no GH_TOKEN to read the API")
    if (job.get("permissions") or {}).get("pull-requests") != "read":
        problems.append("the testes job can't read the PR")
    if job.get("if") != "github.event_name != 'push'":
        problems.append(f"the testes job skips on the PR or the queue ({job.get('if')})")
    on = doc.get("on") or {}
    if "pull_request" not in on or "merge_group" not in on:
        problems.append("the workflow does not run on the PR and the queue")
    if any(s.get("continue-on-error") for s in workflow_yaml.job_steps(job)):
        problems.append("a step of the testes job fails quietly")
    return problems


WORKFLOW_MUTANTS = [
    ("the step skipped in the queue", "      - name: PR description\n        if: ${{ !cancelled() }}",
     "      - name: PR description\n        if: ${{ !cancelled() && github.event_name != 'merge_group' }}"),
    ("the step renamed", "      - name: PR description", "      - name: PR text"),
    ("no token", "          GH_TOKEN: ${{ github.token }}\n        run: python dev/garden.py --pr-description",
     "        run: python dev/garden.py --pr-description"),
    ("no permission to read the PR", "      contents: read\n      pull-requests: read\n    outputs:",
     "      contents: read\n    outputs:"),
    ("another command", "run: python dev/garden.py --pr-description", "run: python dev/garden.py"),
    ("the step quiet on failure", "        run: python dev/garden.py --pr-description",
     "        continue-on-error: true\n        run: python dev/garden.py --pr-description"),
    ("the job skipped in the queue", "    name: Testes\n    if: github.event_name != 'push'",
     "    name: Testes\n    if: github.event_name == 'pull_request'"),
    ("the queue trigger gone", "  merge_group:\n", ""),
]


def test_workflow_mutants(text):
    for label, old, new in WORKFLOW_MUTANTS:
        found = text.count(old) == 1
        check(found and workflow_problems(text.replace(old, new)) != [],
              f"the workflow check catches the mutant: {label}" + ("" if found else " (its text is not in testa.yml)"))


def test_stdlib():
    tudo = garden.load_dev_module("testa_tudo")
    check("dev/garden.py" in tudo.STDLIB and "dev/test_garden.py" in tudo.STDLIB,
          "dev/garden.py and dev/test_garden.py run in the STDLIB of the required check")
    check(json.loads((ROOT / "dev" / "garden.json").read_text(encoding="utf-8")).keys() == garden.COUNTERS.keys(),
          "dev/garden.json has one ceiling per counter")


test_counters()
test_known_misses()
test_check()
test_acceptance()
test_description()
WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "testa.yml").read_text(encoding="utf-8")
problems = workflow_problems(WORKFLOW_TEXT)
check(problems == [], f"the PR description step runs in the required check on every PR and queue entry ({problems})")
test_workflow_mutants(WORKFLOW_TEXT)
test_stdlib()
print(f"{len(failures)} failure(s)" if failures else "ok    all garden cases")
sys.exit(1 if failures else 0)
