"""Testa o aparelho mudo (#136) sem som e sem mexer no audio do PC: um sounddevice de mentira tem um aparelho que abre
sem erro e nao entrega quadro nenhum (a UMC 404HD depois do reinicio do audio), um que so acorda na segunda abertura,
um que recusa abrir (em uso exclusivo por outro programa) e os normais.

Confere: a conferencia acha o mudo, da a segunda chance (e o que acorda nela nao e mudo), nao conta o que nem abriu
como mudo, pula o [Loopback] e os aparelhos fora do WASAPI, fecha tudo que abriu (o que abriu e nao comecou tambem),
toca silencio nas saidas e, com nomes, so abre esses; sem o sounddevice, None. O nome do aparelho e o ultimo
parentese, com os de dentro. Depois de mexer no audio: so a DLL nova reinicia so o servico de audio (o
AudioEndpointBuilder fica), microfone novo reinicia os dois, nada novo nao reinicia nada, e o reinicio confere os
aparelhos (no instalador e na tarefa; a desinstalacao nao confere e apaga os mudos do registro). Os mudos vao para o
registro (numa chave so do teste, no HKCU) e, com o resumo da conferencia, para o --saida; uma conferencia que nao
conferiu nada nao apaga os de antes; a que trava sai do processo sem esperar o driver. No app: o aviso tem um nome por
aparelho, a primeira conferencia com o filtro pronto confere so os mudos do registro (nenhum: nenhum processo), a
preparacao do microfone confere todos depois de reabrir, e o aviso sai quando o audio reabre. A conferencia do app
roda num processo a parte, pela linha de comando de verdade (com um nome que nao existe, entao nenhum aparelho abre),
e o log diz por que ela nao deu. O instalador: com o Inno Setup 6 no PC, monta um setup que nao instala nada, so com o
instalador/mudos.iss e um [Run] que roda o main de verdade do microfone.py (com o instala_todos trocado), roda em
silencio e confere no log o resumo e os aparelhos que a ultima pagina mostraria (com acento, com aspas, nenhum, sem
conferencia e sem o arquivo). Com --tela, abre esse setup na tela, com dois aparelhos mudos, para ver a ultima pagina
(em pt e em en).

    python dev/testa_aparelho_mudo.py
    python dev/testa_aparelho_mudo.py --tela

Sai 1 se algo falhar.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import winreg
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng
from microfone import injeta
from microfone import microfone as filtro

UMC_IN = "IN 1-2 (BEHRINGER UMC 404HD 192k)"
UMC_OUT = "OUT 1-2 (BEHRINGER UMC 404HD 192k)"
MIC = "Microfone (Realtek High Definition Audio)"
FONE = "Alto-falantes (Realtek High Definition Audio)"
ACORDA = "Headset (Fone Bluetooth)"
EXCLUSIVO = "Linha (Placa Em Uso)"
NAO_COMECA = "Entrada (Driver Que Abre E Nao Comeca)"
ESPERA = 0.2  # o tempo de cada aparelho no teste (no app, CONFERE_S)


class Fluxo:
    """Um stream do sounddevice de mentira: o normal chama o callback a cada 10 ms de uma thread, como o PortAudio; o
    mudo abre e nunca chama."""

    def __init__(self, sd, tipo, device, channels, samplerate, dtype, extra_settings, callback):
        d = sd.devs[device]
        self.sd, self.tipo, self.nome, self.canais, self.cb = sd, tipo, d["name"], channels, callback
        if d["_jeito"] == "recusa":
            raise RuntimeError("Error opening stream: Device unavailable [PaErrorCode -9985]")
        sd.aberturas[self.nome] = sd.aberturas.get(self.nome, 0) + 1
        self.mudo = d["_jeito"] == "mudo" or (d["_jeito"] == "acorda" and sd.aberturas[self.nome] == 1)
        self.nao_comeca = d["_jeito"] == "nao_comeca"
        self.fim = threading.Event()
        sd.abertos.add(self)

    def start(self):
        if self.nao_comeca:
            raise RuntimeError("Error starting stream: Unanticipated host error [PaErrorCode -9999]")
        if not self.mudo:
            threading.Thread(target=self._roda, daemon=True).start()

    def _roda(self):
        while not self.fim.wait(0.01):
            dados = np.ones((480, self.canais), np.float32)
            self.cb(dados, 480, None, None)
            if self.tipo == "out":
                self.sd.saidas.append(float(np.abs(dados).max()))

    def close(self):
        self.fim.set()
        self.sd.abertos.discard(self)


class SdFalso:
    def __init__(self, extra=()):
        # (nome, host api, entradas, saidas, jeito); a host api 0 e o MME, a 1 o WASAPI
        lista = [(UMC_IN, 1, 2, 0, "mudo"), (UMC_OUT, 1, 0, 2, "mudo"), (MIC, 1, 2, 0, "normal"),
                 (FONE, 1, 0, 2, "normal"), (FONE + " [Loopback]", 1, 2, 0, "nunca"), (UMC_IN, 0, 2, 0, "nunca"),
                 (EXCLUSIVO, 1, 2, 0, "recusa"), *extra]
        self.devs = [{"name": n, "hostapi": h, "max_input_channels": i, "max_output_channels": o,
                      "default_samplerate": 48000.0, "_jeito": j} for n, h, i, o, j in lista]
        self.aberturas, self.abertos, self.saidas = {}, set(), []

    def query_hostapis(self):
        return [{"name": "MME"}, {"name": "Windows WASAPI"}]

    def query_devices(self):
        return self.devs

    def WasapiSettings(self, auto_convert=False):  # o nome do sounddevice
        return object()

    def InputStream(self, **kw):
        d = self.devs[kw["device"]]
        if d["_jeito"] == "nunca":
            raise AssertionError(f"abriu {d['name']} (host api {d['hostapi']})")
        return Fluxo(self, "in", **kw)

    def OutputStream(self, **kw):
        return Fluxo(self, "out", **kw)


class Chamadas:
    """Guarda as chamadas de quem trocou: o nome e os argumentos, na ordem."""

    def __init__(self):
        self.lista = []

    def __call__(self, nome, volta=None):
        def f(*a, **k):
            self.lista.append((nome, a, k))
            return volta(*a, **k) if callable(volta) else volta
        return f

    def nomes(self):
        return [n for n, _, _ in self.lista]


class TestaConferencia(unittest.TestCase):
    def test_acha_o_mudo_e_nada_mais(self):
        sd = SdFalso()
        t0 = time.monotonic()
        r = filtro.confere_aparelhos(espera_s=ESPERA, sd=sd)
        dt = time.monotonic() - t0
        self.assertEqual(r["mudos"], sorted([UMC_IN, UMC_OUT]))
        self.assertEqual(r["falhas"], [EXCLUSIVO], "o que nem abriu nao e mudo")
        self.assertEqual(r["conferidos"], sorted([UMC_IN, UMC_OUT, MIC, FONE]))
        self.assertEqual(sd.aberturas[UMC_IN], 2, "o mudo tem a segunda chance")
        self.assertEqual(sd.aberturas[MIC], 1, "o que entregou nao abre de novo")
        self.assertFalse(sd.abertos, "tudo que abriu fecha")
        self.assertTrue(sd.saidas and max(sd.saidas) == 0.0, "a saida conferida toca silencio")
        self.assertLess(dt, ESPERA + 1.0 + 2 * ESPERA + 3.0, "sem esperas a mais (com folga para um PC ocupado)")

    def test_o_que_abre_e_nao_comeca_fecha(self):
        sd = SdFalso([(NAO_COMECA, 1, 2, 0, "nao_comeca")])
        r = filtro.confere_aparelhos(espera_s=ESPERA, sd=sd)
        self.assertIn(NAO_COMECA, r["falhas"], "nao comecou: conta como nao aberto, nao como mudo")
        self.assertNotIn(NAO_COMECA, r["mudos"])
        self.assertFalse(sd.abertos, "o stream que abriu e nao comecou tambem fecha")

    def test_o_que_acorda_na_segunda_nao_e_mudo(self):
        sd = SdFalso([(ACORDA, 1, 1, 0, "acorda")])
        r = filtro.confere_aparelhos(espera_s=ESPERA, sd=sd)
        self.assertNotIn(ACORDA, r["mudos"])
        self.assertIn(ACORDA, r["conferidos"])
        self.assertEqual(sd.aberturas[ACORDA], 2)

    def test_sem_mudo_nao_espera(self):
        sd = SdFalso()
        sd.devs = [d for d in sd.devs if d["_jeito"] != "mudo"]
        t0 = time.monotonic()
        r = filtro.confere_aparelhos(espera_s=2.0, sd=sd)
        self.assertEqual(r["mudos"], [])
        self.assertLess(time.monotonic() - t0, 1.5, "sem mudo, sai no primeiro quadro de cada, sem esperar os 2 s")

    def test_com_nomes_so_esses(self):
        sd = SdFalso()
        r = filtro.confere_aparelhos([UMC_OUT, MIC], espera_s=ESPERA, sd=sd)
        self.assertEqual(set(sd.aberturas), {UMC_OUT, MIC})
        self.assertEqual(r["mudos"], [UMC_OUT])
        r = filtro.confere_aparelhos(["nenhum"], espera_s=ESPERA, sd=SdFalso())
        self.assertEqual(r, {"conferidos": [], "mudos": [], "falhas": []})

    def test_mudo_que_recusa_a_segunda_abertura(self):
        """Abriu mudo e recusou a segunda abertura: sem medida, vai para as falhas, e nao para os conferidos (com ele
        so, nada conferido: o registro de antes fica)."""
        sd = SdFalso()
        abre = sd.InputStream

        def so_uma(**kw):
            if sd.aberturas.get(UMC_IN):
                raise RuntimeError("Error opening stream: Device unavailable [PaErrorCode -9985]")
            return abre(**kw)
        sd.InputStream = so_uma
        r = filtro.confere_aparelhos([UMC_IN], espera_s=ESPERA, sd=sd)
        self.assertEqual(r, {"conferidos": [], "mudos": [], "falhas": [UMC_IN]})

    def test_sem_sounddevice(self):
        with mock.patch.dict(sys.modules, {"sounddevice": None}):
            self.assertIsNone(filtro.confere_aparelhos(espera_s=ESPERA))

    def test_aparelho_de(self):
        for nome, quer in ((UMC_IN, "BEHRINGER UMC 404HD 192k"),
                           ("IN 2 (2- BEHRINGER UMC 404HD 192k)", "2- BEHRINGER UMC 404HD 192k"),
                           ("Digital Audio (S/PDIF) (High Definition Audio Device)", "High Definition Audio Device"),
                           ("Alto-falantes (Realtek(R) Audio)", "Realtek(R) Audio"),
                           ("Sem parentese", "Sem parentese"), ("(So o parentese)", "(So o parentese)"),
                           ("Sem fechar (o parentese", "Sem fechar (o parentese"), ("Sobra um)", "Sobra um)")):
            self.assertEqual(filtro.aparelho_de(nome), quer, nome)
        self.assertEqual(filtro.aparelhos_de([UMC_IN, MIC, UMC_OUT]),
                         ["BEHRINGER UMC 404HD 192k", "Realtek High Definition Audio"], "um por aparelho, na ordem")


class TestaReinicio(unittest.TestCase):
    def setUp(self):
        self.c = Chamadas()
        self.protegida = True
        # nada de verdade: nenhum servico, nenhum regsvr32, nenhuma pasta de programas
        self.p = [mock.patch.object(filtro.subprocess, "run", self.c("run")),
                  mock.patch.object(filtro, "servico_audio", self.c("servico_audio")),
                  mock.patch.object(filtro, "_depois_do_reinicio", self.c("confere", {"mudos": [UMC_IN]})),
                  mock.patch.object(filtro, "_protegida", lambda: self.protegida),
                  mock.patch.object(filtro, "_apaga_registro_com", self.c("apaga_com")),
                  mock.patch.object(filtro, "PASTA", tempfile.gettempdir() + r"\ritmelli-teste-nao-existe")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in reversed(self.p):
            p.stop()

    def _construtor(self):
        return [a[0] for n, a, _ in self.c.lista if n == "run" and "AudioEndpointBuilder" in " ".join(a[0])]

    def test_so_o_servico(self):
        for rodando, acao in ((True, "Restart"), (False, "Start")):
            self.c.lista.clear()
            with mock.patch.object(filtro, "audio_rodando", lambda r=rodando: r):
                filtro.reinicia_audio(so_servico=True)
            self.assertEqual(self._construtor(), [], "so a DLL: o AudioEndpointBuilder fica")
            self.assertEqual([a for n, a, _ in self.c.lista if n == "servico_audio"], [(acao,)])
        self.c.lista.clear()
        filtro.reinicia_audio()
        self.assertEqual(len(self._construtor()), 1, "microfone novo: o AudioEndpointBuilder reinicia")
        self.assertEqual([a for n, a, _ in self.c.lista if n == "servico_audio"], [("Start",)])

    def _instala_todos(self, parou, novos):
        self.c.lista.clear()
        mics = [("{a}", "IN 1", "X"), ("{b}", "IN 2", "Y")]
        with mock.patch.object(filtro, "_prepara_dll", lambda dll: parou), \
                mock.patch.object(filtro, "microfones", lambda todos=False: mics), \
                mock.patch.object(filtro, "_pendura", lambda ep: ep in novos), \
                mock.patch.object(filtro, "reinicia_audio", self.c("reinicia")), redirect_stdout(io.StringIO()):
            return filtro.instala_todos("micfx.dll")

    def test_instala_todos(self):
        r = self._instala_todos(parou=True, novos=())
        self.assertEqual(self.c.lista[0], ("reinicia", (), {"so_servico": True}), "so a DLL mudou")
        self.assertEqual(self.c.nomes(), ["reinicia", "confere"])
        self.assertEqual(r, {"mudos": [UMC_IN]})
        self._instala_todos(parou=True, novos=("{b}",))
        self.assertEqual(self.c.lista[0], ("reinicia", (), {"so_servico": False}), "microfone novo")
        self._instala_todos(parou=False, novos=("{a}",))
        self.assertEqual(self.c.lista[0], ("reinicia", (), {"so_servico": False}))
        self.assertEqual(self.c.nomes(), ["reinicia", "confere"])
        r = self._instala_todos(parou=False, novos=())
        self.assertEqual(self.c.nomes(), [], "nada novo: nem reinicia nem confere")
        self.assertIsNone(r)

    def test_instala_um(self):
        for parou, novo, quer in ((True, False, True), (False, True, False), (True, True, False), (False, False, None)):
            self.c.lista.clear()
            with mock.patch.object(filtro, "acha", lambda f: ("{a}", "IN 1", "X")), \
                    mock.patch.object(filtro, "_prepara_dll", lambda dll, p=parou: p), \
                    mock.patch.object(filtro, "_pendura", lambda ep, n=novo: n), \
                    mock.patch.object(filtro, "reinicia_audio", self.c("reinicia")), redirect_stdout(io.StringIO()):
                r = filtro.instala("IN 1", "micfx.dll")
            if quer is None:
                self.assertEqual(self.c.nomes(), [])
                self.assertIsNone(r)
            else:
                self.assertEqual(self.c.lista[0], ("reinicia", (), {"so_servico": quer}), (parou, novo))
                self.assertEqual(self.c.nomes(), ["reinicia", "confere"])

    def _remove(self, sobra):
        self.c.lista.clear()
        with mock.patch.object(filtro, "microfones", lambda todos=False: [("{a}", "IN 1", "X")]), \
                mock.patch.object(filtro, "_devolve", lambda ep: True), \
                mock.patch.object(filtro, "tem_filtro", lambda ep: sobra), \
                mock.patch.object(filtro, "reinicia_audio", self.c("reinicia")), \
                mock.patch.object(filtro, "tarefa_apaga", self.c("tarefa_apaga")), \
                mock.patch.object(filtro, "_esquece_hospedes", self.c("esquece")), \
                mock.patch.object(filtro, "grava_mudos", self.c("grava_mudos")), redirect_stdout(io.StringIO()):
            return filtro.remove()

    def test_remove(self):
        r = self._remove(sobra=False)
        self.assertEqual(self.c.nomes(), ["reinicia", "tarefa_apaga", "esquece", "grava_mudos"],
                         "desinstalando: sem conferencia (nao sobra app para avisar)")
        self.assertEqual(self.c.lista[-1][1], ([],), "e apaga os mudos de antes")
        self.assertIsNone(r)
        r = self._remove(sobra=True)
        self.assertEqual(self.c.nomes(), ["reinicia", "confere"], "sobrou filtro: confere e grava, como ao instalar")
        self.assertEqual(r, {"mudos": [UMC_IN]})

    def test_remove_reprovada(self):
        """Com a pasta do app reprovada (pastas.pasta_protegida), o remove devolve os microfones e sai com erro, sem
        conferir: o sounddevice de la nao e carregado. Desinstalando, os mudos saem do registro do mesmo jeito."""
        import pastas
        self.protegida = pastas.Reprovada("test folder")
        for sobra, quer in ((True, ["reinicia"]),
                            (False, ["apaga_com", "reinicia", "tarefa_apaga", "esquece", "grava_mudos"])):
            with self.assertRaises(SystemExit) as fim:
                self._remove(sobra=sobra)
            self.assertTrue(fim.exception.code)
            self.assertEqual(self.c.nomes(), quer, f"sobrou filtro: {sobra}")


class TestaRegistro(unittest.TestCase):
    """Os mudos no registro, numa chave so do teste no HKCU (no app: HKLM\\SOFTWARE\\Ritmelli\\Microfone)."""

    BASE = rf"SOFTWARE\RitmelliTesteMudo-{os.getpid()}"

    def setUp(self):
        self.p = [mock.patch.object(filtro, "RAIZ_MUDOS", winreg.HKEY_CURRENT_USER),
                  mock.patch.object(filtro, "SALVO", self.BASE + r"\Microfone")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in reversed(self.p):
            p.stop()
        for k in (self.BASE + r"\Microfone", self.BASE):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
            except OSError:
                pass

    def _existe(self):
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, filtro.SALVO).Close()
            return True
        except OSError:
            return False

    def test_grava_e_le(self):
        self.assertEqual(filtro.le_mudos(), [])
        filtro.grava_mudos([])
        self.assertFalse(self._existe(), "apagar sem nada gravado nao cria a chave (o desinstalador)")
        filtro.grava_mudos([UMC_IN, UMC_OUT])
        self.assertEqual(filtro.le_mudos(), [UMC_IN, UMC_OUT])
        filtro.grava_mudos([])
        self.assertEqual(filtro.le_mudos(), [])
        self.assertTrue(self._existe(), "so o valor sai")

    def _confere(self, volta):
        with mock.patch.object(filtro, "confere_aparelhos", volta), redirect_stdout(io.StringIO()) as out:
            r = filtro._depois_do_reinicio(assenta_s=0)
        self.assertEqual(out.getvalue().strip(), r["resumo"], "o log e o resumo, a mesma linha do --saida")
        return r

    def test_depois_do_reinicio(self):
        quer = {"conferidos": [UMC_IN, MIC], "mudos": [UMC_IN], "falhas": [EXCLUSIVO]}
        r = self._confere(lambda: quer)
        self.assertEqual({k: r[k] for k in quer}, quer)
        self.assertEqual(r["resumo"], f"devices: 2 checked; silent: {UMC_IN}; couldn't open: {EXCLUSIVO}")
        self.assertFalse(r["travou"])
        self.assertEqual(filtro.le_mudos(), [UMC_IN])
        r = self._confere(lambda: {"conferidos": [], "mudos": [], "falhas": [MIC]})
        self.assertEqual(filtro.le_mudos(), [UMC_IN], "nada conferido: o de antes fica")
        r = self._confere(lambda: None)
        self.assertEqual((r["mudos"], r["resumo"], r["travou"]), ([], "devices: not checked (no sounddevice)", False))
        self.assertEqual(filtro.le_mudos(), [UMC_IN])
        r = self._confere(lambda: {"conferidos": [UMC_IN, MIC], "mudos": [], "falhas": []})
        self.assertEqual(r["resumo"], "devices: 2 checked")
        self.assertEqual(filtro.le_mudos(), [], "o aparelho voltou: sai do registro")
        filtro.grava_mudos([UMC_IN, UMC_OUT])
        r = self._confere(lambda: {"conferidos": [MIC, UMC_OUT], "mudos": [], "falhas": [UMC_IN]})
        self.assertEqual(filtro.le_mudos(), [UMC_IN], "o mudo que nem abriu segue sem medida: fica; o que abriu sai")
        self.assertEqual(r["mudos"], [], "o --saida e so de agora")

    def test_resumo_num_cano_quebrado(self):
        """O print do resumo num cano quebrado nao perde a conferencia: ela volta para o main (o --saida e o os._exit
        da conferencia presa dependem dela)."""
        class Quebrado(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(32, "Broken pipe")
        quer = {"conferidos": [MIC], "mudos": [], "falhas": []}
        with mock.patch.object(filtro, "confere_aparelhos", lambda: quer), mock.patch.object(sys, "stdout", Quebrado()):
            r = filtro._depois_do_reinicio(assenta_s=0)
        self.assertEqual((r["conferidos"], r["resumo"]), ([MIC], "devices: 1 checked"))

    def test_conferencia_que_quebra_ou_trava(self):
        """Um driver que quebra ou trava na conferencia nao segura a instalacao nem mexe no registro."""
        filtro.grava_mudos([UMC_IN])
        r = self._confere(mock.Mock(side_effect=OSError("driver")))
        self.assertEqual((r["mudos"], r["resumo"], r["travou"]), ([], "devices: not checked (OSError: driver)", False))
        solta = threading.Event()
        with mock.patch.object(filtro, "CONFERE_MAX_S", 0.3):
            t0 = time.monotonic()
            r = self._confere(lambda: solta.wait(10))
            self.assertLess(time.monotonic() - t0, 5.0, "o prazo vale, e nao os 10 s do driver")
        solta.set()
        self.assertEqual(r["resumo"], "devices: not checked (still running after 0 s)")
        self.assertTrue(r["travou"], "o main sai sem esperar a thread presa")
        self.assertEqual(filtro.le_mudos(), [UMC_IN], "o de antes fica")


class TestaLinhaDeComando(unittest.TestCase):
    def setUp(self):
        # o main confere a pasta do app antes do instala-todos (pastas.pasta_protegida): a do teste passa
        p = mock.patch.object(filtro, "_protegida", lambda: True)
        p.start()
        self.addCleanup(p.stop)

    def test_saida_tem_os_mudos(self):
        with tempfile.TemporaryDirectory() as tmp:
            dll, saida = Path(tmp) / "micfx.dll", Path(tmp) / "saida.json"
            dll.write_bytes(b"")
            acento = "Microfone (Áudio Ação)"
            mudos = [UMC_IN, UMC_OUT, acento]
            r = {"conferidos": mudos + [MIC], "mudos": mudos, "falhas": [], "travou": False,
                 "resumo": "devices: 4 checked; silent: " + "; ".join(mudos)}
            with mock.patch.object(filtro, "_migra_registro", lambda: None), \
                    mock.patch.object(filtro, "instala_todos", lambda d: r):
                self.assertEqual(filtro.main(["instala-todos", "--dll", str(dll), "--saida", str(saida)]), 0)
            self.assertTrue(saida.read_bytes().isascii(), "o instalador le o --saida em ASCII")
            self.assertEqual(json.loads(saida.read_text("ascii")),
                             {"ok": True, "conferencia": r["resumo"], "mudos": mudos,
                              "aparelhos": ["BEHRINGER UMC 404HD 192k", "Áudio Ação"]}, "um nome por aparelho")
            with mock.patch.object(filtro, "_migra_registro", lambda: None), \
                    mock.patch.object(filtro, "instala_todos", lambda d: None):
                filtro.main(["instala-todos", "--dll", str(dll), "--saida", str(saida)])
            self.assertEqual(json.loads(saida.read_text("utf-8")), {"ok": True}, "sem reinicio, sem conferencia")

    def test_conferencia_presa_nao_segura_o_processo(self):
        """O driver que trava deixa a thread da conferencia dentro do PortAudio, e o atexit do sounddevice (o
        Pa_Terminate) travaria a saida do processo, que o instalador espera sem prazo: aqui, um atexit que dorme uma
        hora. O main grava o --saida e sai na hora."""
        with tempfile.TemporaryDirectory() as tmp:
            script, saida = Path(tmp) / "trava.py", Path(tmp) / "saida.json"
            script.write_text(TRAVA.replace("RAIZ", repr(str(RAIZ))), "utf-8")
            t0 = time.monotonic()
            try:
                p = subprocess.run([sys.executable, str(script), str(saida)], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=60)
            except subprocess.TimeoutExpired:
                self.fail("o processo ficou preso no atexit")
            self.assertLess(time.monotonic() - t0, 30)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(saida.read_text("ascii")),
                             {"ok": True, "conferencia": "devices: not checked (still running after 1 s)", "mudos": [],
                              "aparelhos": []})
            # o --saida que nao grava (a pasta dele nao existe) tambem nao segura o processo: sai na hora, com erro
            t0 = time.monotonic()
            try:
                p = subprocess.run([sys.executable, str(script), str(Path(tmp) / "nao-existe" / "saida.json")],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            except subprocess.TimeoutExpired:
                self.fail("o --saida que falhou deixou o processo preso no atexit")
            self.assertLess(time.monotonic() - t0, 30)
            self.assertEqual(p.returncode, 1, p.stderr)

    def test_confere(self):
        pedido = []
        with mock.patch.object(filtro, "confere_aparelhos", lambda n: pedido.append(n) or {"mudos": n}), \
                mock.patch.object(filtro, "_migra_registro", side_effect=AssertionError("o confere nao migra")), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(filtro.main(["confere", "--aparelho", UMC_IN, "--aparelho", "Ação (Ç)"]), 0)
        self.assertEqual(pedido, [[UMC_IN, "Ação (Ç)"]])
        pedido.clear()
        with mock.patch.object(filtro, "confere_aparelhos", lambda n: pedido.append(n) or {"mudos": []}), \
                redirect_stdout(io.StringIO()):
            filtro.main(["confere", "--aparelho=-Entrada USB (X)"])
        self.assertEqual(pedido, [["-Entrada USB (X)"]], "o nome que comeca com - vai junto do --aparelho=")
        self.assertEqual(json.loads(out.getvalue().strip()), {"mudos": [UMC_IN, "Ação (Ç)"]})
        self.assertTrue(out.getvalue().isascii(), "o JSON sai em ASCII: o cano do executavel nao e UTF-8")

    def test_processo_de_verdade(self):
        """O app roda o ritmelli.py --microfone confere de verdade; com um nome que nao existe, nada abre."""
        r = eng._confere_fora(["nenhum aparelho com este nome (teste)"])
        self.assertEqual(r, {"conferidos": [], "mudos": [], "falhas": []})


class TestaApp(unittest.TestCase):
    def test_aviso(self):
        a = eng._aviso_mudos([UMC_IN, UMC_OUT])
        self.assertEqual(a["key"], "server.devices.silent")
        self.assertEqual(a["params"], {"name": "BEHRINGER UMC 404HD 192k"}, "um nome por aparelho")
        self.assertIn('"BEHRINGER UMC 404HD 192k"', a["text"])
        a = eng._aviso_mudos([UMC_IN, MIC])
        self.assertEqual(a["params"]["name"], 'BEHRINGER UMC 404HD 192k", "Realtek High Definition Audio')

    def test_confere_fora(self):
        c = Chamadas()
        saida = types.SimpleNamespace(stdout='lixo\n{"conferidos": ["x"], "mudos": ["x"], "falhas": []}\n', stderr="")
        with mock.patch.object(eng.subprocess, "run", c("run", saida)):
            r = eng._confere_fora([UMC_IN])
        cmd = c.lista[0][1][0]
        self.assertEqual(cmd[-3:], ["--microfone", "confere", f"--aparelho={UMC_IN}"])
        self.assertEqual(r["mudos"], ["x"])
        quebrou = types.SimpleNamespace(stdout="", stderr="Traceback (most recent call last):\nRuntimeError: boom\n")
        for run, motivo in ((c("run", quebrou), "RuntimeError: boom"),
                            (c("run", types.SimpleNamespace(stdout="lixo", stderr="")), "JSONDecodeError"),
                            (mock.Mock(side_effect=eng.subprocess.TimeoutExpired("x", 60)), "TimeoutExpired")):
            with mock.patch.object(eng.subprocess, "run", run), redirect_stdout(io.StringIO()) as out:
                self.assertIsNone(eng._confere_fora(), "sem a conferencia: sem aviso")
            self.assertIn("devices: not checked", out.getvalue())
            self.assertIn(motivo, out.getvalue(), "o log diz por que")

    def _motor(self, **kw):
        m = types.SimpleNamespace(_aviso=None, _error=None, _mudos_vistos=False, active={"mic": MIC}, _stack=object(),
                                  _preparados=set(), preparando=None, _alvo=0, _fechado=False,
                                  _lock=threading.RLock(), _reabre=mock.Mock(), _confere_mudos=mock.Mock())
        m.__dict__.update(kw)
        return m

    def test_confere_mudos(self):
        m = self._motor()
        for r in (None, {"conferidos": [MIC], "mudos": [], "falhas": []}):
            with mock.patch.object(eng, "_confere_fora", lambda n, r=r: r):
                eng.Engine._confere_mudos(m)
            self.assertIsNone(m._error)
        with mock.patch.object(eng, "_confere_fora", lambda n: {"mudos": [UMC_IN]}), \
                redirect_stdout(io.StringIO()):
            eng.Engine._confere_mudos(m, [UMC_IN])
        self.assertEqual(m._error["key"], "server.devices.silent")
        self.assertIs(m._aviso, m._error, "a device warning: it leaves when the audio reopens")
        # o audio que reabriu, caiu ou fechou durante a conferencia: o resultado e de antes, e fica de fora
        for muda in ({"_stack": object()}, {"_stack": None}, {"_fechado": True}):
            m = self._motor(_mudos_vistos=True)
            m._error = m._aviso = "the earlier one"

            def confere(n, m=m, muda=muda):
                m.__dict__.update(muda)
                return {"mudos": [UMC_IN]}
            with mock.patch.object(eng, "_confere_fora", confere), redirect_stdout(io.StringIO()):
                eng.Engine._confere_mudos(m, [UMC_IN])
            self.assertEqual(m._error, "the earlier one", muda)
            # o audio que caiu durante a conferencia: os do registro ficam para quando ele voltar
            self.assertEqual(m._mudos_vistos, muda.get("_stack", 0) is not None, muda)
        m = self._motor(_stack=None, _mudos_vistos=True)  # o audio fechado (a reabertura que falhou tem o aviso dela)
        with mock.patch.object(eng, "_confere_fora", side_effect=AssertionError("abriu os aparelhos sem audio")):
            eng.Engine._confere_mudos(m)
        self.assertIsNone(m._error)
        self.assertFalse(m._mudos_vistos, "os do registro ficam para quando o audio abrir")

    def test_ao_abrir_so_os_do_registro(self):
        ok = {"filtro": True, "melhorias": True, "guid": "{a}"}
        with mock.patch.object(eng, "_do_microfone", lambda mic: ok), \
                mock.patch.object(injeta, "hash_microfone", lambda g: 7):
            m = self._motor()
            with mock.patch.object(filtro, "le_mudos", lambda: [UMC_IN]):
                eng.Engine._confere_filtro(m, MIC)
                m._confere_mudos.assert_called_once_with([UMC_IN])
                eng.Engine._confere_filtro(m, MIC)
                m._confere_mudos.assert_called_once()  # so na primeira
            m = self._motor()
            with mock.patch.object(filtro, "le_mudos", lambda: []):
                eng.Engine._confere_filtro(m, MIC)
            m._confere_mudos.assert_not_called()  # nenhum no registro: nenhum processo
            # o _confere_filtro tira o aviso dos aparelhos (o de preparar o microfone), mas nao o dos mudos: ele
            # acabou de sair desta pilha (a conferencia depois da tarefa) e sai quando o audio reabre (o start)
            m._error = m._aviso = {"key": "server.mic.preparing", "params": {}, "text": "x"}
            eng.Engine._confere_filtro(m, MIC)
            self.assertIsNone(m._error)
            m._error = m._aviso = eng._aviso_mudos([UMC_IN])
            eng.Engine._confere_filtro(m, MIC)
            self.assertEqual(m._error["key"], "server.devices.silent")

    def test_depois_de_preparar_confere_todos(self):
        sem = {"filtro": False, "melhorias": True, "guid": "{a}"}
        for r, quer in (({"ok": True}, True), ({"ok": False, "motivo": "audio"}, False)):
            m = self._motor()
            ordem = []
            m._reabre.side_effect = lambda m=m: ordem.append(("reabre", m._mudos_vistos))
            m._confere_mudos.side_effect = lambda *a: ordem.append(("confere", a))
            with mock.patch.object(eng, "_do_microfone", lambda mic: sem), \
                    mock.patch.object(filtro, "pede_tarefa", lambda mic, r=r: r), \
                    mock.patch.object(filtro, "le_mudos", side_effect=AssertionError("ja confere todos")):
                eng.Engine._confere_filtro(m, MIC)
            self.assertEqual(ordem, [("reabre", True), ("confere", ())] if quer else [], r)
            self.assertEqual(m._mudos_vistos, quer, "os do registro entram na de todos; sem ela, ficam para depois")
        m = self._motor(_fechado=True)  # o motor fechou enquanto a tarefa rodava: nem reabre nem confere
        with mock.patch.object(eng, "_do_microfone", lambda mic: sem), \
                mock.patch.object(filtro, "pede_tarefa", lambda mic: {"ok": True}):
            eng.Engine._confere_filtro(m, MIC)
        m._reabre.assert_not_called()
        m._confere_mudos.assert_not_called()

    def test_registro_depois_de_preparar_que_falhou(self):
        """A preparacao que falhou nao gasta a conferencia dos mudos do registro: ela vem na proxima vez com filtro."""
        sem = {"filtro": False, "melhorias": True, "guid": "{a}"}
        ok = {"filtro": True, "melhorias": True, "guid": "{b}"}
        m = self._motor()
        with mock.patch.object(eng, "_do_microfone", lambda mic: sem), \
                mock.patch.object(filtro, "pede_tarefa", lambda mic: {"ok": False, "motivo": "audio"}):
            eng.Engine._confere_filtro(m, MIC)
        m._confere_mudos.assert_not_called()
        with mock.patch.object(eng, "_do_microfone", lambda mic: ok), \
                mock.patch.object(injeta, "hash_microfone", lambda g: 7), \
                mock.patch.object(filtro, "le_mudos", lambda: [UMC_IN]):
            eng.Engine._confere_filtro(m, FONE)  # outro microfone, ja com o filtro
        m._confere_mudos.assert_called_once_with([UMC_IN])


class TestaPedeTarefa(unittest.TestCase):
    """O app pede a tarefa do filtro: o filtro aparece no registro antes de a tarefa reiniciar o audio e conferir os
    aparelhos, entao o audiosrv RUNNING so vale depois de ela acabar (o reabre e a conferencia do app vem depois)."""

    def test_espera_a_tarefa_acabar(self):
        ordem, rodando = [], iter([True, None, False])  # a do meio falhou: ainda rodando, ate o Ready

        def run(cmd, **kw):
            ordem.append(" ".join([os.path.basename(cmd[0]).lower(), *cmd[1:3]]))
            return types.SimpleNamespace(returncode=0, stdout="STATE : 4 RUNNING", stderr="")

        def roda(prazo_s):
            self.assertTrue(5 <= prazo_s <= 10, prazo_s)
            v = next(rodando)
            ordem.append(f"tarefa {v}")
            return v
        with mock.patch.object(filtro, "tarefa_existe", lambda: True), \
                mock.patch.object(filtro.subprocess, "run", run), \
                mock.patch.object(filtro, "do_microfone", lambda n: {"filtro": True, "melhorias": True}), \
                mock.patch.object(filtro, "tarefa_rodando", roda), mock.patch.object(filtro.time, "sleep"):
            self.assertEqual(filtro.pede_tarefa("IN 1"), {"ok": True})
        self.assertEqual(ordem, ["schtasks.exe /run /tn", "tarefa True", "tarefa None", "tarefa False",
                                 "sc.exe query audiosrv"])

    def _pede(self, rodando, sc="STATE : 4 RUNNING", relogio=None):
        ordem = []

        def run(cmd, **kw):
            ordem.append(os.path.basename(cmd[0]).lower())
            return types.SimpleNamespace(returncode=0, stdout=sc, stderr="")
        with mock.patch.object(filtro, "tarefa_existe", lambda: True), \
                mock.patch.object(filtro.subprocess, "run", run), \
                mock.patch.object(filtro, "do_microfone", lambda n: {"filtro": True, "melhorias": True}), \
                mock.patch.object(filtro, "tarefa_rodando", rodando), mock.patch.object(filtro.time, "sleep"), \
                mock.patch.object(filtro.time, "monotonic", relogio or time.monotonic):
            return filtro.pede_tarefa("IN 1"), ordem

    def test_tarefa_presa(self):
        """A tarefa que passa do prazo rodando: falhou, sem olhar o servico (o audio pode nem ter reiniciado)."""
        t = iter(range(0, 10000, 10))
        prazos = []
        r, ordem = self._pede(lambda p: prazos.append(p) or True, relogio=lambda: next(t))
        self.assertEqual(r, {"ok": False, "motivo": "tarefa_falhou", "detalhe": "the task is still running"})
        self.assertNotIn("sc.exe", ordem)
        self.assertEqual((max(prazos), min(prazos)), (10.0, 5.0), "no fim do saldo, a consulta ainda tem 5 s (leva ~1 s)")
        # vista rodando, a consulta que depois passa do prazo (None) conta como rodando: ainda presa
        respostas = iter([True])
        t = iter(range(0, 10000, 10))
        r, ordem = self._pede(lambda p: next(respostas, None), relogio=lambda: next(t))
        self.assertEqual(r, {"ok": False, "motivo": "tarefa_falhou", "detalhe": "the task is still running"})
        self.assertNotIn("sc.exe", ordem)
        # sem nunca ver a tarefa rodando, a consulta sem resposta segue pelo servico, como antes
        r, ordem = self._pede(lambda p: None)
        self.assertEqual((r, ordem), ({"ok": True}, ["schtasks.exe", "sc.exe"]))

    def test_servico_olhado_no_fim_do_prazo(self):
        """A tarefa acabou no fim do prazo: o servico ainda e olhado uma vez."""
        t = iter([0, 1, 1000, 1000, 1000, 1000])
        r, ordem = self._pede(lambda p: False, relogio=lambda: next(t))
        self.assertEqual((r, ordem), ({"ok": True}, ["schtasks.exe", "sc.exe"]))
        t = iter([0, 1, 1000, 1000, 1000, 1000])
        r, _ = self._pede(lambda p: False, sc="STATE : 1 STOPPED", relogio=lambda: next(t))
        self.assertEqual(r, {"ok": False, "motivo": "audio"})

    def test_tarefa_rodando(self):
        for saida, quer in (("Running\r\n", True), ("Queued\r\n", True), ("Ready\r\n", False),
                            ("Disabled\r\n", False), ("", None), ("Unknown\r\n", None)):
            c = Chamadas()
            with mock.patch.object(filtro.subprocess, "run", c("run", types.SimpleNamespace(stdout=saida))):
                self.assertIs(filtro.tarefa_rodando(), quer, saida)
            cmd = c.lista[0][1][0]
            self.assertEqual(cmd[0], filtro.POWERSHELL, "pelo caminho da System32")
            self.assertIn(r"Get-ScheduledTask -TaskPath '\Ritmelli\' -TaskName 'Microfone'", cmd[-1])
            self.assertTrue(c.lista[0][2].get("timeout"), "a consulta tem prazo")
        for erro in (OSError("powershell"), filtro.subprocess.TimeoutExpired("powershell", 10)):
            with mock.patch.object(filtro.subprocess, "run", side_effect=erro):
                self.assertIsNone(filtro.tarefa_rodando(), "sem estado: None (o pede_tarefa decide pelo que ja viu)")


RAIZ = Path(__file__).resolve().parent.parent
_X86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
ISCC = next((p for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                         Path(_X86) / "Inno Setup 6" / "ISCC.exe")
             if p.exists()), None)  # os mesmos lugares do instalador/monta.ps1
ACENTO = "Microfone (Áudio Ação)"
SALA = 'Linha ("Sala" Mixer)'

# o [Run] do setup de teste: o main de verdade do microfone.py, com o instala_todos devolvendo o que o MUDOS_TESTE pede
# (JSON: a lista dos mudos de uma conferencia de 5 aparelhos, null sem reinicio do audio, ou a conferencia inteira;
# "sem" nao grava o arquivo, como um microfone.py que quebrou antes)
AJUDANTE = """import json, os, sys
from unittest import mock
sys.path.insert(0, RAIZ)
from microfone import microfone as filtro
mudos = os.environ["MUDOS_TESTE"]
if mudos != "sem":
    filtro._protegida = lambda: True  # o main confere a pasta do app: a do teste passa
    r = json.loads(mudos)
    if isinstance(r, list):
        r = {"conferidos": ["a"] * 5, "mudos": r, "falhas": [], "travou": False,
             "resumo": "devices: 5 checked" + ("; silent: " + "; ".join(r) if r else "")}
    with mock.patch.object(filtro, "_migra_registro", lambda: None), \\
            mock.patch.object(filtro, "instala_todos", lambda d: r):
        filtro.main(["instala-todos", "--dll", __file__, "--saida", sys.argv[1]])
