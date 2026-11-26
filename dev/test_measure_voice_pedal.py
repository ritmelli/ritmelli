import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dryouts
import measure_voice_pedal as measure

CPU_ONLY = ["AzureExecutionProvider", "CPUExecutionProvider"]
PINNED = measure.pinned_runtime()
WITH_DML = ["DmlExecutionProvider", "CPUExecutionProvider"]


def measure_voices():
    import pistavoz
    return pistavoz.VOZES


class Refusal(unittest.TestCase):
    def run_main(self, available, *args, version=PINNED):
        started = []
        with (mock.patch("onnxruntime.get_available_providers", return_value=available),
              mock.patch("onnxruntime.__version__", version),
              mock.patch.object(measure.so_mock, "sai_se_o_app_ligado", side_effect=SystemExit("past the check")),
              mock.patch.object(measure.so_mock, "start_job", side_effect=lambda *a, **k: started.append(a)),
              mock.patch.object(sys, "argv", ["measure_voice_pedal.py", "IN 1", *args]),
              self.assertRaises(SystemExit) as stop):
            measure.main()
        self.assertEqual(started, [])
        return str(stop.exception.code)

    def test_a_cpu_only_runtime_is_refused(self):
        self.assertIn("no DmlExecutionProvider", self.run_main(CPU_ONLY))

    def test_the_app_runtime_goes_on(self):
        self.assertEqual(self.run_main(WITH_DML), "past the check")

    def test_the_processor_on_purpose_goes_on(self):
        self.assertEqual(self.run_main(CPU_ONLY, "--provider", "cpu", version="1.32.0"), "past the check")

    def test_another_version_of_the_runtime_is_refused(self):
        self.assertIn(f"onnxruntime 1.24.3 here is not the {PINNED} the installer pins",
                      self.run_main(WITH_DML, version="1.24.3"))

    def test_an_unknown_voice_is_refused(self):
        why = self.run_main(WITH_DML, "--voice", "nobody")
        self.assertIn("no voice 'nobody' in vozes.json: pass one of ", why)
        self.assertIn(measure_voices()[0], why)


def track_up_line(after_s):
    pedal = dryouts.VoicePedalStart(clock=lambda: 100.0)
    pedal.pedal(True)
    pedal.clock = lambda: 100.0 + after_s
    with mock.patch("sys.stderr", io.StringIO()) as err:
        pedal.track(True, stamp=1 + round((100.0 + after_s) * 1000) % (2**32 - 1))
        dryouts.LOG.written()
    return err.getvalue().strip()


READY = ["pedal_voz: pronto", track_up_line(3.1)]
FIM = ['fim {"blocos": 74, "secas": 1, "conta_ms_max": 101.1, "voz_taxa": 48000, "providers": '
       '["DmlExecutionProvider", "DmlExecutionProvider", "DmlExecutionProvider", "DmlExecutionProvider"]}']
MIC = "IN 1"


def state(secas=0, secas_pedal=0, volta=4.6, folga=20.0, leitores=1, mic=MIC, anel=True):
    return {"active_devices": {"mic": mic}, "microfone": {"anel": anel, "leitores": leitores, "secas": secas,
                                                         "secas_pedal": secas_pedal, "volta_max_ms": volta,
                                                         "folga_min_ms": folga}}


def row(states_seen, server_lines=READY, voice_lines=FIM, provider="dml"):
    return measure.cycle_row(5, states_seen, MIC, provider, server_lines, voice_lines)


class CycleRow(unittest.TestCase):
    def test_a_cycle_with_its_voice(self):
        got, problem = measure.cycle_row(3, [state(1, 0), state(2, 1), state(3, 1)], MIC, "dml", READY,
                                         ["warning", *FIM])
        self.assertIsNone(problem)
        self.assertEqual(got, {"cycle": 3, "dry_outs": 2, "dry_outs_while_starting": 1, "new_longest_return_ms": None,
                               "track_up_after_s": 3.1, "voice_blocks": 74, "voice_track_dry_outs": 1,
                               "voice_slowest_block_ms": 101.1})

    def test_a_longer_return_in_the_cycle(self):
        got, _ = row([state(volta=434.0), state(volta=656.0)])
        self.assertEqual(got["new_longest_return_ms"], 656.0)

    def test_a_cycle_without_its_voice_stops_the_measurement(self):
        cpu = [FIM[0].replace("DmlExecutionProvider", "CPUExecutionProvider", 1)]
        cases = {"no ready": ([], FIM), "no track up": (["pedal_voz: pronto"], FIM),
                 "an error": ([*READY, "pedal_voz: erro: the voice engine didn't start"], FIM),
                 "no fim": (READY, ["warning"]), "no block": (READY, ['fim {"blocos": 0}']),
                 "a session on the processor": (READY, cpu), "no providers": (READY, ['fim {"blocos": 74}']),
                 "one session told": (READY, ['fim {"blocos": 74, "providers": ["DmlExecutionProvider"]}'])}
        for what, (server_lines, voice_lines) in cases.items():
            with self.subTest(what):
                got, problem = row([state(), state()], server_lines, voice_lines)
                self.assertIsNone(got)
                self.assertTrue(problem.startswith("cycle 5: "), problem)

    def test_a_ring_not_yet_measured_goes_on(self):
        self.assertIsNone(row([state(folga=None), state(folga=None), state(folga=12.0)])[1])

    def test_a_ring_never_measured_stops_the_measurement(self):
        got, problem = row([state(folga=None), state(folga=None)])
        self.assertIsNone(got)
        self.assertIn("never measured its headroom", problem)

    def test_the_processor_on_purpose(self):
        cpu = [FIM[0].replace("DmlExecutionProvider", "CPUExecutionProvider")]
        self.assertIsNone(row([state(), state()], voice_lines=cpu, provider="cpu")[1])

    def test_an_interrupted_cycle_stops_the_measurement(self):
        cases = {"the ring closed": [state(), state(anel=False), state()],
                 "the reader gone and back": [state(), state(leitores=0), state()],
                 "another microphone": [state(), state(mic="Other"), state()],
                 "the injector opened again, the same counters at both ends": [state(2, 0, 9.0, 10.0),
                                                                               state(0, 0, 0.0, None),
                                                                               state(0, 0, 3.1, 30.0),
                                                                               state(2, 0, 9.0, 10.0)],
                 "the counters lower at the end": [state(4, 1, 9.0, 10.0), state(1, 0, 9.0, 10.0)],
                 "the pedal's count lower": [state(3, 1, 9.0, 10.0), state(3, 0, 9.0, 10.0)],
                 "the longest return lower": [state(0, 0, 9.0, 10.0), state(0, 0, 4.0, 10.0)],
                 "the least headroom higher": [state(0, 0, 9.0, 10.0), state(0, 0, 9.0, 20.0)],
                 "the least headroom unmeasured again": [state(0, 0, 9.0, 10.0), state(0, 0, 9.0, None)]}
        for what, states_seen in cases.items():
            with self.subTest(what):
                got, problem = row(states_seen)
                self.assertIsNone(got)
                self.assertTrue(problem.startswith("cycle 5: "), problem)


