import http.server
import io
import itertools
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
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
        self.assertRegex(PINNED or "", r"^\d+\.\d+\.\d+$")
        self.assertIn(f"onnxruntime 1.24.3 here is not the {PINNED} the installer pins",
                      self.run_main(WITH_DML, version="1.24.3"))

    def test_a_measurement_that_could_not_end_is_refused(self):
        for args in (["--cycles", "0"], ["--on-s", "0"], ["--on-s", "-1"], ["--on-s", "nan"], ["--on-s", "inf"]):
            with self.subTest(args=args):
                self.assertIn("--cycles must be 1 or more and --on-s a positive number", self.run_main(WITH_DML, *args))

    def test_an_unknown_voice_is_refused(self):
        why = self.run_main(WITH_DML, "--voice", "nobody")
        self.assertIn("no voice 'nobody' in vozes.json: pass one of ", why)
        self.assertIn(measure_voices()[0], why)


def track_up_line(after_s, seen_s=None):
    pedal = dryouts.VoicePedalStart(clock=lambda: 100.0)
    pedal.sent(pedal.pedal(True))
    pedal.clock = lambda: 100.0 + (after_s if seen_s is None else seen_s)
    with mock.patch("sys.stderr", io.StringIO()) as err:
        pedal.track(1 + round((100.0 + after_s) * 1000) % (2**32 - 1))
    return err.getvalue().strip()


READY = ["pedal_voz: pronto", track_up_line(3.1)]
FIM = ['fim {"blocos": 74, "secas": 1, "conta_ms_max": 101.1, "voz_taxa": 48000, "providers": '
       '["DmlExecutionProvider", "DmlExecutionProvider", "DmlExecutionProvider", "DmlExecutionProvider"]}']
MIC = "IN 1"


def state(secas=0, secas_pedal=0, volta=4.6, folga=20.0, leitores=1, mic=MIC, anel=True, injetor=1, trocados=1):
    return {"active_devices": {"mic": mic}, "microfone": {"anel": anel, "leitores": leitores, "secas": secas,
                                                         "secas_pedal": secas_pedal, "volta_max_ms": volta,
                                                         "folga_min_ms": folga, "injetor": injetor,
                                                         "leitores_trocados": trocados}}


def row(states_seen, server_lines=READY, voice_lines=FIM, provider="dml"):
    return measure.cycle_row(5, states_seen, MIC, provider, server_lines, voice_lines)


