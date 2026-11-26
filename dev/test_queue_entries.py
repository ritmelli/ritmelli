import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = ("server.py", "App")
CONTAINERS = {"fila", "fila_ordem", "mix"}
QUEUE = {"fila", "fila_ordem"}
ENTRY_ATTRS = {"x", "entrada"}
MUTATORS = {"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"}
FILLERS = {"append", "insert", "extend"}
CHANGERS = {"append", "insert", "extend", "remove", "pop", "clear", "sort", "reverse"}

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


def called(node):
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return node.func.id if isinstance(node.func, ast.Name) else None


class Scope:
    def __init__(self):
        self.containers, self.entries = set(), set()


class Entries:
    def __init__(self, modules):
        self.modules = modules
        self.params = {}

    def functions(self):
        out = []

        def walk(name, node, cls):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(name, child, child.name)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((name, child, cls))
                    walk(name, child, cls)
                else:
                    walk(name, child, cls)
        for name, tree in self.modules:
            walk(name, tree, None)
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
            inner.entries |= self.loop_entries(gen.iter, gen.target, inner)
        return inner

    def loop_entries(self, it, target, scope):
        if self.is_container(it, scope):
            return set(targets(target))
        if (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "enumerate" and it.args
                and self.is_container(it.args[0], scope) and isinstance(target, ast.Tuple) and len(target.elts) == 2):
            return set(targets(target.elts[1]))
        return set()

    def is_entry(self, node, scope):
        if isinstance(node, ast.Name):
            return node.id in scope.entries
        if isinstance(node, ast.Attribute):
            return node.attr in ENTRY_ATTRS
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            return self.is_container(node.value, scope)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "next" and node.args:
                return self.is_container(node.args[0], scope)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "pop":
                return self.is_container(node.func.value, scope)
        if isinstance(node, (ast.BoolOp, ast.IfExp)):
            parts = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
            return any(self.is_entry(p, scope) for p in parts)
        return False

    @staticmethod
    def param_names(func):
        return [a.arg for a in func.args.posonlyargs + func.args.args + func.args.kwonlyargs]

    def scope_of(self, func):
        scope = Scope()
        scope.entries |= self.params.get(func.name, set())
        for _ in range(4):
            for node in ast.walk(func):
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        if isinstance(t, ast.Attribute) and t.attr in CONTAINERS:
                            scope.containers |= set(targets(node.value))
                        elif self.is_container(node.value, scope):
                            scope.containers |= set(targets(t))
                        elif self.is_entry(node.value, scope):
                            scope.entries |= set(targets(t))
                elif isinstance(node, (ast.For, ast.comprehension)):
                    scope.entries |= self.loop_entries(node.iter, node.target, scope)
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in FILLERS and self.is_container(node.func.value, scope)):
                    for a in node.args:
                        scope.entries |= set(targets(a)) if isinstance(a, ast.Name) else set()
        return scope

    def bind_params(self, funcs):
        changed = True
        while changed:
            changed = False
            for _, func, _ in funcs:
                scope = self.scope_of(func)
                for node in ast.walk(func):
                    if not isinstance(node, ast.Call):
                        continue
                    name = called(node)
                    for _, target, _ in [f for f in funcs if f[1].name == name]:
                        names = self.param_names(target)
                        shift = 1 if isinstance(node.func, ast.Attribute) and names[:1] == ["self"] else 0
                        bound = [names[i + shift] for i, a in enumerate(node.args)
                                 if i + shift < len(names) and self.is_entry(a, scope)]
                        bound += [kw.arg for kw in node.keywords if kw.arg in names and self.is_entry(kw.value, scope)]
                        new = set(bound) - self.params.setdefault(name, set())
                        if new:
                            self.params[name] |= new
                            changed = True

    def write_target(self, node, scope):
        return isinstance(node, ast.Subscript) and self.is_entry(node.value, scope)

    def writes(self):
        funcs = self.functions()
        self.bind_params(funcs)
        out = []
        for module, func, cls in funcs:
            if (module, cls) == OWNER:
                continue
            scope = self.scope_of(func)
            for node in ast.walk(func):
                hit = None
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                    ts = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                    if any(self.write_target(t, scope) for t in ts):
                        hit = "del" if isinstance(node, ast.Delete) else "assignment"
                    elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr) and \
                            self.is_entry(node.target, scope):
                        hit = "|="
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in MUTATORS and self.is_entry(node.func.value, scope)):
                    hit = f".{node.func.attr}()"
                if hit:
                    out.append(f"{module}:{node.lineno}: {hit} on an entry of the queue or the Mix, in {func.name}")
        return out


