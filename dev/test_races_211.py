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
music = importlib.import_module("music")

WAIT_S = 5
failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg, flush=True)
    if not ok:
        failures.append(msg)


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
    check(not loading and E.track is None,
          f"a download that failed before the swap and a refused stream stop the platter ({j['status']}, "
          f"{E.status()})")


def finished_download(A, E, readers):
    j, loading = download_ends_before_the_swap_and_the_stream_is_refused(
        A, E, readers, {"return_value": A.lib.get("d2")}, "ccccccccccc")
    tr = E.track or {}
    check(not loading and tr.get("id") == "d2" and str(tr.get("path", "")).endswith("d2.m4a"),
          f"a download that finished before the swap and a refused stream play the downloaded file "
          f"({j['status']}, {E.status()}, {tr.get('id')})")


def finished_download_that_left_the_shelf(A, E, readers):
    gone = {"id": "gone", "title": "gone", "file": "gone.m4a", "duration": 120.0, "youtube_id": None,
            "lufs": -14.0, "last_pos": 0}
    j, loading = download_ends_before_the_swap_and_the_stream_is_refused(
        A, E, readers, {"return_value": gone}, "ddddddddddd")
    check(not loading and E.track is None and A.lib.get("gone") is None,
          f"a download that finished, whose record is no longer on the shelf, and a refused stream stop the platter "
          f"({j['status']}, {E.status()})")


def finished_download_forgotten_during_the_refusal(A, E, readers):
    item = A.lib.get("d2")
    real_get = A.lib.get
    removed = []

    def get_then_forget(iid):
        it = real_get(iid)
        if iid == "d2" and it is not None:
            A.lib.items.remove(it)
            removed.append(iid)
        return it
    try:
        with mock.patch.object(A.lib, "get", side_effect=get_then_forget):
            j, loading = download_ends_before_the_swap_and_the_stream_is_refused(
                A, E, readers, {"return_value": item}, "fffffffffff")
    finally:
        if real_get("d2") is None:
            A.lib.items.append(item)
    tr = E.track or {}
    check(removed == ["d2"] and not loading and tr.get("id") == "d2" and str(tr.get("path", "")).endswith("d2.m4a"),
          f"a finished download whose record leaves the shelf right after the refusal reads it plays the file it read "
          f"({removed}, {j['status']}, {E.status()}, {tr.get('id')})")


class SilentFfmpeg:
    returncode = None

    def __init__(self, reading, go):
        self.reading, self.go, self.stdout = reading, go, self

    def read(self, n):
        self.reading.set()
        self.go.wait(WAIT_S)
        return b""

    def kill(self):
        self.returncode = 1

    def wait(self):
        return self.returncode


