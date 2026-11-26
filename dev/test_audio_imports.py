import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER_ONLY = {"yt_fora", "yt_dlp", "ytmusicapi", "requests"}
ENTRY = "server"


def module_name(path):
    parts = list(Path(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def loaded_names(tree, package):
    names = set()
    statements = list(tree.body)
    while statements:
        s = statements.pop()
        if isinstance(s, ast.Import):
            names |= {a.name for a in s.names}
        elif isinstance(s, ast.ImportFrom):
            base = s.module or ""
            if s.level:
                anchor = package.split(".")[:len(package.split(".")) - s.level + 1] if package else []
                base = ".".join([*anchor, *([base] if base else [])])
            names.add(base)
            names |= {f"{base}.{a.name}" if base else a.name for a in s.names}
        elif isinstance(s, (ast.If, ast.Try, ast.With)):
            statements += s.body + getattr(s, "orelse", []) + getattr(s, "finalbody", [])
            statements += [x for h in getattr(s, "handlers", []) for x in h.body]
    return {n for n in names if n}


def heavy_at_load(files):
    modules = {module_name(p): (text, Path(p).name == "__init__.py") for p, text in files.items() if p.endswith(".py")}
    seen, todo, found = set(), [ENTRY], []
    while todo:
        name = todo.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        text, is_package = modules[name]
        package = name if is_package else name.rpartition(".")[0]
        loaded = loaded_names(ast.parse(text), package)
        found += [(name, m) for m in sorted(loaded) if m.split(".")[0] in HELPER_ONLY]
        for m in sorted(loaded):
            parts = m.split(".")
            todo += [".".join(parts[:k]) for k in range(1, len(parts) + 1)]
    return sorted(set(found))


CASES = [
    ("a module the server loads imports the YouTube helper", 1,
     {"server.py": "import comandos\n", "comandos.py": "import yt_fora\n"}),
    ("the helper's library under a try at the top of a module", 1,
     {"server.py": "try:\n    import yt_dlp\nexcept ImportError:\n    yt_dlp = None\n"}),
    ("a module of a local package the server loads", 1,
     {"server.py": "from microfone import preset\n", "microfone/__init__.py": "",
      "microfone/preset.py": "import requests\n"}),
    ("a relative import inside a local package", 1,
     {"server.py": "import microfone.injeta\n", "microfone/__init__.py": "",
      "microfone/injeta.py": "from . import rede\n", "microfone/rede.py": "import ytmusicapi\n"}),
    ("a lazy import inside a function stays in the helper", 0,
     {"server.py": "import andamento\n", "andamento.py": "def mede():\n    from yt_fora import stream_yt\n"}),
    ("a module the server never loads", 0, {"server.py": "import os\n", "yt_tool.py": "import yt_dlp\n"}),
]


def repo_files():
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py")
            if not {"dev", ".git", ".venv", "venv", "build", "dist"} & set(p.relative_to(ROOT).parts)}


def main():
    failed = False
    for label, expected, files in CASES:
        got = len(heavy_at_load(files))
        ok = got == expected
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label}: {got} (expected {expected})")
    found = heavy_at_load(repo_files())
    for module, name in found:
        print(f"FAIL  {module} loads {name} in the audio process: a slow library runs in a helper process "
              f"(ritmelli.py --yt), imported inside the function that the helper runs")
    if not found:
        print(f"ok    the server's process loads none of {', '.join(sorted(HELPER_ONLY))}")
    return 1 if failed or found else 0


if __name__ == "__main__":
    sys.exit(main())
