import asyncio
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dev"))
import compara
import fitcheck
import so_mock

CONSOLE_MARK = "ritmelli-test-console-error"
SCRIPT_MARK = "ritmelli-test-missing.js"
NEVER_READY = ("(() => { if (!window.__ritmelliTest) { window.__ritmelliTest = true; console.error('" + CONSOLE_MARK +
               "'); const s = document.createElement('script'); s.src = '" + SCRIPT_MARK + "'; "
               "document.head.appendChild(s); } return false; })()")
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
SLOW_SCRIPT_S = fitcheck.AVISO_ESPERA_S + 3
HOP_HEADERS = {"host", "origin", "referer", "content-length", "transfer-encoding", "connection", "content-encoding"}

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


class SlowThemeProxy:
    def __init__(self, target):
        self.target, self.delayed, self.port = target, [], so_mock.free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.started = threading.Event()

    async def forward(self, request):
        if request.path.startswith("/t/ritmelli/") and request.path.endswith(".js") and not self.delayed:
            self.delayed.append(request.path)
            await asyncio.sleep(SLOW_SCRIPT_S)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
        if "Origin" in request.headers:
            headers["Origin"] = self.target
        async with self.session.request(request.method, self.target + request.path_qs, headers=headers,
                                        data=await request.read(), allow_redirects=False) as upstream:
            response = web.StreamResponse(status=upstream.status, headers={
                k: v for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS})
            await response.prepare(request)
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


def notice_on_slow_load():
    with tempfile.TemporaryDirectory(prefix="ritmelli-slow-load-") as tmp:
        tmp = Path(tmp)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, config={"boas_vindas": True},
                                        extras=["--metricas-teste"])
            try:
                proxy = SlowThemeProxy(srv.base)
                loop = asyncio.new_event_loop()
                stop = asyncio.Event()
                thread = threading.Thread(target=loop.run_until_complete, args=(proxy.serve(stop),), daemon=True)
                thread.start()
                proxy.started.wait(10)
                try:
                    r = asyncio.run(fitcheck.aviso_no_chrome(proxy.base, None))
                finally:
                    loop.call_soon_threadsafe(stop.set)
                    thread.join(10)
            finally:
                compara.para_servidor(srv)
    check(bool(proxy.delayed), f"the proxy held a theme script {SLOW_SCRIPT_S:.0f} s ({proxy.delayed})")
    check(r["abriu"] is True and not r["erros"],
          f"with a theme script {SLOW_SCRIPT_S:.0f} s late, longer than the {fitcheck.AVISO_ESPERA_S:.0f} s wait "
          f"for the notice, the notice is still seen opening on load ({r})")


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


def notice_page_not_ready():
    with tempfile.TemporaryDirectory(prefix="ritmelli-notice-not-ready-") as tmp:
        tmp = Path(tmp)
        with open(tmp / "server.log", "w", encoding="utf-8") as log:
            srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, config={"boas_vindas": True, "metricas": False},
                                        extras=["--metricas-teste"])
            saved = fitcheck.PRONTA, fitcheck.PRONTA_S
            fitcheck.PRONTA, fitcheck.PRONTA_S = "false", 2.0
            try:
                r = asyncio.run(fitcheck.aviso_no_chrome(srv.base, "ligar"))
            finally:
                fitcheck.PRONTA, fitcheck.PRONTA_S = saved
                compara.para_servidor(srv)
    check(r["not_ready"] == ["notice: the theme was not ready in 2 s"] and r["abriu"] is False
          and r["ao_ligar"] is None,
          f"a page that never gets ready ends the notice check there, with no click on it ({r})")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    notice_on_slow_load()
    notice_page_not_ready()
    fitcheck_never_ready()
    print(f"{'all passed' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
