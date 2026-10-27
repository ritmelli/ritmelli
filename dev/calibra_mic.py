"""Calibra um microfone para soar como outro: grava os dois AO MESMO TEMPO lendo o mesmo
texto (mesma fala, sem diferenca de leitura entre tomadas), alinha pelo envelope e tira a
curva de casamento (espectro medio do alvo menos o do microfone, em terco de oitava). Sai
a tupla por sexto de oitava a partir de 50 Hz, no formato do fx.QuestComoSM58.CURVA.

Foi assim que nasceu a curva do Quest como SM58 (17/10): Quest na cabeca, boca colada no
SM58. As gravacoes ficam em logs/efeitos/ (fora do git: e a voz do usuario).

    python dev/calibra_mic.py                       # grava (bipe na saida padrao) e calcula
    python dev/calibra_mic.py --nome quest2 --so-calcula   # recalcula de gravacoes ja feitas
    python dev/calibra_mic.py --alvo "IN 1 (BEHRINGER UMC 404HD 192k)" --mic "Microfone (Virtual Desktop Audio)"
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aproximar as ap  # noqa: E402
import efeitos as ef  # noqa: E402

SR, B = 48000, 480


def gravar(alvo, mic, nome):
    import sounddevice as sd

    def achar(n):
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == n and "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]:
                return i, d["max_input_channels"]
        raise SystemExit(f"Não achei o dispositivo de entrada \"{n}\".")

    def bipe(n):
        t = np.arange(int(0.15 * SR)) / SR
        b = 0.2 * np.sin(2 * np.pi * 880 * t) * np.minimum(1, np.minimum(t, t[-1] - t) / 0.01)
        sd.play(np.concatenate([np.concatenate([b, np.zeros(int(0.1 * SR))]) for _ in range(n)]).astype(np.float32), SR)
        sd.wait()

    # streams abertos na thread principal: WASAPI em thread sem COM falha (-9999)
    buf, ss = {"alvo": [], "mic": []}, []
    for k, n in (("alvo", alvo), ("mic", mic)):
        i, ch = achar(n)
        ss.append(sd.InputStream(samplerate=SR, channels=ch, device=i, dtype="float32", blocksize=B,
                                 callback=lambda d, fr, t, st, k=k: buf[k].append(d.copy())))
    bipe(1)
    [s.start() for s in ss]
    t0, falou, ultimo = time.time(), False, time.time()
    while time.time() - t0 < 150:  # ate 60 s para comecar; para 3 s depois do fim da fala
        time.sleep(0.05)
        nivel = max((float(np.sqrt(np.mean(v[-1] ** 2))) for v in buf.values() if v), default=0)
        if nivel > 10 ** (-45 / 20):
            falou, ultimo = True, time.time()
        if (falou and time.time() - ultimo > 3) or (not falou and time.time() - t0 > 60):
            break
    [s.stop() for s in ss]
    bipe(2)
    if not falou:
        raise SystemExit("Não ouvi fala em nenhum dos dois microfones.")
    for k, v in buf.items():
        ef.gravar_wav(ef.OUT / f"_calib_{nome}_{k}.wav", np.concatenate(v).mean(axis=1))


def alinhar(a, b, e=240):
    """Atraso de b em relacao a a pelo envelope (5 ms): a forma de onda de dois microfones
    diferentes quase nao correlaciona (0,1 no Quest x SM58), o envelope sim (0,86)."""
    env = lambda x: np.log10(np.sqrt(np.mean(x[: len(x) // e * e].reshape(-1, e) ** 2, axis=1)) + 1e-6)
    ea, eb = env(a), env(b)
    n = min(len(ea), len(eb))
    ea, eb = ea[:n] - ea[:n].mean(), eb[:n] - eb[:n].mean()
    lag = (int(np.argmax(signal.correlate(eb, ea, "full"))) - (n - 1)) * e
    a, b = (a[: len(a) - lag], b[lag:]) if lag >= 0 else (a[-lag:], b)
    m = min(len(a), len(b)) // B * B
    return a[:m], b[:m], lag


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--alvo", default="IN 1 (BEHRINGER UMC 404HD 192k)", help="o som que se quer (SM58 colado)")
    p.add_argument("--mic", default="Microfone (Virtual Desktop Audio)", help="o microfone que vai ser corrigido")
    p.add_argument("--nome", default="mic")
    p.add_argument("--so-calcula", action="store_true", help="usa as gravacoes _calib_<nome>_*.wav ja feitas")
    a = p.parse_args()
    if not a.so_calcula:
        gravar(a.alvo, a.mic, a.nome)
    alvo, mic, lag = alinhar(ef.ler_wav(ef.OUT / f"_calib_{a.nome}_alvo.wav"), ef.ler_wav(ef.OUT / f"_calib_{a.nome}_mic.wav"))
    curva = ap.curva_de_casamento(alvo, mic)
    pts = 50 * 2 ** (np.arange(52) / 6)
    vals = np.interp(pts, ap.F, curva)
    corrigido = ap.stream(ap.Aproximar(curva, excesso=0.0), mic)
    F = ap.F
    for nome, x in (("sem a curva", mic), ("com a curva", corrigido)):
        d = ap.suaviza(ap.ltas(x)) - ap.suaviza(ap.ltas(alvo))
        d -= d[(F >= 300) & (F <= 3000)].mean()
        m = (F >= 80) & (F <= 12000)
        print(f"{nome}: timbre a {np.sqrt(np.mean(d[m] ** 2)):.1f} dB do alvo (pior {d[m][np.argmax(abs(d[m]))]:+.1f} dB em {F[m][np.argmax(abs(d[m]))]:.0f} Hz)")
    print(f"atraso do microfone em relação ao alvo: {lag / SR * 1000:.0f} ms")
    print("CURVA = (" + ", ".join(f"{v:.1f}" for v in vals) + ")")


if __name__ == "__main__":
    main()
