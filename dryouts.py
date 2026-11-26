import itertools
import math
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
        self.track_up_at = self._stamp = self._on = self._ended = None
        self._live = False

    @property
    def on_at(self):
        on = self._on
        return None if on is None else on[0]

    def pedal(self, on):
        start = self._on
        if not on:
            if start is not None:
                start[1] = self.clock()
                self._ended = start
            self._on = None
        elif start is None:
            self._on = [self.clock(), None, None]

    def track(self, live, stamp=None):
        now = self.clock()
        new = (stamp != self._stamp) if stamp else (live and not self._live)
        if new:
            up_at = now - (round(now * 1000) - (stamp - 1)) % (2**32 - 1) / 1000 if stamp else now
            on, ended, owner = self._on, self._ended, None
            if on is not None and up_at >= on[0] and (on[1] is None or up_at <= on[1] + TICK_S):
                owner = on
            elif ended is not None and ended[0] <= up_at <= ended[1] + TICK_S:
                owner = ended
            if owner is not None:
                LOG.tell(f"voice pedal: its voice track came up {up_at - owner[0]:.2f} s after the pedal turned on")
                owner[2] = up_at
            self.track_up_at = up_at
        self._live = live
        if stamp is not None:
            self._stamp = stamp
        return live

    def starting(self, lo=None, empty_at=None):
        start, ended = self._on, self._ended
        if (lo is not None and empty_at is not None and ended is not None
                and ended[0] <= empty_at and (start is None or start[0] > empty_at)):
            start = ended
        if start is None:
            return None, None
        on_at, off_at, up_at = start
        if (empty_at is not None and on_at > empty_at) or (lo is not None and off_at is not None and off_at <= lo):
            return on_at, None
        now = self.clock()
        pedal = f"the pedal turned on {now - on_at:.2f} s ago"
        if off_at is not None:
            pedal += f" and off {now - off_at:.2f} s ago"
            if empty_at is not None and off_at <= empty_at:
                pedal += " (before the ring was seen empty, maybe before it ran dry)"
        if lo is not None and on_at > lo:
            pedal += " (after the ring was last filled, maybe after it ran dry)"
        if up_at is None:
            return on_at, f"{pedal}, its voice track isn't up yet"
        if (now if lo is None else lo) - up_at > AFTER_TRACK_S:
            return on_at, None
        if empty_at is not None and up_at > empty_at + TICK_S:
            return on_at, f"{pedal}, its voice track came up {now - up_at:.2f} s ago, after the ring ran dry"
        if lo is not None and up_at > lo - TICK_S:
            return on_at, (f"{pedal}, its voice track came up {now - up_at:.2f} s ago, after the ring was last filled, "
                           "so which came first is not known")
        return on_at, f"{pedal}, its voice track came up {now - up_at:.2f} s ago"


INJECTORS = itertools.count(1)


class RingDryOuts:
    def __init__(self, pedal):
        self.pedal = pedal
        self.injector = next(INJECTORS)
        self._readers = ((), 0)
        self.while_pedal_starting = 0
        self.counts = (0, 0, 0.0)
        self._told_at = -1e9
        self._start, self._told_this_start = None, 0
        self.filled_at = self.empty_at = None

    def _bounds(self, on_at):
        lo, empty_at = self.filled_at, self.empty_at
        if empty_at is None:
            return ""
        by = math.ceil(round((empty_at - on_at) * 100, 6)) / 100
        if lo is None:
            return f" it ran dry by {by:.2f} s after the pedal turned on;"
        since = math.floor(round((lo - on_at) * 100, 6)) / 100
        return f" it ran dry between {since:.2f} and {by:.2f} s after the pedal turned on;"

    def state(self):
        dry_outs, while_pedal_starting, longest = self.counts
        owners, changes = self._readers
        return {"secas": dry_outs, "secas_pedal": while_pedal_starting, "volta_max_ms": round(longest * 1000, 1),
                "injetor": self.injector, "leitores": len(owners), "leitores_trocados": changes}

    def served(self, owners):
        served, changes = self._readers
        if owners != served:
            self._readers = (owners, changes + 1)
        return owners

    def read_ring(self, read):
        before = self.pedal.clock()
        held = read()
        if held > 0:
            self.filled_at = before
        else:
            self.empty_at = self.pedal.clock()
        return held

    def publish(self, count, longest):
        self.counts = (count, self.while_pedal_starting, longest)

    def ran_dry(self, back_s, count, longest):
        start, starting = self.pedal.starting(self.filled_at, self.empty_at)
        self.while_pedal_starting += starting is not None
        self.publish(count, max(longest, back_s))
        if starting is not None:
            if start != self._start:
                self._start, self._told_this_start = start, 0
            self._told_this_start += 1
            if self._told_this_start <= PEDAL_LINES:
                LOG.tell(f"game output: the microphone ring ran dry while the voice pedal was starting (the thread "
                         f"came back after {back_s * 1000:.0f} ms;{self._bounds(start)} {starting}; "
                         f"{self.while_pedal_starting} of {count} so far, injector {self.injector})")
                return
        if self.pedal.clock() - self._told_at > QUIET_S:
            self._told_at = self.pedal.clock()
            LOG.tell(f"game output: the microphone ring ran dry (the thread came back after {back_s * 1000:.0f} ms; "
                     f"{count} so far, injector {self.injector})")