"""

# a conferencia presa num driver, com o atexit que o sounddevice deixa (o Pa_Terminate) travando a saida
TRAVA = """import atexit, sys, threading, time
from unittest import mock
sys.path.insert(0, RAIZ)
from microfone import microfone as filtro
atexit.register(time.sleep, 3600)
preso = threading.Event()
with mock.patch.object(filtro, "_migra_registro", lambda: None), \\
        mock.patch.object(filtro, "_protegida", lambda: True), \\
        mock.patch.object(filtro, "confere_aparelhos", lambda: preso.wait(3600)), \\
        mock.patch.object(filtro, "CONFERE_MAX_S", 1.0), \\
        mock.patch.object(filtro, "instala_todos", lambda d: filtro._depois_do_reinicio(assenta_s=0)):
    sys.exit(filtro.main(["instala-todos", "--dll", __file__, "--saida", sys.argv[1]]))
"""


def monta_setup(pasta):
    """Um setup que nao instala nada (sem pasta, sem desinstalador, sem administrador), com o instalador/mudos.iss, as
    frases da ultima pagina do ritmelli.iss e o [Run] do AJUDANTE no lugar do ritmelli.exe --microfone."""
    pasta = Path(pasta)
    inst = RAIZ / "instalador"
    ajudante = pasta / "ajudante.py"
    ajudante.write_text(AJUDANTE.replace("RAIZ", repr(str(RAIZ))), "utf-8")
    linhas = [x for x in (inst / "ritmelli.iss").read_text("utf-8-sig").splitlines()
              if x.startswith(("pt.FinishedLabel=", "en.FinishedLabel=", "pt.Abrir=", "en.Abrir="))]
    iss = "\n".join([
        "[Setup]", "AppName=Ritmelli (teste do aparelho mudo)", "AppVersion=0", "CreateAppDir=no", "Uninstallable=no",
        "PrivilegesRequired=lowest", "DisableWelcomePage=yes", "DisableReadyPage=yes", "WizardStyle=modern",
        "ShowLanguageDialog=no", "Compression=none", f"OutputDir={pasta}", "OutputBaseFilename=mudos-teste",
        "[Languages]", 'Name: "en"; MessagesFile: "compiler:Default.isl"',
        f'Name: "pt"; MessagesFile: "{inst / "pt-BR.isl"}"',
        # sem atalho, o Inno usa o FinishedLabelNoIcons: o texto do Ritmelli vai nos dois, como na pagina de verdade
        "[Messages]", *[x for x in linhas if "FinishedLabel" in x],
        *[x.replace("FinishedLabel=", "FinishedLabelNoIcons=") for x in linhas if "FinishedLabel" in x],
        "[CustomMessages]", *[x for x in linhas if "Abrir" in x],
        "[Run]",
        f'Filename: "{sys.executable}"; Parameters: """{ajudante}"" ""{{tmp}}\\microfone.json"""; Flags: runhidden',
        'Filename: "{sys}\\cmd.exe"; Parameters: "/c exit"; Description: "{cm:Abrir}"; '
        "Flags: postinstall nowait skipifsilent runhidden",
        # como no ritmelli.iss: o include antes do [Code], que tem o CurStepChanged sem marca
        f'#include "{inst / "mudos.iss"}"',
        "[Code]", "procedure CurStepChanged(CurStep: TSetupStep);", "begin", "end;", ""])
    (pasta / "mudos-teste.iss").write_bytes(b"\xef\xbb\xbf" + iss.encode("utf-8"))
    r = subprocess.run([str(ISCC), "/Q", str(pasta / "mudos-teste.iss")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise AssertionError(f"o ISCC recusou o mudos.iss ({r.returncode}): {r.stdout}{r.stderr}")
    return pasta / "mudos-teste.exe"


# no GitHub (o job do filtro do testa.yml instala o Inno Setup), sem o ISCC reprova: pular calado tiraria a prova
@unittest.skipIf(ISCC is None and not os.environ.get("GITHUB_ACTIONS"),
                 "sem o Inno Setup 6 (winget install -e --id JRSoftware.InnoSetup)")
class TestaInstalador(unittest.TestCase):
    """A ultima pagina do instalador (instalador/mudos.iss), pelo log do setup em silencio."""

    @classmethod
    def setUpClass(cls):
        if ISCC is None:
            raise AssertionError("sem o Inno Setup 6 no GitHub: o job do filtro do testa.yml instala antes")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.setup = monta_setup(cls.tmp.name)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _log(self, mudos, lingua="en"):
        TestaInstalador.n += 1
        log = Path(self.tmp.name) / f"setup-{self.n}.log"
        env = dict(os.environ, MUDOS_TESTE=mudos if isinstance(mudos, str) else json.dumps(mudos))
        r = subprocess.run([str(self.setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LANG={lingua}",
                            f"/LOG={log}"], env=env, timeout=120)
        self.assertEqual(r.returncode, 0)
        return log.read_bytes().decode("utf-8-sig", errors="replace")

    def test_mudos_no_log(self):
        mudos = [UMC_IN, UMC_OUT, ACENTO, SALA]
        log = self._log(mudos, "pt")
        self.assertIn("aparelhos: devices: 5 checked; silent: " + "; ".join(mudos), log,
                      "o resumo da conferencia, com acento e com aspas")
        self.assertIn('aparelhos mudos: "BEHRINGER UMC 404HD 192k", "Áudio Ação", ""Sala" Mixer"', log,
                      "um nome por aparelho, com acento e com aspas")

    def test_nenhum_mudo(self):
        log = self._log([])
        self.assertIn("aparelhos: devices: 5 checked", log)
        self.assertNotIn("aparelhos mudos", log)
        log = self._log(None)
        self.assertIn("aparelhos: sem conferencia (o audio nao reiniciou", log,
                      "sem reinicio: o log nao finge uma conferencia")
        self.assertNotIn("aparelhos mudos", log)

    def test_nao_conferiu(self):
        r = {"conferidos": [], "mudos": [], "falhas": [], "travou": False,
             "resumo": "devices: not checked (OSError:\tdriver\b\f)"}
        self.assertIn("aparelhos: devices: not checked (OSError: driver  )", self._log(r),
                      "o motivo, com os escapes de controle virando espaco")

    def test_aparelho_com_o_nome_da_chave(self):
        self.assertIn('aparelhos mudos: "aparelhos"', self._log(["aparelhos"]),
                      "um aparelho chamado como a chave do JSON nao esconde a lista")

    def test_sem_o_arquivo(self):
        self.assertIn("aparelhos: sem o microfone.json", self._log("sem"))


if __name__ == "__main__":
    if "--tela" in sys.argv:
        if ISCC is None:
            sys.exit("sem o Inno Setup 6")
        with tempfile.TemporaryDirectory() as tmp:
            setup = monta_setup(tmp)
            for lingua in ("pt", "en"):
                print(f"o setup de teste ({lingua}): feche na ultima pagina")
                subprocess.run([str(setup), f"/LANG={lingua}"], env=dict(os.environ, MUDOS_TESTE=json.dumps(
                    [UMC_IN, UMC_OUT, ACENTO])))
        sys.exit(0)
    unittest.main(verbosity=2)