class CycleRow(unittest.TestCase):
    def test_a_cycle_with_its_voice(self):
        got, problem = measure.cycle_row(3, [state(1, 0), state(2, 1), state(3, 1)], MIC, "dml", READY,
                                         ["warning", *FIM])
        self.assertIsNone(problem)
        self.assertEqual(got, {"cycle": 3, "dry_outs": 2, "dry_outs_while_starting": 1, "new_longest_return_ms": None,
                               "track_up_after_s": [3.1, 3.1], "voice_blocks": 74, "voice_track_dry_outs": 1,
                               "voice_slowest_block_ms": 101.1})

    def test_a_track_seen_later_than_its_stamp_gives_its_interval(self):
        got, _ = row([state(), state()], server_lines=["pedal_voz: pronto", track_up_line(3.1, 3.6)])
        self.assertEqual(got["track_up_after_s"], [3.1, 3.6])

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
                 "another injector, the same counters": [state(1, 1, 9.0, 0.0), state(1, 1, 9.0, 0.0, injetor=2)],
                 "another reader, the same counters": [state(1, 1, 9.0, 0.0), state(1, 1, 9.0, 0.0, trocados=2)],
                 "the same injector, its counters back to zero and up to the same again": [state(2, 0, 9.0, 10.0),
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


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def sse(*rounds_sent):
    out = b""
    for k, (t, st, *n) in enumerate(rounds_sent):
        tick = event("tick", {"pos": 0, "t": t, "n": (n or [k + 1])[0]})
        out += (event("state", st) if st is not None else b"") + tick
    return io.BytesIO(out)


FALLBACK = "Microfone (Realtek(R) Audio)"
def dry_out_line(count, injector, pedal=False):
    start = dryouts.VoicePedalStart(clock=lambda: 100.0)
    if pedal:
        start.sent(start.pedal(True))
    dry = dryouts.RingDryOuts(start)
    dry.injector = injector
    with mock.patch("sys.stderr", io.StringIO()) as err:
        dry.ran_dry(0.656, count, 0.0)
    return err.getvalue().strip()


class Main(unittest.TestCase):
    def run_main(self, got, *args, events=(), asked=MIC, late_lines=()):
        sent = []
        work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        err = []

        def start_job(cmd, **kw):
            err.append(kw["stderr"])
            return proc, None

        def urlopen(req, espera=None):
            if isinstance(req, str):
                req = urllib.request.Request(req)
            path = req.full_url.split("8970", 1)[1]
            sent.append((req.get_method(), path))
            if path == "/api/shutdown" and late_lines:
                err[0].write("".join(ln + "\n" for ln in late_lines))
                err[0].flush()
            if path == "/api/events":
                return sse(*events)
            if req.data and json.loads(req.data) == {"effect": "pistavoz"}:
                err[0].write("\n".join(READY) + "\n")
                err[0].flush()
                logs = work / "local" / "Ritmelli" / "logs"
                logs.mkdir(parents=True, exist_ok=True)
                (logs / "pistavoz.log").write_text("\n".join(FIM) + "\n", encoding="utf-8")
            answers = {"/api/effects": [{"id": "pistavoz"}], "/api/state": got}
            return io.BytesIO(json.dumps(answers.get(path, {})).encode())

        proc = mock.Mock(**{"poll.return_value": None})
        ticks = itertools.count(0.0, 10.0)
        with (mock.patch("onnxruntime.get_available_providers", return_value=WITH_DML),
              mock.patch("onnxruntime.__version__", PINNED),
              mock.patch.object(measure.so_mock, "sai_se_o_app_ligado"),
              mock.patch.object(measure.so_mock, "porta_responde", side_effect=[False, True]),
              mock.patch.object(measure.so_mock, "start_job", start_job),
              mock.patch.object(measure.tempfile, "mkdtemp", return_value=str(work)),
              mock.patch.object(measure.so_mock, "abre", urlopen),
              mock.patch.object(measure.urllib.request, "urlopen",
                                side_effect=AssertionError("urlopen follows the proxy")),
              mock.patch.object(measure, "OFF_S", 0.5),
              mock.patch.object(measure, "clock", lambda: next(ticks)),
              mock.patch.object(sys, "argv", ["measure_voice_pedal.py", asked, "--port", "8970", "--on-s", "0.5",
                                              "--out", str(work / "out.json"), *args])):
            try:
                measure.main()
                why = None
            except SystemExit as stop:
                why = str(stop.code)
        out = work / "out.json"
        return why, sent, json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None

    def test_the_tools_opener_reaches_the_local_server_past_a_proxy(self):
        class Answer(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"here": true}')

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Answer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        proxy = "http://127.0.0.1:9"
        url = f"http://127.0.0.1:{server.server_port}/api/state"
        child = "\n".join([f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})",
                           "import json, so_mock", f"print(json.load(so_mock.abre({url!r}, espera=5)))"])
        env = dict(os.environ, http_proxy=proxy, HTTP_PROXY=proxy, no_proxy="", NO_PROXY="")
        done = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.stdout.strip(), "{'here': True}", done.stderr[-400:])

    def test_a_fallback_microphone_stops_before_the_pedal(self):
        why, sent, _ = self.run_main(state(mic=FALLBACK))
        self.assertIn(f"opened the microphone '{FALLBACK}' and not 'IN 1'", why)
        self.assertEqual(sent, [("GET", "/api/effects"), ("POST", "/api/devices"), ("GET", "/api/state"),
                                ("POST", "/api/shutdown")])

    def test_the_filter_wait_needs_the_ring_open_too(self):
        why, _, result = self.run_main(state(), "--cycles", "1",
                                       events=[(1.0, state(anel=False)), (2.0, state(0, 0, 9.0, 10.0)),
                                               (15.0, state(0, 0, 9.0, 10.0)), (25.0, None)])
        self.assertIsNone(why, "a reader with the ring not open yet is not the filter reading it")
        self.assertEqual(result["cycles"][0]["dry_outs"], 0)

    def test_a_ring_never_open_stops_before_the_pedal(self):
        why, sent, _ = self.run_main(state(), events=[(1.0, state(anel=False)), (70.0, state(anel=False))])
        self.assertIn("the filter of IN 1 never read the ring", why)
        self.assertNotIn(("POST", "/api/settings"), sent)

    def test_a_stream_with_no_state_stops_before_the_pedal(self):
        why, sent, _ = self.run_main(state(), events=[(1.0, None), (70.0, None)])
        self.assertIn("the filter of IN 1 never read the ring", why)
        self.assertIn("0 state(s) seen", why)
        self.assertNotIn(("POST", "/api/settings"), sent)

    def test_a_fallback_microphone_after_the_filter_read_stops_before_the_pedal(self):
        why, sent, _ = self.run_main(state(), events=[(1.0, state(mic=FALLBACK))])
        self.assertIn(f"opened the microphone '{FALLBACK}' and not 'IN 1'", why)
        self.assertEqual(sent, [("GET", "/api/effects"), ("POST", "/api/devices"), ("GET", "/api/state"),
                                ("GET", "/api/events"), ("POST", "/api/shutdown")])

    def test_a_cycle_is_the_rounds_up_to_the_first_one_past_its_end(self):
        why, sent, result = self.run_main(state(), "--cycles", "1",
                                          events=[(1.0, state(0, 0, 9.0, 10.0)), (5.0, state(0, 0, 9.0, 10.0)),
                                                  (15.0, state(1, 1, 656.0, 10.0)), (25.0, None)])
        self.assertIsNone(why)
        self.assertEqual((sent.count(("GET", "/api/events")), sent.count(("GET", "/api/state"))), (1, 1),
                         "one stream for the whole measurement, and /api/state only to check the microphone")
        self.assertEqual((result["dry_outs"], result["dry_outs_while_starting"], result["onnxruntime"],
                          result["cycles"][0]["new_longest_return_ms"]), (1, 1, PINNED, 656.0))
        self.assertEqual((result["cycles"][0]["requested_on_s"], result["cycles"][0]["on_s_between_responses"]),
                         (0.5, 10.0), "the pedal was on for one step of the test's clock, not the 0.5 s asked")

    def test_a_dry_out_captured_just_past_the_end_is_its_cycles(self):
        why, _, result = self.run_main(state(), "--cycles", "1",
                                       events=[(1.0, state(0, 0, 9.0, 10.0)), (15.0, state(0, 0, 9.0, 10.0)),
                                               (20.48, None), (20.52, state(1, 1, 656.0, 10.0))],
                                       late_lines=[dry_out_line(1, 1, pedal=True)])
        self.assertIsNone(why)
        self.assertEqual((result["dry_outs"], result["longest_return_ms_since_the_ring_opened"],
                          result["dry_out_lines"]), (1, 656.0, [dry_out_line(1, 1, pedal=True)]),
                         "the first round past the end closes the cycle, with what it carries")

    def test_each_cycle_takes_the_rounds_of_its_own_window(self):
        why, _, result = self.run_main(state(), "--cycles", "2",
                                       events=[(1.0, state(0, 0, 9.0, 10.0)), (15.0, state(1, 1, 656.0, 10.0)),
                                               (21.0, None), (22.0, state(2, 2, 656.0, 10.0)), (45.0, None),
                                               (46.0, None)])
        self.assertIsNone(why)
        self.assertEqual([(c["dry_outs"], c["dry_outs_while_starting"]) for c in result["cycles"]], [(1, 1), (1, 1)],
                         "the round at 21 s closed the first cycle, so the one at 22 s is the second's")
        self.assertEqual((result["dry_outs"], result["dry_outs_while_starting"]), (2, 2))

    def test_a_round_after_the_last_cut_is_not_measured(self):
        why, _, result = self.run_main(state(), "--cycles", "1",
                                       events=[(1.0, state(0, 0, 9.0, 10.0)), (15.0, state(0, 0, 9.0, 10.0)),
                                               (21.0, None), (25.0, state(1, 1, 656.0, 0.0))])
        self.assertIsNone(why)
        self.assertEqual((result["dry_outs"], result["cycles"][0]["new_longest_return_ms"],
                          result["longest_return_ms_since_the_ring_opened"]), (0, None, 9.0))

    def test_the_result_lists_only_the_dry_outs_between_its_cuts(self):
        told = [dry_out_line(12, 7)] + [dry_out_line(n, 1) for n in (11, 12, 13)]
        why, _, result = self.run_main(state(), "--cycles", "1",
                                       events=[(1.0, state(11, 0, 9.0, 10.0)), (15.0, state(12, 0, 656.0, 10.0)),
                                               (25.0, None)],
                                       late_lines=told)
        self.assertIsNone(why)
        self.assertEqual((result["dry_outs"], result["dry_out_lines"]), (1, [told[2]]),
                         "only the measured injector's line with a total between the cuts")

    def test_a_broken_ring_in_a_cycle_stops_the_measurement(self):
        cases = {"the ring closed": ({"active_devices": {"mic": MIC}, "microfone": {"anel": False, "leitores": 0}},
                                     "the ring had no reader"),
                 "the reader gone": (state(0, 0, 9.0, 10.0, leitores=0), "the ring had no reader"),
                 "another microphone": (state(0, 0, 9.0, 10.0, mic=FALLBACK), "the ring had no reader"),
                 "the counters back with the same injector": (state(0, 0, 0.0, None), "the ring's counters went back"),
                 "another injector with the same counters": (state(2, 0, 9.0, 10.0, injetor=2),
                                                             "the ring's injector was opened again (injector 1, then 2)"),
                 "another reader with the same counters": (state(2, 0, 9.0, 10.0, trocados=2),
                                                           "the ring's reader changed")}
        for what, (broken, said) in cases.items():
            with self.subTest(what):
                why, _, result = self.run_main(state(), "--cycles", "1",
                                               events=[(1.0, state(2, 0, 9.0, 10.0)), (15.0, broken), (25.0, None)])
                self.assertIn(f"cycle 1: {said}", why)
                self.assertIsNone(result)

    def test_skipped_rounds_stop_the_measurement(self):
        why, _, result = self.run_main(state(), "--cycles", "1",
                                       events=[(1.0, state(0, 0, 9.0, 10.0), 10), (15.0, state(0, 0, 9.0, 10.0), 12),
                                               (25.0, None, 13)])
        self.assertIn("cycle 1: the state stream skipped rounds 11 to 11", why)
        self.assertIsNone(result)

    def test_a_stream_that_closes_stops_the_measurement(self):
        why, _, result = self.run_main(state(), "--cycles", "1", events=[(1.0, state(0, 0, 9.0, 10.0))])
        self.assertIn("cycle 1: the server's state stream closed", why)
        self.assertIsNone(result)

    def test_the_name_asked_in_another_case_is_the_same_microphone(self):
        self.assertIsNone(measure.mic_refusal("in 1", state()))
        self.assertIn("opened the microphone None", measure.mic_refusal(MIC, state(mic=None)))


