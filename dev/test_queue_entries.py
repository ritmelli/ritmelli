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
CONTEXTS = {(ast.Assign, "targets"), (ast.Assign, "value"), (ast.AugAssign, "target"), (ast.AugAssign, "value"),
            (ast.Attribute, "value"), (ast.Call, "args"), (ast.Call, "func"), (ast.keyword, "value"),
            (ast.Compare, "left"), (ast.Compare, "comparators"), (ast.For, "iter"), (ast.For, "target"),
            (ast.comprehension, "iter"), (ast.comprehension, "target"), (ast.List, "elts"), (ast.Tuple, "elts"),
            (ast.UnaryOp, "operand"), (ast.BinOp, "left"), (ast.BinOp, "right"), (ast.BoolOp, "values"),
            (ast.If, "test"), (ast.While, "test"), (ast.IfExp, "test"), (ast.IfExp, "body"), (ast.IfExp, "orelse"), (ast.Return, "value"),
            (ast.Subscript, "value"), (ast.Dict, "values"), (ast.Lambda, "body"), (ast.FormattedValue, "value"),
            (ast.Expr, "value")}
ACCEPTED = ("read its fields or call its named methods there (no dunder), compare or test it, bind it to a plain name or "
            "to the queue's own attributes, pass it to or return it from a named function or a callback slot (at most "
            "four hand-offs in a row), hand it to a callee the check does not follow only as QUEUE_READERS, "
            "LIST_READERS, LIST_SORTERS and ENTRY_READERS list, loop over it with a plain name or an unpacked "
            "enumerate(...), unpack it from a call or a tuple of the same length, or copy it (list(), sorted(), a "
            "comprehension, a slice, {**x})")
APP_CLASSES = {"App", "Automatico", "Reserva", "Proximo"}
OWN_ATTRS = CONTAINERS | ENTRY_ATTRS | {"historico"}
MAX_HAND_OFFS = 4
QUEUE_READERS = {"len", "reversed", "list", "sorted", "tuple", "iter", "enumerate", "filter"}
LIST_READERS = QUEUE_READERS | {"next", "min", "max", "enumerate", "filter", "Thread"}
LIST_SORTERS = {"shuffle"}
ENTRY_READERS = {"dict", "id"}

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


def bound_to(func, taken):
    pairs = [(t.id, n.value) for n in ast.walk(func) if isinstance(n, ast.Assign) for t in n.targets
             if isinstance(t, ast.Name)]
    bound = set()
    while more := {t for t, v in pairs if t not in bound and (taken(v) or (isinstance(v, ast.Name) and v.id in bound))}:
        bound |= more
    return bound


def by_getattr(node):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
        return node.args[0], node.args[1].value
    return None


def thread_call(node):
    kws = {k.arg: k.value for k in node.keywords} if isinstance(node, ast.Call) else {}
    if "target" in kws and isinstance(kws.get("args"), ast.Tuple):
        return ast.copy_location(ast.Call(func=kws["target"], args=list(kws["args"].elts), keywords=[]), node)
    return node


def spread_dict(func, name):
    found = [n.value for n in own_nodes(func) if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    uses = [n for n in ast.walk(func) if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)]
    spreads = [k.value for n in own_nodes(func) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
               for k in n.keywords if k.arg is None]
    if len(found) == 1 and isinstance(found[0], ast.Dict) and all(isinstance(k, ast.Constant) for k in found[0].keys) \
            and all(any(u is v for v in spreads) for u in uses):
        return found[0]
    return None


def spread(func, call):
    out = []
    for k in call.keywords:
        d = spread_dict(func, k.value.id) if k.arg is None and isinstance(k.value, ast.Name) else None
        out += [(key.value, value) for key, value in zip(d.keys, d.values)] if d is not None else []
    return out


def fits(target, call):
    a = target.args
    names = [x.arg for x in a.posonlyargs + a.args]
    names = names[1:] if names[:1] == ["self"] else names
    if any(isinstance(x, ast.Starred) for x in call.args) or any(k.arg is None for k in call.keywords):
        return True
    required = names[:len(names) - len(a.defaults)]
    given = len(call.args) + sum(k.arg in required[len(call.args):] for k in call.keywords)
    return (len(call.args) <= len(names) or a.vararg is not None) and given >= len(required) and (
        a.kwarg is not None or all(k.arg in names + [x.arg for x in a.kwonlyargs] for k in call.keywords))


def imports_of(modules):
    known = {name for name, _ in modules}
    aliases, names = {}, {}
    for module, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    aliases.setdefault(module, {})[a.asname or a.name] = a.name.replace(".", "/") + ".py"
            elif isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    sub = f"{node.module.replace('.', '/')}/{a.name}.py"
                    if sub in known:
                        aliases.setdefault(module, {})[a.asname or a.name] = sub
                    else:
                        names.setdefault(module, {})[a.asname or a.name] = node.module.replace(".", "/") + ".py"
    return aliases, names


OWN_NODES = {}


def own_nodes(func, skip=frozenset()):
    if not skip and id(func) in OWN_NODES and OWN_NODES[id(func)][0] is func:
        return OWN_NODES[id(func)][1]
    out, todo = [], list(ast.iter_child_nodes(func))
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or id(node) in skip:
            continue
        out.append(node)
        todo.extend(ast.iter_child_nodes(node))
    if not skip:
        OWN_NODES[id(func)] = (func, out)
    return out


