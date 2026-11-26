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

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def declared(text):
    order = re.search(r"^LockOrder == <<(.*?)>>", text, re.M)
    before = re.search(r"^BeforeQlockOnly == \{(.*?)\}", text, re.M)
    if not order or not before:
        return None, None
    return re.findall(r'"(\w+)"', order.group(1)), set(re.findall(r'"(\w+)"', before.group(1)))


def lock_of(node, cls):
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


def function_table(trees):
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
    return [k for k in dict.fromkeys(keys) if k in table]


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


def in_order(held, lock, order, before):
    if lock in before:
        return not held
    rank = {name: i for i, name in enumerate(order)}
    return all((h in before and lock == "_qlock") or (h in rank and rank[h] < rank[lock]) for h in held)


class Walker(ast.NodeVisitor):
    def __init__(self, name, order, before, table, summary):
        self.name, self.order, self.before, self.table, self.summary = name, order, before, table, summary
        self.cls, self.held, self.bad, self.used, self.nested, self.followed = None, [], [], set(), 0, 0

    def take(self, lock, line, waits=True):
        self.used.add(lock)
        if self.held:
            self.nested += 1
        if not in_order(self.held, lock, self.order, self.before):
            self.bad.append(f"{self.name}:{line}: {lock} taken while holding {', '.join(self.held)}")
        elif lock == "_lock" and "fila_lock" in self.held and waits:
            self.bad.append(f"{self.name}:{line}: the _lock waited for with the fila_lock held (with_engine tries "
                            f"it with blocking=False)")

    def follow(self, node):
        for key in resolve(self.table, node, self.name, self.cls):
            self.followed += 1
            for lock in sorted(self.summary[key]):
                if lock == "_lock" and lock in self.held:
                    continue
                if lock in self.held or not in_order(self.held, lock, self.order, self.before) or (
                        lock == "_lock" and "fila_lock" in self.held):
                    self.bad.append(f"{self.name}:{node.lineno}: calls {key[1] + '.' if key[1] else ''}{key[2]}, "
                                    f"which takes {lock}, while holding {', '.join(self.held)}")

    def visit_ClassDef(self, node):
        outer, self.cls = self.cls, node.name
        self.generic_visit(node)
        self.cls = outer

    def visit_FunctionDef(self, node):
        outer, self.held = self.held, []
        self.generic_visit(node)
        self.held = outer

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

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
            self.follow(node)
        self.generic_visit(node)


def scan(sources, order, before):
    trees = {name: ast.parse(text, name) for name, text in sources.items()}
    table = function_table(trees)
    summary = summaries(table)
    bad, used, nested, followed = [], set(), 0, 0
    for name, tree in trees.items():
        w = Walker(name, order, before, table, summary)
        w.visit(tree)
        bad += w.bad
        used |= w.used
        nested += w.nested
        followed += w.followed
    return bad, used, nested, followed


def methods(tree, cls):
    node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls), None)
    return {} if node is None else {f.name: f for f in node.body if isinstance(f, ast.FunctionDef)}


def audio_locks(text):
    funcs = methods(ast.parse(text), AUDIO[0])
    seen, todo, taken = set(), [AUDIO[1]], {}
    while todo:
        name = todo.pop()
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        for n in ast.walk(funcs[name]):
            lock = lock_of(n.context_expr, AUDIO[0]) if isinstance(n, ast.withitem) else acquired(n, AUDIO[0])
            if lock:
                taken.setdefault(lock, set()).add(name)
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"):
                todo.append(n.func.attr)
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
    for what, (code, expected) in cases.items():
        bad, _, _, _ = scan({"case.py": code}, order, before)
        check(len(bad) == expected, f"the check {'flags' if expected else 'accepts'} {what} ({bad})")
    for what, (sources, expected) in calls.items():
        bad, _, _, _ = scan(sources, order, before)
        check(len(bad) == expected, f"the check {'flags' if expected else 'accepts'} {what} ({bad})")
    real = {m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}
    swapped = [order[1], order[0], *order[2:]]
    bad, _, _, _ = scan(real, swapped, before)
    check(bool(bad), f"with the _lock declared before the fila_lock in the model, the code breaks the order "
                     f"({len(bad)} places, the first {bad[:1]})")
    waits = dict(real, **{"server.py": real["server.py"].replace("acquire(blocking=False)", "acquire()")})
    bad, _, _, _ = scan(waits, order, before)
    check(waits["server.py"] != real["server.py"] and bool(bad),
          f"with the with_engine waiting for the _lock with the fila_lock held, the check fails ({bad[:1]})")
    engine = ("class Engine:\n    def _mixa(self):\n        with self._qlock:\n            self._vira()\n"
              "    def _vira(self):\n        with self._lock:\n            pass\n")
    _, taken = audio_locks(engine)
    check(taken.get("_lock") == {"_vira"},
          f"the audio check sees the _lock taken by a method the _mixa calls ({taken})")


def main():
    order, before = declared(MODEL.read_text(encoding="utf-8"))
    check(order is not None, f"{MODEL.relative_to(ROOT)} declares LockOrder and BeforeQlockOnly")
    if order is None:
        sys.exit(1)
    self_test(order, before)
    sources = {m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}
    bad, used, nested, followed = scan(sources, order, before)
    check(not bad, f"every with of the locks in {', '.join(MODULES)} follows the order declared in the model, also "
                   f"through the calls made with a lock held ({nested} nested acquisitions, {followed} calls "
                   f"followed; {bad})")
    check(used == set(order) | before, f"the code takes exactly the locks the model declares ({sorted(used)})")
    seen, taken = audio_locks(sources["engine.py"])
    check(set(taken) == {"_qlock"}, f"the audio thread ({'.'.join(AUDIO)} and the {len(seen) - 1} Engine methods it "
                                    f"calls) takes only the _qlock ({ {k: sorted(v) for k, v in taken.items()} })")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
