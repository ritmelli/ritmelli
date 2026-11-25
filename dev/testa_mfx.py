"""Testa o pendurar e o devolver do filtro nas vagas de efeito de um microfone (microfone/microfone.py), num registro
falso em memoria: nada toca o registro do PC nem reinicia o audio.

Confere, para o microfone do notebook (EFX e MFX da Fortemedia em lista), para um MFX simples, para um microfone sem
MFX, para um MFX sem o modo RAW e para um pendurado pela versao anterior: o hospedeiro no lugar do ultimo MFX do
fabricante (a vaga dele guarda qual, e o registro de APO do fabricante vai para o do hospedeiro), pendurar de novo nao
muda nada, e o devolver deixa as vagas de efeito exatamente como eram.

    python dev/testa_mfx.py

Sai 1 se algo falhar.
"""
import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pastas  # noqa: E402
from microfone import microfone as mf  # noqa: E402


class RegistroFalso:
    """O pedaco do winreg que o microfone.py usa, num dicionario: chave (caminho em minusculo) -> {nome em minusculo:
    (nome, valor, tipo)}. Nome de valor e caminho sem caixa, como no registro."""

    HKEY_LOCAL_MACHINE = "HKLM"
    REG_SZ, REG_MULTI_SZ, REG_DWORD = 1, 7, 4
    KEY_READ, KEY_SET_VALUE, KEY_ALL_ACCESS, KEY_WRITE = 0x20019, 0x2, 0xF003F, 0x20006

    class Chave:
        def __init__(self, reg, caminho):
            self.reg, self.caminho = reg, caminho

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def __init__(self):
        self.chaves = {}

    def _caminho(self, raiz, sub):
        base = raiz.caminho if isinstance(raiz, self.Chave) else raiz
        return f"{base}\\{sub}".lower()

    def OpenKey(self, raiz, sub, reservado=0, acesso=0):  # noqa: N802 - o nome do winreg
        c = self._caminho(raiz, sub)
        if c not in self.chaves:
            raise FileNotFoundError(c)
        return self.Chave(self, c)

    def CreateKeyEx(self, raiz, sub, reservado=0, acesso=0):  # noqa: N802
        c = self._caminho(raiz, sub)
        partes = c.split("\\")
        for i in range(2, len(partes) + 1):  # como no registro de verdade, os pais nascem junto
            self.chaves.setdefault("\\".join(partes[:i]), {})
        return self.Chave(self, c)

    def QueryValueEx(self, chave, nome):  # noqa: N802
        v = self.chaves[chave.caminho].get(nome.lower())
        if v is None:
            raise FileNotFoundError(nome)
        return v[1], v[2]

    def SetValueEx(self, chave, nome, reservado, tipo, valor):  # noqa: N802
        self.chaves[chave.caminho][nome.lower()] = (nome, list(valor) if tipo == self.REG_MULTI_SZ else valor, tipo)

    def DeleteValue(self, chave, nome):  # noqa: N802
        if self.chaves[chave.caminho].pop(nome.lower(), None) is None:
            raise FileNotFoundError(nome)

    def DeleteKey(self, raiz, sub):  # noqa: N802
        del self.chaves[self._caminho(raiz, sub)]

    def EnumValue(self, chave, i):  # noqa: N802
        vs = list(self.chaves[chave.caminho].values())
        if i >= len(vs):
            raise OSError("sem mais valores")
        return vs[i]

    def EnumKey(self, chave, i):  # noqa: N802
        base = chave.caminho + "\\"
        subs = sorted({c[len(base):].split("\\")[0] for c in self.chaves if c.startswith(base)})
        if i >= len(subs):
            raise OSError("sem mais subchaves")
        return subs[i]

    def valores(self, caminho):
        """{nome em minusculo: (valor, tipo)} da chave: o que se compara antes e depois."""
        return {k: (v[1], v[2]) for k, v in self.chaves[caminho.lower()].items()}