def silent_stream_after_the_download_failed(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "ccccccccccc"
    j = A.new_job("downloading", True, target)
    reading, go, read = threading.Event(), threading.Event(), threading.Event()
    fake = E._reader

    def reader(gen, track, start, deck):
        if not str(track.get("path") or "").startswith("http"):
            return fake(gen, track, start, deck)
        try:
            eng.Engine._reader(E, gen, track, start, deck)
        finally:
            read.set()
    meta = {"youtube_id": target, "title": "the silent one", "channel": "c", "duration": 200.0}
    info = dict(meta, url="https://stream.invalid/audio", id=target)
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(info, {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: SilentFfmpeg(reading, go))):
        swapped = cmd.play_downloading(A, j, target, meta)
        check(swapped and stream.ended.wait(WAIT_S) and reading.wait(WAIT_S),
              "the swap put the job's record on the platter, its stream opened and the reader reads it")
        with mock.patch.object(A, "download", side_effect=RuntimeError("boom")):
            A.run_download(j, target)
        check(j["status"] == "error" and E.track is not None and E.track.get("job") == j["id"],
              "the download failed while the reader still read the stream, and left the platter to it")
        go.set()
        read.wait(WAIT_S)
    del A._abre_stream
    check(E.track is None, f"a stream that gives no audio after its download failed stops the platter ({E.track})")


class AudioFfmpeg(SilentFfmpeg):
    def __init__(self, blocks):
        super().__init__(threading.Event(), threading.Event())
        self.blocks = [bytes(eng.BLOCK * 8)] * blocks

    def read(self, n):
        return self.blocks.pop() if self.blocks else b""


def real_stream_reader(E, fake):
    ended = []

    def reader(gen, track, start, deck):
        if not str(track.get("path") or "").startswith("http"):
            return fake(gen, track, start, deck)
        done = threading.Event()
        ended.append(done)
        try:
            eng.Engine._reader(E, gen, track, start, deck)
        finally:
            done.set()
    return reader, ended


def silent_stream_then_a_seek(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "eeeeeeeeeee"
    j = A.new_job("downloading", True, target)
    reading, go, held, release = threading.Event(), threading.Event(), threading.Event(), threading.Event()
    reader, ended = real_stream_reader(E, E._reader)
    refused = A._stream_refused

    def holds(*a, **kw):
        held.set()
        release.wait(WAIT_S)
        return refused(*a, **kw)
    meta = {"youtube_id": target, "title": "the seeked one", "channel": "c", "duration": 200.0}
    fakes = iter([SilentFfmpeg(reading, go), AudioFfmpeg(2)])
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/b", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: next(fakes)),
          mock.patch.object(A, "_stream_refused", holds)):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and reading.wait(WAIT_S),
              "the stream of the seeked one opened and its reader reads it")
        with mock.patch.object(A, "download", side_effect=RuntimeError("boom")):
            A.run_download(j, target)
        go.set()
        check(held.wait(WAIT_S), "the silent reader marked the file wait and handed the record to the App")
        E.seek(0.5)
        check(len(ended) == 2 and ended[1].wait(WAIT_S), "the seek started a new reader, which read the stream's audio")
        release.set()
        ended[0].wait(WAIT_S)
    del A._abre_stream
    tr = E.track
    check(tr is not None and tr.get("job") == j["id"],
          f"the silent reader's hand-over, late after a seek whose reader has audio, leaves the platter to it ({tr})")


def file_near_the_end_of_a_silent_stream(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "fffffffffff"
    j = A.new_job("downloading", True, target)
    reader, ended = real_stream_reader(E, E._reader)
    meta = {"youtube_id": target, "title": "the short one", "channel": "c", "duration": 1.5}
    item = {"id": "short1", "title": "the short one", "file": "short1.m4a", "duration": 1.5, "lufs": -14.0}
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/c", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: AudioFfmpeg(0))):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and len(ended) == 1
              and ended[0].wait(WAIT_S), "the short one's stream opened and gave no audio")
        reason = (E.error or {}).get("params", {}).get("reason")
        check(isinstance(reason, dict) and reason.get("key") == "server.player.noAudio",
              f"while it still downloads, the warning gives the reason as a message for the screen ({E.error})")
        with mock.patch.object(A, "download", return_value=item):
            A.run_download(j, target)
    del A._abre_stream
    check(readers.wait("short1"), "the file that arrives near the end of a silent stream gets a reader of its own")


