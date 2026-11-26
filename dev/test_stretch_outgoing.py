r"""Checks esticar_saida (engine.py), the outgoing track resampled to a new speed before an on-beat fade-out with both
tracks stretched, on its own, through the real Rubber Band:

  - position: under a strong steady tone (as in the tone pair of dev/testa_passagem.py, #197), every attack in the
    output sits where the returned position (phi) says it came from in the input, to within POSITION_TOLERANCE_MS;
  - level: on broadband noise, no POSITION_WINDOW_MS window at the start of the output drops more than
    LEVEL_DROP_DB below the input, so the switch from what already played into the stretched audio has no gap;
  - short: an input shorter than the warm-up and the crossfade (SHORT_MS) comes back whole, one output frame per
    position.

Each runs at a speed below and one above 1 (A slowed down and sped up, as in the dois and dois-106 pairs).

    python dev/test_stretch_outgoing.py

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
DURATION_S = 12.0
TONE_HZ = 1201.0
ATTACK_BAND = (200.0, 500.0)
ATTACK_EVERY_S = 0.6
CHECKED_S = 4.0
POSITION_TOLERANCE_MS = 2.0
SEARCH_MS = 120.0
POSITION_WINDOW_MS = 5.0
LEVEL_CHECKED_S = 0.3
LEVEL_DROP_DB = 3.0
SHORT_MS = (30.0, 75.0)
SHORT_SPEED = 1.01

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
    z, phi = engine.esticar_saida(x, speed, ramp_samples(speed))
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


def level(speed, rng):
    x = stereo(0.1 * rng.standard_normal(int(DURATION_S * SR)))
    z, _ = engine.esticar_saida(x, speed, ramp_samples(speed))
    w = int(POSITION_WINDOW_MS / 1000 * SR)
    ref = float(np.sqrt(np.mean(x[:int(LEVEL_CHECKED_S * SR), 0] ** 2)))
    drops = [20 * np.log10(max(float(np.sqrt(np.mean(z[i:i + w, 0] ** 2))), 1e-9) / ref)
             for i in range(0, int(LEVEL_CHECKED_S * SR), w)]
    worst = int(np.argmin(drops))
    check(drops[worst] >= -LEVEL_DROP_DB,
          f"level at speed {speed:.4f}: the quietest {POSITION_WINDOW_MS:.0f} ms window of the first "
          f"{LEVEL_CHECKED_S * 1000:.0f} ms, at {worst * POSITION_WINDOW_MS:.0f} ms, is {drops[worst]:+.1f} dB from the "
          f"input (at least -{LEVEL_DROP_DB} dB)")


def short(ms, rng):
    x = stereo(0.1 * rng.standard_normal(int(ms / 1000 * SR)))
    try:
        z, phi = engine.esticar_saida(x, SHORT_SPEED, len(x) // 2)
    except ValueError as ex:
        check(False, f"short input of {ms:.0f} ms: {ex}")
        return
    check(z.shape == (len(phi), 2) and bool(np.isfinite(z).all()),
          f"short input of {ms:.0f} ms: output {z.shape} for {len(phi)} positions")


def main():
    for speed in SPEEDS:
        position(speed, np.random.default_rng(7))
        level(speed, np.random.default_rng(11))
    for ms in SHORT_MS:
        short(ms, np.random.default_rng(13))
    print(f"{len(failures)} failure(s)" if failures else "all passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
