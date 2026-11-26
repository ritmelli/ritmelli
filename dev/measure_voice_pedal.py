# manual: python dev/measure_voice_pedal.py "<microfone>" precisa de um microfone com o filtro, placa de video e os modelos das vozes (python dev/vozes.py baixa), com o Ritmelli desligado
import argparse
import json
import collections
import os
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


def runtime_refusal(provider):
    import onnxruntime
    if provider == "dml" and "DmlExecutionProvider" not in onnxruntime.get_available_providers():
        return (f"onnxruntime {onnxruntime.__version__} here has no DmlExecutionProvider, so the voice process would run "
                "on the processor and not where the app runs it: install the app's runtime (pip install -r requirements.txt "
                "-c instalador/travas.txt, in a venv of its own) or pass --provider cpu to measure the processor on purpose")
    return None


def states(base, seconds):
    end = time.monotonic() + seconds
    with urllib.request.urlopen(base + "/api/events", timeout=seconds + 5) as r:
        event = None
        while time.monotonic() < end:
            line = r.readline().decode("utf-8").strip()
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "state":
                yield json.loads(line[6:])


def hold(base, seconds):
    return collections.deque(states(base, seconds), maxlen=1)


def main():
    ap = argparse.ArgumentParser(description="Measures the microphone ring's dry-outs as the voice pedal turns on (#137), "
                                             "on a real server of this checkout with temporary data.")
    ap.add_argument("mic", help="the microphone, as Windows names it (the one with the Ritmelli filter)")
    ap.add_argument("--cycles", type=int, default=16)
    ap.add_argument("--port", type=int, default=8970)
    ap.add_argument("--voice", default=None, help="one of the voices in vozes.json (default: the first)")
    ap.add_argument("--speaker-hz", type=float, default=120.0)
    ap.add_argument("--provider", choices=("dml", "cpu"), default="dml")
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

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    with open(work / "server.out", "w", encoding="utf-8") as out, open(work / "server.err", "w", encoding="utf-8") as err:
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
            if not any(st["microfone"]["leitores"] >= 1 for st in states(base, UP_S)):
                sys.exit(f"the filter of {a.mic} never read the ring (see {work / 'server.err'})")
            state = call("GET", "/api/state")
            print(f"microphone {state['active_devices']['mic']}, voice {voice}; before: {state['microfone']}", flush=True)
            log = work / "local" / "Ritmelli" / "logs" / "pistavoz.log"
            for n in range(a.cycles):
                before = call("GET", "/api/state")["microfone"]
                call("POST", "/api/settings", {"effect": "pistavoz"})
                hold(base, ON_S)
                on = call("GET", "/api/state")["microfone"]
                call("POST", "/api/settings", {"effect": "nenhum"})
                hold(base, OFF_S)
                after = call("GET", "/api/state")["microfone"]
                ends = [ln for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
                        if ln.startswith("fim ")] if log.is_file() else []
                voice_counts = json.loads(ends[-1][4:]) if ends else {}
                c = {"cycle": n + 1, "dry_outs": after["secas"] - before["secas"],
                     "dry_outs_while_starting": after["secas_pedal"] - before["secas_pedal"],
                     "longest_return_ms": on["volta_max_ms"], "voice_blocks": voice_counts.get("blocos"),
                     "voice_track_dry_outs": voice_counts.get("secas"),
                     "voice_slowest_block_ms": voice_counts.get("conta_ms_max")}
                cycles.append(c)
                print(json.dumps(c), flush=True)
        finally:
            try:
                if proc.poll() is None:
                    call("POST", "/api/shutdown", {})
                    proc.wait(timeout=30)
            finally:
                if job:
                    job.end()
    dry = [ln for ln in (work / "server.err").read_text(encoding="utf-8", errors="replace").splitlines() if "ran dry" in ln]
    blocks = [c["voice_slowest_block_ms"] for c in cycles if c["voice_slowest_block_ms"] is not None]
    result = {"microphone": a.mic, "voice": voice, "provider": a.provider, "cycles": cycles,
              "dry_outs": sum(c["dry_outs"] for c in cycles),
              "dry_outs_while_starting": sum(c["dry_outs_while_starting"] for c in cycles),
              "longest_return_ms": max([c["longest_return_ms"] for c in cycles] or [0.0]),
              "voice_blocks": sum(c["voice_blocks"] or 0 for c in cycles),
              "voice_slowest_block_ms": max(blocks or [0.0]),
              "dry_out_lines": dry, "work": str(work)}
    a.out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{result['dry_outs']} dry-outs in {len(cycles)} cycles, {result['dry_outs_while_starting']} while the pedal "
          f"was starting; longest return {result['longest_return_ms']} ms; voice: {result['voice_blocks']} blocks, the "
          f"slowest {result['voice_slowest_block_ms']} ms; result: {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
