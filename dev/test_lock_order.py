import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "dev" / "tla" / "Locks.tla"
MODULES = ("comandos.py", "server.py", "automatico.py", "engine.py")
ATTRS = {"fila_lock": "fila_lock", "_lock": "_lock", "_qlock": "_qlock", "proximo_lock": "proximo_lock"}
AUDIO = ("Engine", "_mixa")
APP_NAMES = {"A", "app"}
ENGINE_NAMES = {"e", "E", "engine"}
SUBCLASSES = {"MockEngine": "Engine"}
QUEUE_HELD = ["fila_lock", "_qlock"]
PARAM_LOCKS = {("Engine", "outer"): "fila_lock"}
CALLBACKS = {
    ("engine.py", "Engine", "with_lock"): {1: ["fila_lock", "_lock"], "f": ["fila_lock", "_lock"]},
    ("server.py", "App", "change_queue"): {0: QUEUE_HELD, "change": QUEUE_HELD},
    ("server.py", "App", "with_engine"): {0: ["fila_lock", "_lock"], "f": ["fila_lock", "_lock"]},
    ("server.py", "App", "close_switches"): {0: QUEUE_HELD, "read": QUEUE_HELD},
    ("comandos.py", None, "concilia"): {1: QUEUE_HELD, "under": QUEUE_HELD, 2: ["fila_lock"], "closed": ["fila_lock"]},
}
CALLER_HOLDS = {("server.py", "App", "change_queue"): {"fila_lock"}, ("server.py", "App", "close_switches"): {"fila_lock"},
                ("comandos.py", None, "concilia"): {"fila_lock"}}
ENGINE_GUARD = ["_lock", "_qlock"]
WRITERS = {"save_json", "_save", "write_text", "write_bytes"}
WRITES = "a file write"
NO_WRITES = {"fila_lock", "_lock", "_qlock"}

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def declared(text):
    order = re.search(r"^LockOrder == <<(.*?)>>", text, re.M)
    before = re.search(r"^BeforeQlockOnly == \{(.*?)\}", text, re.M)
    audio = re.search(r"^AudioLocks == \{(.*?)\}", text, re.M)
    if not order or not before or not audio:
        return None, None, None
    return (re.findall(r'"(\w+)"', order.group(1)), set(re.findall(r'"(\w+)"', before.group(1))),
            set(re.findall(r'"(\w+)"', audio.group(1))))


def lock_of(node, cls):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "state_section":
        return "_qlock"
    if isinstance(node, ast.Name):
        return PARAM_LOCKS.get((cls, node.id))
    if isinstance(node, ast.Attribute):
        if node.attr == "lock" and (
                (isinstance(node.value, ast.Attribute) and node.value.attr == "lib")
                or (cls == "Library" and isinstance(node.value, ast.Name) and node.value.id == "self")):
            return "lib_lock"
        return ATTRS.get(node.attr)
    return None


def acquired(node, cls):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "acquire":
        return lock_of(node.func.value, cls)
    return None


def nonblocking(call):
    first = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "blocking"), None)
    return isinstance(first, ast.Constant) and first.value is False


HOOKS = {}


def function_table(trees):
    HOOKS.clear()
    HOOKS.update(hooks(trees))
    out = {}
    for module, tree in trees.items():
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[(module, None, n.name)] = n
            elif isinstance(n, ast.ClassDef):
                for f in n.body:
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out[(module, n.name, f.name)] = f
    return out


