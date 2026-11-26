import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import compara
import so_mock

TRACK_S = 3600
GUARD_CROSSED = 97
REFUSAL_DRIVER = f"""
import sys
sys.path.insert(0, sys.argv[1])
import server


def guard_crossed(*args, **kwargs):
    print("the guard let it through: App was built")
    sys.exit({GUARD_CROSSED})


server.App = guard_crossed
sys.argv = ["server.py", "--no-browser", "--port", sys.argv[2], *sys.argv[3:]]
server.main()
"""
HOLDER_WAIT_S = 30.0
CHILD_HOLDS_THE_TRACK = '''
import subprocess
import sys
import threading
child = subprocess.Popen([sys.executable, "-c", "import sys, threading; held = open(sys.argv[1], 'rb'); print('held', flush=True); threading.Event().wait()", sys.argv[1]], stdout=subprocess.PIPE, text=True)
child.stdout.readline()
print("ready", flush=True)
if sys.argv[2] == "hangs":
    threading.Event().wait()
sys.stdin.buffer.read()
'''

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


class RmUniqueProcess(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]


class RmProcessInfo(ctypes.Structure):
    _fields_ = [("Process", RmUniqueProcess), ("strAppName", ctypes.c_wchar * 256),
                ("strServiceShortName", ctypes.c_wchar * 64), ("ApplicationType", ctypes.c_int),
                ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]


def holders(path):
    rm = ctypes.WinDLL("rstrtmgr")
    session, key = wintypes.DWORD(), ctypes.create_unicode_buffer(64)
    if rm.RmStartSession(ctypes.byref(session), 0, key):
        raise OSError("RmStartSession failed")
    try:
        files = (ctypes.c_wchar_p * 1)(str(path))
        if rm.RmRegisterResources(session, 1, files, 0, None, 0, None):
            raise OSError("RmRegisterResources failed")
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(16), wintypes.DWORD()
        infos = (RmProcessInfo * 16)()
        if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons)):
            raise OSError("RmGetList failed")
        return [infos[i].strAppName for i in range(count.value)]
    finally:
        rm.RmEndSession(session)


