import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = ("server.py", "App")
CONTAINERS = {"fila", "fila_ordem", "mix", "_mix"}
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


def target_nodes(node):
    if isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            yield from target_nodes(e)
    elif isinstance(node, ast.Starred):
        yield from target_nodes(node.value)
    else:
        yield node


def passed_to_change_queue(func):
    names, lambdas = set(), set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and called(node) == "change_queue":
            values = list(node.args) + [kw.value for kw in node.keywords if kw.arg == "change"]
            names |= {a.id for a in values if isinstance(a, ast.Name)}
            lambdas |= {id(a) for a in values if isinstance(a, ast.Lambda)}
    return names, lambdas


def callback_escapes(modules):
    out = []
    for module, tree in modules:
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nested = {n.name for n in ast.walk(func) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n is not func}
            names, _ = passed_to_change_queue(func)
            passed = {id(a) for n in ast.walk(func) if isinstance(n, ast.Call) and called(n) == "change_queue"
                      for a in list(n.args) + [kw.value for kw in n.keywords if kw.arg == "change"]}
            out += [f"{module}:{n.lineno}: {n.id}, passed to change_queue, used outside it in {func.name}"
                    for n in ast.walk(func) if isinstance(n, ast.Name) and n.id in names & nested
                    and id(n) not in passed]
    return out


def own_nodes(func, skip=frozenset()):
    todo = list(ast.iter_child_nodes(func))
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or id(node) in skip:
            continue
        yield node
        todo.extend(ast.iter_child_nodes(node))


