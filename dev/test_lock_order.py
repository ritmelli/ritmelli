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
BUILDERS = {("engine.py", "Engine", "trocar_fonte"): ("novo", 1, ENGINE_GUARD),
            ("engine.py", "Engine", "preparar"): ("track", 0, ENGINE_GUARD),
            ("engine.py", "Engine", "load"): ("track", 0, ENGINE_GUARD),
            ("server.py", "App", "_troca"): ("tr", 0, ["fila_lock"] + ENGINE_GUARD)}
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
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
        return ATTRS.get(node.args[1].value)
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


def has_lock(node, cls):
    if lock_of(node, cls):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(has_lock(e, cls) for e in node.elts)
    if isinstance(node, ast.Dict):
        return any(has_lock(x, cls) for x in [*node.values, *(k for k in node.keys if k is not None)])
    if isinstance(node, ast.Lambda):
        return has_lock(node.body, cls)
    if isinstance(node, ast.IfExp):
        return has_lock(node.body, cls) or has_lock(node.orelse, cls)
    if isinstance(node, ast.BoolOp):
        return any(has_lock(v, cls) for v in node.values)
    if isinstance(node, (ast.Starred, ast.NamedExpr)):
        return has_lock(node.value, cls)
    return False


def lock_bindings(trees):
    out = []
    for module, tree in trees.items():
        owner = {id(n): c.name for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for n in ast.walk(c)}
        inside = {}
        for f in ast.walk(tree):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inside.update((id(m), f.name) for m in ast.walk(f))
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and n.value is not None:
                roots = n.targets if isinstance(n, ast.Assign) else [n.target]
                values = [n.value]
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                roots, values = [n.optional_vars], [n.context_expr]
            elif isinstance(n, ast.withitem):
                cls = owner.get(id(n))
                if not lock_of(n.context_expr, cls) and any(lock_of(v, cls) for v in ast.walk(n.context_expr)):
                    out.append(f"{module}:{n.context_expr.lineno}: a lock taken through an expression, not by its name")
                continue
            elif isinstance(n, ast.Call) and acquired(n, owner.get(id(n))) and not (
                    nonblocking(n) and inside.get(id(n)) == "with_lock"):
                out.append(f"{module}:{n.lineno}: {acquired(n, owner.get(id(n)))} acquired by hand, outside the "
                           f"with_lock's try")
                continue
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                roots, values = [n.target], [n.iter]
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                roots = [ast.Name(a.arg) for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs]
                values = n.args.defaults + [d for d in n.args.kw_defaults if d is not None]
            elif isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom)):
                if n.value is not None and has_lock(n.value, owner.get(id(n))):
                    out.append(f"{module}:{n.lineno}: a lock returned by a function")
                continue
            elif isinstance(n, ast.Call):
                args = [*(n.args[1:] if called_attr(n) == "with_lock" else n.args), *(k.value for k in n.keywords)]
                if any(has_lock(a, owner.get(id(n))) for a in args):
                    out.append(f"{module}:{n.lineno}: a lock passed as an argument to {ast.unparse(n.func)}")
                continue
            else:
                continue
            names = [t.id for root in roots for t in ast.walk(root) if isinstance(t, ast.Name)]
            if names and any(lock_of(v, owner.get(id(n))) for value in values for v in ast.walk(value)):
                at = n if hasattr(n, 'lineno') else values[0]
                out.append(f"{module}:{at.lineno}: a lock bound to a name "
                           f"({', '.join(names)})")
    return out


def acquired(node, cls):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "acquire":
        return lock_of(node.func.value, cls)
    return None


def nonblocking(call):
    first = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "blocking"), None)
    return isinstance(first, ast.Constant) and first.value is False


class Table(dict):
    def __init__(self, funcs, hooked, aliased):
        super().__init__(funcs)
        self.hooked, self.aliased = hooked, aliased


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
    table = Table(out, hooks(trees), {})
    table.aliased.update(bound_aliases(trees, table))
    return table


