"""Testa o pedal de troca de voz (o contrato do API.md, "Pedal de troca de voz") sem o modulo de fora: um pistavoz de
mentira no sys.modules. Cobre o fx.py (o modulo que nao cumpre o contrato conta como ausente, com o motivo no log; com
ele, o pistavoz entra no lugar do alien, na mesma posicao, com as vozes no /api/effects; sem ele, o alien volta), o
estado do pedal no Estado (a voz que nao e das VOZES sai como a primeira, o passo que nao e dos tres sai null, o
progresso em passos de 1/12 e so no ouvindo, o erro do estado() vai para o log uma vez), o liga() do motor (na ordem
das trocas, numa thread so dele, o erro dele no log sem parar a thread, o False do fechar esperado e nada depois dele) e
o escolhe() do servidor (na fila dele, na ordem dos pedidos, numa thread so dele, o pedido cancelado antes da vez nao
chega ao modulo e o erro volta para quem pediu; o escolhe_voz com o prazo de 15 s do API.md: vencido o prazo, False, e
o pedido que esperava na fila nao chega ao modulo; um TimeoutError do proprio modulo sobe como erro, nao como prazo).

    python dev/testa_pedal_voz.py

Precisa das dependencias do app (numpy, pedalboard, aiohttp): fica fora do passo so com a biblioteca padrao do CI, como o
testa_adianta. Sai 1 se algo falhar."""
import asyncio
import contextlib
import importlib
import importlib.machinery
import io
import queue
import sys
import threading
import types
import unittest
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# o pistavoz de verdade (se estiver ao lado do codigo) fica de fora: cada teste poe o dele
sys.modules["pistavoz"] = None
import dryouts
import engine
import fx
import server


def falso(**campos):
    """Um pistavoz de mentira; o __spec__ e o que o find_spec do fx.py le no sys.modules."""
    m = types.ModuleType("pistavoz")
    m.__spec__ = importlib.machinery.ModuleSpec("pistavoz", None)
    m.__dict__.update(campos)
    return m


def com(mod):
    """O fx.py recarregado com este pistavoz (None = ausente), e o log dele."""
    sys.modules["pistavoz"] = mod
    with contextlib.redirect_stderr(io.StringIO()) as log:
        importlib.reload(fx)
    return log.getvalue()


def stamp(t):
    return 1 + round(t * 1000) % (2**32 - 1)


