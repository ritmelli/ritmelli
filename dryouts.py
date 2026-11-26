import itertools
import math
import sys
import time

AFTER_TRACK_S = 5.0
QUIET_S = 10.0
PEDAL_LINES = 10
TICK_S = 0.016
ENDED_STARTS = 8


def tell(line):
    print(line, file=sys.stderr, flush=True)


def up_after(up_ms, sent):
    return sent is not None and up_ms > round(sent * 1000)


class VoicePedalStart:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.track_up_at = self._stamp = self._on = None
        self._ended = ()

    @property
    def on_at(self):
        on = self._on
        return None if on is None else on[0]

    def pedal(self, on):
        start = self._on
        if not on:
            if start is not None:
                start[1] = self.clock()
                self._ended = (*self._ended, start)[-ENDED_STARTS:]
            self._on = None
            return None
        if start is None:
            start = self._on = [self.clock(), None, None, None]
        return start

    def sent(self, start):
        if start is not None and start[3] is None:
            start[3] = self.clock()

    def track(self, stamp):
        now = self.clock()
        if stamp and stamp != self._stamp:
            now_ms = round(now * 1000)
            up_ms = now_ms - (now_ms - (stamp - 1)) % (2**32 - 1)
            up_at = up_ms / 1000
            on, ended = self._on, self._ended
            if on is not None and up_after(up_ms, on[3]) and (on[1] is None or up_at <= on[1] + TICK_S):
                owner = on
            else:
                owner = next((e for e in reversed(ended) if up_after(up_ms, e[3]) and up_at <= e[1] + TICK_S), None)
            if owner is not None:
                tell(f"voice pedal: its voice track came up {up_at - owner[0]:.2f} s after the pedal turned on")
                owner[2] = up_at
            self.track_up_at = up_at
        self._stamp = stamp

    def starting(self, lo=None, empty_at=None):
        start, ended = self._on, self._ended
        off_by = lo if lo is not None else empty_at
        if empty_at is not None and (start is None or start[0] > empty_at):
            start = next((e for e in reversed(ended) if e[0] <= empty_at and e[1] > off_by), start)
        if start is None:
            return None, None
        on_at, off_at, up_at, _ = start
        if (empty_at is not None and on_at > empty_at) or (None not in (off_by, off_at) and off_at <= off_by):
            return on_at, None
        now = self.clock()
        pedal = f"the pedal turned on {now - on_at:.2f} s ago"
        if off_at is not None:
            pedal += f" and off {now - off_at:.2f} s ago"
            if empty_at is not None and off_at <= empty_at:
                pedal += " (before the ring was seen empty, maybe before it ran dry)"
        if lo is not None and on_at > lo:
            pedal += " (after the ring was last filled, maybe after it ran dry)"
        elif lo is None and empty_at is not None:
            pedal += " (with no fill seen, maybe after it ran dry)"
        if up_at is None:
            return on_at, f"{pedal}, its voice track isn't up yet"
        if (lo if lo is not None else now if empty_at is None else empty_at) - up_at > AFTER_TRACK_S:
            return on_at, None
        if empty_at is not None and up_at > empty_at + TICK_S:
            return on_at, f"{pedal}, its voice track came up {now - up_at:.2f} s ago, after the ring ran dry"
        if lo is None and empty_at is not None:
            return on_at, (f"{pedal}, its voice track came up {now - up_at:.2f} s ago, with no fill seen, "
                           "so which came first is not known")
        if lo is not None and up_at > lo + TICK_S:
            return on_at, (f"{pedal}, its voice track came up {now - up_at:.2f} s ago, after the ring was last filled, "
                           "so which came first is not known")
        if lo is not None and up_at > lo - TICK_S:
            return on_at, (f"{pedal}, its voice track came up {now - up_at:.2f} s ago, within a tick of the ring's last "
                           "fill, so which came first is not known")
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
            self.filled_at = None
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
                tell(f"game output: the microphone ring ran dry while the voice pedal was starting (the thread "
                     f"came back after {back_s * 1000:.0f} ms;{self._bounds(start)} {starting}; "
                     f"{self.while_pedal_starting} of {count} so far, injector {self.injector})")
                return
        if self.pedal.clock() - self._told_at > QUIET_S:
            self._told_at = self.pedal.clock()
            tell(f"game output: the microphone ring ran dry (the thread came back after {back_s * 1000:.0f} ms; "
                 f"{count} so far, injector {self.injector})")