def with_lock_holds_during_callback(engine):
    func = defined(engine, "Engine", "with_lock")
    if func is None:
        return False
    callback = func.args.args[-1].arg

    def is_release(n):
        return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "release"
                and lock_of(n.func.value, "Engine") == "_lock")
    tries = [n.body[0] for n in ast.walk(func) if isinstance(n, ast.If) and acquired(n.test, "Engine") == "_lock"
             and len(n.body) == 1 and isinstance(n.body[0], ast.Try)]
    return len(tries) == 1 and any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callback
        for b in tries[0].body for n in ast.walk(b)) and not any(
        is_release(n) for b in tries[0].body for n in ast.walk(b)) and any(
        is_release(n) for b in tries[0].finalbody for n in ast.walk(b))


def section_yields_under_qlock(engine):
    func = defined(engine, "Engine", "state_section")
    if func is None:
        return False
    yields = [n for n in ast.walk(func) if isinstance(n, (ast.Yield, ast.YieldFrom))]
    held = {id(n) for w in ast.walk(func) if isinstance(w, ast.With)
            and any(lock_of(i.context_expr, "Engine") == "_qlock" for i in w.items)
            for b in w.body for n in ast.walk(b)}
    return bool(yields) and all(id(y) in held for y in yields)


def value_calls(value):
    if isinstance(value, ast.Call):
        return [value]
    if isinstance(value, ast.BoolOp):
        return [c for v in value.values for c in value_calls(v)]
    if isinstance(value, ast.IfExp):
        return value_calls(value.body) + value_calls(value.orelse)
    return []


def by_getattr(node):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
        return ast.Attribute(value=node.args[0], attr=node.args[1].value, ctx=ast.Load())
    return node


def bound_keys(table, value, names, module, cls):
    value = by_getattr(value)
    if isinstance(value, ast.Name):
        return names.get(value.id, [])
    if isinstance(value, ast.IfExp):
        return (bound_keys(table, value.body, names, module, cls)
                + bound_keys(table, value.orelse, names, module, cls))
    if isinstance(value, ast.BoolOp):
        return [k for v in value.values for k in bound_keys(table, v, names, module, cls)]
    if isinstance(value, ast.Attribute):
        return resolve(table, ast.Call(func=value, args=[], keywords=[]), module, cls)
    return []


def bindings_of(func):
    for n in ast.walk(func):
        if isinstance(n, ast.Assign):
            targets, value = n.targets, n.value
        elif isinstance(n, (ast.AnnAssign, ast.NamedExpr)) and n.value is not None:
            targets, value = [n.target], n.value
        else:
            continue
        for t in targets:
            if isinstance(t, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)) \
                    and len(t.elts) == len(value.elts):
                yield from ((u, v) for u, v in zip(t.elts, value.elts) if isinstance(u, ast.Name))
            elif isinstance(t, ast.Name):
                yield t, value


