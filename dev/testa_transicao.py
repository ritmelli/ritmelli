r"""As contas da passagem (transicao.py) sobre entradas e saidas gravadas: o dev/testa_transicao.json guarda cada chamada
que o motor fez ao transicao.py nos pares da banca das passagens (dev/testa_passagem.py), com os argumentos e o que
voltou, e este teste chama de novo cada uma e confere que volta o mesmo. Sem som, sem ffmpeg e sem o motor: so o
transicao.py e o numpy. Toda funcao publica do transicao.py tem de ter ao menos um caso gravado.

    python dev/testa_transicao.py            confere os casos gravados
    python dev/testa_transicao.py --grava    roda a banca das passagens neste checkout (precisa do ffmpeg, como ela) e
                                             regrava o JSON com as chamadas que o motor fez

Regravar e para quando uma conta muda de proposito (o PR diz por que) ou quando a banca ganha par: a banca passa antes,
e os casos novos saem do motor de verdade, nunca escritos a mao.

The JSON keeps a fingerprint of the bench (its tokens, without comments and docstrings, the same on every Python
version), and the check fails when the bench changed since the recording: a pair that changed has to be recorded
again.

O nivel dos blocos (a lista (t0, quadros, rms) do leitor do motor) vai uma vez so, no "niveis", e cada chamada aponta
para ele; as colunas dele (no "colunas", tambem uma vez cada) e os arrays vao em base64 dos bytes (zlib), para a volta
ser exata.

Sai 1 se algo falha."""
import argparse
import ast
import base64
import hashlib
import inspect
import io
import json
import math
import runpy
import sys
import tokenize
import zlib
from pathlib import Path

import numpy as np

DEV = Path(__file__).resolve().parent
RAIZ = DEV.parent
sys.path.insert(0, str(RAIZ))
import transicao

CASOS = DEV / "testa_transicao.json"
BANCA = DEV / "testa_passagem.py"
TOL = 1e-9  # numpy de outra versao pode mudar o ultimo bit de uma media; a decisao, nunca


def _publicas():
    return sorted(n for n, f in vars(transicao).items()
                  if inspect.isfunction(f) and not n.startswith("_") and f.__module__ == "transicao")


def _b64(a):
    return base64.b64encode(zlib.compress(np.ascontiguousarray(a).tobytes(), 9)).decode("ascii")


def _de_b64(txt, dtype):
    return np.frombuffer(zlib.decompress(base64.b64decode(txt)), dtype=dtype).copy()


def _e_niv(v):
    return isinstance(v, list) and v and all(isinstance(x, tuple) and len(x) == 3 for x in v)


class Gravador:
    """Embrulha as funcoes publicas do transicao.py e guarda cada chamada (do par que esta rodando) com o que voltou."""

    def __init__(self):
        self.par, self.casos, self.niveis, self.colunas, self.vistos = None, [], {}, {}, set()

    def _col(self, a):
        z = _b64(a)
        chave = hashlib.sha1(z.encode()).hexdigest()[:12]
        self.colunas.setdefault(chave, z)
        return chave

    def _niv(self, v):
        t = np.array([x[0] for x in v], np.float64)
        q = np.array([x[1] for x in v], np.int64)
        r = np.array([x[2] for x in v], np.float64)
        r32 = bool(np.array_equal(r.astype(np.float32).astype(np.float64), r))  # o rms do leitor e um float32
        d = {"t": self._col(t), "q": self._col(q), "r32" if r32 else "r": self._col(r.astype(np.float32) if r32 else r)}
        chave = hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]
        self.niveis.setdefault(chave, d)
        return {"niv": chave}

    def cod(self, v):
        if _e_niv(v):
            return self._niv(v)
        if isinstance(v, np.ndarray):
            return {"nd": str(v.dtype), "shape": list(v.shape), "z": _b64(v)}
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if isinstance(v, (int, np.integer)):
            return int(v)
        if isinstance(v, (float, np.floating)):
            return float(v)
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, (tuple, list)):
            return [self.cod(x) for x in v]
        raise TypeError(f"sem codificacao para {type(v).__name__}")

    def embrulha(self, nome):
        f = getattr(transicao, nome)

        def gravado(*args, **kw):
            saida = f(*args, **kw)
            caso = {"par": self.par, "fn": nome, "args": [self.cod(a) for a in args],
                    "kw": {k: self.cod(v) for k, v in kw.items()}, "saida": self.cod(saida)}
            chave = json.dumps(caso, sort_keys=True)
            if self.par is not None and chave not in self.vistos:
                self.vistos.add(chave)
                self.casos.append(caso)
            return saida
        setattr(transicao, nome, gravado)