EP = "{4f6ea1d0-a906-4f42-83ac-2ab996490575}"
EP2 = "{0b1c2d3e-4f50-4617-8899-aabbccddeeff}"
EFX_FM = "{8338CED2-0837-11DC-8314-0800200C9A66}"  # os APOs da Fortemedia do notebook
MFX_FM = "{70306EF0-7851-11DC-8314-0800200C9A66}"
MFX_OUTRO = "{11111111-2222-4333-8444-555555555555}"
MODOS = [mf.MODO_PADRAO, mf.MODO_RAW, "{FC1CFC9B-B9D6-4CFA-B5E0-4BB2166878B2}",
         "{98951333-B9CD-48B1-A0A3-FF40682D73F7}"]
HOST0, HOST1 = mf.HOSPEDES[0], mf.HOSPEDES[1]


def fx_de(ep):
    return f"HKLM\\{mf.CAPTURA}\\{ep}\\FxProperties"


class Base(unittest.TestCase):
    def setUp(self):
        self.reg = RegistroFalso()
        self._winreg, mf.winreg = mf.winreg, self.reg
        r = self.reg
        # o registro de APO da Fortemedia (o motor le dele as flags e as interfaces) e o padrao do hospedeiro
        fm = r.CreateKeyEx(r.HKEY_LOCAL_MACHINE, f"{mf.APOS}\\{MFX_FM}")
        r.SetValueEx(fm, "FriendlyName", 0, r.REG_SZ, "CFMAPOCAP")
        r.SetValueEx(fm, "Flags", 0, r.REG_DWORD, 0xF)
        r.SetValueEx(fm, "APOInterface0", 0, r.REG_SZ, "{AF5B7468-391D-47FF-B88C-CF5E3B8D546A}")
        r.SetValueEx(fm, "NumAPOInterfaces", 0, r.REG_DWORD, 1)
        for h in mf.HOSPEDES:
            k = r.CreateKeyEx(r.HKEY_LOCAL_MACHINE, f"{mf.APOS}\\{h}")
            r.SetValueEx(k, "FriendlyName", 0, r.REG_SZ, "Ritmelli Microfone (hospedeiro)")
            r.SetValueEx(k, "Flags", 0, r.REG_DWORD, 0xE)

    def tearDown(self):
        mf.winreg = self._winreg

    def microfone(self, fx, ep=EP):
        """Cria o microfone com essas vagas de efeito ({nome: (valor, tipo)}) e as melhorias ligadas."""
        r = self.reg
        props = r.CreateKeyEx(r.HKEY_LOCAL_MACHINE, f"{mf.CAPTURA}\\{ep}\\Properties")
        r.SetValueEx(props, mf.SEM_MELHORIAS, 0, r.REG_DWORD, 0)
        k = r.CreateKeyEx(r.HKEY_LOCAL_MACHINE, f"{mf.CAPTURA}\\{ep}\\FxProperties")
        for nome, (valor, tipo) in fx.items():
            r.SetValueEx(k, nome, 0, tipo, valor)
        return r.valores(fx_de(ep))

    def le(self, nome, ep=EP):
        return self.reg.valores(fx_de(ep)).get(nome.lower(), (None,))[0]

    def vaga(self, n):
        try:
            return self.reg.valores(f"HKLM\\{mf.SALVO}").get(f"_hospede{n}", (None,))[0]
        except KeyError:
            return None

    def notebook(self, ep=EP, mfx=MFX_FM, modos=MODOS):
        """O microfone do notebook antes do Ritmelli: EFX e MFX da Fortemedia em lista, sem SFX."""
        r = self.reg
        return self.microfone({mf.ASSOCIACAO: (mf.KSNODETYPE_ANY, r.REG_SZ),
                               mf.EFX_LISTA: ([EFX_FM], r.REG_MULTI_SZ), mf.MFX_LISTA: ([mfx], r.REG_MULTI_SZ),
                               mf.MODOS_EFX: (list(MODOS), r.REG_MULTI_SZ),
                               mf.MODOS_MFX: (list(modos), r.REG_MULTI_SZ)}, ep)