class PedalVoz(unittest.TestCase):
    def setUp(self):
        self.ligas, self.estado = [], {"voz": "lira", "visor": None, "progresso": None}
        self.mod = falso(VOZES=["mina", "lira"], estado=lambda: self.estado, escolhe=lambda v: None,
                         liga=lambda on: self.ligas.append((on, threading.current_thread().name)))
        server.App._pedal_voz_erro = None

    def tearDown(self):
        com(None)

    def test_contrato_quebrado_e_ausente(self):
        for mod, motivo in ((falso(VOZES=[], estado=print, escolhe=print, liga=print), "VOZES"),
                            (falso(VOZES="mina", estado=print, escolhe=print, liga=print), "VOZES"),
                            (falso(VOZES=["mina"], estado=print, escolhe=print), "liga")):
            log = com(mod)
            self.assertIsNone(fx.pistavoz, motivo)
            self.assertIn(motivo, log, "o motivo vai para o log")
            self.assertIn("alien", [e["id"] for e in fx.lista()], "sem o pedal, o alienigena fica")

    def test_impedimento(self):
        """Sem placa de video ou sem as vozes, o impedimento() diz o motivo: o pedal fica de fora, como modulo ausente."""
        def quebra():
            raise OSError("dxgi")
        for imp, motivo in ((lambda: "no graphics card for DirectML", "no graphics card"), (quebra, "dxgi")):
            self.mod.impedimento = imp
            log = com(self.mod)
            self.assertIsNone(fx.pistavoz, motivo)
            self.assertIn(motivo, log, "o motivo vai para o log")
            self.assertIn("alien", [e["id"] for e in fx.lista()], "sem o pedal, o alienigena fica")
        self.mod.impedimento = lambda: None
        com(self.mod)
        self.assertIs(fx.pistavoz, self.mod, "sem motivo, o pedal entra")

    def test_no_lugar_do_alien(self):
        com(None)
        ids = [e["id"] for e in fx.lista()]
        com(self.mod)
        lista = fx.lista()
        self.assertEqual([e["id"] for e in lista], [("pistavoz" if i == "alien" else i) for i in ids])
        self.assertEqual(next(e for e in lista if e["id"] == "pistavoz")["vozes"], ["mina", "lira"])
        self.assertIsNone(fx.criar("pistavoz"), "o efeito daqui nao mexe na voz")

    def test_estado(self):
        com(self.mod)
        casos = [({"voz": "lira"}, {"voz": "lira", "visor": None, "progresso": None}),
                 ({"voz": "outra"}, {"voz": "mina", "visor": None, "progresso": None}),
                 ({"voz": "mina", "visor": "calibrando"}, {"voz": "mina", "visor": None, "progresso": None}),
                 ({"voz": "mina", "visor": "ouvindo", "progresso": 0.49}, {"voz": "mina", "visor": "ouvindo", "progresso": 0.5}),
                 ({"voz": "mina", "visor": "ouvindo", "progresso": 7}, {"voz": "mina", "visor": "ouvindo", "progresso": 1.0}),
                 ({"voz": "mina", "visor": "ouvindo", "progresso": True}, {"voz": "mina", "visor": "ouvindo", "progresso": None}),
                 ({"voz": "mina", "visor": "ouvindo", "progresso": float("nan")}, {"voz": "mina", "visor": "ouvindo", "progresso": None}),
                 ({"voz": "mina", "visor": "pronto", "progresso": 0.5}, {"voz": "mina", "visor": "pronto", "progresso": None}),
                 (None, {"voz": "mina", "visor": None, "progresso": None})]
        for e, esperado in casos:
            self.estado = e
            self.assertEqual(server.App.pedal_voz(), esperado, e)

    def test_erro_do_estado_uma_vez_no_log(self):
        com(self.mod)

        def quebra():
            raise RuntimeError("sem placa")
        self.mod.estado = quebra
        with contextlib.redirect_stderr(io.StringIO()) as log:
            for _ in range(3):
                self.assertEqual(server.App.pedal_voz(), {"voz": "mina", "visor": None, "progresso": None})
        self.assertEqual(log.getvalue().count("estado() failed"), 1, "um erro igual sai uma vez, nao a cada tick")

    def test_records_when_the_pedal_turned_on(self):
        com(self.mod)
        e = engine.Engine.__new__(engine.Engine)
        e._pv_fila, e._pv_fechada, e.voice_pedal = None, False, dryouts.VoicePedalStart()
        self.addCleanup(e._pedal_voz_fecha)
        self.assertIsNone(e.voice_pedal.on_at, "before the pedal turns on")
        e._pedal_voz_liga(True)
        first = e.voice_pedal.on_at
        self.assertIsNotNone(first, "the pedal turned on")
        e._pedal_voz_liga(True)
        self.assertEqual(e.voice_pedal.on_at, first, "on again while on keeps when it first turned on")
        e._pedal_voz_liga(False)
        self.assertIsNone(e.voice_pedal.on_at, "the pedal turned off")
        e._pedal_voz_liga(True)
        self.assertGreaterEqual(e.voice_pedal.on_at, first, "on after off is a new start")

    def test_a_track_of_the_process_still_stopping_is_not_the_next_starts(self):
        now, entered, release, sent = [1.0], threading.Event(), threading.Event(), queue.SimpleQueue()

        def liga(on):
            if not on:
                entered.set()
                release.wait(5)
            sent.put(on)
        self.mod.liga = liga
        com(self.mod)
        e = engine.Engine.__new__(engine.Engine)
        e._pv_fila, e._pv_fechada, e.voice_pedal = None, False, dryouts.VoicePedalStart(clock=lambda: now[0])
        self.addCleanup(e._pedal_voz_fecha)
        self.addCleanup(release.set)
        e._pedal_voz_liga(True)
        self.assertIs(sent.get(timeout=5), True)
        now[0] = 1.5
        e._pedal_voz_liga(False)
        self.assertTrue(entered.wait(5))
        now[0] = 2.1
        e._pedal_voz_liga(True)
        now[0] = 2.3
        with contextlib.redirect_stderr(io.StringIO()) as log:
            e.voice_pedal.track(True, stamp(2.2))
        self.assertEqual((log.getvalue(), e.voice_pedal.starting()[1]),
                         ("", "the pedal turned on 0.20 s ago, its voice track isn't up yet"),
                         "the track came up while the process of the first start was still stopping")
        now[0] = 2.4
        release.set()
        self.assertEqual((sent.get(timeout=5), sent.get(timeout=5)), (False, True))
        now[0] = 2.6
        with contextlib.redirect_stderr(io.StringIO()) as log:
            e.voice_pedal.track(True, stamp(2.5))
        self.assertIn("voice pedal: its voice track came up 0.40 s after the pedal turned on", log.getvalue())

    def test_liga_na_ordem_e_fecha(self):
        com(self.mod)
        e = engine.Engine.__new__(engine.Engine)
        e._pv_fila, e._pv_fechada, e.voice_pedal = None, False, dryouts.VoicePedalStart()
        quebrou = []

        def liga(on):
            if not quebrou:
                quebrou.append(on)
                raise RuntimeError("primeira falha")
            self.ligas.append((on, threading.current_thread().name))
        self.mod.liga = liga
        with contextlib.redirect_stderr(io.StringIO()) as log:
            for on in (True, False, True, True):
                e._pedal_voz_liga(on)
            e._pedal_voz_fecha()
        self.assertIn("liga() failed", log.getvalue())
        self.assertEqual(self.ligas, [(False, "pedal_voz"), (True, "pedal_voz"), (True, "pedal_voz"), (False, "pedal_voz")],
                         "na ordem, na thread dele, e o fechar espera o False")
        e._pedal_voz_liga(True)
        e._pedal_voz_fecha()
        self.assertEqual(len(self.ligas), 4, "depois de fechar, nada mais chega ao modulo")

    def test_escolhe_na_ordem(self):
        chegou, solta = [], threading.Event()

        def escolhe(v):
            if v == "espera":   # segura a thread: os pedidos de depois ficam na fila
                solta.wait(2)
            chegou.append((v, threading.current_thread().name))
            if v == "quebra":
                raise RuntimeError("sem placa")
            if v == "sai":   # o SystemExit do modulo vira RuntimeError para quem pediu, e o laco segue
                raise SystemExit(3)
            return v
        pedidos = {v: Future() for v in ("espera", "cancelado", "mina", "quebra", "sai", "lira")}
        for v, fut in pedidos.items():
            server.fila_voz.put((fut, escolhe, v))
        self.assertTrue(pedidos["cancelado"].cancel(), "o pedido ainda na fila se cancela")
        solta.set()
        self.assertEqual(pedidos["lira"].result(2), "lira")
        self.assertEqual(chegou, [(v, "pedal_voz_escolhe") for v in ("espera", "mina", "quebra", "sai", "lira")],
                         "na ordem, na thread dela, e o cancelado nao chega ao modulo")
        self.assertEqual(pedidos["mina"].result(0), "mina")
        with self.assertRaisesRegex(RuntimeError, "sem placa"):
            pedidos["quebra"].result(0)
        with self.assertRaisesRegex(RuntimeError, "SystemExit"):
            pedidos["sai"].result(0)

    def test_escolhe_com_prazo(self):
        chegou, solta = [], threading.Event()

        def escolhe(v):
            chegou.append(v)
            if v == "trava":   # o modulo travado: segura a thread ate o fim do teste
                solta.wait(2)
            if v == "estoura":
                raise TimeoutError("do modulo")

        async def dois():
            trava = asyncio.ensure_future(server.escolhe_voz(escolhe, "trava", .05))
            na_fila = asyncio.ensure_future(server.escolhe_voz(escolhe, "na-fila", .05))
            return await trava, await na_fila
        self.assertEqual(asyncio.run(dois()), (False, False), "o prazo vence no travado e no que esperava atras dele")
        solta.set()
        with self.assertRaisesRegex(TimeoutError, "do modulo"):
            asyncio.run(server.escolhe_voz(escolhe, "estoura", 2))
        self.assertEqual(chegou, ["trava", "estoura"], "o que venceu na fila nao chega ao modulo")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