class Entries:
    def __init__(self, modules, attrs=CONTAINERS, owner_only=False):
        self.modules, self.attrs, self.owner_only = modules, attrs, owner_only
        self.params, self.cparams, self.walks, self.scopes, self.returns = {}, {}, {}, {}, set()

    def walk(self, func):
        if id(func) not in self.walks:
            self.walks[id(func)] = list(ast.walk(func))
        return self.walks[id(func)]

    def functions(self):
        out = []

        def walk(name, node, cls, parent):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(name, child, child.name, None)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((name, child, cls, parent))
                    walk(name, child, cls, child)
                else:
                    walk(name, child, cls, parent)
        for name, tree in self.modules:
            walk(name, tree, None, None)
        return out

    def is_container(self, node, scope):
        if isinstance(node, ast.Attribute) and node.attr in self.attrs:
            return True
        if isinstance(node, ast.Name):
            return node.id in scope.containers
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            return self.is_container(node.value, scope)
        if isinstance(node, ast.BinOp):
            return self.is_container(node.left, scope) or self.is_container(node.right, scope)
        if isinstance(node, ast.BoolOp):
            return any(self.is_container(v, scope) for v in node.values)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "copy"
                and not node.args):
            return self.is_container(node.func.value, scope)
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
            return node.attr in ENTRY_ATTRS and not self.owner_only
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            return self.is_container(node.value, scope)
        if isinstance(node, ast.Call):
            if called(node) in self.returns:
                return True
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

    def scope_of(self, func, parent=None, parents=None):
        if id(func) not in self.scopes:
            self.scopes[id(func)] = self.compute_scope(func, parent, parents)
        return self.scopes[id(func)]

    def compute_scope(self, func, parent, parents):
        scope = Scope()
        if parent is not None:
            outer = self.scope_of(parent, (parents or {}).get(id(parent)), parents)
            own = set(self.param_names(func)) | {n.id for n in own_nodes(func)
                                                 if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            scope.containers, scope.entries = set(outer.containers) - own, set(outer.entries) - own
        scope.entries |= self.params.get(func.name, set())
        scope.containers |= self.cparams.get(func.name, set())
        for _ in range(4):
            for node in self.walk(func):
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    for root in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        pairs = list(zip(root.elts, node.value.elts)) if (
                            isinstance(root, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List))
                            and len(root.elts) == len(node.value.elts)) else [(root, node.value)]
                        for t, value in pairs:
                            if isinstance(t, ast.Attribute) and t.attr in self.attrs:
                                scope.containers |= set(targets(value))
                            elif self.is_container(value, scope):
                                scope.containers |= set(targets(t))
                            elif self.is_entry(value, scope):
                                scope.entries |= set(targets(t))
                elif isinstance(node, (ast.For, ast.comprehension)):
                    scope.entries |= self.loop_entries(node.iter, node.target, scope)
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in FILLERS and self.is_container(node.func.value, scope)):
                    for a in node.args:
                        scope.entries |= set(targets(a)) if isinstance(a, ast.Name) else set()
        return scope

    def bind_params(self, funcs, parents):
        by_name = {}
        for f in funcs:
            by_name.setdefault(f[1].name, []).append(f[1])
        calls = {id(f): [n for n in self.walk(f) if isinstance(n, ast.Call) and called(n) in by_name]
                 for _, f, _, _ in funcs}
        changed = True
        while changed:
            changed = False
            self.scopes.clear()
            for _, func, _, parent in funcs:
                if not calls[id(func)]:
                    continue
                scope = self.scope_of(func, parent, parents)
                for node in calls[id(func)]:
                    name = called(node)
                    for target in by_name[name]:
                        names = self.param_names(target)
                        shift = 1 if isinstance(node.func, ast.Attribute) and names[:1] == ["self"] else 0
                        args = [(names[i + shift], a) for i, a in enumerate(node.args) if i + shift < len(names)]
                        args += [(kw.arg, kw.value) for kw in node.keywords if kw.arg in names]
                        for into, test in ((self.params, self.is_entry), (self.cparams, self.is_container)):
                            new = {n for n, a in args if test(a, scope)} - into.setdefault(name, set())
                            if new:
                                into[name] |= new
                                changed = True

    def write_target(self, node, scope):
        return isinstance(node, ast.Subscript) and self.is_entry(node.value, scope)

    def writes(self):
        funcs = self.functions()
        parents = {id(f): p for _, f, _, p in funcs}
        self.bind_params(funcs, parents)
        changed = True
        while changed:
            changed = False
            for _, func, _, parent in funcs:
                if func.name in self.returns:
                    continue
                scope = self.scope_of(func, parent, parents)
                if any(isinstance(n, ast.Return) and n.value is not None and self.is_entry(n.value, scope)
                       for n in own_nodes(func)):
                    self.returns.add(func.name)
                    self.scopes.clear()
                    changed = True
        allowed, skip = set(), set()
        for _, func, _, _ in funcs:
            names, lambdas = passed_to_change_queue(func)
            skip |= lambdas
            allowed |= {id(n) for n in ast.walk(func) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n is not func and n.name in names}
        out = []
        for module, func, cls, parent in funcs:
            if ((module, cls) == OWNER) != self.owner_only:
                continue
            if self.owner_only and (id(func) in allowed or func.name == "__init__"):
                continue
            scope = self.scope_of(func, parent, parents)
            for node in own_nodes(func, skip if self.owner_only else frozenset()):
                hit = None
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                    roots = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                    ts = [u for root in roots for u in target_nodes(root)]
                    if any(self.write_target(t, scope) for t in ts):
                        hit = "del" if isinstance(node, ast.Delete) else "assignment"
                    elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr) and \
                            self.is_entry(node.target, scope):
                        hit = "|="
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in MUTATORS and self.is_entry(node.func.value, scope)):
                    hit = f".{node.func.attr}()"
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and isinstance(node.func.value, ast.Name) and node.func.value.id == "dict"
                      and node.func.attr in MUTATORS and node.args and self.is_entry(node.args[0], scope)):
                    hit = f"dict.{node.func.attr}()"
                if hit:
                    where = "in the App outside a change_queue" if self.owner_only else "outside the App"
                    out.append(f"{module}:{node.lineno}: {hit} on an entry of the queue or the Mix {where}, in "
                               f"{func.name}")
        return out


APP_NAMES = {"A", "app"}


def queue_attr(node, module, cls):
    if not (isinstance(node, ast.Attribute) and node.attr in QUEUE):
        return False
    v = node.value
    return ((isinstance(v, ast.Name) and (v.id in APP_NAMES or (v.id == "self" and (module, cls) == OWNER)))
            or (isinstance(v, ast.Attribute) and v.attr == "app"))


def direct_aliases(func, module, cls, known):
    out, before = set(known), -1
    assigns = [n for n in ast.walk(func) if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None]
    while len(out) != before:
        before = len(out)
        for node in assigns:
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                pairs = list(zip(t.elts, node.value.elts)) if (
                    isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple)) else [(t, node.value)]
                for target, value in pairs:
                    if isinstance(target, ast.Name) and (
                            queue_attr(value, module, cls) or (isinstance(value, ast.Name) and value.id in out)):
                        out.add(target.id)
    return out


