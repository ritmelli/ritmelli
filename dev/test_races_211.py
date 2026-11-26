import contextlib
import importlib.util
import io
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("testa_comandos", ROOT / "dev" / "testa_comandos.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)
cmd, eng, pastas, server = harness.cmd, harness.eng, harness.pastas, harness.server

ISSUE = 211
WAIT_S = 5
failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


def known(fixed, what):
    if fixed:
        check(False, f"known failure #{ISSUE} passes now: {what}; make it a regular check and close the issue")
    else:
        print(f"known failure #{ISSUE}: {what}", flush=True)


class Readers:
    def __init__(self, E):
        self.done = {}
        self.lock = threading.Lock()
        real = E._reader

        def reader(gen, track, start, deck):
            real(gen, track, start, deck)
            self.event(track.get("id")).set()
        E._reader = reader

    def event(self, iid):
        with self.lock:
            return self.done.setdefault(iid, threading.Event())

    def wait(self, iid):
        ok = self.event(iid).wait(WAIT_S)
        self.done.pop(iid, None)
        return ok


class StreamThread:
    def __init__(self, A):
        self.ended = threading.Event()
        real = A._abre_stream

        def opens(*a):
            try:
                real(*a)
            finally:
                self.ended.set()
        A._abre_stream = opens


def play(A, E, readers, iid):
    cmd.tocar(A, iid)
    return readers.wait(iid)


def download_ends_before_the_swap_and_the_stream_is_refused(A, E, readers, job_result, target):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    j = A.new_job("downloading", True, target)
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(A, "download", **job_result):
        A.run_download(j, target)
    check(E.track is not None and E.track["id"] == "d1" and j["status"] != "running",
          f"the download ended while d1 was on the platter, and left it there ({j['status']})")
    stream = StreamThread(A)
    with contextlib.redirect_stderr(io.StringIO()):
        swapped = cmd.play_downloading(A, j, target, {"youtube_id": target, "title": "the downloaded one"})
        check(swapped and stream.ended.wait(WAIT_S), "the swap put the job's record on the platter and its stream was "
                                                      "refused")
    del A._abre_stream
    tr = E.track
    loading = tr is not None and tr.get("job") == j["id"] and not tr.get("path") and E.status() == "buffering"
    return j, loading


def failed_download(A, E, readers):
    j, loading = download_ends_before_the_swap_and_the_stream_is_refused(
        A, E, readers, {"side_effect": RuntimeError("boom")}, "bbbbbbbbbbb")
    known(not loading and E.track is None,
          f"#211.1: a download that failed before the swap and a refused stream leave the platter loading "
          f"({j['status']}, {E.status()})")


def finished_download(A, E, readers):
    j, loading = download_ends_before_the_swap_and_the_stream_is_refused(
        A, E, readers, {"return_value": A.lib.get("d2")}, "ccccccccccc")
    tr = E.track or {}
    known(not loading and tr.get("id") == "d2" and str(tr.get("path", "")).endswith("d2.m4a"),
          f"a download that finished before the swap and a refused stream leave the platter loading "
          f"({j['status']}, {E.status()}, {tr.get('id')})")


def audio_version_during_a_pending_switch(A, E, readers):
    cmd.limpar_fila(A)
    A.lib.update("d3", duration=600.0)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = {"id": "d3", "youtube_id": "aaaaaaaaaaa", "url": None, "title": "similar", "channel": "c",
         "duration": 600.0, "job": None, "qid": "similar1", "auto": True}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    cap = E.captura()
    with contextlib.redirect_stderr(io.StringIO()):
        A._prepara(cap.track, x, (id(cap.track), x["qid"]), cap)
    check(E.pronto_tag == x["qid"] and readers.wait("d3"), "the similar track is prepared on the second deck, read")
    for _ in range(harness.BLOCOS + 5):
        E._mixa(eng.BLOCK)
        if E.virou is not None:
            break
    check(E.virou is not None and E.virou[2] == x["qid"] and E.track["youtube_id"] == "aaaaaaaaaaa",
          "the engine switched to it on its own, and the watcher has not reconciled it yet")
    playing = E.track["youtube_id"]
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with A.fila_lock:
        A.automatico._troca_audio("aaaaaaaaaaa", v)
    closed = cmd.avanca(A, virada=E.virou)
    known(closed is x and closed["youtube_id"] == playing,
          f"#211.2: the audio version rewrote the entry of the pending switch ({closed and closed['youtube_id']} "
          f"in the queue, {playing} on the platter)")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio"
        with mock.patch.object(server, "LIB", audio), mock.patch.object(pastas, "LIB", audio):
            A, E = harness.monta(Path(tmp))
            readers = Readers(E)
            try:
                failed_download(A, E, readers)
                finished_download(A, E, readers)
                audio_version_during_a_pending_switch(A, E, readers)
            finally:
                E.close()
    failures.extend(harness.falhas)
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