class Entries:
    def __init__(self, modules, attrs=CONTAINERS, owner_only=False):
        self.modules, self.attrs, self.owner_only = modules, attrs, owner_only
        self.params, self.cparams, self.walks, self.scopes, self.returns = {}, {}, {}, {}, set()
        self.creturns, self.refused, self.chains = set(), [], []
        self.slot_lambdas, self.names, self.parents = {}, set(), {}

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
        if isinstance(node, ast.IfExp):
            return self.is_container(node.body, scope) or self.is_container(node.orelse, scope)
        if isinstance(node, ast.NamedExpr):
            return self.is_container(node.value, scope)
        if isinstance(node, ast.Call) and called(node) in self.creturns:
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "copy"
                and not node.args):
            return self.is_container(node.func.value, scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("list", "sorted",
                                                                                              "reversed", "tuple", "iter"):
            return bool(node.args) and self.is_container(node.args[0], scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "filter":
            return len(node.args) == 2 and self.is_container(node.args[1], scope)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return any(self.is_entry(e, scope) for e in node.elts)
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
            if isinstance(node.func, ast.Name) and node.func.id in ("next", "min", "max") and node.args:
                return self.is_container(node.args[0], scope)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "pop":
                return self.is_container(node.func.value, scope)
        if isinstance(node, (ast.BoolOp, ast.IfExp)):
            parts = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
            return any(self.is_entry(p, scope) for p in parts)
        if isinstance(node, ast.NamedExpr):
            return self.is_entry(node.value, scope)
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
        size = None
        while size != (len(scope.containers), len(scope.entries)):
            size = len(scope.containers), len(scope.entries)
            for node in self.walk(func):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                    for root in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        pairs = list(zip(root.elts, node.value.elts)) if (
                            isinstance(root, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List))
                            and len(root.elts) == len(node.value.elts)) else [(root, node.value)]
                        for t, value in pairs:
                            if isinstance(t, (ast.Tuple, ast.List)) and self.is_container(value, scope):
                                for e in t.elts:
                                    if isinstance(e, ast.Starred):
                                        scope.containers |= set(targets(e.value))
                                    else:
                                        scope.entries |= set(targets(e))
                            elif isinstance(t, ast.Attribute) and t.attr in self.attrs:
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
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr in FILLERS and isinstance(node.func.value, ast.Name)
                      and any(self.is_entry(a, scope) or self.is_container(a, scope) for a in node.args)):
                    scope.containers.add(node.func.value.id)
        return scope

    def callback_slots(self, funcs, parents):
        out = {}
        for _, func, _, parent in funcs:
            scope = self.scope_of(func, parent, parents)
            for n in own_nodes(func):
                owner = isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and self.param_owner(func, n.func.id)
                got = {i for i, a in enumerate(n.args) if self.is_entry(a, scope) or self.is_container(a, scope)}                     if owner else set()
                if got:
                    out.setdefault((owner.name, n.func.id), set()).update(got)
        return out

    def param_owner(self, func, name):
        while func is not None and name not in self.param_names(func):
            func = self.parents.get(id(func))
        return func

    def bind_callbacks(self, funcs, parents, by_name, calls):
        changed = False
        for (owner, slot), got in self.callback_slots(funcs, parents).items():
            for target in by_name.get(owner, []):
                names = self.param_names(target)
                shift = 1 if names[:1] == ["self"] else 0
                at = names.index(slot) - shift
                for _, func, _, _ in funcs:
                    for node in calls[id(func)]:
                        if called(node) != owner:
                            continue
                        given = [k.value for k in node.keywords if k.arg == slot]
                        given += [node.args[at]] if 0 <= at < len(node.args) else []
                        for value in given:
                            if isinstance(value, ast.Lambda):
                                inner = [a.arg for a in value.args.args]
                                self.slot_lambdas[id(value)] = (value, {inner[i] for i in got if i < len(inner)}, func)
                            elif isinstance(value, (ast.Name, ast.Attribute)) and called(ast.Call(func=value)) in by_name:
                                name = called(ast.Call(func=value))
                                for cb in by_name[name]:
                                    inner = self.param_names(cb)
                                    off = 1 if isinstance(value, ast.Attribute) and inner[:1] == ["self"] else 0
                                    new = {inner[i + off] for i in got if i + off < len(inner)}
                                    new -= self.params.setdefault(name, set())
                                    if new:
                                        self.params[name] |= new
                                        changed = True
        return changed

    def lambda_refusals(self, module_of):
        out = []
        for lam, names, func in self.slot_lambdas.values():
            parent = {}
            for node in ast.walk(lam):
                for child in ast.iter_child_nodes(node):
                    parent[id(child)] = node
            for node in ast.walk(lam.body):
                if not (isinstance(node, ast.Name) and node.id in names):
                    continue
                up = parent.get(id(node))
                if node is lam.body or isinstance(up, (ast.Compare, ast.IfExp, ast.BoolOp)) or (
                        isinstance(up, ast.UnaryOp) and isinstance(up.op, ast.Not)):
                    continue
                out.append(f"{module_of.get(id(func), '?')}:{node.lineno}: an entry handed to a lambda in a callback "
                           f"slot ({ast.unparse(lam)[:60]}), in {func.name}, is not a form the check reads: the lambda "
                           f"only returns, compares or tests it")
        return out

    def bind_params(self, funcs, parents):
        self.parents, by_name = parents, {}
        classes = {c.name: [b.id for b in c.bases if isinstance(b, ast.Name)]
                   for _, tree in self.modules for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
        imports = imports_of(self.modules)
        for f in funcs:
            by_name.setdefault(f[1].name, []).append(f[1])
        calls = {id(f): [n for n in map(thread_call, self.walk(f)) if isinstance(n, ast.Call) and called(n) in by_name]
                 for _, f, _, _ in funcs}
        changed = True
        while changed:
            changed = False
            self.scopes.clear()
            for module, func, cls, parent in funcs:
                if not calls[id(func)]:
                    continue
                scope = self.scope_of(func, parent, parents)
                for node in calls[id(func)]:
                    name = called(node)
                    for target in self.callees_of(node, module, cls, scope, funcs, classes, imports) or by_name[name]:
                        names = self.param_names(target)
                        shift = 1 if isinstance(node.func, ast.Attribute) and names[:1] == ["self"] else 0
                        args = [(names[i + shift], a) for i, a in enumerate(node.args) if i + shift < len(names)]
                        args += [(kw.arg, kw.value) for kw in node.keywords if kw.arg in names]
                        args += [(k, v) for k, v in spread(func, node) if k in names]
                        for into, test in ((self.params, self.is_entry), (self.cparams, self.is_container)):
                            new = {n for n, a in args if test(a, scope)} - into.setdefault(name, set())
                            if new:
                                into[name] |= new
                                changed = True
            if not changed and self.bind_callbacks(funcs, parents, by_name, calls):
                changed = True

    def find_returns(self, funcs, parents):
        found, changed = False, True
        while changed:
            changed = False
            for _, func, _, parent in funcs:
                scope = self.scope_of(func, parent, parents)
                values = [n.value for n in own_nodes(func) if isinstance(n, ast.Return) and n.value is not None]
                for into, test in ((self.returns, self.is_entry), (self.creturns, self.is_container)):
                    if func.name not in into and any(test(v, scope) for v in values):
                        into.add(func.name)
                        self.scopes.clear()
                        changed = found = True
        return found

    def mutator(self, node, scope):
        taken = by_getattr(node)
        if taken:
            return taken[1] in MUTATORS and self.is_entry(taken[0], scope)
        return isinstance(node, ast.Attribute) and node.attr in MUTATORS and self.is_entry(node.value, scope)

    def escaping(self, module, func, scope):
        bound = bound_to(func, lambda v: self.mutator(v, scope))
        return [f"{module}:{n.lineno}: a mutator of an entry returned from a change_queue callback, in {func.name}"
                for n in ast.walk(func) if isinstance(n, ast.Return) and n.value is not None
                and (self.mutator(n.value, scope) or (isinstance(n.value, ast.Name) and n.value.id in bound))]

    def same_list(self, node, func, seen=frozenset()):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            node = node.value
        if isinstance(node, ast.Name):
            if node.id in seen:
                return False
            values = [n.value for n in own_nodes(func) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == node.id for t in n.targets)]
            return bool(values) and all(self.same_list(v, func, seen | {node.id}) for v in values)
        return isinstance(node, ast.Attribute) and node.attr in self.attrs

    def may_be_list(self, node, func, seen=frozenset()):
        if isinstance(node, ast.IfExp):
            return self.may_be_list(node.body, func, seen) or self.may_be_list(node.orelse, func, seen)
        if isinstance(node, ast.BoolOp):
            return any(self.may_be_list(v, func, seen) for v in node.values)
        if not isinstance(node, ast.Name):
            return isinstance(node, ast.Attribute) and node.attr in self.attrs
        if node.id in seen or node.id in self.param_names(func):
            return node.id not in seen
        for n in own_nodes(func):
            for t in n.targets if isinstance(n, ast.Assign) else []:
                pairs = list(zip(t.elts, n.value.elts)) if isinstance(t, ast.Tuple) and isinstance(
                    n.value, ast.Tuple) and len(t.elts) == len(n.value.elts) else [(t, n.value)]
                if any(isinstance(a, ast.Name) and a.id == node.id and self.may_be_list(b, func, seen | {node.id})
                       for a, b in pairs):
                    return True
        return False

    def identity_returns(self, funcs):
        return {func.name for _, func, _, _ in funcs
                if any(isinstance(n, ast.Return) and n.value is not None and self.same_list(n.value, func)
                       for n in own_nodes(func))}

    def app_ref(self, node, cls):
        if isinstance(node, ast.Attribute):
            v = node.value
            return (isinstance(v, ast.Name) and (v.id in APP_NAMES or (v.id == "self" and cls in APP_CLASSES))) or (
                isinstance(v, ast.Attribute) and v.attr == "app")
        if isinstance(node, ast.Subscript):
            return self.app_ref(node.value, cls)
        if isinstance(node, ast.IfExp):
            return self.app_ref(node.body, cls) or self.app_ref(node.orelse, cls)
        if isinstance(node, ast.BoolOp):
            return any(self.app_ref(v, cls) for v in node.values)
        return isinstance(node, (ast.Name, ast.Call, ast.ListComp, ast.GeneratorExp, ast.BinOp))

    @staticmethod
    def literal_ok(up, field, parent):
        outer = parent.get(id(up))
        if outer is None:
            return False
        holder, where = outer
        if (type(holder), where) in ((ast.Assign, "targets"), (ast.For, "target"), (ast.comprehension, "target")):
            return True
        if isinstance(holder, ast.Assign) and where == "value":
            t = holder.targets[0]
            return isinstance(t, (ast.Tuple, ast.List)) and len(t.elts) == len(up.elts)
        if isinstance(holder, ast.keyword) and holder.arg == "args":
            call = parent.get(id(holder))
            return call is not None and isinstance(call[0], ast.Call) and any(
                k.arg == "target" and isinstance(k.value, (ast.Name, ast.Attribute)) for k in call[0].keywords)
        return False

    def stored_form(self, node, up, field, parent, func, scope, cls):
        app = self.app_ref(node, cls)
        if isinstance(up, ast.Return) and self.same_list(node, func):
            return "the queue itself returned from a function"
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and any(self.app_ref(e, cls) for e in node.elts) and \
                not self.literal_ok(node, field, {**parent, id(node): (up, field)}):
            return "an entry or a container inside a list, a tuple or a set"
        if not app:
            return None
        if isinstance(up, ast.Assign) and field == "value":
            t = up.targets[0]
            if isinstance(t, ast.Attribute) and t.attr not in OWN_ATTRS:
                return "an entry or a container stored in an attribute that is not the queue's"
            if isinstance(t, ast.Subscript) and not self.is_container(t.value, scope):
                return "an entry or a container stored under a key or an index"
        if isinstance(up, ast.Call) and isinstance(up.func, ast.Lambda):
            return "an entry or a container passed to a lambda"
        if isinstance(up, ast.Call) and getattr(up.func, "id", None) == "enumerate":
            outer = parent.get(id(up))
            target = outer and getattr(outer[0], "target", None)
            if not (outer and outer[1] == "iter" and isinstance(target, ast.Tuple) and len(target.elts) == 2
                    and all(isinstance(e, ast.Name) for e in target.elts)):
                return "enumerate(...) without unpacking"
        if isinstance(up, (ast.List, ast.Tuple, ast.Set)) and not self.literal_ok(up, field, parent):
            return "an entry or a container inside a list, a tuple or a set"
        if isinstance(up, ast.Dict):
            key = next((k for k, v in zip(up.keys, up.values) if v is node), "absent")
            holder = parent.get(id(up))
            named = holder and isinstance(holder[0], ast.Assign) and isinstance(holder[0].targets[0], ast.Name)
            if key is not None and not (named and spread_dict(func, holder[0].targets[0].id) is up):
                return "an entry or a container inside a dict"
        return None

    def unfollowed(self, node, up, field, parent, func, scope):
        call = parent.get(id(up), (None,))[0] if isinstance(up, ast.keyword) else up
        if not (isinstance(call, ast.Call) and (up is not call or field == "args")) or node is call.func:
            return None
        name = called(call)
        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and \
                call.func.value.id in ("dict", "list") and name in MUTATORS | CHANGERS:
            return None
        if name in self.names or (isinstance(call.func, ast.Name) and self.param_owner(func, call.func.id)):
            return None
        if self.same_list(node, func):
            ok = name in QUEUE_READERS
        elif self.is_container(node, scope):
            ok = name in LIST_READERS or (name in LIST_SORTERS and not self.may_be_list(node, func))
        else:
            ok = name in ENTRY_READERS or (isinstance(call.func, ast.Attribute) and name in FILLERS)
        return None if ok else f"handed to {ast.unparse(call.func)[:40]}, a callee the check does not follow"

    def refused_form(self, node, up, field, callees, in_owner=False):
        if in_owner and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                isinstance(node.func.value, ast.Name) and node.func.value.id == "self" and node.func.attr in self.same:
            return f"a name bound to {node.func.attr}(), an App method that returns the queue itself"
        if isinstance(node, (ast.NamedExpr, ast.Starred)):
            return "an assignment expression or a starred value"
        if (type(up), field) not in CONTEXTS:
            return f"an entry or a container in a {type(up).__name__}"
        if isinstance(up, ast.Assign) and field == "value":
            t = up.targets[0]
            if len(up.targets) > 1:
                return "a chained assignment"
            if isinstance(t, (ast.Tuple, ast.List)) and not isinstance(node, ast.Call) and not (
                    isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == len(t.elts)
                    and not any(isinstance(e, ast.Starred) for e in t.elts)):
                return "unpacking the queue or the Mix"
        if isinstance(up, (ast.For, ast.comprehension)) and field == "iter" and not isinstance(up.target, ast.Name):
            return "a loop that unpacks the entries"
        if isinstance(up, ast.Attribute) and up.attr in MUTATORS | CHANGERS and id(up) not in callees:
            return "a mutator taken without its call"
        if isinstance(up, ast.Call) and isinstance(up.func, ast.Name) and up.func.id == "getattr":
            return "getattr"
        if isinstance(up, ast.Attribute) and up.attr.startswith("__") and up.attr.endswith("__"):
            return f"a dunder method ({up.attr})"
        return None

    def refusals(self, module, func, scope, in_owner=False, cls=None):
        parent, callees, out = {}, set(), []
        for node in own_nodes(func):
            callees |= {id(node.func)} if isinstance(node, ast.Call) else set()
            for field, value in ast.iter_fields(node):
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, ast.AST):
                        parent[id(child)] = (node, field)
        for node in own_nodes(func):
            if id(node) not in parent or not (self.is_entry(node, scope) or self.is_container(node, scope)):
                continue
            up, field = parent[id(node)]
            if (self.is_entry(up, scope) or self.is_container(up, scope)) and \
                    not isinstance(node, (ast.NamedExpr, ast.Starred)):
                continue
            form = self.refused_form(node, up, field, callees, in_owner) or \
                self.stored_form(node, up, field, parent, func, scope, cls) or \
                self.unfollowed(node, up, field, parent, func, scope)
            if form:
                out.append(f"{module}:{node.lineno}: {form} ({ast.unparse(up)[:60]}), in {func.name}, is not a form "
                           f"the check reads: {ACCEPTED}")
        return out

    def callees_of(self, call, module, cls, scope, funcs, classes, imports):
        f = call.func
        if isinstance(f, ast.Name):
            home = imports[1].get(module, {}).get(f.id, module)
            return [g for m, g, c, p in funcs if g.name == f.id and (
                (m == home and c is None and p is None) or (m == module and p is not None))]
        if not isinstance(f, ast.Attribute):
            return []
        v = f.value
        if isinstance(v, ast.Name) and v.id == "self" and cls:
            line, todo = set(), [cls]
            while todo:
                c = todo.pop()
                line.add(c)
                todo += [b for b in classes.get(c, ()) if b not in line]
            return [g for m, g, c, p in funcs if g.name == f.attr and c in line and p is None]
        if isinstance(v, ast.Name) and v.id in imports[0].get(module, {}):
            home = imports[0][module][v.id]
            return [g for m, g, c, p in funcs if g.name == f.attr and m == home and c is None and p is None]
        if self.is_entry(v, scope) or self.is_container(v, scope):
            return []
        return [g for m, g, c, p in funcs if g.name == f.attr and c is not None and p is None and fits(g, call)]

    def hand_offs(self, funcs, parents):
        classes = {c.name: [b.id for b in c.bases if isinstance(b, ast.Name)]
                   for _, tree in self.modules for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
        imports, edges = imports_of(self.modules), {}
        label = {id(f): (m, f"{c}.{f.name}" if c else f.name) for m, f, c, _ in funcs}
        for module, func, cls, parent in funcs:
            received = self.params.get(func.name, set()) | self.cparams.get(func.name, set())
            if not received:
                continue
            scope = self.scope_of(func, parent, parents)
            for call in map(thread_call, self.walk(func)):
                if not isinstance(call, ast.Call):
                    continue
                values = list(call.args) + [k.value for k in call.keywords if k.arg] + [v for _, v in spread(func, call)]
                if any(isinstance(v, ast.Name) and v.id in received for v in values):
                    for g in self.callees_of(call, module, cls, scope, funcs, classes, imports):
                        edges.setdefault(id(func), {}).setdefault(id(g), call.lineno)

        def deepest(fid, n):
            best = []
            for g in edges.get(fid, {}) if n <= MAX_HAND_OFFS + 1 else ():
                chain = deepest(g, n + 1)
                best = chain if len(chain) > len(best) else best
            return [fid] + best
        out = []
        for fid in edges:
            chain = deepest(fid, 1)
            names = [label[i][1] for i in chain]
            self.chains.append(names)
            if len(chain) - 1 > MAX_HAND_OFFS:
                out.append(f"{label[fid][0]}:{edges[fid][chain[1]]}: {' -> '.join(names)}, the queue or an entry handed "
                           f"on {len(chain) - 1} times in a row, is not a form the check reads: {ACCEPTED}")
        return out

    def write_target(self, node, scope):
        return isinstance(node, ast.Subscript) and self.is_entry(node.value, scope)

    def writes(self):
        funcs = self.functions()
        parents = {id(f): p for _, f, _, p in funcs}
        self.bind_params(funcs, parents)
        while self.find_returns(funcs, parents):
            self.bind_params(funcs, parents)
        allowed, skip = set(), set()
        for _, func, _, _ in funcs:
            names, lambdas = passed_to_change_queue(func)
            skip |= lambdas
            allowed |= {id(n) for n in ast.walk(func) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n is not func and n.name in names}
        out, self.same = [], self.identity_returns(funcs)
        self.names = {f.name for _, f, _, _ in funcs} | {c.name for _, tree in self.modules for c in ast.walk(tree)
                                                         if isinstance(c, ast.ClassDef)}
        self.refused += self.lambda_refusals({id(f): m for m, f, _, _ in funcs})
        self.refused += self.hand_offs(funcs, parents)
        for module, func, cls, parent in funcs:
            self.refused += self.refusals(module, func, self.scope_of(func, parent, parents), (module, cls) == OWNER,
                                          cls)
            if ((module, cls) == OWNER) != self.owner_only:
                continue
            if self.owner_only and (id(func) in allowed or func.name == "__init__"):
                out += self.escaping(module, func, self.scope_of(func, parent, parents))
                continue
            scope = self.scope_of(func, parent, parents)
            callees = {id(n.func) for n in ast.walk(func) if isinstance(n, ast.Call)}
            if self.owner_only:
                out += [f"{module}:{n.lineno}: a mutator of an entry returned from a change_queue callback, in "
                        f"{func.name}" for n in ast.walk(func)
                        if isinstance(n, ast.Lambda) and id(n) in skip and self.mutator(n.body, scope)]
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
                elif (isinstance(node, ast.Attribute) and node.attr in MUTATORS and id(node) not in callees
                      and self.is_entry(node.value, scope)):
                    hit = f"a captured .{node.attr}"
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and isinstance(node.func.value, ast.Name) and node.func.value.id == "dict"
                      and node.func.attr in MUTATORS and node.args and self.is_entry(node.args[0], scope)):
                    hit = f"dict.{node.func.attr}()"
                elif (taken := by_getattr(node)) and taken[1] in MUTATORS and self.is_entry(taken[0], scope):
                    hit = f"a .{taken[1]} taken by getattr"
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


