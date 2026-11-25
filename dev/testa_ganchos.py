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
The private names come from the class's own syntax tree: every method, every name assigned at the class's level (also
under an if or a try there) and every self._x or cls._x it assigns whose name starts with one underscore (not two). A
reach is a read, write or call of one of those names on an object other than self or cls (a class's own _lock is its
own), and also a getattr, setattr, hasattr or delattr (or builtins.getattr and the rest) with the name as a literal.
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
# the reaches into the App's insides from the modules at the root, other than server.py; it only goes down
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


def own(node):
    return isinstance(node, ast.Name) and node.id in ("self", "cls")


def class_level(body):
    """The statements at a class's own level: its body and what the control blocks there hold (an if, a try), without
    going into a def or a nested class."""
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


def privates(tree, classes):
    """The private names the top-level classes named in classes define: their methods and the names assigned at the
    class's own level (also under an if or a try there), and every self._x or cls._x their methods assign (a helper
    def nested inside a method is not the class's)."""
    out = set()
    for c in tree.body:
        if not (isinstance(c, ast.ClassDef) and c.name in classes):
            continue
        for s in class_level(c.body):  # the class's own level: its methods and _X = ...
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(s.name)
            for target in (s.targets if isinstance(s, ast.Assign) else [s.target] if isinstance(s, ast.AnnAssign)
                           else []):
                if isinstance(target, ast.Name):
                    out.add(target.id)
        for no in ast.walk(c):
            if isinstance(no, ast.Attribute) and isinstance(no.ctx, ast.Store) and own(no.value):
                out.add(no.attr)
    return {n for n in out if is_private(n)}


ATTR_FUNCTIONS = ("getattr", "setattr", "hasattr", "delattr")


def attr_function(func):
    """Whether a call's func is getattr and its kin, by name or through the builtins module."""
    return ((isinstance(func, ast.Name) and func.id in ATTR_FUNCTIONS)
            or (isinstance(func, ast.Attribute) and func.attr in ATTR_FUNCTIONS and isinstance(func.value, ast.Name)
                and func.value.id == "builtins"))


def reaches(owner, names):
    """[(module, line, name)] of the reaches into names from the modules at the root other than owner: an attribute
    on an object other than self or cls, or a getattr/setattr/hasattr/delattr (also builtins.getattr and the rest)
    with the name as a literal."""
    out = []
    for f in sorted(RAIZ.glob("*.py")):
        if f.name == owner:
            continue
        for no in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Attribute) and no.attr in names and not own(no.value):
                out.append((f.name, no.lineno, no.attr))
            elif (isinstance(no, ast.Call) and attr_function(no.func) and len(no.args) >= 2
                  and isinstance(no.args[1], ast.Constant) and no.args[1].value in names and not own(no.args[0])):
                out.append((f.name, no.lineno, no.args[1].value))
    return sorted(out)


def ratchet(what, owner, classes, ceiling, ceiling_name):
    """Checks the reaches into the insides of classes (top-level in the module owner) against the ceiling; True if it
    fails."""
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

falhou |= ratchet("engine", "engine.py", {"Engine", "MockEngine"}, ENGINE_CEILING, "ENGINE_CEILING")
falhou |= ratchet("App", "server.py", {"App"}, APP_CEILING, "APP_CEILING")
sys.exit(1 if falhou else 0)
