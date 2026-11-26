r"""Confere que os ganchos do engine.py para o modulo opcional de fora do repo nao crescem. O modulo e o que o
engine.py importa num try com o except ImportError que o troca por None; o nome dele sai do proprio engine.py.
Gancho, para esta conta: cada nome diferente do engine.py que tem o nome do modulo como uma das palavras dele
(funcao, metodo, atributo, constante, variavel), cada atributo lido direto do modulo e cada atributo lido de um
objeto com o nome dele, tambem por um apelido local (x = self._modulo) e pelo getattr. A conta tem de dar o TETO:
acima dele, entrou gancho novo; abaixo, saiu um, e o TETO desce junto no mesmo PR. Gancho com nome que nao lembra o
modulo escapa da conta, e a regra vale igual (docs/arquitetura/fx.md). So a biblioteca padrao, lendo o texto do
engine.py: nada e importado nem tocado.

The same ceiling holds the server routes that only that module calls: the OUT_OF_REPO group of permissao.py, read
from its text too, has to have exactly ROUTES_CEILING entries. A new route for the module goes through the ones already
there; one that leaves lowers the ceiling in the same PR.

It also holds the seams between the modules at the repo root, each count against its ceiling: above it, a new reach
went in; below it, the PR lowers the ceiling with it. It counts the reaches into the private names of the engine
(Engine, MockEngine and engine.py's own), of the App (and server.py's own) and of the Automatico (and automatico.py's
own) from the other root modules, the reaches into the Library's from the rest of server.py, and the direct writes to
the public state of the App and of the engine from outside their modules. What is a reach or a write is what the cases
below say: the ones counted, the ones not counted and the known misses (#232). Every number goes to the PR summary.

    python dev/testa_ganchos.py

Sai 1 se uma das contas nao bate."""
import ast
import functools
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TETO = 24
ROUTES_CEILING = 3
# the reaches into the engine's insides from the modules at the root, other than engine.py; it only goes down
ENGINE_CEILING = 0
APP_CEILING = 0
AUTOMATICO_CEILING = 0
LIBRARY_CEILING = 0
APP_WRITES_CEILING = 27
ENGINE_WRITES_CEILING = 16


def opcionais(arvore):
    """Os modulos do try/except ImportError do topo que viram None. Onde o de fora roda, ele esta ao lado do codigo:
    por isso nao vale olhar se o arquivo existe."""
    achados = set()
    for no in arvore.body:
        if not isinstance(no, ast.Try):
            continue
        importados = {a.asname or a.name for i in no.body if isinstance(i, ast.Import) for a in i.names}
        for h in no.handlers:
            nomes = {h.type.id} if isinstance(h.type, ast.Name) else (
                {e.id for e in h.type.elts if isinstance(e, ast.Name)} if isinstance(h.type, ast.Tuple) else set())
            if not nomes & {"ImportError", "ModuleNotFoundError"}:
                continue
            for s in h.body:
                if (isinstance(s, ast.Assign) and isinstance(s.value, ast.Constant) and s.value.value is None):
                    achados |= {t.id for t in s.targets if isinstance(t, ast.Name) and t.id in importados}
    return achados