def queue_expr(node, module, cls, known):
    if isinstance(node, ast.Name):
        return node.id in known
    if isinstance(node, ast.IfExp):
        return queue_expr(node.body, module, cls, known) or queue_expr(node.orelse, module, cls, known)
    if isinstance(node, ast.BoolOp):
        return any(queue_expr(v, module, cls, known) for v in node.values)
    if isinstance(node, ast.NamedExpr):
        return queue_expr(node.value, module, cls, known)
    return queue_attr(node, module, cls)


def direct_aliases(func, module, cls, known):
    out, before = set(known), -1
    assigns = [n for n in ast.walk(func) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
               and n.value is not None]
    while len(out) != before:
        before = len(out)
        for node in assigns:
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                pairs = list(zip(t.elts, node.value.elts)) if (
                    isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple)) else [(t, node.value)]
                for target, value in pairs:
                    if isinstance(target, ast.Name) and queue_expr(value, module, cls, out):
                        out.add(target.id)
    return out


class QueueChanges(ast.NodeVisitor):
    def __init__(self, module, params):
        self.module, self.params, self.cls, self.stack, self.found, self.passing = module, params, None, [], [], []
        self.callees, self.bound, self.funcs = set(), [], []

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
        self.bound.append(bound_to(node, self.changer))
        self.funcs.append(node)
        self.generic_visit(node)
        self.funcs.pop()
        self.bound.pop()
        self.stack.pop()

    def changer(self, node):
        taken = by_getattr(node)
        if taken:
            return taken[1] in CHANGERS and self.queue_ref(taken[0])
        return isinstance(node, ast.Attribute) and node.attr in CHANGERS and self.queue_ref(node.value)

    def escapes(self, node, value):
        if value is not None and (self.changer(value) or (isinstance(value, ast.Name) and self.bound
                                                          and value.id in self.bound[-1])):
            self.found.append(f"{self.module}:{node.lineno}: a changer of the queue returned from a change_queue "
                              f"callback")

    def visit_Return(self, node):
        if self.stack and self.stack[-1][0]:
            self.escapes(node, node.value)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        parent = self.stack[-1] if self.stack else None
        allowed = parent is not None and id(node) in parent[1][1]
        if allowed:
            self.escapes(node, node.body)
        self.stack.append((allowed, (set(), set()), parent[2] if parent else set()))
        self.generic_visit(node)
        self.stack.pop()

    def queue_ref(self, node):
        return queue_expr(node, self.module, self.cls, self.stack[-1][2] if self.stack else set())

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

    def visit_Attribute(self, node):
        if node.attr in CHANGERS and id(node) not in self.callees and self.queue_ref(node.value):
            self.flag(node, f"a captured .{node.attr} of the queue")
        self.generic_visit(node)

    def visit_Call(self, node):
        self.callees.add(id(node.func))
        if isinstance(node.func, ast.Attribute) and node.func.attr in CHANGERS and self.queue_ref(node.func.value):
            self.flag(node, f".{node.func.attr}() on the queue")
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "list" and node.func.attr in CHANGERS and node.args
                and self.queue_ref(node.args[0])):
            self.flag(node, f"list.{node.func.attr}() on the queue")
        if (taken := by_getattr(node)) and taken[1] in CHANGERS and self.queue_ref(taken[0]):
            self.flag(node, f"a .{taken[1]} of the queue taken by getattr")
        call = thread_call(node)
        slots = list(enumerate(call.args)) + [(kw.arg, kw.value) for kw in call.keywords if kw.arg]
        slots += spread(self.funcs[-1], call) if self.funcs else []
        self.passing += [(called(call), slot, isinstance(call.func, ast.Attribute)) for slot, a in slots
                         if self.queue_ref(a)]
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