def bound_aliases(trees, table):
    out = {}
    for module, tree in trees.items():
        scopes = [(None, n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        scopes += [(c.name, f) for c in tree.body if isinstance(c, ast.ClassDef) for f in c.body
                   if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for cls, func in scopes:
            names, pairs, before = {}, list(bindings_of(func)), -1
            while sum(map(len, names.values())) != before:
                before = sum(map(len, names.values()))
                for target, value in pairs:
                    keys = bound_keys(table, value, names, module, cls)
                    if keys:
                        names[target.id] = list(dict.fromkeys(names.get(target.id, []) + keys))
            for n in ast.walk(func):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names
                        and id(n) not in table.aliased):
                    out[id(n)] = names[n.func.id]
    return out


def resolve(table, call, module, cls):
    f, keys = by_getattr(call.func), []
    if id(call) in table.aliased:
        keys = list(table.aliased[id(call)])
    elif isinstance(f, ast.Name):
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
    keys = [table.hooked.get(k, k) for k in keys]
    return [k for k in dict.fromkeys(keys) if k in table]


def self_attr(node):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def hooks(trees):
    empty = ast.Module(body=[], type_ignores=[])
    engine, server = trees.get("engine.py", empty), trees.get("server.py", empty)
    setters, hooked = setters_of(engine), {}

    def bind(attr, value):
        if isinstance(value, ast.Lambda) and isinstance(value.body, ast.Call):
            value = value.body.func
        if self_attr(value):
            hooked[("engine.py", "Engine", attr)] = ("server.py", "App", self_attr(value))
    for n in ast.walk(server):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in setters and n.args:
            bind(setters[n.func.attr], n.args[0])
        elif isinstance(n, ast.Assign):
            for target in n.targets:
                pairs = (zip(target.elts, n.value.elts) if isinstance(target, ast.Tuple)
                         and isinstance(n.value, ast.Tuple) else [(target, n.value)])
                for t, v in pairs:
                    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Attribute) and t.value.attr == "engine":
                        bind(t.attr, v)
    return hooked


def aliases(tree):
    out = {}
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = {}
            for target, value in bindings_of(func):
                if self_attr(by_getattr(value)):
                    names.setdefault(target.id, set()).add(self_attr(by_getattr(value)))
            if names:
                out[func] = names
    return out


def setters_of(engine):
    return {f.name: f.body[0].targets[0].attr for f in ast.walk(engine)
            if isinstance(f, ast.FunctionDef) and len(f.body) == 1 and isinstance(f.body[0], ast.Assign)
            and isinstance(f.body[0].targets[0], ast.Attribute) and isinstance(f.body[0].value, ast.Name)}


def unresolved_hooks(trees):
    engine = trees["engine.py"]
    init, setters = defined(engine, "Engine", "__init__"), setters_of(engine)
    empty = {t.attr for n in ast.walk(init) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
             and n.value.value is None for t in n.targets if self_attr(t)}
    for name, f in methods(engine, "Engine").items():
        if name != "__init__" and name not in setters:
            empty -= {self_attr(t) for n in ast.walk(f) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))
                      for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                      for t in (t.elts if isinstance(t, ast.Tuple) else [t])}
    called = {self_attr(n.func) for n in ast.walk(engine) if isinstance(n, ast.Call) and self_attr(n.func) in empty}
    for func, names in aliases(engine).items():
        called |= {a for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   for a in names.get(n.func.id, ()) if a in empty}
    hooked = hooks(trees)
    return sorted(a for a in called if ("engine.py", "Engine", a) not in hooked)


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

    def visit_Module(self, node):
        for top in node.body:
            for cls, f in ([(top.name, f) for f in top.body] if isinstance(top, ast.ClassDef) else [(None, top)]):
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    outer, self.cls = self.cls, cls
                    self.mark_callbacks(f)
                    self.cls = outer
        self.generic_visit(node)

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
                for call in value_calls(n.value):
                    out += [m for key in resolve(self.table, call, self.name, self.cls)
                            for r in ast.walk(self.table[key]) if isinstance(r, ast.Return) and r.value is not None
                            for m in ast.walk(r.value) if isinstance(m, ast.Lambda)]
        return out

    def mark_callbacks(self, func):
        for call in ast.walk(func):
            if not isinstance(call, ast.Call):
                continue
            for key in resolve(self.table, call, self.name, self.cls):
                slots = dict(CALLBACKS.get(key, {}))
                if key[0] == "engine.py":
                    slots["pode"] = ENGINE_GUARD
                if key in BUILDERS:
                    name, at, locks = BUILDERS[key]
                    slots[name] = slots[at] = locks
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


def calls_with_locks(node, cls, held, out, passed, root=True):
    if isinstance(node, (ast.With, ast.AsyncWith)):
        held = held | {lock_of(i.context_expr, cls) for i in node.items} - {None}
    elif isinstance(node, ast.Lambda) and not root:
        held = passed.get(id(node), set())
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not root:
        held = passed.get(node.name, set())
    if isinstance(node, ast.Call):
        out.append((node, held))
    if isinstance(node, ast.If) and acquired(node.test, cls):
        calls_with_locks(node.test, cls, held, out, passed, False)
        for child in node.body:
            calls_with_locks(child, cls, held | {acquired(node.test, cls)}, out, passed, False)
        for child in node.orelse:
            calls_with_locks(child, cls, held, out, passed, False)
        return
    for child in ast.iter_child_nodes(node):
        calls_with_locks(child, cls, held, out, passed, False)


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
                if slot in slots and isinstance(arg, (ast.Name, ast.Lambda)):
                    out[arg.id if isinstance(arg, ast.Name) else id(arg)] = set(slots[slot]) | CALLER_HOLDS.get(key, set())
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