def resolve(table, call, module, cls):
    f, keys = call.func, []
    if isinstance(f, ast.Name):
        keys = [(module, None, f.id)]
    elif isinstance(f, ast.Attribute):
        v, name = f.value, f.attr
        if isinstance(v, ast.Name) and v.id == "self" and cls:
            keys = [(module, cls, name)] + [(m, c, name) for (m, c, _) in table if c == SUBCLASSES.get(cls)]
        elif (isinstance(v, ast.Name) and v.id in APP_NAMES) or (isinstance(v, ast.Attribute) and v.attr == "app"):
            keys = [("server.py", "App", name)]
        elif (isinstance(v, ast.Name) and v.id in ENGINE_NAMES) or (isinstance(v, ast.Attribute)
                                                                    and v.attr == "engine"):
            keys = [("engine.py", "Engine", name), ("engine.py", "MockEngine", name)]
        elif isinstance(v, ast.Name) and v.id == "cmd":
            keys = [("comandos.py", None, name)]
        elif isinstance(v, ast.Attribute) and v.attr == "automatico":
            keys = [("automatico.py", "Automatico", name)]
        elif isinstance(v, ast.Attribute) and v.attr == "lib":
            keys = [("server.py", "Library", name)]
    keys = [HOOKS.get(k, k) for k in keys]
    return [k for k in dict.fromkeys(keys) if k in table]


def hooks(trees):
    setters = {}
    for f in ast.walk(trees.get("engine.py", ast.Module(body=[], type_ignores=[]))):
        if (isinstance(f, ast.FunctionDef) and len(f.body) == 1 and isinstance(f.body[0], ast.Assign)
                and isinstance(f.body[0].targets[0], ast.Attribute) and isinstance(f.body[0].value, ast.Name)):
            setters[f.name] = f.body[0].targets[0].attr
    out = {}
    for call in ast.walk(trees.get("server.py", ast.Module(body=[], type_ignores=[]))):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in setters
                and call.args and isinstance(call.args[0], ast.Lambda) and isinstance(call.args[0].body, ast.Call)
                and isinstance(call.args[0].body.func, ast.Attribute)):
            out[("engine.py", "Engine", setters[call.func.attr])] = ("server.py", "App", call.args[0].body.func.attr)
    return out


def summaries(table):
    direct, calls = {}, {}
    for key, func in table.items():
        module, cls, _ = key
        direct[key], calls[key] = set(), set()
        for n in ast.walk(func):
            lock = lock_of(n.context_expr, cls) if isinstance(n, ast.withitem) else acquired(n, cls)
            if lock:
                direct[key].add(lock)
            if isinstance(n, ast.Call):
                calls[key] |= set(resolve(table, n, module, cls))
                if writer(n):
                    direct[key].add(WRITES)
    out = {k: set(v) for k, v in direct.items()}
    changed = True
    while changed:
        changed = False
        for key in table:
            more = set().union(*(out[c] for c in calls[key])) - out[key] if calls[key] else set()
            if more:
                out[key] |= more
                changed = True
    return out


def writer(call):
    f = call.func
    return (f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None) in WRITERS


def in_order(held, lock, order, before):
    if lock in before:
        return not held
    rank = {name: i for i, name in enumerate(order)}
    return all((h in before and lock == "_qlock") or (h in rank and rank[h] < rank[lock]) for h in held)


