import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = ("server.py", "App")
CONTAINERS = {"fila", "fila_ordem", "mix"}
MUTATORS = {"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"}
FILLERS = {"append", "insert", "extend"}

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def targets(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            yield from targets(e)
    elif isinstance(node, ast.Name):
        yield node.id


class Scope:
    def __init__(self):
        self.containers, self.entries = set(), set()


class Entries:
    def __init__(self, tree, skip_class=None):
        self.tree, self.skip_class = tree, skip_class
        self.params = {}
        self.writes = []

    def functions(self):
        out = []

        def walk(node, cls):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(child, child.name)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((child, cls))
                    walk(child, cls)
                else:
                    walk(child, cls)
        walk(self.tree, None)
        return out

    def is_container(self, node, scope):
        if isinstance(node, ast.Attribute) and node.attr in CONTAINERS:
            return True
        if isinstance(node, ast.Name):
            return node.id in scope.containers
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            return self.is_container(node.value, scope)
        if isinstance(node, ast.BinOp):
            return self.is_container(node.left, scope) or self.is_container(node.right, scope)
        if isinstance(node, ast.BoolOp):
            return any(self.is_container(v, scope) for v in node.values)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("list", "sorted",
                                                                                              "reversed", "tuple"):
            return bool(node.args) and self.is_container(node.args[0], scope)
        if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
            return self.is_entry(node.elt, self.comp_scope(node, scope))
        return False

    def comp_scope(self, node, scope):
        inner = Scope()
        inner.containers, inner.entries = set(scope.containers), set(scope.entries)
        for gen in node.generators:
            if self.is_container(gen.iter, inner):
                inner.entries |= set(targets(gen.target))
        return inner

    def is_entry(self, node, scope):
        if isinstance(node, ast.Name):
            return node.id in scope.entries
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            return self.is_container(node.value, scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "next" and node.args:
            return self.is_container(node.args[0], scope)
        if isinstance(node, (ast.BoolOp, ast.IfExp)):
            parts = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
            return any(self.is_entry(p, scope) for p in parts)
        return False

    def scope_of(self, func):
        scope = Scope()
        params = [a.arg for a in func.args.posonlyargs + func.args.args]
        scope.entries |= {params[i] for i in self.params.get(func.name, set()) if i < len(params)}
        for _ in range(4):
            for node in ast.walk(func):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Attribute) and t.attr in CONTAINERS:
                            scope.containers |= set(targets(node.value))
                        elif self.is_container(node.value, scope):
                            scope.containers |= set(targets(t))
                        elif self.is_entry(node.value, scope):
                            scope.entries |= set(targets(t))
                elif isinstance(node, (ast.For, ast.comprehension)) and self.is_container(node.iter, scope):
                    scope.entries |= set(targets(node.target))
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in FILLERS and self.is_container(node.func.value, scope)):
                    for a in node.args:
                        scope.entries |= set(targets(a)) if isinstance(a, ast.Name) else set()
        return scope

    def bind_params(self, funcs):
        changed = True
        while changed:
            changed = False
            for func, _ in funcs:
                scope = self.scope_of(func)
                for node in ast.walk(func):
                    if not isinstance(node, ast.Call):
                        continue
                    name = (node.func.attr if isinstance(node.func, ast.Attribute)
                            else node.func.id if isinstance(node.func, ast.Name) else None)
                    target = next((f for f, _ in funcs if f.name == name), None)
                    if target is None:
                        continue
                    shift = 1 if isinstance(node.func, ast.Attribute) and target.args.args[:1] and \
                        target.args.args[0].arg == "self" else 0
                    for i, a in enumerate(node.args):
                        if self.is_entry(a, scope) and i + shift not in self.params.setdefault(name, set()):
                            self.params[name].add(i + shift)
                            changed = True

    def write_target(self, node, scope):
        return isinstance(node, ast.Subscript) and self.is_entry(node.value, scope)

    def run(self, name):
        funcs = self.functions()
        self.bind_params(funcs)
        for func, cls in funcs:
            if cls is not None and cls == self.skip_class:
                continue
            scope = self.scope_of(func)
            for node in ast.walk(func):
                hit = None
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                    ts = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                    if any(self.write_target(t, scope) for t in ts):
                        hit = "del" if isinstance(node, ast.Delete) else "assignment"
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in MUTATORS and self.is_entry(node.func.value, scope)):
                    hit = f".{node.func.attr}()"
                if hit:
                    self.writes.append(f"{name}:{node.lineno}: {hit} on an entry of the queue or the Mix, in "
                                       f"{func.name}")
        return self.writes


def scan(name, text):
    skip = OWNER[1] if name == OWNER[0] else None
    return Entries(ast.parse(text, name), skip).run(name)


BASE_USES = '''
class Automatico:
    def _busca_mix(self, base):
        A = self.app
        lista = self.mix_do(base)
        with A.fila_lock:
            for m in lista:
                A.mix_seq += 1
                m["ordem"] = A.mix_seq
                if m["youtube_id"] in A.versoes:
                    self._poe_versao(m, A.versoes[m["youtube_id"]])
            A.mix = lista

    def _poe_versao(self, x, v):
        x["audio"] = True
        if v:
            x.update(v, video=x.get("video") or x["youtube_id"], thumb=music.thumb(v["youtube_id"]), tipo="ATV")

    def _troca_audio(self, vid, v):
        A = self.app
        presa = A.fila[0] if A.fila and self._presa() else None
        for x in list(A.mix or []) + [y for y in A.fila if y.get("auto") and y is not presa]:
            if x.get("youtube_id") == vid and not x.get("audio"):
                self._poe_versao(x, v)
'''

FORMS = {
    "the head of the queue by index": ("def f(A):\n    A.fila[0]['fixa'] = True\n", 1),
    "an entry found by next()": ("def f(A, q):\n    x = next((y for y in A.fila if y['qid'] == q), None)\n"
                                 "    x['fixa'] = True\n", 1),
    "an entry of a copy of the Mix": ("def f(A):\n    for m in sorted(A.mix):\n        m.setdefault('ordem', 0)\n", 1),
    "del on an entry of the order the user built": ("def f(A):\n    for x in A.fila_ordem:\n        del x['fixa']\n",
                                                    1),
    "a new dict from an entry": ("def f(A):\n    for m in A.mix:\n        m = dict(m, ordem=1)\n", 0),
    "a dict that is no entry": ("def f(A):\n    d = {}\n    d['k'] = 1\n    d.update(a=1)\n", 0),
    "the App writing its own entries": ("class App:\n    def f(self):\n        for x in self.fila:\n"
                                        "            x['fixa'] = True\n", 0),
}


def main():
    found = scan("automatico.py", BASE_USES)
    lines = sorted(int(w.split(":")[1]) for w in found)
    check(lines == [9, 15, 17], f"the check flags the three writes the base made outside the App (the Mix numbering, "
                                f"the audio mark and the update of _poe_versao): {found}")
    for what, (code, expected) in FORMS.items():
        name = OWNER[0] if code.startswith("class App") else "case.py"
        got = scan(name, code)
        check(len(got) == expected, f"the check {'flags' if expected else 'accepts'} {what} ({got})")
    writes = []
    for path in sorted(ROOT.glob("*.py")):
        writes += scan(path.name, path.read_text(encoding="utf-8"))
    check(not writes, f"no module writes an entry of the queue or the Mix outside the {OWNER[1]} ({writes})")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
