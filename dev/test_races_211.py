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


class Started:
    def __init__(self):
        self.events, self.cond = [], threading.Condition()

    def __len__(self):
        with self.cond:
            return len(self.events)

    def add(self):
        done = threading.Event()
        with self.cond:
            self.events.append(done)
            self.cond.notify_all()
        return done

    def started(self, n):
        with self.cond:
            return self.cond.wait_for(lambda: len(self.events) >= n, WAIT_S)

    def nth(self, i):
        return self.events[i] if self.started(i + 1) else threading.Event()


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


def renamed_after_the_first_build(A, iid, title, build):
    first = [True]

    def built():
        record = build()
        if first[0]:
            first[0] = False
            cmd.update_record(A, iid, title=title)
        return record
    return built


def shown_title(A):
    return (A.leitura()[0].get("track") or {}).get("title")


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


def finished_download_put_back_before_the_stop(A, E, readers):
    back = {"id": "back", "title": "back", "file": "back.m4a", "duration": 120.0, "youtube_id": None, "lufs": -14.0,
            "last_pos": 0}
    stop, landed = E.stop, []

    def second_download_lands_first(*a, **kw):
        if kw.get("pode") is not None and A.lib.get("back") is None and (E.track or {}).get("job"):
            A.lib.add(dict(back))
            landed.append(True)
        return stop(*a, **kw)
    with mock.patch.object(E, "stop", second_download_lands_first):
        j, loading = download_ends_before_the_swap_and_the_stream_is_refused(
            A, E, readers, {"return_value": back}, "hhhhhhhhhhh")
    tr = E.track or {}
    A.lib.remove("back")
    check(landed == [True] and not loading and tr.get("id") == "back" and str(tr.get("path", "")).endswith("back.m4a"),
          f"a finished download whose record left the shelf, put back by a second download right before the refused "
          f"stream's stop, plays the file instead of loading forever ({landed}, {j['status']}, {E.status()}, "
          f"{tr.get('id')})")


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
    returncode, waited_alive = None, False

    def __init__(self, reading, go):
        self.reading, self.go, self.stdout = reading, go, self

    def read(self, n):
        self.reading.set()
        self.go.wait(WAIT_S)
        return b""

    def kill(self):
        self.returncode = 1

    def wait(self):
        if self.returncode is None:
            self.returncode, self.waited_alive = 0, True
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
    stream, made = StreamThread(A), []
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(info, {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: made.append(SilentFfmpeg(reading, go)) or made[-1])):
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
    check(made and not any(f.waited_alive for f in made),
          "the reader of a stream that ends with no audio kills its ffmpeg before it waits for it")


class AudioFfmpeg(SilentFfmpeg):
    def __init__(self, blocks):
        super().__init__(threading.Event(), threading.Event())
        self.blocks = [bytes(eng.BLOCK * 8)] * blocks

    def read(self, n):
        return self.blocks.pop() if self.blocks else b""


class HeldAudioFfmpeg(SilentFfmpeg):
    def __init__(self, go, reading=None):
        super().__init__(reading or threading.Event(), go)
        self.blocks = [bytes(eng.BLOCK * 8)] * 2

    def read(self, n):
        if self.blocks:
            return self.blocks.pop()
        return super().read(n)


def stream_opens_after_the_download_read_the_platter(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "ooooooooooo"
    j = A.new_job("downloading", True, target)
    captured, go, done = threading.Event(), threading.Event(), threading.Event()
    reader, ended = real_stream_reader(E, E._reader)
    swap = E.trocar_fonte

    def holds(atual, novo):
        if not atual.get("path") and callable(novo):
            captured.set()
            go.wait(WAIT_S)
        return swap(atual, novo)
    meta = {"youtube_id": target, "title": "the opened one", "channel": "c", "duration": 200.0}
    info = dict(meta, url="https://stream.invalid/o", id=target)

    def downloads():
        try:
            A.run_download(j, target)
        finally:
            done.set()
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(E, "trocar_fonte", holds), mock.patch.object(A, "download", return_value=A.lib.get("d2")),
          mock.patch.object(A, "stream_info", side_effect=lambda *a, **kw: (captured.wait(WAIT_S), (info, {}))[1]),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: HeldAudioFfmpeg(go))):
        check(cmd.play_downloading(A, j, target, meta), "the swap put the job's record on the platter")
        threading.Thread(target=downloads, daemon=True).start()
        check(captured.wait(WAIT_S) and stream.ended.wait(WAIT_S),
              "the download finished and read the waiting record, and then the stream opened, with audio")
        go.set()
        check(done.wait(WAIT_S) and ended.nth(0).wait(WAIT_S), "the download's swap and the stream's reader ended")
    del A._abre_stream
    tr = E.track or {}
    check(tr.get("id") == "d2" and str(tr.get("path", "")).endswith("d2.m4a") and readers.wait("d2"),
          f"a download that finished while the stream was opening still puts its file on the platter "
          f"({tr.get('id')}, {tr.get('path')})")


def file_after_a_refused_stream(A, E, readers, device_warning=None):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "ppppppppppp"
    j = A.new_job("downloading", True, target)
    stream = StreamThread(A)
    with contextlib.redirect_stderr(io.StringIO()):
        swapped = cmd.play_downloading(A, j, target, {"youtube_id": target, "title": "the refused one"})
        check(swapped and stream.ended.wait(WAIT_S), "the swap put the job's record on the platter and its stream was "
                                                      "refused")
    del A._abre_stream
    check((E.error or {}).get("key") == "server.player.streamRefused" and not (E.track or {}).get("path"),
          f"the record waits for its download with the stream's warning ({E.error})")
    if device_warning is not None:
        E.set_error(device_warning)
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(A, "download", return_value=A.lib.get("d2")):
        A.run_download(j, target)
    check(readers.wait("d2") and E.error is device_warning,
          f"the file that replaces the waiting record takes the stream's warning away and leaves "
          f"{'the device warning that came after it' if device_warning else 'none'} ({E.error})")


def file_after_the_record_was_renamed_on_the_shelf(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "rrrrrrrrrrr"
    j = A.new_job("downloading", True, target)
    stream = StreamThread(A)
    with contextlib.redirect_stderr(io.StringIO()):
        swapped = cmd.play_downloading(A, j, target, {"youtube_id": target, "title": "the renamed one"})
        check(swapped and stream.ended.wait(WAIT_S), "the job's record is on the platter and its stream was refused")
    del A._abre_stream
    waiting = E.track
    item = dict(A.lib.get("d2"), id=waiting["id"], youtube_id=target, title="the renamed one")
    swap = E.trocar_fonte

    def renamed_first(atual, novo):
        return swap(atual, renamed_after_the_first_build(A, item["id"], "a new name", novo))
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "trocar_fonte", renamed_first),
          mock.patch.object(A, "download", side_effect=lambda *a: A.lib.add(item) or item)):
        A.run_download(j, target)
    tr = E.track or {}
    check(readers.wait(item["id"]) and str(tr.get("path", "")).endswith("d2.m4a") and tr.get("title") == "a new name",
          f"a rename on the shelf between the download reading the platter and its swap still puts the file on the "
          f"platter, with the new name ({tr.get('title')}, {tr.get('path')})")
    cmd.update_record(A, item["id"], title="the last name")
    check(E.track is tr and tr.get("title") == "the last name",
          f"a rename with the file on the platter renames the platter's own track ({(E.track or {}).get('title')})")


