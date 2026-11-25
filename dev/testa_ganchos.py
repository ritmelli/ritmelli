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

    python dev/testa_ganchos.py

Sai 1 se uma das contas nao bate."""
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TETO = 26
ROUTES_CEILING = 3


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
sys.exit(1 if falhou else 0)
