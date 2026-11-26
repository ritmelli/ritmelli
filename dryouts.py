import queue
import sys
import threading
import time

AFTER_TRACK_S = 5.0
QUIET_S = 10.0
PEDAL_LINES = 10
LOG_LINES = 64


class Log:
    def __init__(self, size=LOG_LINES):
        self._lines = queue.Queue(size)
        self.dropped = 0
        threading.Thread(target=self._write, daemon=True, name="dryouts-log").start()

    def tell(self, line):
        try:
            self._lines.put_nowait(line)
        except queue.Full:
            self.dropped += 1

    def written(self):
        self._lines.join()

    def _write(self):
        told = 0
        while True:
            line = self._lines.get()
            dropped = self.dropped
            if dropped > told:
                line, told = f"{line} ({dropped - told} line(s) of the dry-out log dropped before this one)", dropped
            try:
                if sys.stderr is not None:
                    print(line, file=sys.stderr, flush=True)
            except OSError:
                self.dropped += 1
            finally:
                self._lines.task_done()


LOG = Log()


class VoicePedalStart:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.on_at = self.track_up_at = self._stamp = None
        self._live = False

    def pedal(self, on):
        if not on:
            self.on_at = None
        elif self.on_at is None:
            self.on_at = self.clock()

    def track(self, live, stamp=None, up_s_ago=0.0):
        new = (stamp != self._stamp) if stamp else (live and not self._live)
        if new:
            up_at, on_at = self.clock() - up_s_ago, self.on_at
            if on_at is not None and up_at >= on_at:
                LOG.tell(f"voice pedal: its voice track came up {up_at - on_at:.2f} s after the pedal turned on")
            self.track_up_at = up_at
        self._live = live
        if stamp is not None:
            self._stamp = stamp
        return live

    def starting(self, away_s=0.0):
        on_at, up_at = self.on_at, self.track_up_at
        if on_at is None:
            return on_at, None
        now = self.clock()
        if up_at is None or up_at < on_at:
            return on_at, f"the pedal turned on {now - on_at:.2f} s ago, its voice track isn't up yet"
        if now - up_at > AFTER_TRACK_S:
            return on_at, None
        if now - up_at < away_s:
            return on_at, (f"the pedal turned on {now - on_at:.2f} s ago, its voice track came up {now - up_at:.2f} s "
                           "ago, while the thread was away, so which came first is not known")
        return on_at, f"the pedal turned on {now - on_at:.2f} s ago, its voice track came up {now - up_at:.2f} s ago"


class RingDryOuts:
    def __init__(self, pedal):
        self.pedal = pedal
        self.while_pedal_starting = 0
        self._told_at = -1e9
        self._start, self._told_this_start = None, 0

    def ran_dry(self, back_s, count):
        start, starting = self.pedal.starting(back_s)
        if starting is not None:
            self.while_pedal_starting += 1
            if start != self._start:
                self._start, self._told_this_start = start, 0
            self._told_this_start += 1
            if self._told_this_start <= PEDAL_LINES:
                LOG.tell(f"game output: the microphone ring ran dry while the voice pedal was starting (the thread "
                         f"came back after {back_s * 1000:.0f} ms; {starting}; {self.while_pedal_starting} of {count} "
                         "so far)")
                return
        if self.pedal.clock() - self._told_at > QUIET_S:
            self._told_at = self.pedal.clock()
            LOG.tell(f"game output: the microphone ring ran dry (the thread came back after {back_s * 1000:.0f} ms; "
                     f"{count} so far)")