def file_near_the_end_of_a_stream_with_audio(A, E, readers, repeat=False):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "qqqqqqqqq22" if repeat else "qqqqqqqqqqq"
    j = A.new_job("downloading", True, target)
    reading, go = threading.Event(), threading.Event()
    opened, done = [], Started()

    def reader(gen, track, start, deck):
        finished = done.add()
        try:
            eng.Engine._reader(E, gen, track, start, deck)
        finally:
            finished.set()

    def popen(args, **kw):
        if "-i" not in args or "-ss" not in args:
            return AudioFfmpeg(0)
        path, at = str(args[args.index("-i") + 1]), float(args[args.index("-ss") + 1])
        opened.append((Path(path).name if not path.startswith("http") else "stream", at > 0))
        if path.startswith("http"):
            return HeldAudioFfmpeg(go, reading)
        if len(opened) == 3:
            E.set_loop(False)
        return AudioFfmpeg(0 if at > 0 else 2)
    meta = {"youtube_id": target, "title": "the short one", "channel": "c", "duration": 1.0}
    stream, waiting = StreamThread(A), []

    def info(*a, **kw):
        waiting.append(E.captura().play)
        return dict(meta, url="https://stream.invalid/q", id=target), {}
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", side_effect=info), mock.patch.object(eng.subprocess, "Popen", popen)):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and reading.wait(WAIT_S),
              "the short one's stream opened and its reader queued its audio, up to the end, without the end yet")
        if repeat:
            E.set_loop(True)
        with mock.patch.object(A, "download", return_value=dict(A.lib.get("d2"), duration=1.0)):
            A.run_download(j, target)
        check(done.nth(1).wait(WAIT_S), "the file's reader ended")
        go.set()
        done.nth(0).wait(WAIT_S)
    del A._abre_stream
    tr, d = E.track or {}, E._deck
    want = [("stream", False), ("d2.m4a", True)] + ([("d2.m4a", False)] if repeat else [])
    same = waiting == [E.captura().play]
    check(str(tr.get("path", "")).endswith("d2.m4a") and opened == want and E.error is None and d.eof_gen == d.gen
          and same,
          f"the file that comes when the stream's audio already reaches the end gets its own reader, whose empty read at "
          f"the file's end is the end of the record{', and the Repeat plays the file again' if repeat else ''}, with no "
          f"warning, all in the play the waiting record began ({opened}, {E.error}, plays {waiting} and "
          f"{E.captura().play})")


class FailedFfmpeg(AudioFfmpeg):
    def __init__(self):
        super().__init__(0)

    def wait(self):
        if self.returncode is None:
            self.returncode = 1
        return self.returncode


def failed_read_after_a_seek_near_the_end(A, E, readers):
    check(play(A, E, readers, "d2"), "d2 is on the platter, read")
    done, dur = threading.Event(), float((E.track or {}).get("duration") or 0)

    def reader(gen, track, start, deck):
        try:
            eng.Engine._reader(E, gen, track, start, deck)
        finally:
            done.set()
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: FailedFfmpeg())):
        check(dur > eng.FILE_TAIL_S and E.seek(dur - 1.0) and done.wait(WAIT_S),
              f"a seek into the last second of d2 ({dur} s) started a reader, whose ffmpeg failed without a frame")
    check((E.error or {}).get("key") == "server.player.readFailedAt",
          f"a file that fails to decode near its end shows the read error, not the end of the record ({E.error})")


def real_stream_reader(E, fake):
    ended = Started()

    def reader(gen, track, start, deck):
        if not str(track.get("path") or "").startswith("http"):
            return fake(gen, track, start, deck)
        done = ended.add()
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
    playing, stops = threading.Event(), threading.Event()
    reader, ended = real_stream_reader(E, E._reader)
    refused = A._stream_refused

    def holds(*a, **kw):
        held.set()
        release.wait(WAIT_S)
        return refused(*a, **kw)
    meta = {"youtube_id": target, "title": "the seeked one", "channel": "c", "duration": 200.0}
    fakes = iter([SilentFfmpeg(reading, go), HeldAudioFfmpeg(stops, playing)])
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
        check(ended.started(2) and playing.wait(WAIT_S) and len(ended) == 2, "the seek started a new reader, which reads the stream's audio")
        release.set()
        ended.nth(0).wait(WAIT_S)
    del A._abre_stream
    tr = E.track
    check(tr is not None and tr.get("job") == j["id"] and E.error is None,
          f"the silent reader's hand-over, late after a seek whose reader has audio, leaves the platter to it, without "
          f"a warning ({tr}, {E.error})")
    stops.set()
    ended.nth(1).wait(WAIT_S)


def audio_version_while_an_entry_plays_from_the_queue(A):
    cmd.limpar_fila(A)
    entry = {"id": None, "url": None, "title": "similar", "channel": "c", "duration": 300.0, "job": None,
             "youtube_id": "lllllllllll", "auto": True}
    head, x = dict(entry, qid="head5", youtube_id="mmmmmmmmmmm"), dict(entry, qid="play5")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([head, x]))
    v = {"youtube_id": "nnnnnnnnnnn", "duration": 200, "title": "the audio", "channel": "c"}
    seen = []

    def remote(j, alvo, meta, **kw):
        with A.fila_lock:
            A.automatico._troca_audio("lllllllllll", v)
        seen.append((alvo, meta.get("youtube_id"), meta.get("title")))
        return False
    with mock.patch.object(A, "tocar_remoto", remote):
        cmd.tocar_da_fila(A, x["qid"])
    check(x["youtube_id"] == "nnnnnnnnnnn" and seen == [("lllllllllll", "lllllllllll", "similar")],
          f"an entry played from the queue while the audio version swaps it plays the record it was clicked as, "
          f"its target and its details from one read ({seen}, the queue's entry now {x['youtube_id']})")


def file_wait_after_a_passage_switch(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "kkkkkkkkkkk"
    j = A.new_job("downloading", True, target)
    reading, go = threading.Event(), threading.Event()
    reader, ended = real_stream_reader(E, E._reader)
    refused, marked = A._stream_refused, []

    def marks(*a, **kw):
        marked.append(E._gen)
        return refused(*a, **kw)
    meta = {"youtube_id": target, "title": "the waiting one", "channel": "c", "duration": 200.0}
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/k", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: SilentFfmpeg(reading, go)),
          mock.patch.object(A, "_stream_refused", marks)):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and reading.wait(WAIT_S),
              "the stream of the waiting one opened and its reader reads it")
        go.set()
        check(ended.nth(0).wait(WAIT_S) and len(ended) == 1 and len(marked) == 1 and E.esperando_arquivo(),
              f"the stream gave no audio while its download runs, and the platter waits for the file ({marked})")
    del A._abre_stream
    prepared_similar(A, E, readers, "wait1")
    warned = E.warn_on(E.track, "the outgoing stream's warning")
    check(E.virou is not None or mix_until_the_switch(E), "the engine switched to the similar track, on the other deck")
    check(warned and E.error is None,
          f"the switch to the prepared deck takes the outgoing stream's warning off (put up: {warned}, now {E.error})")
    while E._gen < marked[0]:
        E.seek(1.0)
    check(E._gen == marked[0] and not E.esperando_arquivo(),
          f"the deck that took the platter, at the gen the stream waited on, does not wait for that file "
          f"(gen {E._gen}, the wait at {marked[0]})")