class QueueChanges(ast.NodeVisitor):
    def __init__(self, module, params):
        self.module, self.params, self.cls, self.stack, self.found, self.passing = module, params, None, [], [], []

    def visit_ClassDef(self, node):
        outer, self.cls = self.cls, node.name
        self.generic_visit(node)
        self.cls = outer

    def visit_FunctionDef(self, node):
        parent = self.stack[-1] if self.stack else None
        allowed = ((self.module, self.cls, node.name) == (OWNER[0], OWNER[1], "__init__")
                   or (parent is not None and node.name in parent[1][0]))
        own = {n for n in Entries.param_names(node) if n in self.params.get(node.name, set())}
        aliases = direct_aliases(node, self.module, self.cls, (parent[2] if parent else set()) | own)
        self.stack.append((allowed, passed_to_change_queue(node), aliases))
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        parent = self.stack[-1] if self.stack else None
        allowed = parent is not None and id(node) in parent[1][1]
        self.stack.append((allowed, (set(), set()), parent[2] if parent else set()))
        self.generic_visit(node)
        self.stack.pop()

    def queue_ref(self, node):
        return queue_attr(node, self.module, self.cls) or (
            isinstance(node, ast.Name) and bool(self.stack) and node.id in self.stack[-1][2])

    def flag(self, node, what):
        if not (self.stack and self.stack[-1][0]):
            self.found.append(f"{self.module}:{node.lineno}: {what} outside a change_queue")

    def visit_Assign(self, node):
        ts = [u for root in node.targets for u in target_nodes(root)]
        if any(queue_attr(t, self.module, self.cls) or (isinstance(t, ast.Subscript) and self.queue_ref(t.value))
               for t in ts):
            self.flag(node, "assignment to the queue")
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        t = node.target
        if self.queue_ref(t) or (isinstance(t, ast.Subscript) and self.queue_ref(t.value)):
            self.flag(node, "assignment to the queue")
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        t = node.target
        if queue_attr(t, self.module, self.cls) or (isinstance(t, ast.Subscript) and self.queue_ref(t.value)):
            self.flag(node, "assignment to the queue")
        self.generic_visit(node)

    def visit_Delete(self, node):
        if any(isinstance(t, ast.Subscript) and self.queue_ref(t.value)
               for root in node.targets for t in target_nodes(root)):
            self.flag(node, "del on the queue")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in CHANGERS and self.queue_ref(node.func.value):
            self.flag(node, f".{node.func.attr}() on the queue")
        name = called(node)
        slots = list(enumerate(node.args)) + [(kw.arg, kw.value) for kw in node.keywords]
        self.passing += [(name, slot, isinstance(node.func, ast.Attribute)) for slot, a in slots if self.queue_ref(a)]
        self.generic_visit(node)


