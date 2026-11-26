import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve() / "dev"))
import test_fitcheck_ready as t
from aiohttp import web

marks = []
start = [0.0]


def mark(*what):
    marks.append((round(time.monotonic() - start[0], 2), *what))


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
    try:
        async with self.session.request(request.method, self.target + request.path_qs, headers=headers,
                                        data=await request.read(), allow_redirects=False) as upstream:
            if is_state:
                mark("state upstream answered", agent, upstream.status)
            response = web.StreamResponse(status=upstream.status, headers={
                k: v for k, v in upstream.headers.items() if k.lower() not in t.HOP_HEADERS})
            await response.prepare(request)
            if is_state:
                mark("state headers written", agent)
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            if is_state:
                mark("state done", agent)
            return response
    except BaseException as ex:
        mark("error", path, agent, type(ex).__name__, str(ex)[:80])
        raise


t.ThemeProxy.forward = forward
n, bad = int(sys.argv[2]), 0
for i in range(n):
    marks.clear()
    start[0] = time.monotonic()
    before = len(t.failures)
    t.notice_reopens_on_slow_state()
    failed = len(t.failures) > before
    bad += failed
    print(i, "FAIL" if failed else "ok", marks, flush=True)
print("bad", bad, "of", n)
