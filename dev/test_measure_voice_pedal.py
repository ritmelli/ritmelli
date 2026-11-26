import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_voice_pedal as measure

CPU_ONLY = ["AzureExecutionProvider", "CPUExecutionProvider"]
WITH_DML = ["DmlExecutionProvider", "CPUExecutionProvider"]


class Refusal(unittest.TestCase):
    def run_main(self, available, *args):
        started = []
        with (mock.patch("onnxruntime.get_available_providers", return_value=available),
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
        self.assertEqual(self.run_main(CPU_ONLY, "--provider", "cpu"), "past the check")


READY = ["pedal_voz: pronto"]
FIM = ['fim {"blocos": 74, "secas": 1, "conta_ms_max": 101.1, "voz_taxa": 48000}']


def state(secas=0, secas_pedal=0, volta=4.6):
    return {"secas": secas, "secas_pedal": secas_pedal, "volta_max_ms": volta}


class CycleRow(unittest.TestCase):
    def test_a_cycle_with_its_voice(self):
        row, problem = measure.cycle_row(3, state(1, 0), state(3, 1), READY, ["warning", *FIM])
        self.assertIsNone(problem)
        self.assertEqual(row, {"cycle": 3, "dry_outs": 2, "dry_outs_while_starting": 1, "new_longest_return_ms": None,
                               "voice_blocks": 74, "voice_track_dry_outs": 1, "voice_slowest_block_ms": 101.1})

    def test_a_longer_return_in_the_cycle(self):
        row, _ = measure.cycle_row(1, state(volta=434.0), state(volta=656.0), READY, FIM)
        self.assertEqual(row["new_longest_return_ms"], 656.0)

    def test_a_cycle_without_its_voice_stops_the_measurement(self):
        cases = {"no ready": ([], FIM), "an error": ([*READY, "pedal_voz: erro: the voice engine didn't start"], FIM),
                 "no fim": (READY, ["warning"]), "no block": (READY, ['fim {"blocos": 0}'])}
        for what, (server_lines, voice_lines) in cases.items():
            with self.subTest(what):
                row, problem = measure.cycle_row(5, state(), state(), server_lines, voice_lines)
                self.assertIsNone(row)
                self.assertTrue(problem.startswith("cycle 5: "), problem)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