class Walker(ast.NodeVisitor):
    def __init__(self, name, order, before, table, summary):
        self.name, self.order, self.before, self.table, self.summary = name, order, before, table, summary
        self.cls, self.held, self.bad, self.used, self.nested, self.followed = None, [], [], set(), 0, 0
        self.callbacks, self.walked, self.scopes = {}, 0, []

    def take(self, lock, line, waits=True):
        self.used.add(lock)
        if self.held:
            self.nested += 1
        if not in_order(self.held, lock, self.order, self.before):
            self.bad.append(f"{self.name}:{line}: {lock} taken while holding {', '.join(self.held)}")
        elif lock == "_lock" and "fila_lock" in self.held and waits:
            self.bad.append(f"{self.name}:{line}: the _lock waited for with the fila_lock held (with_engine tries "
                            f"it with blocking=False)")

    def against_held(self, locks, node, label):
        for lock in sorted(locks):
            if lock == WRITES:
                if NO_WRITES & set(self.held):
                    self.bad.append(f"{self.name}:{node.lineno}: calls {label}, which writes a file, while holding "
                                    f"{sorted(NO_WRITES & set(self.held))}")
                continue
            if lock == "_lock" and lock in self.held and "_qlock" not in self.held:
                continue
            if lock in self.held or not in_order(self.held, lock, self.order, self.before) or (
                    lock == "_lock" and "fila_lock" in self.held):
                self.bad.append(f"{self.name}:{node.lineno}: calls {label}, which takes {lock}, while holding "
                                f"{', '.join(self.held)}")

    def local(self, node):
        if not isinstance(node.func, ast.Name):
            return None
        for outer in reversed(self.scopes):
            for n in ast.walk(outer):
                if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not outer
                        and n.name == node.func.id):
                    return n
        return None

    def local_locks(self, func):
        locks = set()
        for n in ast.walk(func):
            lock = lock_of(n.context_expr, self.cls) if isinstance(n, ast.withitem) else acquired(n, self.cls)
            if lock:
                locks.add(lock)
            if isinstance(n, ast.Call):
                if writer(n):
                    locks.add(WRITES)
                for key in resolve(self.table, n, self.name, self.cls):
                    locks |= self.summary[key]
        return locks

    def follow(self, node):
        keys = resolve(self.table, node, self.name, self.cls)
        for key in keys:
            self.followed += 1
            self.against_held(self.summary[key], node, f"{key[1] + '.' if key[1] else ''}{key[2]}")
        nested = None if keys else self.local(node)
        if nested is not None:
            self.followed += 1
            self.against_held(self.local_locks(nested), node, nested.name)

    def visit_ClassDef(self, node):
        outer, self.cls = self.cls, node.name
        self.generic_visit(node)
        self.cls = outer

    def callables(self, func, arg):
        if isinstance(arg, ast.Lambda):
            return [arg]
        if not isinstance(arg, ast.Name):
            return []
        out = [n for n in ast.walk(func) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == arg.id and n is not func]
        for n in ast.walk(func):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == arg.id for t in n.targets):
                out += [m for m in ast.walk(n.value) if isinstance(m, ast.Lambda)]
        return out

    def mark_callbacks(self, func):
        for call in ast.walk(func):
            if not isinstance(call, ast.Call):
                continue
            for key in resolve(self.table, call, self.name, self.cls):
                slots = dict(CALLBACKS.get(key, {}))
                if key[0] == "engine.py":
                    slots["pode"] = ENGINE_GUARD
                args = list(enumerate(call.args)) + [(k.arg, k.value) for k in call.keywords]
                for slot, arg in args:
                    if slot in slots:
                        for target in self.callables(func, arg):
                            self.callbacks[id(target)] = slots[slot]

    def visit_FunctionDef(self, node):
        self.walked += id(node) in self.callbacks
        outer, self.held = self.held, list(self.callbacks.get(id(node), []))
        self.mark_callbacks(node)
        self.scopes.append(node)
        self.generic_visit(node)
        self.scopes.pop()
        self.held = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self.walked += id(node) in self.callbacks
        outer, self.held = self.held, list(self.callbacks.get(id(node), []))
        self.generic_visit(node)
        self.held = outer

    def visit_With(self, node):
        taken = []
        for item in node.items:
            self.visit(item.context_expr)
            lock = lock_of(item.context_expr, self.cls)
            if lock:
                self.take(lock, item.context_expr.lineno)
                self.held.append(lock)
                taken.append(lock)
        for stmt in node.body:
            self.visit(stmt)
        del self.held[len(self.held) - len(taken):]

    visit_AsyncWith = visit_With

    def visit_Call(self, node):
        lock = acquired(node, self.cls)
        if lock:
            self.take(lock, node.lineno, waits=not nonblocking(node))
        elif self.held:
            if writer(node) and NO_WRITES & set(self.held):
                self.bad.append(f"{self.name}:{node.lineno}: a file written while holding "
                                f"{sorted(NO_WRITES & set(self.held))}")
            self.follow(node)
        self.generic_visit(node)


def defined(tree, cls, name):
    body = tree.body if cls is None else next(
        (n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls), [])
    return next((f for f in body if isinstance(f, ast.FunctionDef) and f.name == name), None)


