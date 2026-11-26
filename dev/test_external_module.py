import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import engine
import i18n

MODULE_NAME = "mina"
QUIET = 0.01


class FakeHandle:
    def __init__(self, failure=None):
        self.failure, self.calls = failure, 0

    def liga(self):
        self.calls += 1
        if self.failure is not None:
            raise self.failure


def fake_module(handle):
    return types.SimpleNamespace(Mina=lambda eng: handle, QUIET_RMS=QUIET, TAIL_S=0.5)


def bare_engine():
    e = engine.Engine.__new__(engine.Engine)
    e.mina_permitida, e._mina, e.error = True, None, None
    e._mina_lock, e._mina_buf, e._mina_int_n, e._mina_voz_em = threading.Lock(), np.zeros(0, np.float32), 0, -1e9
    return e


class TurningOn(unittest.TestCase):
    def turn_on(self, failure):
        e, handle = bare_engine(), FakeHandle(failure)
        with mock.patch.object(engine, MODULE_NAME, fake_module(handle)):
            e._mina_liga()
        self.assertEqual(handle.calls, 1)
        return e

    def test_the_message_the_module_gives_is_shown_as_it_came(self):
        refusal = i18n.Recusa("server.external.example", "Set up {thing}.", thing="this")
        self.assertEqual(self.turn_on(refusal).error, refusal.msg)

    def test_any_other_failure_shows_the_neutral_message_with_the_reason(self):
        self.assertEqual(self.turn_on(ValueError("missing setting")).error,
                         {"key": "server.mina.notConfigured", "params": {"reason": "missing setting"},
                          "text": "This effect isn't configured (missing setting)."})

    def test_a_failure_while_building_the_module_shows_the_neutral_message(self):
        def refuse(eng):
            raise ValueError("cannot build")
        e = bare_engine()
        with mock.patch.object(engine, MODULE_NAME, types.SimpleNamespace(Mina=refuse)):
            e._mina_liga()
        self.assertEqual((e._mina, e.error["key"], e.error["params"]), (None, "server.mina.notConfigured",
                                                                          {"reason": "cannot build"}))

    def test_turning_on_cleanly_leaves_no_error(self):
        self.assertIsNone(self.turn_on(None).error)

    def test_without_permission_nothing_is_built(self):
        e = bare_engine()
        e.mina_permitida = False
        built = []
        with mock.patch.object(engine, MODULE_NAME, types.SimpleNamespace(Mina=built.append)):
            e._mina_liga()
        self.assertEqual((built, e._mina), ([], None))


class VoiceQueue(unittest.TestCase):
    def setUp(self):
        self.e = bare_engine()
        patcher = mock.patch.object(engine, MODULE_NAME, fake_module(None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_silencing_drops_the_queued_voice(self):
        self.e._mina_buf, self.e._mina_int_n = np.ones(480, np.float32), 100
        self.e.mina_cala()
        self.assertEqual((len(self.e._mina_buf), self.e._mina_int_n), (0, 0))

    def test_an_interjection_waits_while_voice_is_queued(self):
        voice = np.full(480, 0.5, np.float32)
        self.e._mina_buf = voice.copy()
        self.assertFalse(self.e.mina_interjeicao(np.full(240, 0.3, np.float32)))
        np.testing.assert_array_equal(self.e._mina_buf, voice)
        self.assertEqual(self.e._mina_int_n, 0)

    def test_an_interjection_replaces_an_empty_or_silent_queue(self):
        for queued in (np.zeros(0, np.float32), np.full(960, QUIET / 2, np.float32)):
            self.e._mina_buf, self.e._mina_int_n = queued, 0
            x = np.full(240, 0.3, np.float32)
            self.assertTrue(self.e.mina_interjeicao(x))
            np.testing.assert_array_equal(self.e._mina_buf, x)
            self.assertEqual(self.e._mina_int_n, 240)

    def test_the_reply_plays_right_after_the_interjection_and_only_the_reply_holds_the_guard(self):
        interjection, reply = np.full(240, 0.3, np.float32), np.full(480, 0.6, np.float32)
        self.assertTrue(self.e.mina_interjeicao(interjection))
        self.e.mina_voz(reply)
        with mock.patch.object(engine.time, "monotonic", return_value=1000.0):
            np.testing.assert_array_equal(self.e._mina_tira(240), interjection)
            self.assertFalse(self.e.mina_falando())
            np.testing.assert_array_equal(self.e._mina_tira(480), reply)
            self.assertTrue(self.e.mina_falando())


if __name__ == "__main__":
    unittest.main()