def file_near_the_end_of_a_silent_stream(A, E, readers, device_warning=None, before=False):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    case = "1" if device_warning is None else "4" if before else "3"
    target = "fffffffff" + case * 2
    j = A.new_job("downloading", True, target)
    reader, ended = real_stream_reader(E, E._reader)
    reading, go = threading.Event(), threading.Event()
    meta = {"youtube_id": target, "title": "the short one", "channel": "c", "duration": 1.5}
    iid = "short" + case
    item = {"id": iid, "title": "the short one", "file": f"{iid}.m4a", "duration": 1.5, "lufs": -14.0}
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/c", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: SilentFfmpeg(reading, go))):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and reading.wait(WAIT_S),
              "the short one's stream opened and its reader reads it")
        if before:
            E.set_error(device_warning)
        go.set()
        check(ended.nth(0).wait(WAIT_S) and len(ended) == 1, "the short one's stream gave no audio")
        if before:
            check(E.error is device_warning, f"a device warning that came first stays over the stream's ({E.error})")
        else:
            reason = (E.error or {}).get("params", {}).get("reason")
            check(isinstance(reason, dict) and reason.get("key") == "server.player.noAudio",
                  f"while it still downloads, the warning gives the reason as a message for the screen ({E.error})")
        if device_warning is not None and not before:
            E.set_error(device_warning)
        with mock.patch.object(A, "download", return_value=item):
            A.run_download(j, target)
    del A._abre_stream
    check(readers.wait(iid), "the file that arrives near the end of a silent stream gets a reader of its own")
    if device_warning is None:
        check(E.error is None, f"and the warning that it would play once the download finished leaves ({E.error})")
    else:
        check(E.error is device_warning, f"and a device warning that came {'before' if before else 'after'} the "
                                         f"stream's stays ({E.error})")


def file_after_a_stream_that_dropped(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "rrrrrrrrrrr"
    j = A.new_job("downloading", True, target)
    reader, ended = real_stream_reader(E, E._reader)
    meta = {"youtube_id": target, "title": "the dropped one", "channel": "c", "duration": 200.0}
    item = {"id": "dropped1", "title": "the dropped one", "file": "dropped1.m4a", "duration": 200.0, "lufs": -14.0}
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/r", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: AudioFfmpeg(2))):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and ended.nth(0).wait(WAIT_S)
              and len(ended) == 1, "the dropped one's stream opened, gave some audio and stopped long before its end")
        check(not E.esperando_arquivo() and E._deck.eof_gen == E._deck.gen,
              "known failure #294: the stream that dropped marks the end of the record instead of waiting for the file")
        with mock.patch.object(A, "download", return_value=item):
            A.run_download(j, target)
    del A._abre_stream
    tr, d = E.track or {}, E._deck
    check(tr.get("id") == "dropped1" and d.eof_gen == d.gen,
          f"known failure #294: the file of a stream that dropped comes in on a record already at its end, with no "
          f"reader of its own ({tr.get('id')})")


def file_before_the_silent_stream_reports(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "kkkkkkkkkkk"
    j = A.new_job("downloading", True, target)
    reading, go = threading.Event(), threading.Event()
    reader, ended = real_stream_reader(E, E._reader)
    meta = {"youtube_id": target, "title": "the early one", "channel": "c", "duration": 1.5}
    item = {"id": "short2", "title": "the early one", "file": "short2.m4a", "duration": 1.5, "lufs": -14.0}
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/d", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: SilentFfmpeg(reading, go))):
        check(cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S) and reading.wait(WAIT_S),
              "the early one's stream opened and its reader still reads it")
        with mock.patch.object(A, "download", return_value=item):
            A.run_download(j, target)
        go.set()
        ended.nth(0).wait(WAIT_S)
    del A._abre_stream
    check(readers.wait("short2"), "the file that arrives near the end, before the silent stream's reader reports, gets a "
                                  "reader of its own")


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
        A._prepara(cap.track, x, dict(x), cap)
    check(E.pronto_tag == x["qid"] and readers.wait("d3"), "the similar track is prepared on the second deck, read")
    return x


def mix_until_the_switch(E):
    for _ in range(harness.BLOCOS + 5):
        E._mixa(eng.BLOCK)
        if E.virou is not None:
            return True
    return False


def download_done_while_its_stream_is_prepared(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "sssssssssss"
    j = A.new_job("downloading", True, target)
    x = {"id": None, "youtube_id": target, "url": None, "title": "prepared", "channel": "c", "duration": 600.0,
         "job": j["id"], "qid": "prep7"}
    item = {"id": "prep7", "title": "prepared", "file": "prep7.m4a", "duration": 600.0, "lufs": -14.0,
            "youtube_id": target}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    cap = E.captura()
    info = {"url": "https://stream.invalid/p", "id": target, "title": "prepared", "duration": 600.0}
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(A, "stream_info", return_value=(info, {})):
        A._prepara(cap.track, x, dict(x), cap)
    check(E.pronto_tag == x["qid"], "the downloading entry's stream is prepared on the second deck")
    with (contextlib.redirect_stderr(io.StringIO()),
          mock.patch.object(A, "download", side_effect=lambda *a: A.lib.add(item) or item)):
        A.run_download(j, target)
    check(j["status"] == "done" and (E.track or {}).get("id") == "d1",
          "the download finished while d1 was on the platter and the entry's stream waited prepared")
    check(E.virou is not None or mix_until_the_switch(E), "the engine switched to the prepared stream")
    with contextlib.redirect_stderr(io.StringIO()):
        A._volta_passagem()
    tr = E.track or {}
    check(tr.get("job") == j["id"] and str(tr.get("path", "")).startswith("https://"),
          f"known failure #294: after the switch, the stream stays on the platter though its download finished "
          f"({tr.get('path')})")


def finished_download_after_a_passage_switched_to_its_file(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "ttttttttttt"
    j = A.new_job("downloading", True, target)
    x = {"id": None, "youtube_id": target, "url": None, "title": "shelved", "channel": "c", "duration": 600.0,
         "job": j["id"], "qid": "shelf8"}
    item = {"id": "shelf8", "title": "shelved", "file": "shelf8.m4a", "duration": 600.0, "lufs": -14.0,
            "youtube_id": target}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    switched = []

    def download(*a):
        A.lib.add(item)
        cap = E.captura()
        A._prepara(cap.track, x, dict(x), cap)
        if E.virou is not None or mix_until_the_switch(E):
            switched.append(E.track)
        return item
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(A, "download", side_effect=download),
          mock.patch.object(E, "trocar_fonte", wraps=E.trocar_fonte) as swap):
        A.run_download(j, target)
    check(switched and switched[0].get("id") == "shelf8" and E.track is switched[0] and not swap.called,
          f"a download that finishes after the passage switched to its shelf file leaves that file on the platter, "
          f"with no hand-over ({switched and switched[0].get('path')}, {swap.call_count})")


def passage_to_a_shelf_file_renamed_on_the_way(A, E, readers, before_the_publish):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    iid = "named1" if before_the_publish else "named2"
    A.lib.add(dict(A.lib.get("d2"), id=iid, title="the old name"))
    x = {"id": iid, "youtube_id": None, "url": None, "title": "the old name", "channel": "c", "duration": 120.0,
         "job": None, "qid": iid}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    prepare = E.preparar

    def renamed_first(track, *a, **kw):
        return prepare(renamed_after_the_first_build(A, iid, "the new name", track), *a, **kw)
    cap = E.captura()
    with (contextlib.redirect_stderr(io.StringIO()),
          mock.patch.object(E, "preparar", renamed_first if before_the_publish else prepare)):
        A._prepara(cap.track, x, dict(x), cap)
    check(E.pronto_tag == x["qid"], "the shelf file is prepared on the second deck")
    if not before_the_publish:
        cmd.update_record(A, iid, title="the new name")
    check(E.virou is not None or mix_until_the_switch(E), "the engine switched to the prepared file")
    tr = E.track or {}
    when = "between the passage reading the shelf and publishing" if before_the_publish else "with the file prepared"
    check(tr.get("id") == iid and tr.get("title") == "the new name",
          f"a rename on the shelf {when} reaches the platter after the switch ({tr.get('id')}, {tr.get('title')})")


def stream_renamed_while_it_opens(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "uuuuuuuuuuu"
    j = A.new_job("downloading", True, target)
    info = {"url": "https://stream.invalid/u", "id": target, "title": "the old name", "duration": 200.0}
    swap, renamed = E.trocar_fonte, []

    def renamed_first(atual, novo):
        if not atual.get("path") and not renamed:
            A.lib.add(dict(A.lib.get("d2"), id=atual["id"], youtube_id=target, title="the old name"))
            cmd.update_record(A, atual["id"], title="the new name")
            renamed.append(atual["id"])
        return swap(atual, novo)
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "trocar_fonte", renamed_first),
          mock.patch.object(A, "stream_info", return_value=(info, {}))):
        check(cmd.play_downloading(A, j, target, {"youtube_id": target, "title": "the old name"})
              and stream.ended.wait(WAIT_S), "the job's record is on the platter and its stream opened")
    del A._abre_stream
    check(len(renamed) == 1 and (A.lib.get(renamed[0]) or {}).get("title") == "the new name",
          f"the rename ran once, when the waiting record handed over to its stream, and the shelf has the new name "
          f"({renamed})")
    check(str((E.track or {}).get("path", "")).startswith("https://"), "the job's stream is on the platter")
    check(shown_title(A) == "the old name",
          f"known failure #303: a rename on the shelf while the stream opens is undone by the stream's record, built "
          f"before ({shown_title(A)})")


