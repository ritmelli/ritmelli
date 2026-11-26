import sys
from pathlib import Path

p = Path("dev/fitcheck.py")
s = p.read_text(encoding="utf-8")
nav = '                    events.loader = (await cmd("Page.navigate", url=url)).get("loaderId")'
clock = "wait_notice(cmd, events.state_at + AVISO_ESPERA_S)"
if s.count(nav) != 1 or s.count(clock) != 1:
    sys.exit("the mutant did not apply")
s = s.replace(nav, "                    navigated = time.monotonic()\n" + nav)
s = s.replace(clock, "wait_notice(cmd, navigated + AVISO_ESPERA_S)")
p.write_text(s, encoding="utf-8")
print("mutant: the notice clock starts at Page.navigate")