def scan(sources, chains=None):
    modules = [(name, ast.parse(text, name)) for name, text in sources.items()]
    entries, owner = Entries(modules), Entries(modules, attrs=QUEUE, owner_only=True)
    entry_writes = entries.writes() + owner.writes()
    if chains is not None:
        chains += entries.chains + owner.chains
    params, changes, before = {}, [], None
    while params != before:
        before, passing, changes = params, [], []
        for name, tree in modules:
            v = QueueChanges(name, params)
            v.visit(tree)
            changes += v.found
            passing += v.passing
        params = queue_params(modules, passing)
    return entry_writes, changes + callback_escapes(modules), list(dict.fromkeys(entries.refused + owner.refused))


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
    "an entry in a conditional stored in a dict": (
        {"case.py": "def f(A, flag):\n    d = {'e': A.fila[0] if flag else None}\n    d['e']['audio'] = True\n"}, 1),
    "an entry in an or passed to a lambda": (
        {"case.py": "def f(A):\n    (lambda e: e.update(audio=True))(A.fila[0] or None)\n"}, 1),
    "an entry handed to a thread whose target is a lambda": (
        {"case.py": "def f(A):\n    threading.Thread(target=lambda x: x.update(audio=True), args=(A.fila[0],)).start()\n"},
        1),
    "an entry in a dict spread into a lambda": (
        {"case.py": "def f(A):\n    kw = {'e': A.fila[0]}\n    (lambda e: e.update(audio=True))(**kw)\n"}, 1),
    "an entry in a spread dict a nested function changes": (
        {"case.py": "def f(A, h):\n    kw = {'e': A.fila[0]}\n    def g():\n        kw['e']['audio'] = True\n    g()\n"
                    "    h(**kw)\n"}, 1),
    "an entry appended to a local list, then written through it": (
        {"case.py": "def f(A):\n    out = []\n    for x in A.mix:\n        out.append(x)\n    out[0]['seen'] = True\n"}, 1),
    "an entry handed to a callee the check does not follow": (
        {"case.py": "import operator\ndef f(A):\n    operator.setitem(A.fila[0], 'k', 1)\n"}, 1),
    "an entry a lambda in a callback slot changes": (
        {"case.py": "def concilia(A, closed=None):\n    for x in A.fila:\n        closed(x)\n"
                    "def f(A):\n    concilia(A, closed=lambda x: x.update(audio=True))\n"}, 1),
    "an entry a named callback in a slot changes": (
        {"case.py": "def mark(x):\n    x['k'] = 1\ndef concilia(A, closed=None):\n    for x in A.fila:\n        closed(x)\n"
                    "def f(A):\n    concilia(A, closed=mark)\n"}, 1),
    "an entry a callback of an enclosing function's slot changes": (
        {"case.py": "def mark(x):\n    x['k'] = 1\ndef order(items, tempo):\n    def first():\n"
                    "        return tempo(next(iter(items)))\n    return first()\ndef f(A):\n    order(A.mix, mark)\n"}, 1),
    "a copy of the queue a sorter reorders": (
        {"case.py": "import random\ndef f(A):\n    mine = [x for x in A.fila]\n    random.shuffle(mine)\n"}, 0),
    "an alias of the queue, bound in a tuple, that a sorter reorders": (
        {"case.py": "import random\ndef f(A, on):\n    q, o = A.fila, A.fila_ordem\n    if on:\n        q = list(q)\n"
                    "    random.shuffle(q)\n"}, 1),
    "a name rebound to a slice of itself": ({"case.py": "def f(A):\n    q = A.fila\n    q = q[1:]\n    return q\n"}, 0),
    "a dunder method called on an entry": (
        {"case.py": "def f(A):\n    for x in A.fila:\n        x.__init__(title='wrong')\n"}, 1),
    "an entry handed on four times, then changed": (
        {"case.py": "def e(x):\n    x['k'] = 1\ndef d(x):\n    e(x)\ndef c(x):\n    d(x)\ndef b(x):\n    c(x)\n"
                    "def a(x):\n    b(x)\ndef f(A):\n    a(A.fila[0])\n"}, 1),
    "an entry handed on five times, the last through another module": (
        {"comandos.py": "def g(x):\n    x['k'] = 1\n",
         "case.py": "import comandos as cmd\ndef e(x):\n    cmd.g(x)\ndef d(x):\n    e(x)\ndef c(x):\n    d(x)\n"
                    "def b(x):\n    c(x)\ndef a(x):\n    b(x)\ndef f(A):\n    a(A.fila[0])\n"}, 1),
    "a hand-off through self that stays in the App": (
        {"server.py": "class Other:\n    def d(self, x):\n        self.e(x)\n    def e(self, x):\n        self.g(x)\n"
                      "    def g(self, x):\n        pass\nclass App:\n    def a(self, x):\n        self.b(x)\n"
                      "    def b(self, x):\n        self.c(x)\n    def c(self, x):\n        self.d(x)\n"
                      "    def d(self, x):\n        self.e(x)\n    def e(self, x):\n        x['k'] = 1\n"
                      "    def f(self):\n        self.a(self.fila[0])\n"}, 1),
    "a method of the queue itself, not a hand-off": (
        {"server.py": "class Other:\n    def index(self, x):\n        self.g(x)\n    def g(self, x):\n        self.h(x)\n"
                      "    def h(self, x):\n        pass\nclass App:\n    def a(self, x):\n        self.b(x)\n"
                      "    def b(self, x):\n        self.c(x)\n    def c(self, x):\n        return self.fila.index(x)\n"
                      "    def f(self):\n        self.a(self.fila[0])\n"}, 0),
    "a method that cannot take the call's arguments, not a hand-off": (
        {"case.py": "class Proximo:\n    def resolve(self, x, error):\n        pass\nclass Engine:\n"
                    "    def resolve(self, d=None):\n        self.m(d)\n    def m(self, d):\n        self.n(d)\n"
                    "    def n(self, d):\n        pass\ndef c(x, g):\n    g.resolve(x, None)\ndef b(x, g):\n    c(x, g)\n"
                    "def a(x, g):\n    b(x, g)\ndef f(A, g):\n    a(A.fila[0], g)\n"}, 0),
    "an entry stored in an attribute that is not the queue's": (
        {"automatico.py": "class Automatico:\n    def f(self):\n        self.saved = self.app.fila[0]\n"}, 0),
    "an entry stored under a key": ({"case.py": "def f(A, d):\n    d['e'] = A.fila[0]\n"}, 0),
    "the queue inside a dict": ({"case.py": "def f(A):\n    d = {'q': A.fila}\n    return d\n"}, 0),
    "the queue inside a list": ({"case.py": "def f(A):\n    box = [A.fila]\n    return box\n"}, 0),
    "the queue inside a tuple": ({"case.py": "def f(A):\n    return (A.fila, 1)\n"}, 0),
    "an entry passed to a lambda": ({"case.py": "def f(A):\n    (lambda e: e.update(audio=True))(A.fila[0])\n"}, 0),
    "the queue passed to a lambda": ({"case.py": "def f(A):\n    (lambda q: q.clear())(A.fila)\n"}, 0),
    "enumerate without unpacking": ({"case.py": "def f(A):\n    for pair in enumerate(A.fila):\n"
                                                "        pair[1]['audio'] = True\n"}, 0),
    "a function of another module that returns the queue itself": (
        {"case.py": "def entries(A):\n    return A.fila\ndef f(A):\n    entries(A).clear()\n"}, 0),
    "an entry the App spreads into a call through a dict": (
        {"server.py": "class App:\n    def g(self, entrada=None):\n        entrada['k'] = 1\n    def f(self):\n"
                      "        x = self.fila[0]\n        kw = {'entrada': x}\n        self.g(**kw)\n"}, 1),
    "an entry the App hands to a thread's target": (
        {"server.py": "class App:\n    def g(self, x):\n        x['k'] = 1\n    def f(self):\n"
                      "        threading.Thread(target=self.g, args=(self.fila[0],)).start()\n"}, 1),
    "an entry a helper returns, passed to another that writes it": (
        {"case.py": "def head(A):\n    return A.fila[0]\ndef rewrite(entry):\n    entry.update(audio=True)\n"
                    "def f(A):\n    rewrite(head(A))\n"}, 1),
    "an entry of the queue a helper returns": (
        {"case.py": "def entries(A):\n    return A.fila\ndef f(A):\n    entries(A)[0].update(audio=True)\n"}, 1),
    "the head of the queue by index": ({"case.py": "def f(A):\n    A.fila[0]['fixa'] = True\n"}, 1),
    "an entry taken by next(iter())": ({"case.py": "def f(A):\n    x = next(iter(A.fila))\n    x.update(title='New')\n"}, 1),
    "an entry of a container chosen by a conditional": (
        {"case.py": "def f(A, flag):\n    q = A.fila if flag else A.mix\n    q[0].update(title='New')\n"}, 1),
    "an entry bound by an assignment expression": (
        {"case.py": "def f(A):\n    if entry := next(iter(A.fila), None):\n        entry['audio'] = True\n"}, 1),
    "an entry of a filtered queue": (
        {"case.py": "def f(A):\n    for x in filter(None, A.fila):\n        x['fixa'] = True\n"}, 1),
    "an entry wrapped in a list": ({"case.py": "def f(A):\n    y = [A.fila[0]]\n    y[0]['fixa'] = True\n"}, 1),
    "an entry written on an assignment expression": (
        {"case.py": "def f(A):\n    (e := A.fila[0]).update(audio=True)\n"}, 1),
    "a captured update of an entry": (
        {"case.py": "def f(A):\n    rewrite = A.fila[0].update\n    rewrite(audio=True)\n"}, 1),
    "a mutator of an entry returned from the App's change": (
        {"server.py": "class App:\n    def f(self):\n        def ch():\n            return self.fila[0].update\n"
                      "        self.change_queue(ch)(audio=True)\n"}, 1),
    "a mutator of an entry returned through a chain of names from the App's change": (
        {"server.py": "class App:\n    def f(self):\n        def ch():\n            u = self.fila[0].update\n"
                      "            w = u\n            return w\n        self.change_queue(ch)(audio=True)\n"}, 1),
    "a mutator of an entry returned by a lambda passed as the App's change": (
        {"server.py": "class App:\n    def f(self):\n        self.change_queue(lambda: self.fila[0].update)(audio=True)\n"},
        1),
    "an update of an entry called in a lambda passed as the App's change": (
        {"server.py": "class App:\n    def f(self):\n        self.change_queue(lambda: self.fila[0].update(audio=True))\n"},
        0),
    "an update of an entry taken by getattr": (
        {"case.py": "def f(A):\n    getattr(A.fila[0], 'update')(audio=True)\n"}, 1),
    "an entry of a queue bound inline": ({"case.py": "def f(A):\n    (q := A.fila)[0]['audio'] = True\n"}, 1),
    "an entry found by next()":({"case.py": "def f(A, q):\n    x = next((y for y in A.fila if y['qid'] == q), None)"
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
    "an entry unpacked from the queue": ({"case.py": "def f(A):\n    x, _ = A.fila\n    x.update(a=1)\n"}, 1),
    "an entry from a starred unpacking of the queue": (
        {"case.py": "def f(A):\n    x, *_ = A.fila\n    x['k'] = 1\n"}, 1),
    "the rest of the Automatico's Mix from a starred unpacking": (
        {"automatico.py": "class Automatico:\n    def f(self):\n        _, *rest = self._mix\n"
                          "        rest[0]['ordem'] = 1\n"}, 1),
    "an entry of the Mix from unpacking": ({"case.py": "def f(A):\n    x, _ = A.mix[0], None\n    x.update(a=1)\n"}, 1),
    "an entry passed to a method whose namesake in another class takes more arguments": (
        {"case.py": "class Auto:\n    def refuse(self, x):\n        return x['qid']\nclass Page:\n"
                    "    def refuse(self, i, message):\n        return message.count('\\n', 0, i)\n"
                    "def f(A, auto):\n    auto.refuse(A.fila[0])\n"}, 0),
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
    "the queue handed to a callee the check does not follow": (
        {"case.py": "import random\ndef f(A):\n    random.shuffle(A.fila)\n"}, 1),
    "the queue a thread's target clears": (
        {"case.py": "def cut(q):\n    q.clear()\ndef f(A):\n    threading.Thread(target=cut, args=(A.fila,)).start()\n"}, 1),
    "the queue a dict spread as **name hands to a helper that clears it": (
        {"case.py": "def cut(q=None):\n    q.clear()\ndef f(A):\n    kw = {'q': A.fila}\n    cut(**kw)\n"}, 1),
    "the queue two relays hand to a helper that clears it": (
        {"case.py": "def cut(q):\n    q.clear()\ndef r2(q):\n    cut(q)\ndef r1(q):\n    r2(q)\ndef f(A):\n    r1(A.fila)\n"}, 1),
    "a dunder method called on the queue": ({"case.py": "def f(A):\n    A.fila.__setitem__(0, {})\n"}, 1),
    "a name bound to an App method that returns the queue itself": (
        {"server.py": "class App:\n    def live_queue(self):\n        return self.fila\n    def f(self):\n"
                      "        live = self.live_queue()\n        live.clear()\n"}, 1),
    "a name bound to an App method that returns a copy of the queue": (
        {"server.py": "class App:\n    def queue_copy(self):\n        return list(self.fila)\n    def f(self):\n"
                      "        live = self.queue_copy()\n        live.clear()\n"}, 0),
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
    "a queue chosen by a conditional": (
        {"case.py": "def f(A, flag):\n    q = A.fila if flag else A.fila_ordem\n    q.clear()\n"}, 1),
    "a queue chosen by a conditional, inline": (
        {"case.py": "def f(A, flag):\n    (A.fila if flag else A.fila_ordem).clear()\n"}, 1),
    "a captured append of the queue": ({"case.py": "def f(A, x):\n    add = A.fila.append\n    add(x)\n"}, 1),
    "a changer of the queue returned from the change": (
        {"case.py": "def f(A, x):\n    def ch():\n        return A.fila.remove\n    A.change_queue(ch)(x)\n"}, 1),
    "a changer of the queue returned through a name from the change": (
        {"case.py": "def f(A, x):\n    def ch():\n        rm = A.fila.remove\n        return rm\n"
                    "    A.change_queue(ch)(x)\n"}, 1),
    "a changer of the queue returned through a chain of names from the change": (
        {"case.py": "def f(A, x):\n    def ch():\n        rm = A.fila.remove\n        r = rm\n        return r\n"
                    "    A.change_queue(ch)(x)\n"}, 1),
    "a changer of the queue returned by a lambda passed as the change": (
        {"case.py": "def f(A, x):\n    A.change_queue(lambda: A.fila.remove)(x)\n"}, 1),
    "a changer of the queue called inside the change, its result returned": (
        {"case.py": "def f(A, x):\n    def ch():\n        return A.fila.remove(x)\n    A.change_queue(ch)\n"}, 0),
    "a captured append of the queue inside the change": (
        {"case.py": "def f(A, x):\n    def ch():\n        add = A.fila.append\n        add(x)\n    A.change_queue(ch)\n"},
        0),
    "an append of the queue taken by getattr": ({"case.py": "def f(A, x):\n    getattr(A.fila, 'append')(x)\n"}, 1),
    "list.append on the queue": ({"case.py": "def f(A, x):\n    list.append(A.fila, x)\n"}, 1),
    "a queue bound by an assignment expression": ({"case.py": "def f(A):\n    if q := A.fila:\n        q.clear()\n"}, 1),
    "another class's own fila": ({"fx.py": "class Fx:\n    def f(self):\n        self.fila = []\n"}, 0),
    "the App building its queue in __init__": (
        {"server.py": "class App:\n    def __init__(self):\n        self.fila = []\n"}, 0),
}


REFUSED_FORMS = {
    "an entry bound by an assignment expression", "an entry written on an assignment expression",
    "a captured update of an entry", "a mutator of an entry returned from the App's change",
    "a mutator of an entry returned through a chain of names from the App's change",
    "a mutator of an entry returned by a lambda passed as the App's change", "an update of an entry taken by getattr",
    "an entry of a queue bound inline", "an annotated alias", "an entry unpacked from the queue",
    "an entry from a starred unpacking of the queue", "the rest of the Automatico's Mix from a starred unpacking",
    "a captured append of the queue", "a changer of the queue returned from the change",
    "a changer of the queue returned through a name from the change",
    "a changer of the queue returned through a chain of names from the change",
    "a changer of the queue returned by a lambda passed as the change",
    "a captured append of the queue inside the change", "an append of the queue taken by getattr",
    "a queue bound by an assignment expression", "a name bound to an App method that returns the queue itself",
    "an entry wrapped in a list", "an entry stored in an attribute that is not the queue's",
    "an entry stored under a key", "the queue inside a dict", "the queue inside a list", "the queue inside a tuple",
    "an entry passed to a lambda", "the queue passed to a lambda", "enumerate without unpacking",
    "a function of another module that returns the queue itself", "an entry of the queue a helper returns",
    "an entry handed on five times, the last through another module", "a dunder method called on an entry",
    "a dunder method called on the queue", "an entry in a conditional stored in a dict",
    "an entry in an or passed to a lambda", "an entry handed to a thread whose target is a lambda",
    "an entry in a dict spread into a lambda", "an entry in a spread dict a nested function changes",
    "an entry handed to a callee the check does not follow", "an entry a lambda in a callback slot changes",
    "the queue handed to a callee the check does not follow",
    "an alias of the queue, bound in a tuple, that a sorter reorders"}


def production_sources():
    paths = sorted(ROOT.glob("*.py")) + sorted((ROOT / "microfone").glob("*.py"))
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in paths}


