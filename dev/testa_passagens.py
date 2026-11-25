"""Testa o teto de logs/passagens/: o registro do fim de cada disco (Engine._registra_fim) grava um AAAA-MM-DD.jsonl
por dia de uso, e a primeira passagem do dia apaga os de mais de PASSAGENS_DIAS dias. Tudo numa pasta temporaria
(pastas.LOGS trocado), sem audio: o motor nasce sem o __init__ e o retrato do fim e um fixo.

    python dev/testa_passagens.py

Sai 1 se algo falhar.
"""
import contextlib
import datetime
import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as eng  # noqa: E402

DISCO = {"id": "a", "title": "A", "channel": "c", "duration": 200}


def _motor():
    """O Engine so com o que o _registra_fim usa."""
    e = object.__new__(eng.Engine)
    e._olock = threading.Lock()
    e._ondas = {}
    e._passagens_dia = None
    return e


def _passa(e):
    """Uma passagem: o registro do fim, com a saida de erro guardada."""
    err = io.StringIO()
    with mock.patch.object(eng, "retrato_fim", return_value=(-14.0, 110.0, [-140], [-1.0])), \
            contextlib.redirect_stderr(err):
        e._registra_fim(None, DISCO, dict(DISCO, id="b"), 200.0, None, None, False, 0.0, 195.0, 4.0, None, "teste")
    return err.getvalue()


class Teto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name) / "logs"
        self.pasta = self.logs / "passagens"
        self.pasta.mkdir(parents=True)
        p = mock.patch.object(eng.pastas, "LOGS", self.logs)
        p.start()
        self.addCleanup(p.stop)
        self.hoje = datetime.date.fromisoformat(time.strftime("%Y-%m-%d"))

    def _arquivo(self, dias, nome=None):
        p = self.pasta / (nome or f"{self.hoje - datetime.timedelta(days=dias)}.jsonl")
        p.write_text("{}\n", encoding="utf-8")
        return p

    def test_primeira_passagem_apaga_so_o_de_8_dias(self):
        oito, seis = self._arquivo(8), self._arquivo(6)
        err = _passa(_motor())
        self.assertFalse(oito.exists(), "o de 8 dias ficou")
        self.assertTrue(seis.exists(), "o de 6 dias saiu")
        self.assertIn("removed 1 end records", err)
        hoje = self.pasta / f"{self.hoje}.jsonl"
        self.assertEqual(len(hoje.read_text(encoding="utf-8").splitlines()), 1, "o registro de hoje nao foi gravado")

    def test_borda_e_o_que_nao_e_registro(self):
        sete, outro, quinze = self._arquivo(7), self._arquivo(0, "anotacoes.jsonl"), self._arquivo(15)
        texto = self._arquivo(0, f"{self.hoje - datetime.timedelta(days=30)}.txt")
        self.assertEqual(eng.poda_passagens(self.pasta, self.hoje), [quinze.name])
        for p in (sete, outro, texto):
            self.assertTrue(p.exists(), f"{p.name} saiu")

    def test_so_a_primeira_do_dia_poda(self):
        e = _motor()
        _passa(e)
        nove = self._arquivo(9)  # aparece depois da primeira passagem do dia: fica ate o dia seguinte
        _passa(e)
        self.assertTrue(nove.exists(), "a segunda passagem do dia podou de novo")
        self.assertEqual(len((self.pasta / f"{self.hoje}.jsonl").read_text(encoding="utf-8").splitlines()), 2)
        e._passagens_dia = str(self.hoje - datetime.timedelta(days=1))  # a sessao vem de ontem: virou o dia
        _passa(e)
        self.assertFalse(nove.exists(), "a primeira passagem do dia novo nao podou")

    def test_falha_na_poda_nao_derruba_o_registro(self):
        oito = self._arquivo(8)
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("aberto")):
            _passa(_motor())
        self.assertTrue(oito.exists())
        self.assertTrue((self.pasta / f"{self.hoje}.jsonl").exists(), "o registro de hoje nao foi gravado")


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if r.wasSuccessful() else 1)