def downloading_job_played_after_a_rename(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "wwwwwwwwwww"
    j = A.new_job("downloading", True, target)
    x = {"id": None, "youtube_id": target, "url": None, "title": "the old name", "channel": "c", "duration": 600.0,
         "job": j["id"], "qid": "named5"}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    remote, renamed = A.tocar_remoto, []

    def shelved_and_renamed_after_the_miss(*a, **kw):
        A.lib.add(dict(A.lib.get("d2"), id=target, youtube_id=target, title="the old name"))
        cmd.update_record(A, target, title="the new name")
        renamed.append(target)
        return remote(*a, **kw)
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()),
          mock.patch.object(A, "tocar_remoto", shelved_and_renamed_after_the_miss)):
        played = cmd.pular(A)
        check(played is x and stream.ended.wait(WAIT_S),
              "the Next's play missed the shelf, the record was shelved and renamed while the job ran, and the job's "
              "record went on the platter")
    del A._abre_stream
    check(renamed == [target] and (A.lib.get(target) or {}).get("title") == "the new name",
          f"the rename ran once, after the Next missed the shelf, and the shelf has the new name ({renamed})")
    check((E.track or {}).get("id") == target and j["status"] == "running",
          "the job's waiting record is on the platter")
    check(shown_title(A) == "the old name",
          f"known failure #303: a Next to a downloading job whose record was renamed on the shelf after the Next "
          f"missed it puts the entry's name on the platter ({shown_title(A)})")


def prepared_stream_renamed_before_it_is_published(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "vvvvvvvvvvv"
    j = A.new_job("downloading", True, target)
    x = {"id": None, "youtube_id": target, "url": None, "title": "the old name", "channel": "c", "duration": 600.0,
         "job": j["id"], "qid": "named4"}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    info = {"url": "https://stream.invalid/v", "id": target, "title": "the old name", "duration": 600.0}
    channel, renamed = A.canal_depois, []

    def shelved_and_renamed_after_the_build(d, *a, **kw):
        A.lib.add(dict(A.lib.get("d2"), id=target, youtube_id=target, title="the old name"))
        cmd.update_record(A, target, title="the new name")
        renamed.append(target)
        return channel(d, *a, **kw)
    cap = E.captura()
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(A, "stream_info", return_value=(info, {})),
          mock.patch.object(A, "canal_depois", shelved_and_renamed_after_the_build)):
        A._prepara(cap.track, x, dict(x), cap)
    check(E.pronto_tag == x["qid"], "the job's stream is prepared on the second deck")
    check(E.virou is not None or mix_until_the_switch(E), "the engine switched to the prepared stream")
    check(renamed == [target] and (A.lib.get(target) or {}).get("title") == "the new name",
          f"the rename ran once, while the passage built the job's stream, and the shelf has the new name ({renamed})")
    check((E.track or {}).get("id") == target and str((E.track or {}).get("path", "")).startswith("https://"),
          "the job's prepared stream, its HTTP address, is on the platter after the switch")
    check(shown_title(A) == "the old name",
          f"known failure #303: a rename on the shelf while the passage prepares a job's stream leaves the queue "
          f"entry's name on the platter after the switch ({shown_title(A)})")


def play_from_the_shelf_renamed_on_the_way(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    A.lib.add(dict(A.lib.get("d2"), id="named3", title="the old name"))
    load = E.load

    def renamed_first(track, *a, **kw):
        return load(renamed_after_the_first_build(A, "named3", "the new name", track), *a, **kw)
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "load", renamed_first):
        played = A.play_item(A.lib.get("named3"), 0.0)
    tr = E.track or {}
    check(played and tr.get("id") == "named3" and tr.get("title") == "the new name",
          f"a rename on the shelf between a play building the record and the load puts the new name on the platter "
          f"({tr.get('id')}, {tr.get('title')})")


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

    def check_held():
        inside.append(E._qlock.locked())
        if not inside[-1]:
            mix_until_the_switch(E)
        return real()
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with A.fila_lock, mock.patch.object(A.automatico, "head_held", check_held):
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

    def reads(entry, shelf=None):
        found = source(entry, shelf)
        read.set()
        go.wait(WAIT_S)
        return found
    cap = E.captura()
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with mock.patch.object(A, "fonte_de", reads), contextlib.redirect_stderr(io.StringIO()):
        t = threading.Thread(target=A._prepara, args=(cap.track, x, dict(x), cap))
        t.start()
        read.wait(WAIT_S)
        cmd.mover_na_fila(A, y["qid"], 0)
        with A.fila_lock:
            A.automatico._troca_audio("aaaaaaaaaaa", v)
        cmd.mover_na_fila(A, y["qid"], 1)
        go.set()
        t.join(WAIT_S)
    check(read.is_set() and A.fila[0] is x and x["youtube_id"] == "fffffffffff" and "fixa" not in x
          and E.pronto_tag is None,
          f"an entry that left the head, took the audio version and came back while the passage read its source is "
          f"not prepared with the source of before ({x['youtube_id']} in the queue, prepared {E.pronto_tag})")


