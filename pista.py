"""O processo da troca de voz (o pedal de troca de voz, #129): le a voz crua do microfone pelo anel do filtro
(microfone/injeta.py), converte pelo conversor.py e escreve a convertida na pista da voz, que o filtro poe no lugar da
voz do microfone, com a musica do app por cima. Quem sobe e o pistavoz.py (ritmelli.py --pistavoz '<json>'), num
processo a parte: a conta na placa de video nao disputa o interpretador com o audio do app.

json: engine e voz (as pastas dos modelos), tom (semitons), provedor ("dml" ou "cpu").
Pela saida padrao: "pronto" quando a voz convertida comecou a sair, "erro: <motivo>" se nao deu. Pela entrada padrao:
"sair"; entrada fechada (o app caiu) tambem. Ao sair, a pista desliga e a voz do microfone volta na hora."""
import collections
import ctypes
import json
import queue
import sys
import threading
import time

import numpy as np

from microfone import injeta

SR = 48000
COLCHAO = SR * 120 // 1000   # 120 ms de silencio na frente da primeira voz: a folga contra um bloco que demora
RETEM_S = 0.1                # a primeira voz espera ate isso um filtro pegar a pista (ver laco)
ANEL_S = 10                  # o anel so existe com o microfone do app aberto: espera ate isso por ele


def diz(texto):
    print(texto, flush=True)


class Para48k:
    """A voz crua na taxa do microfone -> 48 kHz, linear e com estado entre os pedacos (o mesmo do engine.py)."""

    def __init__(self):
        self.taxa, self.ult, self.fase = 0, 0.0, 0.0

    def __call__(self, x, taxa):
        if taxa in (0, SR) or not len(x):
            return x
        if taxa != self.taxa:
            self.taxa, self.ult, self.fase = taxa, float(x[0]), 0.0
        passo = taxa / SR
        y = np.concatenate([[self.ult], x]).astype(np.float64)
        t = np.arange(self.fase, len(x), passo)
        out = np.interp(t, np.arange(len(y)), y).astype(np.float32)
        self.fase = (t[-1] + passo - len(x)) if len(t) else self.fase - len(x)
        self.ult = float(x[-1])
        return out


class Pista:
    """A voz crua -> o conversor -> a pista. A conta roda numa thread so dela; o laco da pista nunca espera por ela
    (segue lendo a voz e batendo o pulso, senao o filtro devolve a voz do microfone)."""

    def __init__(self, m, conv):
        self.m, self.conv = m, conv
        self.entra = queue.SimpleQueue()
        self.sai, self.trava = collections.deque(), threading.Lock()
        self.vai = True
        self.est = {"blocos": 0, "secas": 0, "conta_ms_max": 0.0, "voz_taxa": 0}
        self.erro = None

    def _conta(self):
        from conversor import mmcss
        mmcss()
        while self.vai:
            x = self.entra.get()
            if x is None:
                return
            t0 = time.perf_counter()
            try:
                y = self.conv.bloco(x)
            except Exception as ex:  # noqa: BLE001 - a voz volta para o microfone e o app fica sabendo
                self.erro = f"{type(ex).__name__}: {ex}"
                self.vai = False
                return
            self.est["conta_ms_max"] = round(max(self.est["conta_ms_max"], (time.perf_counter() - t0) * 1000), 1)
            with self.trava:
                self.sai.append(y)

    def laco(self):
        from conversor import N, mmcss
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
        mmcss()
        threading.Thread(target=self._conta, daemon=True, name="conta").start()
        para48 = Para48k()
        acum, comecou, seca, retido, retem_ate = np.zeros(0, np.float32), False, False, [], 0.0
        try:
            while self.vai:
                if comecou:
                    self.m.pista_pulso()  # a pista e nossa enquanto este processo roda
                x, taxa = self.m.voz()
                if len(x):
                    self.est["voz_taxa"] = int(taxa)
                    acum = np.concatenate([acum, para48(x, taxa)])
                    while len(acum) >= N:
                        self.entra.put(np.ascontiguousarray(acum[:N], np.float32))
                        acum = acum[N:]
                with self.trava:
                    prontos = list(self.sai)
                    self.sai.clear()
                for y in prontos:
                    if not comecou:
                        comecou = True
                        self.m.pista_liga(True)  # a voz do microfone sai agora: a convertida ja chegou
                        self.m.pista_escreve(np.zeros(COLCHAO, np.float32))
                        diz("pronto")
                        retem_ate = time.perf_counter() + RETEM_S
                    retido.append(y)
                # o filtro so comeca do ponto em que a pista ligou se o que esta escrito dali couber na metade da pista:
                # o colchao mais o primeiro bloco passam disso, e ele pularia para o mais novo, jogando o colchao fora.
                # A primeira voz espera um filtro pegar a pista (fila > 0) ou ate RETEM_S
                if retido and not (self.m.pista_na_fila() == 0 and time.perf_counter() < retem_ate):
                    for y in retido:
                        self.m.pista_escreve(y)
                        self.est["blocos"] += 1
                    retido.clear()
                if comecou:
                    vazia = self.m.pista_na_fila() == 0
                    if vazia and not seca:
                        self.est["secas"] += 1
                    seca = vazia
                time.sleep(0.001)
        finally:
            self.vai = False
            self.entra.put(None)
            self.m.pista_liga(False)  # a voz do microfone volta na hora
            winmm.timeEndPeriod(1)


def main(args):
    cfg = json.loads(args[0])
    m, t0 = None, time.monotonic()
    while m is None:
        try:
            m = injeta.Microfone()
        except injeta.SemFiltro as ex:
            if time.monotonic() - t0 > ANEL_S:
                diz(f"erro: no microphone filter ({ex})")
                return 3
            time.sleep(0.25)
    try:
        import conversor
        if cfg.get("provedor", "dml") == "dml":
            conversor.tempo_real()
        conv = conversor.Conversor(cfg["engine"], cfg["voz"], tom=float(cfg.get("tom", 0)),
                                   provedor=cfg.get("provedor", "dml"))
    except Exception as ex:  # noqa: BLE001 - sem o motor nao ha pedal: o app fica sabendo por que
        diz(f"erro: the voice engine didn't start ({type(ex).__name__}: {ex})")
        m.fecha()
        return 2
    p = Pista(m, conv)
    t = threading.Thread(target=p.laco, daemon=True, name="pista")
    t.start()
    sair = threading.Event()

    def ouve():
        for linha in sys.stdin:
            if linha.strip() == "sair":
                break
        sair.set()  # "sair", ou a entrada fechou (o app caiu)
    threading.Thread(target=ouve, daemon=True, name="entrada").start()
    while p.vai and not sair.wait(0.2):
        pass
    p.vai = False
    t.join(timeout=2)
    m.fecha()
    if p.erro:
        diz(f"erro: {p.erro}")
    print("fim " + json.dumps(p.est), file=sys.stderr, flush=True)
    return 0
