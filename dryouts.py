import sys
import time

AFTER_TRACK_S = 5.0
QUIET_S = 10.0
PEDAL_LINES = 10


class VoicePedalStart:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.on_at = self.track_up_at = None
        self._live = False

    def pedal(self, on):
        if not on:
            self.on_at = None
        elif self.on_at is None:
            self.on_at = self.clock()

    def track(self, live, up_s_ago=0.0):
        if live and not self._live:
            self.track_up_at = self.clock() - up_s_ago
        self._live = live
        return live

    def starting(self):
        on_at, up_at = self.on_at, self.track_up_at
        if on_at is None:
            return None
        now = self.clock()
        if up_at is None or up_at < on_at:
            return f"the pedal turned on {now - on_at:.2f} s ago, its voice track isn't up yet"
        if now - up_at > AFTER_TRACK_S:
            return None
        return f"the pedal turned on {now - on_at:.2f} s ago, its voice track came up {now - up_at:.2f} s ago"


class RingDryOuts:
    def __init__(self, pedal):
        self.pedal = pedal
        self.while_pedal_starting = 0
        self._told_at = -1e9
        self._start, self._told_this_start = None, 0

    def ran_dry(self, back_s, count):
        start, starting = self.pedal.on_at, self.pedal.starting()
        if starting is not None:
            self.while_pedal_starting += 1
            if start != self._start:
                self._start, self._told_this_start = start, 0
            self._told_this_start += 1
            if self._told_this_start <= PEDAL_LINES:
                print(f"game output: the microphone ring ran dry while the voice pedal was starting (the thread came "
                      f"back after {back_s * 1000:.0f} ms; {starting}; {self.while_pedal_starting} of {count} so far)",
                      file=sys.stderr, flush=True)
                return
        if self.pedal.clock() - self._told_at > QUIET_S:
            self._told_at = self.pedal.clock()
            print(f"game output: the microphone ring ran dry (the thread came back after {back_s * 1000:.0f} ms; "
                  f"{count} so far)", file=sys.stderr, flush=True)