def _docstring_starts(tree):
    return {(n.body[0].value.lineno, n.body[0].value.col_offset) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)}


def bench_fingerprint(path=BANCA):
    source = path.read_text(encoding="utf-8")
    docstrings = _docstring_starts(ast.parse(source))
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER}
    kept = [f"{tokenize.tok_name[t.type]} {t.string}" for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type not in skip and not (t.type == tokenize.STRING and t.start in docstrings)]
    return hashlib.sha1("\n".join(kept).encode()).hexdigest()


def grava():
    g = Gravador()
    for nome in _publicas():
        g.embrulha(nome)  # antes de a banca importar o motor: o "from transicao import" dele pega o embrulhado
    sys.argv = [str(BANCA)]
    banca = runpy.run_path(str(BANCA), run_name="banca")
    glob = banca["main"].__globals__
    confere = glob["confere"]

    def confere_gravando(par, *a, **kw):
        g.par = par.nome
        try:
            return confere(par, *a, **kw)
        finally:
            g.par = None
    glob["confere"] = confere_gravando
    if glob["main"]() != 0:
        print("FALHA a banca das passagens falhou: nada foi gravado")
        return 1
    if any(Path(m.__file__).resolve().parent != RAIZ for m in (glob["eng"], transicao)):
        print("FALHA a banca rodou outro motor que nao o deste checkout")
        return 1
    dados = {"sobre": "gerado por: python dev/testa_transicao.py --grava (as chamadas do motor ao transicao.py nos "
                      "pares da banca das passagens)",
             "bench": bench_fingerprint(), "colunas": g.colunas, "niveis": g.niveis, "casos": g.casos}
    CASOS.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    por_fn = {}
    for c in g.casos:
        por_fn[c["fn"]] = por_fn.get(c["fn"], 0) + 1
    print(f"gravados {len(g.casos)} casos em {CASOS.name} ({len(g.niveis)} niveis): "
          + ", ".join(f"{n} {k}" for n, k in sorted(por_fn.items())))
    return 0


def _dec(v, niveis, colunas):
    if isinstance(v, dict) and "niv" in v:
        d = niveis[v["niv"]]
        t, q = _de_b64(colunas[d["t"]], np.float64), _de_b64(colunas[d["q"]], np.int64)
        r = (_de_b64(colunas[d["r32"]], np.float32).astype(np.float64) if "r32" in d
             else _de_b64(colunas[d["r"]], np.float64))
        return [(float(a), int(b), float(c)) for a, b, c in zip(t, q, r)]
    if isinstance(v, dict) and "nd" in v:
        return _de_b64(v["z"], np.dtype(v["nd"])).reshape(v["shape"])
    if isinstance(v, list):
        return [_dec(x, niveis, colunas) for x in v]
    return v


def _igual(a, b):
    """O que voltou (a) contra o gravado (b): bool e None iguais, inteiro inteiro e igual (o motor usa como tamanho de
    array), o resto a TOL, lista item a item."""
    if isinstance(b, bool) or b is None:
        return a is b or (isinstance(a, (bool, np.bool_)) and bool(a) == b)
    if isinstance(a, (bool, np.bool_)):
        return False
    if isinstance(b, int):
        return isinstance(a, (int, np.integer)) and int(a) == b
    if isinstance(b, float):
        return isinstance(a, (int, float, np.integer, np.floating)) and math.isclose(float(a), b, rel_tol=TOL,
                                                                                      abs_tol=TOL)
    if isinstance(b, list):
        return isinstance(a, (list, tuple)) and len(a) == len(b) and all(_igual(x, y) for x, y in zip(a, b))
    return a == b


