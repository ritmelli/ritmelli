import hashlib
import itertools
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
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "dev" / "tla"
JAR_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar"
JAR_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
LIMIT_S = 60
TIMED_OUT = "TLC was stopped at the time limit"
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
    action: str = None


RENAME = (("WithTheRename", "TRUE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"),
          ("WithTheForget", "FALSE"))
RENAME_SWITCH = RENAME + (("WithTheJobSwitch", "TRUE"), ("DownloadEndsBeforeTheSourcePick", "TRUE"),
                          ("WithTheJobOnThePlatter", "FALSE"))
RENAME_PLAY = (("WithTheRename", "TRUE"), ("WithTheJobOnThePlatter", "FALSE"), ("WithTheMoves", "FALSE"),
               ("WithTheSeek", "FALSE"), ("WithTheForget", "FALSE"))
PART_CONSTANTS = ("DownloadOutcomes", "StreamReaderStartsWith", "QueueLengths")
RENAME_PARTS = (
    ("the download failing", ("error",), ("done", "st_reading"), (1, 2)),
    ("the download putting it on the shelf and the stream with audio", ("shelved",), ("done",), (1, 2)),
    ("the download putting it on the shelf, the stream silent and one entry in the queue", ("shelved",),
     ("st_reading",), (1,)),
    ("the download putting it on the shelf, the stream silent and two entries in the queue", ("shelved",),
     ("st_reading",), (2,)),
)


def tla_set(values):
    return "{" + ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in values) + "}"


def rename_part(title, *choices):
    return Run(f"Races211, the code as it is: the download, the stream and the swap, with the record renamed on the "
               f"shelf, {title}", "Races211",
               constants=RENAME + tuple((n, tla_set(c)) for n, c in zip(PART_CONSTANTS, choices)))