def builder_held(funcs, name, param, memo):
    if (name, param) in memo:
        return memo[name, param]
    memo[name, param] = set()
    sites = []
    calls_with_locks(funcs[name], "Engine", set(), sites, {})
    best = set()
    for call, held in sites:
        f = call.func
        if isinstance(f, ast.Name) and f.id == param:
            here = held
        elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self" and f.attr in funcs
              and any(isinstance(kw.value, ast.Name) and kw.value.id == param for kw in call.keywords)):
            kw = next(kw.arg for kw in call.keywords if isinstance(kw.value, ast.Name) and kw.value.id == param)
            here = held | builder_held(funcs, f.attr, kw, memo)
        else:
            continue
        best = here if len(here) > len(best) else best
    memo[name, param] = best
    return best


def builds(value, name):
    def call(v):
        return isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == name and not v.args
    return call(value) or (isinstance(value, ast.IfExp) and call(value.body) and isinstance(value.test, ast.Call)
                           and called_attr(value.test) == "callable"
                           and any(isinstance(a, ast.Name) and a.id == name for a in value.test.args))


def builder_failures(tree):
    funcs, memo = methods(tree, "Engine"), {}
    out = [f"Engine.{key[2]} calls its builder {name} under {sorted(builder_held(funcs, key[2], name, memo))}, not "
           f"under {locks}" for key, (name, _, locks) in BUILDERS.items() if key[0] == "engine.py"
           and not set(locks) <= builder_held(funcs, key[2], name, memo)]
    for key, (name, _, _) in BUILDERS.items():
        if key[0] == "engine.py":
            out += [f"Engine.{key[2]}:{n.lineno} publishes a track that is not its builder's call"
                    for n in ast.walk(funcs[key[2]]) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Attribute) and t.attr == "track" for t in n.targets)
                    and not builds(n.value, name)]
            out += [f"Engine.{key[2]}:{n.lineno} hands the _restart a track that is not its builder"
                    for n in ast.walk(funcs[key[2]]) if isinstance(n, ast.Call) and called_attr(n) == "_restart"
                    for kw in n.keywords if kw.arg == "track"
                    and not (isinstance(kw.value, ast.Name) and kw.value.id == name)]
    return out


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
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                todo.append(("self", n.attr))
            elif isinstance(n, ast.Name):
                todo.append(("module", n.id))
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr"
                  and len(n.args) >= 2 and isinstance(n.args[0], ast.Name) and n.args[0].id == "self"
                  and isinstance(n.args[1], ast.Constant)):
                todo.append(("self", n.args[1].value))
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
        "the _qlock taken by getattr, then the fila_lock": (
            "def f(A, E):\n    with getattr(E, '_qlock'):\n        with A.fila_lock:\n            pass\n", 1),
        "the fila_lock, then a with of the _lock": ("def f(A, e):\n    with A.fila_lock:\n        with e._lock:\n"
                                                    "            pass\n", 1),
    })
    bound, passed, returned = "bound to a name", "passed as an argument", "returned by a function"
    bindings = {
        "a lock bound to a local name": ("def f(E):\n    q = E._qlock\n    with q:\n        pass\n", bound),
        "a lock bound to a local name in one branch": (
            "def f(A, E):\n    q = E._lock if A else E._qlock\n    with q:\n        pass\n", bound),
        "the _qlock section bound to a local name": (
            "def f(E):\n    s = E.state_section()\n    with s:\n        pass\n", bound),
        "a lock bound by a with ... as": ("def f(E):\n    with E._lock as held:\n        pass\n", bound),
        "a shelf lock bound to a local name": ("class Library:\n    def f(self):\n        held = self.lock\n", bound),
        "an annotated binding": ("def f(E):\n    q: object = E._qlock\n", bound),
        "a binding in a with (q := ...)": ("def f(E):\n    with (q := E._qlock):\n        pass\n", bound),
        "a lock unpacked from a tuple": ("def f(A, E):\n    a, q = A, E._qlock\n", bound),
        "a lock kept on an attribute": ("class Engine:\n    def f(self, E):\n        self.q = E._qlock\n", bound),
        "a lock as a for target": ("def f(A):\n    for lk in (A.fila_lock,):\n        with lk:\n            pass\n", bound),
        "a lock as a comprehension target": ("def f(A):\n    [x.acquire() for x in [A.fila_lock]]\n", bound),
        "a lock as a parameter's default": ("def f(A, lk=None):\n    def g(lk=A.fila_lock):\n        pass\n", bound),
        "a lock passed as an argument": ("def f(A, h):\n    h(A.fila_lock)\n", passed),
        "a lock handed to a lambda": ("def f(A):\n    with (lambda lk: lk)(A.fila_lock):\n        pass\n", passed),
        "a lock passed in a dict": ("def f(A, h):\n    h({'lock': A.fila_lock})\n", passed),
        "a lock passed as a dict key": ("def f(A, h):\n    h({A.fila_lock: 1})\n", passed),
        "a lock passed by a conditional": ("def f(A, E, h):\n    h(E._lock if A else E._qlock)\n", passed),
        "a lambda returning a lock passed on": ("def f(E, h):\n    h(lambda: E._lock)\n", passed),
        "a lock returned by a getter": ("class Engine:\n    def _mix_lock(self):\n        return self._lock\n", returned),
        "a _qlock section returned by a getter": ("def f(E):\n    return E.state_section()\n", returned),
        "a lock returned by a conditional": ("def f(A, E):\n    return E._lock if A else E._qlock\n", returned),
        "a lock returned in a tuple": ("def f(E):\n    return (E._lock,)\n", returned),
        "a lock yielded from a getter": ("def f(E):\n    yield from (E._qlock,)\n", returned),
        "a lock returned by a lambda": ("def f(E):\n    return lambda: E._lock\n", returned),
        "a lock chosen by an expression in a with": (
            "def f(A, E):\n    with (E._lock if A else E._qlock):\n        pass\n", "taken through an expression"),
        "a lock acquired by hand around a with": (
            "def f(E):\n    E._qlock.acquire()\n    try:\n        with E._lock:\n            pass\n"
            "    finally:\n        E._qlock.release()\n", "acquired by hand"),
    }
    for what, (code, rule) in bindings.items():
        bad = lock_bindings({"case.py": ast.parse(code)})
        check(any(rule in b for b in bad), f"the binding check flags {what}, as {rule} ({bad})")
    bad = lock_bindings({"case.py": ast.parse("def f(A, E):\n    d = E._deck\n    n = len(A.fila)\n")})
    check(not bad, f"the binding check accepts names bound to what is not a lock ({bad})")
    calls = {
        "an engine method that takes the _lock, called with the _qlock held": (
            {"engine.py": "class Engine:\n    def stop(self):\n        with self._lock:\n            pass\n",
             "case.py": "def f(A, E):\n    with E._qlock:\n        E.stop()\n"}, 1),
        "an engine method that takes the _lock, called through a local name with the _qlock held": (
            {"engine.py": "class Engine:\n    def stop(self):\n        with self._lock:\n            pass\n",
             "case.py": "def f(A, E):\n    finish = E.stop\n    with E.state_section():\n        finish()\n"}, 1),
        "an Engine method that takes the _lock, called by the engine with the _qlock held through a name bound in two "
        "branches": (
            {"engine.py": "class Engine:\n    def stop(self):\n        with self._lock:\n            pass\n"
                          "    def esperando_arquivo(self):\n        return True\n"
                          "    def f(self, c):\n        if c:\n            fn = self.stop\n        else:\n"
                          "            fn = self.esperando_arquivo\n        with self._qlock:\n            fn()\n"}, 1),
        **{f"an engine method that takes the _lock, called with the _qlock held through {what}": (
            {"engine.py": "class Engine:\n    def stop(self):\n        with self._lock:\n            pass\n",
             "case.py": f"def f(A, E, c):\n{bind}    with E.state_section():\n        {call}\n"}, 1)
           for what, bind, call in (
               ("getattr", "", "getattr(E, 'stop')()"),
               ("a name bound by getattr", "    finish = getattr(E, 'stop')\n", "finish()"),
               ("a name unpacked from a tuple", "    finish, x = E.stop, 1\n", "finish()"),
               ("a chain of names", "    a = E.stop\n    finish = a\n", "finish()"),
               ("a name bound by a conditional", "    finish = E.stop if c else None\n", "finish()"))},
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
    vira = "    def _vira(self):\n        with self._lock:\n            pass\n"
    for what, body in (("through a local alias", "        vira = self._vira\n        vira()\n"),
                       ("through getattr", "        getattr(self, '_vira')()\n"),
                       ("as a callback", "        run(self._vira)\n")):
        _, taken = audio_locks("class Engine:\n    def _mixa(self):\n" + body + vira)
        check(taken.get("_lock") == {"_vira"},
              f"the audio check sees the _lock taken by a method the _mixa reaches {what} ({taken})")


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
        "                if waits and self._stream_silent is not None:\n                    self._stream_silent(track)\n",
        "                    if waits and self._stream_silent is not None:\n                        self._stream_silent(track)\n")
    bad, *_ = scan(dict(sources, **{"engine.py": inside}), order, before)
    check(inside != sources["engine.py"] and any("_stream_refused" in b for b in bad),
          f"with the reader handing a silent stream to the App while it holds the _qlock, the check fails, through the "
          f"hook the App registers ({bad[:1]})")
    named = re.sub(r"self\.engine\.on_silent_stream\(lambda tr: self\._stream_refused\(\s*tr, [^\n]*\)\)",
                   "self.engine.on_silent_stream(self._stream_refused)", sources["server.py"])
    bad, *_ = scan(dict(sources, **{"engine.py": inside, "server.py": named}), order, before)
    check(named != sources["server.py"] and any("_stream_refused" in b for b in bad),
          f"and so it does with the hook registered as a bound method ({bad[:1]})")
    hooked = hooks(trees)
    unresolved = unresolved_hooks(trees)
    check(not unresolved and len(hooked) >= 4,
          f"every hook the engine calls resolves to the App method that the App puts on it ({sorted(hooked)}; "
          f"unresolved {unresolved})")
    unhooked = sources["server.py"].replace("        self.engine.religar_stream = self.religar_stream\n", "")
    unresolved = unresolved_hooks(dict(trees, **{"server.py": ast.parse(unhooked)}))
    check(unhooked != sources["server.py"] and unresolved == ["religar_stream"],
          f"with the App no longer putting its religar_stream on the engine, the hook check fails ({unresolved})")
    for what, old, new, callee in (
            ("the measure handed to the App", "            try:\n                self.mediu(track, float(lufs))\n",
             "            try:\n                with self._qlock:\n                    self.mediu(track, float(lufs))\n",
             "App.mediu"),
            ("the dropped stream handed to the App through a local name",
             "                religar(track, fim, lambda: self._stream_desistiu(deck, gen, track, fim))\n",
             "                with self._qlock:\n"
             "                    religar(track, fim, lambda: self._stream_desistiu(deck, gen, track, fim))\n",
             "App.religar_stream")):
        moved = sources["engine.py"].replace(old, new)
        bad, *_ = scan(dict(sources, **{"engine.py": moved}), order, before)
        check(moved != sources["engine.py"] and any(callee in b for b in bad),
              f"with {what} called under the _qlock, the check fails ({[b for b in bad if callee in b][:1]})")
    for what, bind in (("a local name", "        finish = A.engine.stop\n"),
                       ("a local name bound in two branches", "        if A.fila:\n            finish = A.engine.stop\n"
                                                             "        else:\n"
                                                             "            finish = A.engine.esperando_arquivo\n")):
        hidden = sources["comandos.py"].replace(
            "        cap = A.engine.stop()\n", bind + "        with A.engine.state_section():\n            cap = finish()\n", 1)
        bad, *_ = scan(dict(sources, **{"comandos.py": hidden}), order, before)
        check(hidden != sources["comandos.py"] and any("Engine.stop" in b for b in bad),
              f"with the Stop calling the engine's stop through {what} under the _qlock, the check fails "
              f"({[b for b in bad if 'Engine.stop' in b][:1]})")
    later = ("class App:\n    def change_queue(self, change):\n        pass\n    def f(self):\n"
             "        with self.fila_lock:\n            threading.Thread(target=lambda: self.change_queue(None)).start()\n")
    callers = caller_failures({"server.py": ast.parse(later)})
    check(len(callers) == 1 and "App.f" in callers[0],
          f"a lambda made under the fila_lock that calls the change_queue later, on its own thread, does not count "
          f"as holding it ({callers})")
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
    check(with_lock_holds_during_callback(trees["engine.py"]),
          "the engine's with_lock runs its callback inside the try that took the _lock, and releases it only in the "
          "finally")
    early = sources["engine.py"].replace(
        "                        try:\n                            return f(after)\n                        finally:\n"
        "                            self._lock.release()\n",
        "                        self._lock.release()\n                        return f(after)\n", 1)
    check(early != sources["engine.py"] and not with_lock_holds_during_callback(ast.parse(early)),
          "with the with_lock releasing the _lock before its callback, that check fails")
    check(section_yields_under_qlock(trees["engine.py"]),
          "the engine's state_section yields only inside a with of the _qlock, the lock its callers are counted as holding")
    bare = sources["engine.py"].replace("        with self._qlock:\n            yield\n", "        yield\n", 1)
    check(bare != sources["engine.py"] and not section_yields_under_qlock(ast.parse(bare)),
          "with the state_section yielding without the _qlock, that check fails")
    built = builder_failures(trees["engine.py"])
    check(not built, f"every Engine method that takes a builder calls it under the _lock and the _qlock, where it "
                     f"publishes ({built})")
    for what, old, new in (
            ("the trocar_fonte publishing the record it built on entry",
             "                novo = self.track = d.track = novo() if callable(novo) else novo\n",
             "                novo = self.track = d.track = initial\n"),
            ("the preparar publishing the record it built on entry",
             "                d.track = track = track() if callable(track) else initial\n",
             "                d.track = track = initial\n"),
            ("the trocar_fonte calling its builder but publishing the record it built on entry",
             "                novo = self.track = d.track = novo() if callable(novo) else novo\n",
             "                novo = self.track = d.track = (novo(), initial)[1] if callable(novo) else novo\n"),
            ("the trocar_fonte handing the record it built on entry to the _restart",
             "antes, leitor = self._restart(lambda: self._clamp(self.pos, initial), track=novo,",
             "antes, leitor = self._restart(lambda: self._clamp(self.pos, initial), track=initial,"),
            ("the load handing the record it built on entry to the _restart",
             "            antes, leitor = self._restart(self._clamp(start, initial), track=track,",
             "            antes, leitor = self._restart(self._clamp(start, initial), track=initial,")):
        early = sources["engine.py"].replace(old, new, 1)
        check(early != sources["engine.py"] and builder_failures(ast.parse(early)),
              f"with {what}, that check fails ({builder_failures(ast.parse(early))})")
    locked = sources["server.py"].replace(
        'self.engine.trocar_fonte(tr, lambda: dict(item, path=str(LIB / item["file"])))',
        'self.engine.trocar_fonte(tr, lambda: self.lib.update(item["id"]) and dict(item, path=str(LIB / item["file"])))',
        1)
    bad, *_ = scan(dict(sources, **{"server.py": locked}), order, before)
    check(locked != sources["server.py"] and any("lib_lock" in b for b in bad),
          f"with the download's builder taking the shelf's lock, which the engine runs under the _qlock, the order "
          f"check fails ({[b for b in bad if 'lib_lock' in b][:1]})")
    locked = sources["server.py"].replace(
        'return lambda: dict(it, path=str(LIB / it["file"]), **marca_auto(x))',
        'return lambda: self.lib.update(it["id"]) and dict(it, path=str(LIB / it["file"]), **marca_auto(x))', 1)
    bad, *_ = scan(dict(sources, **{"server.py": locked}), order, before)
    check(locked != sources["server.py"] and any("lib_lock" in b for b in bad),
          f"with the passage's builder, which fonte_de returns and the preparar runs under the _qlock, taking the "
          f"shelf's lock, the order check fails ({[b for b in bad if 'lib_lock' in b][:1]})")
    fallback = locked.replace("novo = self.fonte_de(seen)\n", "novo = self.fonte_de(seen) or None\n", 1)
    bad, *_ = scan(dict(sources, **{"server.py": fallback}), order, before)
    check(fallback != locked and any("lib_lock" in b for b in bad),
          f"and so it does with the builder reached through a fallback, fonte_de(seen) or None "
          f"({[b for b in bad if 'lib_lock' in b][:1]})")
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
    capture = "        with self._qlock:\n            if self._pronto is not None and self.track is not None"
    aliased = sources["engine.py"].replace(
        "        b = self._captura(frames)\n", "        capture = self._captura\n        b = capture(frames)\n", 1
    ).replace(capture, capture.replace("self._qlock", "self._lock, self._qlock"), 1)
    _, taken = audio_locks(aliased)
    check(aliased.count("capture = self._captura") == 1 and "_captura" in taken.get("_lock", ()),
          f"with the _mixa calling the _captura through a local alias and the _captura taking the _lock, the audio "
          f"check fails ({ {k: sorted(v) for k, v in taken.items()} })")
    bound = lock_bindings(trees)
    check(not bound, f"no lock of the model is bound to a local name in {', '.join(MODULES)}, so every with and "
                     f"acquire names its lock ({bound})")
    head = "        buf = np.zeros((frames, 2), np.float32)\n        b = self._captura(frames)\n"
    for what, alias in (("a local name", "        audio_lock = self._lock\n"),
                        ("a local name set in one branch",
                         "        audio_lock = self._lock if self.loop else self._qlock\n")):
        aliased = sources["engine.py"].replace(
            head, "        buf = np.zeros((frames, 2), np.float32)\n" + alias
            + "        with audio_lock:\n            pass\n        b = self._captura(frames)\n")
        bound = lock_bindings(dict(trees, **{"engine.py": ast.parse(aliased)}))
        check(aliased != sources["engine.py"] and len(bound) == 1,
              f"with the _mixa taking a lock through {what}, the binding check fails ({bound})")
    getter = sources["engine.py"].replace(
        head, "        buf = np.zeros((frames, 2), np.float32)\n        with self._mix_lock():\n            pass\n"
        "        b = self._captura(frames)\n").replace(
        "    def on_silent_stream(self, f):\n", "    def _mix_lock(self):\n        return self._lock\n\n"
        "    def on_silent_stream(self, f):\n")
    bound = lock_bindings(dict(trees, **{"engine.py": ast.parse(getter)}))
    check(getter.count("_mix_lock") == 2 and len(bound) == 1,
          f"with the _mixa taking the _lock from a getter, the binding check fails ({bound})")
    for what, taken in (("a lock chosen by an expression", "        with (self._lock if self.paused else self._qlock):\n"
                                                             "            pass\n"),
                        ("a lock acquired by hand", "        self._lock.acquire()\n        self._lock.release()\n")):
        mixed = sources["engine.py"].replace(head, "        buf = np.zeros((frames, 2), np.float32)\n" + taken
                                             + "        b = self._captura(frames)\n")
        bound = lock_bindings(dict(trees, **{"engine.py": ast.parse(mixed)}))
        check(mixed != sources["engine.py"] and len(bound) == 1,
              f"with the _mixa taking {what}, the binding check fails ({bound})")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
