import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "dev" / "tla"
JAR_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
JAR_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
LIMIT_S = 60
KEYWORDS = ("CONSTANTS", "SYMMETRY", "SPECIFICATION", "INVARIANTS", "PROPERTIES", "CHECK_DEADLOCK")


@dataclass(frozen=True)
class Run:
    title: str
    spec: str
    expect: str = "pass"
    constants: tuple = ()
    invariants: tuple = None
    properties: tuple = ()
    specification: str = None
    symmetry: bool = True
    deadlock: bool = True
    known: int = None


RACES_SAFE = ("TypeOK", "LockOrderKept")
RUNS = (
    Run("Races211, the code as it is: types and lock order", "Races211", invariants=RACES_SAFE),
    Run("Races211, the code as it is: #211.1, a failed download and a refused stream leave the platter loading",
        "Races211", "invariant NoOrphanLoading", invariants=("NoOrphanLoading",), known=211),
    Run("Races211, the code as it is: a finished download and a refused stream leave the platter loading",
        "Races211", "invariant NoStaleLoading", invariants=("NoStaleLoading",), known=211),
    Run("Races211, the code as it is: #211.2, the pending switch's entry gets the audio version",
        "Races211", "invariant SwitchEntryMatchesPlatter", invariants=("SwitchEntryMatchesPlatter",), known=211),
    Run("Races211 with the fix", "Races211",
        constants=(("StreamFailureChecksJob", "TRUE"), ("AudioSwapThroughChangeQueue", "TRUE"))),
    Run("LocksAndSwitch, the code as it is", "LocksAndSwitch"),
    Run("LocksAndSwitch, the code as it is: every reservation resolves (weak fairness, no symmetry)",
        "LocksAndSwitch", invariants=(), properties=("ReservationsResolve",), specification="FairSpec",
        symmetry=False, deadlock=False, constants=(("Reopens", "FALSE"),)),
    Run("mutant: overlapping Nexts do not join", "LocksAndSwitch", "invariant OneAdvance",
        constants=(("NextsJoin", "FALSE"),)),
    Run("mutant: the first Next does not resolve its group", "LocksAndSwitch", "deadlock",
        constants=(("NextResolvesItsGroup", "FALSE"),)),
    Run("mutant: the Stop does not close the pending switch first", "LocksAndSwitch",
        "invariant HistoryOnceInOrder", constants=(("StopClosesSwitches", "FALSE"),)),
    Run("mutant: a queue change outside the _qlock", "LocksAndSwitch", "invariant SwitchOnlyToHead",
        constants=(("QueueChangeUnderQlock", "FALSE"),)),
    Run("mutant: the reservation reads App.proximo under the proximo_lock", "LocksAndSwitch",
        "invariant LockOrderKept", constants=(("ReserveReadsProximoWithoutLock", "FALSE"),)),
    Run("mutant: taking the switch leaves it in the engine", "LocksAndSwitch", "invariant SwitchClosesOnce",
        constants=(("TakingTheSwitchClearsIt", "FALSE"),)),
    Run("mutant: a swap that fails keeps its reservation", "LocksAndSwitch", "property", invariants=(),
        properties=("ReservationsResolve",), specification="FairSpec", symmetry=False, deadlock=False,
        constants=(("FailedSwapReleasesReservation", "FALSE"), ("Reopens", "FALSE"))),
)

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def parse_cfg(text):
    blocks, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        word, _, rest = line.partition(" ")
        if word in KEYWORDS:
            current = blocks.setdefault(word, [])
            if rest.strip():
                current.append(rest.strip())
        elif current is not None:
            current.append(line)
    return blocks


def write_cfg(base, run):
    blocks = parse_cfg(base)
    constants = dict(c.split(" = ", 1) for c in blocks.get("CONSTANTS", []))
    for name, value in run.constants:
        if name not in constants:
            raise KeyError(f"{run.spec}.cfg has no constant {name}")
        constants[name] = value
    blocks["CONSTANTS"] = [f"{k} = {v}" for k, v in constants.items()]
    if run.invariants is not None:
        blocks["INVARIANTS"] = list(run.invariants)
    if run.properties:
        blocks["PROPERTIES"] = list(run.properties)
    if run.specification:
        blocks["SPECIFICATION"] = [run.specification]
    if not run.symmetry:
        blocks.pop("SYMMETRY", None)
    blocks["CHECK_DEADLOCK"] = ["TRUE" if run.deadlock else "FALSE"]
    out = []
    for word in KEYWORDS:
        if blocks.get(word):
            out.append(word)
            out.extend(f"    {item}" for item in blocks[word])
    return "\n".join(out) + "\n"


def outcome(text):
    m = re.search(r"Error: Invariant (\w+) is violated", text)
    if m:
        return f"invariant {m.group(1)}"
    if "Error: Deadlock reached." in text:
        return "deadlock"
    if "Error: Temporal properties were violated." in text:
        return "property"
    if "Model checking completed. No error has been found." in text:
        return "pass"
    return "error"


def states(text):
    m = re.search(r"([\d,]+) distinct states found", text)
    return m.group(1).replace(",", "") if m else "?"


def jar_path(tmp):
    given = os.environ.get("TLA2TOOLS")
    path = Path(given) if given else tmp / "tla2tools.jar"
    if not given:
        with urllib.request.urlopen(JAR_URL, timeout=60) as r, open(path, "wb") as f:
            shutil.copyfileobj(r, f)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    check(digest == JAR_SHA256, f"tla2tools.jar is the pinned one (sha256 {digest})")
    return path if digest == JAR_SHA256 else None


def tlc(java, jar, work, run, index):
    cfg = work / f"run{index}.cfg"
    cfg.write_text(write_cfg((MODELS / f"{run.spec}.cfg").read_text(encoding="utf-8"), run), encoding="utf-8")
    start = time.monotonic()
    liveness = ["-lncheck", "final"] if run.properties else []
    p = subprocess.run([java, "-XX:+UseParallelGC", "-cp", str(jar), "tlc2.TLC", "-workers", "auto", "-cleanup",
                        *liveness, "-metadir", str(work / f"states{index}"), "-config", cfg.name, f"{run.spec}.tla"],
                       cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr, time.monotonic() - start


def report(run, got, text, took):
    detail = f"{run.title}: {got}, {states(text)} states, {took:.1f} s"
    if took > LIMIT_S:
        check(False, f"{detail}: over the {LIMIT_S} s limit")
    elif run.known is not None:
        if got == "pass":
            check(False, f"known failure #{run.known} passes now: {run.title}; make it a regular check and close "
                         f"the issue")
        elif got == run.expect:
            print(f"known failure #{run.known}: {detail}", flush=True)
        else:
            check(False, f"{detail} (expected {run.expect}, the known failure of #{run.known})")
    else:
        check(got == run.expect, f"{detail}" + ("" if got == run.expect else f" (expected {run.expect})"))
    if got != run.expect:
        print("\n".join(text.splitlines()[-80:]), flush=True)


def main():
    java = shutil.which("java")
    check(java is not None, "java is on the PATH")
    if java is None:
        sys.exit(1)
    with tempfile.TemporaryDirectory(prefix="ritmelli-tla-") as tmp:
        tmp = Path(tmp)
        jar = jar_path(tmp)
        if jar is None:
            sys.exit(1)
        work = tmp / "models"
        work.mkdir()
        for f in MODELS.glob("*.tla"):
            shutil.copy(f, work / f.name)
        for i, run in enumerate(RUNS):
            text, took = tlc(java, jar, work, run, i)
            report(run, outcome(text), text, took)
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