def calls_with_locks(node, cls, held, out, passed):
    if isinstance(node, ast.With):
        held = held | {lock_of(i.context_expr, cls) for i in node.items} - {None}
    elif isinstance(node, ast.FunctionDef) and node.name in passed:
        held = passed[node.name]
    if isinstance(node, ast.Call):
        out.append((node, held))
    if isinstance(node, ast.If) and acquired(node.test, cls):
        calls_with_locks(node.test, cls, held, out, passed)
        for child in node.body:
            calls_with_locks(child, cls, held | {acquired(node.test, cls)}, out, passed)
        for child in node.orelse:
            calls_with_locks(child, cls, held, out, passed)
        return
    for child in ast.iter_child_nodes(node):
        calls_with_locks(child, cls, held, out, passed)


def passed_callbacks(func):
    out = {}
    for call in ast.walk(func):
        if not isinstance(call, ast.Call):
            continue
        name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
        for key, slots in CALLBACKS.items():
            if key[2] != name:
                continue
            args = list(enumerate(call.args)) + [(kw.arg, kw.value) for kw in call.keywords]
            for slot, arg in args:
                if slot in slots and isinstance(arg, ast.Name):
                    out[arg.id] = set(slots[slot]) | CALLER_HOLDS.get(key, set())
    return out


def uses_pode(value):
    return any(isinstance(n, ast.Name) and n.id == "pode" for n in ast.walk(value))


def pode_guarantees(tree):
    funcs = methods(tree, "Engine")
    memo = {}

    def guarantee(name):
        if name in memo:
            return memo[name]
        memo[name] = set()
        sites, got = [], None
        calls_with_locks(funcs[name], "Engine", set(), sites, {})
        forwarded = {id(n) for c, _ in sites for kw in c.keywords if kw.arg == "pode" and isinstance(kw.value, ast.Lambda)
                     for n in ast.walk(kw.value)}
        for call, held in sites:
            f = call.func
            if isinstance(f, ast.Name) and f.id == "pode" and id(call) not in forwarded:
                here = held
            elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self"
                  and f.attr in funcs and any(kw.arg == "pode" and uses_pode(kw.value) for kw in call.keywords)):
                here = held | guarantee(f.attr)
            else:
                continue
            got = here if got is None else got & here
        memo[name] = got or set()
        return memo[name]
    return {name: guarantee(name) for name, f in funcs.items()
            if not name.startswith("_") and "pode" in [a.arg for a in f.args.args + f.args.kwonlyargs]}


def pode_failures(tree):
    return [f"Engine.{name} runs its pode under {sorted(held)}, not under {ENGINE_GUARD}"
            for name, held in pode_guarantees(tree).items() if not set(ENGINE_GUARD) <= held]


def called_attr(call):
    return call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)


def outer_failures(trees):
    calls = [c for t in trees.values() for c in ast.walk(t) if isinstance(c, ast.Call) and called_attr(c) == "with_lock"]
    return [f"with_lock called with {ast.unparse(c.args[0]) if c.args else 'nothing'} as its outer lock, not the "
            f"fila_lock" for c in calls if not (c.args and isinstance(c.args[0], ast.Attribute)
                                                and c.args[0].attr == "fila_lock")] + ([] if calls else ["no with_lock"])


def caller_failures(trees):
    table = function_table(trees)
    edges, called = [], set()
    for key, func in table.items():
        module, cls, _ = key
        sites = []
        calls_with_locks(func, cls, set(), sites, passed_callbacks(func))
        for call, held in sites:
            for callee in resolve(table, call, module, cls):
                if callee != key:
                    edges.append((key, callee, held))
                    called.add(callee)
    needs = {k: set(v) for k, v in CALLER_HOLDS.items() if k in table}
    why, changed = {}, True
    while changed:
        changed = False
        for caller, callee, held in edges:
            miss = needs.get(callee, set()) - held - needs.get(caller, set())
            if miss:
                needs.setdefault(caller, set()).update(miss)
                why.setdefault(caller, callee)
                changed = True

    def chain(k):
        out = [k]
        while out[-1] in why and why[out[-1]] not in out:
            out.append(why[out[-1]])
        return " -> ".join(".".join(p for p in x[1:] if p) for x in out)
    return [f"{k[0]}: {chain(k)} needs {sorted(v)} held, and nothing that calls {k[2]} holds it"
            for k, v in needs.items() if k not in called]


