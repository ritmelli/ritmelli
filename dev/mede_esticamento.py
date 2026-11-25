# manual: python dev/mede_esticamento.py [--carga N] precisa de uns minutos de CPU so para ela (mede tempo real e nao tem veredito)
r"""Mede se o esticamento da passagem (o esticar e o esticar_saida do engine.py, pela Rubber Band) seca o anel do jogo, e
se ele num processo a parte, abaixo do normal (como o --andamento), secaria menos no mesmo prazo do plano.

O motor de verdade toca, em tempo real, os pares da banca que esticam (dev/testa_passagem.py: seco, fade e dois, os
mesmos WAV sinteticos), com a saida para o jogo no Injetor de verdade escrevendo no AnelFalso do
dev/testa_microfone.py (o leitor que tira 10 ms a cada 10 ms, como o audiodg, num anel Local\ so da medida). O
AnelFalso roda num processo dele, de prioridade alta, como o audiodg: no processo do motor, a parada do interpretador
parava o leitor junto e escondia a seca. Em cada passagem, do preparar ate a decisao publicada e meio segundo depois,
conta: as secas do Injetor (o anel vazio quando a thread voltou), as faltas do leitor (o filtro soltaria silencio), a
pior volta da thread e o menor tanto no anel; e o tempo do plano (o "planned in" do log do motor) e o ramo.

Os modos, com o mesmo audio e a mesma carga:
  - local: o esticar e o esticar_saida no processo do motor, como o app faz hoje;
  - auxiliar: os dois num processo a parte (este script com --serve), aberto abaixo do normal antes da passagem (o
    caso bom dele: o import do motor e das bibliotecas ja feito; o tempo de abrir sai na medida, a parte). O pedido vai
    por cano: o x em float32, e volta a saida e as posicoes. Sem resposta em PRAZO_AUX_S, a chamada falha e o motor
    faz a passagem so de volume, como faz com qualquer erro do plano.

A primeira passagem do processo (a do par seco) para o interpretador uns 30 ms e seca uma vez, com o esticamento aqui
ou no auxiliar (e o resto do planejador na primeira vez): uma passagem vai antes, como aquecimento, fora da conta.

--aux-normal: o auxiliar na prioridade normal, e nao abaixo dela (para comparar).

--carga N: N processos ocupando a CPU na prioridade normal (o jogo) durante cada passagem, e mortos no fim dela; o
dobro dos nucleos faz o papel de um PC mais fraco. Cada passagem dura de 5 a 25 s; com --vezes 3, os tres pares e os
dois modos, ~4 min.

    python dev/mede_esticamento.py [--carga N] [--vezes K] [--modo local auxiliar] [--par seco fade dois]
                                   [--aux-normal] [--json saida.json] [-v]

Manual (a linha do topo): mede tempo real, depende da maquina e nao tem veredito. Nao abre aparelho de som, o anel
Global\ do filtro de verdade nem conexao nenhuma. Mas e uma medida do PC onde roda, e nao a de um Windows de teste com
o filtro e um jogo de verdade. Como o dev/mede_folga.py, com a saida redirecionada o script se solta do console (preso
a um console, o interpretador para de 10 a 25 ms com a CPU cheia, paradas que o app nao tem); --console mantem. O
resultado de 25/11 esta no docs/arquitetura/engine.md.
"""
import argparse
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

DEV = Path(__file__).resolve().parent
RAIZ = DEV.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(1, str(DEV))

AQUECE_S = 2.0      # A toca isso (o leitor e o anel assentam) antes do preparar
DEPOIS_S = 0.5      # a janela da medida vai ate isso depois da decisao publicada
PRAZO_PLANO_S = 60.0
PRAZO_AUX_S = 20.0  # sem resposta do auxiliar nisso, a chamada falha (o motor passa so pelo volume)
PARES = ("seco", "fade", "dois")  # os pares da banca que esticam (o recusado nao chama a Rubber Band)
ABAIXO_DO_NORMAL = 0x00004000
ALTA = 0x00000080  # o leitor, no lugar do audiodg