APP_NAMES = {"A", "app"}


class QueueChanges(ast.NodeVisitor):
    def __init__(self, module):
        self.module, self.cls, self.stack, self.found = module, None, [], []

    def visit_ClassDef(self, node):
        outer, self.cls = self.cls, node.name
        self.generic_visit(node)
        self.cls = outer

    def through_change_queue(self, func):
        passed = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and called(node) == "change_queue":
                passed |= {a.id for a in node.args if isinstance(a, ast.Name)}
                passed |= {id(a) for a in node.args if isinstance(a, ast.Lambda)}
        return passed

    def visit_FunctionDef(self, node):
        parent = self.stack[-1] if self.stack else None
        allowed = ((self.module, self.cls, node.name) == (OWNER[0], OWNER[1], "__init__")
                   or (parent is not None and node.name in parent[1]))
        self.stack.append((allowed, self.through_change_queue(node)))
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        parent = self.stack[-1] if self.stack else None
        self.stack.append((parent is not None and id(node) in parent[1], set()))
        self.generic_visit(node)
        self.stack.pop()

    def queue_attr(self, node):
        if not (isinstance(node, ast.Attribute) and node.attr in QUEUE):
            return False
        v = node.value
        in_app = (self.module, self.cls) == OWNER
        return ((isinstance(v, ast.Name) and (v.id in APP_NAMES or (v.id == "self" and in_app)))
                or (isinstance(v, ast.Attribute) and v.attr == "app"))

    def queue_target(self, node):
        return self.queue_attr(node) or (isinstance(node, ast.Subscript) and self.queue_attr(node.value))

    def flag(self, node, what):
        if not (self.stack and self.stack[-1][0]):
            self.found.append(f"{self.module}:{node.lineno}: {what} outside a change_queue")

    def visit_Assign(self, node):
        if any(self.queue_target(t) for t in node.targets):
            self.flag(node, "assignment to the queue")
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if self.queue_target(node.target):
            self.flag(node, "assignment to the queue")
        self.generic_visit(node)

    visit_AnnAssign = visit_AugAssign

    def visit_Delete(self, node):
        if any(isinstance(t, ast.Subscript) and self.queue_attr(t.value) for t in node.targets):
            self.flag(node, "del on the queue")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in CHANGERS and self.queue_attr(node.func.value):
            self.flag(node, f".{node.func.attr}() on the queue")
        self.generic_visit(node)


def scan(sources):
    modules = [(name, ast.parse(text, name)) for name, text in sources.items()]
    entry_writes = Entries(modules).writes()
    changes = []
    for name, tree in modules:
        v = QueueChanges(name)
        v.visit(tree)
        changes += v.found
    return entry_writes, changes


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

