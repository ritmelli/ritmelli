import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "dev" / "tla" / "Locks.tla"
MODULES = ("comandos.py", "server.py", "automatico.py", "engine.py")
ATTRS = {"fila_lock": "fila_lock", "_lock": "_lock", "_qlock": "_qlock", "proximo_lock": "proximo_lock"}
AUDIO = ("Engine", "_mixa")

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


def in_order(held, lock, order, before):
    if lock in before:
        return not held
    rank = {name: i for i, name in enumerate(order)}
    return all((h in before and lock == "_qlock") or (h in rank and rank[h] < rank[lock]) for h in held)


class Walker(ast.NodeVisitor):
    def __init__(self, name, order, before):
        self.name, self.order, self.before = name, order, before
        self.cls, self.held, self.bad, self.used, self.nested = None, [], [], set(), 0

    def take(self, lock, line):
        self.used.add(lock)
        if self.held:
            self.nested += 1
        if not in_order(self.held, lock, self.order, self.before):
            self.bad.append(f"{self.name}:{line}: {lock} taken while holding {', '.join(self.held)}")

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
            self.take(lock, node.lineno)
        self.generic_visit(node)


def scan(sources, order, before):
    bad, used, nested = [], set(), 0
    for name, text in sources.items():
        w = Walker(name, order, before)
        w.visit(ast.parse(text, name))
        bad += w.bad
        used |= w.used
        nested += w.nested
    return bad, used, nested


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
    for what, (code, expected) in cases.items():
        bad, _, _ = scan({"case.py": code}, order, before)
        check(len(bad) == expected, f"the check {'flags' if expected else 'accepts'} {what} ({bad})")
    swapped = [order[1], order[0], *order[2:]]
    bad, _, _ = scan({m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}, swapped, before)
    check(bool(bad), f"with the _lock declared before the fila_lock in the model, the code breaks the order "
                     f"({len(bad)} places, the first {bad[:1]})")
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
    bad, used, nested = scan(sources, order, before)
    check(not bad, f"every with of the locks in {', '.join(MODULES)} follows the order declared in the model "
                   f"({nested} nested acquisitions; {bad})")
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
