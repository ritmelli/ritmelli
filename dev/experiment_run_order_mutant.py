import subprocess
import sys
from pathlib import Path

p = Path("dev/fitcheck.py")
s = p.read_text(encoding="utf-8")
anchor = "                    ready = await navigate_and_wait(cmd, a.url, PRONTA, barrados, PRONTA_S)\n"
if s.count(anchor) != 1:
    sys.exit("the mutant did not apply")
p.write_text(s.replace(anchor, anchor + "                    await confere_pagina(cmd, a.url, barrados)\n"), encoding="utf-8")
try:
    sys.path.insert(0, "dev")
    import test_fitcheck_ready as t
    t.fitcheck_timeout_then_chrome_gone()
finally:
    subprocess.run(["git", "checkout", "HEAD", "--", "dev/fitcheck.py"], check=True)
caught = len(t.failures) == 1 and t.failures[0].startswith("the fitcheck, its Chrome gone right after a timeout")
print("MATCH: the origin check before the verdict fails the test" if caught else f"MISMATCH: {t.failures}")
sys.exit(0 if caught else 1)