def scope_failures(trees):
    out = []
    for key, slots in CALLBACKS.items():
        module, cls, name = key
        func = defined(trees[module], cls, name)
        if func is None:
            out.append(f"{name} is not in {module}")
            continue
        params = [a.arg for a in func.args.args]
        found = []
        calls_with_locks(func, cls, set(), found, passed_callbacks(func))
        for slot, locks in slots.items():
            if not isinstance(slot, str):
                continue
            sites = [h for c, h in found if isinstance(c.func, ast.Name) and c.func.id == slot]
            sites += [set(other[s]) | CALLER_HOLDS.get(k, set()) for c, _ in found for k, other in CALLBACKS.items()
                      if called_attr(c) == k[2] for s, a in list(enumerate(c.args)) + [(kw.arg, kw.value)
                                                                                    for kw in c.keywords]
                      if s in other and isinstance(a, ast.Name) and a.id == slot]
            need = set(locks) - CALLER_HOLDS.get(key, set())
            if slot not in params or not sites or any(not need <= h for h in sites):
                out.append(f"{module}: {name} runs its {slot} with {[sorted(h) for h in sites]}, not with "
                           f"{sorted(need)} (the caller holds {sorted(CALLER_HOLDS.get(key, set()))})")
    return out


def scan(sources, order, before):
    trees = {name: ast.parse(text, name) for name, text in sources.items()}
    table = function_table(trees)
    summary = summaries(table)
    bad, used, nested, followed, walked = [], set(), 0, 0, 0
    for name, tree in trees.items():
        w = Walker(name, order, before, table, summary)
        w.visit(tree)
        bad += w.bad
        used |= w.used
        nested += w.nested
        followed += w.followed
        walked += w.walked
    return bad, used, nested, followed, walked


def methods(tree, cls):
    node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls), None)
    return {} if node is None else {f.name: f for f in node.body if isinstance(f, ast.FunctionDef)}


def audio_locks(text):
    tree = ast.parse(text)
    funcs = {("self", k): f for k, f in methods(tree, AUDIO[0]).items()}
    funcs.update({("module", f.name): f for f in tree.body if isinstance(f, ast.FunctionDef)})
    seen, todo, taken = set(), [("self", AUDIO[1])], {}
    while todo:
        key = todo.pop()
        if key in seen or key not in funcs:
            continue
        seen.add(key)
        for n in ast.walk(funcs[key]):
            lock = lock_of(n.context_expr, AUDIO[0]) if isinstance(n, ast.withitem) else acquired(n, AUDIO[0])
            if lock:
                taken.setdefault(lock, set()).add(key[1])
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"):
                todo.append(("self", n.func.attr))
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                todo.append(("module", n.func.id))
    return seen, taken


