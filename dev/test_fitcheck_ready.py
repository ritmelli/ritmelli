import asyncio
import contextlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import compara
import fitcheck
import so_mock

CONSOLE_MARK = "ritmelli-test-console-error"
SCRIPT_MARK = "ritmelli-test-missing.js"
NEVER_READY = ("(() => { if (!window.__ritmelliTest && document.head) { console.error('" + CONSOLE_MARK + "'); "
               "const s = document.createElement('script'); s.src = '" + SCRIPT_MARK + "'; "
               "document.head.appendChild(s); window.__ritmelliTest = true; } return false; })()")
FITCHECK_NEVER_READY = r"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "dev"))
import fitcheck
fitcheck.PRONTA = sys.argv[2]
fitcheck.PRONTA_S = 3.0
sys.argv = ["fitcheck.py", sys.argv[3], "--sizes", "390x844", "--shots", sys.argv[4]]
fitcheck.main()
"""
FITCHECK_TIMEOUT_THEN_GONE = r"""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "dev"))
import fitcheck
started = []
real_popen, real_wait = subprocess.Popen, fitcheck.wait_ready


def popen(cmd, *args, **kwargs):
    child = real_popen(cmd, *args, **kwargs)
    if cmd and cmd[0] == fitcheck.CHROME:
        started.append(child)
    return child


async def wait_then_kill_chrome(*args, **kwargs):
    outcome = await real_wait(*args, **kwargs)
    for child in started:
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
    return outcome


subprocess.Popen, fitcheck.wait_ready = popen, wait_then_kill_chrome
fitcheck.PRONTA = sys.argv[2]
fitcheck.PRONTA_S = 2.0
sys.argv = ["fitcheck.py", sys.argv[3], "--sizes", "390x844,768x1024"]
fitcheck.main()
"""
LIGAR_THEN_GONE = r"""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "dev"))
import compara
import fitcheck
import so_mock
started, waits = [], []
real_popen, real_wait = subprocess.Popen, fitcheck.wait_notice


def popen(cmd, *args, **kwargs):
    child = real_popen(cmd, *args, **kwargs)
    if cmd and cmd[0] == fitcheck.CHROME:
        started.append(child)
    return child


def kill_chrome():
    for child in started:
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)


async def kill_chrome_on_the_second_wait(cmd, deadline):
    waits.append(deadline)
    if len(waits) == 2 and sys.argv[2] == "during":
        kill_chrome()
    seen = await real_wait(cmd, deadline)
    if len(waits) == 2 and sys.argv[2] == "after":
        kill_chrome()
    return seen


subprocess.Popen, fitcheck.wait_notice = popen, kill_chrome_on_the_second_wait
with tempfile.TemporaryDirectory(prefix="ritmelli-ligar-gone-") as tmp:
    with open(Path(tmp) / "server.log", "w", encoding="utf-8") as log:
        srv = compara.sobe_servidor(Path(tmp), so_mock.free_port(), log,
                                    config={"boas_vindas": True, "metricas": False}, extras=["--metricas-teste"])
        try:
            r = asyncio.run(fitcheck.aviso_no_chrome(srv.base, "ligar"))
        finally:
            compara.para_servidor(srv)
