# manual: python dev/measure_voice_pedal.py "<microfone>" precisa de um microfone com o filtro, placa de video e os modelos das vozes (python dev/vozes.py baixa), com o Ritmelli desligado
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import so_mock

ON_S = 8.0
OFF_S = 4.0
UP_S = 60.0
VOICE_SESSIONS = 4
DRY_LINE = re.compile(r"ran dry .*?(\d+) so far, injector (\d+)\)")
UP_LINE = re.compile(r"voice pedal: its voice track came up (\d+\.\d+) s after the pedal turned on")


def lines(path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []


def pinned_runtime():
    for line in lines(ROOT / "instalador" / "travas.txt"):
        if line.startswith("onnxruntime-directml=="):
            return line.split("==", 1)[1].strip()
    return None


def runtime_refusal(provider):
    import onnxruntime
    install = ("install the app's runtime (pip install -r requirements.txt -c instalador/travas.txt, in a venv of its "
               "own) or pass --provider cpu to measure the processor on purpose")
    if provider != "dml":
        return None
    if "DmlExecutionProvider" not in onnxruntime.get_available_providers():
        return (f"onnxruntime {onnxruntime.__version__} here has no DmlExecutionProvider, so the voice process would "
                f"run on the processor and not where the app runs it: {install}")
    if onnxruntime.__version__ != pinned_runtime():
        return (f"onnxruntime {onnxruntime.__version__} here is not the {pinned_runtime()} the installer pins "
                f"(instalador/travas.txt): {install}")
    return None


def voice_refusal(voice, voices):
    if voice is not None and voice not in voices:
        return f"no voice {voice!r} in vozes.json: pass one of {', '.join(voices)}"
    return None


clock = time.monotonic


class StreamBroken(Exception):
    pass


def rounds(r):
    event = data = state = None
    while True:
        try:
            raw = r.readline()
        except TimeoutError:
            raise StreamBroken("the server's state stream sent nothing for 30 s") from None
        if not raw:
            raise StreamBroken("the server's state stream closed")
        line = raw.decode("utf-8").strip()
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
        elif not line:
            if event == "state" and data is not None:
                state = json.loads(data)
            elif event == "tick" and data is not None:
                tick = json.loads(data)
                yield tick["t"], tick["n"], state
                state = None
            event = data = None


class Record:
    def __init__(self, r):
        self._rounds, self._n, self.current = rounds(r), None, None

    def until(self, end, want=None):
        got = []
        while True:
            t, n, state = next(self._rounds)
            if self._n is not None and n != self._n + 1:
                raise StreamBroken(f"the state stream skipped rounds {self._n + 1} to {n - 1}, so the ring wasn't "
                                   "seen whole")
            self._n = n
            if state is not None:
                got.append(state)
                self.current = state
                if want and want(state):
                    return got
            if t >= end:
                return got


def mic_refusal(asked, state):
    opened = state["active_devices"]["mic"]
    if (opened or "").casefold() != asked.casefold():
        return (f"the server opened the microphone {opened!r} and not {asked!r}: pass the full name Windows gives it, "
                "and check that it is plugged in")
    return None


def reading(st):
    return st["microfone"]["anel"] and st["microfone"]["leitores"] >= 1


def interruption(states_seen, mic):
    for st in states_seen:
        m = st["microfone"]
        if not m["anel"] or m["leitores"] < 1 or st["active_devices"]["mic"] != mic:
            return (f"the ring had no reader of {mic} ({m['leitores']} reader(s), microphone "
                    f"{st['active_devices']['mic']})")
    for a, b in zip(states_seen, states_seen[1:]):
        a, b = a["microfone"], b["microfone"]
        if b["injetor"] != a["injetor"]:
            return f"the ring's injector was opened again (injector {a['injetor']}, then {b['injetor']})"
        if b["leitores_trocados"] != a["leitores_trocados"]:
            return "the ring's reader changed (a new reader's first empty read is not counted as a dry-out)"
        dropped = a["folga_min_ms"] is not None and (b["folga_min_ms"] is None or b["folga_min_ms"] > a["folga_min_ms"])
        if any(b[k] < a[k] for k in ("secas", "secas_pedal", "volta_max_ms")) or dropped:
            return "the ring's counters went back with the same injector"
    return None


def cycle_row(n, states_seen, mic, provider, server_lines, voice_lines, on_s=ON_S):
    broke = interruption(states_seen, mic)
    if broke:
        return None, f"cycle {n}: {broke}"
    if states_seen[-1]["microfone"]["folga_min_ms"] is None:
        return None, f"cycle {n}: the ring never measured its headroom, so its dry-outs weren't counted"
    if not any(ln.startswith("pedal_voz: pronto") for ln in server_lines):
        return None, f"cycle {n}: the voice process never said it was ready within {on_s:.0f} s of the pedal (--on-s)"
    ups = [float(m.group(1)) for ln in server_lines if (m := UP_LINE.search(ln))]
    if not ups:
        return None, f"cycle {n}: the ring never saw this cycle's voice track come up"
    errors = [ln for ln in server_lines if ln.startswith("pedal_voz: erro")]
    if errors:
        return None, f"cycle {n}: {errors[0]}"
    ends = [json.loads(ln[4:]) for ln in voice_lines if ln.startswith("fim ")]
    if not ends or not ends[-1].get("blocos"):
        return None, f"cycle {n}: the voice process converted no block (its log has no fim with blocks)"
    if provider == "dml" and ends[-1].get("providers") != ["DmlExecutionProvider"] * VOICE_SESSIONS:
        return None, f"cycle {n}: the voice sessions ran on {ends[-1].get('providers')}, not all on DirectML"
    before, after = states_seen[0]["microfone"], states_seen[-1]["microfone"]
    rose = after["volta_max_ms"] > before["volta_max_ms"]
    return {"cycle": n, "dry_outs": after["secas"] - before["secas"],
            "dry_outs_while_starting": after["secas_pedal"] - before["secas_pedal"],
            "new_longest_return_ms": after["volta_max_ms"] if rose else None, "track_up_after_s": ups[0],
            "voice_blocks": ends[-1]["blocos"],
            "voice_track_dry_outs": ends[-1].get("secas"), "voice_slowest_block_ms": ends[-1].get("conta_ms_max")}, None


def main():
    ap = argparse.ArgumentParser(description="Measures the microphone ring's dry-outs as the voice pedal turns on "
                                             "(#137), on a real server of this checkout with temporary data.")
    ap.add_argument("mic", help="the microphone, as Windows names it (the one with the Ritmelli filter)")
    ap.add_argument("--cycles", type=int, default=16)
    ap.add_argument("--port", type=int, default=8970)
    ap.add_argument("--voice", default=None, help="one of the voices in vozes.json (default: the first)")
    ap.add_argument("--speaker-hz", type=float, default=120.0)
    ap.add_argument("--provider", choices=("dml", "cpu"), default="dml")
    ap.add_argument("--on-s", type=float, default=ON_S, help="how long the pedal stays on in each cycle")
    ap.add_argument("--out", type=Path, default=Path("voice_pedal.json"))
    a = ap.parse_args()
    if a.cycles < 1 or not math.isfinite(a.on_s) or a.on_s <= 0:
        sys.exit(f"--cycles must be 1 or more and --on-s a positive number of seconds (got {a.cycles} and {a.on_s})")
    sys.path.insert(0, str(ROOT))
    import onnxruntime
    import pistavoz
    refusal = runtime_refusal(a.provider) or voice_refusal(a.voice, pistavoz.VOZES)
    if refusal:
        sys.exit(refusal)
    so_mock.sai_se_o_app_ligado("dev/measure_voice_pedal.py")
    if a.port == so_mock.PORTA_DO_APP or so_mock.porta_responde(a.port):
        sys.exit(f"port {a.port} is the app's or already answers: pass another --port")
    work = Path(tempfile.mkdtemp(prefix="ritmelli-voice-pedal-"))
    (work / "local").mkdir()
    (work / "data").mkdir()
    voice = a.voice or pistavoz.VOZES[0]
    (work / "data" / "pedal_voz.json").write_text(json.dumps({"voz": voice, "falante_hz": a.speaker_hz}),
                                                  encoding="utf-8")
    env = dict(os.environ, LOCALAPPDATA=str(work / "local"), PYTHONUTF8="1", RITMELLI_PISTAVOZ_PROVEDOR=a.provider)
    cmd = [sys.executable, str(ROOT / "server.py"), "--port", str(a.port), "--no-browser", "--so-local", "--data-dir",
           str(work / "data")]
    base = f"http://127.0.0.1:{a.port}"

    def call(method, path, body=None, timeout=30):
        req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    server_err = work / "server.err"
    with open(work / "server.out", "w", encoding="utf-8") as out, open(server_err, "w", encoding="utf-8") as err:
        proc, job = so_mock.start_job(cmd, cwd=ROOT, env=env, stdout=out, stderr=err)
        cycles, events = [], None
        try:
            end = time.monotonic() + UP_S
            while not so_mock.porta_responde(a.port):
                try:
                    sys.exit(f"the server exited with code {proc.wait(timeout=0.5)} (see {work / 'server.err'})")
                except subprocess.TimeoutExpired:
                    if time.monotonic() > end:
                        sys.exit(f"the server didn't come up in {UP_S:.0f} s (see {work / 'server.err'})")
            if "pistavoz" not in [e.get("id") for e in call("GET", "/api/effects")]:
                sys.exit(f"the voice pedal is off in this checkout (see {work / 'server.err'})")
            call("POST", "/api/devices", {"mic": a.mic})
            refusal = mic_refusal(a.mic, call("GET", "/api/state"))
            if refusal:
                sys.exit(refusal)
            events = urllib.request.urlopen(base + "/api/events", timeout=30)
            record = Record(events)
            try:
                read = record.until(clock() + UP_S, want=reading)
            except StreamBroken as ex:
                sys.exit(f"waiting for the filter to read the ring: {ex} (see {server_err})")
            last = record.current
            if last is None or not reading(last):
                sys.exit(f"the filter of {a.mic} never read the ring (see {server_err}; {len(read)} state(s) seen)")
            refusal = mic_refusal(a.mic, last)
            if refusal:
                sys.exit(refusal)
            print(f"microphone {last['active_devices']['mic']}, voice {voice}; before: {last['microfone']}",
                  flush=True)
            log = work / "local" / "Ritmelli" / "logs" / "pistavoz.log"
            mic, start = last["active_devices"]["mic"], last
            first = last["microfone"]["secas"]
            for n in range(1, a.cycles + 1):
                seen = len(lines(work / "server.err"))
                try:
                    call("POST", "/api/settings", {"effect": "pistavoz"})
                    during = record.until(clock() + a.on_s)
                    call("POST", "/api/settings", {"effect": "nenhum"})
                    during += record.until(clock() + OFF_S)
                except StreamBroken as ex:
                    sys.exit(f"cycle {n}: {ex} (see {server_err} and {log})")
                states_seen = [start, *during]
                start = states_seen[-1]
                c, problem = cycle_row(n, states_seen, mic, a.provider, lines(server_err)[seen:], lines(log), a.on_s)
                if problem:
                    sys.exit(f"{problem} (see {work / 'server.err'} and {log})")
                cycles.append(c)
                print(json.dumps(c), flush=True)
        finally:
            if events is not None:
                events.close()
            try:
                if proc.poll() is None:
                    call("POST", "/api/shutdown", {}, timeout=5)
                    proc.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired) as ex:
                print(f"the server didn't stop through its API ({type(ex).__name__}: {ex}): its job ends it",
                      file=sys.stderr, flush=True)
            finally:
                if job:
                    job.end()
    dry = [ln for ln in lines(work / "server.err")
           if (m := DRY_LINE.search(ln)) and first < int(m.group(1)) <= start["microfone"]["secas"]
           and int(m.group(2)) == start["microfone"]["injetor"]]
    blocks = [c["voice_slowest_block_ms"] for c in cycles if c["voice_slowest_block_ms"] is not None]
    result = {"microphone": mic, "voice": voice, "provider": a.provider, "onnxruntime": onnxruntime.__version__,
              "cycles": cycles,
              "dry_outs": sum(c["dry_outs"] for c in cycles),
              "dry_outs_while_starting": sum(c["dry_outs_while_starting"] for c in cycles),
              "slowest_track_up_s": max([c["track_up_after_s"] for c in cycles] or [None]),
              "longest_return_ms_since_the_ring_opened": start["microfone"]["volta_max_ms"],
              "voice_blocks": sum(c["voice_blocks"] or 0 for c in cycles),
              "voice_slowest_block_ms": max(blocks or [0.0]),
              "dry_out_lines": dry, "work": str(work)}
    a.out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{result['dry_outs']} dry-outs in {len(cycles)} cycles, {result['dry_outs_while_starting']} while the pedal "
          f"was starting; longest return {result['longest_return_ms_since_the_ring_opened']} ms; voice: "
          f"{result['voice_blocks']} blocks, the slowest {result['voice_slowest_block_ms']} ms; result: {a.out}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