def self_test(order, before):
    cases = {
        "the _qlock, then the fila_lock": ("def f(A, E):\n    with E._qlock:\n        with A.fila_lock:\n"
                                           "            pass\n", 1),
        "the fila_lock, then the proximo_lock": ("def f(A):\n    with A.fila_lock:\n        with A.proximo_lock:\n"
                                                 "            pass\n", 1),
        "the _qlock, then _lock.acquire()": ("def f(E):\n    with E._qlock:\n        E._lock.acquire()\n", 1),
        "the _lock, then the shelf's lock": ("def f(A, E):\n    with E._lock:\n        with A.lib.lock:\n"
                                             "            pass\n", 1),
        "the proximo_lock and the _qlock in one with": ("def f(A, E):\n    with A.proximo_lock, E._qlock:\n"
                                                        "        pass\n", 0),
        "the shelf's lock, then the _qlock": ("def f(A, e):\n    with A.lib.lock:\n        with e._qlock:\n"
                                              "            pass\n", 0),
        "the fila_lock, then _lock.acquire(blocking=False)": ("def f(A, e):\n    with A.fila_lock:\n"
                                                              "        e._lock.acquire(blocking=False)\n", 0),
        "a lock taken in a nested function does not count as held by the outer one": (
            "def f(A, E):\n    with E._qlock:\n        def g():\n            with A.fila_lock:\n"
            "                pass\n", 0),
    }
    cases.update({
        "the fila_lock, then a blocking _lock.acquire()": ("def f(A, e):\n    with A.fila_lock:\n"
                                                           "        e._lock.acquire()\n", 1),
        "the fila_lock, then a with of the _lock": ("def f(A, e):\n    with A.fila_lock:\n        with e._lock:\n"
                                                    "            pass\n", 1),
    })
    calls = {
        "an engine method that takes the _lock, called with the _qlock held": (
            {"engine.py": "class Engine:\n    def stop(self):\n        with self._lock:\n            pass\n",
             "case.py": "def f(A, E):\n    with E._qlock:\n        E.stop()\n"}, 1),
        "the change_queue called with the _qlock already held": (
            {"server.py": "class App:\n    def change_queue(self, c):\n        with self.engine._qlock:\n"
                          "            c()\n    def f(self):\n        with self.engine._qlock:\n"
                          "            self.change_queue(None)\n"}, 1),
        "an engine method that waits for the _lock, called with the fila_lock held": (
            {"engine.py": "class Engine:\n    def stop(self):\n        with self._lock:\n            pass\n",
             "case.py": "def f(A):\n    with A.fila_lock:\n        A.engine.stop()\n"}, 1),
        "the _lock taken again through a method of the same engine (an RLock)": (
            {"engine.py": "class Engine:\n    def a(self):\n        with self._lock:\n            self.b()\n"
                          "    def b(self):\n        with self._lock:\n            pass\n"}, 0),
    }
    stubs = {"server.py": "class App:\n    def change_queue(self, change):\n        pass\n"
                          "    def with_engine(self, f):\n        pass\n"
                          "    def save_cfg(self):\n        save_json(self.cfg_path, self.cfg)\n"
                          "class Library:\n    def update(self):\n        with self.lock:\n            pass\n",
             "engine.py": "class Engine:\n    def stop(self, pode=None):\n        with self._lock:\n"
                          "            with self._qlock:\n                pass\n"
                          "    def reopen(self):\n        with self._lock:\n            pass\n",
             "automatico.py": "class Automatico:\n    def head_held(self):\n        with self.app.engine._qlock:\n"
                              "            return True\n",
             "comandos.py": "def concilia(A, under, closed=None):\n    pass\n"}
    callbacks = {
        "a change passed to change_queue that stops the engine": (
            "def f(A, E):\n    A.change_queue(lambda: E.stop())\n", 1),
        "a change passed by keyword to change_queue that stops the engine": (
            "def f(A, E):\n    def change():\n        E.stop()\n    A.change_queue(change=change)\n", 1),
        "a with_engine body that takes the proximo_lock": (
            "def f(A):\n    def body(depois):\n        with A.proximo_lock:\n            pass\n"
            "    A.with_engine(body)\n", 1),
        "a concilia round that takes the proximo_lock": (
            "def f(A):\n    def under(v):\n        with A.proximo_lock:\n            return None\n"
            "    cmd.concilia(A, under)\n", 1),
        "the shelf's lock inside an engine pode": (
            "def f(A, E):\n    def pode():\n        with A.lib.lock:\n            return True\n"
            "    E.stop(pode=pode)\n", 1),
        "a pode bound to a variable that stops the engine": (
            "def f(A, E):\n    pode = (lambda: E.stop()) if A else None\n    E.stop(pode=pode)\n", 1),
        "a shelf method that takes its lock, called with the fila_lock held": (
            "def f(A):\n    with A.fila_lock:\n        A.lib.update()\n", 1),
        "a pode that only reads the platter": ("def f(A, E, tr):\n    E.stop(pode=lambda: E.track is tr)\n", 0),
        "a pode that calls an engine method taking only the _lock": (
            "def f(E):\n    E.stop(pode=lambda: E.reopen())\n", 1),
        "a change passed to change_queue that asks the Automatico, which takes the _qlock": (
            "def f(A):\n    A.change_queue(lambda: A.automatico.head_held())\n", 1),
        "a pode that calls a local helper taking the shelf's lock": (
            "def f(A, E):\n    def record():\n        with A.lib.lock:\n            return None\n"
            "    E.stop(pode=lambda: record() is None)\n", 1),
        "a file written with the fila_lock held": (
            "def f(A, p, d):\n    with A.fila_lock:\n        save_json(p, d)\n", 1),
        "a with_engine body that saves the settings": (
            "def f(A):\n    def body(depois):\n        A.save_cfg()\n    A.with_engine(body)\n", 1),
        "an engine pode that saves the settings": (
            "def f(A, E):\n    E.stop(pode=lambda: A.save_cfg())\n", 1),
        "a file written with only the engine's _qlock held": (
            "def f(E, p, d):\n    with E._qlock:\n        save_json(p, d)\n", 1),
        "a copy under the fila_lock, written after it": (
            "def f(A, p):\n    with A.fila_lock:\n        d = dict(A.cfg)\n    save_json(p, d)\n", 0),
    }
    for what, (code, expected) in callbacks.items():
        bad, *_ = scan(dict(stubs, **{"case.py": code}), order, before)
        check(bool(bad) == bool(expected), f"the check {'flags' if expected else 'accepts'} {what} ({bad})")
    for what, (code, expected) in cases.items():
        bad, *_ = scan({"case.py": code}, order, before)
        check(len(bad) == expected, f"the check {'flags' if expected else 'accepts'} {what} ({bad})")
    for what, (sources, expected) in calls.items():
        bad, *_ = scan(sources, order, before)
        check(len(bad) == expected, f"the check {'flags' if expected else 'accepts'} {what} ({bad})")
    real = {m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}
    swapped = [order[1], order[0], *order[2:]]
    bad, *_ = scan(real, swapped, before)
    check(bool(bad), f"with the _lock declared before the fila_lock in the model, the code breaks the order "
                     f"({len(bad)} places, the first {bad[:1]})")
    helper = real["server.py"].replace(
        "        def shelf_record():\n            return self.lib.get(",
        "        def shelf_record():\n            with self.lib.lock:\n                pass\n"
        "            return self.lib.get(")
    bad, *_ = scan(dict(real, **{"server.py": helper}), order, before)
    check(helper != real["server.py"] and bool(bad),
          f"with the shelf's lock taken in the refused stream's shelf_record, which its pode calls, the check fails "
          f"({bad[:1]})")
    waits = dict(real, **{"engine.py": real["engine.py"].replace("acquire(blocking=False)", "acquire()")})
    bad, *_ = scan(waits, order, before)
    check(waits["engine.py"] != real["engine.py"] and bool(bad),
          f"with the with_engine waiting for the _lock with the fila_lock held, the check fails ({bad[:1]})")
    engine = ("class Engine:\n    def _mixa(self):\n        with self._qlock:\n            self._vira()\n"
              "    def _vira(self):\n        with self._lock:\n            pass\n")
    _, taken = audio_locks(engine)
    check(taken.get("_lock") == {"_vira"},
          f"the audio check sees the _lock taken by a method the _mixa calls ({taken})")
    engine = ("def take_engine_lock(e):\n    with e._lock:\n        pass\n"
              "class Engine:\n    def _mixa(self):\n        take_engine_lock(self)\n        with self._qlock:\n"
              "            pass\n")
    _, taken = audio_locks(engine)
    check(taken.get("_lock") == {"take_engine_lock"},
          f"the audio check sees the _lock taken by a module function the _mixa calls ({taken})")


