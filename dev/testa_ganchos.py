r"""Confere que os ganchos do engine.py para o modulo opcional de fora do repo nao crescem. O modulo e o que o
engine.py importa num try com o except ImportError que o troca por None e que nao mora neste repo; o nome dele sai
do proprio engine.py. Gancho, para esta conta: cada nome diferente do engine.py que tem o nome do modulo como uma
das palavras dele (funcao, metodo, atributo, constante, variavel), cada atributo lido direto do modulo e cada
atributo lido de um objeto com o nome dele. A conta tem de dar o TETO: acima dele, entrou gancho novo; abaixo, saiu
um, e o TETO desce junto no mesmo PR. Gancho com nome que nao lembra o modulo escapa da conta, e a regra vale igual
(docs/arquitetura/fx.md). So a biblioteca padrao, lendo o texto do engine.py: nada e importado nem tocado.

    python dev/testa_ganchos.py

Sai 1 se a conta nao bate."""
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TETO = 24


def opcionais_de_fora(arvore):
    """Os modulos do try/except ImportError do topo que viram None e que nao moram no repo."""
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
    return {m for m in achados if not (RAIZ / f"{m}.py").exists() and not (RAIZ / m).is_dir()}


def ganchos(arvore, modulo):
    def tem(nome):  # o nome do modulo como palavra do identificador (_x_voz, X_FOLGA_S, X), nao pedaco de outra
        return modulo.lower() in (p.lower() for p in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", nome))

    achados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Name) and tem(no.id):
            achados.add(no.id)
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and tem(no.name):
            achados.add(no.name)
        elif isinstance(no, ast.arg) and tem(no.arg):
            achados.add(no.arg)
        elif isinstance(no, ast.Attribute):
            if tem(no.attr):
                achados.add(no.attr)
            base = no.value
            dono = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
            if dono and tem(dono) and not tem(no.attr):
                achados.add(f"{dono}.{no.attr}")
    return achados


arvore = ast.parse((RAIZ / "engine.py").read_text(encoding="utf-8"))
modulos = opcionais_de_fora(arvore)
conta = len(set().union(*(ganchos(arvore, m) for m in modulos))) if modulos else 0
print(f"modulos opcionais de fora do repo no engine.py: {len(modulos)}; ganchos: {conta} (TETO {TETO})")
if conta > TETO:
    print(f"FALHA o engine.py ganhou {conta - TETO} gancho(s) para o modulo de fora do repo: o que ele precisa passa "
          "pelo que ja existe (docs/arquitetura/fx.md)")
    sys.exit(1)
if conta < TETO:
    print(f"FALHA saiu gancho: baixe o TETO do dev/testa_ganchos.py para {conta} neste mesmo PR")
    sys.exit(1)
print("ok    os ganchos para o modulo de fora do repo nao cresceram")