class TheRecord(unittest.TestCase):
    def test_a_state_belongs_to_the_round_of_the_tick_after_it(self):
        record = measure.Record(sse((1.0, state()), (2.0, None), (3.0, state(1)), (9.0, None)))
        self.assertEqual((record.until(1.5), record.current), ([state()], state()))
        self.assertEqual((record.until(5.0), record.current), ([state(1)], state(1)))

    def test_an_old_round_read_late_still_counts_and_the_state_after_it_too(self):
        record = measure.Record(sse((4.0, None), (4.5, state(1, 1, 656.0)), (5.5, None)))
        self.assertEqual(record.until(5.0), [state(1, 1, 656.0)],
                         "how late the tool reads the stream doesn't move a round from one window to another")

    def test_the_first_round_at_or_past_the_end_closes_the_window(self):
        record = measure.Record(sse((1.0, state()), (5.0, state(1)), (6.0, state(2)), (9.0, None)))
        self.assertEqual(record.until(5.0), [state(), state(1)])
        self.assertEqual(record.until(5.5), [state(2)])
        self.assertEqual(record.until(7.0), [], "a round already past the end closes the window on its own")

    def test_a_wanted_state_stops_the_wait_and_leaves_the_rest(self):
        record = measure.Record(sse((1.0, state(leitores=0)), (2.0, state()), (3.0, state(1)), (9.0, None)))
        self.assertEqual(record.until(100.0, want=lambda st: st["microfone"]["leitores"] >= 1),
                         [state(leitores=0), state()])
        self.assertEqual(record.until(5.0), [state(1)])

    def test_a_stream_that_closes_stops_the_wait(self):
        record = measure.Record(sse((1.0, state())))
        with self.assertRaises(measure.StreamBroken):
            record.until(5.0)
        self.assertEqual(record.current, state())

    def test_a_silent_stream_stops_the_wait(self):
        r = mock.Mock(**{"readline.side_effect": TimeoutError("timed out")})
        with self.assertRaises(measure.StreamBroken) as stop:
            measure.Record(r).until(5.0)
        self.assertIn("sent nothing for 30 s", str(stop.exception))

    def test_skipped_rounds_stop_the_wait(self):
        record = measure.Record(sse((1.0, state(), 7), (2.0, state(1), 9), (3.0, None, 10)))
        with self.assertRaises(measure.StreamBroken) as stop:
            record.until(5.0)
        self.assertIn("skipped rounds 8 to 8", str(stop.exception))

    def test_other_events_are_not_states(self):
        r = io.BytesIO(event("caps", {}) + event("library", [{"id": "x"}]) + b"data: {}\n\n" + event("state", state())
                       + event("jobs", []) + event("tick", {"pos": 0, "t": 1.0, "n": 1})
                       + event("tick", {"pos": 0, "t": 9.0, "n": 2}))
        self.assertEqual(measure.Record(r).until(5.0), [state()])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=2, exit=False).result.wasSuccessful() else 1)
