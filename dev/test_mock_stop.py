import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import so_mock

TRACK_S = 1800
HOLDER_WAIT_S = 30.0

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
    with tempfile.TemporaryDirectory(prefix=f"ritmelli-mock-stop-{role}-") as tmp:
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
                srv.encerra()
        check(bool(measuring), f"{role}: the shelf loudness measurement opened the track with ffmpeg ({measuring})")
        left = holders(wav)
        try:
            os.remove(wav)
            removed = True
        except PermissionError:
            removed = False
        check(srv.srv.returncode == 0, f"{role}: the server stops by itself, not killed (exit {srv.srv.returncode})")
        check(removed and not left,
              f"{role}: the moment the stop returns, nothing holds the track and it deletes ({left})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    stop_while_measuring("phone", ["--papel-local", "celular"])
    stop_while_measuring("pc", [])
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