class TestaMfx(Base):
    def test_notebook(self):
        antes = self.notebook()
        self.assertTrue(mf._pendura(EP))  # noqa: SLF001
        self.assertEqual(self.le(mf.EFX_LISTA), [EFX_FM, mf.CLSID])
        self.assertEqual(self.le(mf.MFX_LISTA), [HOST0], "o hospedeiro no lugar do MFX da Fortemedia")
        self.assertEqual(self.vaga(0), MFX_FM, "a vaga 0 carrega a Fortemedia")
        self.assertEqual(self.le(mf.MODOS_MFX), MODOS, "os modos do MFX sao os do fabricante")
        self.assertEqual(self.le(mf.LFX), mf.CLSID)
        apo = self.reg.valores(f"HKLM\\{mf.APOS}\\{HOST0}")
        self.assertEqual(apo["flags"], (0xF, self.reg.REG_DWORD), "as flags do fabricante no hospedeiro")
        self.assertEqual(apo["apointerface0"][0], "{AF5B7468-391D-47FF-B88C-CF5E3B8D546A}")
        self.assertEqual(apo["friendlyname"][0], "Ritmelli Microfone (hospedeiro)", "o nome fica o nosso")
        k = self.reg.OpenKey("HKLM", f"{mf.CAPTURA}\\{EP}\\FxProperties")
        self.assertTrue(mf.nosso(k))
        self.assertTrue(mf.no_mfx(k))
        self.assertFalse(mf._pendura(EP), "pendurar de novo mudou algo")  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [HOST0])
        self.assertTrue(mf._devolve(EP))  # noqa: SLF001
        self.assertEqual(self.reg.valores(fx_de(EP)), antes, "o devolver nao deixou as vagas como eram")

    def test_dois_mfx_do_fabricante(self):
        """So o ultimo da lista do fabricante vai para dentro do hospedeiro; os da frente ficam."""
        r = self.reg
        antes = self.microfone({mf.MFX_LISTA: ([MFX_OUTRO, MFX_FM], r.REG_MULTI_SZ),
                                mf.MODOS_MFX: (list(MODOS), r.REG_MULTI_SZ)})
        mf._pendura(EP)  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [MFX_OUTRO, HOST0])
        self.assertEqual(self.vaga(0), MFX_FM)
        mf._devolve(EP)  # noqa: SLF001
        self.assertEqual(self.reg.valores(fx_de(EP)), antes)

    def test_mfx_simples(self):
        r = self.reg
        antes = self.microfone({mf.EFX: (EFX_FM, r.REG_SZ), mf.MFX: (MFX_FM, r.REG_SZ),
                                mf.MODOS_MFX: ([mf.MODO_PADRAO, mf.MODO_RAW], r.REG_MULTI_SZ)})
        mf._pendura(EP)  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [HOST0])
        self.assertIsNone(self.le(mf.MFX), "o MFX simples ficou junto com a lista")
        self.assertFalse(mf._pendura(EP))  # noqa: SLF001
        mf._devolve(EP)  # noqa: SLF001
        self.assertEqual(self.reg.valores(fx_de(EP)), antes)

    def test_sem_raw(self):
        """MFX do fabricante que nao cobre o RAW: o raw pula o MFX e ficaria sem musica, entao fica tudo no EFX."""
        antes = self.notebook(modos=[mf.MODO_PADRAO])
        mf._pendura(EP)  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [MFX_FM])
        self.assertIsNone(self.vaga(0))
        k = self.reg.OpenKey("HKLM", f"{mf.CAPTURA}\\{EP}\\FxProperties")
        self.assertFalse(mf.no_mfx(k))
        mf._devolve(EP)  # noqa: SLF001
        self.assertEqual(self.reg.valores(fx_de(EP)), antes)

    def test_sem_mfx(self):
        """Interface de audio sem processamento do fabricante: nada na lista de MFX."""
        antes = self.microfone({})
        mf._pendura(EP)  # noqa: SLF001
        self.assertIsNone(self.le(mf.MFX_LISTA))
        self.assertTrue(mf.nosso(self.reg.OpenKey("HKLM", f"{mf.CAPTURA}\\{EP}\\FxProperties")))
        mf._devolve(EP)  # noqa: SLF001
        self.assertEqual(self.reg.valores(fx_de(EP)), antes)

    def test_vagas_por_fabricante(self):
        """Dois microfones com o mesmo MFX dividem a vaga; outro fabricante pega a seguinte."""
        self.notebook()
        self.notebook(EP2, mfx=MFX_OUTRO)
        mf._pendura(EP)  # noqa: SLF001
        mf._pendura(EP2)  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA, EP2), [HOST1])
        self.assertEqual((self.vaga(0), self.vaga(1)), (MFX_FM, MFX_OUTRO))
        ep3 = "{99999999-0000-4000-8000-000000000003}"
        self.notebook(ep3)
        mf._pendura(ep3)  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA, ep3), [HOST0])
        self.assertIsNone(self.vaga(2))

    def test_sem_vaga_livre(self):
        """As vagas acabaram: a lista do fabricante fica como esta (o EFX segue com a musica)."""
        r = self.reg
        raiz = r.CreateKeyEx(r.HKEY_LOCAL_MACHINE, mf.SALVO)
        for n in range(len(mf.HOSPEDES)):
            r.SetValueEx(raiz, f"_hospede{n}", 0, r.REG_SZ, f"{{0000000{n}-0000-4000-8000-000000000000}}")
        self.notebook()
        mf._pendura(EP)  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [MFX_FM])

    def test_modos_perderam_o_raw(self):
        """Um driver novo tirou o RAW dos modos do MFX: o hospedeiro sai e a Fortemedia volta para a lista."""
        self.notebook()
        mf._pendura(EP)  # noqa: SLF001
        r = self.reg
        r.SetValueEx(r.OpenKey("HKLM", f"{mf.CAPTURA}\\{EP}\\FxProperties"), mf.MODOS_MFX, 0, r.REG_MULTI_SZ,
                     [mf.MODO_PADRAO])
        self.assertTrue(mf._pendura(EP))  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [MFX_FM])

    def test_driver_reescreveu(self):
        """Um driver novo reescreveu a lista com outro MFX: o hospedeiro passa a carregar o novo, em outra vaga."""
        self.notebook()
        mf._pendura(EP)  # noqa: SLF001
        r = self.reg
        r.SetValueEx(r.OpenKey("HKLM", f"{mf.CAPTURA}\\{EP}\\FxProperties"), mf.MFX_LISTA, 0, r.REG_MULTI_SZ,
                     [MFX_OUTRO])
        self.assertTrue(mf._pendura(EP))  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [HOST1])
        self.assertEqual(self.vaga(1), MFX_OUTRO)

    def test_versao_anterior(self):
        """Pendurado pela versao 2 (so EFX e LFX, sem guardar a lista de MFX): pendurar de novo guarda a lista do
        fabricante como original, poe o hospedeiro no lugar, e o devolver volta ao de antes do Ritmelli."""
        antes = self.notebook()
        r = self.reg
        salvo = r.CreateKeyEx(r.HKEY_LOCAL_MACHINE, f"{mf.SALVO}\\{EP}")
        fx = r.OpenKey("HKLM", f"{mf.CAPTURA}\\{EP}\\FxProperties")
        for k in (mf.ASSOCIACAO, mf.EFX_LISTA, mf.MODOS_EFX, mf.MODOS_MFX):  # o que a versao 2 guardava e havia
            v = antes[k.lower()]
            r.SetValueEx(salvo, k, 0, v[1], v[0])
        r.SetValueEx(salvo, "_ausentes", 0, r.REG_MULTI_SZ, [mf.LFX, mf.SFX, mf.MODOS_SFX])
        r.SetValueEx(salvo, "_versao", 0, r.REG_DWORD, 2)
        r.SetValueEx(salvo, "_tinha_sfx", 0, r.REG_DWORD, 0)
        r.SetValueEx(salvo, "_sem_melhorias", 0, r.REG_DWORD, 0)
        r.SetValueEx(fx, mf.EFX_LISTA, 0, r.REG_MULTI_SZ, [EFX_FM, mf.CLSID])
        r.SetValueEx(fx, mf.LFX, 0, r.REG_SZ, mf.CLSID)
        self.assertTrue(mf._pendura(EP))  # noqa: SLF001
        self.assertEqual(self.le(mf.MFX_LISTA), [HOST0])
        self.assertEqual(r.QueryValueEx(salvo, "_versao")[0], mf.VERSAO_SALVO)
        mf._devolve(EP)  # noqa: SLF001
        self.assertEqual(self.reg.valores(fx_de(EP)), antes)

    def test_esquece_hospedes(self):
        self.notebook()
        mf._pendura(EP)  # noqa: SLF001
        mf._esquece_hospedes()  # noqa: SLF001
        self.assertIsNone(self.vaga(0))


