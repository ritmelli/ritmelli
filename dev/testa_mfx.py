"""Testa o pendurar e o devolver do filtro nas vagas de efeito de um microfone (microfone/microfone.py), num registro
falso em memoria: nada toca o registro do PC nem reinicia o audio.

Confere, para o microfone do notebook (EFX e MFX da Fortemedia em lista), para um MFX simples, para um microfone sem
MFX, para um MFX sem o modo RAW e para um pendurado pela versao anterior: o hospedeiro no lugar do ultimo MFX do
fabricante (a vaga dele guarda qual, e o registro de APO do fabricante vai para o do hospedeiro), pendurar de novo nao
muda nada, e o devolver deixa as vagas de efeito exatamente como eram.

    python dev/testa_mfx.py

Sai 1 se algo falhar.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
        self.chaves.setdefault(c, {})
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


class TestaMfx(unittest.TestCase):
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
            r.SetValueEx(k, "FriendlyName", 0, r.REG_SZ, "Vitrola Microfone (hospedeiro)")
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
        """O microfone do notebook antes da Vitrola: EFX e MFX da Fortemedia em lista, sem SFX."""
        r = self.reg
        return self.microfone({mf.ASSOCIACAO: (mf.KSNODETYPE_ANY, r.REG_SZ),
                               mf.EFX_LISTA: ([EFX_FM], r.REG_MULTI_SZ), mf.MFX_LISTA: ([mfx], r.REG_MULTI_SZ),
                               mf.MODOS_EFX: (list(MODOS), r.REG_MULTI_SZ),
                               mf.MODOS_MFX: (list(modos), r.REG_MULTI_SZ)}, ep)

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
        self.assertEqual(apo["friendlyname"][0], "Vitrola Microfone (hospedeiro)", "o nome fica o nosso")
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
        fabricante como original, poe o hospedeiro no lugar, e o devolver volta ao de antes da Vitrola."""
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


if __name__ == "__main__":
    unittest.main()