def failed_source_before_the_audio_version(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = {"id": "d3", "youtube_id": "aaaaaaaaaaa", "url": None, "title": "similar", "channel": "c",
         "duration": 600.0, "job": None, "qid": "similar5", "auto": True}
    y = dict(x, id="d2", youtube_id="bbbbbbbbbbb", qid="other5")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([x, y]))
    read, go, tried = threading.Event(), threading.Event(), threading.Event()

    def fails(entry, shelf=None):
        read.set()
        go.wait(WAIT_S)
        raise RuntimeError("the source of before is gone")
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), contextlib.redirect_stderr(io.StringIO()):
        with mock.patch.object(A, "fonte_de", fails):
            A._volta_passagem()
            read.wait(WAIT_S)
            cmd.mover_na_fila(A, y["qid"], 0)
            with A.fila_lock:
                A.automatico._troca_audio("aaaaaaaaaaa", v)
            cmd.mover_na_fila(A, y["qid"], 1)
            go.set()
            harness.ate(lambda: A.preparando is None)
        with mock.patch.object(A, "_prepara", side_effect=lambda *a: tried.set()) as prepara:
            A._volta_passagem()
            tried.wait(WAIT_S)
        A.preparando = None
    check(tried.is_set() and prepara.call_args.args[1] is x and x["youtube_id"] == "fffffffffff",
          f"a source of before that failed while the entry took the audio version does not keep the new version from "
          f"its passage ({A.failed_passages}, prepared again: {tried.is_set()})")


def engine_prepare_failure_before_the_audio_version(A, E, readers):
    cmd.limpar_fila(A)
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = {"id": "d3", "youtube_id": "aaaaaaaaaaa", "url": None, "title": "similar", "channel": "c",
         "duration": 600.0, "job": None, "qid": "similar6", "auto": True}
    y = dict(x, id="d2", youtube_id="bbbbbbbbbbb", qid="other6")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([x, y]))
    started, tried = threading.Event(), threading.Event()
    v = {"youtube_id": "fffffffffff", "duration": 200, "title": "similar", "channel": "c"}
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        with mock.patch.object(A, "_prepara", side_effect=lambda *a: started.set()):
            A._volta_passagem()
            started.wait(WAIT_S)
        A.preparando = None
        key = carried_key(A, x)
        with E.state_section():
            E._prepare_failure = key
        cmd.mover_na_fila(A, y["qid"], 0)
        with A.fila_lock:
            A.automatico._troca_audio("aaaaaaaaaaa", v)
        cmd.mover_na_fila(A, y["qid"], 1)
        with mock.patch.object(A, "_prepara", side_effect=lambda *a: tried.set()) as prepara:
            A._volta_passagem()
            tried.wait(WAIT_S)
        A.preparando = None
    check(tried.is_set() and prepara.call_args.args[1] is x and x["youtube_id"] == "fffffffffff",
          f"an engine prepare that failed before the entry took the audio version keys the source it prepared, and "
          f"the new version gets its passage ({A.failed_passages}, prepared again: {tried.is_set()})")


class Launches:
    def __init__(self):
        self.qids = []

    def __call__(self, target=None, args=(), daemon=None):
        self.qids.append(args[1]["qid"])
        return self

    def start(self):
        return None


def two_entries(A, n):
    cmd.limpar_fila(A)
    x = {"id": "d3", "youtube_id": "aaaaaaaaaaa", "url": None, "title": "similar", "channel": "c",
         "duration": 600.0, "job": None, "qid": f"similar{n}", "auto": True}
    y = dict(x, id="d2", youtube_id="bbbbbbbbbbb", qid=f"other{n}")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([x, y]))
    return x, y


def carried_key(A, x):
    return A.engine.captura().play, x["qid"], A.passage_source(x)


def watch(A, launches):
    with mock.patch.object(server.threading, "Thread", launches):
        A._volta_passagem()
    A.preparando = None


def engine_prepare_failure_read_with_another_head(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, y = two_entries(A, 7)
    launches = Launches()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
        key = carried_key(A, x)
        with E.state_section():
            E._prepare_failure = key
        cmd.mover_na_fila(A, y["qid"], 0)
        watch(A, launches)
        cmd.mover_na_fila(A, y["qid"], 1)
        watch(A, launches)
    check(launches.qids == [x["qid"], y["qid"]],
          f"an engine prepare failure read while another entry is at the head stays with the entry that failed: the "
          f"other head is prepared, and the one that failed is not prepared again when it comes back unchanged "
          f"({A.failed_passages}, launched {launches.qids})")


def engine_prepare_failure_right_after_the_poll(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 8)
    launches, take = Launches(), E.take_prepare_failure

    def fails_after_the_take(*a):
        found, key = take(*a), carried_key(A, x)
        with E.state_section():
            E._prepare_failure, E.pronto_tag = key, None
        return found
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
        with E.state_section():
            E.pronto_tag = x["qid"]
        with mock.patch.object(E, "take_prepare_failure", fails_after_the_take):
            watch(A, launches)
        watch(A, launches)
    check(launches.qids == [x["qid"]],
          f"a prepare that fails right after the watcher reads the engine is not started again, then or on the next "
          f"pass ({A.failed_passages}, launched {launches.qids})")


def prepare_published_right_after_the_poll(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 9)
    launches, take = Launches(), E.take_prepare_failure

    def publishes_after_the_take(*a):
        found = take(*a)
        with E.state_section():
            E.pronto_tag = x["qid"]
        A.preparando = None
        return found
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), mock.patch.object(server.threading, "Thread", launches):
        A._volta_passagem()
        with mock.patch.object(E, "take_prepare_failure", publishes_after_the_take):
            A._volta_passagem()
    A.preparando = None
    with E.state_section():
        E.pronto_tag = None
    check(launches.qids == [x["qid"]],
          f"a prepare that publishes and ends right after the watcher reads the engine is not started again "
          f"(launched {launches.qids})")