class Gravador:
    """O subprocess.run de mentira: guarda cada comando e responde como o Windows (o schtasks /query nao acha a
    tarefa). Com reg e inproc, o regsvr32 grava o InprocServer32 do filtro como o de verdade."""

    def __init__(self, reg=None):
        self.comandos, self.reg = [], reg

    def __call__(self, args, **kw):
        args = list(args)
        self.comandos.append(args)
        if self.reg is not None and args[0] == mf.REGSVR32 and "/u" not in args:
            k = self.reg.CreateKeyEx("HKLM", rf"SOFTWARE\Classes\CLSID\{mf.CLSID}\InprocServer32")
            self.reg.SetValueEx(k, "", 0, self.reg.REG_SZ, args[-1])
        return types.SimpleNamespace(returncode=1 if "/query" in args else 0, stdout="", stderr="")

    def de(self, programa):
        """Os comandos desse programa. Os do Windows tem de ir pelo caminho completo da System32: pelo nome solto, o
        Windows procuraria antes na pasta do executavel."""
        feitos = [c for c in self.comandos if os.path.basename(c[0]).lower() in (programa, programa + ".exe")]
        for c in feitos:
            if c[0] not in ("servico", "reinicia"):
                assert os.path.dirname(c[0]).lower() == mf.SYSTEM32.lower(), f"{c[0]} sem o caminho da System32"
        return feitos