ENTRY_FORMS = {
    "the head of the queue by index": ({"case.py": "def f(A):\n    A.fila[0]['fixa'] = True\n"}, 1),
    "an entry found by next()": ({"case.py": "def f(A, q):\n    x = next((y for y in A.fila if y['qid'] == q), None)"
                                             "\n    x['fixa'] = True\n"}, 1),
    "an entry of a copy of the Mix": ({"case.py": "def f(A):\n    for m in sorted(A.mix):\n"
                                                  "        m.setdefault('ordem', 0)\n"}, 1),
    "del on an entry of the order the user built": ({"case.py": "def f(A):\n    for x in A.fila_ordem:\n"
                                                                "        del x['fixa']\n"}, 1),
    "an annotated alias": ({"case.py": "def f(A):\n    x: dict = A.fila[0]\n    x['audio'] = True\n"}, 1),
    "a |= on an entry": ({"case.py": "def f(A):\n    for x in A.fila:\n        x |= {'audio': True}\n"}, 1),
    "an entry from enumerate()": ({"case.py": "def f(A):\n    for i, x in enumerate(A.fila):\n"
                                              "        x['fixa'] = True\n"}, 1),
    "an entry popped from the queue": ({"case.py": "def f(A):\n    x = A.fila.pop(0)\n    x['fixa'] = True\n"}, 1),
    "the entry of a reservation": ({"case.py": "def f(A):\n    A.reserva.x.update(audio=True)\n"}, 1),
    "an entry passed by keyword to a helper": ({"case.py": "def g(x=None):\n    x['audio'] = True\n"
                                                           "def f(A):\n    g(x=A.fila[0])\n"}, 1),
    "an entry passed to a function of another module": ({"comandos.py": "def marca(x):\n    x['audio'] = True\n",
                                                         "case.py": "def f(A):\n    cmd.marca(A.fila[0])\n"}, 1),
    "a new dict from an entry": ({"case.py": "def f(A):\n    for m in A.mix:\n        m = dict(m, ordem=1)\n"}, 0),
    "a dict that is no entry": ({"case.py": "def f(A):\n    d = {}\n    d['k'] = 1\n    d.update(a=1)\n"}, 0),
    "the App writing its own entries": ({"server.py": "class App:\n    def f(self):\n        for x in self.fila:\n"
                                                      "            x['fixa'] = True\n"}, 0),
}

QUEUE_FORMS = {
    "an append to the queue outside the App": ({"case.py": "def f(A, x):\n    A.fila.append(x)\n"}, 1),
    "an App method that removes from the queue by itself": (
        {"server.py": "class App:\n    def f(self, x):\n        self.fila.remove(x)\n"}, 1),
    "a slice assignment to the queue": ({"case.py": "def f(A, nova):\n    A.fila[1:] = nova\n"}, 1),
    "a new order the user built, outside a change_queue": ({"case.py": "def f(A):\n    A.fila_ordem = None\n"}, 1),
    "the change in a closure passed to change_queue": (
        {"server.py": "class App:\n    def f(self, x):\n        def remove_entry():\n            self.fila.remove(x)\n"
                      "        self.change_queue(remove_entry)\n"}, 0),
    "the change in a lambda passed to change_queue": (
        {"case.py": "def f(A, x):\n    A.change_queue(lambda: A.fila.append(x))\n"}, 0),
    "another class's own fila": ({"fx.py": "class Fx:\n    def f(self):\n        self.fila = []\n"}, 0),
    "the App building its queue in __init__": (
        {"server.py": "class App:\n    def __init__(self):\n        self.fila = []\n"}, 0),
}


def production_sources():
    paths = sorted(ROOT.glob("*.py")) + sorted((ROOT / "microfone").glob("*.py"))
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in paths}


def main():
    found, _ = scan({"automatico.py": BASE_USES})
    lines = sorted(int(w.split(":")[1]) for w in found)
    check(lines == [9, 15, 17], f"the check flags the three writes the base made outside the App (the Mix numbering, "
                                f"the audio mark and the update of _poe_versao): {found}")
    for what, (sources, expected) in ENTRY_FORMS.items():
        got, _ = scan(sources)
        check(len(got) == expected, f"the entry check {'flags' if expected else 'accepts'} {what} ({got})")
    for what, (sources, expected) in QUEUE_FORMS.items():
        _, got = scan(sources)
        check(len(got) == expected, f"the queue check {'flags' if expected else 'accepts'} {what} ({got})")
    sources = production_sources()
    writes, changes = scan(sources)
    check(not writes, f"no module writes an entry of the queue or the Mix outside the {OWNER[1]} ({writes})")
    check(not changes, f"every change to the queue in the {len(sources)} modules goes through change_queue "
                       f"({changes})")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
