import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve() / "dev"))
import compara
import test_fitcheck_ready as t
from aiohttp import web

marks = []
start = [0.0]
logs = []
hooks = Path(tempfile.mkdtemp(prefix="ritmelli-fh-"))
trigger = hooks / "dump-now"
SITE = '''import faulthandler, os, threading, time
TRIGGER = %r
def watch():
    while True:
        time.sleep(0.2)
        if os.path.exists(TRIGGER):
            print("---- stacks at", time.monotonic(), flush=True)
            faulthandler.dump_traceback(all_threads=True)
            time.sleep(2.0)
threading.Thread(target=watch, daemon=True).start()
''' % str(trigger)
(hooks / "sitecustomize.py").write_text(SITE, encoding="utf-8")


def mark(*what):
    marks.append((round(time.monotonic() - start[0], 2), round(time.monotonic(), 2), *what))


async def dump_if_late(seconds):
    await asyncio.sleep(seconds)
    trigger.write_text("now", encoding="utf-8")
    mark("asked the server for its stacks")


async def forward(self, request):
    path = request.path
    is_state = path == "/api/state"
    agent = "chrome" if "Chrome" in request.headers.get("User-Agent", "") else "other"
    if is_state:
        mark("state in", agent)
    if path == t.LATE_ASKED:
        self.held.append(path)
        return web.Response(status=204)
    if hold := self.hold_for(request):
        self.held.append(path)
        await asyncio.sleep(hold)
        if is_state:
            mark("state hold over", agent)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in t.HOP_HEADERS | {"accept-encoding"}}
    if "Origin" in request.headers:
        headers["Origin"] = self.target
    late = asyncio.ensure_future(dump_if_late(2.0)) if is_state else None
    try:
        async with self.session.request(request.method, self.target + request.path_qs, headers=headers,
                                        data=await request.read(), allow_redirects=False) as upstream:
            if late:
                late.cancel()
            if is_state:
                mark("state upstream answered", agent, upstream.status)
            response = web.StreamResponse(status=upstream.status, headers={
                k: v for k, v in upstream.headers.items() if k.lower() not in t.HOP_HEADERS})
            await response.prepare(request)
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            if is_state:
                mark("state done", agent)
            return response
    except BaseException as ex:
        mark("error", path, agent, type(ex).__name__, str(ex)[:80])
        raise


real_sobe, real_para = compara.sobe_servidor, compara.para_servidor


def sobe(tmp, porta, log, *args, **kwargs):
    env = dict(kwargs.pop("env", None) or {}, PYTHONPATH=str(hooks))
    srv = real_sobe(tmp, porta, log, *args, env=env, **kwargs)
    srv.log_path = log.name
    return srv


def para(srv):
    try:
        logs.append(Path(srv.log_path).read_text(encoding="utf-8", errors="replace"))
    finally:
        real_para(srv)


t.ThemeProxy.forward = forward
compara.sobe_servidor, compara.para_servidor = sobe, para
n, bad = int(sys.argv[2]), 0
for i in range(n):
    marks.clear()
    logs.clear()
    trigger.unlink(missing_ok=True)
    start[0] = time.monotonic()
    before = len(t.failures)
    t.notice_reopens_on_slow_state()
    failed = len(t.failures) > before
    bad += failed
    print(i, "FAIL" if failed else "ok", marks[:14], flush=True)
    if failed or trigger.exists():
        print("---- server log of this round ----")
        print("\n".join(logs)[-60000:])
        print("---- end ----", flush=True)
print("bad", bad, "of", n)
