import sys

sys.path.insert(0, "dev")
import fitcheck
import test_fitcheck_ready as t

slow_load, load_proxy = t.notice_through({"hold_script_s": t.LATE_S}, {"boas_vindas": True})
slow_state, state_proxy = t.notice_through({"hold_state_s": t.LATE_S}, {"boas_vindas": True})
cases = (("slow load", slow_load, bool(load_proxy.held)),
         ("slow state", slow_state, "/api/state" in state_proxy.held
          and (slow_state["load_to_state_s"] or 0) > fitcheck.AVISO_ESPERA_S))
bad = 0
for name, r, delayed in cases:
    only_the_notice = (delayed and not r["not_ready"] and not r["erros"] and r["load_to_state_s"] is not None
                       and r["abriu"] is False)
    print(f"{name}: {'the notice alone failed' if only_the_notice else 'NOT the expected failure'} ({r})")
    bad += not only_the_notice
print("MATCH" if not bad else "MISMATCH")
sys.exit(1 if bad else 0)