def _anel():
    """O leitor num processo a parte: cria o AnelFalso, diz o nome dele e le ate o stdin fechar; "zera" zera as faltas
    e "conta" devolve quantas foram."""
    import testa_microfone as tm  # noqa: PLC0415
    from microfone import injeta  # noqa: PLC0415
    anel = tm.AnelFalso()
    anel.liga()
    print(injeta.MAPA, flush=True)
    for linha in sys.stdin:
        if linha.strip() == "zera":
            anel.faltou = 0
            anel.lido.clear()
        print(anel.faltou, flush=True)
    anel.desliga()


class Leitor:
    """O AnelFalso do processo a parte, visto daqui."""

    def __init__(self, eng):
        self.p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--anel"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, cwd=str(RAIZ), creationflags=ALTA | eng.NO_WINDOW)
        self.nome = self.p.stdout.readline().strip()
        if not self.nome:
            raise RuntimeError("o leitor nao subiu")

    def _pede(self, o_que):
        self.p.stdin.write(o_que + "\n")
        self.p.stdin.flush()
        return int(self.p.stdout.readline())

    def zera(self):
        self._pede("zera")

    def faltas(self):
        return self._pede("conta")

    def fecha(self):
        with contextlib.suppress(Exception):
            self.p.stdin.close()
        try:
            self.p.wait(5)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()


def _serve():
    """O auxiliar: le pedidos do stdin (uma linha JSON e o x em float32) e responde (uma linha JSON, a saida em float32 e
    as posicoes em float64), ate o stdin fechar."""
    import engine as eng  # noqa: PLC0415 - so o auxiliar carrega o motor aqui
    ent, sai = sys.stdin.buffer, sys.stdout.buffer
    sai.write(b"pronto\n")
    sai.flush()
    while True:
        linha = ent.readline()
        if not linha:
            return
        p = json.loads(linha)
        x = np.frombuffer(ent.read(p["n"] * 8), np.float32).reshape(-1, 2)
        f = eng.esticar if p["f"] == "esticar" else eng.esticar_saida
        z, phi = f(x, *p["args"])
        z, phi = np.ascontiguousarray(z, np.float32), np.ascontiguousarray(phi, np.float64)
        sai.write(json.dumps({"n": len(z), "m": len(phi)}).encode() + b"\n")
        sai.write(z.tobytes())
        sai.write(phi.tobytes())
        sai.flush()


class Auxiliar:
    """O processo a parte do modo auxiliar, um pedido por vez."""

    def __init__(self, eng, normal):
        t = time.perf_counter()
        self.p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, cwd=str(RAIZ),
                                  creationflags=(0 if normal else ABAIXO_DO_NORMAL) | eng.NO_WINDOW)
        if self.p.stdout.readline() != b"pronto\n":
            raise RuntimeError("o auxiliar nao subiu")
        self.abrir_s = time.perf_counter() - t
        self.lock = threading.Lock()
        self.chamadas = []  # (funcao, segundos, amostras de x)

    def chama(self, f, x, *args):
        x = np.ascontiguousarray(x, np.float32)
        with self.lock:
            t = time.perf_counter()
            res = {}

            def _troca():
                try:
                    self.p.stdin.write(json.dumps({"f": f, "n": len(x), "args": [float(a) if isinstance(a, float)
                                                                                    else int(a) for a in args]}
                                                  ).encode() + b"\n")
                    self.p.stdin.write(x.tobytes())
                    self.p.stdin.flush()
                    h = json.loads(self.p.stdout.readline())
                    z = np.frombuffer(self.p.stdout.read(h["n"] * 8), np.float32).reshape(-1, 2).copy()
                    phi = np.frombuffer(self.p.stdout.read(h["m"] * 8), np.float64).copy()
                    res["ok"] = (z, phi)
                except Exception as ex:  # noqa: BLE001 - vai para quem chamou
                    res["erro"] = ex
            th = threading.Thread(target=_troca, daemon=True)
            th.start()
            th.join(PRAZO_AUX_S)
            self.chamadas.append((f, time.perf_counter() - t, len(x)))
            if th.is_alive():
                self.p.kill()  # o pedido pela metade estraga o cano: o auxiliar nao serve mais
                raise TimeoutError(f"the stretch helper didn't answer in {PRAZO_AUX_S:.0f} s")
            if "erro" in res:
                raise res["erro"]
            return res["ok"]

    def fecha(self):
        with contextlib.suppress(Exception):
            self.p.stdin.close()
        try:
            self.p.wait(5)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()