def stream_prepare_failed_then_the_file_reached_the_shelf(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    cmd.limpar_fila(A)
    x = {"id": None, "youtube_id": "kkkkkkkkkkk", "url": None, "title": "similar", "channel": "c", "duration": 600.0,
         "job": None, "qid": "similar11", "auto": True}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    launches = Launches()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
        A.failed_passages.add(carried_key(A, x))
        watch(A, launches)
        A.lib.add({"id": "shelf11", "title": "similar", "file": "shelf11.m4a", "duration": 600.0, "lufs": -14.0,
                   "youtube_id": "kkkkkkkkkkk"})
        watch(A, launches)
        cap = E.captura()
        with mock.patch.object(E, "preparar", return_value=True) as prepares:
            A._prepara(cap.track, x, dict(x), cap)
    A.lib.remove("shelf11")
    handed = prepares.call_args.args[0]() if prepares.call_count == 1 and callable(prepares.call_args.args[0]) else None
    check(launches.qids == [x["qid"], x["qid"]] and (handed or {}).get("file") == "shelf11.m4a",
          f"a stream prepare that failed is not started again from the same stream, and the file that then reaches "
          f"the shelf gets its own attempt, which the worker hands to the engine (launched {launches.qids}, handed "
          f"{(handed or {}).get('file')})")


def file_reached_the_shelf_while_the_prepare_picked_its_source(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    cmd.limpar_fila(A)
    x = {"id": None, "youtube_id": "lllllllllll", "url": None, "title": "similar", "channel": "c", "duration": 600.0,
         "job": None, "qid": "similar12", "auto": True}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    picking, go = threading.Event(), threading.Event()
    launches = Launches()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), contextlib.redirect_stderr(io.StringIO()):
        with mock.patch.object(A, "shelf_item", worker_pauses(A, picking, go)), \
                mock.patch.object(E, "preparar", side_effect=RuntimeError("the file would not open")):
            A._volta_passagem()
            paused = picking.wait(WAIT_S)
            A.lib.add({"id": "shelf12", "title": "similar", "file": "shelf12.m4a", "duration": 600.0, "lufs": -14.0,
                       "youtube_id": "lllllllllll"})
            go.set()
            ended = harness.ate(lambda: A.preparando is None)
            handed = E.preparar.call_args.args[0]() if E.preparar.call_count == 1 else None
        recorded = carried_key(A, x) in A.failed_passages
        watch(A, launches)
    A.lib.remove("shelf12")
    check(paused and ended and (handed or {}).get("file") == "shelf12.m4a" and recorded,
          f"the worker paused before its pick, found the file, handed it to the engine and recorded its key (paused "
          f"{paused}, ended {ended}, handed {(handed or {}).get('file')}, recorded {recorded})")
    check(launches.qids == [],
          f"a file that reaches the shelf while the prepare picks its source, and then fails, is keyed by that file: "
          f"the next poll does not start it again ({A.failed_passages}, launched {launches.qids})")


def worker_pauses(A, pausing, go):
    lookup = A.shelf_item

    def looks(entry):
        if threading.current_thread() is not threading.main_thread():
            pausing.set()
            go.wait(WAIT_S)
        return lookup(entry)
    return looks


def similar_on_its_own(A, letter, n):
    cmd.limpar_fila(A)
    x = {"id": None, "youtube_id": letter * 11, "url": None, "title": "similar", "channel": "c", "duration": 600.0,
         "job": None, "qid": f"similar{n}", "auto": True}
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(x))
    return x


def shelf_record(letter, n):
    return {"id": f"shelf{n}", "title": "similar", "file": f"shelf{n}.m4a", "duration": 600.0, "lufs": -14.0,
            "youtube_id": letter * 11}


def gain_failure_of_a_shelf_file(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = similar_on_its_own(A, "m", 13)
    A.lib.add(item := shelf_record("m", 13))
    launches = Launches()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), contextlib.redirect_stderr(io.StringIO()), \
            mock.patch.object(E, "gain_for", side_effect=ValueError("a stored lufs that is not a number")):
        A._volta_passagem()
        harness.ate(lambda: A.preparando is None)
        watch(A, launches)
    key = carried_key(A, x)
    A.lib.remove("shelf13")
    check(launches.qids == [] and key[2] == ("m" * 11, cmd.Identity(item)) and key in A.failed_passages,
          f"a shelf file whose gain fails is keyed by that file, before the gain, and the next poll does not start it "
          f"again ({A.failed_passages}, launched {launches.qids})")


def two_failures_on_one_record(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, y = two_entries(A, 14)
    launches = Launches()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
        key = carried_key(A, x)
        with E.state_section():
            E._prepare_failure = key
        cmd.mover_na_fila(A, y["qid"], 0)
        watch(A, launches)
        key = carried_key(A, y)
        with E.state_section():
            E._prepare_failure = key
        cmd.mover_na_fila(A, x["qid"], 0)
        watch(A, launches)
    check(launches.qids == [x["qid"], y["qid"]],
          f"two prepares that fail on the same record both stay failed: the first is not started again when it "
          f"comes back to the head after the second failed ({A.failed_passages}, launched {launches.qids})")
    old = E.captura().play
    check(play(A, E, readers, "d2"), "d2 is on the platter, read")
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
    check(not any(k[0] == old for k in A.failed_passages),
          f"the failures of a record leave when another record plays ({A.failed_passages})")


def failure_of_an_earlier_play_of_the_record_playing(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 18)
    launches, old, before, key = Launches(), E.captura().track, E.captura().play, carried_key(A, x)
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        with E.state_section():
            E._prepare_failure = key
        watch(A, launches)
        blocked = launches.qids == []
        E.load(old, 0.0)
        again = readers.wait("d1") and E.captura().track is old and E.captura().play == before + 1
        watch(A, launches)
    A.failed_passages.clear()
    check(blocked and again and launches.qids == [x["qid"]],
          f"the same record object loaded again is a new play: the failure of the first play blocked its source then, "
          f"and does not block it now (blocked {blocked}, again {again}, launched {launches.qids})")


def failures_leave_at_the_switch(A, E, readers):
    x = prepared_similar(A, E, readers, "switch23")
    y = dict(x, id="d2", youtube_id="bbbbbbbbbbb", qid="other23")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.append(y))
    launches, key, before = Launches(), carried_key(A, y), E.captura().play
    A.failed_passages.add(key)
    switched = mix_until_the_switch(E)
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), contextlib.redirect_stderr(io.StringIO()):
        watch(A, launches)
    counted = E.captura().play == before + 1 and E.captura().track.get("id") == "d3"
    pruned = key not in A.failed_passages
    A.failed_passages.clear()
    check(switched and counted and pruned and launches.qids == [y["qid"]],
          f"the passage switch is a new play: the failures of the play before it leave, and the source that failed "
          f"there gets its prepare (switched {switched}, counted {counted}, pruned {pruned}, launched "
          f"{launches.qids})")


