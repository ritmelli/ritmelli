import queue
import sys
import threading
import time

AFTER_TRACK_S = 5.0
QUIET_S = 10.0
PEDAL_LINES = 10
LOG_LINES = 64
TICK_S = 0.016


class Log:
    def __init__(self, size=LOG_LINES):
        self._lines = queue.Queue(size)
        self._full = self._failed = 0
        threading.Thread(target=self._write, daemon=True, name="dryouts-log").start()

    def tell(self, line):
        try:
            self._lines.put_nowait(line)
        except queue.Full:
            self._full += 1

    @property
    def dropped(self):
        return self._full + self._failed

    def written(self):
        self._lines.join()

    def _write(self):
        told = 0
        while True:
            line = self._lines.get()
            dropped = self.dropped
            if dropped > told:
                line = f"{line} ({dropped - told} line(s) of the dry-out log dropped before this one)"
            try:
                if sys.stderr is not None:
                    print(line, file=sys.stderr, flush=True)
                    told = dropped
            except OSError:
                self._failed += 1
            finally:
                self._lines.task_done()


LOG = Log()


class VoicePedalStart:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.on_at = self.track_up_at = self._stamp = self.last_on = None
        self._live = False

    def pedal(self, on):
        on_at = self.on_at
        if not on:
            if on_at is not None:
                up_at = self.track_up_at
                self.last_on = (on_at, self.clock(), up_at if up_at is not None and up_at >= on_at else None)
            self.on_at = None
        elif on_at is None:
            self.on_at = self.clock()

    def track(self, live, stamp=None):
        now = self.clock()
        new = (stamp != self._stamp) if stamp else (live and not self._live)
        if new:
            up_at = now - (round(now * 1000) - (stamp - 1)) % (2**32 - 1) / 1000 if stamp else now
            on_at = self.on_at
            if on_at is not None and up_at >= on_at:
                LOG.tell(f"voice pedal: its voice track came up {up_at - on_at:.2f} s after the pedal turned on")
            self.track_up_at = up_at
        self._live = live
        if stamp is not None:
            self._stamp = stamp
        return live

    def starting(self, lo=None, empty_at=None):
        on_at, last_on, up_at = self.on_at, self.last_on, self.track_up_at
        off_at = None
        if (lo is not None and empty_at is not None and last_on is not None and lo < last_on[1]
                and last_on[0] <= empty_at and (on_at is None or on_at > empty_at)):
            on_at, off_at, kept = last_on
            up_at = up_at if up_at is not None and on_at <= up_at <= off_at + TICK_S else kept
        if on_at is None or (empty_at is not None and on_at > empty_at):
            return on_at, None
        now = self.clock()
        pedal = f"the pedal turned on {now - on_at:.2f} s ago"
        if off_at is not None:
            pedal += f" and off {now - off_at:.2f} s ago"
            if off_at <= empty_at:
                pedal += " (before the ring was seen empty, maybe before it ran dry)"
        if lo is not None and on_at > lo:
            pedal += " (after the ring was last filled, maybe after it ran dry)"
        if up_at is None or up_at < on_at:
            return on_at, f"{pedal}, its voice track isn't up yet"
        if (now if lo is None else lo) - up_at > AFTER_TRACK_S:
            return on_at, None
        if empty_at is not None and up_at > empty_at + TICK_S:
            return on_at, f"{pedal}, its voice track came up {now - up_at:.2f} s ago, after the ring ran dry"
        if lo is not None and up_at > lo - TICK_S:
            return on_at, (f"{pedal}, its voice track came up {now - up_at:.2f} s ago, after the ring was last filled, "
                           "so which came first is not known")
        return on_at, f"{pedal}, its voice track came up {now - up_at:.2f} s ago"


class RingDryOuts:
    def __init__(self, pedal):
        self.pedal = pedal
        self.while_pedal_starting = 0
        self.counts = (0, 0)
        self._told_at = -1e9
        self._start, self._told_this_start = None, 0
        self.filled_at = self.empty_at = None

    def state(self):
        dry_outs, while_pedal_starting = self.counts
        return {"secas": dry_outs, "secas_pedal": while_pedal_starting}

    def read_ring(self, read):
        before = self.pedal.clock()
        held = read()
        if held > 0:
            self.filled_at = before
        else:
            self.empty_at = self.pedal.clock()
        return held

    def ran_dry(self, back_s, count):
        start, starting = self.pedal.starting(self.filled_at, self.empty_at)
        if starting is not None:
            self.while_pedal_starting += 1
        self.counts = (count, self.while_pedal_starting)
        if starting is not None:
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
