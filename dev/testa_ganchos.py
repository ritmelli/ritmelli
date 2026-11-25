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

It also ratchets the reaches into the insides of two classes from the other modules at the repo root:
  - the engine's (Engine and MockEngine, in engine.py), from server.py, comandos.py, automatico.py and the rest; the
    interface is Engine.line, on_line, take_switch, drop_prepared, gain_for, update_track, platter_state and
    tracks_in_use. The count must equal ENGINE_CEILING;
  - the App's (server.App), from comandos.py, automatico.py and the rest; the interface is its public methods
    (change_queue, remove_from_queue, release_reservation, with_engine, search_songs, run_helper and the others). The
    count must equal APP_CEILING.
The private names come from the class's own syntax tree: every method and nested class, every name assigned at the
class's level (also under an if or a try there) or declared in its __slots__, and every self._x or cls._x its methods
assign (also by setattr) whose name starts with one underscore (not two). A reach is a read, write or call of one of
those names, and also a getattr, setattr, hasattr or delattr (or builtins.getattr and the rest) with the name as a
literal or as a loop variable over a literal tuple of names, on any object but a method's own self or cls (its first
parameter; a staticmethod has none), in a class without a base, reaching a name that class defines itself (a class's
own _lock is its own); a class with a base gets no pass, so a subclass reading, assigning or overriding an inherited _x
is a reach.
What counts is the seam between modules: the class's own module stays out, since an underscore name is private to its
module. Above the ceiling, a new reach went in: go through the interface. Below it, the PR lowers the ceiling with it.
Both numbers go to the PR summary (the "-- summary:" lines that dev/testa_tudo.py collects).

    python dev/testa_ganchos.py

Sai 1 se uma das contas nao bate."""
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TETO = 26
ROUTES_CEILING = 3
# the reaches into the engine's insides from the modules at the root, other than engine.py; it only goes down
ENGINE_CEILING = 14
APP_CEILING = 0


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


def attr_function(func, names=ATTR_FUNCTIONS):
    return ((isinstance(func, ast.Name) and func.id in names)
            or (isinstance(func, ast.Attribute) and func.attr in names and isinstance(func.value, ast.Name)
                and func.value.id == "builtins"))


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
    elif isinstance(value, (ast.Tuple, ast.List)):
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
            and isinstance(value.generators[0].iter, (ast.Tuple, ast.List))):
        return [e for e in value.generators[0].iter.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def literal_items(iterable, scope, assignments):
    if isinstance(iterable, (ast.Tuple, ast.List)):
        return iterable.elts
    method = None
    if (isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Attribute) and not iterable.args
            and iterable.func.attr in ("items", "keys")):
        method, iterable = iterable.func.attr, iterable.func.value
    if isinstance(iterable, ast.Name):
        iterable = assignments.single_value(scope, iterable.id)
        if method is None and isinstance(iterable, (ast.Tuple, ast.List)):
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


def attr_call_names(call, loop_names):
    if not (isinstance(call, ast.Call) and attr_function(call.func) and len(call.args) >= 2):
        return []
    name = call.args[1]
    return list(string_literals(name)) if isinstance(name, ast.Constant) else loop_names.get(id(name), [])


def instance_stores(method):
    loop_names = loop_variable_names(method)
    for n, receivers in nodes_with_own_receivers(method, method_receivers(method)):
        if (isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name)
                and n.value.id in receivers):
            yield n.attr
        elif (isinstance(n, ast.Call) and attr_function(n.func, ("setattr",)) and n.args
              and isinstance(n.args[0], ast.Name) and n.args[0].id in receivers):
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
            own_names = set() if c.bases else class_privates(c)
            for s in class_level(c.body):
                if c.bases:
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
                    if n in names and not passes(no, no.args[0], n)]
    return out


def reaches(owner, names):
    return sorted(r for f in sorted(RAIZ.glob("*.py")) if f.name != owner
                  for r in module_reaches(f.name, ast.parse(f.read_text(encoding="utf-8")), names))


def ratchet(what, owner, classes, ceiling, ceiling_name):
    names = privates(ast.parse((RAIZ / owner).read_text(encoding="utf-8")), classes)
    if not names:
        print(f"FAIL  {owner} defines no private name in {', '.join(sorted(classes))}: the classes moved or were "
              "renamed")
        return True
    found = reaches(owner, names)
    per_module = {}
    for module, _, _ in found:
        per_module[module] = per_module.get(module, 0) + 1
    detail = ", ".join(f"{k} {v}" for k, v in per_module.items()) or "none"
    print(f"-- summary: reaches into the {what}'s insides outside {owner}: {len(found)} "
          f"(ceiling {ceiling}; {detail})")
    if len(found) == ceiling:
        print(f"ok    the reaches into the {what}'s insides did not grow")
        return False
    if len(found) > ceiling:
        print(f"FAIL  {len(found) - ceiling} new reach(es) into the {what}'s insides: go through its public interface "
              "(docs/arquitetura/comandos.md)")
    else:
        print(f"FAIL  fewer reaches into the {what}'s insides: lower {ceiling_name} in dev/testa_ganchos.py to "
              f"{len(found)} in this same PR")
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
]
NOT_REACHES = [
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


def case_reaches(owner, other):
    return len(module_reaches("case.py", ast.parse(other), privates(ast.parse(owner), {"Owner"})))


cases_failed = False
for label, owner, other in CAUGHT:
    if case_reaches(owner, other) != 1:
        print(f"FAIL  the ratchet no longer counts this reach: {label}")
        cases_failed = True
for label, owner, other in NOT_REACHES:
    if case_reaches(owner, other):
        print(f"FAIL  the ratchet counts this as a reach: {label}")
        cases_failed = True
for label, other in KNOWN_MISSES:
    if case_reaches(OWNER, other):
        print(f"FAIL  the ratchet now counts this reach: {label}; move it from KNOWN_MISSES to CAUGHT and update "
              f"{KNOWN_MISSES_ISSUE}")
        cases_failed = True
falhou |= cases_failed
if not cases_failed:
    print(f"ok    the ratchet's own cases: {len(CAUGHT)} counted, {len(NOT_REACHES)} not counted, "
          f"{len(KNOWN_MISSES)} known misses ({KNOWN_MISSES_ISSUE})")
falhou |= ratchet("engine", "engine.py", {"Engine", "MockEngine"}, ENGINE_CEILING, "ENGINE_CEILING")
falhou |= ratchet("App", "server.py", {"App"}, APP_CEILING, "APP_CEILING")
sys.exit(1 if falhou else 0)