def queue_params(modules, passing):
    funcs = [f for _, tree in modules for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    out = {}
    for name, slot, method in passing:
        for f in [f for f in funcs if f.name == name]:
            names = Entries.param_names(f)
            shift = 1 if method and names[:1] == ["self"] else 0
            if isinstance(slot, str) and slot in names:
                out.setdefault(name, set()).add(slot)
            elif isinstance(slot, int) and slot + shift < len(names):
                out.setdefault(name, set()).add(names[slot + shift])
    return out


def scan(sources):
    modules = [(name, ast.parse(text, name)) for name, text in sources.items()]
    entry_writes = Entries(modules).writes() + Entries(modules, attrs=QUEUE, owner_only=True).writes()
    params, changes = {}, []
    for _ in range(3):
        passing, changes = [], []
        for name, tree in modules:
            v = QueueChanges(name, params)
            v.visit(tree)
            changes += v.found
            passing += v.passing
        params = queue_params(modules, passing)
    return entry_writes, changes + callback_escapes(modules)


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
    "a tuple assignment to an entry": ({"case.py": "def f(A):\n    A.fila[0]['audio'], y = True, 1\n"}, 1),
    "the Automatico writing an entry of its own Mix in place": (
        {"automatico.py": "class Automatico:\n    def f(self):\n        for m in self._mix:\n            m['ordem'] = 1\n"}, 1),
    "an entry a helper returns": ({"case.py": "def head(A):\n    return A.fila[0]\n"
                                              "def f(A):\n    head(A).update(a=1)\n"}, 1),
    "a copy a helper returns": ({"case.py": "def head(A):\n    return dict(A.fila[0])\n"
                                            "def f(A):\n    head(A).update(a=1)\n"}, 0),
    "a name a nested function binds for itself": ({"case.py": "def f(A):\n    x = A.fila[0]\n    def g(x):\n"
                                                              "        x['k'] = 1\n    g({})\n"}, 0),
    "dict.update called on an entry of the Mix": ({"case.py": "def f(A):\n    dict.update(A.mix[0], audio=True)\n"}, 1),
    "an entry of a shallow copy of the queue": ({"case.py": "def f(A):\n    for x in A.fila.copy():\n"
                                                            "        x['fixa'] = True\n"}, 1),
    "a new dict made from an entry, then changed": ({"case.py": "def f(A):\n    y = dict(A.fila[0])\n"
                                                                "    y['fixa'] = True\n"}, 0),
    "an entry of the Mix from unpacking": ({"case.py": "def f(A):\n    x, _ = A.mix[0], None\n    x.update(a=1)\n"}, 1),
    "a new dict from an entry":({"case.py": "def f(A):\n    for m in A.mix:\n        m = dict(m, ordem=1)\n"}, 0),
    "a dict that is no entry": ({"case.py": "def f(A):\n    d = {}\n    d['k'] = 1\n    d.update(a=1)\n"}, 0),
    "a helper that writes the entries of the Mix it gets": (
        {"case.py": "def rewrite(items):\n    for m in items:\n        m['k'] = 1\n"
                    "def f(A):\n    rewrite(A.mix)\n"}, 1),
    "the App writing its queue entries outside a change_queue": (
        {"server.py": "class App:\n    def f(self):\n        for x in self.fila:\n            x['fixa'] = True\n"}, 1),
    "the App writing its queue entries in a closure passed to change_queue": (
        {"server.py": "class App:\n    def f(self, q):\n        x = next(e for e in self.fila if e['qid'] == q)\n"
                      "        def move():\n            x['fixa'] = True\n        self.change_queue(move)\n"}, 0),
    "the App writing the Mix entries": (
        {"server.py": "class App:\n    def f(self):\n        for m in self.mix:\n            m['audio'] = True\n"}, 0),
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
    "an alias of the queue that clears it": ({"case.py": "def f(A):\n    pool = A.fila\n    pool.clear()\n"}, 1),
    "an alias from unpacking that appends": (
        {"server.py": "class App:\n    def f(self, x):\n        f, o = self.fila, self.fila_ordem\n"
                      "        f.append(x)\n"}, 1),
    "a helper that clears the queue it gets": ({"case.py": "def cut(q):\n    q.clear()\ndef f(A):\n    cut(A.fila)\n"},
                                               1),
    "a copy of the queue that changes": ({"case.py": "def f(A, x):\n    pool = list(A.fila)\n    pool.append(x)\n"},
                                         0),
    "the change passed by keyword to change_queue": (
        {"case.py": "def f(A, x):\n    def ch():\n        A.fila.append(x)\n    A.change_queue(change=ch)\n"}, 0),
    "a tuple assignment to the queue": (
        {"server.py": "class App:\n    def f(self):\n        self.fila, self.fila_ordem = [], None\n"}, 1),
    "an alias made inside a block and passed on": (
        {"case.py": "def f(A, c):\n    if c:\n        q = A.fila\n    p = q\n    p.clear()\n"}, 1),
    "a change_queue callback also called by itself": (
        {"server.py": "class App:\n    def f(self, x):\n        def remove_entry():\n            self.fila.remove(x)\n"
                      "        remove_entry()\n        self.change_queue(remove_entry)\n"}, 1),
    "a change_queue callback handed to another function": (
        {"server.py": "class App:\n    def f(self, x):\n        def remove_entry():\n            self.fila.remove(x)\n"
                      "        later(remove_entry)\n        self.change_queue(remove_entry)\n"}, 1),
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
    direct = sources["server.py"].replace("self.change_queue(swap_entries)", "swap_entries()")
    got, _ = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and len(got) == 1,
          f"with the App's audio version writing the entries without change_queue, the check fails ({got})")
    direct = sources["server.py"].replace("self.change_queue(swap_entries)",
                                          "swap_entries()\n        self.change_queue(swap_entries)")
    _, got = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and len(got) == 1,
          f"with the App's audio version also calling its change_queue callback by itself, the check fails ({got})")
    direct = sources["server.py"].replace("self.change_queue(replace_queue)", "replace_queue()")
    _, got = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and len(got) == 1,
          f"with the App replacing its queue without change_queue, the check fails ({got})")
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
