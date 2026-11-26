# manual: python dev/measure_voice_pedal.py "<microfone>" precisa de um microfone com o filtro, placa de video e os modelos das vozes (python dev/vozes.py baixa), com o Ritmelli desligado
import argparse
import json
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
UP_LINE = re.compile(r"voice pedal: its voice track came up (\d+\.\d+) s after the pedal turned on")


def lines(path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []


def runtime_refusal(provider):
    import onnxruntime
    if provider == "dml" and "DmlExecutionProvider" not in onnxruntime.get_available_providers():
        return (f"onnxruntime {onnxruntime.__version__} here has no DmlExecutionProvider, so the voice process would "
                "run on the processor and not where the app runs it: install the app's runtime (pip install -r "
                "requirements.txt -c instalador/travas.txt, in a venv of its own) or pass --provider cpu to measure "
                "the processor on purpose")
    return None


def read_states(r, seconds, clock=time.monotonic):
    end, event = clock() + seconds, None
    while clock() < end:
        raw = r.readline()
        if not raw:
            raise EOFError(f"the server's state stream closed {end - clock():.1f} s before the end of the wait")
        line = raw.decode("utf-8").strip()
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event == "state":
            yield json.loads(line[6:])


def states(base, seconds):
    with urllib.request.urlopen(base + "/api/events", timeout=seconds + 5) as r:
        yield from read_states(r, seconds)


def hold(base, seconds):
    return list(states(base, seconds))


def mic_refusal(asked, state):
    opened = state["active_devices"]["mic"]
    if (opened or "").casefold() != asked.casefold():
        return (f"the server opened the microphone {opened!r} and not {asked!r}: pass the full name Windows gives it, "
                "and check that it is plugged in")
    return None


def interruption(states_seen, mic):
    for st in states_seen:
        m = st["microfone"]
        if not m["anel"] or m["leitores"] < 1 or st["active_devices"]["mic"] != mic:
            return (f"the ring had no reader of {mic} ({m['leitores']} reader(s), microphone "
                    f"{st['active_devices']['mic']})")
    for a, b in zip(states_seen, states_seen[1:]):
        a, b = a["microfone"], b["microfone"]
        dropped = a["folga_min_ms"] is not None and (b["folga_min_ms"] is None or b["folga_min_ms"] > a["folga_min_ms"])
        if any(b[k] < a[k] for k in ("secas", "secas_pedal", "volta_max_ms")) or dropped:
            return "the ring's counters started over (the injector was opened again)"
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
    refusal = runtime_refusal(a.provider)
    if refusal:
        sys.exit(refusal)
    so_mock.sai_se_o_app_ligado("dev/measure_voice_pedal.py")
    if a.port == so_mock.PORTA_DO_APP or so_mock.porta_responde(a.port):
        sys.exit(f"port {a.port} is the app's or already answers: pass another --port")
    work = Path(tempfile.mkdtemp(prefix="ritmelli-voice-pedal-"))
    (work / "local").mkdir()
    (work / "data").mkdir()
    sys.path.insert(0, str(ROOT))
    import pistavoz
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
        cycles = []
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
            try:
                read = any(st["microfone"]["leitores"] >= 1 for st in states(base, UP_S))
            except EOFError as ex:
                sys.exit(f"waiting for the filter to read the ring: {ex} (see {server_err})")
            if not read:
                sys.exit(f"the filter of {a.mic} never read the ring (see {server_err})")
            state = call("GET", "/api/state")
            print(f"microphone {state['active_devices']['mic']}, voice {voice}; before: {state['microfone']}",
                  flush=True)
            log = work / "local" / "Ritmelli" / "logs" / "pistavoz.log"
            mic, last = state["active_devices"]["mic"], state
            for n in range(1, a.cycles + 1):
                seen = len(lines(work / "server.err"))
                try:
                    call("POST", "/api/settings", {"effect": "pistavoz"})
                    during = hold(base, a.on_s)
                    call("POST", "/api/settings", {"effect": "nenhum"})
                    during += hold(base, OFF_S)
                except EOFError as ex:
                    sys.exit(f"cycle {n}: {ex} (see {server_err} and {log})")
                states_seen = [last, *during, call("GET", "/api/state")]
                last = states_seen[-1]
                c, problem = cycle_row(n, states_seen, mic, a.provider, lines(server_err)[seen:], lines(log), a.on_s)
                if problem:
                    sys.exit(f"{problem} (see {work / 'server.err'} and {log})")
                cycles.append(c)
                print(json.dumps(c), flush=True)
        finally:
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
    dry = [ln for ln in lines(work / "server.err") if "ran dry" in ln]
    blocks = [c["voice_slowest_block_ms"] for c in cycles if c["voice_slowest_block_ms"] is not None]
    result = {"microphone": mic, "voice": voice, "provider": a.provider, "cycles": cycles,
              "dry_outs": sum(c["dry_outs"] for c in cycles),
              "dry_outs_while_starting": sum(c["dry_outs_while_starting"] for c in cycles),
              "slowest_track_up_s": max([c["track_up_after_s"] for c in cycles] or [None]),
              "longest_return_ms_since_the_ring_opened": last["microfone"]["volta_max_ms"],
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
