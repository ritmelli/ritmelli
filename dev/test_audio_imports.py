import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER_ONLY = {"yt_fora", "yt_dlp", "ytmusicapi", "requests"}
ENTRY = "server"


def loaded_names(tree):
    names = set()
    statements = list(tree.body)
    while statements:
        s = statements.pop()
        if isinstance(s, ast.Import):
            names |= {a.name.split(".")[0] for a in s.names}
        elif isinstance(s, ast.ImportFrom) and s.module and not s.level:
            names.add(s.module.split(".")[0])
        elif isinstance(s, (ast.If, ast.Try, ast.With)):
            statements += s.body + getattr(s, "orelse", []) + getattr(s, "finalbody", [])
            statements += [x for h in getattr(s, "handlers", []) for x in h.body]
    return names


def heavy_at_load(files):
    modules = {Path(p).stem: text for p, text in files.items() if "/" not in p and p.endswith(".py")}
    seen, todo, found = set(), [ENTRY], []
    while todo:
        name = todo.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        loaded = loaded_names(ast.parse(modules[name]))
        found += [(name, m) for m in sorted(loaded & HELPER_ONLY)]
        todo += sorted(loaded & modules.keys())
    return found


CASES = [
    ("a module the server loads imports the YouTube helper", 1,
     {"server.py": "import comandos\n", "comandos.py": "import yt_fora\n"}),
    ("the helper's library under a try at the top of a module", 1,
     {"server.py": "try:\n    import yt_dlp\nexcept ImportError:\n    yt_dlp = None\n"}),
    ("a lazy import inside a function stays in the helper", 0,
     {"server.py": "import andamento\n", "andamento.py": "def mede():\n    from yt_fora import stream_yt\n"}),
    ("a module the server never loads", 0, {"server.py": "import os\n", "yt_tool.py": "import yt_dlp\n"}),
]


def main():
    failed = False
    for label, expected, files in CASES:
        got = len(heavy_at_load(files))
        ok = got == expected
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label}: {got} (expected {expected})")
    files = {p.name: p.read_text(encoding="utf-8") for p in ROOT.glob("*.py")}
    found = heavy_at_load(files)
    for module, name in found:
        print(f"FAIL  {module}.py loads {name} in the audio process: a slow library runs in a helper process "
              f"(ritmelli.py --yt), imported inside the function that the helper runs")
    if not found:
        print(f"ok    the server's process loads none of {', '.join(sorted(HELPER_ONLY))}")
    return 1 if failed or found else 0


if __name__ == "__main__":
    sys.exit(main())