def carrega(congelado, exe=None):
    """O microfone.py de novo, como no executavel (a PASTA na pasta dele) ou pelo codigo."""
    if congelado:
        sys.frozen = True
        with mock.patch.object(sys, "executable", exe):
            importlib.reload(mf)
    else:
        if hasattr(sys, "frozen"):
            del sys.frozen
        importlib.reload(mf)


class TestaPastaProtegida(Base):
    """A regra da pasta protegida no filtro (pastas.pasta_protegida), com o registro falso, os comandos gravados e a
    regra trocada por uma que anota a pasta: nada de verdade e copiado, registrado nem agendado."""

    def setUp(self):
        self.vistas, self.aprova = [], True
        self.cmd = None
        self._regra = pastas.pasta_protegida
        pastas.pasta_protegida = self.regra
        super().setUp()

    def tearDown(self):
        super().tearDown()
        pastas.pasta_protegida = self._regra
        carrega(False)

    def regra(self, pasta=None, raiz=None):
        self.vistas.append(pasta)
        return True if self.aprova else pastas.Reprovada("test folder")

    def falsos(self, existe=()):
        """O que mexe no disco e nos servicos, trocado por gravadores; existe: os caminhos que existem."""
        self.cmd = Gravador(self.reg)
        self.copias, self.pastas_criadas, self.apagadas = [], [], []
        existe = {os.path.normcase(c) for c in existe}
        pilha = [mock.patch.object(mf.subprocess, "run", self.cmd),
                 mock.patch.object(mf.shutil, "copy2", lambda de, para: self.copias.append(para)),
                 mock.patch.object(mf.shutil, "rmtree", lambda p, **kw: self.apagadas.append(p)),
                 mock.patch.object(mf.os, "makedirs", lambda p, **kw: self.pastas_criadas.append(p)),
                 mock.patch.object(mf.os.path, "exists", lambda p: os.path.normcase(p) in existe),
                 mock.patch.object(mf, "_sha", lambda p: "igual"),
                 mock.patch.object(mf, "audio_rodando", lambda: True),
                 mock.patch.object(mf, "servico_audio", lambda acao: self.cmd.comandos.append(["servico", acao])),
                 mock.patch.object(mf, "reinicia_audio", lambda: self.cmd.comandos.append(["reinicia"]))]
        for p in pilha:
            p.start()
            self.addCleanup(p.stop)

    def nada_mexido(self):
        self.assertEqual(self.cmd.comandos, [], "rodou um comando com a pasta reprovada")
        self.assertEqual(self.copias + self.pastas_criadas + self.apagadas, [], "mexeu no disco com a pasta reprovada")

    def test_pasta_pelo_codigo(self):
        """Pelo codigo, a pasta conferida e a do instalador (%ProgramW6432%\\Ritmelli), e nao a do Python."""
        carrega(False)
        self.tearDown_winreg()
        raiz = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
        self.assertEqual(mf.PASTA, os.path.join(raiz, "Ritmelli", "microfone"))
        self.aprova = False
        self.falsos()
        with self.assertRaises(SystemExit):
            mf._prepara_dll(r"C:\x\micfx.dll")  # noqa: SLF001
        self.assertEqual(self.vistas, [os.path.join(raiz, "Ritmelli")])
        self.nada_mexido()

    def test_pasta_no_executavel(self):
        """No executavel, a pasta conferida e a dele, onde quer que o setup a tenha posto."""
        carrega(True, r"C:\Program Files\Ritmelli-2\ritmelli.exe")
        self.tearDown_winreg()
        self.assertEqual(mf.PASTA, r"C:\Program Files\Ritmelli-2\microfone")
        self.aprova = False
        self.falsos()
        with self.assertRaises(SystemExit):
            mf._prepara_dll(r"C:\x\micfx.dll")  # noqa: SLF001
        self.assertEqual(self.vistas, [r"C:\Program Files\Ritmelli-2"])
        self.nada_mexido()

    def tearDown_winreg(self):
        """O reload trouxe o winreg de verdade de volta: o falso de novo."""
        mf.winreg = self.reg

    def test_instala_todos_desarma(self):
        """A tarefa do filtro (o instala-todos do executavel) com a pasta reprovada: antes de migrar o registro e de
        procurar a DLL, apaga as duas tarefas (a da atualizacao com o /end, a propria por ultimo) e sai com erro."""
        carrega(True, r"C:\Program Files\Ritmelli\ritmelli.exe")
        self.tearDown_winreg()
        self.notebook()
        antes = {k: dict(v) for k, v in self.reg.chaves.items()}
        self.aprova = False
        self.falsos()
        import atualizador
        migrou = []
        with mock.patch.object(mf, "_migra_registro", lambda: migrou.append(1)), \
                mock.patch.object(atualizador.subprocess, "run", self.cmd):
            self.assertEqual(mf.main(["instala-todos", "--dll", r"C:\nao\existe.dll"]), 1)
        self.assertEqual(migrou, [], "migrou o registro antes de conferir a pasta")
        tarefas = [(c[1], c[c.index("/tn") + 1]) for c in self.cmd.de("schtasks") if c[1] != "/query"]
        self.assertEqual(tarefas, [("/end", atualizador.TAREFA), ("/delete", atualizador.TAREFA),
                                   ("/delete", mf.TAREFA)])
        self.assertEqual(sorted(c[-1] for c in self.cmd.de("schtasks") if c[1] == "/query"),
                         sorted([atualizador.TAREFA, mf.TAREFA]), "nao conferiu as duas")
        self.assertEqual(self.reg.chaves, antes, "mexeu no registro com a pasta reprovada")
        self.assertEqual(self.copias + self.pastas_criadas + self.apagadas, [])

    def test_instala_todos_pelo_codigo_nao_desarma(self):
        """Pelo codigo (o passo do README, como administrador), o instala e o instala-todos nao apagam tarefa nenhuma:
        recusam antes de migrar o registro, sem mexer em nada."""
        carrega(False)
        self.tearDown_winreg()
        self.aprova = False
        for acao in (["instala-todos"], ["instala", "--microfone", "IN 2"]):
            with self.subTest(acao=acao[0]):
                self.falsos(existe=[r"C:\x\micfx.dll"])
                migrou = []
                with mock.patch.object(mf, "_migra_registro", lambda: migrou.append(1)):
                    self.assertEqual(mf.main([*acao, "--dll", r"C:\x\micfx.dll"]), 1)
                self.assertEqual(migrou, [], "migrou o registro antes de conferir a pasta")
                self.nada_mexido()

    def test_dll_registrada_em_outra_pasta(self):
        """O filtro registrado aponta para outra pasta (a instalacao anterior): a DLL desta pasta e registrada, o audio
        reinicia uma vez e a anterior fica; os originais ja guardados dos microfones ficam."""
        carrega(True, r"C:\Program Files\Ritmelli-2\ritmelli.exe")
        self.tearDown_winreg()
        r = self.reg
        k = r.CreateKeyEx("HKLM", rf"SOFTWARE\Classes\CLSID\{mf.CLSID}\InprocServer32")
        r.SetValueEx(k, "", 0, r.REG_SZ, r"C:\Program Files\Ritmelli\microfone\micfx.dll")
        antes = self.notebook()
        mf._pendura(EP)  # noqa: SLF001
        guardado = r.valores(f"HKLM\\{mf.SALVO}\\{EP}")
        self.falsos(existe=[r"C:\x\micfx.dll"])
        mf.instala_todos(r"C:\x\micfx.dll")
        destino = r"C:\Program Files\Ritmelli-2\microfone\micfx.dll"
        self.assertEqual(self.copias, [destino])
        self.assertEqual([c[-1] for c in self.cmd.de("regsvr32")], [destino])
        self.assertEqual(self.cmd.de("reinicia"), [["reinicia"]], "o audio nao reiniciou uma vez")
        self.assertEqual(self.apagadas, [], "a DLL anterior saiu")
        self.assertEqual(r.valores(f"HKLM\\{mf.SALVO}\\{EP}"), guardado, "o original guardado mudou")
        self.falsos(existe=[r"C:\x\micfx.dll", destino])
        mf.instala_todos(r"C:\x\micfx.dll")
        self.assertEqual(self.cmd.de("reinicia"), [], "de novo, com a DLL ja registrada aqui: o audio reiniciou")
        mf._devolve(EP)  # noqa: SLF001
        self.assertEqual(r.valores(fx_de(EP)), antes)

    def com_dois(self):
        """Dois microfones com o filtro, o registro do COM e do APO de cada CLSID nosso e a vaga do hospedeiro."""
        r = self.reg
        self.notebook(EP)
        self.notebook(EP2)
        mf._pendura(EP)  # noqa: SLF001
        mf._pendura(EP2)  # noqa: SLF001
        for c in mf.NOSSOS:
            r.CreateKeyEx("HKLM", rf"SOFTWARE\Classes\CLSID\{c}")
            k = r.CreateKeyEx("HKLM", rf"SOFTWARE\Classes\CLSID\{c}\InprocServer32")
            r.SetValueEx(k, "", 0, r.REG_SZ, mf.PASTA + r"\micfx.dll")
            r.CreateKeyEx("HKLM", rf"{mf.APOS}\{c}")
        mics = [(EP, "Microfone", "Notebook"), (EP2, "Outro", "USB")]
        p = mock.patch.object(mf, "microfones", lambda todos=False: mics)
        p.start()
        self.addCleanup(p.stop)
        return mics

    def tem_chave(self, caminho):
        return f"HKLM\\{caminho}".lower() in self.reg.chaves

    def remove_um_de_dois(self, aprova):
        """Tirar o filtro de um de dois microfones deixa o outro com ele, a tarefa e as vagas do hospedeiro."""
        carrega(True, r"C:\Program Files\Ritmelli\ritmelli.exe")
        self.tearDown_winreg()
        mics = self.com_dois()
        self.aprova = aprova
        self.falsos(existe=[mf.PASTA + r"\micfx.dll"])
        with mock.patch.object(mf, "acha", lambda filtro: mics[0]):
            if aprova:
                mf.remove("Microfone")
            else:
                with self.assertRaises(SystemExit):
                    mf.remove("Microfone")
        self.assertFalse(mf.tem_filtro(EP))
        self.assertTrue(mf.tem_filtro(EP2), "o outro microfone perdeu o filtro")
        self.assertEqual(self.vaga(0), MFX_FM, "a vaga do hospedeiro saiu")
        self.assertEqual(self.cmd.de("schtasks"), [], "mexeu na tarefa")
        self.assertEqual(self.cmd.de("regsvr32") + self.apagadas, [], "tirou a DLL com um microfone usando")
        self.assertTrue(self.tem_chave(rf"SOFTWARE\Classes\CLSID\{mf.CLSID}"), "o COM do filtro saiu")

    def test_remove_um_de_dois_protegida(self):
        self.remove_um_de_dois(True)

    def test_remove_um_de_dois_reprovada(self):
        """Com a pasta reprovada, tambem: e o comando sai com erro."""
        self.remove_um_de_dois(False)

    def test_remove_reprovada(self):
        """O desinstalador com a pasta reprovada: os microfones voltam ao original, o registro do COM e do APO sai pelo
        winreg (sem carregar a DLL: nada de regsvr32 /u), a pasta fica como esta, a tarefa e as vagas saem, e o comando
        sai com erro depois de devolver tudo."""
        carrega(True, r"C:\Program Files\Ritmelli\ritmelli.exe")
        self.tearDown_winreg()
        self.com_dois()
        self.aprova = False
        self.falsos(existe=[mf.PASTA + r"\micfx.dll"])
        with self.assertRaises(SystemExit) as fim:
            mf.remove()
        self.assertTrue(fim.exception.code)
        self.assertFalse(mf.tem_filtro(EP) or mf.tem_filtro(EP2), "um microfone ficou com o filtro")
        self.assertEqual(self.cmd.de("regsvr32"), [], "carregou a DLL da pasta reprovada")
        self.assertEqual(self.apagadas, [], "apagou a pasta reprovada")
        for c in mf.NOSSOS:
            self.assertFalse(self.tem_chave(rf"SOFTWARE\Classes\CLSID\{c}"), f"o CLSID {c} ficou")
            self.assertFalse(self.tem_chave(rf"SOFTWARE\Classes\CLSID\{c}\InprocServer32"), f"o servidor de {c} ficou")
            self.assertFalse(self.tem_chave(rf"{mf.APOS}\{c}"), f"o APO {c} ficou")
        self.assertIsNone(self.vaga(0), "a vaga do hospedeiro ficou")
        self.assertEqual([c[1] for c in self.cmd.de("schtasks")], ["/delete"], "a tarefa do filtro nao saiu")
        self.assertEqual(self.cmd.de("reinicia"), [["reinicia"]])

    def test_remove_protegida(self):
        """O desinstalador com a pasta protegida: como antes, o regsvr32 /u e a pasta saem."""
        carrega(True, r"C:\Program Files\Ritmelli\ritmelli.exe")
        self.tearDown_winreg()
        self.com_dois()
        self.falsos(existe=[mf.PASTA + r"\micfx.dll"])
        mf.remove()
        self.assertEqual(self.cmd.de("regsvr32"), [[mf.REGSVR32, "/s", "/u", mf.PASTA + r"\micfx.dll"]])
        self.assertEqual(self.apagadas, [mf.PASTA])
        self.assertEqual(self.vistas, [os.path.dirname(mf.PASTA)])

    def test_tarefa_cria_reprovada(self):
        """O tarefa_cria do executavel com a pasta reprovada apaga a tarefa que existir e volta, sem sys.exit."""
        carrega(True, r"C:\Program Files\Ritmelli\ritmelli.exe")
        self.tearDown_winreg()
        self.aprova = False
        self.falsos()
        mf.tarefa_cria()
        self.assertEqual(self.cmd.comandos, [[mf.SCHTASKS, "/delete", "/tn", mf.TAREFA, "/f"]])
        self.assertEqual(os.path.dirname(mf.SCHTASKS).lower(), mf.SYSTEM32.lower())


if __name__ == "__main__":
    unittest.main()