def ganchos(arvore, modulo):
    def tem(nome):  # o nome do modulo como palavra do identificador (_x_voz, X_FOLGA_S, X), nao pedaco de outra
        return modulo.lower() in (p.lower() for p in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", nome))

    def nome_de(no):
        return no.id if isinstance(no, ast.Name) else no.attr if isinstance(no, ast.Attribute) else ""

    achados = set()
    escopos = [arvore] + [f for f in ast.walk(arvore) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for escopo in escopos:
        # o apelido local de uma funcao (x = self._modulo): o que se le ou chama nele conta como no original
        apelido = {} if escopo is arvore else {
            a.targets[0].id: nome_de(a.value) for a in ast.walk(escopo)
            if isinstance(a, ast.Assign) and len(a.targets) == 1 and isinstance(a.targets[0], ast.Name)
            and nome_de(a.value) and tem(nome_de(a.value))}

        def dono(no):
            d = nome_de(no)
            d = apelido.get(d, d) if isinstance(no, ast.Name) else d
            return d if d and tem(d) else ""

        for no in ast.walk(escopo):
            if isinstance(no, ast.Name) and tem(no.id):
                achados.add(no.id)
            elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and tem(no.name):
                achados.add(no.name)
            elif isinstance(no, ast.arg) and tem(no.arg):
                achados.add(no.arg)
            elif isinstance(no, ast.Attribute):
                if tem(no.attr):
                    achados.add(no.attr)
                elif dono(no.value):
                    achados.add(f"{dono(no.value)}.{no.attr}")
            elif (isinstance(no, ast.Call) and nome_de(no.func) in ("getattr", "hasattr", "setattr")
                  and len(no.args) >= 2 and isinstance(no.args[1], ast.Constant) and isinstance(no.args[1].value, str)):
                attr = no.args[1].value  # a mesma regra do acesso direto
                if tem(attr):
                    achados.add(attr)
                elif dono(no.args[0]):
                    achados.add(f"{dono(no.args[0])}.{attr}")
    return achados


def out_of_repo_routes(tree):
    """The (method, route) pairs of the OUT_OF_REPO tuple in permissao.py, or None when it isn't a literal tuple."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OUT_OF_REPO"
                                                 for t in node.targets)):
            try:
                routes = ast.literal_eval(node.value)
            except ValueError:
                return None
            return routes if isinstance(routes, tuple) else None
    return None


def is_private(name):
    return name.startswith("_") and not name.startswith("__")


def class_level(body):
    for s in body:
        yield s
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(s, field, None)
            if isinstance(inner, list):
                yield from class_level(inner)
        for block in getattr(s, "handlers", []) + getattr(s, "cases", []):
            yield from class_level(block.body)


def bound_names(target):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for t in target.elts:
            yield from bound_names(t)
    elif isinstance(target, ast.Starred):
        yield from bound_names(target.value)


def assigned_targets(statement):
    if isinstance(statement, ast.Assign):
        return statement.targets
    return [statement.target] if isinstance(statement, ast.AnnAssign) else []


ATTR_FUNCTIONS = ("getattr", "setattr", "hasattr", "delattr")
LITERAL_SEQUENCES = (ast.Tuple, ast.List, ast.Set)


OBJECT_METHODS = {"getattr": "__getattribute__", "setattr": "__setattr__", "delattr": "__delattr__"}


def attr_function(func, names=ATTR_FUNCTIONS):
    if isinstance(func, ast.Name):
        return func.id in names
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return False
    if func.value.id == "builtins":
        return func.attr in names
    return func.value.id == "object" and func.attr in {OBJECT_METHODS.get(n) for n in names}


def call_args(call):
    out = []
    for a in call.args:
        if isinstance(a, ast.Starred) and isinstance(a.value, LITERAL_SEQUENCES):
            out += a.value.elts
        else:
            out.append(a)
    return out


def has_base(c):
    return any(not (isinstance(b, ast.Name) and b.id == "object") for b in c.bases)


RECEIVERS = frozenset(("self", "cls"))


def method_receivers(method):
    if any(attr_function(d, ("staticmethod",)) for d in method.decorator_list):
        return frozenset()
    first_parameter = (method.args.posonlyargs + method.args.args)[:1]
    return frozenset(p.arg for p in first_parameter) & RECEIVERS


def nodes_with_own_receivers(node, receivers):
    for child in ast.iter_child_nodes(node):
        inner = receivers
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = child.args
            inner = receivers - {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg] if p}
        yield child, receivers
        yield from nodes_with_own_receivers(child, inner)


def string_literals(value):
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        yield value.value
    elif isinstance(value, LITERAL_SEQUENCES):
        for e in value.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                yield e.value


SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def nodes_with_scope(node, scope):
    for child in ast.iter_child_nodes(node):
        yield child, scope
        yield from nodes_with_scope(child, child if isinstance(child, SCOPES) else scope)


class Assignments:
    def __init__(self, tree):
        self.values = {}
        self.enclosing = {}
        for n, scope in nodes_with_scope(tree, tree):
            if isinstance(n, SCOPES):
                self.enclosing[id(n)] = scope
            for target in assigned_targets(n):
                if isinstance(target, ast.Name):
                    self.values.setdefault((id(scope), target.id), []).append(n.value)

    def single_value(self, scope, name):
        while scope is not None:
            values = self.values.get((id(scope), name))
            if values is not None:
                return values[0] if len(values) == 1 else None
            scope = self.enclosing.get(id(scope))
            while isinstance(scope, ast.ClassDef):
                scope = self.enclosing.get(id(scope))
        return None


def dict_keys(value):
    if isinstance(value, ast.Dict):
        return [k for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if (isinstance(value, ast.DictComp) and len(value.generators) == 1 and isinstance(value.key, ast.Name)
            and isinstance(value.generators[0].target, ast.Name) and value.key.id == value.generators[0].target.id
            and isinstance(value.generators[0].iter, LITERAL_SEQUENCES)):
        return [e for e in value.generators[0].iter.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def literal_items(iterable, scope, assignments):
    if isinstance(iterable, LITERAL_SEQUENCES):
        return iterable.elts
    method = None
    if (isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Attribute) and not iterable.args
            and iterable.func.attr in ("items", "keys")):
        method, iterable = iterable.func.attr, iterable.func.value
    if isinstance(iterable, ast.Name):
        iterable = assignments.single_value(scope, iterable.id)
        if method is None and isinstance(iterable, LITERAL_SEQUENCES):
            return iterable.elts
    keys = dict_keys(iterable) if iterable is not None else None
    if keys is None:
        return None
    return [ast.Tuple(elts=[k, ast.Constant(None)]) for k in keys] if method == "items" else keys


def loop_variable_names(tree):
    out = {}
    assignments = Assignments(tree)

    def pairs(target, item):
        if isinstance(target, ast.Name):
            yield target.id, item
        elif (isinstance(target, (ast.Tuple, ast.List)) and isinstance(item, (ast.Tuple, ast.List))
              and len(target.elts) == len(item.elts)):
            for t, v in zip(target.elts, item.elts):
                yield from pairs(t, v)

    def bind(target, iterable, body, scope):
        items = literal_items(iterable, scope, assignments)
        if items is None:
            return
        values = {}
        for item in items:
            for name, v in pairs(target, item):
                values.setdefault(name, []).extend(string_literals(v) if isinstance(v, ast.Constant) else [])
        for part in body:
            for n in ast.walk(part):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and values.get(n.id):
                    out[id(n)] = values[n.id]
    for no, scope in nodes_with_scope(tree, tree):
        if isinstance(no, (ast.For, ast.AsyncFor)):
            bind(no.target, no.iter, no.body + no.orelse, scope)
        elif isinstance(no, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            elts = [no.key, no.value] if isinstance(no, ast.DictComp) else [no.elt]
            for i, g in enumerate(no.generators):
                bind(g.target, g.iter, elts + g.ifs + no.generators[i + 1:], scope)
    return out


def attr_call_names(call, loop_names, functions=ATTR_FUNCTIONS):
    if not (isinstance(call, ast.Call) and attr_function(call.func, functions) and len(call_args(call)) >= 2):
        return []
    name = call_args(call)[1]
    return list(string_literals(name)) if isinstance(name, ast.Constant) else loop_names.get(id(name), [])


def instance_stores(method):
    loop_names = loop_variable_names(method)
    for n, receivers in nodes_with_own_receivers(method, method_receivers(method)):
        if (isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name)
                and n.value.id in receivers):
            yield n.attr
        elif (isinstance(n, ast.Call) and attr_function(n.func, ("setattr",)) and call_args(n)
              and isinstance(call_args(n)[0], ast.Name) and call_args(n)[0].id in receivers):
            yield from attr_call_names(n, loop_names)


def class_privates(c):
    out = set()
    for s in class_level(c.body):
        if isinstance(s, ast.ClassDef):
            out.add(s.name)
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(s.name)
            out |= set(instance_stores(s))
        for target in assigned_targets(s):
            out |= set(bound_names(target))
            if isinstance(target, ast.Name) and target.id == "__slots__" and s.value is not None:
                out |= set(string_literals(s.value))
    return {n for n in out if is_private(n)}


def privates(tree, classes):
    return set().union(*(class_privates(c) for c in tree.body if isinstance(c, ast.ClassDef) and c.name in classes))


def module_reaches(module, tree, names):
    out = []
    own_names_by_node = {}
    for c in ast.walk(tree):
        if isinstance(c, ast.ClassDef):
            own_names = set() if has_base(c) else class_privates(c)
            for s in class_level(c.body):
                if has_base(c):
                    defined = set().union(*(bound_names(t) for t in assigned_targets(s)))
                    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        defined.add(s.name)
                    out += [(module, s.lineno, n) for n in sorted(defined & names)]
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    own_names_by_node.update((id(n), (own_names, receivers))
                                             for n, receivers in nodes_with_own_receivers(s, method_receivers(s)))

    def passes(node, receiver, name):
        own_names, receivers = own_names_by_node.get(id(node), ((), ()))
        return isinstance(receiver, ast.Name) and receiver.id in receivers and name in own_names
    loop_names = loop_variable_names(tree)
    for no in ast.walk(tree):
        if isinstance(no, ast.Attribute) and no.attr in names and not passes(no, no.value, no.attr):
            out.append((module, no.lineno, no.attr))
        else:
            out += [(module, no.lineno, n) for n in attr_call_names(no, loop_names)
                    if n in names and not passes(no, call_args(no)[0], n)]
    return out


@functools.cache
def parsed(name):
    return ast.parse((RAIZ / name).read_text(encoding="utf-8"))


def root_modules(owner):
    return [f.name for f in sorted(RAIZ.glob("*.py")) if f.name != owner]


def module_privates(tree):
    out = set()
    for s in class_level(tree.body):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(s.name)
        elif isinstance(s, (ast.Import, ast.ImportFrom)):
            out |= {a.asname or a.name.split(".")[0] for a in s.names}
        for target in assigned_targets(s):
            out |= set(bound_names(target))
    return {n for n in out if is_private(n)}


COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def lexical_nodes(node, scope):
    for child in ast.iter_child_nodes(node):
        yield from lexical_node(child, scope)


def lexical_node(node, scope):
    def visit(parts, where):
        for part in parts:
            yield from lexical_node(part, where)
    yield node, scope
    if isinstance(node, FUNCTIONS):
        a = node.args
        annotations = [p.annotation for p in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]
                       if p and p.annotation] + [r for r in [getattr(node, "returns", None)] if r]
        yield from visit(a.defaults + [d for d in a.kw_defaults if d] + getattr(node, "decorator_list", [])
                         + annotations, scope)
        yield from visit(node.body if isinstance(node.body, list) else [node.body], node)
    elif isinstance(node, ast.ClassDef):
        yield from visit(node.bases + node.keywords + node.decorator_list, scope)
        yield from visit(node.body, node)
    elif isinstance(node, COMPREHENSIONS):
        first, *later = node.generators
        yield from visit([first.iter], scope)
        elements = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        yield from visit([first.target, *first.ifs]
                         + [n for g in later for n in (g.target, g.iter, *g.ifs)] + elements, node)
    else:
        yield from lexical_nodes(node, scope)


class ModuleBindings:
    def __init__(self, tree):
        self.tree = tree
        self.enclosing = {}
        self.declared = {}
        nodes = list(lexical_nodes(tree, tree))
        for n, scope in nodes:
            if isinstance(n, SCOPES + COMPREHENSIONS):
                self.enclosing[id(n)] = scope
        self.bind_all(nodes)
        declarations = [(n, scope) for n, scope in nodes if isinstance(n, (ast.Global, ast.Nonlocal))]
        local = set(self.bound) - {(id(scope), name) for n, scope in declarations for name in n.names}
        for n, scope in declarations:
            outer = (lambda name: tree) if isinstance(n, ast.Global) else (
                lambda name: self.binder_above(scope, name, local))
            self.declared.update(((id(scope), name), outer(name)) for name in n.names)
        self.bind_all(nodes)

    def bind_all(self, nodes):
        self.bound = {}
        for n, scope in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.bind(scope, n.name, None)
            if isinstance(n, FUNCTIONS):
                a = n.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                    if arg:
                        self.bind(n, arg.arg, None)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    self.bind(scope, a.asname or a.name.split(".")[0], a.name if a.asname else a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    self.bind(scope, a.asname or a.name, None)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                self.bind(scope, n.id, None)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                self.bind(scope, n.name, None)

    def function_above(self, scope):
        scope = self.enclosing.get(id(scope))
        while isinstance(scope, ast.ClassDef):
            scope = self.enclosing.get(id(scope))
        return scope

    def binder_above(self, scope, name, local):
        scope = self.function_above(scope)
        while scope is not None and scope is not self.tree and (id(scope), name) not in local:
            scope = self.function_above(scope)
        return scope

    def bind(self, scope, name, module):
        scope = self.declared.get((id(scope), name), scope)
        self.bound.setdefault((id(scope), name), set()).update([module] if module else [])

    def modules(self, name, scope):
        while scope is not None:
            scope = self.declared.get((id(scope), name), scope)
            found = self.bound.get((id(scope), name))
            if found is not None:
                return found
            scope = self.function_above(scope)
        return set()


def string_literal_arg(call, keyword):
    first = call_args(call)[:1] or [k.value for k in call.keywords if k.arg == keyword]
    return first[0].value if first and isinstance(first[0], ast.Constant) else None


def module_private_reaches(module, tree, owner_module, names):
    bindings = ModuleBindings(tree)
    loop_names = loop_variable_names(tree)

    def holds(node, module, scope):
        return isinstance(node, ast.Name) and module in bindings.modules(node.id, scope)

    def the_module(node, scope):
        if isinstance(node, ast.Call):
            return (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                    and holds(node.func.value, "importlib", scope) and string_literal_arg(node, "name") == owner_module)
        if isinstance(node, ast.Subscript):
            return (isinstance(node.value, ast.Attribute) and node.value.attr == "modules"
                    and holds(node.value.value, "sys", scope) and isinstance(node.slice, ast.Constant)
                    and node.slice.value == owner_module)
        return holds(node, owner_module, scope)
    out = []
    for no, scope in lexical_nodes(tree, tree):
        if isinstance(no, ast.ImportFrom) and no.module == owner_module and not no.level:
            out += [(module, no.lineno, a.name) for a in no.names if a.name in names]
        elif isinstance(no, ast.Attribute) and no.attr in names and the_module(no.value, scope):
            out.append((module, no.lineno, no.attr))
        elif isinstance(no, ast.Call) and call_args(no) and the_module(call_args(no)[0], scope):
            out += [(module, no.lineno, n) for n in attr_call_names(no, loop_names) if n in names]
    return out


CONTAINER_MUTATORS = frozenset(("add", "append", "extend", "insert", "pop", "remove", "discard", "clear",
                                "setdefault", "popitem", "sort", "reverse", "difference_update",
                                "intersection_update", "symmetric_difference_update"))
APP_NAMES = frozenset(("A", "app"))
ENGINE_NAMES = frozenset(("E", "e", "engine", "motor"))


def instance_state(tree, classes):
    out = set()
    for c in tree.body:
        if isinstance(c, ast.ClassDef) and c.name in classes:
            for s in class_level(c.body):
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out |= set(instance_stores(s))
                    if any(attr_function(d, ("property",)) for d in s.decorator_list):
                        out.add(s.name)
    return {n for n in out if not n.startswith("_")}


def held_attribute(node):
    while isinstance(node, ast.Subscript):
        node = node.value
    return [(node.value, node.attr)] if isinstance(node, ast.Attribute) else []


def written_attributes(node, loop_names):
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return [(node.value, node.attr)]
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return held_attribute(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CONTAINER_MUTATORS:
        return held_attribute(node.func.value)
    return [(call_args(node)[0], n) for n in attr_call_names(node, loop_names, ("setattr", "delattr"))]


def named(receiver, names):
    return ((isinstance(receiver, ast.Name) and receiver.id in names)
            or (isinstance(receiver, ast.Attribute) and receiver.attr in names))


def state_writes(module, tree, names, receivers):
    loop_names = loop_variable_names(tree)
    return [(module, node.lineno, attr) for node in ast.walk(tree)
            for receiver, attr in written_attributes(node, loop_names) if attr in names and named(receiver, receivers)]


def class_reaches(owner, classes):
    tree = parsed(owner)
    names = privates(tree, classes)
    if not names:
        return None
    module_names = module_privates(tree)
    return sorted(r for m in root_modules(owner)
                  for r in module_reaches(m, parsed(m), names)
                  + module_private_reaches(m, parsed(m), owner.removesuffix(".py"), module_names))


def owner_writes(owner, classes, receivers):
    names = instance_state(parsed(owner), classes)
    if not names:
        return None
    return sorted(r for m in root_modules(owner) for r in state_writes(m, parsed(m), names, receivers))


def library_reaches():
    tree = parsed("server.py")
    if not any(isinstance(c, ast.ClassDef) and c.name == "Library" for c in tree.body):
        return None
    return sorted(module_reaches("server.py", tree, privates(tree, {"Library"})))


def ratchet(what, where, found, ceiling, ceiling_name, advice):
    if found is None:
        print(f"FAIL  no name to count for the {what}: the classes moved or were renamed")
        return True
    per_module = {}
    for module, _, _ in found:
        per_module[module] = per_module.get(module, 0) + 1
    detail = ", ".join(f"{k} {v}" for k, v in per_module.items()) or "none"
    print(f"-- summary: {what} {where}: {len(found)} (ceiling {ceiling}; {detail})")
    if len(found) == ceiling:
        print(f"ok    the {what} did not grow")
        return False
    if len(found) > ceiling:
        print(f"FAIL  {len(found) - ceiling} new {what}: {advice}")
    else:
        print(f"FAIL  fewer {what}: lower {ceiling_name} in dev/testa_ganchos.py to {len(found)} in this same PR")
    for module, line, name in found:
        print(f"        {module}:{line} .{name}")
    return True


falhou = False
arvore = ast.parse((RAIZ / "engine.py").read_text(encoding="utf-8"))
modulos = opcionais(arvore)
conta = len(set().union(*(ganchos(arvore, m) for m in modulos))) if modulos else 0
print(f"modulos opcionais no engine.py: {len(modulos)}; ganchos: {conta} (TETO {TETO})")
if conta > TETO:
    print(f"FALHA o engine.py ganhou {conta - TETO} gancho(s) para o modulo de fora do repo: o que ele precisa passa "
          "pelo que ja existe (docs/arquitetura/fx.md)")
    falhou = True
elif conta < TETO:
    print(f"FALHA saiu gancho: baixe o TETO do dev/testa_ganchos.py para {conta} neste mesmo PR")
    falhou = True
else:
    print("ok    os ganchos para o modulo de fora do repo nao cresceram")

routes = out_of_repo_routes(ast.parse((RAIZ / "permissao.py").read_text(encoding="utf-8")))
if routes is None:
    print("FAIL  permissao.py has no OUT_OF_REPO tuple written as a literal: the routes can't be counted")
    falhou = True
else:
    count = len(set(routes))
    print(f"routes only the module from outside the repo calls: {count} (ROUTES_CEILING {ROUTES_CEILING})")
    if count != len(routes):
        print("FAIL  OUT_OF_REPO lists the same route twice")
        falhou = True
    elif count > ROUTES_CEILING:
        print(f"FAIL  the server gained {count - ROUTES_CEILING} route(s) for the module from outside the repo: what "
              "it needs goes through the ones it already has")
        falhou = True
    elif count < ROUTES_CEILING:
        print(f"FAIL  a route left: lower ROUTES_CEILING in dev/testa_ganchos.py to {count} in this same PR")
        falhou = True
    else:
        print("ok    the routes for the module from outside the repo didn't grow")

OWNER = "class Owner:\n    def _x(self):\n        pass\n"
CAUGHT = [
    ("an attribute", OWNER, "def f(o):\n    return o._x\n"),
    ("getattr with the name", OWNER, "def f(o):\n    return getattr(o, '_x')\n"),
    ("builtins.getattr", OWNER, "import builtins\n\n\ndef f(o):\n    return builtins.getattr(o, '_x')\n"),
    ("a loop over a literal tuple", OWNER, "def f(o):\n    for k in ('_x', 'y'):\n        getattr(o, k)\n"),
    ("a loop that unpacks", OWNER, "def f(o):\n    for _, k in (('a', '_x'),):\n        setattr(o, k, 0)\n"),
    ("a comprehension", OWNER, "def f(o):\n    return [getattr(o, k) for k in ('_x',)]\n"),
    ("the names from a dictionary", OWNER, "def f(o):\n    for k, v in {'_x': 1}.items():\n        setattr(o, k, v)\n"),
    ("the keys of a dict comprehension assigned once", OWNER,
     "def f(o):\n    values = {k: 0 for k in ('_x', 'public') if k}\n    for k, v in values.items():\n"
     "        setattr(o, k, v)\n"),
    ("a dict comprehension with a local class assigning the same name", OWNER,
     "def f(o):\n    values = {k: 0 for k in ('_x', 'public')}\n\n    class Local:\n        values = {}\n\n"
     "    for k, v in values.items():\n        setattr(o, k, v)\n"),
    ("a loop in a class body over a dictionary of the enclosing function", OWNER,
     "def f(o):\n    values = {k: 0 for k in ('_x', 'public')}\n\n    class Local:\n"
     "        for k, v in values.items():\n            setattr(o, k, v)\n"),
    ("a loop over a tuple assigned once", OWNER,
     "def f(o):\n    names = ('_x', 'y')\n    for k in names:\n        getattr(o, k)\n"),
    ("a module-level def f(self)", OWNER, "def f(self):\n    return self._x\n"),
    ("a subclass reading it", OWNER, "class Sub(Owner):\n    def m(self):\n        return self._x\n"),
    ("a subclass overriding it", OWNER, "class Sub(Owner):\n    def _x(self):\n        pass\n"),
    ("a nested def with its own self", OWNER,
     "class Other:\n    _x = 0\n\n    def m(self, o):\n        def read(self):\n            return self._x\n"
     "        return read(o)\n"),
    ("a second parameter called cls", OWNER,
     "class Other:\n    _x = 0\n\n    def m(self, cls):\n        return getattr(cls, '_x')\n"),
    ("a staticmethod's self", OWNER,
     "class Other:\n    _x = 0\n\n    @staticmethod\n    def m(self):\n        return self._x\n"),
    ("defined under an if", "class Owner:\n    if True:\n        def _x(self):\n            pass\n", "o._x\n"),
    ("defined by unpacking", "class Owner:\n    _w, (_x, *_y) = 1, (2, 3)\n", "o._x\n"),
    ("declared in __slots__", "class Owner:\n    __slots__ = ('_x',)\n", "o._x\n"),
    ("set by setattr", "class Owner:\n    def __init__(self):\n        setattr(self, '_x', 0)\n", "o._x\n"),
    ("set by setattr in a loop",
     "class Owner:\n    def __init__(self):\n        for k in ('_x',):\n            setattr(self, k, 0)\n", "o._x\n"),
    ("set through a captured self",
     "class Owner:\n    def __init__(self):\n        def init():\n            self._x = 0\n        init()\n", "o._x\n"),
    ("a nested class", "class Owner:\n    class _x:\n        pass\n", "o._x\n"),
    ("a loop over a set literal", OWNER, "def f(o):\n    for k in {'_x'}:\n        getattr(o, k)\n"),
    ("getattr with the name unpacked", OWNER, "def f(o):\n    return getattr(o, *('_x',))\n"),
    ("object.__getattribute__", OWNER, "def f(o):\n    return object.__getattribute__(o, '_x')\n"),
    ("object.__setattr__", OWNER, "def f(o):\n    object.__setattr__(o, '_x', 0)\n"),
    ("object.__delattr__", OWNER, "def f(o):\n    object.__delattr__(o, '_x')\n"),
    ("set by object.__setattr__", "class Owner:\n    def __init__(self):\n        object.__setattr__(self, '_x', 0)\n",
     "o._x\n"),
    ("a subclass of a class whose base is object", OWNER,
     "class Sub(Owner, object):\n    def m(self):\n        return self._x\n"),
]
NOT_REACHES = [
    ("its own name in a class whose only base is object", OWNER,
     "class Other(object):\n    _x = 0\n\n    def m(self):\n        return self._x\n"),
    ("its own name", OWNER, "class Other:\n    _x = 0\n\n    def m(self):\n        return self._x\n"),
    ("its own name, captured", OWNER,
     "class Other:\n    _x = 0\n\n    def m(self):\n        return (lambda: self._x)()\n"),
    ("a class body's names, which its methods do not see", OWNER,
     "def f(o):\n    names = ('y',)\n\n    class Other:\n        names = ('_x',)\n\n        def m(self):\n"
     "            for k in names:\n                getattr(o, k)\n"),
    ("a name assigned twice", OWNER,
     "def f(o, other):\n    names = ('_x',)\n    names = other\n    for k in names:\n        getattr(o, k)\n"),
    ("a nested class's own self",
     "class Owner:\n    def m(self):\n        class Local:\n"
     "            def __init__(self):\n                self._x = 0\n",
     "o._x\n"),
]
KNOWN_MISSES_ISSUE = "https://github.com/ritmelli/ritmelli/issues/232"
KNOWN_MISSES = [
    ("set by setattr in a loop over a module tuple",
     "NAMES = ('_x',)\n\n\nclass Owner:\n    def __init__(self):\n        for k in NAMES:\n"
     "            setattr(self, k, 0)\n",
     "o._x\n"),
    ("a tuple extended after it is assigned",
     "def f(o):\n    names = ('y',)\n    names += ('_x',)\n    for k in names:\n        getattr(o, k)\n"),
    ("a key stored into the dictionary after it is assigned",
     "def f(o):\n    names = {'y': 1}\n    names['_x'] = 2\n    for k in names:\n        getattr(o, k)\n"),
    ("the name in a variable", "def f(o):\n    n = '_x'\n    return getattr(o, n)\n"),
    ("getattr under another name", "def f(o):\n    g = getattr\n    return g(o, '_x')\n"),
    ("operator.attrgetter", "import operator\n\n\ndef f(o):\n    return operator.attrgetter('_x')(o)\n"),
    ("vars()", "def f(o):\n    return vars(o)['_x']\n"),
    ("__dict__", "def f(o):\n    return o.__dict__['_x']\n"),
    ("self rebound in a method",
     "class Other:\n    _x = 0\n\n    def m(self, o):\n        self = o\n        return self._x\n"),
    ("self rebound in a comprehension",
     "class Other:\n    _x = 0\n\n    def m(self, others):\n        return [self._x for self in others]\n"),
]
MODULE_OWNER = "def _x():\n    pass\n"
MODULE_CAUGHT = [
    ("an attribute of the module", MODULE_OWNER, "import owner\n\n\ndef f():\n    return owner._x()\n"),
    ("an attribute of the module under another name", MODULE_OWNER,
     "import owner as o\n\n\ndef f():\n    return o._x()\n"),
    ("the module imported inside a function", MODULE_OWNER, "def f():\n    import owner\n    return owner._x\n"),
    ("the module after a comprehension that reuses its name", MODULE_OWNER,
     "import owner as e\n\nnames = [e for e in ()]\ne._x\n"),
    ("a default argument", MODULE_OWNER, "import owner as e\n\n\ndef f(e=e._x):\n    return e\n"),
    ("importlib.import_module", MODULE_OWNER,
     "import importlib\n\n\ndef f():\n    return importlib.import_module('owner')._x\n"),
    ("sys.modules", MODULE_OWNER, "import sys\n\n\ndef f():\n    return sys.modules['owner']._x\n"),
    ("a global the function assigns", MODULE_OWNER,
     "import owner as e\n\n\ndef f():\n    global e\n    e = e._x\n"),
    ("importlib.import_module with the name as a keyword", MODULE_OWNER,
     "import importlib\n\nimportlib.import_module(name='owner')._x\n"),
    ("a nonlocal two functions up", MODULE_OWNER,
     "def outer():\n    import owner as e\n\n    def middle():\n        def inner():\n            nonlocal e\n"
     "            e = e._x\n        return inner\n    return middle\n"),
    ("a nonlocal through a function that declares it too", MODULE_OWNER,
     "def outer():\n    e = None\n\n    def middle():\n        nonlocal e\n        e = 1\n\n        def inner():\n"
     "            nonlocal e\n            import owner as e\n        inner()\n    middle()\n    return e._x\n"),
    ("a nonlocal the function assigns", MODULE_OWNER,
     "def outer():\n    import owner as e\n\n    def inner():\n        nonlocal e\n        e = e._x\n    return inner\n"),
    ("a reach before the alias is rebound", MODULE_OWNER, "import owner as e\n\ne._x()\ne = None\n"),
    ("a parameter annotation", MODULE_OWNER, "import owner as e\n\n\ndef f(e: e._x):\n    return e\n"),
    ("a return annotation", MODULE_OWNER, "import owner as e\n\n\ndef f(e) -> e._x:\n    return e\n"),
    ("the first iterable of a comprehension", MODULE_OWNER,
     "import owner as e\n\nvalues = [e for e in e._x]\n"),
    ("the module seen from a method", MODULE_OWNER,
     "import owner as e\n\n\nclass C:\n    def m(self):\n        return e._x\n"),
    ("a name imported from the module", MODULE_OWNER, "from owner import _x\n"),
    ("getattr on the module", MODULE_OWNER, "import owner\n\n\ndef f():\n    return getattr(owner, '_x')\n"),
    ("a private class", "class _x:\n    pass\n", "import owner\n\nowner._x\n"),
    ("a private constant", "_x = 1\n", "import owner\n\nowner._x\n"),
    ("a module imported under a private name", "import helper as _x\n", "import owner\n\nowner._x\n"),
    ("a name imported under a private name", "from helper import y as _x\n", "import owner\n\nowner._x\n"),
    ("a private defined under a try", "try:\n    import y\nexcept ImportError:\n    _x = None\n",
     "import owner\n\nowner._x\n"),
]
MODULE_NOT_REACHES = [
    ("a public name of the module", "def _x():\n    pass\n\n\ndef x():\n    pass\n", "import owner\n\nowner.x\n"),
    ("the same name on another object", MODULE_OWNER, "import owner\n\n\ndef f(o):\n    return o._x\n"),
    ("the same name in another module", MODULE_OWNER, "import other\n\nother._x\n"),
    ("a parameter that shadows the module", MODULE_OWNER,
     "import owner as e\n\n\ndef f(e):\n    return e._x\n"),
    ("a comprehension variable that shadows the module", MODULE_OWNER,
     "import owner as e\n\nvalues = [e._x for e in ()]\n"),
    ("a parameter of a nested function that shadows the module", MODULE_OWNER,
     "import owner as e\n\n\ndef f():\n    def g(e):\n        return e._x\n    return g\n"),
    ("a parameter named importlib", MODULE_OWNER, "def f(importlib):\n    return importlib.import_module('owner')._x\n"),
    ("an exception caught as sys", MODULE_OWNER,
     "import sys\n\n\ndef f():\n    try:\n        pass\n    except Exception as sys:\n        return sys.modules['owner']._x\n"),
    ("a parameter named sys", MODULE_OWNER, "def f(sys):\n    return sys.modules['owner']._x\n"),
    ("a local that shadows the module", MODULE_OWNER,
     "import owner\n\n\ndef f(o):\n    owner = o\n    return owner._x\n"),
]
MODULE_KNOWN_MISSES = [
    ("a method default read before the class body rebinds the alias", MODULE_OWNER,
     "import owner as e\n\n\nclass C:\n    def f(self, x=e._x):\n        return x\n    e = None\n"),
    ("the module bound to another name", MODULE_OWNER, "import owner\n\nm = owner\nm._x\n"),
]
STATE_OWNER = "class App:\n    def __init__(self):\n        self.x = []\n\n    @property\n    def p(self):\n        return 1\n"
WRITES_CAUGHT = [
    ("an assignment", APP_NAMES, "def f(A):\n    A.x = 1\n"),
    ("an augmented assignment", APP_NAMES, "def f(A):\n    A.x += [1]\n"),
    ("one of a pair", APP_NAMES, "def f(A):\n    A.x, A.y = 1, 2\n"),
    ("through self.app", APP_NAMES, "class Other:\n    def m(self):\n        self.app.x = 1\n"),
    ("an item", APP_NAMES, "def f(A):\n    A.x[0] = 1\n"),
    ("a slice", APP_NAMES, "def f(A):\n    A.x[1:] = []\n"),
    ("an item of an item", APP_NAMES, "def f(A):\n    A.x[0][1] = 2\n"),
    ("a del", APP_NAMES, "def f(A):\n    del A.x\n"),
    ("a container method", APP_NAMES, "def f(app):\n    app.x.append(1)\n"),
    ("a set method that changes it", APP_NAMES, "def f(A, ids):\n    A.x.difference_update(ids)\n"),
    ("intersection_update", APP_NAMES, "def f(A, ids):\n    A.x.intersection_update(ids)\n"),
    ("symmetric_difference_update", APP_NAMES, "def f(A, ids):\n    A.x.symmetric_difference_update(ids)\n"),
    ("a container method on an item", APP_NAMES, "def f(A):\n    A.x[0]['tags'].append(1)\n"),
    ("setattr", APP_NAMES, "def f(A):\n    setattr(A, 'x', 1)\n"),
    ("a read-only property", APP_NAMES, "def f(A):\n    A.p = 1\n"),
    ("object.__setattr__", APP_NAMES, "def f(A):\n    object.__setattr__(A, 'x', 1)\n"),
    ("delattr in a loop", APP_NAMES, "def f(A):\n    for k in ('x',):\n        delattr(A, k)\n"),
    ("the engine through the App", ENGINE_NAMES, "def f(A):\n    A.engine.x = 1\n"),
    ("the engine in a local", ENGINE_NAMES, "def f(A):\n    E = A.engine\n    E.x = None\n"),
]
WRITES_NOT_COUNTED = [
    ("a read", APP_NAMES, "def f(A):\n    return A.x[0]\n"),
    ("a call of a public method", APP_NAMES, "def f(A):\n    A.change_queue(A.x.copy)\n"),
    ("another class's own attribute", APP_NAMES, "class Other:\n    def m(self):\n        self.x = 1\n"),
    ("an object that is not the App", APP_NAMES, "def f(o):\n    o.x = 1\n"),
    ("an attribute the App does not have", APP_NAMES, "def f(A):\n    A.y = 1\n"),
]
WRITES_KNOWN_MISSES = [
    ("the App under another name", APP_NAMES, "def f(server_app):\n    server_app.x = 1\n"),
    ("a dictionary's update, which reads like a public method named update", APP_NAMES,
     "def f(A):\n    A.x.update(y=1)\n"),
    ("a container held in a local", APP_NAMES, "def f(A):\n    x = A.x\n    x.append(1)\n"),
]


def case_reaches(owner, other):
    return len(module_reaches("case.py", ast.parse(other), privates(ast.parse(owner), {"Owner"})))


def case_module_reaches(owner, other):
    return len(module_private_reaches("case.py", ast.parse(other), "owner", module_privates(ast.parse(owner))))


def case_writes(receivers, other):
    return len(state_writes("case.py", ast.parse(other), instance_state(ast.parse(STATE_OWNER), {"App"}), receivers))


def check_cases(what, count, caught, not_counted, misses):
    failed = False
    for label, *source in caught:
        if count(*source) != 1:
            print(f"FAIL  the ratchet no longer counts this {what}: {label}")
            failed = True
    for label, *source in not_counted:
        if count(*source):
            print(f"FAIL  the ratchet counts this as a {what}: {label}")
            failed = True
    for label, *source in misses:
        if count(*source):
            print(f"FAIL  the ratchet now counts this {what}: {label}; move it from the known misses to the caught "
                  f"cases and update {KNOWN_MISSES_ISSUE}")
            failed = True
    if not failed:
        print(f"ok    the ratchet's own {what} cases: {len(caught)} counted, {len(not_counted)} not counted, "
              f"{len(misses)} known misses ({KNOWN_MISSES_ISSUE})")
    return failed


falhou |= check_cases("reach", lambda *s: case_reaches(*s) if len(s) == 2 else case_reaches(OWNER, *s), CAUGHT,
                      NOT_REACHES, KNOWN_MISSES)
falhou |= check_cases("module reach", case_module_reaches, MODULE_CAUGHT, MODULE_NOT_REACHES, MODULE_KNOWN_MISSES)
falhou |= check_cases("write", case_writes, WRITES_CAUGHT, WRITES_NOT_COUNTED, WRITES_KNOWN_MISSES)
INTERFACE = "go through its public interface (docs/arquitetura/comandos.md)"
falhou |= ratchet("reaches into the engine's insides", "outside engine.py",
                  class_reaches("engine.py", {"Engine", "MockEngine"}), ENGINE_CEILING, "ENGINE_CEILING", INTERFACE)
falhou |= ratchet("reaches into the App's insides", "outside server.py", class_reaches("server.py", {"App"}),
                  APP_CEILING, "APP_CEILING", INTERFACE)
falhou |= ratchet("reaches into the Automatico's insides", "outside automatico.py",
                  class_reaches("automatico.py", {"Automatico"}), AUTOMATICO_CEILING, "AUTOMATICO_CEILING", INTERFACE)
falhou |= ratchet("reaches into the Library's insides", "outside the Library class", library_reaches(),
                  LIBRARY_CEILING, "LIBRARY_CEILING", "go through its public methods")
falhou |= ratchet("direct writes to the App's state", "outside server.py",
                  owner_writes("server.py", {"App"}, APP_NAMES), APP_WRITES_CEILING, "APP_WRITES_CEILING",
                  "change it through a method of the App or of the object that owns it")
falhou |= ratchet("direct writes to the engine's state", "outside engine.py",
                  owner_writes("engine.py", {"Engine", "MockEngine"}, ENGINE_NAMES), ENGINE_WRITES_CEILING,
                  "ENGINE_WRITES_CEILING", "change it through a method of the engine")
sys.exit(1 if falhou else 0)