def engine_takes_the_excerpt_from_transicao():
    tree = ast.parse((RAIZ / "engine.py").read_text(encoding="utf-8"))
    plan = next((n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Engine" for n in c.body
                 if isinstance(n, ast.FunctionDef) and n.name == "_plano_dois"), None)
    if plan is None:
        return ["engine.py has no Engine._plano_dois"]
    expected = {"i2": "saida_a(swap)", "i1": "transicao.phase_excerpt_start(saida_a(virar - FASE_ANTES_S), i2)"}
    stores = {name: [] for name in expected}
    for node in ast.walk(plan):
        if isinstance(node, ast.Name) and node.id in stores and not isinstance(node.ctx, ast.Load):
            stores[node.id].append(node)
    failures = []
    for name, source in expected.items():
        values = [n.value for n in ast.walk(plan) if isinstance(n, ast.Assign) and len(n.targets) == 1
                  and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
        want = ast.dump(ast.parse(source, mode="eval").body)
        if len(stores[name]) != 1 or len(values) != 1 or ast.dump(values[0]) != want:
            failures.append(f"Engine._plano_dois sets {name} only as {name} = {source} "
                            f"({[ast.unparse(v) for v in values]}, {len(stores[name])} store(s))")
    return failures


def phase_excerpt_stays_after_the_outgoing_ramp():
    virar = 100.0
    failures = []
    for sa in (1 + transicao.SAI_MAX, 1 - transicao.SAI_MAX):
        n_ra, ideal_start = transicao.rampa_saida(sa, virar)
        ramp_start = ideal_start + transicao.BLOCK / transicao.SR
        ramp_end = ramp_start + n_ra * (1 + sa) / 2 / transicao.SR

        def output_at(t):
            return n_ra + round((t - ramp_end) * transicao.SR / sa)
        swap = output_at(virar)
        start = transicao.phase_excerpt_start(output_at(virar - transicao.FASE_ANTES_S), swap)
        start_on_disc = ramp_end + (start - n_ra) * sa / transicao.SR
        length = (swap - start) / transicao.SR
        print(f"sa {sa:.2f}: the phase excerpt starts at {start_on_disc:.2f} s of the disc and lasts {length:.2f} s "
              f"of output; the speed ramp ends at {ramp_end:.2f} s, the swap is at {virar:.2f} s")
        if start < n_ra:
            failures.append(f"with the outgoing track at {sa:.2f}, the phase excerpt (transicao.phase_excerpt_start) "
                            f"starts at {start_on_disc:.2f} s of the disc, inside its speed ramp (until "
                            f"{ramp_end:.2f} s)")
        if length < transicao.FASE_MIN_S:
            failures.append(f"with the outgoing track at {sa:.2f}, the phase excerpt (transicao.phase_excerpt_start) "
                            f"lasts {length:.2f} s of output, less than FASE_MIN_S ({transicao.FASE_MIN_S} s)")
    return failures


def confere():
    if not CASOS.exists():
        print(f"FALHA sem {CASOS.name}: python dev/testa_transicao.py --grava")
        return 1
    dados = json.loads(CASOS.read_text(encoding="utf-8"))
    colunas, niveis, casos = dados["colunas"], dados["niveis"], dados["casos"]
    falhas, por_fn = [], {}
    for i, c in enumerate(casos):
        por_fn[c["fn"]] = por_fn.get(c["fn"], 0) + 1
        f = getattr(transicao, c["fn"], None)
        if f is None:
            falhas.append(f"caso {i} ({c['par']}): o transicao.py nao tem mais {c['fn']}")
            continue
        args = [_dec(a, niveis, colunas) for a in c["args"]]
        kw = {k: _dec(v, niveis, colunas) for k, v in c["kw"].items()}
        saida = f(*args, **kw)
        if not _igual(saida, c["saida"]):
            falhas.append(f"caso {i} ({c['par']}): {c['fn']} voltou {saida!r}, gravado {c['saida']!r}")
    pares = sorted({c["par"] for c in casos})
    print(f"{len(casos)} casos de {len(pares)} pares ({', '.join(pares)}): "
          + ", ".join(f"{n} {k}" for n, k in sorted(por_fn.items())))
    sem = [n for n in _publicas() if n not in por_fn]
    if sem:
        falhas.append(f"funcao publica do transicao.py sem caso gravado: {', '.join(sem)}")
    if dados.get("bench") != bench_fingerprint():
        falhas.append(f"the bench ({BANCA.name}) changed since {CASOS.name} was recorded: python dev/testa_transicao.py "
                      "--grava")
    falhas += phase_excerpt_stays_after_the_outgoing_ramp() + engine_takes_the_excerpt_from_transicao()
    for f in falhas:
        print(f"FALHA {f}")
    print("ok" if not falhas else f"{len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grava", action="store_true", help="roda a banca e regrava o JSON")
    sys.exit(grava() if ap.parse_args().grava else confere())