def failure_kept_through_the_file_handover_at_the_stream_end(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    target = "ttttttttttt"
    j = A.new_job("downloading", True, target)
    held, go, mede = threading.Event(), threading.Event(), E._mede
    launches = Launches()

    def decodes_nothing(gen, track, start, deck):
        with E._qlock:
            deck.eof_gen = gen

    def gated(*a):
        held.set()
        go.wait(WAIT_S)
        return mede(*a)
    reader, ended = real_stream_reader(E, decodes_nothing)
    meta = {"youtube_id": target, "title": "the stream that ends", "channel": "c", "duration": 1.0}
    stream = StreamThread(A)
    with (contextlib.redirect_stderr(io.StringIO()), mock.patch.object(E, "_reader", reader),
          mock.patch.object(A, "stream_info", return_value=(dict(meta, url="https://stream.invalid/t", id=target), {})),
          mock.patch.object(eng.subprocess, "Popen", lambda *a, **kw: AudioFfmpeg(2)),
          mock.patch.object(eng, "TRANS_PREP_S", 1e6), mock.patch.object(E, "_mede", gated)):
        opened = cmd.play_downloading(A, j, target, meta) and stream.ended.wait(WAIT_S)
        at_the_end = (ended.nth(0).wait(WAIT_S) and str(E.track.get("path", "")).startswith("http")
                      and E._deck.eof_gen == E._deck.gen)
        x, _ = two_entries(A, 21)
        A._volta_passagem()
        deck = E._pronto if held.wait(WAIT_S) else None
        key, before = carried_key(A, x), E.captura().play
        with mock.patch.object(A, "download", return_value=A.lib.get("d2")):
            A.run_download(j, target)
        kept = (deck is not None and E._pronto is deck and str(E.track.get("path", "")).endswith("d2.m4a")
                and E.captura().play == before)
        go.set()
        failed = (harness.ate(lambda: A.preparando is None) and harness.ate(lambda: E._prepare_failure is not None)
                  and E._prepare_failure == key)
        watch(A, launches)
    del A._abre_stream
    recorded = key in A.failed_passages
    A.failed_passages.clear()
    check(opened and at_the_end and kept and failed and recorded and launches.qids == [],
          f"a job's stream whose reader reached its end hands over to the shelf file in the same play and keeps the deck "
          f"prepared before it; the deck that decodes nothing then fails with the key its prepare carried, and the "
          f"watcher does not start that source again (opened {opened}, at the end {at_the_end}, kept {kept}, failed "
          f"{failed}, recorded {recorded}, launched {launches.qids})")


def failures_leave_when_a_stream_enters(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 24)
    launches, key, before = Launches(), carried_key(A, x), E.captura().play
    A.failed_passages.add(key)
    waiting = {"id": "job-s24", "title": "loading", "job": None, "path": None, "stream": True, "duration": 600.0}
    E.espera(waiting)
    entered = E.captura().track is waiting and E.captura().play == before + 1
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
    pruned = key not in A.failed_passages
    A.failed_passages.clear()
    check(entered and pruned,
          f"a record entering the platter through espera, still waiting for its stream, is a new play, and the "
          f"failures of the play before it leave (entered {entered}, pruned {pruned})")


def failure_kept_through_a_restart_of_the_same_record(A, E, readers, restart, how):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 25)
    launches, key, before = Launches(), carried_key(A, x), E.captura().play
    A.failed_passages.add(key)
    with E.state_section():
        E.ended, E._deck.eof_gen = True, E._deck.gen
    restart()
    again = readers.wait("d1") and E.captura().play == before
    E.set_loop(False)
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
    kept = key in A.failed_passages
    A.failed_passages.clear()
    check(again and kept and launches.qids == [],
          f"the record that ended and starts again from the top through {how} is the same play, and its failures still "
          f"block their source (again {again}, kept {kept}, launched {launches.qids})")


def failure_kept_through_a_seek(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 22)
    launches, key = Launches(), carried_key(A, x)
    A.failed_passages.add(key)
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        line = E.captura().linha
        E.seek(30.0)
        moved = readers.wait("d1") and E.captura().linha != line
        watch(A, launches)
    kept = key in A.failed_passages
    A.failed_passages.clear()
    check(moved and kept and launches.qids == [],
          f"a seek starts a new line in the same play, and the play's failures still block their source (moved "
          f"{moved}, kept {kept}, launched {launches.qids})")


def shelf_record_deleted_before_the_pick(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = similar_on_its_own(A, "n", 15)
    A.failed_passages.add(carried_key(A, x))
    A.lib.add(shelf_record("n", 15))
    picking, go, lookups = threading.Event(), threading.Event(), []
    pauses = worker_pauses(A, picking, go)

    def looks(entry):
        found = pauses(entry)
        if threading.current_thread() is not threading.main_thread():
            lookups.append((found, threading.current_thread()))
        return found
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), contextlib.redirect_stderr(io.StringIO()), \
            mock.patch.object(A, "shelf_item", looks), \
            mock.patch.object(A, "stream_info", side_effect=RuntimeError("the stream that failed")) as opens:
        A._volta_passagem()
        paused = picking.wait(WAIT_S)
        A.lib.remove("shelf15")
        go.set()
        ended = harness.ate(lambda: len(lookups) == 1 and not lookups[0][1].is_alive())
    check(paused and ended and len(lookups) == 1 and lookups[0][0][1] is None and not opens.called,
          f"a shelf record deleted between the poll and the pick leaves the stream that failed before: the worker's "
          f"own lookup saw the deletion, it ended, and it did not open that stream again (paused {paused}, ended "
          f"{ended}, lookups {len(lookups)}, opened {opens.call_count})")


def replacement_shelf_file_after_its_predecessor_failed(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x = similar_on_its_own(A, "p", 19)
    A.lib.add(dict(shelf_record("p", 19), added="2026-11-26T00:00:00", lufs=-14.0))
    A.failed_passages.add(failed := carried_key(A, x))
    A.lib.remove("shelf19")
    A.lib.add(replacement := dict(shelf_record("p", 19), added="2026-11-26T00:00:00", lufs=-9.0))
    launches, want = Launches(), carried_key(A, x)
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6):
        watch(A, launches)
        cap = E.captura()
        with mock.patch.object(E, "preparar", return_value=True) as prepares:
            A._prepara(cap.track, x, dict(x), cap)
    handed = prepares.call_args.args[0]() if prepares.call_count == 1 and callable(prepares.call_args.args[0]) else None
    key = prepares.call_args.kwargs.get("key") if prepares.call_count == 1 else None
    A.lib.remove("shelf19")
    A.failed_passages.clear()
    check(launches.qids == [x["qid"]] and (handed or {}).get("lufs") == -9.0
          and key == want != failed and want[2][1] == cmd.Identity(replacement),
          f"a shelf record downloaded again with the same id, file name and added stamp, replacing one whose prepare "
          f"failed, for the same entry, gets its own prepare, and the worker hands the new record and its own key to "
          f"the engine (launched {launches.qids}, handed lufs {(handed or {}).get('lufs')}, key {key})")


def engine_failure_through_the_real_prepare(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, _ = two_entries(A, 16)

    def decodes_nothing(gen, track, start, deck):
        with E._qlock:
            deck.eof_gen = gen
    launches = Launches()
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), contextlib.redirect_stderr(io.StringIO()), \
            mock.patch.object(E, "_reader", decodes_nothing):
        A._volta_passagem()
        prepared = harness.ate(lambda: A.preparando is None) and harness.ate(lambda: E._prepare_failure is not None)
        watch(A, launches)
    recorded = carried_key(A, x) in A.failed_passages
    A.failed_passages.clear()
    check(prepared and launches.qids == [] and recorded and E.pronto_tag is None,
          f"the real prepare hands its key to the engine, the deck that decodes nothing fails with it, and the watcher "
          f"does not start that prepare again (launched {launches.qids})")