def main():
    order, before, audio = declared(MODEL.read_text(encoding="utf-8"))
    check(order is not None, f"{MODEL.relative_to(ROOT)} declares LockOrder, BeforeQlockOnly and AudioLocks")
    if order is None:
        sys.exit(1)
    self_test(order, before)
    sources = {m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}
    bad, used, nested, followed, walked = scan(sources, order, before)
    check(not bad, f"every with of the locks in {', '.join(MODULES)} follows the order declared in the model, also "
                   f"through the calls made with a lock held and the callbacks run under one ({nested} nested "
                   f"acquisitions, {followed} calls followed, {walked} callbacks; {bad})")
    check(used == set(order) | before, f"the code takes exactly the locks the model declares ({sorted(used)})")
    trees = {m: ast.parse(sources[m], m) for m in MODULES}
    inside = sources["engine.py"].replace(
        "                        self._espera_arquivo = gen\n                if waits and self._stream_silent is not None:\n"
        "                    self._stream_silent(track)\n",
        "                        self._espera_arquivo = gen\n                    if waits and self._stream_silent is not None:\n"
        "                        self._stream_silent(track)\n")
    bad, *_ = scan(dict(sources, **{"engine.py": inside}), order, before)
    check(inside != sources["engine.py"] and any("_stream_refused" in b for b in bad),
          f"with the reader handing a silent stream to the App while it holds the _qlock, the check fails, through the "
          f"hook the App registers ({bad[:1]})")
    callers = caller_failures(trees)
    check(not callers, f"whoever calls the change_queue, the close_switches and the concilia holds the fila_lock, also "
                       f"up the calls to the entry points ({callers})")
    bare = sources["server.py"].replace("        with self.fila_lock:\n            return self.change_queue(move)\n",
                                        "        return self.change_queue(move)\n")
    callers = caller_failures(dict(trees, **{"server.py": ast.parse(bare)}))
    check(bare != sources["server.py"] and len(callers) == 1,
          f"with the App moving an entry through change_queue without the fila_lock, the check fails ({callers})")
    scope = scope_failures(trees) + outer_failures(trees)
    check(not scope, f"each callback the check follows runs, in the code that calls it, under the locks the check "
                     f"gives it ({len(CALLBACKS)} functions; {scope})")
    moved = sources["server.py"].replace("        with self.engine.state_section():\n            r = change()\n",
                                         "        r = change()\n        with self.engine.state_section():\n")
    scope = scope_failures(dict(trees, **{"server.py": ast.parse(moved)}))
    check(moved != sources["server.py"] and len(scope) == 1,
          f"with the change_queue running its change before taking the _qlock, the scope check fails ({scope})")
    guarded = pode_guarantees(trees["engine.py"])
    check(len(guarded) >= 5 and not pode_failures(trees["engine.py"]),
          f"every Engine method that takes a pode runs it under the _lock and the _qlock, also through the methods it "
          f"hands it to ({sorted(guarded)}; {pode_failures(trees['engine.py'])})")
    early = sources["engine.py"].replace("        with self._qlock:\n            if pode is not None and not pode():\n"
                                         "                return None, None\n",
                                         "        if pode is not None and not pode():\n            return None, None\n"
                                         "        with self._qlock:\n")
    check(early != sources["engine.py"] and len(pode_failures(ast.parse(early))) >= 3,
          f"with the _restart running the pode before the _qlock, the check fails for the methods that hand it on "
          f"({pode_failures(ast.parse(early))})")
    seen, taken = audio_locks(sources["engine.py"])
    check(set(taken) == audio, f"the audio thread ({'.'.join(AUDIO)} and the {len(seen) - 1} Engine methods it calls) "
                               f"takes only the AudioLocks of the model, {sorted(audio)} "
                               f"({ {k: sorted(v) for k, v in taken.items()} })")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