class TheMicrophone(unittest.TestCase):
    def run_main(self, opened, asked=MIC, readers=0):
        sent, opened = [], list(opened)
        work = self.enterContext(tempfile.TemporaryDirectory())

        def urlopen(req, timeout=None):
            path = req.full_url.split("8970", 1)[1]
            sent.append((req.get_method(), path))
            answers = {"/api/effects": [{"id": "pistavoz"}]}
            if path == "/api/state":
                answers[path] = state(mic=opened.pop(0) if len(opened) > 1 else opened[0])
            return io.BytesIO(json.dumps(answers.get(path, {})).encode())

        proc = mock.Mock(**{"poll.return_value": None})
        with (mock.patch("onnxruntime.get_available_providers", return_value=WITH_DML),
              mock.patch("onnxruntime.__version__", PINNED),
              mock.patch.object(measure.so_mock, "sai_se_o_app_ligado"),
              mock.patch.object(measure.so_mock, "porta_responde", side_effect=[False, True]),
              mock.patch.object(measure.so_mock, "start_job", return_value=(proc, None)),
              mock.patch.object(measure.tempfile, "mkdtemp", return_value=work),
              mock.patch.object(measure.urllib.request, "urlopen", urlopen),
              mock.patch.object(measure, "states", lambda base, seconds: iter([state(mic=opened[0], leitores=readers)])),
              mock.patch.object(sys, "argv", ["measure_voice_pedal.py", asked, "--port", "8970"]),
              self.assertRaises(SystemExit) as stop):
            measure.main()
        return str(stop.exception.code), sent

    def test_a_fallback_microphone_stops_before_the_pedal(self):
        why, sent = self.run_main(["Microfone (Realtek(R) Audio)"])
        self.assertIn("opened the microphone 'Microfone (Realtek(R) Audio)' and not 'IN 1'", why)
        self.assertEqual(sent, [("GET", "/api/effects"), ("POST", "/api/devices"), ("GET", "/api/state"),
                                ("POST", "/api/shutdown")])

    def test_a_fallback_microphone_after_the_filter_read_stops_before_the_pedal(self):
        why, sent = self.run_main([MIC, "Microfone (Realtek(R) Audio)"], readers=1)
        self.assertIn("opened the microphone 'Microfone (Realtek(R) Audio)' and not 'IN 1'", why)
        self.assertEqual(sent, [("GET", "/api/effects"), ("POST", "/api/devices"), ("GET", "/api/state"),
                                ("GET", "/api/state"), ("POST", "/api/shutdown")])

    def test_the_name_asked_in_another_case_is_the_same_microphone(self):
        self.assertIsNone(measure.mic_refusal("in 1", state()))
        self.assertIn("opened the microphone None", measure.mic_refusal(MIC, state(mic=None)))


def stream(*states_sent):
    return io.BytesIO(b"".join(b"event: state\ndata: " + json.dumps(s).encode() + b"\n\n" for s in states_sent))


class ReadStates(unittest.TestCase):
    def test_a_stream_that_ends_early_stops_the_wait(self):
        got = []
        with self.assertRaises(EOFError):
            got.extend(measure.read_states(stream(state()), 8.0, clock=lambda: 100.0))
        self.assertEqual(got, [state()])

    def test_the_wait_ends_at_its_deadline(self):
        times = iter([100.0, 100.0, 100.0, 109.0])
        self.assertEqual(list(measure.read_states(stream(state(), state(1)), 8.0, clock=lambda: next(times))),
                         [state()])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