RUNS = (
    Run("Races211, the code as it is: the download, the stream and the swap, with another record played", "Races211",
        constants=(("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("Races211, the code as it is: a swap that finds the record on the shelf publishes its file",
        "Races211", "invariant SwapLeavesTheShelfFileOff", invariants=("SwapLeavesTheShelfFileOff",),
        constants=(("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"), ("WithTheForget", "FALSE")),
        action="SwapPublishesTheFile"),
    Run("Races211, the code as it is: the download, the stream and the swap, with the record leaving the shelf",
        "Races211", constants=(("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"))),
    Run("Races211, the code as it is: the download, the stream and a seek", "Races211",
        constants=(("WithTheMoves", "FALSE"), ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("Races211, the code as it is: the queue moves, the passage and the audio version", "Races211",
        constants=(("WithTheJob", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("Races211, the code as it is: the job with one queue move", "Races211",
        constants=(("TwoMoves", "FALSE"), ("WithThePlay", "FALSE"),
                   ("WithTheForget", "FALSE"), ("WithTheSeek", "FALSE"))),
    *(rename_part(*part) for part in RENAME_PARTS),
    Run("Races211, the code as it is: a passage to the job's shelf file, with the record renamed on the shelf",
        "Races211", constants=RENAME_SWITCH),
    Run("Races211, the code as it is: the job's record played from the shelf, with the record renamed on the shelf",
        "Races211", constants=RENAME_PLAY),
    Run("mutant: the shelf record a play puts on the platter is built before the load takes the _qlock", "Races211",
        "invariant PlatterHasTheCurrentName", invariants=("PlatterHasTheCurrentName",),
        constants=RENAME_PLAY + (("RecordBuiltUnderTheLock", "FALSE"),)),
    Run("known failure #303: a rename on the shelf while a job's stream opens: the stream comes in with the name it "
        "copied before", "Races211", "invariant NameIsCurrentOutsideARename",
        invariants=("NameIsCurrentOutsideARename",), action="StreamOpened",
        constants=RENAME + (("TheJobIsPlayedBeforeItsDownloadEnds", "TRUE"),)),
    Run("known failure #303: a rename on the shelf before a play of a downloading job publishes its record: the record "
        "keeps the request's name", "Races211", "invariant NameIsCurrentOutsideARename",
        invariants=("NameIsCurrentOutsideARename",), action="SwapPublishes", constants=RENAME),
    Run("known failure #303: a rename on the shelf while the passage prepares a job's stream: the stream keeps the "
        "queue entry's name", "Races211", "invariant NameIsCurrentOutsideARename",
        invariants=("NameIsCurrentOutsideARename",), action="MixerSwitches",
        constants=RENAME + (("WithTheJobSwitch", "TRUE"), ("WithTheJobOnThePlatter", "FALSE"))),
    Run("mutant: a rename on the shelf puts a new track dict on the platter", "Races211",
        "invariant FinishedDownloadReachesThePlatter", invariants=("FinishedDownloadReachesThePlatter",),
        constants=RENAME + (("RenameReplacesTheTrack", "TRUE"),)),
    Run("mutant: the download's file is built before the swap takes the _qlock", "Races211",
        "invariant PlatterHasTheCurrentName", invariants=("PlatterHasTheCurrentName",),
        constants=RENAME + (("RecordBuiltUnderTheLock", "FALSE"),)),
    Run("mutant: the passage's shelf file is built before it is published", "Races211",
        "invariant PlatterHasTheCurrentName", invariants=("PlatterHasTheCurrentName",),
        constants=RENAME_SWITCH + (("RecordBuiltUnderTheLock", "FALSE"),)),
    Run("mutant: a rename on the shelf leaves the prepared deck's track with the old name", "Races211",
        "invariant PlatterHasTheCurrentName", invariants=("PlatterHasTheCurrentName",),
        constants=RENAME_SWITCH + (("RenameReachesThePreparedDeck", "FALSE"),)),
    Run("mutant: a refused stream does not look at the job (#211.1)", "Races211", "invariant NoOrphanLoading",
        invariants=("NoOrphanLoading",),
        constants=(("StreamFailureChecksJob", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: a refused stream does not look at the job, which finished", "Races211", "invariant NoStaleLoading",
        invariants=("NoStaleLoading",),
        constants=(("StreamFailureChecksJob", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: the audio version changes the entries outside the change_queue (#211.2)", "Races211",
        "invariant SwitchEntryMatchesPlatter", invariants=("SwitchEntryMatchesPlatter",),
        constants=(("AudioSwapThroughChangeQueue", "FALSE"), ("WithTheJob", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: a refused stream acts on whatever record the platter holds", "Races211",
        "invariant StreamActsOnItsAttempt", invariants=("StreamActsOnItsAttempt",),
        constants=(("StreamChecksItsTrack", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: a refused stream decides the stop before trying the file", "Races211", "invariant NoStaleLoading",
        constants=(("RefusedStreamTriesTheFileFirst", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: a refused stream waits for a finished download whose record left the shelf", "Races211",
        "invariant NoStaleLoading", invariants=("NoStaleLoading",),
        constants=(("RefusedStreamStopsWithoutTheFile", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: the passage publishes a source whose entry changed version while it was read", "Races211",
        "invariant SwitchEntryMatchesPlatter", invariants=("SwitchEntryMatchesPlatter",),
        constants=(("PrepareChecksTheVersion", "FALSE"), ("WithTheJob", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: the audio version rewrites the entry a reservation in flight is playing", "Races211",
        "invariant ReservedEntryMatchesRead", invariants=("ReservedEntryMatchesRead",),
        constants=(("AudioVersionKeepsTheReservation", "FALSE"), ("WithTheJob", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: the file that replaces a stream gets no reader of its own (only the record changes)", "Races211",
        "invariant NoStaleLoading", invariants=("NoStaleLoading",),
        constants=(("FileSwapStartsItsReader", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("Races211, the code as it is with a stream that drops: every property but the one #294 breaks", "Races211",
        invariants=("TypeOK", "LockOrderKept", "NoOrphanLoading", "SwitchEntryMatchesPlatter",
                    "ReservedEntryMatchesRead", "StreamActsOnItsAttempt", "NoRefusalWhilePlaying",
                    "NoPassageFromBeforeTheSeek", "FinishedDownloadReachesThePlatter",
                    "HandoverOnlyOntoTheJobsRecord"),
        constants=(("WithTheDrop", "TRUE"), ("WithTheMoves", "FALSE"),
                   ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("Races211, the code as it is with a switch to a job's stream: every property but the one #294 breaks",
        "Races211",
        invariants=("TypeOK", "LockOrderKept", "NoOrphanLoading", "NoStaleLoading", "SwitchEntryMatchesPlatter",
                    "ReservedEntryMatchesRead", "StreamActsOnItsAttempt", "NoRefusalWhilePlaying",
                    "NoPassageFromBeforeTheSeek", "HandoverOnlyOntoTheJobsRecord"),
        constants=(("WithTheJobSwitch", "TRUE"), ("WithTheMoves", "FALSE"),
                   ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("Races211, the code as it is with a switch to a job's entry already on the shelf (or failed) when the passage "
        "picked its source", "Races211",
        constants=(("WithTheJobSwitch", "TRUE"), ("DownloadEndsBeforeTheSourcePick", "TRUE"), ("WithTheMoves", "FALSE"),
                   ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("mutant: the shelf file a passage switches to keeps the job, and the finished download hands it over again",
        "Races211", "invariant HandoverOnlyOntoTheJobsRecord", invariants=("HandoverOnlyOntoTheJobsRecord",),
        constants=(("PassageFileKeepsTheJob", "TRUE"), ("WithTheJobSwitch", "TRUE"),
                   ("DownloadEndsBeforeTheSourcePick", "TRUE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"),
                   ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("mutant: the passage prepares the stream of a job whose file is already on the shelf", "Races211",
        "invariant FinishedDownloadReachesThePlatter", invariants=("FinishedDownloadReachesThePlatter",),
        constants=(("PrepareLooksAtTheShelf", "FALSE"), ("WithTheJobSwitch", "TRUE"),
                   ("DownloadEndsBeforeTheSourcePick", "TRUE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"),
                   ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("known failure #294: a stream with a download that drops before its end ends the record, and the file that "
        "comes has no reader", "Races211", "invariant NoStaleLoading", invariants=("NoStaleLoading",),
        constants=(("WithTheDrop", "TRUE"), ("WithTheMoves", "FALSE"),
                   ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("known failure #294: a switch to a stream whose download finished while it waited prepared keeps the stream",
        "Races211", "invariant FinishedDownloadReachesThePlatter", invariants=("FinishedDownloadReachesThePlatter",),
        constants=(("WithTheJobSwitch", "TRUE"), ("WithTheMoves", "FALSE"),
                   ("WithTheSeek", "FALSE"), ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("mutant: a stream that gives no audio waits for the file without asking the App", "Races211",
        "invariant NoOrphanLoading", invariants=("NoOrphanLoading",),
        constants=(("SilentStreamGoesToTheApp", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("mutant: the silent stream's hand-over stops or warns after a seek whose reader has audio", "Races211",
        "invariant NoRefusalWhilePlaying", invariants=("NoRefusalWhilePlaying",),
        constants=(("StreamRefusalChecksItsWait", "FALSE"), ("WithTheMoves", "FALSE"),
                   ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("mutant: the file wait is keyed by the record alone, without the reader's gen", "Races211",
        "invariant NoRefusalWhilePlaying", invariants=("NoRefusalWhilePlaying",),
        constants=(("WaitKeyedByGen", "FALSE"), ("WithTheMoves", "FALSE"),
                   ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("mutant: a seek keeps the line and the prepared passage", "Races211", "invariant NoPassageFromBeforeTheSeek",
        invariants=("NoPassageFromBeforeTheSeek",),
        constants=(("SeekStartsANewLine", "FALSE"), ("WithTheMoves", "FALSE"),
                   ("WithThePlay", "FALSE"), ("WithTheForget", "FALSE"))),
    Run("mutant: the stream that opened does not look for the download that finished meanwhile", "Races211",
        "invariant FinishedDownloadReachesThePlatter", invariants=("FinishedDownloadReachesThePlatter",),
        constants=(("OpenedStreamLooksForTheFile", "FALSE"), ("WithTheMoves", "FALSE"), ("WithTheSeek", "FALSE"))),
    Run("LocksAndSwitch, the code as it is", "LocksAndSwitch"),
    Run("LocksAndSwitch, the code as it is: every reservation resolves (weak fairness, no symmetry)",
        "LocksAndSwitch", invariants=(), properties=("ReservationsResolve",), specification="FairSpec",
        symmetry=False, deadlock=False, constants=(("Reopens", "FALSE"),)),
    Run("mutant: overlapping Nexts do not join", "LocksAndSwitch", "invariant OneAdvance",
        constants=(("NextsJoin", "FALSE"),)),
    Run("LocksAndSwitch, the code as it is: every play raises", "LocksAndSwitch",
        constants=(("PlaysCanSucceed", "FALSE"),)),
    Run("mutant: overlapping Nexts do not join, and every play raises (two entries leave the queue)", "LocksAndSwitch",
        "invariant OneRemoval", constants=(("NextsJoin", "FALSE"), ("PlaysCanSucceed", "FALSE"))),
    Run("mutant: a Next that takes its pending switch goes on to reserve and play the next entry", "LocksAndSwitch",
        "invariant OneRemoval", constants=(("TakenSwitchEndsTheAdvance", "FALSE"),)),
    Run("mutant: a Next that finds the pending switch while it reserves takes it and goes on to reserve and play",
        "LocksAndSwitch", "invariant OneRemoval", constants=(("SwitchFoundAtReserveEndsTheAdvance", "FALSE"),)),
    Run("mutant: a Next does not join an advance that already published its line", "LocksAndSwitch",
        "invariant OneAdvance", invariants=("OneAdvance",), constants=(("NextsJoinAfterPublish", "FALSE"),)),
    Run("mutant: closing the switches drops the pending one without reconciling it", "LocksAndSwitch",
        "invariant SwitchClosesOnce", invariants=("SwitchClosesOnce",),
        constants=(("ClosingRecordsTheSwitch", "FALSE"),)),
    Run("mutant: the watcher drops the second switch without reconciling it", "LocksAndSwitch",
        "invariant SwitchClosesOnce", constants=(("ClosesTheSecondSwitch", "FALSE"),)),
    Run("mutant: the Stop does not put its record in the history", "LocksAndSwitch",
        "invariant HistoryOnceInOrder", invariants=("HistoryOnceInOrder",),
        constants=(("StopSavesItsRecord", "FALSE"),)),
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
    Run("mutant: the audio thread takes the _lock", "LocksAndSwitch", "invariant LockOrderKept",
        invariants=("LockOrderKept",), constants=(("MixerTakesOnlyQlock", "FALSE"),)),
    Run("mutant: a Next whose play raised leaves the error out of its group", "LocksAndSwitch",
        "invariant OneAdvance", invariants=("OneAdvance",), constants=(("PlayErrorReachesTheGroup", "FALSE"),)),
    Run("mutant: a Next whose play raised after a Stop resolved its group raises anyway", "LocksAndSwitch",
        "invariant OneAdvance", invariants=("OneAdvance",),
        constants=(("RaisingNextTakesTheResolvedResult", "FALSE"),)),
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
    elif run.expect.startswith("invariant "):
        blocks["INVARIANTS"] = [run.expect.split()[1]]
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
    found = re.findall(r"(\d[\d,]*) distinct states found", text)
    return found[-1].replace(",", "") if found else "?"


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
    try:
        p = subprocess.run([java, "-XX:+UseParallelGC", "-cp", str(jar), "tlc2.TLC", "-workers", "auto", "-cleanup",
                            *liveness, "-metadir", str(work / f"states{index}"), "-config", cfg.name,
                            f"{run.spec}.tla"], cwd=work, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL, timeout=LIMIT_S)
    except subprocess.TimeoutExpired:
        return TIMED_OUT, time.monotonic() - start
    return p.stdout + p.stderr, time.monotonic() - start


def report(run, got, text, took):
    expect = run.expect
    if run.action:
        steps = re.findall(r"State \d+: <(\w+) ", text)
        got, expect = f"{got} by {steps[-1] if steps else '?'}", f"{expect} by {run.action}"
    detail = f"{run.title}: {got}, {states(text)} states, {took:.1f} s"
    if took > LIMIT_S or text == TIMED_OUT:
        check(False, f"{detail}: over the {LIMIT_S} s limit")
    else:
        check(got == expect, detail + ("" if got == expect else f" (expected {expect})"))
    if got != expect:
        print("\n".join(text.splitlines()[-80:]), flush=True)


def cfg_choices(cfg_text):
    constants = dict(c.split(" = ", 1) for c in parse_cfg(cfg_text).get("CONSTANTS", []))
    return [{text or int(number) for text, number in re.findall(r'"([^"]*)"|(\d+)', constants.get(name, ""))}
            for name in PART_CONSTANTS]


def rename_part_failures(parts, cfg_text):
    whole = set(itertools.product(*cfg_choices(cfg_text)))
    covered = [c for _, *choices in parts for c in itertools.product(*choices)]
    out = [f"the rename parts leave out {sorted(whole - set(covered), key=str)}"] if whole - set(covered) else []
    out += [f"the rename parts choose {sorted(set(covered) - whole, key=str)}, which the cfg does not"
            ] if set(covered) - whole else []
    out += ["the rename parts overlap"] if len(covered) != len(set(covered)) else []
    return out


def main():
    cfg = (MODELS / "Races211.cfg").read_text(encoding="utf-8")
    found = rename_part_failures(RENAME_PARTS, cfg)
    check(found == [], f"the {len(RENAME_PARTS)} rename runs together are the whole configuration of the cfg, each "
                       f"choice once ({found})")
    check(rename_part_failures(RENAME_PARTS[:-1], cfg) != [], "the mutant without the last rename part fails")
    wider = cfg.replace('StreamReaderStartsWith = {"done", "st_reading"}',
                        'StreamReaderStartsWith = {"done", "st_reading", "sr_dropped"}')
    check(wider != cfg and rename_part_failures(RENAME_PARTS, wider) != [],
          "the mutant whose cfg gains a choice the rename parts do not run fails")
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
        limits = []

        def stuck(*a, **kw):
            limits.append(kw.get("timeout"))
            raise subprocess.TimeoutExpired(a[0], kw.get("timeout"))
        with mock.patch.object(subprocess, "run", stuck):
            text, _ = tlc(java, jar, work, RUNS[0], "stuck")
        check(limits == [LIMIT_S] and text == TIMED_OUT,
              f"a TLC run is stopped at the {LIMIT_S} s limit and reported as over it ({limits})")
        for i, run in enumerate(RUNS):
            text, took = tlc(java, jar, work, run, i)
            report(run, outcome(text), text, took)
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
