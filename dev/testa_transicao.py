r"""As contas da passagem (transicao.py) sobre entradas e saidas gravadas: o dev/testa_transicao.json guarda cada chamada
que o motor fez ao transicao.py nos pares da banca das passagens (dev/testa_passagem.py), com os argumentos e o que
voltou, e este teste chama de novo cada uma e confere que volta o mesmo. Sem som, sem ffmpeg e sem o motor: so o
transicao.py e o numpy. Toda funcao publica do transicao.py tem de ter ao menos um caso gravado.

    python dev/testa_transicao.py            confere os casos gravados
    python dev/testa_transicao.py --grava    roda a banca das passagens neste checkout (precisa do ffmpeg, como ela) e
                                             regrava o JSON com as chamadas que o motor fez

Regravar e para quando uma conta muda de proposito (o PR diz por que) ou quando a banca ganha par: a banca passa antes,
e os casos novos saem do motor de verdade, nunca escritos a mao.

O nivel dos blocos (a lista (t0, quadros, rms) do leitor do motor) vai uma vez so, no "niveis", e cada chamada aponta
para ele; as colunas dele (no "colunas", tambem uma vez cada) e os arrays vao em base64 dos bytes (zlib), para a volta
ser exata.

Sai 1 se algo falha."""
import argparse
import ast
import base64
import hashlib
import inspect
import json
import math
import runpy
import sys
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
             "colunas": g.colunas, "niveis": g.niveis, "casos": g.casos}
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


def engine_constant_from_its_text(name):
    tree = ast.parse((RAIZ / "engine.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                break
    raise LookupError(f"engine.py has no top-level {name} written as a literal")


def phase_excerpt_stays_after_the_outgoing_ramp():
    try:
        fase_min_s = engine_constant_from_its_text("FASE_MIN_S")
    except LookupError as ex:
        return [str(ex)]
    virar = 100.0
    falhas = []
    for sa in (1 + transicao.SAI_MAX, 1 - transicao.SAI_MAX):
        n_ra, ramp_start = transicao.rampa_saida(sa, virar)
        disc_seconds_in_ramp = n_ra * (1 + sa) / 2 / transicao.SR
        ramp_margin = virar - transicao.FASE_ANTES_S - (ramp_start + disc_seconds_in_ramp)
        excerpt_from_switch = max(transicao.FASE_ANTES_S, fase_min_s * sa)
        constant_speed_from_switch = transicao.FASE_ANTES_S + ramp_margin
        exceeds = excerpt_from_switch > constant_speed_from_switch + 1e-9
        print(f"sa {sa:.2f}: max(FASE_ANTES_S, FASE_MIN_S * sa) = {excerpt_from_switch:.2f} s "
              f"{'>' if exceeds else '<='} FASE_ANTES_S + the ramp margin ({ramp_margin:.2f} s) = "
              f"{constant_speed_from_switch:.2f} s")
        if exceeds:
            falhas.append(f"with the outgoing track at {sa:.2f}, FASE_MIN_S ({fase_min_s} s) of its output goes back "
                          f"{excerpt_from_switch:.2f} s of disc from the switch, into its speed ramp, which ends "
                          f"{constant_speed_from_switch:.2f} s before it "
                          f"(FASE_MIN_S * (1 + SAI_MAX) <= FASE_ANTES_S + {ramp_margin:.2f})")
    return falhas


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
    falhas += phase_excerpt_stays_after_the_outgoing_ramp()
    for f in falhas:
        print(f"FALHA {f}")
    print("ok" if not falhas else f"{len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grava", action="store_true", help="roda a banca e regrava o JSON")
    sys.exit(grava() if ap.parse_args().grava else confere())