def prepared_head_moved_back_during_the_poll(A, E, readers):
    check(play(A, E, readers, "d1"), "d1 is on the platter, read")
    x, y = (dict(e, auto=False) for e in two_entries(A, 10))
    with A.fila_lock:
        A.change_queue(lambda: (A.fila.clear(), A.fila.extend([x, y])))
    inner, take, done = A.fila_lock, E.take_prepare_failure, []

    def gap():
        if not done:
            done.append(True)
            cmd.mover_na_fila(A, y["qid"], 0)
            with E.state_section():
                E.pronto_tag = y["qid"]

    class GapLock:
        released = False

        def __enter__(self):
            if GapLock.released:
                gap()
            inner.acquire()

        def __exit__(self, *exc):
            inner.release()
            GapLock.released = True

        def locked(self):
            return inner.locked()

    def moves_back_and_publishes(*a):
        if not inner.locked():
            gap()
        return take(*a)

    with E.state_section():
        E.pronto_tag = y["qid"]
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), mock.patch.object(server.threading, "Thread", Launches()), \
            mock.patch.object(E, "take_prepare_failure", moves_back_and_publishes), \
            mock.patch.object(A, "fila_lock", GapLock()):
        A._volta_passagem()
    gap()
    survived = E.pronto_tag
    with mock.patch.object(eng, "TRANS_PREP_S", 1e6), mock.patch.object(server.threading, "Thread", Launches()):
        A._volta_passagem()
    kept = E.pronto_tag
    A.preparando = None
    with E.state_section():
        E.pronto_tag = None
    check(survived == kept == y["qid"],
          f"a head that moves back and gets its prepared deck in any gap of the watcher's poll keeps that deck, and "
          f"the next poll keeps the deck prepared for the head (prepared after the poll: {survived}, after the next: "
          f"{kept})")


def audio_version_entries(A, E):
    cmd.limpar_fila(A)
    entry = {"id": None, "url": None, "title": "similar", "channel": "c", "duration": 300.0, "job": None,
             "youtube_id": "ggggggggggg", "auto": True}
    head, tail = dict(entry, qid="head1"), dict(entry, qid="tail1")
    with A.fila_lock:
        A.change_queue(lambda: A.fila.extend([head, tail]))
    mixed = {"youtube_id": "ggggggggggg", "title": "mixed", "ordem": 1}
    plain = {"youtube_id": "hhhhhhhhhhh", "title": "plain", "ordem": 2}
    au = A.automatico
    mix0, au._mix = au._mix, [mixed, plain, head]
    v = {"youtube_id": "iiiiiiiiiii", "duration": 200, "title": "the audio", "channel": "c"}
    audio = {"youtube_id": "iiiiiiiiiii", "duration": 200, "title": "the audio", "channel": "c", "audio": True,
             "video": "ggggggggggg", "thumb": music.thumb("iiiiiiiiiii"), "tipo": "ATV"}
    try:
        with A.fila_lock, mock.patch.object(au, "head_held", return_value=True):
            au._troca_audio("ggggggggggg", v)
        check(head == dict(entry, qid="head1"), f"the held head keeps its version ({head})")
        check(tail == dict(entry, qid="tail1", **audio), f"the entry after it takes the audio version ({tail})")
        check(au._mix[0] == {"ordem": 1, **audio} and mixed == {"youtube_id": "ggggggggggg", "title": "mixed",
                                                              "ordem": 1},
              f"the Mix entry takes the audio version as a new entry ({au._mix[0]}, {mixed})")
        check(au._mix[2] is not head and au._mix[2]["audio"],
              f"the Mix's copy of the head takes it too, and the queue's head stays ({au._mix[2]})")
        with A.fila_lock, mock.patch.object(au, "head_held", return_value=False):
            au._troca_audio("hhhhhhhhhhh", None)
        check(au._mix[1] == {"youtube_id": "hhhhhhhhhhh", "title": "plain", "ordem": 2, "audio": True},
              f"with no audio version, the Mix entry only gets the mark that it was looked up ({au._mix[1]})")
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
        au._mix = mix0
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
                finished_download_put_back_before_the_stop(A, E, readers)
                finished_download_forgotten_during_the_refusal(A, E, readers)
                refused_stream_after_another_record(A, E, readers)
                silent_stream_after_the_download_failed(A, E, readers)
                stream_opens_after_the_download_read_the_platter(A, E, readers)
                file_after_a_refused_stream(A, E, readers)
                file_after_the_record_was_renamed_on_the_shelf(A, E, readers)
                file_after_a_refused_stream(
                    A, E, readers, server.i18n.msg("server.devices.notFound", "Couldn't find the device."))
                file_near_the_end_of_a_stream_with_audio(A, E, readers)
                file_near_the_end_of_a_stream_with_audio(A, E, readers, repeat=True)
                failed_read_after_a_seek_near_the_end(A, E, readers)
                silent_stream_then_a_seek(A, E, readers)
                file_near_the_end_of_a_silent_stream(A, E, readers)
                file_near_the_end_of_a_silent_stream(
                    A, E, readers, server.i18n.msg("server.devices.notFound", "Couldn't find the device."))
                file_near_the_end_of_a_silent_stream(
                    A, E, readers, server.i18n.msg("server.devices.notFound", "Couldn't find the device."), before=True)
                file_after_a_stream_that_dropped(A, E, readers)
                file_before_the_silent_stream_reports(A, E, readers)
                warning_after_another_record_took_the_platter(A, E, readers)
                download_done_while_its_stream_is_prepared(A, E, readers)
                finished_download_after_a_passage_switched_to_its_file(A, E, readers)
                passage_to_a_shelf_file_renamed_on_the_way(A, E, readers, True)
                passage_to_a_shelf_file_renamed_on_the_way(A, E, readers, False)
                play_from_the_shelf_renamed_on_the_way(A, E, readers)
                stream_renamed_while_it_opens(A, E, readers)
                downloading_job_played_after_a_rename(A, E, readers)
                prepared_stream_renamed_before_it_is_published(A, E, readers)
                audio_version_during_a_pending_switch(A, E, readers)
                audio_version_while_the_engine_switches(A, E, readers)
                audio_version_while_the_passage_reads_the_source(A, E, readers)
                failed_source_before_the_audio_version(A, E, readers)
                engine_prepare_failure_before_the_audio_version(A, E, readers)
                engine_prepare_failure_read_with_another_head(A, E, readers)
                engine_prepare_failure_right_after_the_poll(A, E, readers)
                prepare_published_right_after_the_poll(A, E, readers)
                prepared_head_moved_back_during_the_poll(A, E, readers)
                stream_prepare_failed_then_the_file_reached_the_shelf(A, E, readers)
                file_reached_the_shelf_while_the_prepare_picked_its_source(A, E, readers)
                gain_failure_of_a_shelf_file(A, E, readers)
                two_failures_on_one_record(A, E, readers)
                shelf_record_deleted_before_the_pick(A, E, readers)
                failure_of_an_earlier_play_of_the_record_playing(A, E, readers)
                failure_kept_through_the_file_handover_at_the_stream_end(A, E, readers)
                failure_kept_through_a_seek(A, E, readers)
                failures_leave_at_the_switch(A, E, readers)
                failures_leave_when_a_stream_enters(A, E, readers)
                failure_kept_through_a_restart_of_the_same_record(A, E, readers, E.resume, "resume")
                failure_kept_through_a_restart_of_the_same_record(A, E, readers, E.alterna, "the toggle")
                failure_kept_through_a_restart_of_the_same_record(A, E, readers, lambda: E.set_loop(True),
                                                                  "the Repeat turned on at the end")
                replacement_shelf_file_after_its_predecessor_failed(A, E, readers)
                engine_failure_through_the_real_prepare(A, E, readers)
                audio_version_entries(A, E)
                audio_version_while_an_entry_plays_from_the_queue(A)
                file_wait_after_a_passage_switch(A, E, readers)
            finally:
                E.close()
    failures.extend(harness.falhas)
    if failures:
        print(f"\n{len(failures)} failure(s)")
        sys.exit(1)
    print("\nall passed")


if __name__ == "__main__":
    main()