def main():
    found, _, _ = scan({"automatico.py": BASE_USES})
    lines = sorted(int(w.split(":")[1]) for w in found)
    check(lines == [9, 15, 17], f"the check flags the three writes the base made outside the App (the Mix numbering, "
                                f"the audio mark and the update of _poe_versao): {found}")
    for name, table, pick in (("entry", ENTRY_FORMS, 0), ("queue", QUEUE_FORMS, 1)):
        for what, (sources, expected) in table.items():
            result = scan(sources)
            got, refused = result[pick], result[2]
            if what in REFUSED_FORMS:
                check(bool(refused), f"the {name} check refuses {what} as a form it does not read ({refused[:1]})")
            else:
                check(len(got) == expected and not refused,
                      f"the {name} check {'flags' if expected else 'accepts'} {what} ({got}{refused[:1]})")
    sources = production_sources()
    direct = sources["server.py"].replace("self.change_queue(swap_entries)", "swap_entries()")
    got, _, _ = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and len(got) == 1,
          f"with the App's audio version writing the entries without change_queue, the check fails ({got})")
    captured = sources["automatico.py"].replace(
        "        for x in A.fila:\n            vistas |= music.chaves_musica(x)\n",
        "        for x in A.fila:\n            mark = x.update\n            mark(seen=True)\n"
        "            vistas |= music.chaves_musica(x)\n", 1)
    _, _, got = scan(dict(sources, **{"automatico.py": captured}))
    check(captured != sources["automatico.py"] and bool(got),
          f"with the Automatico writing a queue entry through its captured update, the check refuses the form ({got})")
    direct = sources["server.py"].replace("self.change_queue(swap_entries)",
                                          "swap_entries()\n        self.change_queue(swap_entries)")
    _, got, _ = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and len(got) == 1,
          f"with the App's audio version also calling its change_queue callback by itself, the check fails ({got})")
    direct = sources["server.py"].replace("self.change_queue(replace_queue)", "replace_queue()")
    _, got, _ = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and len(got) == 1,
          f"with the App replacing its queue without change_queue, the check fails ({got})")
    direct = sources["server.py"].replace("        self.change_queue(remove_entry)\n",
                                          "        self.change_queue(remove_entry)\n"
                                          "        if q := self.fila:\n            q.remove(x)\n", 1)
    _, _, got = scan(dict(sources, **{"server.py": direct}))
    check(direct != sources["server.py"] and bool(got),
          f"with the App removing from its queue through an assignment expression, the check refuses the form ({got})")
    escaped = sources["server.py"].replace(
        "        def remove_entry():\n            self.fila.remove(x)\n", "        def remove_entry():\n", 1).replace(
        "                self.fila_ordem.remove(x)\n        self.change_queue(remove_entry)\n",
        "                self.fila_ordem.remove(x)\n            return self.fila.remove\n"
        "        self.change_queue(remove_entry)(x)\n", 1)
    _, _, got = scan(dict(sources, **{"server.py": escaped}))
    check(escaped.count("return self.fila.remove") == 1 and bool(got),
          f"with the App's remove_from_queue returning the queue's remove from its change and calling it after, the "
          f"check refuses the form ({got})")
    chains = []
    for what, module, old, new, pick in (
            ("the Automatico writing the window it gathered", "automatico.py",
             "        parecidas = {id(c) for c in janela}\n",
             "        janela[0]['seen'] = True\n        parecidas = {id(c) for c in janela}\n", 0),
            ("the Automatico numbering the free Mix it gathered", "automatico.py",
             "        mix = self._livres()\n", "        mix = self._livres()\n        for m in mix:\n"
                                                "            m['ordem'] = 0\n", 0),
            ("the App shuffling its queue itself", "server.py", "random.shuffle(meus)", "random.shuffle(fila)", 2)):
        changed = sources[module].replace(old, new, 1)
        got = scan(dict(sources, **{module: changed}))[pick]
        check(changed != sources[module] and bool(got), f"with {what}, the check fails ({got[:1]})")
    writes, changes, refused = scan(sources, chains)
    deep = max(chains, key=len)
    check(len(deep) - 1 == MAX_HAND_OFFS, f"the deepest hand-off in the code is the {MAX_HAND_OFFS} the check allows "
                                         f"({' -> '.join(deep)})")
    check(not refused, f"the {len(sources)} modules use only the forms the check reads ({refused[:3]})")
    check(not writes, f"no module writes an entry of the queue or the Mix outside the {OWNER[1]} ({writes})")
    check(not changes, f"every change to the queue in the {len(sources)} modules goes through change_queue "
                       f"({changes})")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
