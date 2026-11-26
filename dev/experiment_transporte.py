import asyncio, sys, tempfile, time
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "dev"))
import compara, so_mock, missing_script as ms

async def transporte(tab):
    tab.failing.add("transporte.js")
    await ms.open_page(tab)
    t0 = time.monotonic()
    card = (await tab.page_reaches("s.card", ms.CARD_SHOWS_S))
    t1 = time.monotonic()
    tab.failing.clear()
    back = await tab.page_reaches("s.online === true && !s.card", ms.RELOAD_S)
    t2 = time.monotonic()
    ok = card.get("card") and back.get("online") is True and len(tab.documents) == 1
    return ok, f"card {card.get('card')} after {t1-t0:.1f}s, back {back.get('online')} card {back.get('card')} after {t2-t1:.1f}s, asks {tab.asked.get('transporte.js')}, docs {len(tab.documents)}"

n, bad = int(sys.argv[2]), 0
with tempfile.TemporaryDirectory(prefix="ritmelli-transporte-", ignore_cleanup_errors=True) as folder:
    tmp = Path(folder)
    with open(tmp / "server.log", "w", encoding="utf-8") as log:
        srv = compara.sobe_servidor(tmp, so_mock.free_port(), log, raiz=root, config={"boas_vindas": True}, extras=[])
        try:
            for i in range(n):
                ok, msg = asyncio.run(ms.with_tab(srv, transporte))
                bad += not ok
                print("OK  " if ok else "FAIL", i, msg, flush=True)
        finally:
            compara.para_servidor(srv)
print("bad", bad, "of", n)