def warning_after_another_record_took_the_platter(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "ggggggggggg"
    j = A.new_job("downloading", True, target)
    real_msg = server.i18n.msg
    built = []

    def msg_then_play(key, *a, **kw):
        m = real_msg(key, *a, **kw)
        if key == "server.player.streamRefused":
            built.append(m)
            cmd.tocar(A, "d2")
        return m
    stream = StreamThread(A)
    try:
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(server.i18n, "msg", msg_then_play):
            cmd.play_downloading(A, j, target, {"youtube_id": target, "title": "still downloading"})
            check(stream.ended.wait(WAIT_S) and readers.wait("d2"),
                  "the stream of the running job was refused, and d2 took the platter while the warning was built")
    finally:
        del A._abre_stream
        A.job_update(j, status="error")
    check(len(built) == 1 and E.track is not None and E.track["id"] == "d2" and E.error is not built[0],
          f"the warning of the refused stream does not land on the record that replaced it ({E.error})")


def refused_stream_after_another_record(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "eeeeeeeeeee"
    j = A.new_job("downloading", True, target)
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(A, "download", side_effect=RuntimeError("x")):
        A.run_download(j, target)
    entered, go = threading.Event(), threading.Event()
    real = A._stream_refused

    def paused(tr, reason):
        entered.set()
        go.wait(WAIT_S)
        real(tr, reason)
    A._stream_refused = paused
    stream = StreamThread(A)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            cmd.play_downloading(A, j, target, {"youtube_id": target, "title": "the failed one"})
            check(entered.wait(WAIT_S), "the stream was refused while the job's record was on the platter")
            check(play(A, E, readers, "d2"), "and d2 took the platter before the refusal acted")
            go.set()
            check(stream.ended.wait(WAIT_S), "the refusal ended")
    finally:
        go.set()
        del A._abre_stream
        del A._stream_refused
    check(E.track is not None and E.track["id"] == "d2" and E.status() == "playing",
          f"the refused stream of the failed job leaves the record that replaced it playing ({E.status()})")


def prepared_similar(A, E, readers, qid):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = {"id": "d3", "youtube_id": "aaaaaaaaaaa", "url": None, "title": "similar", "channel": "c",
         "duration": 600.0, "job": None, "qid": qid, "auto": True}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    cap = E.captura()
    with contextlib.redirect_stderr(io.StringIO()):
        A._prepara(cap.track, x, dict(x), (id(cap.track), x["qid"]), cap)
    check(E.pronto_tag == x["qid"] and readers.wait("d3"), "the similar track is prepared on the second deck, read")
    return x


def mix_until_the_switch(E):
    for _ in range(harness.BLOCOS + 5):
        E._mixa(eng.BLOCK)
        if E.virou is not None:
            return True
    return False


def audio_version_during_a_pending_switch(A, E, readers):
    x = prepared_similar(A, E, readers, "similar1")
    mix_until_the_switch(E)
    check(E.virou is not None and E.virou[2] == x["qid"] and E.track["youtube_id"] == "aaaaaaaaaaa",
          "the engine switched to it on its own, and the watcher has not reconciled it yet")
    playing = E.track["youtube_id"]
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with A.fila_lock:
        A.automatico._troca_audio("aaaaaaaaaaa", v)
    closed = cmd.avanca(A, virada=E.virou)
    check(closed is x and closed["youtube_id"] == playing,
          f"the audio version leaves the entry of the pending switch as the platter plays it "
          f"({closed and closed['youtube_id']} in the queue, {playing} on the platter)")


def audio_version_while_the_engine_switches(A, E, readers):
    x = prepared_similar(A, E, readers, "similar2")
    real = A.automatico.head_held
    inside = []

    def presa():
        inside.append(E._qlock.locked())
        if not inside[-1]:
            mix_until_the_switch(E)
        return real()
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with A.fila_lock, mock.patch.object(A.automatico, "head_held", presa):
        A.automatico._troca_audio("aaaaaaaaaaa", v)
    check(inside == [True], f"the audio version reads the pending switch and the held head in one stretch of the "
                            f"_qlock, where the engine cannot switch ({inside})")
    check(E.virou is not None or mix_until_the_switch(E), "the engine switched to the similar track")
    playing = E.track["youtube_id"]
    closed = cmd.avanca(A, virada=E.virou)
    check(closed is x and closed["youtube_id"] == playing,
          f"a switch that comes during the audio version leaves its entry as the platter plays it "
          f"({closed and closed['youtube_id']} in the queue, {playing} on the platter)")


def audio_version_while_the_passage_reads_the_source(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = {"id": "d3", "youtube_id": "aaaaaaaaaaa", "url": None, "title": "similar", "channel": "c",
         "duration": 600.0, "job": None, "qid": "similar4", "auto": True}
    y = dict(x, id="d2", youtube_id="bbbbbbbbbbb", qid="other4")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([x, y]))
    read, go, source = threading.Event(), threading.Event(), A.fonte_de

    def reads(entry):
        found = source(entry)
        read.set()
        go.wait(WAIT_S)
        return found
    cap = E.captura()
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with mock.patch.object(A, "fonte_de", reads), contextlib.redirect_stderr(io.StringIO()):
        t = threading.Thread(target=A._prepara, args=(cap.track, x, dict(x), (id(cap.track), x["qid"]), cap))
        t.start()
        read.wait(WAIT_S)
        cmd.mover_na_fila(A, y["qid"], 0)
        with A.fila_lock:
            A.automatico._troca_audio("aaaaaaaaaaa", v)
        cmd.mover_na_fila(A, y["qid"], 1)
        go.set()
        t.join(WAIT_S)
    check(A.fila[0] is x and x["youtube_id"] == "fffffffffff" and "fixa" not in x and E.pronto_tag is None,
          f"an entry that left the head, took the audio version and came back while the passage read its source is "
          f"not prepared with the source of before ({x['youtube_id']} in the queue, prepared {E.pronto_tag})")


def audio_version_entries(A, E):
    cmd.limpar_fila(A)
    entry = {"id": None, "url": None, "title": "similar", "channel": "c", "duration": 300.0, "job": None,
             "youtube_id": "ggggggggggg", "auto": True}
    head, tail = dict(entry, qid="head1"), dict(entry, qid="tail1")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([head, tail]))
    mixed = {"youtube_id": "ggggggggggg", "title": "mixed", "ordem": 1}
    plain = {"youtube_id": "hhhhhhhhhhh", "title": "plain", "ordem": 2}
    mix0, A.mix = A.mix, [mixed, plain, head]
    v = {"youtube_id": "iiiiiiiiiii", "duration": 200, "title": "the audio", "channel": "c"}
    audio = {"youtube_id": "iiiiiiiiiii", "duration": 200, "title": "the audio", "channel": "c", "audio": True,
             "video": "ggggggggggg", "thumb": music.thumb("iiiiiiiiiii"), "tipo": "ATV"}
    try:
        with A.fila_lock, mock.patch.object(A.automatico, "head_held", return_value=True):
            A.apply_audio_version("ggggggggggg", v)
        check(head == dict(entry, qid="head1"), f"the held head keeps its version ({head})")
        check(tail == dict(entry, qid="tail1", **audio), f"the entry after it takes the audio version ({tail})")
        check(mixed == {"ordem": 1, **audio}, f"the Mix entry takes the audio version ({mixed})")
        with A.fila_lock, mock.patch.object(A.automatico, "head_held", return_value=False):
            A.apply_audio_version("hhhhhhhhhhh", None)
        check(plain == {"youtube_id": "hhhhhhhhhhh", "title": "plain", "ordem": 2, "audio": True},
              f"with no audio version, the Mix entry only gets the mark that it was looked up ({plain})")
        reserved = dict(entry, qid="reserved1", youtube_id="jjjjjjjjjjj")
        with A.fila_lock:
            A.change_queue(lambda: A.fila.append(reserved))
            with E.state_section():
                A.reserva = cmd.Reserva(*E.line(), reserved)
        with A.fila_lock, mock.patch.object(A.automatico, "head_held", return_value=False):
            A.apply_audio_version("jjjjjjjjjjj", v)
        check(reserved == dict(entry, qid="reserved1", youtube_id="jjjjjjjjjjj"),
              f"the entry a reservation in flight is playing, away from the head, keeps its version ({reserved})")
    finally:
        A.reserva = None
        A.mix = mix0
        cmd.limpar_fila(A)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio"
        with mock.patch.object(server, "LIB", audio), mock.patch.object(pastas, "LIB", audio):
            A, E = harness.monta(Path(tmp))
            readers = Readers(E)
            A.lib.update("d3", duration=600.0)
            try:
                failed_download(A, E, readers)
                finished_download(A, E, readers)
                finished_download_that_left_the_shelf(A, E, readers)
                finished_download_forgotten_during_the_refusal(A, E, readers)
                refused_stream_after_another_record(A, E, readers)
                silent_stream_after_the_download_failed(A, E, readers)
                silent_stream_then_a_seek(A, E, readers)
                file_near_the_end_of_a_silent_stream(A, E, readers)
                warning_after_another_record_took_the_platter(A, E, readers)
                audio_version_during_a_pending_switch(A, E, readers)
                audio_version_while_the_engine_switches(A, E, readers)
                audio_version_while_the_passage_reads_the_source(A, E, readers)
                audio_version_entries(A, E)
            finally:
                E.close()
    failures.extend(harness.falhas)
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
