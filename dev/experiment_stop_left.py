import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve() / "dev"))
import so_mock
import test_mock_stop as t

seen = []
real_left_after = so_mock._Job.left_after


def image(k, handle):
    size = wintypes.DWORD(1024)
    buf = ctypes.create_unicode_buffer(1024)
    if k.QueryFullProcessImageNameW(wintypes.HANDLE(handle), 0, buf, ctypes.byref(size)):
        return Path(buf.value).name
    return f"? ({ctypes.get_last_error()})"


def left_after(self, seconds):
    began = time.monotonic()
    handles = self.members()
    names = [image(self.k, h) for h in handles]
    try:
        fim = time.monotonic() + seconds
        still = []
        for handle, name in zip(handles, names):
            self.k.WaitForSingleObject(wintypes.HANDLE(handle), max(0, int((fim - time.monotonic()) * 1000)))
            code = wintypes.DWORD()
            self.k.GetExitCodeProcess(wintypes.HANDLE(handle), ctypes.byref(code))
            if code.value == 259:
                still.append(name)
    finally:
        for handle in handles:
            self.k.CloseHandle(wintypes.HANDLE(handle))
    seen.append({"members at the stop": names, "still running after the wait": still,
                 "waited": round(time.monotonic() - began, 2)})
    return self.active()


so_mock._Job.left_after = left_after
n, bad = int(sys.argv[2]), 0
for i in range(n):
    for role, extras in (("phone", ["--papel-local", "celular"]), ("pc", [])):
        seen.clear()
        before = len(t.failures)
        t.stop_while_measuring(role, extras)
        failed = len(t.failures) > before
        bad += failed
        print(i, role, "FAIL" if failed else "ok", seen, flush=True)
print("bad", bad, "of", 2 * n)
