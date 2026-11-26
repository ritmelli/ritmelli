import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER_ONLY = {"yt_fora", "yt_dlp", "ytmusicapi", "requests"}
HELPER_ENTRIES = {"andamento": "main"}
ENTRY = "server"


def module_name(path):
    parts = list(Path(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def type_checking(node):
    test = node.test
    return isinstance(node, ast.If) and (
        (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
        or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"))


def import_nodes(tree, skip_function=None):
    todo = list(ast.iter_child_nodes(tree))
    while todo:
        node = todo.pop()
        if isinstance(node, ast.If) and type_checking(node):
            todo += node.orelse
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == skip_function:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        todo += list(ast.iter_child_nodes(node))


def loaded_names(tree, package, skip_function=None):
    names = set()
    for s in import_nodes(tree, skip_function):
        if isinstance(s, ast.Import):
            names |= {a.name for a in s.names}
            continue
        base = s.module or ""
        if s.level:
            anchor = package.split(".")[:len(package.split(".")) - s.level + 1] if package else []
            base = ".".join([*anchor, *([base] if base else [])])
        names.add(base)
        names |= {f"{base}.{a.name}" if base else a.name for a in s.names}
    return {n for n in names if n}


def entry_calls(module, tree):
    aliases = {}
    for s in import_nodes(tree):
        if isinstance(s, ast.Import):
            aliases |= {(a.asname or a.name): a.name for a in s.names if a.name in HELPER_ENTRIES}
        elif s.module in HELPER_ENTRIES and not s.level:
            aliases |= {(a.asname or a.name): f"{s.module}.{a.name}" for a in s.names
                        if a.name == HELPER_ENTRIES[s.module]}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in aliases
                and f.attr == HELPER_ENTRIES.get(aliases[f.value.id])):
            found.append((module, f"{aliases[f.value.id]}.{f.attr}"))
        elif isinstance(f, ast.Name) and aliases.get(f.id, "").count(".") == 1:
            found.append((module, aliases[f.id]))
    return found


def heavy_in_process(files):
    modules = {module_name(p): (text, Path(p).name == "__init__.py") for p, text in files.items() if p.endswith(".py")}
    seen, todo, found = set(), [ENTRY], []
    while todo:
        name = todo.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        text, is_package = modules[name]
        tree = ast.parse(text)
        package = name if is_package else name.rpartition(".")[0]
        loaded = loaded_names(tree, package, HELPER_ENTRIES.get(name))
        found += [(name, m) for m in sorted(loaded) if m.split(".")[0] in HELPER_ONLY]
        if name not in HELPER_ENTRIES:
            found += [(name, f"the helper entry {call}()") for _, call in entry_calls(name, tree)]
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
    ("a module the server loads on demand, inside a function", 1,
     {"server.py": "def abre():\n    import microfone.injeta\n", "microfone/__init__.py": "",
      "microfone/injeta.py": "import requests\n"}),
    ("an import in a class body", 1, {"server.py": "class A:\n    import requests\n"}),
    ("an import in a loop at load time", 1, {"server.py": "for _ in range(1):\n    import yt_dlp\n"}),
    ("an import only for type checking", 0,
     {"server.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import requests\n"}),
    ("the helper's own entry imports the YouTube helper", 0,
     {"server.py": "import andamento\n", "andamento.py": "def main():\n    from yt_fora import stream_yt\n"}),
    ("the server calls the helper's entry in its own process", 1,
     {"server.py": "import andamento as an\nan.main()\n", "andamento.py": "def main():\n    pass\n"}),
    ("a module the server never loads", 0, {"server.py": "import os\n", "yt_tool.py": "import yt_dlp\n"}),
]


def repo_files():
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py")
            if not {"dev", ".git", ".venv", "venv", "build", "dist"} & set(p.relative_to(ROOT).parts)}


def main():
    failed = False
    for label, expected, files in CASES:
        got = len(heavy_in_process(files))
        ok = got == expected
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label}: {got} (expected {expected})")
    found = heavy_in_process(repo_files())
    for module, name in found:
        print(f"FAIL  {module} loads {name} in the audio process: a slow library runs in a helper process "
              f"(ritmelli.py --yt, ritmelli.py --andamento)")
    if not found:
        print(f"ok    the server's process loads none of {', '.join(sorted(HELPER_ONLY))}")
    return 1 if failed or found else 0


if __name__ == "__main__":
    sys.exit(main())
