import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
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


ENGINE = "try:\n    import fora\nexcept ImportError:\n    fora = None\n\n\nclass Engine:\n    def _inside(self):\n        pass\n\n    def __init__(self):\n        self.pos = 0\n"
PERMISSAO = 'OUT_OF_REPO = (\n    ("GET", "/api/a"),\n)\n'
SERVER = ("class App:\n    def __init__(self):\n        self.queue = []\n\n    def _state(self):\n        pass\n\n\n"
          "class Library:\n    def _books(self):\n        return self._books\n")
AUTOMATICO = "class Automatico:\n    def _round(self):\n        pass\n"
HOOKS_BASE = {"engine.py": ENGINE, "permissao.py": PERMISSAO, "server.py": SERVER, "automatico.py": AUTOMATICO,
              "comandos.py": "x = 1\n"}
WORKFLOW = ("name: W\non:\n  push:\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - name: S\n"
            "        shell: python3 {0}\n        run: |\n          try:\n              pass\n{handler}")
INDEX = "<html>\n<script>\nlet a = 1;\n</script>\n</html>\n"
PY_STEP = ("jobs:\n  JOB:\n    runs-on: ubuntu-24.04\n    steps:\n      - name: S\n        shell: python3 {0}\n"
           "        run: |\n          import time\n          time.sleep(1)\n")
TUDO = ('STDLIB = ["dev/testa_x.py"]\nCOMPLETO = list(STDLIB)\nLONG_TESTS = {}\nMICROFONE = []\nTELA = []\n'
        'PASSOS = {}\n')
AGENTS_OK ="# AGENTS.md\n\n- A rule that `testa_i18n` holds.\n"

MOLDURAS = next(iter(garden.GENERATED_MARKERS))
RUN_PS = "subprocess.run([POWERSHELL, '-Command', ps])\n"
ATTEMPT = "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
ATTEMPT_PS = "function attempt { try { f } catch { $null } }\n"
NESTED_FSTRING = ("import subprocess\nsubprocess.run(['powershell', '-Command', "
                  "f\"Write-Output '{f\"{\"}\"}\"}'{TAIL}\"])\n")
ASYNC_RETRY = ("import asyncio\nasync def attempt():\n    try:\n        return await f()\n    except OSError:\n"
               "        return None\nasync def main():\n    while True:\n        if await CALL():\n"
               "            break\n        await asyncio.sleep(1)\n")
ACTION = "runs:\n  using: composite\n  steps:\n    - shell: pwsh\n      run: RUN\n"
ALIASED_JOB = "jobs:\n  test: &t\n    runs-on: windows-2025\n    steps:\n      - run: RUN\n  build: *t\n"
COMPOSITE_PYTHON_STEP = "runs:\n  using: composite\n  steps:\n    - shell: python\n      run: |\nDOC        x = 1\n"