def _p99(h):
    acum = np.cumsum(h)
    return int(np.searchsorted(acum, 0.99 * acum[-1])) if acum[-1] else None


def passa(eng, banca, tm, fx, modo, carga, aux_normal, verboso):
    """Uma passagem em tempo real, do comeco de A ate a decisao publicada: o que a medida viu."""
    from microfone import injeta  # noqa: PLC0415
    log = banca.Log(verboso)
    aux = Auxiliar(eng, aux_normal) if modo == "auxiliar" else None
    orig = eng.esticar, eng.esticar_saida
    chamadas = aux.chamadas if aux is not None else []  # (funcao, segundos, amostras de x)

    def _local(nome, f):
        def cronometra(x, *a):
            t = time.perf_counter()
            try:
                return f(x, *a)
            finally:
                chamadas.append((nome, time.perf_counter() - t, len(x)))
        return cronometra
    if aux is not None:
        eng.esticar = lambda x, *a: aux.chama("esticar", x, *a)
        eng.esticar_saida = lambda x, *a: aux.chama("esticar_saida", x, *a)
    else:
        eng.esticar, eng.esticar_saida = _local("esticar", orig[0]), _local("esticar_saida", orig[1])
    ocupa = [subprocess.Popen([sys.executable, "-c", "while True: pass"], creationflags=eng.NO_WINDOW)
             for _ in range(carga)]
    anel = Leitor(eng)
    injeta.MAPA = anel.nome
    e = inj = None
    try:
        with contextlib.redirect_stderr(log):
            e = eng.Engine("mede", "")
            e.active = {"mic": "mede", "monitor": ""}
            e._alvo = tm.ALVO  # noqa: SLF001 - o microfone que o AnelFalso le
            e.vol, e.volume_auto = 1.0, False
            e.load(fx["a"], start=fx["inicio"])
            inj = eng.Injetor(e)
            banca._espera(lambda: inj.leitores and e.pos >= fx["inicio"] + AQUECE_S, 15.0, "A nao tocou")  # noqa: SLF001
            inj.secas, inj.folga_min, inj.volta_max = 0, None, 0.0
            inj.voltas[:] = 0
            anel.zera()
            t0 = time.perf_counter()
            if not e.preparar(fx["b"], "mede"):
                raise banca.Falha("o preparar recusou B")
            banca._espera(lambda: log.acha("transition: on beat:") or log.acha("transition: beats not aligned:"),  # noqa: SLF001
                          PRAZO_PLANO_S, "o planejador nao publicou a decisao")
            ate_decisao = time.perf_counter() - t0
            time.sleep(DEPOIS_S)
            secas, faltou = inj.secas, anel.faltas()
            volta_max, folga_min, p99 = inj.volta_max, inj.folga_min, _p99(inj.voltas)
    finally:
        if inj is not None:
            inj.para()
        anel.fecha()
        if e is not None:
            with contextlib.redirect_stderr(log):
                e._cancela_passagem(tudo=True)  # noqa: SLF001
                e._deck.gen += 1  # noqa: SLF001
        for p in ocupa:
            p.kill()
        for p in ocupa:
            p.wait()
        eng.esticar, eng.esticar_saida = orig
        if aux is not None:
            aux.fecha()
    decisao = log.acha("transition: on beat:") or log.acha("transition: beats not aligned:")
    plano = log.acha("transition: prepared ")
    plano_s = float(plano.split("planned in ")[1].split(" s")[0]) if plano else None
    return {"modo": modo, "carga": carga, "ramo": banca._ramo(decisao), "decisao": decisao,  # noqa: SLF001
            "plano_s": plano_s, "ate_decisao_s": round(ate_decisao, 2), "secas": secas, "faltou": faltou,
            "volta_max_ms": round(volta_max * 1000, 1), "volta_p99_ms": p99,
            "menor_no_anel_ms": None if folga_min is None else round(folga_min * 1000 / eng.SR, 1),
            "auxiliar_abrir_s": None if aux is None else round(aux.abrir_s, 2),
            "chamadas": [(f, round(s, 2)) for f, s, _ in chamadas]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--anel", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--aux-normal", action="store_true", help="o auxiliar na prioridade normal")
    ap.add_argument("--carga", type=int, default=0, help="processos ocupando a CPU (padrao: nenhum)")
    ap.add_argument("--vezes", type=int, default=3, help="passagens de cada par em cada modo (padrao: 3)")
    ap.add_argument("--modo", nargs="+", choices=("local", "auxiliar"), default=["local", "auxiliar"])
    ap.add_argument("--par", nargs="+", choices=PARES, default=list(PARES))
    ap.add_argument("--json", type=Path, help="grava as passagens medidas neste arquivo")
    ap.add_argument("--console", action="store_true", help="fica preso ao console")
    ap.add_argument("-v", action="store_true", help="mostra o log do motor")
    a = ap.parse_args()
    if a.serve:
        return _serve()
    if a.anel:
        return _anel()
    if not a.console and not sys.stdout.isatty() and not sys.stderr.isatty():
        import ctypes  # noqa: PLC0415
        ctypes.windll.kernel32.FreeConsole()  # sem console, como o executavel: a saida ja vai para arquivo ou cano
    sys.stdout.reconfigure(encoding="utf-8")
    argv, sys.argv = sys.argv, sys.argv[:1]  # a banca e o teste do microfone leem os argumentos deles ao importar
    try:
        import testa_microfone as tm  # noqa: PLC0415 - poe o MICFX_MAPA num nome Local\ so do teste, antes do motor
        import testa_passagem as banca  # noqa: PLC0415
    finally:
        sys.argv = argv
    eng = banca.eng
    eng._processo_acima()  # noqa: SLF001 - como o app
    tmp = Path(tempfile.mkdtemp(prefix="ritmelli-estica-"))
    eng.pastas.LOGS = tmp / "logs"  # o registro do fim de cada passagem vai para a pasta temporaria
    feitas = []
    try:
        pares = {p.nome: p for p in banca.PARES}
        fxs = {n: banca.monta(pares[n], tmp / n) for n in a.par}
        # a primeira passagem do processo para o interpretador uns 30 ms (com o esticamento aqui ou no auxiliar: e o
        # resto do planejador na primeira vez), e fica fora da conta
        r = passa(eng, banca, tm, fxs[a.par[0]], "local", 0, a.aux_normal, a.v)
        print(f"aquecimento (fora da conta): secas {r['secas']}, volta max {r['volta_max_ms']} ms", flush=True)
        for k in range(a.vezes):
            for n in a.par:
                for modo in a.modo:  # alternados: a maquina muda devagar, e os dois modos veem a mesma
                    r = passa(eng, banca, tm, fxs[n], modo, a.carga, a.aux_normal, a.v)
                    r.update(par=n, vez=k + 1, aux_normal=a.aux_normal)
                    feitas.append(r)
                    print(f"{n:5} {modo:8} carga {a.carga}: {r['ramo']:5} plano {r['plano_s']} s (decisao em "
                          f"{r['ate_decisao_s']} s); secas {r['secas']}, faltas do leitor {r['faltou']}, volta max "
                          f"{r['volta_max_ms']} ms (p99 {r['volta_p99_ms']}), menor no anel {r['menor_no_anel_ms']} ms;"
                          f" chamadas {r['chamadas']}"
                          + (f"; auxiliar aberto em {r['auxiliar_abrir_s']} s" if modo == "auxiliar" else ""),
                          flush=True)
    finally:
        time.sleep(0.2)  # os leitores e a onda fecham o ffmpeg dos WAV
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nresumo (soma das secas e das faltas; plano: mediana e maior)")
    for modo in a.modo:
        rs = [r for r in feitas if r["modo"] == modo]
        pl = [r["plano_s"] for r in rs if r["plano_s"] is not None]
        print(f"  {modo:8} carga {a.carga}: {len(rs)} passagens; secas {sum(r['secas'] for r in rs)}, faltas "
              f"{sum(r['faltou'] for r in rs)}; volta max {max(r['volta_max_ms'] for r in rs)} ms; plano "
              f"{np.median(pl):.2f} s (maior {max(pl):.2f}); ramos {sorted({r['ramo'] for r in rs})}")
    if a.json:
        a.json.write_text(json.dumps(feitas, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
