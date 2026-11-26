r"""Checks esticar_saida (engine.py), the outgoing track resampled to a new speed before an on-beat fade-out with both
tracks stretched, on its own, through the real Rubber Band:

  - position: under a strong steady tone (as in the tone pair of dev/testa_passagem.py, #197), every attack in the
    output sits where the returned position (phi) says it came from in the input, to within POSITION_TOLERANCE_MS;
  - pitch: after the ramp, at the constant speed, the steady tone is back at its own pitch, so the output did go
    through the Rubber Band;
  - level: on broadband noise, no LEVEL_WINDOW_MS window at the start of the output drops more than
    LEVEL_DROP_DB below the input, so the switch from what already played into the stretched audio has no gap;
  - short: an input shorter than the warm-up and the crossfade (SHORT_MS) comes back whole, one output frame per
    position;
  - incoming level: the same level check on esticar, the next track's stretch, which still starts silent (#264). It is
    a known failure: it runs and its result is shown, and a drop only in the first INCOMING_SILENT_MS, with no gap
    (more than INCOMING_GAP_DB down) after it, does not count. A gap after it counts, and passing does too, so the fix
    takes the case off the list.

Position, pitch and level run at a speed below and one above 1 (A slowed down and sped up, as in the dois and dois-106
pairs); both short inputs run at SHORT_SPEED; the incoming level runs at 1 - TEMPO_MAX and 1 + TEMPO_MAX.

    python dev/test_stretch_outgoing.py

One line with the measured numbers also goes to the PR summary (the "-- summary:" line of dev/testa_tudo.py).

Exits 1 if anything fails."""
import sys
from pathlib import Path

import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import engine
import transicao

SR = engine.SR
SPEEDS = (1 - transicao.SAI_MAX, 1 + transicao.SAI_MAX)
DURATION_S = 22.0
TONE_HZ = 1201.0
ATTACK_BAND = (200.0, 500.0)
ATTACK_EVERY_S = 0.6
CHECKED_S = 4.0
POSITION_TOLERANCE_MS = 2.0
SEARCH_MS = 120.0
LEVEL_WINDOW_MS = 5.0
LEVEL_CHECKED_S = 0.3
LEVEL_DROP_DB = 3.0
PITCH_TOLERANCE_HZ = 5.0
SHORT_MS = (30.0, 75.0)
SHORT_SPEED = 1.01
INCOMING_SPEEDS = (1 - transicao.TEMPO_MAX, 1 + transicao.TEMPO_MAX)
INCOMING_OVERLAP_S = 4.0
INCOMING_RAMP_S = 8.0
INCOMING_ISSUE = 264
INCOMING_SILENT_MS = 60.0
INCOMING_GAP_DB = 6.0

failures = []


def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def stereo(x):
    return np.repeat(x[:, None], 2, axis=1).astype(np.float32)


def band(x, edges):
    return signal.sosfilt(signal.butter(4, edges, "bandpass", fs=SR, output="sos"), x)


