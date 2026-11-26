import sys

sys.path.insert(0, "dev")
import test_fitcheck_ready as t

t.notice_on_slow_load()
t.notice_on_slow_state()
f = t.failures
ok = (len(f) == 2 and f[0].startswith("with a theme script held") and f[1].startswith("with the page")
      and all("'abriu': False" in x for x in f))
print("MATCH: both slow cases fail with the notice not seen" if ok else f"MISMATCH: {f}")
sys.exit(0 if ok else 1)