print("RESULT " + json.dumps({"r": r, "waits": len(waits)}))
"""
LATE_S = fitcheck.AVISO_ESPERA_S + 2
LATE_ASKED = "/__ritmelli-test-late-notice"
LATE_STATE_S = 2.0
STACKS_HOOK = ROOT / "dev" / "stacks_hook"
STACKS_MARK = "---- the server's stacks, asked by the test"
HELD_CHILD = '''
import sys
import threading


def held_in_this_function():
    print("ready", flush=True)
    threading.Event().wait()


held_in_this_function()
'''
SLOW_UPSTREAM = '''
import http.server
import sys
import threading


class Slow(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        state_held_upstream()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


released = threading.Event()


def state_held_upstream():
    released.wait(float(sys.argv[2]))


threading.Thread(target=lambda: (sys.stdin.readline(), released.set()), daemon=True).start()
server = http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), Slow)
print("listening", flush=True)
server.serve_forever()
'''
LATE_NOTICE = ("<script>(() => { const show = HTMLDialogElement.prototype.showModal; "
               "HTMLDialogElement.prototype.showModal = function () { if (this.id !== 'dlg-metricas') "
               f"return show.call(this); fetch('{LATE_ASKED}'); "
               f"setTimeout(() => show.call(this), {LATE_S * 1000:.0f}); }}; }})();</script>")
HOP_HEADERS = {"host", "origin", "referer", "content-length", "transfer-encoding", "connection", "content-encoding"}

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


class ServerStacks:
    def __init__(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port, self.asker, self.asked = self.listener.getsockname()[1], None, False
        self.accepted = threading.Event()
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        with contextlib.suppress(OSError):
            self.asker, _ = self.listener.accept()
        self.accepted.set()

    def env(self):
        path = os.pathsep.join(p for p in (str(STACKS_HOOK), os.environ.get("PYTHONPATH")) if p)
        return {"PYTHONPATH": path, "RITMELLI_STACKS_PORT": str(self.port)}

    def ask(self):
        if self.asker is not None and not self.asked:
            self.asked = True
            self.asker.sendall(b"x")

    def of(self, log):
        text = Path(log).read_text(encoding="utf-8", errors="replace")
        return text[text.index(STACKS_MARK):] if self.asked and STACKS_MARK in text else None

    def close(self):
        if self.asker is not None:
            self.asker.close()
        self.listener.close()


class ThemeProxy:
    def __init__(self, target, hold_script_s=0, hold_state_s=0, late_notice=False, stacks=None):
        self.target, self.port = target, so_mock.free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.hold_script_s, self.hold_state_s, self.late_notice = hold_script_s, hold_state_s, late_notice
        self.held, self.started, self.stacks = [], threading.Event(), stacks

    def hold_for(self, request):
        from_browser = "Chrome" in request.headers.get("User-Agent", "")
        if self.hold_script_s and request.path.startswith("/t/ritmelli/") and request.path.endswith(".js"):
            return 0 if self.held else self.hold_script_s
        if self.hold_state_s and from_browser and request.path == "/api/state":
            return self.hold_state_s
        return 0

    async def forward(self, request):
        if request.path == LATE_ASKED:
            self.held.append(request.path)
            return web.Response(status=204)
        if hold := self.hold_for(request):
            self.held.append(request.path)
            await asyncio.sleep(hold)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS | {"accept-encoding"}}
        if "Origin" in request.headers:
            headers["Origin"] = self.target
        late = None
        if (self.stacks is not None and request.method == "GET" and request.path == "/api/state"
                and "Chrome" in request.headers.get("User-Agent", "")):
            late = asyncio.get_running_loop().call_later(LATE_STATE_S, self.stacks.ask)
        try:
            return await self.relay(request, headers, late)
        finally:
            if late is not None:
                late.cancel()

    async def relay(self, request, headers, late):
        async with self.session.request(request.method, self.target + request.path_qs, headers=headers,
                                        data=await request.read(), allow_redirects=False) as upstream:
            if late is not None:
                late.cancel()
            response = web.StreamResponse(status=upstream.status, headers={
                k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS})
            await response.prepare(request)
            if self.late_notice and request.path == "/t/ritmelli/":
                page = (await upstream.read()).decode("utf-8")
                await response.write(page.replace("<head>", "<head>" + LATE_NOTICE, 1).encode("utf-8"))
            else:
                async for chunk in upstream.content.iter_any():
                    await response.write(chunk)
            await response.write_eof()
            return response

    async def serve(self, stop):
        self.session = ClientSession(auto_decompress=False)
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.forward)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", self.port).start()
        self.started.set()
        await stop.wait()
        await runner.cleanup()
        await self.session.close()


def notice_through(proxy_options, config, button=None):
    with tempfile.TemporaryDirectory(prefix="ritmelli-notice-") as tmp:
        tmp = Path(tmp)
        stacks = ServerStacks()
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, config=config, extras=["--metricas-teste"],
                                        env=stacks.env())
            try:
                proxy = ThemeProxy(srv.base, stacks=stacks, **proxy_options)
                loop, stop = asyncio.new_event_loop(), asyncio.Event()
                thread = threading.Thread(target=loop.run_until_complete, args=(proxy.serve(stop),), daemon=True)
                thread.start()
                proxy.started.wait(10)
                try:
                    r = asyncio.run(fitcheck.aviso_no_chrome(proxy.base, button))
                finally:
                    loop.call_soon_threadsafe(stop.set)
                    thread.join(10)
            finally:
                try:
                    compara.para_servidor(srv)
                finally:
                    stacks.close()
                    found = stacks.of(tmp / "server.log")
                    if found:
                        print(found[-6000:], file=sys.stderr, flush=True)
        if found:
            r["server_stacks"] = found[-6000:]
    return r, proxy


def child_stacks(code, stacks, ready, *args):
    child = subprocess.Popen([sys.executable, "-c", code, *args], env=dict(os.environ, **stacks.env()),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8")
    said, came = [], threading.Event()
    reader = threading.Thread(target=lambda: (said.append(child.stdout.readline()), came.set()), daemon=True)
    reader.start()
    if came.wait(10) and said[0].strip() == ready:
        stacks.accepted.wait(10)
        return child
    try:
        child.kill()
        child.wait()
        reader.join(10)
        child.communicate()
    finally:
        stacks.close()
    raise TimeoutError(f"the child did not say {ready!r} in 10 s ({said})")


def stacks_of_a_held_process():
    stacks = ServerStacks()
    child = child_stacks(HELD_CHILD, stacks, "ready")
    try:
        stacks.ask()
        seen, dumped = [], threading.Event()

        def read():
            for line in child.stderr:
                seen.append(line)
                if "held_in_this_function" in line:
                    dumped.set()

        threading.Thread(target=read, daemon=True).start()
        dumped.wait(10)
    finally:
        child.kill()
        child.wait()
        stacks.close()
    text = "".join(seen)
    check(STACKS_MARK in text and "held_in_this_function" in text,
          f"a test server asked for its stacks prints every thread's, with the function it is held in ({text[-300:]!r})")


def proxy_asks_when_the_state_is_late():
    stacks, port = ServerStacks(), so_mock.free_port()
    child = child_stacks(SLOW_UPSTREAM, stacks, "listening", str(port), "30")
    err, held = [], threading.Event()

    def read():
        for line in child.stderr:
            err.append(line)
            if "state_held_upstream" in line:
                held.set()

    threading.Thread(target=read, daemon=True).start()
    status, seen = None, False
    try:
        proxy = ThemeProxy(f"http://127.0.0.1:{port}", stacks=stacks)
        loop, stop = asyncio.new_event_loop(), asyncio.Event()
        thread = threading.Thread(target=loop.run_until_complete, args=(proxy.serve(stop),), daemon=True)
        thread.start()
        proxy.started.wait(10)

        async def state():
            async with ClientSession() as session:
                pending = asyncio.ensure_future(session.get(proxy.base + "/api/state", headers={"User-Agent": "Chrome"}))
                found = await asyncio.to_thread(held.wait, 10)
                child.stdin.write("release\n")
                child.stdin.flush()
                async with await pending as r:
                    return r.status, found

        status, seen = asyncio.run(state())
        loop.call_soon_threadsafe(stop.set)
        thread.join(10)
    finally:
        child.kill()
        child.wait()
        stacks.close()
    text = "".join(err)
    check(status == 200 and stacks.asked and seen,
          f"the proxy asks the server for its stacks once its GET /api/state is {LATE_STATE_S:.0f} s late, and they show "
          f"where the server is held ({status}, asked {stacks.asked}, {text[-300:]!r})")


def notice_on_slow_load():
    r, proxy = notice_through({"hold_script_s": LATE_S}, {"boas_vindas": True})
    check(bool(proxy.held) and r["abriu"] is True and not r["erros"],
          f"with a theme script held {LATE_S:.0f} s ({proxy.held}), longer than the "
          f"{fitcheck.AVISO_ESPERA_S:.0f} s wait for the notice, the notice is still seen opening on load ({r})")


def notice_on_slow_state():
    r, proxy = notice_through({"hold_state_s": LATE_S}, {"boas_vindas": True})
    gap = r["load_to_state_s"]
    check("/api/state" in proxy.held and gap is not None and gap > fitcheck.AVISO_ESPERA_S and r["abriu"] is True
          and not r["erros"],
          f"with the page's GET /api/state ending {gap} s after the load event, more than the "
          f"{fitcheck.AVISO_ESPERA_S:.0f} s wait, the notice is still seen opening: the clock starts at that response "
          f"({r})")


def notice_reopens_on_slow_state():
    r, proxy = notice_through({"hold_state_s": LATE_S}, {"boas_vindas": True, "metricas": True}, "esc")
    held = proxy.held.count("/api/state")
    check(held >= 2 and r["abriu"] is True and r["fechou"] is True and r["reabriu"] is True and not r["not_ready"],
          f"with every GET /api/state of the page held {LATE_S:.0f} s ({held} held), the notice closed by Esc is "
          f"still seen opening again on the next load: that wait also starts at the state ({r})")


def notice_late_after_state():
    r, proxy = notice_through({"late_notice": True}, {"boas_vindas": True})
    check(LATE_ASKED in proxy.held and r["abriu"] is False and not r["not_ready"],
          f"a notice that opens {LATE_S:.0f} s after the state, past the {fitcheck.AVISO_ESPERA_S:.0f} s wait, fails "
          f"the check ({r})")


def probe_past_the_deadline():
    async def never_answers(method, **params):
        await asyncio.Event().wait()

    async def notice_open(method, **params):
        return {"result": {"value": True}}

    start = time.monotonic()
    late = asyncio.run(fitcheck.wait_notice(never_answers, start + 0.3))
    took = time.monotonic() - start
    check(late is False and took < 2, f"a probe whose answer crosses the deadline does not count, and the wait ends at "
                                      f"the deadline ({late}, {took:.2f} s)")
    check(asyncio.run(fitcheck.wait_notice(notice_open, time.monotonic() + 0.3)) is True,
          "a probe that answers open before the deadline counts")
    check(asyncio.run(fitcheck.wait_notice(notice_open, time.monotonic() - 0.1)) is False,
          "a deadline already past does not probe")

    async def gone(method, **params):
        raise ConnectionError("the DevTools connection ended (closed)")

    check(asyncio.run(fitcheck.wait_notice(gone, time.monotonic() + 1)) is None,
          "a Chrome that goes away during the wait for the notice is told apart from a notice that did not open")

    async def open_but_late(method, **params):
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            pass
        return {"result": {"value": True}}

    check(asyncio.run(fitcheck.wait_notice(open_but_late, time.monotonic() + 0.2)) is False,
          "a probe that answers open after the deadline, before its timeout runs, does not count")


ORIGIN = "http://127.0.0.1:1"


def sent(request, loader, ticks, path="/api/state", method="GET", origin=ORIGIN):
    return {"method": "Network.requestWillBeSent",
            "params": {"requestId": request, "loaderId": loader, "timestamp": ticks, "wallTime": ticks + 1e9,
                       "request": {"method": method, "url": f"{origin}{path}"}}}


def answered(request, status=200, path="/api/state"):
    return {"method": "Network.responseReceived",
            "params": {"requestId": request, "response": {"status": status, "url": f"{ORIGIN}{path}"}}}


def finished(request, ticks):
    return {"method": "Network.loadingFinished", "params": {"requestId": request, "timestamp": ticks}}


def calibrated(offset):
    events = fitcheck.PageEvents(ORIGIN)
    events.mono_minus_ticks = offset
    return events


def state_of_this_navigation_only():
    events = calibrated(1000.0)
    for m in (sent("a", "old", 10.0), answered("a"), finished("a", 10.5),
              sent("b", "new", 11.0, "/api/library"), answered("b", path="/api/library"), finished("b", 11.5),
              sent("c", "new", 12.0, method="POST"), answered("c"), finished("c", 12.5),
              sent("e", "new", 12.5), answered("e", 500), finished("e", 12.75),
              sent("f", "new", 12.6, origin="http://127.0.0.1:2"), answered("f"), finished("f", 12.8),
              sent("g", "new", 12.7), sent("g", "new", 12.75, "/elsewhere"), answered("g", path="/elsewhere"),
              finished("g", 12.9),
              sent("d", "new", 13.0), answered("d"), finished("d", 13.25)):
        events.take(m)
        if m["params"]["requestId"] in ("e", "f", "g") and m["method"] == "Network.loadingFinished":
            events.loader = "new"
            if events.state_at is not None:
                check(False, f"request {m['params']['requestId']} started the clock")
            events.loader = None
    before = events.state_at
    events.loader = "new"
    check(before is None and events.state_at == 1013.25,
          "the GET /api/state of the current navigation starts the clock at its own end, even when its events came "
          "before Page.navigate returned, and not one of the page before it, another request, a failed state, another "
          "origin or a request redirected away")


def clock_from_the_event_not_from_its_handling():
    events = calibrated(time.monotonic() - 9 - 101.0)
    events.loader = "now"
    for m in (sent("a", "now", 100.0), answered("a"), finished("a", 101.0)):
        events.take(m)

    async def notice_open(method, **params):
        return {"result": {"value": True}}

    late = asyncio.run(fitcheck.wait_notice(notice_open, events.state_at + fitcheck.AVISO_ESPERA_S))
    check(late is False and abs(time.monotonic() - events.state_at - 9) < 0.5,
          f"state events handled 9 s after the state ended: the {fitcheck.AVISO_ESPERA_S:.0f} s already passed, and a "
          f"notice open now does not count ({late})")


def no_wall_clock_in_the_conversion():
    events = calibrated(500.0)
    events.loader = "now"
    for m in (sent("a", "now", 100.0), answered("a"), finished("a", 101.0)):
        events.take(m)
    at = events.state_at
    real_time = time.time
    time.time = lambda: real_time() + 3600
    try:
        events.take(sent("z", "now", 102.0, "/api/library"))
        stepped = events.state_at
    finally:
        time.time = real_time
    check(at == 601.0 and stepped == at,
          f"a wall clock step and another request after the state leave the clock where it was ({at}, {stepped})")


def ready_answer_past_the_deadline():
    async def ready_but_late(method, **params):
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            pass
        return {"result": {"value": True}}

    outcome = asyncio.run(fitcheck.wait_ready(ready_but_late, "true", [], 0.2))
    check(outcome is fitcheck.Ready.TIMED_OUT,
          f"the shared ready wait does not accept a ready answer that came after its deadline ({outcome})")
    blocked = []

    async def ready_after_a_block(method, **params):
        blocked.append("http://elsewhere.invalid/")
        return {"result": {"value": True}}

    outcome = asyncio.run(fitcheck.wait_ready(ready_after_a_block, "true", blocked, 5))
    check(outcome is fitcheck.Ready.LEFT,
          f"a page blocked from leaving while a probe was out is reported as leaving, not ready ({outcome})")


def notice_page_not_ready():
    saved = fitcheck.PRONTA_S
    fitcheck.PRONTA_S = 2.0
    try:
        r, _ = notice_through({"hold_state_s": 6}, {"boas_vindas": True, "metricas": False}, "ligar")
    finally:
        fitcheck.PRONTA_S = saved
    check(r["not_ready"] == ["notice: the theme was not ready in 2 s"] and r["abriu"] is False
          and r["ao_ligar"] is None,
          f"a page whose state never comes ends the notice check there, with no click on it ({r})")


def fitcheck_never_ready():
    with tempfile.TemporaryDirectory(prefix="ritmelli-fitcheck-not-ready-") as tmp:
        tmp = Path(tmp)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log)
            try:
                p = subprocess.run([sys.executable, "-c", FITCHECK_NEVER_READY, str(ROOT), NEVER_READY,
                                    f"{srv.base}/t/ritmelli/?lang=pt_BR", str(tmp / "shots")], cwd=ROOT,
                                   env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=180)
            finally:
                compara.para_servidor(srv)
        out = p.stdout + p.stderr
        print(out.rstrip())
        lines = out.splitlines()
        check(p.returncode == 1 and any(line.startswith("FALHA") and "390x844: the theme was not ready in 3 s" in line
                                        for line in lines),
              f"the fitcheck fails a size whose theme never gets ready, with the shared verdict (exit {p.returncode})")
        check(any(re.fullmatch(rf"  response: 404 http://127\.0\.0\.1:\d+/.*{re.escape(SCRIPT_MARK)}", line)
                  for line in lines), "the fitcheck prints the 404 of the script, read from Network.responseReceived")
        shot = tmp / "shots" / "not-ready_390x844.png"
        check(shot.is_file() and shot.stat().st_size > 0, "the fitcheck saves a print of the page that was not ready")


def fitcheck_timeout_then_chrome_gone():
    with tempfile.TemporaryDirectory(prefix="ritmelli-fitcheck-gone-") as tmp:
        tmp = Path(tmp)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log)
            try:
                p = subprocess.run([sys.executable, "-c", FITCHECK_TIMEOUT_THEN_GONE, str(ROOT), NEVER_READY,
                                    f"{srv.base}/t/ritmelli/?lang=pt_BR"], cwd=ROOT,
                                   env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=180)
            finally:
                compara.para_servidor(srv)
    out = p.stdout + p.stderr
    print(out.rstrip())
    lines = out.splitlines()
    verdict = next((i for i, line in enumerate(lines) if line.startswith("FALHA")
                    and "390x844: the theme was not ready in 2 s" in line), None)
    console = next((i for i, line in enumerate(lines) if line.startswith("  console: ") and CONSOLE_MARK in line), None)
    gone = next((i for i, line in enumerate(lines) if line.startswith("FALHA")
                 and "768x1024: the Chrome DevTools connection closed" in line), None)
    check(p.returncode == 1 and verdict is not None and console is not None and console < verdict
          and gone is not None and gone > verdict and "Traceback" not in out,
          f"the fitcheck, its Chrome gone right after a timeout, still gives the shared verdict and what it had "
          f"collected, then says the Chrome went away at the next size, with no traceback (exit {p.returncode})")


def ligar_then_chrome_gone(when):
    p = subprocess.run([sys.executable, "-c", LIGAR_THEN_GONE, str(ROOT), when], cwd=ROOT,
                       env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    out = p.stdout + p.stderr
    print(out.rstrip())
    line = next((x for x in out.splitlines() if x.startswith("RESULT ")), "")
    result = json.loads(line[len("RESULT "):]) if line else {}
    r = result.get("r", {})
    check(result.get("waits") == 2 and (r.get("ao_ligar") is None or when == "after") and "Traceback" not in out
          and any("browser went away" in v for v in r.get("not_ready", [])),
          f"a Chrome that goes away {when} the wait after Comecar a enviar ends the check with the Chrome-gone verdict, "
          f"with no traceback ({r.get('not_ready')})")


def timeout_then_disconnect():
    events = fitcheck.PageEvents()
    events.page_errors.append("console.error: collected before the timeout")

    async def gone(method, **params):
        raise ConnectionError("the DevTools connection ended (closed)")

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        verdict = asyncio.run(fitcheck.report_not_ready(gone, "390x844", fitcheck.Ready.TIMED_OUT,
                                                         fitcheck.READY_CONDITIONS, events, 20.0))
    text = out.getvalue()
    check(verdict == "390x844: the theme was not ready in 20 s" and "collected before the timeout" in text
          and "the conditions did not come: ConnectionError" in text,
          f"a timeout whose diagnostic finds the connection gone still gives the shared verdict and what it had "
          f"collected ({verdict})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    timeout_then_disconnect()
    probe_past_the_deadline()
    state_of_this_navigation_only()
    clock_from_the_event_not_from_its_handling()
    no_wall_clock_in_the_conversion()
    ready_answer_past_the_deadline()
    stacks_of_a_held_process()
    proxy_asks_when_the_state_is_late()
    notice_on_slow_load()
    notice_on_slow_state()
    notice_reopens_on_slow_state()
    notice_late_after_state()
    notice_page_not_ready()
    fitcheck_never_ready()
    fitcheck_timeout_then_chrome_gone()
    ligar_then_chrome_gone("during")
    ligar_then_chrome_gone("after")
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