def attacks_input(rng):
    n = int(DURATION_S * SR)
    t = np.arange(n) / SR
    x = 0.3 * np.sin(2 * np.pi * TONE_HZ * t)
    k = int(0.12 * SR)
    env = np.exp(-np.arange(k) / SR / 0.03)
    env[:48] *= np.arange(48) / 48
    starts = np.arange(0.3, DURATION_S - 1.0, ATTACK_EVERY_S)
    for start in starts:
        i = int(start * SR)
        burst = band(rng.standard_normal(k + SR // 10), ATTACK_BAND)[SR // 10:]
        x[i:i + k] += 0.4 * env * burst / np.abs(burst).max()
    return stereo(x), starts * SR


def ramp_samples(speed):
    return transicao.rampa_saida(speed, 100.0)[0]


def position(speed, rng):
    x, starts = attacks_input(rng)
    ramp = ramp_samples(speed)
    z, phi = engine.esticar_saida(x, speed, ramp)
    xb, zb = band(x[:, 0], ATTACK_BAND), band(z[:, 0], ATTACK_BAND)
    attack, search = int(0.1 * SR), int(SEARCH_MS / 1000 * SR)
    errors = []
    for p in starts[starts < CHECKED_S * SR].astype(int):
        k = int(np.searchsorted(phi, p))
        lo = max(0, k - search)
        corr = signal.correlate(zb[lo:k + search + attack], xb[p:p + attack], mode="valid")
        errors.append((k - (lo + int(np.argmax(corr)))) / SR * 1000)
    worst = max(errors, key=abs)
    check(abs(worst) <= POSITION_TOLERANCE_MS,
          f"position at speed {speed:.4f}: of {len(errors)} attacks in the first {CHECKED_S:.0f} s, the worst plays "
          f"{worst:+.1f} ms before where phi puts it (at most {POSITION_TOLERANCE_MS} ms either way)")
    tail = z[ramp + SR // 4:ramp + SR // 4 + SR, 0]
    if len(tail) != SR:
        check(False, f"pitch at speed {speed:.4f}: {len(tail)} frames after the ramp, where {SR} were expected")
        return worst, None
    peak_hz = float(np.fft.rfftfreq(len(tail), 1 / SR)[int(np.argmax(np.abs(np.fft.rfft(tail))))])
    check(abs(peak_hz - TONE_HZ) <= PITCH_TOLERANCE_HZ,
          f"pitch at speed {speed:.4f}: the steady tone after the ramp is at {peak_hz:.1f} Hz (its own {TONE_HZ:.0f} Hz, "
          f"at most {PITCH_TOLERANCE_HZ} Hz off)")
    return worst, peak_hz


def start_drop(x, z, what, speed):
    w = int(LEVEL_WINDOW_MS / 1000 * SR)
    ref = float(np.sqrt(np.mean(x[:int(LEVEL_CHECKED_S * SR), 0] ** 2)))
    drops = [20 * np.log10(max(float(np.sqrt(np.mean(z[i:i + w, 0] ** 2))), 1e-9) / ref)
             for i in range(0, int(LEVEL_CHECKED_S * SR), w)]
    worst = int(np.argmin(drops))
    msg = (f"{what} at speed {speed:.4f}: the quietest {LEVEL_WINDOW_MS:.0f} ms window of the first "
           f"{LEVEL_CHECKED_S * 1000:.0f} ms, at {worst * LEVEL_WINDOW_MS:.0f} ms, is {drops[worst]:+.1f} dB from the "
           f"input (at least -{LEVEL_DROP_DB} dB)")
    return drops, drops[worst] >= -LEVEL_DROP_DB, msg


def level(speed, rng):
    x = stereo(0.1 * rng.standard_normal(int(DURATION_S * SR)))
    z, _ = engine.esticar_saida(x, speed, ramp_samples(speed))
    drops, ok, msg = start_drop(x, z, "level", speed)
    check(ok, msg)
    return min(drops)


def incoming_level(speed, rng):
    x = stereo(0.1 * rng.standard_normal(int(DURATION_S * SR)))
    n_sob, n_ramp = int(INCOMING_OVERLAP_S * SR), int(INCOMING_RAMP_S * SR)
    z, _ = engine.esticar(x, speed, n_sob, n_ramp, int(speed * n_sob + n_ramp * (1 + speed) / 2))
    drops, ok, msg = start_drop(x, z, "incoming level", speed)
    cut = int(INCOMING_SILENT_MS / LEVEL_WINDOW_MS)
    symptom = min(drops[:cut]) < -LEVEL_DROP_DB and min(drops[cut:]) >= -INCOMING_GAP_DB
    if ok:
        check(False, f"{msg}: passed, but it is a known failure (#{INCOMING_ISSUE}): if the fix is on purpose, the "
                     "case leaves the known failures in the same PR")
    elif symptom:
        print(f"known #{INCOMING_ISSUE} {msg}")
    else:
        check(False, f"{msg}, and from {INCOMING_SILENT_MS:.0f} ms on the quietest window is {min(drops[cut:]):+.1f} dB "
                     f"(a gap is more than {INCOMING_GAP_DB:.0f} dB down): more than the silent start of #{INCOMING_ISSUE}")
    return min(drops)


def short(ms, rng):
    x = stereo(0.1 * rng.standard_normal(int(ms / 1000 * SR)))
    z, phi = engine.esticar_saida(x, SHORT_SPEED, len(x) // 2)
    whole = len(phi) > 0 and len(x) - 5 <= phi[-1] < len(x)
    check(whole and z.shape == (len(phi), 2) and bool(np.isfinite(z).all()),
          f"short input of {ms:.0f} ms ({len(x)} frames): output {z.shape} for {len(phi)} positions, the last at "
          f"{phi[-1] if len(phi) else float('nan'):.1f}")


def main():
    positions, pitches, levels = [], [], []
    for speed in SPEEDS:
        worst, hz = position(speed, np.random.default_rng(7))
        positions.append(f"{worst:+.1f} ms")
        pitches.append("short tail" if hz is None else f"{hz:.1f} Hz")
        levels.append(f"{level(speed, np.random.default_rng(11)):+.1f} dB")
    for ms in SHORT_MS:
        short(ms, np.random.default_rng(13))
    incoming = [f"{incoming_level(speed, np.random.default_rng(17)):+.1f} dB" for speed in INCOMING_SPEEDS]
    print(f"-- summary: {'FAIL' if failures else 'ok'} at speeds {' / '.join(f'{s:.2f}' for s in SPEEDS)}: position "
          f"{' / '.join(positions)}, pitch {' / '.join(pitches)}, level {' / '.join(levels)}; known failure "
          f"#{INCOMING_ISSUE}, the incoming level at {' / '.join(f'{s:.2f}' for s in INCOMING_SPEEDS)}: "
          f"{' / '.join(incoming)}")
    print(f"{len(failures)} failure(s)" if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