def shelf_with_one_long_track(tmp):
    data, library = tmp / "dados", tmp / "local" / "Ritmelli" / "library"
    data.mkdir(parents=True)
    library.mkdir(parents=True)
    track = {"id": "long-01", "title": "A long track", "file": "long-01.wav", "duration": TRACK_S, "youtube_id": None,
             "thumb": None, "channel": "Test", "added": "2026-11-01T12:00:00", "last_pos": 0, "plays": 0}
    (data / "library.json").write_text(json.dumps([track]), encoding="utf-8")
    (data / "config.json").write_text(json.dumps({"boas_vindas": True}), encoding="utf-8")
    with wave.open(str(library / track["file"]), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(bytes(2 * 8000 * TRACK_S))
    return data, library / track["file"]


def wait_for_ffmpeg_on(path):
    deadline = time.monotonic() + HOLDER_WAIT_S
    while time.monotonic() < deadline:
        found = holders(path)
        if any(name.lower().startswith("ffmpeg") for name in found):
            return found
        time.sleep(0.05)
    return []


def stop_while_measuring(role, extras):
    with tempfile.TemporaryDirectory(prefix=f"ritmelli-mock-stop-{role}-", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        data, wav = shelf_with_one_long_track(tmp)
        port = so_mock.free_port()
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = so_mock.sobe([sys.executable, str(ROOT / "server.py"), "--mock", "--no-browser", "--port", str(port),
                                "--data-dir", str(data), *extras], port, cwd=ROOT, stdout=log,
                               stderr=subprocess.STDOUT, env=dict(os.environ, LOCALAPPDATA=str(tmp / "local")))
            try:
                measuring = wait_for_ffmpeg_on(wav)
            finally:
                stop_error = stop(srv)
        check(bool(measuring), f"{role}: the shelf loudness measurement opened the track with ffmpeg ({measuring})")
        left = holders(wav)
        try:
            os.remove(wav)
            removed = True
        except PermissionError:
            removed = False
        check(srv.srv.returncode == 0 and stop_error is None,
              f"{role}: the server stops by itself and leaves nothing running (exit {srv.srv.returncode}, {stop_error})")
        check(removed and not left,
              f"{role}: the moment the stop returns, nothing holds the track and it deletes ({left})")


def http_shutdown_with_the_pipe_open():
    with tempfile.TemporaryDirectory(prefix="ritmelli-mock-stop-http-") as tmp:
        tmp = Path(tmp)
        data, _ = shelf_with_one_long_track(tmp)
        port = so_mock.free_port()
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = so_mock.sobe([sys.executable, str(ROOT / "server.py"), "--mock", "--no-browser", "--port", str(port),
                                "--data-dir", str(data)], port, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               env=dict(os.environ, LOCALAPPDATA=str(tmp / "local")))
            try:
                srv.api("POST", "/api/shutdown", espera=5)
                code = srv.srv.wait(30)
            finally:
                stop(srv)
        text = (tmp / "server.log").read_text(encoding="utf-8", errors="replace")
    check(code == 0 and "Fatal Python error" not in text,
          f"pc: the /api/shutdown with the stdin pipe still open exits cleanly (exit {code}"
          f"{', ' + text[text.index('Fatal Python error'):][:120] if 'Fatal Python error' in text else ''})")


def refusals_before_start():
    with tempfile.TemporaryDirectory(prefix="ritmelli-mock-refusals-") as tmp:
        local = Path(tmp) / "local"
        user_data = local / "Ritmelli" / "library"
        user_data.mkdir(parents=True)
        env = dict(os.environ, LOCALAPPDATA=str(local))
        for args, expected in ((["--stop-on-stdin-eof"], "--stop-on-stdin-eof only works with --mock"),
                               (["--papel-local", "celular"], "--papel-local only works with --mock"),
                               (["--metricas-teste"], "--metricas-teste only works with --mock"),
                               (["--mock", "--data-dir", str(user_data)], "--mock never uses the user's data")):
            p = subprocess.run([sys.executable, "-c", REFUSAL_DRIVER, str(ROOT), str(so_mock.free_port()), *args],
                               cwd=ROOT, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            check(p.returncode not in (0, GUARD_CROSSED) and expected in p.stderr,
                  f"server.py {' '.join(args[:2])}: refused before it starts ({p.returncode}, {p.stderr.strip()[-120:]})")


def flag_only_for_a_server_that_knows_it():
    with tempfile.TemporaryDirectory(prefix="ritmelli-old-checkout-") as tmp:
        old = Path(tmp)
        (old / "server.py").write_text("print('a server.py from before the stop flag')", encoding="utf-8")
        check(compara.knows_stop_flag(ROOT) and not compara.knows_stop_flag(old),
              f"the compara passes {so_mock.STOP_FLAG} to this checkout's server.py and not to an older one, which "
              "would refuse it")


def measurement_stopped_by_the_given_kill():
    sys.path.insert(0, str(ROOT))
    import engine
    import sonoridade
    with tempfile.TemporaryDirectory(prefix="ritmelli-measure-stop-", ignore_cleanup_errors=True) as tmp:
        _, wav = shelf_with_one_long_track(Path(tmp))
        result, kills = [], []
        measuring = threading.Thread(target=lambda: result.append(sonoridade.mede_arquivo(wav, engine.FFMPEG)))
        measuring.start()
        found = wait_for_ffmpeg_on(wav)

        def kill(p):
            kills.append(p)
            engine.mata(p)

        sonoridade.stop_measurements(kill)
        measuring.join(30)
        left = holders(wav)
    check(bool(found) and len(kills) == 1 and result == [None] and not left,
          f"stop_measurements ends a running measurement through the kill it is given (the engine's mata) and waits "
          f"for it: nothing holds the track after ({found}, {len(kills)} kill, {result}, {left})")


def stop(srv):
    try:
        srv.encerra()
    except so_mock.Recusa as ex:
        return str(ex)
    return None


def server_whose_child_holds_the_track(kind, expected):
    with tempfile.TemporaryDirectory(prefix=f"ritmelli-{kind}-server-", ignore_cleanup_errors=True) as tmp:
        _, wav = shelf_with_one_long_track(Path(tmp))
        proc, job = so_mock.start_job([sys.executable, "-c", CHILD_HOLDS_THE_TRACK, str(wav), kind],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdout.readline()
        held = holders(wav)
        refused = stop(so_mock.Filho(proc, so_mock.free_port(), job))
        left = holders(wav)
        try:
            os.remove(wav)
            removed = True
        except PermissionError:
            removed = False
    check(bool(held) and refused is not None and expected in refused and not left and removed,
          f"a server that {kind} with a child holding the track fails the stop, and the stop ends that child: nothing "
          f"holds the track after ({held}, {refused}, {left})")


def resume_that_fails():
    real_resume, real_popen, started = so_mock._resume, so_mock.subprocess.Popen, []

    def popen(*args, **kwargs):
        started.append(real_popen(*args, **kwargs))
        return started[-1]

    so_mock._resume, so_mock.subprocess.Popen = (lambda process: 0xC0000001), popen
    try:
        so_mock.start_job([sys.executable, "-c", "print('never runs')"], stdout=subprocess.PIPE, text=True)
        refused = None
    except so_mock.Recusa as ex:
        refused = str(ex)
    finally:
        so_mock._resume, so_mock.subprocess.Popen = real_resume, real_popen
    ended = len(started) == 1 and started[0].poll() is not None
    check(refused is not None and "not resumed" in refused and ended,
          f"a server that cannot be resumed is refused and ended, with its job closed ({refused}, ended {ended})")


class KernelWith:
    def __init__(self, real, **overrides):
        self.real, self.overrides = real, overrides

    def __getattr__(self, name):
        return self.overrides.get(name) or getattr(self.real, name)


def holder_in_a_job(tmp):
    _, wav = shelf_with_one_long_track(Path(tmp))
    proc, job = so_mock.start_job([sys.executable, "-c", CHILD_HOLDS_THE_TRACK, str(wav), "hangs"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdout.readline()
    return proc, job, wav


def job_api_failures():
    with tempfile.TemporaryDirectory(prefix="ritmelli-job-api-", ignore_cleanup_errors=True) as tmp:
        proc, job, wav = holder_in_a_job(tmp)
        real = job.k

        def partial(handle, kind, info, size, returned):
            ok = real.QueryInformationJobObject(handle, kind, info, size, returned)
            if kind == 3:
                info._obj.NumberOfAssignedProcesses += 1
            return ok

        job.k = KernelWith(real, QueryInformationJobObject=partial)
        try:
            job.members()
            partial_refused = None
        except so_mock.Recusa as ex:
            partial_refused = str(ex)
        job.k = KernelWith(real, IsProcessInJob=lambda *args: 0)
        try:
            job.members()
            check_refused = None
        except so_mock.Recusa as ex:
            check_refused = str(ex)
        job.k = KernelWith(real, QueryInformationJobObject=lambda *args: 0)
        try:
            job.end()
            end_refused = None
        except so_mock.Recusa as ex:
            end_refused = str(ex)
        try:
            proc.wait(10)
            server_ended = True
        except subprocess.TimeoutExpired:
            server_ended = False
            proc.kill()
    check(partial_refused is not None and "more than it lists" in partial_refused,
          f"a job listing shorter than the job is refused ({partial_refused})")
    check(check_refused is not None and "could not be checked" in check_refused,
          f"a job member that cannot be checked is refused ({check_refused})")
    check(end_refused is not None and "did not list" in end_refused and server_ended,
          f"a job whose listing fails while it ends is still terminated, and the stop fails saying it could not "
          f"confirm the exits ({end_refused}, server ended {server_ended})")


def resume_cleanup_when_terminate_fails():
    real_resume, real_kernel, real_close, closed = so_mock._resume, so_mock._kernel, so_mock._Job.close, []

    def terminate_fails(*args):
        raise OSError("terminate failed")

    def close(job):
        closed.append(job.job is not None)
        real_close(job)

    started = []
    real_popen = so_mock.subprocess.Popen

    def popen(*args, **kwargs):
        started.append(real_popen(*args, **kwargs))
        return started[-1]

    so_mock._resume = lambda process: 0xC0000001
    so_mock._kernel = lambda: KernelWith(real_kernel(), TerminateProcess=terminate_fails)
    so_mock._Job.close, so_mock.subprocess.Popen = close, popen
    try:
        so_mock.start_job([sys.executable, "-c", "print('never runs')"], stdout=subprocess.PIPE, text=True)
        raised = None
    except (so_mock.Recusa, OSError) as ex:
        raised = ex
    finally:
        so_mock._resume, so_mock._kernel, so_mock._Job.close, so_mock.subprocess.Popen = (
            real_resume, real_kernel, real_close, real_popen)
    ended = len(started) == 1 and started[0].poll() is not None
    check(isinstance(raised, OSError) and True in closed and ended,
          f"when the terminate of a server that could not be resumed fails, its job is still closed (which ends it) "
          f"and the process waited for ({raised!r}, closed {closed}, ended {ended})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    job_api_failures()
    resume_cleanup_when_terminate_fails()
    resume_that_fails()
    refusals_before_start()
    flag_only_for_a_server_that_knows_it()
    http_shutdown_with_the_pipe_open()
    server_whose_child_holds_the_track("hangs", "did not stop")
    server_whose_child_holds_the_track("exits", "left 1 process")
    measurement_stopped_by_the_given_kill()
    stop_while_measuring("phone", ["--papel-local", "celular"])
    stop_while_measuring("pc", [])
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