CASES = {
    "comment_lines": [
        ("a quoted run that goes on to the next line",
         {"action.yml": "runs:\n  steps:\n    - shell: pwsh\n      run: \"Write-Output 'a #b'\n        'c'\"\n"},
         {"action.yml": "runs:\n  steps:\n    - shell: pwsh\n      run: \"Write-Output 'a #b'\n        # why\"\n"}),
        ("a version comment after a tag is no pin", {"a.yml": "steps:\n  - uses: o/r@" + "a" * 40 + " # v3.2\n"},
         {"a.yml": "steps:\n  - uses: o/r@v3 # v3.2\n"}),
        ("a uses: inside a step name is no pin", {"a.yml": "steps:\n  - uses: o/r@" + "a" * 40 + " # v3.2\n"},
         {"a.yml": "steps:\n  - name: 'uses: o/r@" + "a" * 40 + "' # v3.2\n"}),
        ("python", {"a.py": "x = '#not a comment'\n"}, {"a.py": "x = 1  # a comment\n"}),
        ("python shebang and encoding", {"a.py": "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nx = 1\n"},
         {"a.py": "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n# why\nx = 1\n"}),
        ("python manual line", {"dev/a.py": "# manual: python dev/a.py precisa de um microfone\n"},
         {"dev/a.py": "# manual: python dev/a.py precisa de um microfone\n# and more\n"}),
        ("js", {"a.js": "const u = 'http://x'; const r = /a\\/\\/b/;\n"}, {"a.js": "const u = 1; // why\n"}),
        ("js block", {"a.js": "const t = `/* not */`;\n"}, {"a.js": "/* one\n   two */\nconst t = 1;\n"}, 2),
        ("js block marker", {"a.js": "/* DECK-JS-INICIO */\nx();\n/* DECK-JS-FIM */\n"},
         {"a.js": "/* DECK-JS-INICIO */\nx(); /* why */\n/* DECK-JS-FIM */\n"}),
        ("prose on the marker's own line", {"a.js": "/* DECK-JS-INICIO */\nx();\n/* DECK-JS-FIM */\n"},
         {"a.js": "/* DECK-JS-INICIO: the decks in pixel art */\nx();\n/* DECK-JS-FIM */\n"}),
        ("prose under a block marker", {"a.js": "/* DECK-JS-INICIO */\nx();\n"},
         {"a.js": "/* DECK-JS-INICIO\n   the deck, and why it lives here */\nx();\n"}),
        ("css", {"a.css": "a { content: '/* no */'; }\n"}, {"a.css": "a { color: red; } /* why */\n"}),
        ("css generated block", {"a.css": f"/* {MOLDURAS} */\na {{}}\n/* molduras:fim */\n"},
         {"a.css": f"/* {MOLDURAS} */\n/* hand */\na {{}}\n/* molduras:fim */\n"}),
        ("a license header after a blank line", {"a.py": "\n# SPDX-License-Identifier: GPL-3.0-or-later\nx = 1\n"},
         {"a.py": "\n# SPDX-License-Identifier: GPL-3.0-or-later\nx = 1  # why\n"}),
        ("a license header", {"a.py": "# SPDX-License-Identifier: GPL-3.0-or-later\nx = 1\n"},
         {"a.py": "# SPDX-License-Identifier: GPL-3.0-or-later\n# why\nx = 1\n"}),
        ("powershell", {"a.ps1": "$a = 'x # y'\n$b = \"#$a\"\n"}, {"a.ps1": "$a = 1 # why\n"}),
        ("properties", {"a.properties": "key=value # not a comment\nother=! nor this\n"},
         {"a.properties": "# a comment\n! another\nkey=value\n"}, 2),
        ("powershell block", {"a.ps1": "$a = @'\n# inside a here-string\n'@\n"}, {"a.ps1": "<#\n why\n#>\n$a = 1\n"}, 3),
        ("psd1", {"a.psd1": "@{ A = '#' }\n"}, {"a.psd1": "# why\n@{ A = 1 }\n"}),
        ("yml", {"a.yml": "a: 'b # c'\n"}, {"a.yml": "a: b  # why\n"}),
        ("yml pin", {"a.yml": "steps:\n  - uses: o/r@" + "a" * 40 + " # v3.2\n"},
         {"a.yml": "steps:\n  - uses: o/r@v3 # why\n"}),
        ("yml run block in bash", {".github/workflows/a.yml": "jobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n"
                                            "          echo \"## title\"\n"},
         {".github/workflows/a.yml": "jobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n          # why\n"
                   "          echo hi\n"}),
        ("yml run block in python", {"action.yml": "runs:\n  steps:\n    - shell: python3 {0}\n      run: |\n        x = '# no'\n"},
         {"action.yml": "runs:\n  steps:\n    - shell: python3 {0}\n      run: |\n        x = 1  # why\n"}),
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
        ("html", {"a.html": "<p>x</p>\n"}, {"a.html": "<!-- why -->\n<p>x</p>\n"}),
        ("an i18n-ok marker with prose", {"a.py": "x = 1  # i18n-ok\n"}, {"a.py": "x = 1  # i18n-ok: workaround\n"}),
        ("the inline-script marker is a comment", {"a.html": "<p>x</p>\n"},
         {"a.html": "<!-- inline-script: script-failed.js -->\n"}),
        ("html inline js and css", {"a.html": "<script>\nlet a = '//';\n</script>\n<style>\na {}\n</style>\n"},
         {"a.html": "<script>\nlet a = 1; // why\n</script>\n<style>\na {} /* why */\n</style>\n"}, 2),
        ("spec", {"a.spec": "a = Analysis(['x'])\n"}, {"a.spec": "# why\na = Analysis(['x'])\n"}),
        ("sh", {"a.sh": "#!/usr/bin/env bash\necho \"#x\"\n"}, {"a.sh": "#!/usr/bin/env bash\necho x # why\n"}),
        ("toml", {"a.toml": "a = \"#b\"\n"}, {"a.toml": "# why\na = 1\n"}),
    ],
    "docstring_lines": [
        ("a function", {"a.py": "def f():\n    return '''not a docstring'''\n"},
         {"a.py": "def f():\n    '''Why.'''\n    return 1\n"}),
        ("a docstring in a Python step of a composite action", {"tools/a/action.yml": COMPOSITE_PYTHON_STEP.replace("DOC", "")},
         {"tools/a/action.yml": COMPOSITE_PYTHON_STEP.replace("DOC", "        '''Why the step reads it.'''\n")}),
    ],
    "suppressions": [
        ("-EA 0", {"a.ps1": "Get-Item x -EA Stop\n"}, {"a.ps1": "Get-Item x -EA 0\n"}),
        ("-ErrorAction:Ignore", {"a.ps1": "Get-Item x -ErrorAction:Stop\n"}, {"a.ps1": "Get-Item x -ErrorAction:Ignore\n"}),
        ("the error preference", {"a.ps1": "$ErrorActionPreference = 'Stop'\n"},
         {"a.ps1": "$ErrorActionPreference = 'SilentlyContinue'\n"}),
        ("the error preference of a scope", {"a.ps1": "$global:ErrorActionPreference = 'Stop'\n"},
         {"a.ps1": "$global:ErrorActionPreference = 'SilentlyContinue'\n"}),
        ("a quiet error in a cmd step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: cmd\n"
                                     "        run: powershell -Command \"Get-Item x\"\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: cmd\n"
                                     "        run: powershell -Command \"Get-Item x -ErrorAction SilentlyContinue\"\n"}),
        ("a quoted continue-on-error", {"a.yml": "steps:\n  - run: echo\n    'continue-on-error': false\n"},
         {"a.yml": "steps:\n  - run: echo\n    'continue-on-error': true\n"}),
        ("noqa", {"a.py": "x = 'noqa'\n"}, {"a.py": "x = 1  # noqa: E501\n"}),
        ("type: ignore", {"a.py": "x: int = 1\n"}, {"a.py": "x: int = 'a'  # type: ignore\n"}),
        ("pragma: no cover", {"a.py": "def f():\n    pass\n"}, {"a.py": "def f():  # pragma: no cover\n    pass\n"}),
        ("eslint-disable", {"a.js": "const eslint = 1;\n"}, {"a.js": "// eslint-disable-next-line\nconst a = 1;\n"}),
        ("pragma warning", {"a.cpp": "#pragma once\n"}, {"a.cpp": "#pragma warning(disable: 4996)\n"}),
        ("continue-on-error", {"a.yml": "steps:\n  - run: echo continue-on-error\n    continue-on-error: false\n"},
         {"a.yml": "steps:\n  - run: echo\n    continue-on-error: true\n"}),
        ("noqa in a one-line Python step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n        run: \"print(1)\"\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: \"print(1)  # noqa\"\n"}),
        ("noqa in a one-line Python step with a YAML comment",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: \"print(1)\"  # why\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: \"print(1)  # noqa\"  # why\n"}),
        ("SilentlyContinue", {"a.ps1": "$ProgressPreference = 'SilentlyContinue'\n"},
         {"a.ps1": "Get-Item x -ErrorAction SilentlyContinue\n"}),
        ("SilentlyContinue in the PowerShell a Python script runs", {"a.py": "ps = 'Get-Item x'\n" + RUN_PS},
         {"a.py": "ps = 'Get-Item x -ErrorAction SilentlyContinue'\n" + RUN_PS}),
    ],
    "sleeps_app": [
        ("Start-Sleep in a Python string that is no PowerShell", {"a.py": "x = 'Start-Sleep 1'\n"},
         {"a.py": 'import subprocess\nsubprocess.run(["powershell", "-Command", "Start-Sleep 1"])\n'}),
        ("the sleep alias", {"a.ps1": "Write-Output sleep\n"}, {"a.ps1": "sleep 1\n"}),
        ("the module name of Start-Sleep", {"a.ps1": "Microsoft.PowerShell.Utility\\Write-Output 1\n"},
         {"a.ps1": "Microsoft.PowerShell.Utility\\Start-Sleep 1\n"}),
        ("Start-Sleep by its quoted name", {"a.ps1": "& \"Write-Output\" 1\n"}, {"a.ps1": "& \"Start-Sleep\" 1\n"}),
        ("a Thread.Sleep joined to another test", {"a.ps1": "if ([System.Threading.Thread]::CurrentThread -and $x) { }\n"},
         {"a.ps1": "if ([System.Threading.Thread]::Sleep(1) -and $x) { }\n"}),
        ("Start-Sleep in a switch predicate", {"a.ps1": "switch ($x) { { $true } { 'y' } }\n"},
         {"a.ps1": "switch ($x) { { Start-Sleep 1; $true } { 'y' } }\n"}),
        ("a sleep in the iterable of a for", {"a.py": "import time\nfor item in items:\n    pass\n"},
         {"a.py": "import time\nfor item in time.sleep(1):\n    pass\n"}),
        ("a sleep in the subject of a match", {"a.py": "import time\nmatch x:\n    case _:\n        pass\n"},
         {"a.py": "import time\nmatch time.sleep(1):\n    case _:\n        pass\n"}),
        ("a sleep in the guard of a case", {"a.py": "import time\nmatch x:\n    case 1 if ready():\n        pass\n"},
         {"a.py": "import time\nmatch x:\n    case 1 if time.sleep(1):\n        pass\n"}),
        ("a script set in either branch",
         {"a.py": "import subprocess\nif flag:\n    ps = 'Get-Date'\nelse:\n    ps = 'Get-Item x'\n" + RUN_PS},
         {"a.py": "import subprocess\nif flag:\n    ps = 'Start-Sleep 1'\nelse:\n    ps = 'Get-Item x'\n" + RUN_PS}),
        ("the Thread.Sleep of PowerShell", {"a.ps1": "[System.Threading.Thread]::CurrentThread\n"},
         {"a.ps1": "[System.Threading.Thread]::Sleep(10)\n"}),
        ("time.sleep", {"a.py": "import time\ntime.perf_counter()\n"}, {"a.py": "import time\ntime.sleep(1)\n"}),
        ("an alias", {"a.py": "import time as t\nt.monotonic()\n"}, {"a.py": "import time as t\nt.sleep(1)\n"}),
        ("from time import sleep", {"a.py": "from time import monotonic\n"},
         {"a.py": "from time import sleep\nsleep(1)\n"}),
        ("asyncio.sleep", {"a.py": "import asyncio\n"}, {"a.py": "import asyncio\nawait asyncio.sleep(1)\n"}),
        ("Start-Sleep", {"a.ps1": "# Start-Sleep in a comment\n"}, {"a.ps1": "Start-Sleep 1\n"}),
        ("Start-Sleep in a batch file", {"a.bat": "rem Start-Sleep 1\n"}, {"a.bat": "powershell -Command \"Start-Sleep 1\"\n"}),
        ("the Sleep of a type that is no Thread", {"a.ps1": "[MyThread]::Sleep(1)\n"},
         {"a.ps1": "[Threading.Thread]::Sleep(1)\n"}),
        ("a sleep in a PowerShell if counts once", {"a.ps1": "if (Test-Path x) { }\n"},
         {"a.ps1": "if (Start-Sleep 1) { }\n"}),
        ("a sleep in a PowerShell while counts once", {"a.ps1": "while (Test-Path x) { }\n"},
         {"a.ps1": "while (Start-Sleep 1) { }\n"}),
        ("a sleep in a Python while counts once", {"a.py": "import time\nwhile not ready():\n    pass\n"},
         {"a.py": "import time\nwhile not time.sleep(1):\n    pass\n"}),
        ("a sleep in a default", {"a.py": "import time\ndef f(delay=1):\n    pass\n"},
         {"a.py": "import time\ndef f(delay=time.sleep(1)):\n    pass\n"}),
        ("a script set earlier on the same line",
         {"a.py": "import subprocess\nps = 'Get-Date'; subprocess.run(['powershell', '-Command', ps])\n"},
         {"a.py": "import subprocess\nps = 'Start-Sleep 1'; subprocess.run(['powershell', '-Command', ps])\n"}),
        ("a parameter hides the module's script",
         {"a.py": "import subprocess\nps = 'Start-Sleep 1'\ndef run(ps):\n    subprocess.run(['powershell', '-Command', ps])\n"},
         {"a.py": "import subprocess\nps = 'Start-Sleep 1'\ndef run():\n    subprocess.run(['powershell', '-Command', ps])\n"}),
        ("in microfone/", {"dev/a.py": "import time\ntime.sleep(1)\n"},
         {"dev/a.py": "import time\ntime.sleep(1)\n", "microfone/a.py": "import time\ntime.sleep(1)\n"}),
        ("a sleep in the type of an except",
         {"a.py": "import time\ntry:\n    f()\nexcept get_type(x):\n    pass\n"},
         {"a.py": "import time\ntry:\n    f()\nexcept get_type(time.sleep(1)):\n    pass\n"}),
        ("a sleep in the annotation of a parameter", {"a.py": "import time\ndef f(x: int):\n    pass\n"},
         {"a.py": "import time\ndef f(x: time.sleep(1)):\n    pass\n"}),
        ("a sleep in the annotation of a result", {"a.py": "import time\ndef f() -> int:\n    pass\n"},
         {"a.py": "import time\ndef f() -> time.sleep(1):\n    pass\n"}),
        ("a sleep in the index of a PowerShell assignment", {"a.ps1": "$a[$(Get-Date)] = 42\n"},
         {"a.ps1": "$a[$(Start-Sleep 1)] = 42\n"}),
        ("a module script set in either branch",
         {"a.py": "import subprocess\nif flag:\n    PS = 'Get-Item x'\nelse:\n    PS = 'Get-Date'\n"
                  "def run():\n    subprocess.run(['powershell', '-Command', PS])\n"},
         {"a.py": "import subprocess\nif flag:\n    PS = 'Start-Sleep 1'\nelse:\n    PS = 'Get-Date'\n"
                  "def run():\n    subprocess.run(['powershell', '-Command', PS])\n"}),
        ("a script set before an if that sets it in both branches",
         {"a.py": "import subprocess\nps = loader()\nif flag:\n    ps = 'Get-Date'\nelse:\n    ps = 'Get-Item x'\n"
                  + RUN_PS},
         {"a.py": "import subprocess\nps = loader()\nif flag:\n    ps = 'Start-Sleep 1'\nelse:\n    ps = 'Get-Item x'\n"
                  + RUN_PS}),
        ("a script with an f-string inside a field", {"a.py": NESTED_FSTRING.replace("{TAIL}", "")},
         {"a.py": NESTED_FSTRING.replace("{TAIL}", "; Start-Sleep 1")}),
        ("a composite action outside .github", {"tools/a/action.yml": ACTION.replace("RUN", "Write-Output 1")},
         {"tools/a/action.yml": ACTION.replace("RUN", "Start-Sleep 1")}),
        ("a script with a raw f-string inside a field", {"a.py": "import subprocess\nps = f'{rf\"\\{{\"}'\n" + RUN_PS},
         {"a.py": "import subprocess\nps = f'{rf\"\\{{\"}; Start-Sleep 1'\n" + RUN_PS}),
        ("an annotation that Python keeps as text",
         {"a.py": "from __future__ import annotations\nimport time\ndef f(x: time.sleep(1)) -> time.sleep(2):\n    pass\n"},
         {"a.py": "from __future__ import annotations\nimport time\ndef f(x=time.sleep(1)):\n    pass\n"}),
        ("the annotation of a class variable runs, also inside a function",
         {"a.py": "import time\ndef f():\n    class A:\n        x: int = 3\n"},
         {"a.py": "import time\ndef f():\n    class A:\n        x: time.sleep(1) = 3\n"}),
        ("a sleep in the annotation of a module variable", {"a.py": "import time\nx: int = 3\n"},
         {"a.py": "import time\nx: time.sleep(1) = 3\n"}),
        ("the annotation of a local variable never runs", {"a.py": "import time\ndef f():\n    x: time.sleep(1) = 3\n"},
         {"a.py": "import time\ndef f():\n    x: int = time.sleep(1)\n"}),
        ("a sleep in the index of an assignment in a PowerShell condition", {"a.ps1": "if ($a[$(Get-Date)] = 1) { }\n"},
         {"a.ps1": "if ($a[$(Start-Sleep 1)] = 1) { }\n"}),
        ("a branch's script does not reach the other branch",
         {"a.py": "import subprocess\nps = 'Get-Date'\nif flag:\n    ps = 'Start-Sleep 1'\nelse:\n    " + RUN_PS},
         {"a.py": "import subprocess\nps = 'Get-Date'\nif flag:\n    ps = 'Start-Sleep 1'\n" + RUN_PS}),
    ],
    "sleeps_dev": [
        ("Start-Sleep in a one-line PowerShell step",
         {".github/workflows/w.yml": "jobs:\n  monta:\n    steps:\n      - shell: pwsh\n"
                                     "        run: \"Write-Output ok # Start-Sleep 1\"\n"},
         {".github/workflows/w.yml": "jobs:\n  monta:\n    steps:\n      - shell: pwsh\n"
                                     "        run: \"Start-Sleep 1 # wait\"\n"}),
        ("in dev/", {"a.py": "import time\ntime.sleep(1)\n"},
         {"a.py": "import time\ntime.sleep(1)\n", "dev/a.py": "import time\ntime.sleep(1)\n"}),
        ("a tool, not a test", {"dev/testa_x.py": "import time\ntime.sleep(1)\n",
                                "dev/test_x.py": "import time\ntime.sleep(1)\n",
                                "instalador/testa-x.ps1": "Start-Sleep 1\n"},
         {"dev/testa_x.py": "import time\ntime.sleep(1)\n", "dev/shot.py": "import time\ntime.sleep(1)\n"}),
        ("a sleep in a Python step, in a test job and in a build job",
         {".github/workflows/w.yml": PY_STEP.replace("JOB", "testa")},
         {".github/workflows/w.yml": PY_STEP.replace("JOB", "testa") + PY_STEP.split("jobs:\n")[1].replace("JOB", "monta")}),
        ("a workflow's test job is a test, its build job is not",
         {".github/workflows/w.yml": "jobs:\n  testes:\n    runs-on: windows-2025\n    steps:\n      - run: Start-Sleep 1\n"},
         {".github/workflows/w.yml": "jobs:\n  testes:\n    runs-on: windows-2025\n    steps:\n      - run: Start-Sleep 1\n"
                                     "  monta:\n    runs-on: windows-2025\n    steps:\n      - run: Start-Sleep 1\n"}),
        ("a PowerShell command in a bash step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - run: pwsh -Command 'Get-Date'\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - run: pwsh -Command 'Start-Sleep 1'\n"}),
        ("a run key outside a step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    env:\n      run: Start-Sleep 1\n"
                                     "    steps:\n      - run: Get-Date\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    env:\n      run: Get-Date\n"
                                     "    steps:\n      - run: Start-Sleep 1\n"}),
        ("a step that runs an anchored script",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    env:\n      D: &d Start-Sleep 1\n"
                                     "    steps:\n      - run: Get-Date\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    env:\n      D: &d Start-Sleep 1\n"
                                     "    steps:\n      - run: *d\n"}),
        ("steps shared with a test job by an alias",
         {".github/workflows/w.yml": "jobs:\n  test:\n    runs-on: windows-2025\n    steps: &s\n      - run: Start-Sleep 1\n"},
         {".github/workflows/w.yml": "jobs:\n  test:\n    runs-on: windows-2025\n    steps: &s\n      - run: Start-Sleep 1\n"
                                     "  build:\n    runs-on: windows-2025\n    steps: *s\n"}),
        ("a GitHub expression with a quoted }}",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: Write-Output ${{ '}}' }}\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: Start-Sleep ${{ '}}' }}\n"}),
        ("a GitHub expression in a PowerShell step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: Write-Output ${{ inputs.seconds }}\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: Start-Sleep -Seconds ${{ inputs.seconds }}\n"}),
        ("the PowerShell a Python step runs",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n        run: |\n"
                                     "          import subprocess\n"
                                     "          subprocess.run(['powershell', '-Command', 'Get-Date'])\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n        run: |\n"
                                     "          import subprocess\n"
                                     "          subprocess.run(['powershell', '-Command', 'Start-Sleep 1'])\n"}),
        ("a workflow", {"instalador/testa-x.ps1": "Start-Sleep 1\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n      - run: Start-Sleep 1\n"}),
        ("a job that is an alias of another", {".github/workflows/w.yml": ALIASED_JOB.replace("RUN", "Write-Output 1")},
         {".github/workflows/w.yml": ALIASED_JOB.replace("RUN", "Start-Sleep 1")}),
    ],
    "theme_timers": [
        ("setTimeout", {"themes/t/a.js": "// setTimeout(f, 1)\nconst s = 'setTimeout(';\n"},
         {"themes/t/a.js": "setTimeout(f, 1);\n"}),
        ("setInterval in index.html", {"themes/t/index.html": "<script>\nf();\n</script>\n"},
         {"themes/t/index.html": "<script>\nsetInterval(f, 1);\n</script>\n"}),
        ("a timer in an attribute", {"themes/t/index.html": "<div title=\"setTimeout(f, 1)\"></div>\n"},
         {"themes/t/index.html": "<div title=\"x\"></div>\n<script>\nsetTimeout(f, 1);\n</script>\n"}),
        ("a script commented out", {"themes/t/index.html": "<!--\n<script>\nsetTimeout(f, 1);\n</script>\n-->\n"},
         {"themes/t/index.html": "<script>\nsetTimeout(f, 1);\n</script>\n"}),
        ("requestIdleCallback", {"gallery/a.js": "setTimeout(f, 1);\n"}, {"themes/t/a.js": "requestIdleCallback(f);\n"}),
    ],
    "theme_animation_frames": [
        ("requestAnimationFrame", {"themes/t/a.js": "setTimeout(f, 1);\n"}, {"themes/t/a.js": "requestAnimationFrame(f);\n"}),
    ],
    "retries": [
        ("a loop that stops on the flag its helper sets",
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while not done:\n    other = attempt()\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while not done:\n    done = attempt()\n    time.sleep(1)\n"}),
        ("a do-until on the flag its helper sets",
         {"a.ps1": "function attempt { try { f } catch { $null } }\ndo { $other = attempt; Start-Sleep 1 } until ($done)\n"},
         {"a.ps1": "function attempt { try { f } catch { $null } }\ndo { $done = attempt; Start-Sleep 1 } until ($done)\n"}),
        ("a helper called twice, tested once",
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if ready():\n        break\n    attempt()\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if attempt():\n        break\n    attempt()\n    time.sleep(1)\n"}),
        ("a test of the helper joined to another",
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if not attempt() and enabled:\n        break\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if attempt() and enabled:\n        break\n    time.sleep(1)\n"}),
        ("a comparison of the helper's result is no test of its success",
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while not (attempt() is False):\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while not attempt():\n    time.sleep(1)\n"}),
        ("a PowerShell comparison of the helper's result",
         {"a.ps1": "function attempt { try { f } catch { $null } }\n"
                   "while ($true) { if ((attempt) -eq $null) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": "function attempt { try { f } catch { $null } }\n"
                   "while ($true) { if (attempt) { break }; Start-Sleep 1 }\n"}),
        ("a PowerShell comparison of the flag",
         {"a.ps1": "function attempt { try { f } catch { $null } }\n"
                   "while ($true) { $s = attempt; if ($s -eq $null) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": "function attempt { try { f } catch { $null } }\n"
                   "while ($true) { $s = attempt; if ($s) { break }; Start-Sleep 1 }\n"}),
        ("the helper's result passed to another call",
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if check(attempt()):\n        break\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if attempt():\n        break\n    time.sleep(1)\n"}),
        ("a flag set inside a PowerShell condition",
         {"a.ps1": "function f { try { g } catch { $null } }\n"
                   "while ($true) { if ($other = f) { }; if ($s) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": "function f { try { g } catch { $null } }\n"
                   "while ($true) { if ($s = f) { }; if ($s) { break }; Start-Sleep 1 }\n"}),
        ("a flag set by a walrus",
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if (other := attempt()):\n        pass\n    if r:\n        break\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while True:\n    if (r := attempt()):\n        pass\n    if r:\n        break\n    time.sleep(1)\n"}),
        ("a flag set with its scope",
         {"a.ps1": "function attempt { try { f } catch { $null } }\ndo { $script:other = attempt; Start-Sleep 1 } until ($done)\n"},
         {"a.ps1": "function attempt { try { f } catch { $null } }\ndo { $script:done = attempt; Start-Sleep 1 } until ($done)\n"}),
        ("a do-until on the result of its helper",
         {"a.ps1": "function Get-S { try { f } catch { $null } }\ndo { Start-Sleep 1; $s = Get-S } until (-not $s)\n"},
         {"a.ps1": "function Get-S { try { f } catch { $null } }\ndo { Start-Sleep 1; $s = Get-S } until ($s)\n"}),
        ("a while on the result of its helper",
         {"a.py": "import time\ndef r():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while r():\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef r():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "while not r():\n    time.sleep(1)\n"}),
        ("a PowerShell test of the helper joined to another",
         {"a.ps1": "function attempt { try { f } catch { $null } }\n"
                   "while ($true) { if (-not (attempt) -and $on) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": "function attempt { try { f } catch { $null } }\n"
                   "while ($true) { if ((attempt) -and $on) { break }; Start-Sleep 1 }\n"}),
        ("a PowerShell retry next to another try that waits",
         {"a.ps1": "while ($true) { try { f } catch { throw }; try { g; Start-Sleep 5 } catch { throw } }\n"},
         {"a.ps1": "while ($true) { try { f } catch { Start-Sleep 1 }; try { g; Start-Sleep 5 } catch { } }\n"}),
        ("a PowerShell retry whose if guard the try turns off",
         {"a.ps1": "while ($true) { if (-not $done) { f; $done = $true }; Start-Sleep 1 }\n"},
         {"a.ps1": "while ($true) { if (-not $done) { try { f; $done = $true } catch { } }; Start-Sleep 1 }\n"}),
        ("a PowerShell retry whose try sits in a helper",
         {"a.ps1": "function Get-State($p) { try { Invoke-RestMethod $p } catch { $null } }\n"
                   "foreach ($p in $paths) { Start-Sleep 1; if ($s = Get-State $p) { break } }\n"},
         {"a.ps1": "function Get-State($p) { try { Invoke-RestMethod $p } catch { $null } }\n"
                   "foreach ($i in 1..40) { Start-Sleep 1; if ($s = Get-State 'x') { break } }\n"}),
        ("a Python retry whose try sits in a helper",
         {"a.py": "import time\ndef ready():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "for _ in range(30):\n    if not ready():\n        break\n    time.sleep(1)\n"},
         {"a.py": "import time\ndef ready():\n    try:\n        return f()\n    except OSError:\n        return None\n"
                  "for _ in range(30):\n    if ready():\n        break\n    time.sleep(1)\n"}),
        ("a retry whose helper waits in its handler",
         {"a.py": "import time\ndef attempt(item):\n    try:\n        return f(item)\n    except OSError:\n"
                  "        time.sleep(1)\n        return None\nfor item in items:\n    if attempt(item):\n        break\n"},
         {"a.py": "import time\ndef attempt():\n    try:\n        return f()\n    except OSError:\n"
                  "        time.sleep(1)\n        return None\nwhile True:\n    if attempt():\n        break\n"}),
        ("a poll whose helper returns inside its try",
         {"a.py": "import time\nclass A:\n    def check(self):\n        try:\n            return f()\n"
                  "        except OSError:\n            return None\n\n    def poll(self):\n"
                  "        while True:\n            self.check()\n            time.sleep(5)\n"},
         {"a.py": "import time\nclass A:\n    def check(self):\n        try:\n            return f()\n"
                  "        except OSError:\n            return None\n\n    def poll(self):\n"
                  "        while True:\n            if self.check():\n                return\n            time.sleep(5)\n"}),
        ("a Python retry of a method on self",
         {"a.py": "import time\nclass A:\n    def ok(self):\n        try:\n            return f()\n"
                  "        except OSError:\n            return None\n\n    def wait(self, other):\n"
                  "        while True:\n            if other.ok():\n                break\n            time.sleep(1)\n"},
         {"a.py": "import time\nclass A:\n    def ok(self):\n        try:\n            return f()\n"
                  "        except OSError:\n            return None\n\n    def wait(self, other):\n"
                  "        while True:\n            if self.ok():\n                break\n            time.sleep(1)\n"}),
        ("the PowerShell retry a Python script runs",
         {"a.py": 'import subprocess\nsubprocess.run(["powershell", "-Command", "while ($true) { f; Start-Sleep 1 }"])\n'},
         {"a.py": 'import subprocess\nps = "while ($true) { try { f; break } catch { Start-Sleep 1 } }"\n'
                  'subprocess.run(["powershell", "-Command", ps])\n'}),
        ("a loop with try and a sleep", {"a.py": "import time\nwhile True:\n    try:\n        f()\n    except OSError:\n"
                                                 "        return\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile True:\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        time.sleep(1)\n"}),
        ("the sleep in a nested function", {"a.py": "import time\nfor x in y:\n    try:\n        f()\n        break\n"
                                                    "    except OSError:\n        pass\n    def g():\n        time.sleep(1)\n"},
         {"a.py": "import time\nfor x in y:\n    try:\n        f()\n        break\n    except OSError:\n        pass\n"
                  "    time.sleep(1)\n"}),
        ("a poll that goes on either way, against one that ends when it works",
         {"a.py": "import time\nfor d in cases:\n    time.sleep(0.05)\n    try:\n        st = f(d)\n"
                  "    except E as ex:\n        st = ex.status\n    check(st)\n"},
         {"a.py": "import time\ndef w():\n    for _ in range(50):\n        time.sleep(0.2)\n        try:\n"
                  "            if f():\n                return\n        except RuntimeError:\n            pass\n"}),
        ("an attempt the success turns off (the phone port of server.py)",
         {"a.py": "import asyncio\nasync def w():\n    for d in cases:\n        try:\n            st = await f(d)\n"
                  "        except OSError as e:\n            st = e\n        await asyncio.sleep(1)\n"},
         {"a.py": "import asyncio\nasync def w():\n    site = None\n    while True:\n        if site is None and ip:\n"
                  "            try:\n                site = await open_port(ip)\n            except OSError:\n"
                  "                site = None\n        await asyncio.sleep(5)\n"}),
        ("the success after the try", {"a.py": "import time\nwhile True:\n    try:\n        get()\n    except OSError:\n"
                                               "        pass\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile True:\n    try:\n        get()\n    except OSError:\n        pass\n"
                  "    if done():\n        return\n    time.sleep(1)\n"}),
        ("a watcher that polls the same after a success and a failure (engine.py's _vigia_loop)",
         {"a.py": "import time\nwhile True:\n    time.sleep(1)\n    try:\n        d = read()\n    except OSError:\n"
                  "        continue\n    use(d)\n"},
         {"a.py": "import time\nwhile True:\n    try:\n        d = read()\n    except OSError:\n        time.sleep(1)\n"
                  "        continue\n    use(d)\n"}),
        ("a while whose condition the success turns off",
         {"a.py": "import time\nwhile not stop:\n    try:\n        f()\n    except OSError:\n        pass\n"
                  "    time.sleep(1)\n"},
         {"a.py": "import time\nwhile not done:\n    try:\n        f()\n        done = True\n    except OSError:\n"
                  "        pass\n    time.sleep(1)\n"}),
        ("an outer loop around a retry", {"a.py": "import time\nfor a in b:\n    x = 1\n"},
         {"a.py": "import time\nfor a in b:\n    while True:\n        try:\n            f()\n        except OSError:\n"
                  "            time.sleep(1)\n"}),
        ("a retry in a workflow's Python step",
         {".github/workflows/w.yml": PY_STEP.replace("JOB", "monta").replace(
             "time.sleep(1)\n", "for _ in range(3):\n              f()\n              time.sleep(1)\n")},
         {".github/workflows/w.yml": PY_STEP.replace("JOB", "monta").replace(
             "time.sleep(1)\n", "for _ in range(3):\n              try:\n                  f()\n                  break\n"
                                "              except OSError:\n                  time.sleep(1)\n")}),
        ("powershell", {"a.ps1": "for ($i = 0; $i -lt 3; $i++) { try { f } catch { }; Start-Sleep 1 }\n"},
         {"a.ps1": "for ($i = 0; $i -lt 3; $i++) { try { f } catch { Start-Sleep 1 } }\n"}),
        ("a powershell poll that waits the same after a success and a failure",
         {"a.ps1": "while ($true) { try { Get-Status } catch { Write-Warning $_ }; Start-Sleep 5 }\n"},
         {"a.ps1": "while ($true) { try { Get-Status; break } catch { Write-Warning $_ }; Start-Sleep 5 }\n"}),
        ("powershell in a Python string", {"a.py": "ps = 'do{Start-Sleep 1;try{f}catch{}}while($a)'\n" + RUN_PS},
         {"a.py": "ps = 'do{Start-Sleep 1;try{$s=f}catch{}}while($s -eq $null)'\n" + RUN_PS}),
        ("a powershell for whose condition the try turns off",
         {"a.ps1": "for ($i = 0; $i -lt 9 -and -not $e; $i++) { try { f } catch { }; Start-Sleep 1 }\n"},
         {"a.ps1": "for ($i = 0; $i -lt 9 -and -not $e; $i++) { try { $e = f } catch { }; Start-Sleep 1 }\n"}),
        ("a powershell loop around a retry", {"a.ps1": "foreach ($x in $y) { f $x }\n"},
         {"a.ps1": "foreach ($x in $y) {\n  while ($true) { try { f $x; break } catch { Start-Sleep 1 } }\n}\n"}),
        ("a powershell loop around a retry in a Python string", {"a.py": "ps = 'foreach($x in $y){f $x}'\n" + RUN_PS},
         {"a.py": "ps = 'foreach($x in $y){while($true){try{f $x;break}catch{Start-Sleep 1}}}'\n" + RUN_PS}),
        ("a poll followed by a while that reads what its try set",
         {"a.ps1": "while ($true) { try { $status = Get-Status } catch { Write-Warning $_ }; Start-Sleep 5 }\n"
                   "while ($status) { f }\n"},
         {"a.ps1": "do { try { $status = Get-Status } catch { }; Start-Sleep 5 } while (-not $status)\n"}),
        ("a catch that waits and throws, and a break only on the failure path",
         {"a.ps1": "while ($true) { try { f } catch { Start-Sleep 1; throw } }\n"
                   "while ($true) { try { f } catch { break }; Start-Sleep 1 }\n"},
         {"a.ps1": "while ($true) { try { f; break } catch { Start-Sleep 1 } }\n"}),
        ("a poll whose warning says return",
         {"a.ps1": "while ($true) { try { Get-Status } catch { Write-Warning 'will return later' }; Start-Sleep 5 }\n"},
         {"a.ps1": "while ($true) { try { Get-Status } catch { Write-Warning 'again'; Start-Sleep 5 } }\n"}),
        ("a catch of two types", {"a.ps1": "while ($true) { Get-Status; Start-Sleep 1 }\n"},
         {"a.ps1": "while ($true) { try { f; break } catch [IO.FileNotFoundException], [IO.DirectoryNotFoundException] "
                   "{ Start-Sleep 1 } }\n"}),
        ("two retries in one Python string", {"a.py": "ps = 'f'\n" + RUN_PS},
         {"a.py": "ps = ('while($true){try{f;break}catch{Start-Sleep 1}}\\n'\n"
                  "      'while($true){try{g;break}catch{Start-Sleep 1}}')\n" + RUN_PS}, 2),
        ("a Python poll that waits the same in the try and in the handler",
         {"a.py": "import time\nwhile True:\n    try:\n        f()\n        time.sleep(1)\n    except OSError:\n"
                  "        time.sleep(1)\n"},
         {"a.py": "import time\nwhile True:\n    try:\n        f()\n    except OSError:\n        time.sleep(1)\n"}),
        ("a powershell poll that waits the same in the try and in the catch",
         {"a.ps1": "while ($true) { try { f; Start-Sleep 1 } catch { Start-Sleep 1 } }\n"},
         {"a.ps1": "while ($true) { try { f } catch { Start-Sleep 1 } }\n"}),
        ("a catch that throws only sometimes",
         {"a.ps1": "while ($true) { try { f } catch { Start-Sleep 1; throw } }\n"},
         {"a.ps1": "while ($true) { try { f } catch { if ($fatal) { throw }; Start-Sleep 1 } }\n"}),
        ("a JavaScript poll that reschedules the same after the catch",
         {"a.js": "function poll() {\n  try { f(); } catch (e) { setTimeout(poll, 1000); return; }\n"
                  "  setTimeout(poll, 1000);\n}\n"},
         {"a.js": "function poll() {\n  try { f(); } catch (e) { setTimeout(poll, 1000); return; }\n  mostrar();\n}\n"}),
        ("a Python poll that breaks only on a failure",
         {"a.py": "import time\nwhile True:\n    try:\n        f()\n    except FileNotFoundError:\n        break\n"
                  "    except OSError:\n        pass\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile True:\n    try:\n        f()\n        break\n    except OSError:\n        pass\n"
                  "    time.sleep(1)\n"}),
        ("a Python poll whose try keeps the loop on",
         {"a.py": "import time\nwhile running:\n    try:\n        f()\n        running = True\n    except OSError:\n"
                  "        pass\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile running:\n    try:\n        f()\n        running = False\n    except OSError:\n"
                  "        pass\n    time.sleep(1)\n"}),
        ("a do-while followed by another loop", {"a.py": "ps = 'do{f}while($a);while($b){Start-Sleep 1}'\n" + RUN_PS},
         {"a.py": "ps = 'do{try{f}catch{Start-Sleep 1}}while($a);while($b){Start-Sleep 1}'\n" + RUN_PS}),
        ("a script's onerror that loads it again",
         {"a.js": "const loadAgain = () => {\n  l.onerror = () => { l.remove(); };\n};\nsetTimeout(loadAgain, 3000);\n"},
         {"a.js": "const loadAgain = () => {\n  l.onerror = () => { l.remove(); setTimeout(loadAgain, 3000); };\n};\n"}),
        ("a catch that reconnects",
         {"a.html": "<script>\nfunction conectar() {\n  try { f(); } catch (e) { setTimeout(() => g(), 1); }\n}\n</script>\n"},
         {"a.html": "<script>\nfunction conectar() {\n  try { es = T.eventos(u); } catch (e) { reconT = setTimeout(conectar, 3000); "
                    "return; }\n}\n</script>\n"}),
        ("the theme's catch on several lines",
         {"a.js": "function conectar() {\n  try { f(); } catch (e) { report(e); } setTimeout(conectar, 100);\n}\n"},
         {"a.js": "function conectar() {\n  try {\n    es = T.eventos(u);\n  } catch (e) {\n"
                  "    reconT = setTimeout(conectar, 3000);\n    return;\n  }\n}\n"}),
        ("a timer that reports instead of trying again",
         {"a.js": "function conectar() {\n  try { f(); } catch (e) { setTimeout(reportError, 1000); }\n}\n"},
         {"a.js": "function conectar() {\n  try { f(); } catch (e) { setTimeout(conectar, 1000); }\n}\n"}),
        ("an onerror that reschedules the caller",
         {"a.js": "function carregar() {\n  s.onerror = function () {\n    s.remove();\n    setTimeout(avisar, 1000);\n"
                  "  };\n}\nfunction conectar() { carregar(); }\nfunction avisar() { mostrar(); }\n"},
         {"a.js": "function carregar() {\n  s.onerror = function () {\n    s.remove();\n    setTimeout(conectar, 1000);\n"
                  "  };\n}\nfunction conectar() { carregar(); }\n"}),
        ("a method with the caller's name is not a call to it",
         {"a.js": "function carregar() {\n  s.onerror = () => { setTimeout(avisar, 1000); };\n}\n"
                  "function avisar() { logger.carregar(); logger . carregar(); }\n"},
         {"a.js": "function carregar() {\n  s.onerror = () => { setTimeout(avisar, 1000); };\n}\n"
                  "function avisar() { carregar(); }\n"}),
        ("a handler exits", {"a.py": "import sys, time\nfor w in sizes:\n    try:\n        f(w)\n    except OSError:\n"
                                     "        sys.exit(1)\n    time.sleep(1)\n"},
         {"a.py": "import sys, time\nfor w in sizes:\n    try:\n        f(w)\n    except OSError:\n"
                  "        print('again')\n        time.sleep(1)\n"}),
        ("a brace and a timer inside strings",
         {"a.js": "function go() {\n  s.onerror = () => { report(\"setTimeout(go, 100)\"); };\n}\n"},
         {"a.js": "function go() {\n  s.onerror = () => { report(\"}\"); setTimeout(go, 100); };\n}\n"}),
        ("the transport's aoFalhar", {"a.js": "function conectar() {\n  es.aoFalhar(() => { online(false); });\n}\n"},
         {"a.js": "function conectar() {\n  es.aoFalhar(() => {\n    if (S.pareando) return;\n    fonte.fechar();\n"
                  "    api('GET', '/api/state').then(() => true, e => e.status !== 401)\n"
                  "      .then(volta => { if (volta && !S.pareando) reconT = setTimeout(conectar, 3000); });\n  });\n}\n"}),
        ("a catch that reschedules through an arrow",
         {"a.js": "function connect(url) {\n  try { open(url); } catch (e) { setTimeout(() => reportError(url), 100); }\n}\n"},
         {"a.js": "function connect(url) {\n  try { open(url); } catch (e) { setTimeout(() => connect(url), 100); }\n}\n"}),
        ("a promise catch that tries again", {"a.js": "fetch(u).then(go);\n"},
         {"a.js": "function go() { fetch(u).catch(() => setTimeout(go, 3000)); }\n"}),
        ("a switch key is no test of the flag",
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { $s = attempt; switch ($x) { $s { break outer } }; "
                                "Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { $s = attempt; if ($s) { break outer }; Start-Sleep 1 }\n"}),
        ("a break inside a switch leaves only the switch",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt) { switch (1) { 1 { break } } }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt) { break }; Start-Sleep 1 }\n"}),
        ("a labeled break inside a switch leaves the loop",
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { if (attempt) { switch (1) { 1 { break } } }; "
                                "Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { if (attempt) { switch (1) { 1 { break outer } } }; "
                                "Start-Sleep 1 }\n"}),
        ("a flag passed to another call is no test of it",
         {"a.py": ATTEMPT + "while True:\n    s = attempt()\n    if check(s):\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    s = attempt()\n    if s:\n        break\n    time.sleep(1)\n"}),
        ("a PowerShell flag passed to a command is no test of it",
         {"a.ps1": ATTEMPT_PS + "while ($true) { $s = attempt; if (Test-Path $s) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { $s = attempt; if ($s) { break }; Start-Sleep 1 }\n"}),
        ("a flag set from a comparison of the helper, tested negated",
         {"a.py": ATTEMPT + "while True:\n    done = attempt() is None\n    if not done:\n        break\n"
                            "    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    done = attempt()\n    if done:\n        break\n    time.sleep(1)\n"}),
        ("a flag set from the negated helper",
         {"a.py": ATTEMPT + "while True:\n    done = not attempt()\n    if done:\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    done = attempt()\n    if done:\n        break\n    time.sleep(1)\n"}),
        ("a flag set from a comparison of the helper",
         {"a.py": ATTEMPT + "while True:\n    done = attempt() is None\n    if done:\n        break\n"
                            "    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    done = attempt()\n    if done:\n        break\n    time.sleep(1)\n"}),
        ("a PowerShell flag set from a comparison of the helper",
         {"a.ps1": ATTEMPT_PS + "while ($true) { $done = (attempt) -eq $null; if ($done) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { $done = attempt; if ($done) { break }; Start-Sleep 1 }\n"}),
        ("a helper piped to another command",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt | Out-Null) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt) { break }; Start-Sleep 1 }\n"}),
        ("a walrus that sets the flag from another call",
         {"a.py": ATTEMPT + "while True:\n    s = attempt()\n    if (s := other()):\n        break\n"
                            "    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    s = attempt()\n    if (s := attempt()):\n        break\n"
                            "    time.sleep(1)\n"}),
        ("an awaited helper", {"a.py": ASYNC_RETRY.replace("CALL", "other")},
         {"a.py": ASYNC_RETRY.replace("CALL", "attempt")}),
        ("a sleep in the iterable is no wait between tries",
         {"a.py": "import time\nfor x in items(time.sleep(1)):\n    try:\n        f()\n        break\n"
                  "    except OSError:\n        pass\n"},
         {"a.py": "import time\nfor x in items():\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        time.sleep(1)\n"}),
        ("a sleep in the else of a for is no wait between tries",
         {"a.py": "import time\nfor x in items():\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        pass\nelse:\n    time.sleep(1)\n"},
         {"a.py": "import time\nfor x in items():\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        time.sleep(1)\nelse:\n    pass\n"}),
        ("a sleep in the else of a while is no wait between tries",
         {"a.py": "import time\nwhile tries():\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        pass\nelse:\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile tries():\n    try:\n        f()\n        break\n    except OSError:\n"
                  "        time.sleep(1)\nelse:\n    pass\n"}),
        ("a sleep in the start of a PowerShell for is no wait between tries",
         {"a.ps1": "for ($i = $(Start-Sleep 1); $i -lt 3; $i++) { try { f; break } catch { } }\n"},
         {"a.ps1": "for ($i = 0; $i -lt 3; Start-Sleep 1) { try { f; break } catch { } }\n"}),
        ("a sleep in the list of a PowerShell foreach is no wait between tries",
         {"a.ps1": "foreach ($x in $(Start-Sleep 1; 1..3)) { try { f; break } catch { } }\n"},
         {"a.ps1": "foreach ($x in 1..3) { try { f; break } catch { Start-Sleep 1 } }\n"}),
        ("a helper whose output goes elsewhere",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt > $null) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt 2>$null) { break }; Start-Sleep 1 }\n"}),
        ("a helper whose errors join its output",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt 2>&1) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt 2>$null) { break }; Start-Sleep 1 }\n"}),
        ("a Python loop condition that compares the flag",
         {"a.py": "import time\nwhile running is True:\n    try:\n        f()\n        other = False\n"
                  "    except OSError:\n        pass\n    time.sleep(1)\n"},
         {"a.py": "import time\nwhile running is True:\n    try:\n        f()\n        running = False\n"
                  "    except OSError:\n        pass\n    time.sleep(1)\n"}),
        ("a PowerShell loop condition that compares the flag",
         {"a.ps1": "while ($running -eq $true) { try { f; $other = $false } catch { }; Start-Sleep 1 }\n"},
         {"a.ps1": "while ($running -eq $true) { try { f; $running = $false } catch { }; Start-Sleep 1 }\n"}),
        ("a walrus inside a comparison sets the flag",
         {"a.py": ATTEMPT + "while True:\n    if (other := attempt()) is None:\n        log()\n    if r:\n"
                            "        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    if (r := attempt()) is None:\n        log()\n    if r:\n"
                            "        break\n    time.sleep(1)\n"}),
        ("a helper that reaches the attempt through the list of its own loop",
         {"a.py": ATTEMPT + "def ready():\n    for m in listed():\n        return m\n    return None\n"
                      "while not done:\n    time.sleep(1)\n    done = ready()\n"},
         {"a.py": ATTEMPT + "def ready():\n    for m in attempt():\n        return m\n    return None\n"
                      "while not done:\n    time.sleep(1)\n    done = ready()\n"}),
        ("a quoted label leaves the loop from a switch",
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { :pick switch (1) { 1 { if (attempt) { break 'pick' } } }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { :pick switch (1) { 1 { if (attempt) { break 'outer' } } }; Start-Sleep 1 }\n"}),
        ("a break that names its own switch leaves only the switch",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if (attempt) { :sw switch (1) { 1 { break SW } } }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + ":outer while ($true) { if (attempt) { :sw switch (1) { 1 { break outer } } }; Start-Sleep 1 }\n"}),
        ("a walrus compared to the helper is no flag of it",
         {"a.py": ATTEMPT + "while True:\n    if (s := other()) == attempt():\n        log()\n    if s:\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    if (s := attempt()) == other():\n        log()\n    if s:\n        break\n    time.sleep(1)\n"}),
        ("a walrus of the negated helper",
         {"a.py": ATTEMPT + "while True:\n    if (r := not attempt()) is False:\n        log()\n    if r:\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    if (r := not attempt()) is False:\n        log()\n    if not r:\n        break\n"
                      "    time.sleep(1)\n"}),
        ("a walrus beside the helper in an or",
         {"a.py": ATTEMPT + "while True:\n    a = (b := other()) or attempt()\n    if b:\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    a = (b := other()) or attempt()\n    if a:\n        break\n    time.sleep(1)\n"}),
        ("a helper that takes its own flag",
         {"a.py": ATTEMPT + "while True:\n    if (s := other(s)):\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    if (s := attempt(s)):\n        break\n    time.sleep(1)\n"}),
        ("a flag set from the negated helper and tested negated",
         {"a.py": ATTEMPT + "while True:\n    done = not attempt()\n    if done:\n        break\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "while True:\n    done = not attempt()\n    if not done:\n        break\n    time.sleep(1)\n"}),
        ("a loop that runs while the negated flag holds",
         {"a.py": ATTEMPT + "done = True\nwhile not done:\n    done = not attempt()\n    time.sleep(1)\n"},
         {"a.py": ATTEMPT + "done = True\nwhile done:\n    done = not attempt()\n    time.sleep(1)\n"}),
        ("a PowerShell flag set from the negated helper and tested negated",
         {"a.ps1": ATTEMPT_PS + "while ($true) { $done = -not (attempt); if ($done) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { $done = -not (attempt); if (-not $done) { break }; Start-Sleep 1 }\n"}),
        ("a PowerShell do-while on the negated flag",
         {"a.ps1": ATTEMPT_PS + "do { $failed = -not (attempt); Start-Sleep 1 } until ($failed)\n"},
         {"a.ps1": ATTEMPT_PS + "do { $failed = -not (attempt); Start-Sleep 1 } while ($failed)\n"}),
        ("a cast assignment that is the test of a PowerShell condition",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if ([bool]$s = other) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { if ([bool]$s = attempt) { break }; Start-Sleep 1 }\n"}),
        ("a cast flag set in a PowerShell condition",
         {"a.ps1": ATTEMPT_PS + "while ($true) { if ([bool]$t = attempt) { }; if ($s) { break }; Start-Sleep 1 }\n"},
         {"a.ps1": ATTEMPT_PS + "while ($true) { if ([bool]$s = attempt) { }; if ($s) { break }; Start-Sleep 1 }\n"}),
    ],
    "broad_excepts": [
        ("a PowerShell catch with no type", {"a.ps1": "try { f } catch [IO.IOException] { }\n"},
         {"a.ps1": "try { f } catch { }\n"}),
        ("a PowerShell catch of System.Exception", {"a.ps1": "try { f } catch [IO.IOException] { }\n"},
         {"a.ps1": "try { f } catch [System.Exception] { }\n"}),
        ("a PowerShell trap with no type", {"a.ps1": "trap [IO.IOException] { continue }\n"},
         {"a.ps1": "trap { continue }\n"}),
        ("the PowerShell a Python script runs",
         {"a.py": 'import subprocess\nsubprocess.run(["powershell", "-Command", "try { f } catch [IO.IOException] { }"])\n'},
         {"a.py": 'import subprocess\nsubprocess.run(["powershell", "-Command", "try { f } catch { }"])\n'}),
        ("a PowerShell catch in a workflow step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: try { f } catch [IO.IOException] { }\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: try { f } catch { }\n"}),
        ("a PowerShell catch of a BaseException, which PowerShell lacks",
         {"a.ps1": "try { f } catch [BaseException] { }\n"}, {"a.ps1": "try { f } catch [Exception] { }\n"}),
        ("the PowerShell a Python script joins",
         {"a.py": "import subprocess\ncode = '\\n'.join(['try { f } catch [IO.IOException] { }', *extra])\n"
                  "subprocess.run(['powershell', '-Command', code])\n"},
         {"a.py": "import subprocess\ncode = '\\n'.join(['try { f } catch { }', *extra])\n"
                  "subprocess.run(['powershell', '-Command', code])\n"}),
        ("a catch inside a PowerShell condition", {"a.ps1": "if (try { f } catch [IO.IOException] { }) { }\n"},
         {"a.ps1": "if (try { f } catch { }) { }\n"}),
        ("a script joined inside a joined script",
         {"a.py": "import subprocess\npart = '\\n'.join(['try { f } catch [IO.IOException] { }'])\n"
                  "code = '\\n'.join([part, 'Get-Date'])\nsubprocess.run(['powershell', '-Command', code])\n"},
         {"a.py": "import subprocess\npart = '\\n'.join(['try { f } catch { }'])\n"
                  "code = '\\n'.join([part, 'Get-Date'])\nsubprocess.run(['powershell', '-Command', code])\n"}),
        ("a windows runner written in capitals",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: Ubuntu-24.04\n    steps:\n      - run: try { f } catch { }\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: Windows-2025\n    steps:\n      - run: try { f } catch { }\n"}),
        ("a windows runner named by an alias",
         {".github/workflows/w.yml": "x: &w [ubuntu-24.04]\njobs:\n  j:\n    runs-on: *w\n    steps:\n"
                                     "      - run: try { f } catch { }\n"},
         {".github/workflows/w.yml": "x: &w [windows-2025]\njobs:\n  j:\n    runs-on: *w\n    steps:\n"
                                     "      - run: try { f } catch { }\n"}),
        ("a PowerShell catch in an if condition counts once",
         {"a.ps1": "if (& { try { f } catch [IO.IOException] { } }) { }\n"},
         {"a.ps1": "if (& { try { f } catch { } }) { }\n"}),
        ("except Exception", {"a.py": "try:\n    f()\nexcept OSError:\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept Exception:\n    pass\n"}),
        ("a lowercase exception is another name in Python",
         {"a.py": "try:\n    f()\nexcept exception:\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept Exception:\n    pass\n"}),
        ("a bare except", {"a.py": "try:\n    f()\nexcept (OSError, ValueError):\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept:\n    pass\n"}),
        ("a tuple with Exception", {"a.py": "try:\n    f()\nexcept (OSError, ValueError):\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept (OSError, Exception):\n    pass\n"}),
        ("BaseException", {"a.py": "x = BaseException\n"}, {"a.py": "try:\n    f()\nexcept BaseException:\n    raise\n"}),
        ("the Python of a workflow", {".github/workflows/w.yml": WORKFLOW.replace("{handler}", "          except OSError:\n"
                                                                                       "              pass\n")},
         {".github/workflows/w.yml": WORKFLOW.replace("{handler}", "          except Exception:\n              pass\n")}),
        ("the Python of a workflow with shell: python",
         {".github/workflows/w.yml": WORKFLOW.replace("python3 {0}", "python").replace(
             "{handler}", "          except OSError:\n              pass\n")},
         {".github/workflows/w.yml": WORKFLOW.replace("python3 {0}", "python").replace(
             "{handler}", "          except Exception:\n              pass\n")}),
        ("a JavaScript catch with nothing in it",
         {"a.js": "try { f(); } catch (e) { report(e); }\np.catch(e => report(e));\n"},
         {"a.js": "try { f(); } catch (e) { /* the pointer left */ }\n"}),
        ("a promise catch with an empty callback", {"a.js": "api('GET', '/x').catch(e => mostrar(e));\n"},
         {"a.js": "api('GET', '/x').catch(() => {});\n"}),
        ("a promise catch with an empty callback and a trailing comma", {"a.js": "p.catch(e => mostrar(e),);\n"},
         {"a.js": "p.catch(() => {},);\n"}),
        ("an empty catch in an inline script",
         {"a.html": "<script>\ntry { f(); } catch { mostrar(); }\n</script>\n"},
         {"a.html": "<script>\ntry { f(); } catch { }\n</script>\n"}),
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
        ("ficou de fora with its issue in the line's comment, in Python",
         {"dev/t.py": "print('--   o guard ficou de fora')  # #219\n"},
         {"dev/t.py": "print('--   o guard ficou de fora')  # no issue\n"}),
        ("a known failure", {"dev/t.py": "print('known failure #240: theme_rebuild counts a reindented line')\n"
                                         "ISSUE = 'https://github.com/o/r/issues/255'\n"
                                         "print(f'known failure, {ISSUE}: a refused dequeue fails the run')\n"},
         {"dev/t.py": "print('known failure: theme_rebuild counts a reindented line')\n"}),
        ("ficou de fora in a workflow",
         {"action.yml": "runs:\n  steps:\n    - run: echo 'sem placa de video, o pedal de troca de voz ficou de fora'\n"},
         {"action.yml": "runs:\n  steps:\n    - run: echo '--   o pedal de troca de voz ficou de fora'\n"}),
        ("ficou de fora with its issue in the line's comment",
         {"action.yml": "runs:\n  steps:\n    - run: echo '--   o pedal ficou de fora'  # #219\n"},
         {"action.yml": "runs:\n  steps:\n    - run: echo '--   o pedal ficou de fora'  # no issue\n"}),
        ("ficou de fora in a PowerShell script", {"a.ps1": "# o pedal ficou de fora num comentario\n"},
         {"a.ps1": "'--   o pedal ficou de fora'\n"}),
        ("ficou de fora in a one-line PowerShell comment",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: \"# '--   o pedal ficou de fora'\"\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: \"Write-Output '--   o pedal ficou de fora'\"\n"}),
        ("ficou de fora in a comment of a quoted step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: \"Write-Output ok\n          # '--   o pedal ficou de fora'\"\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    runs-on: windows-2025\n    steps:\n"
                                     "      - run: \"Write-Output ok\n          Write-Output '--   o pedal ficou de fora'\"\n"}),
        ("skipIf in a workflow's Python step",
         {".github/workflows/w.yml": PY_STEP.replace("JOB", "testa").replace(
             "time.sleep(1)\n", "@unittest.skipIf(X, 'no X (#12)')\n          class T: pass\n")},
         {".github/workflows/w.yml": PY_STEP.replace("JOB", "testa").replace(
             "time.sleep(1)\n", "@unittest.skipIf(X, 'no X')\n          class T: pass\n")}),
        ("SkipTest in a one-line Python step",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: import unittest; raise unittest.SkipTest('no X (#12)')\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: \"import unittest; raise unittest.SkipTest('no X')\"\n"}),
        ("SkipTest in a one-line Python step with its issue in the YAML comment",
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: import unittest; raise unittest.SkipTest()  # #250\n"},
         {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                     "        run: import unittest; raise unittest.SkipTest()  # no issue\n"}),
        ("skipIf in a .yaml workflow",
         {".github/workflows/w.yaml": PY_STEP.replace("JOB", "testa").replace("time.sleep(1)\n", "x = 1\n")},
         {".github/workflows/w.yaml": PY_STEP.replace("JOB", "testa").replace(
             "time.sleep(1)\n", "@unittest.skipIf(X, 'no X')\n          class T: pass\n")}),
    ],
    "todo_markers": [
        ("in a comment", {"a.py": "PIXELS = ['XXX', '.X.']\n", "a.md": "o METODO e o MÉTODO\n"},
         {"a.py": "x = 1  # TODO later\n"}),
        ("in a .md", {"a.md": "TODOS os casos\n"}, {"a.md": "FIXME: this\n"}),
    ],
    "prose_justifications": [
        ("in a comment", {"a.py": "print('using the old one for now')\n"}, {"a.py": "x = 1  # for now\n"}),
        ("the issue at the top of the comment block",
         {"a.js": "/* (#119) a prova de que a aba voltou em branco: o pixel do meio. Sem prova\n"
                  "   (fora da mesa), a mesa inteira */\nlet a = 1;\n"},
         {"a.js": "/* a prova de que a aba voltou em branco: o pixel do meio. Sem prova\n"
                  "   (fora da mesa), a mesa inteira */\nlet a = 1;\n"}),
        ("an issue in the comment of the line before",
         {"a.py": "# the old reader stays for now\n# until #119 lands\nx = 1\n"},
         {"a.py": "a = 1  # issue #119\nb = 2  # for now\n"}),
        ("the issue on the next line of the paragraph",
         {"a.md": "The old reader stays for now, until\n[#119](https://github.com/o/r/issues/119) lands.\n"},
         {"a.md": "The old reader stays for now.\n\nSee #119 for another thing.\n"}),
        ("a word that holds the phrase, and a phrase across code",
         {"a.md": "Reproduced an unknown issue in the old build.\nThe known `config.json` issue.\n"},
         {"a.md": "Reproduced a known issue in the old build.\n"}),
        ("a phrase broken across two comment lines",
         {"a.py": "# Keep this fallback for\n# now, until #119 lands.\nx = 1\n"},
         {"a.py": "# Keep this fallback for\n# now.\nx = 1\n"}),
        ("a phrase broken across two lines",
         {"a.md": "The old reader stays por\nenquanto, until #119 lands.\n",
          "b.md": "The scoreboard counts `por enquanto` with no issue.\n"},
         {"a.md": "The old reader stays por\nenquanto.\n"}),
        ("a map row and a contributing note with no test",
         {"a.md": "| Sem teste | `compasso.py` | o PR diz como conferiu |\nThe window has no test yet: say how you checked.\n"},
         {"a.md": "| Sem teste | `compasso.py` | accepted risk |\n"}),
        ("a description of what did not change", {"a.md": "as rotas que trocam no laço ainda esperam ali, como antes\n"},
         {"a.md": "as rotas que trocam no laço ainda esperam ali, por enquanto\n"}),
        ("a docstring is not a comment", {"a.py": "def f():\n    '''Accepted risk.'''\n"},
         {"a.py": "def f():\n    '''Accepted risk.'''\n    return 1  # accepted risk\n"}),
        ("in a .md", {"a.md": "Sem prova: issue #5\n"}, {"a.md": "Sem prova.\n"}),
    ],
    "non_ascii_identifiers": [
        ("a name", {"a.py": "x = 'laço'\n"}, {"a.py": "laço = 1\n"}),
        ("an argument", {"a.py": "def f(a):\n    pass\n"}, {"a.py": "def f(ação):\n    pass\n"}),
        ("an except name", {"a.py": "try:\n    f()\nexcept OSError as e:\n    pass\n"},
         {"a.py": "try:\n    f()\nexcept OSError as ação:\n    pass\n"}),
        ("a match capture", {"a.py": "match x:\n    case [a, *b]:\n        pass\n"},
         {"a.py": "match x:\n    case [a, *ação]:\n        pass\n"}),
        ("a match as", {"a.py": "match x:\n    case int() as n:\n        pass\n"},
         {"a.py": "match x:\n    case int() as número:\n        pass\n"}),
        ("a name the parser folds to ASCII", {"a.py": "K = 1\n"}, {"a.py": "K = 1\n"}),
        ("an imported module", {"a.py": "from modulo import x\n"}, {"a.py": "from módulo import x\n"}),
        ("a part of a dotted module", {"a.py": "from cafe.api import route\n"}, {"a.py": "from café.api import route\n"}),
        ("the original name of an alias", {"a.py": "import modulo as m\n"}, {"a.py": "import módulo as m\n"}),
        ("an alias", {"a.py": "import modulo as m\n"}, {"a.py": "import modulo as ação\n"}),
        ("a match mapping rest", {"a.py": "match x:\n    case {'a': 1, **r}:\n        pass\n"},
         {"a.py": "match x:\n    case {'a': 1, **resto_ç}:\n        pass\n"}),
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
    "automatico_reaches": [
        ("a reach from another module", HOOKS_BASE, {**HOOKS_BASE, "comandos.py": "def f(a):\n    return a._round()\n"}),
    ],
    "library_reaches": [
        ("a reach from the rest of server.py",
         {**HOOKS_BASE, "server.py": SERVER + "\n\ndef f(lib):\n    return lib.books\n"},
         {**HOOKS_BASE, "server.py": SERVER + "\n\ndef f(lib):\n    return lib._books()\n"}),
    ],
    "app_writes": [
        ("a write to the App's state", {**HOOKS_BASE, "comandos.py": "def f(A):\n    return A.queue[0]\n"},
         {**HOOKS_BASE, "comandos.py": "def f(A):\n    A.queue.append(1)\n"}),
    ],
    "engine_writes": [
        ("a write to the engine's state", {**HOOKS_BASE, "comandos.py": "def f(E):\n    return E.pos\n"},
         {**HOOKS_BASE, "comandos.py": "def f(E):\n    E.pos = 1\n"}),
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
        ("a numbered item after one with its check", {"AGENTS.md": "# A\n\n1. A rule that `testa_i18n` holds.\n"},
         {"AGENTS.md": "# A\n\n1. A rule that `testa_i18n` holds.\n2. A rule with no check.\n"}),
        ("a sub-item after one with its check", {"AGENTS.md": AGENTS_OK},
         {"AGENTS.md": AGENTS_OK + "  - a sub-rule with no check.\n"}),
        ("a test taken out of the registry of the tree measured",
         {"AGENTS.md": "# A\n\n- A rule that `testa_x` holds.\n", "dev/testa_tudo.py": TUDO},
         {"AGENTS.md": "# A\n\n- A rule that `testa_x` holds.\n",
          "dev/testa_tudo.py": TUDO.replace('["dev/testa_x.py"]', "[]")}),
        ("a job of the testa.yml", {"AGENTS.md": AGENTS_OK + "- The `Testa o PR` check.\n",
                                    ".github/workflows/testa.yml": "on:\n  push:\njobs:\n  x:\n    name: Testa o PR\n"},
         {"AGENTS.md": AGENTS_OK + "- The `Testa o PR` check.\n"}),
        ("a check named in double quotes is no citation", {"AGENTS.md": AGENTS_OK, ".github/workflows/testa.yml": "on:\n  push:\njobs:\n  x:\n    name: Testa o PR\n"},
         {"AGENTS.md": AGENTS_OK + "- Run \"testa_i18n\" and \"Testa o PR\" before the queue.\n", ".github/workflows/testa.yml": "on:\n  push:\njobs:\n  x:\n    name: Testa o PR\n"}),
        ("the name of another workflow is no check", {"AGENTS.md": AGENTS_OK, ".github/workflows/monta.yml": "name: Monta o instalador\non:\n  push:\njobs:\n  testa-parcial:\n    runs-on: windows-2025\n"},
         {"AGENTS.md": AGENTS_OK + "- Run `Monta o instalador` on the branch.\n", ".github/workflows/monta.yml": "name: Monta o instalador\non:\n  push:\njobs:\n  testa-parcial:\n    runs-on: windows-2025\n"}),
        ("a job with words after it is no citation, a registered step with its option is",
         {"AGENTS.md": AGENTS_OK + "- A rule held by `testa_pasta_protegida --disco`.\n", ".github/workflows/testa.yml": "on:\n  push:\njobs:\n  testes:\n    name: Testes\n"},
         {"AGENTS.md": AGENTS_OK + "- A rule of the `testes inventado` job.\n", ".github/workflows/testa.yml": "on:\n  push:\njobs:\n  testes:\n    name: Testes\n"}),
        ("a script registered only as a step, with its option",
         {"AGENTS.md": "# A\n\n- A rule held by `test_smoke --strict`.\n",
          "dev/testa_tudo.py": TUDO.replace("PASSOS = {}", "PASSOS = {'smoke': ('dev/test_smoke.py', '--strict')}")},
         {"AGENTS.md": "# A\n\n- A rule held by `test_smoke`.\n",
          "dev/testa_tudo.py": TUDO.replace("PASSOS = {}", "PASSOS = {'smoke': ('dev/test_smoke.py', '--strict')}")}),
        ("a test with an option that is not registered",
         {"AGENTS.md": AGENTS_OK + "- A rule held by `fitcheck.py --metricas`.\n"},
         {"AGENTS.md": AGENTS_OK + "- A rule held by `testa_pasta_protegida --dsico`.\n"}),
        ("a row of the map with no check in its test column",
         {"AGENTS.md": "# A\n\n| Area | Files | Test |\n| --- | --- | --- |\n| Texts | `i18n.py` | `testa_i18n` |\n"},
         {"AGENTS.md": "# A\n\n| Area | Files | Test |\n| --- | --- | --- |\n| Texts | `i18n.py` | `testa_i18n` |\n| Window | `janela.py` | `engine.py` |\n"}),
        ("a row of the map whose test column is empty",
         {"AGENTS.md": "# A\n\n| Area | Files | Test |\n| --- | --- | --- |\n| Texts | `i18n.py` | `testa_i18n` |\n"},
         {"AGENTS.md": "# A\n\n| Area | Files | Test |\n| --- | --- | --- |\n| Texts | `i18n.py` | `testa_i18n` |\n| Texts | `testa_i18n` ||\n"}),
        ("a row of the map without its test column",
         {"AGENTS.md": "# A\n\n| Area | Files | Test |\n| --- | --- | --- |\n| Texts | `i18n.py` | `testa_i18n` |\n"},
         {"AGENTS.md": "# A\n\n| Area | Files | Test |\n| --- | --- | --- |\n| Texts | `i18n.py` | `testa_i18n` |\n| Garden | `dev/garden.py` |\n"}),
        ("a job of another workflow is no check", {"AGENTS.md": AGENTS_OK, ".github/workflows/monta.yml": "name: Monta o instalador\non:\n  push:\njobs:\n  testa-parcial:\n    runs-on: windows-2025\n"},
         {"AGENTS.md": AGENTS_OK + "- The `testa-parcial` job of `monta.yml`.\n", ".github/workflows/monta.yml": "name: Monta o instalador\non:\n  push:\njobs:\n  testa-parcial:\n    runs-on: windows-2025\n"}),
    ],
}

KNOWN_MISSES_ISSUE = "https://github.com/ritmelli/ritmelli/issues/254"
KNOWN_MISSES = [
    ("broad_excepts", "a JavaScript catch that handles nothing but is not empty",
     {"a.js": "try { f(); } catch (e) { void e; }\n"},
     ((".js", ".html"), r"catch\s*(?:\([^)]*\))?\s*\{\s*void\s+[\w$]+\s*;?\s*\}")),

    ("retries", "a JavaScript failure told by an if (index.html, the transport not loaded)",
     {"a.js": "function carregarTransporte() {\n  s.onload = () => {\n"
              "    if (typeof TRANSPORTE === 'undefined') { s.remove(); reconT = setTimeout(conectar, 3000); return; }\n"
              "    carregar();\n  };\n}\nfunction conectar() {\n  carregarTransporte();\n}\n"},
     ((".js", ".html"), r"onload\s*=[^;]*?\{[^}]*?if\s*\([^)]*\)\s*\{[^}]*setTimeout\(")),
]


def count(name, files):
    return garden.count_of(garden.COUNTERS[name](garden.Tree(files)))


EXPECTED_HARMLESS = {"theme_inline_lines": 1, "engine_py_lines": 1, "server_py_lines": 1, "index_html_lines": 1,
                     "agents_md_lines": 1, "engine_hooks": 1, "out_of_repo_routes": 1, "engine_reaches": 0,
                     "app_reaches": 0}


def test_counters():
    check(set(CASES) == set(garden.COUNTERS), f"every counter has its cases (missing: "
          f"{sorted(set(garden.COUNTERS) - set(CASES))}, unknown: {sorted(set(CASES) - set(garden.COUNTERS))})")
    for name, cases in CASES.items():
        for label, harmless, weedy, *delta in cases:
            before, after = count(name, harmless), count(name, weedy)
            expected = EXPECTED_HARMLESS.get(name, 0)
            check(before == expected, f"{name}, {label}: the harmless case counts {expected} ({before})")
            step = delta[0] if delta else 1
            check(after == before + step, f"{name}, {label}: the weed counts {step} ({before} -> {after})")


def test_string_lines():
    two = "ps = ('do{Start-Sleep 1}while($a);'\n      'if($b){Start-Sleep 1}')\n" + RUN_PS
    items = garden.COUNTERS["sleeps_app"](garden.Tree({"a.py": two}))
    check(items == [("a.py", 1), ("a.py", 2)], f"each fragment of a concatenated string keeps its own line ({items})")
    between = "ps = ('do{f}while($a);'  # Start-Sleep here is a comment\n      'if($b){g}')\n" + RUN_PS
    check(garden.COUNTERS["sleeps_app"](garden.Tree({"a.py": between})) == [],
          "a comment between two fragments of a string is not part of it")
    wide = "x = 'ação'; ps = 'Start-Sleep 1'\n" + RUN_PS
    check(garden.COUNTERS["sleeps_app"](garden.Tree({"a.py": wide})) == [("a.py", 1)],
          "a string after a wide character is read whole")
    built = "n = 2\nps = (f'$fim=(Get-Date).AddSeconds({n:.0f});'\n      f'{n}-Service x; Start-Sleep {n}')\n" + RUN_PS
    items = garden.COUNTERS["sleeps_app"](garden.Tree({"a.py": built}))
    check(items == [("a.py", 3)], f"an f-string's fields read as PowerShell values, at their lines ({items})")
    for label, text, line in (
            ("an escaped newline stays on its line", "ps = 'Get-Date\\nStart-Sleep 1'\n", 1),
            ("the text after a field keeps its line", "n = 1\nps = f'''x {n}\n{n}; Start-Sleep 1'''\n", 3),
            ("a field over two lines moves the next line", "n = 1\nps = f'''x {\nn}\nStart-Sleep 1'''\n", 4)):
        items = garden.COUNTERS["sleeps_app"](garden.Tree({"a.py": text + RUN_PS}))
        check(items == [("a.py", line)], f"{label} ({items})")
    joined = "import subprocess\ncode = ','.join(['$a = 1', value])\nsubprocess.run(['powershell', '-Command', code])\n"
    problems = garden.measure({"a.py": joined})[1]
    check(problems == [], f"a value after the separator of a join reads as a value ({problems})")
    items = garden.COUNTERS["skipped_tests"](garden.Tree({"a.ps1": "$x = @'\n'--   o pedal ficou de fora'\n'@\n"}))
    check(items == [("a.ps1", 2)], f"each line of a PowerShell here-string is code at its own line ({items})")


def test_unreadable():
    for label, files, place in (
            ("Python file", {"a.py": "def f(:\n"}, "a.py:1: the Python reader stops here"),
            ("Python step", {".github/workflows/w.yml": "jobs:\n  j:\n    steps:\n      - shell: python\n"
                                                        "        run: |\n          def f(:\n"},
             ".github/workflows/w.yml:6: the Python reader stops here"),
            ("script passed to PowerShell",
             {"a.py": "import subprocess\ndef run(script):\n    subprocess.run(['powershell', '-Command', script])\n"},
             "a.py:3: the PowerShell reader can't follow the script"),
            ("testa.yml", {".github/workflows/testa.yml": "jobs:\n  a: [\n"},
             ".github/workflows/testa.yml:2: the YAML reader stops here"),
            ("script joined from a name with two values",
             {"a.py": "import subprocess\npart = 'Get-Date'\nif flag:\n    part = 'Start-Sleep 1'\n"
                      "ps = '\\n'.join([part])\n" + RUN_PS},
             "a.py:6: the PowerShell reader can't follow the script"),
            ("script set in a try and in its else",
             {"a.py": "import subprocess\nps = loader()\ntry:\n    ps = 'Get-Date'\nexcept OSError:\n    pass\n"
                      "else:\n    ps = 'Get-Item x'\n" + RUN_PS},
             "a.py:9: the PowerShell reader can't follow the script"),
            ("script set in both branches of an if inside another if",
             {"a.py": "import subprocess\nps = loader()\nif a:\n    if b:\n        ps = 'Get-Date'\n    else:\n"
                      "        ps = 'Get-Item x'\n" + RUN_PS},
             "a.py:8: the PowerShell reader can't follow the script"),
            ("script joined from a literal and an unknown value",
             {"a.py": "import subprocess\npart = 'Start-Sleep 1'\nif flag:\n    part = load()\nps = '\\n'.join([part])\n" + RUN_PS},
             "a.py:6: the PowerShell reader can't follow the script"),
            ("module script set again after the function",
             {"a.py": "import subprocess\nPS = 'Get-Date'\ndef run():\n    subprocess.run(['powershell', '-Command', PS])\n"
                      "PS = 'Start-Sleep 1'\n"},
             "a.py:4: the PowerShell reader can't follow the script"),
            ("Python step of a composite action",
             {"action.yml": "runs:\n  steps:\n    - shell: python\n      run: this is not Python!\n"},
             "action.yml:4: the Python reader stops here")):
        try:
            problems = garden.measure(files)[1]
        except ValueError as ex:
            problems = [repr(ex)]
        check(any(p.startswith(place) for p in problems), f"an unreadable {label} is reported at its place ({problems})")
    for label, text in (("a collection as a key", "? [a]\n: b\n"),
                        ("a list as the name of a job", "jobs: {one: {name: [hi]}}\n")):
        try:
            garden.measure({".github/workflows/testa.yml": text})
            crashed = ""
        except ValueError as ex:
            crashed = repr(ex)
        check(not crashed, f"a testa.yml with {label} does not stop the count ({crashed})")
    step = "runs:\n  steps:\n    - shell: python\n      run: this is not Python!\n"
    jobs = "jobs:\n  j:\n    steps:\n      - shell: python\n        run: this is not Python!\n"
    problems = garden.measure({"config.yml": step, "ci/ci.yml": jobs})[1]
    check(problems == [], f"a YAML that is no workflow and no action has no steps ({problems})")


def test_workflow_python_lines():
    quoted = WORKFLOW.replace("python3 {0}", '"python3 {0}"').replace("{handler}", "          except Exception:\n"
                                                                                  "              pass\n")
    found = garden.COUNTERS["broad_excepts"](garden.Tree({".github/workflows/w.yml": quoted}))
    check(found == [(".github/workflows/w.yml", 13)], f"a quoted shell is still Python, at its line ({found})")
    commented = WORKFLOW.replace("run: |", "run: |  # the check").replace(
        "{handler}", "          except Exception:\n              pass\n")
    found = garden.COUNTERS["broad_excepts"](garden.Tree({".github/workflows/w.yml": commented}))
    check(found == [(".github/workflows/w.yml", 13)], f"a block with a comment on its header is still read ({found})")
    shell_after = ("jobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n          try:\n"
                   "              pass\n          except Exception:\n              pass\n        shell: python\n")
    found = garden.COUNTERS["broad_excepts"](garden.Tree({".github/workflows/w.yml": shell_after}))
    check(found == [(".github/workflows/w.yml", 8)], f"a step that names its shell after the block ({found})")
    note = WORKFLOW.replace("          try:\n", "          '''Why the check reads the labels here.'''\n          try:\n").replace(
        "{handler}", "          except OSError:\n              pass\n")
    found = garden.COUNTERS["docstring_lines"](garden.Tree({".github/workflows/w.yml": note}))
    check(found == [(".github/workflows/w.yml", 11)], f"a module docstring in a workflow's Python step ({found})")
    name = WORKFLOW.replace("              pass\n{handler}", "              métrica = 1\n{handler}").replace(
        "{handler}", "          except OSError:\n              pass\n")
    found = garden.COUNTERS["non_ascii_identifiers"](garden.Tree({".github/workflows/w.yml": name}))
    check(found == [(".github/workflows/w.yml", 12)], f"a non-ASCII name in a workflow's Python step ({found})")
    retry = PY_STEP.replace("JOB", "monta").replace(
        "time.sleep(1)\n", "for _ in range(3):\n              try:\n                  f()\n                  break\n"
                           "              except OSError:\n                  time.sleep(1)\n")
    found = garden.COUNTERS["retries"](garden.Tree({".github/workflows/w.yml": retry}))
    check(found == [(".github/workflows/w.yml", 9)], f"a retry in a workflow step is listed at its line ({found})")


def uses_of(tree, suffixes, pattern):
    return [f"{path}:{text.count("\n", 0, m.start()) + 1}" for path, text in sorted(tree.items())
            if path.endswith(suffixes) for m in re.finditer(pattern, text)]


def test_known_misses():
    tree = garden.working_tree(ROOT)
    for name, label, files, detector in KNOWN_MISSES:
        check(count(name, files) == 0, f"known miss ({KNOWN_MISSES_ISSUE}): {name} does not count {label}; when it "
              f"does, move the case to CASES")
        check(bool(uses_of(files, *detector)), f"known miss ({KNOWN_MISSES_ISSUE}): the detector of {label} "
              f"finds its own case")
        used = uses_of(tree, *detector)
        check(not used, f"known miss ({KNOWN_MISSES_ISSUE}): the repo does not use {label} yet ({used[:3]}); "
              f"when it does, make {name} count it and move the case to CASES")


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
    _, first = garden.check({"a": 1}, {"a": 1}, None)
    check(first == ["-- summary: garden a: 1 (new, no ceiling on the base)"],
          f"with no base at all, every counter goes to the summary ({first})")
    failed, measured = garden.check({"a": [("x.py", 1)] * 2, "b": 5}, {"a": 2, "b": 5}, {"a": 3, "b": 5})
    check(failed == [] and measured == ["-- summary: garden a: 2 (-1 against the base)"],
          f"a base from before the scoreboard is measured: the delta of what changed ({measured})")
    for label, ceilings, base in (("NaN", {"a": float("nan")}, {"a": 1}), ("a text", {"a": "2"}, {"a": 1}),
                                  ("a negative number", {"a": -1}, {"a": 1}), ("NaN on the base", {"a": 2},
                                                                              {"a": float("nan")})):
        bad, _ = garden.check({"a": [("x.py", 1), ("x.py", 2)]}, ceilings, base)
        check(len(bad) == 1 and "not a whole number" in bad[0], f"a ceiling that is {label} fails ({bad})")
    _, quiet = garden.check({"a": 1}, {"a": 1}, {"a": 1})
    check(quiet == [], f"with no change, no summary line ({quiet})")


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
    base = garden.scoreboard(HOOKS_BASE)
    ceilings = {k: garden.count_of(v) for k, v in base.items()}
    writes = {**HOOKS_BASE, "comandos.py": "def f(A):\n    A.queue = []\n"}
    raised = dict(ceilings, app_writes=ceilings["app_writes"] + 1)
    failed, _ = garden.check(garden.scoreboard(writes), raised, ceilings, {"comandos.py": {2}})
    check(len(failed) == 1 and failed[0].startswith("app_writes: the ceiling went up"),
          f"a direct write to the App with app_writes raised along with it fails ({failed})")


def test_description():
    good = "The problem.\n\n**How it was proven**\n- `python dev/garden.py` fails on the base.\n"
    check(garden.description_problems(good) == [], "a description with a proof section passes")
    check(garden.description_problems("Proof: `python x.py` passes.") == [], "a proof line with its content passes")
    check(garden.description_problems("## Proof\n\nIt works.\n") != [], "a proof section with no run, test or print fails")
    check(garden.description_problems("The problem.\n") != [], "a description with no proof section fails")
    passing = {
        "a line label": "How it was proved: `python dev/testa_mock.py` passes 70 of 70.",
        "a heading with a list": "## How it was proven\n\n- `gh run view 1` shows the step failing on the base.\n",
        "a link to a run": "## Proof\n\nThe [run](https://github.com/o/r/actions/runs/123) fails on the base.\n",
        "a screenshot": "**Proof**\n\n![the page](https://github.com/user-attachments/assets/1)\n",
        "a command after a prompt": "## Proof\n\n```\n$ python dev/testa_i18n.py\n```\n",
        "a test's output": "## Proof\n\n```\nok    the keys\n```\n",
        "a test runner's output": "## Proof\n\n```\n===== 12 passed in 3.1s =====\n```\n",
        "the summary of dev/testa_tudo.py": "## Proof\n\n```\n14 of 14 passed in 37 s, 4 at a time\n```\n",
        "a heading inside the code block": "# Change\n\n## Proof\n\n```bash\n# Before\n$ python dev/x.py\nfails\n```\n",
        "bold sub-labels under the heading": "## Proof\n\n**Before the change** ([run 1](https://github.com/o/r/"
                                             "actions/runs/1)): fails.\n",
        "a checked item": "## Proof\n\n- [x] `python dev/testa_i18n.py` passes.\n",
        "an open item next to a run": "## Proof\n\n- [ ] the phone\n- `python dev/testa_i18n.py` passes.\n",
        "a Test results heading": "## Test results\n\n`python dev/test_garden.py` passed.\n",
        "a Verification heading": "## Verification\n\n`python dev/test_garden.py` passed.\n",
        "a Testing heading": "## Testing\n\n`python dev/test_garden.py` passed.\n",
        "a run after a subcommand": "## Proof\n\nruff check . passed.\n",
        "an option after a subcommand": "## Proof\n\ngit diff --check passed.\n",
        "a run told in plain text": "## Proof\n\nRan python dev/test_garden.py successfully.\n",
        "a test named in plain text with its result": "## Proof\n\ntesta_i18n passes 70 of 70.\n",
        "a label and test names under the heading": "## How it was proved\n\nLocally: `testa_tudo` 30/30 and "
                                                    "`--microfone` 4/4.\n",
    }
    passing["a phrase quoted as code"] = good + "\nThe check fails on `for now` with no issue link.\n"
    passing["a phrase in a pasted log"] = ("## Proof\n\n```\n$ python dev/garden.py --pr-description\n"
                                           "FAIL  PR #9 description: line 4: \"for now\" with no issue link\n```\n")
    for label, body in passing.items():
        check(garden.description_problems(body) == [], f"a proof section with {label} passes")
    failing = {
        "loose backticks": "Proof: `trust me`",
        "an issue link as the only proof": "## Proof\n\nSee #12 and https://github.com/o/r/issues/12.\n",
        "the proof after the section ends": "## Proof\n\nIt works.\n\n## Notes\n\n`python dev/x.py`\n",
        "a heading with nothing under it": "## Proof\n## Other\n![a](https://x/a.png)\n",
        "a plain label after it": "Proof: it works.\nNotes: `python dev/x.py` is the next step.\n",
        "an empty code block": "## Proof\n\n```\n```\n",
        "a code block with no run in it": "## Proof\n\n```\nIt works.\n```\n",
        "a prompt with no command": "## Proof\n\n```\n> everything passed\n```\n",
        "a code block with only a claim": "## Proof\n\n```\nAll tests passed.\n```\n",
        "a code block that reports a claim": "## Proof\n\n```\nThe reviewer said 12 passed.\n```\n",
        "an option alone": "## Proof\n\n`--help`\n",
        "a production file": "## Proof\n\n`engine.py` is fine.\n",
        "a command with nothing to run": "## Proof\n\n`python`\n",
        "a command alone on the block's first line": "## Proof\n\n```\npython\nAll tests passed.\n```\n",
        "an issue number inside code": "## Proof\n\n- `python dev/garden.py` fails on the base.\n\n"
                                        "The rest stays for now (`#250`).\n",
        "an issue number inside double backticks": "## Proof\n\n- `python dev/garden.py` fails on the base.\n\n"
                                                    "The rest stays for now (``#250``).\n",
        "a proof hidden in an HTML comment": "## Proof\n<!-- `python dev/garden.py` fails on the base -->\n",
        "a code block that never closes": "## Proof\n\n```\npython dev/x.py\n```text\n",
        "a proof section only inside an example block": "```markdown\n## Proof\n`python dev/garden.py`\n```\n",
        "a fragment of a link as the issue": good + "\nThe rest stays for now ([details](https://example.org/page#250)).\n",
        "an issues path off GitHub as the issue": good + "\nThe rest stays for now (https://example.org/issues/250).\n",
        "a host that ends in github.com": good + "\nThe rest stays for now (https://not-github.com/o/r/issues/250).\n",
        "a fragment after a dash": good + "\nThe rest stays for now (https://example.org/page-#250).\n",
        "an issues path of GitHub on another host": good + "\nThe rest stays for now "
                                                          "(https://example.org/github.com/o/r/issues/250).\n",
        "a run link only as an example in code": "## Proof\n\nThe link looks like `https://github.com/o/r/actions/runs/1`.\n",
        "a run link as an example in code across lines": "## Proof\n\nThe link looks like `see\n"
                                                         "https://github.com/o/r/actions/runs/1`.\n",
        "an image as an example in code across lines": "## Proof\n\nLike `this\n![a](https://github.com/user-attachments/"
                                                       "assets/1)` here.\n",
        "an image only as an example in code":"## Proof\n\n`![a](https://github.com/user-attachments/assets/1)`\n",
        "a proof label inside an open numbered item": "## Proof\n\n1. [ ] Pending\n   **Proof**\n"
                                                      "   `python dev/testa_i18n.py`\n",
        "a zip of logs as the only attachment": "## Proof\n\n[Download logs](https://github.com/user-attachments/files/"
                                                "123/logs.zip)\n",
        "only an open checklist item":"## Proof\n\n- [ ] `python dev/testa_i18n.py`\n  ```\n  ok    the keys\n"
                                       "  ```\n",
        "an anchor as the link's target": good + "\nThe rest stays for now ([details](#250)).\n",
        "the issue in the next paragraph": good + "\nThe rest stays for now.\n\nSee #250.\n",
        "the issue in the next list item, in bold": good + "\n- The rest stays for now.\n"
                                                     "- **[#250](https://github.com/o/r/issues/250)** is another.\n",
        "the issue in the next list item": good + "\n- The rest stays for now.\n- #250 is another thing.\n",
    }
    for label, body in failing.items():
        check(garden.description_problems(body) != [], f"a proof section with {label} fails")
    prose = good + "\nThe rest stays for now.\n"
    check(any("for now" in p for p in garden.description_problems(prose)), "a prose phrase with no issue fails")
    check(garden.description_problems(good + "\nThe fallback stays for now, tracked in ritmelli/ritmelli#254.\n") == [],
          "a prose phrase with an owner/repo#n reference passes")
    check(garden.description_problems(good + "\nThe rest stays for now (#250).\n") == [],
          "a prose phrase with its issue passes")
    check(garden.description_problems(good + "\nThe rest stays for now ([details](https://github.com/o/r/issues/250)).\n")
          == [], "a prose phrase with a link to its issue passes")
    check(garden.description_problems(good + "\nThe rest stays for now, tracked in\nhttps://github.com/o/r/issues/250.\n")
          == [], "a prose phrase with its issue on the next line of the paragraph passes")
    check(garden.description_problems(good + "\nThe rest stays for now, tracked in\n"
                                             "**[#250](https://github.com/o/r/issues/250)**.\n") == [],
          "a prose phrase with its issue in bold on the next line of the paragraph passes")
    for label, line in [("a closing line", "Closes #280"), ("a closing list item", "- Fixes #12"),
                        ("closing lines joined", "Closes #1, fixes #2 and resolves o/r#3"),
                        ("closing lines joined with a comma and an and", "Closes #1, fixes #2, and resolves #3"),
                        ("closing lines joined with a semicolon", "Closes #1; fixes #2"),
                        ("a closing line that goes on", "Closes #272: the per-file cases that failed now and then"),
                        ("a closing line with another issue after it", "Closes #196. #197, the pair, stays open."),
                        ("a reference with no closing word", "It leaves the cause of #276 open."),
                        ("a reference to keep", "Refs #276"), ("a closing word in code", "The `fixes #3` text."),
                        ("a closing word with no issue", "It fixes the loop."), ("a word that ends in fix", "prefixes #4")]:
        check(garden.description_problems(good + "\n" + line + "\n") == [], f"{label} passes")
    check(garden.description_problems(good + "\n```\nIt does not fix #9.\n```\n") == [], "a closing word in a code block passes")
    for label, line in [("the closing word after a negation (#290)", "This PR adds that diagnostic. It does not fix #276."),
                        ("a closing word after a closing line", "Closes #1. It does not fix #2."),
                        ("a closing word in a sentence", "This might fix #12 too."),
                        ("a closing word with a colon and another repo", "It is fixed: o/r#5 in passing."),
                        ("a closing word with the issue link", "Nothing here resolves https://github.com/o/r/issues/7.")]:
        problems = garden.description_problems(good + "\n" + line + "\n")
        check(len(problems) == 1 and "closes the issue" in problems[0], f"{label} fails ({problems})")
    check(garden.pr_number("pull_request", {"pull_request": {"number": 7}}) == 7, "the PR number of a pull_request")
    check(garden.pr_number("merge_group", {"merge_group": {"head_ref": "refs/heads/gh-readonly-queue/main/pr-246-"
                                                           + "a" * 40}}) == 246, "the PR number of a merge_group entry")
    check(garden.pr_number("push", {}) is None, "no PR on a push")


def run_description(event_name, event, body):
    asked = []

    def fetch(repo, number):
        asked.append((repo, number))
        return body
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "event.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        saved = {k: os.environ.get(k) for k in ("GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH", "GITHUB_REPOSITORY")}
        os.environ.update(GITHUB_EVENT_NAME=event_name, GITHUB_EVENT_PATH=str(path), GITHUB_REPOSITORY="o/r")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = garden.check_description(fetch)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return code, asked


def test_description_step():
    good = "**How it was proven**\n- `python dev/garden.py` fails on the base.\n"
    queue = {"merge_group": {"head_ref": "refs/heads/gh-readonly-queue/main/pr-9-" + "b" * 40}}
    code, asked = run_description("pull_request", {"pull_request": {"number": 9}}, good)
    check(code == 0 and asked == [("o/r", 9)], f"on the PR, the description is read from the API and passes ({asked})")
    code, asked = run_description("merge_group", queue, "Edited after the green check.\n")
    check(code == 1 and asked == [("o/r", 9)], "in the queue, a description edited to drop its proof fails")
    code, asked = run_description("merge_group", {"merge_group": {"head_ref": "refs/heads/main"}}, good)
    check(code == 1 and asked == [], "a queue entry that names no PR fails")
    code, asked = run_description("pull_request", {}, good)
    check(code == 1 and asked == [], "a pull_request event with no PR number fails")
    code, asked = run_description("push", {}, good)
    check(code == 0 and asked == [], "a push has no description to check")


def base_in(env):
    saved = {k: os.environ.get(k) for k in ("GITHUB_EVENT_NAME", "GITHUB_REF", "BASE")}
    os.environ.update(env)
    try:
        return garden.base_commit()
    except garden.BaseError:
        return None
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_queue_base():
    entry = "c" * 40
    base = base_in({"GITHUB_EVENT_NAME": "merge_group", "GITHUB_REF": f"refs/heads/gh-readonly-queue/main/pr-9-{entry}",
                    "BASE": "a" * 40})
    check(base == entry, f"a queue entry is compared to the commit it was built on, not the queue's base ({base})")
    check(base_in({"GITHUB_EVENT_NAME": "merge_group", "GITHUB_REF": "refs/heads/main", "BASE": "a" * 40}) is None,
          "a queue entry whose ref names no base fails")
    check(base_in({"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/9/merge", "BASE": "b" * 40}) == "b" * 40,
          "a PR is compared to its base")


def run_in(repo, env):
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = garden.run(repo)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return code, out.getvalue()


def ceilings_of(files):
    return json.dumps({k: garden.count_of(v) for k, v in garden.scoreboard(files).items()}) + "\n"


def test_queue_run():
    two = {"a.py": "x = 1  # one\ny = 2  # two\n"}
    one = {"a.py": "x = 1  # one\ny = 2\n"}
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        garden.git("init", "-q", root=repo)
        garden.git("config", "core.autocrlf", "false", root=repo)
        main = commit(repo, {**two, "dev/garden.json": ceilings_of(two)}, "main, two comments")
        first = commit(repo, {**one, "dev/garden.json": ceilings_of(one)}, "the first entry takes one out")
        for path, text in {**two, "dev/garden.json": ceilings_of(two)}.items():
            (repo / path).write_bytes(text.encode("utf-8"))
        queue = {"GITHUB_EVENT_NAME": "merge_group", "BASE": main,
                 "GITHUB_REF": f"refs/heads/gh-readonly-queue/main/pr-9-{first}"}
        code, out = run_in(repo, queue)
        check(code == 1 and "comment_lines: the ceiling went up from 1 to 2" in out,
              "the second entry of the queue puts the comment back with the ceiling, and fails against the first entry")
        code, out = run_in(repo, {"GITHUB_EVENT_NAME": "pull_request", "BASE": main, "GITHUB_REF": "refs/pull/9/merge"})
        check(code == 0 and "-- summary:" not in out,
              f"the same tree as a PR against main passes ({out.splitlines()[-1:]})")


def test_measured_base():
    catch = {"a.ps1": "try { f } catch { }\n"}
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        garden.git("init", "-q", root=repo)
        garden.git("config", "core.autocrlf", "false", root=repo)
        blind = json.loads(ceilings_of(catch))
        blind["broad_excepts"] = 0
        main = commit(repo, {**catch, "dev/garden.json": json.dumps(blind) + "\n"},
                      "main, from a counter that did not see the catch")
        (repo / "dev" / "garden.json").write_text(ceilings_of(catch), encoding="utf-8")
        code, out = run_in(repo, {"GITHUB_EVENT_NAME": "pull_request", "BASE": main, "GITHUB_REF": "refs/pull/9/merge"})
        check(code == 0, "a counter that learns to see a weed already on the base raises its ceiling to the base's "
                         f"count, measured with this code ({out.splitlines()[-1:]})")
        two = {"a.ps1": "try { f } catch { }\ntry { g } catch { }\n"}
        (repo / "a.ps1").write_text(two["a.ps1"], encoding="utf-8")
        (repo / "dev" / "garden.json").write_text(ceilings_of(two), encoding="utf-8")
        code, out = run_in(repo, {"GITHUB_EVENT_NAME": "pull_request", "BASE": main, "GITHUB_REF": "refs/pull/9/merge"})
        check(code == 1 and "broad_excepts: the ceiling went up from 1 to 2" in out,
              "a new catch with its ceiling still fails against the base measured with this code")
        (repo / "a.ps1").write_text("try { f\n", encoding="utf-8")
        code, out = run_in(repo, {"GITHUB_EVENT_NAME": "pull_request", "BASE": main, "GITHUB_REF": "refs/pull/9/merge"})
        check(code == 1 and "unreadable: a.ps1:2: the PowerShell reader stops here" in out,
              f"a file the reader can't read fails with its place ({[x for x in out.splitlines() if 'unreadable' in x]})")


def commit(repo, files, message):
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(text.encode("utf-8"))
    garden.git("add", "-A", root=repo)
    garden.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", message, root=repo)
    return garden.git("rev-parse", "HEAD", root=repo)[1].strip()


def test_base():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        garden.git("init", "-q", root=repo)
        garden.git("config", "core.autocrlf", "false", root=repo)
        before = commit(repo, {"a.py": "x = 1  # why\r\n", "engine.py": "x = 1\n", "c.iss": "﻿; why\n"},
                        "before the scoreboard")
        after = commit(repo, {"a.py": "x = 1  # why\ny = 2  # and why\n", "dev/garden.json": '{"comment_lines": 2}\n'},
                       "the scoreboard")
        try:
            garden.verify_base("not-a-commit", root=repo)
            raised = False
        except garden.BaseError:
            raised = True
        check(raised, "a base that is not a commit fails instead of reading as a base with nothing to measure")
        garden.verify_base(before, root=repo)
        garden.verify_base(after, root=repo)
        garden.verify_base("", root=repo)
        blob = subprocess.run(["git", "cat-file", "-p", f"{before}:a.py"], cwd=repo, capture_output=True).stdout
        check(blob == b"x = 1  # why\r\n", f"the fixture's blob keeps its CRLF ({blob!r})")
        (repo / "b.iss").write_bytes("﻿; why\n[Setup]\n".encode("utf-8"))
        seen = garden.working_tree(repo).get("b.iss", "")
        check(seen.startswith(";") and count("comment_lines", {"b.iss": seen}) == 1,
              f"a file with a BOM keeps its first line in the count ({seen[:8]!r})")
        (repo / "b.iss").unlink()
        tree = garden.base_tree(before, root=repo)
        check(tree == {"a.py": "x = 1  # why\n", "engine.py": "x = 1\n", "c.iss": "; why\n"},
              f"the base tree is read from git, with its text files and no BOM ({tree})")
        measured = {k: garden.count_of(v) for k, v in garden.scoreboard(tree).items()}
        now = garden.scoreboard(garden.base_tree(after, root=repo))
        ceilings = {k: garden.count_of(v) for k, v in now.items()}
        failed, summary = garden.check(now, ceilings, measured)
        check(summary == ["-- summary: garden comment_lines: 3 (+1 against the base)"],
              f"against a measured base, only the counter that changed goes to the summary ({summary})")
        check(failed == ["comment_lines: the ceiling went up from 2 to 3 in dev/garden.json: a ceiling only goes down"],
              f"the PR that brings the scoreboard can't raise a count with its first ceilings either ({failed})")


PASSO = "python dev/testa_tudo.py --passo pr-description"


def workflow_problems(text):
    try:
        doc = workflow_yaml.loads(text, name="testa.yml")
    except workflow_yaml.YamlError as ex:
        return [f"the workflow does not read: {ex}"]
    tudo = garden.testa_tudo()
    problems = [f for f in tudo.mode_failures({".github/workflows/testa.yml": doc}) if "--passo pr-description" in f]
    if tudo.PASSOS.get("pr-description") != ("dev/garden.py", "--pr-description"):
        problems.append("the pr-description step of PASSOS does not run dev/garden.py --pr-description")
    job = (doc.get("jobs") or {}).get("testes") or {}
    step = workflow_yaml.find_step(job, "PR description") or {}
    if (step.get("run") or "").strip() != PASSO:
        problems.append(f"the step runs something else than \"{PASSO}\"")
    if (step.get("env") or {}).get("GH_TOKEN") != "${{ github.token }}":
        problems.append("the step has no GH_TOKEN to read the API")
    if (job.get("permissions") or {}).get("pull-requests") != "read":
        problems.append("the testes job can't read the PR")
    return problems


WORKFLOW_MUTANTS = [
    ("the step skipped in the queue", "      - name: PR description\n        if: ${{ !cancelled() }}",
     "      - name: PR description\n        if: ${{ !cancelled() && github.event_name != 'merge_group' }}"),
    ("the step renamed", "      - name: PR description", "      - name: PR text"),
    ("no token", "          GH_TOKEN: ${{ github.token }}\n        run: " + PASSO, "        run: " + PASSO),
    ("no permission to read the PR", "      contents: read\n      pull-requests: read\n    outputs:",
     "      contents: read\n    outputs:"),
    ("another command", "run: " + PASSO, "run: python dev/testa_tudo.py --passo disco"),
    ("an exit before the command", "        run: " + PASSO, "        run: |\n          exit 0\n          " + PASSO),
    ("the step quiet on failure", "        run: " + PASSO, "        continue-on-error: true\n        run: " + PASSO),
    ("the job skipped in the queue", "    name: Testes\n    if: github.event_name != 'push'",
     "    name: Testes\n    if: github.event_name == 'pull_request'"),
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
    generator = (ROOT / "dev" / "molduras.py").read_text(encoding="utf-8")
    check(all(f"/* {m} */" in generator for m in garden.GENERATED_MARKERS),
          "the generated marker kept out of the count is the one dev/molduras.py writes")
    tree = garden.Tree(garden.working_tree())
    hooks = garden.COUNTERS["engine_hooks"](tree)
    code = tree.lexed("engine.py").code
    docs = {n for p, n in garden.docstring_lines(tree) if p == "engine.py"}
    check(all(code.get(n, "").strip() and n not in docs for _, n in hooks),
          "each hook of engine.py is listed at a line of code, not of a comment or docstring")


test_counters()
test_known_misses()
test_string_lines()
test_workflow_python_lines()
test_check()
test_acceptance()
test_description()
test_base()
test_queue_base()
test_queue_run()
test_measured_base()
test_unreadable()
test_description_step()

WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "testa.yml").read_text(encoding="utf-8")
problems = workflow_problems(WORKFLOW_TEXT)
check(problems == [], f"the PR description step runs in the required check on every PR and queue entry ({problems})")
test_workflow_mutants(WORKFLOW_TEXT)
test_stdlib()
print(f"{len(failures)} failure(s)" if failures else "ok    all garden cases")
sys.exit(1 if failures else 0)
