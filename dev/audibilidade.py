"""Volume como o ouvido soma: energia por banda critica (escala Bark) elevada a 0,23 e
somada (lei de Stevens por banda, sem limiar nem mascaramento: aproximacao do Zwicker).
A ponderacao K (LUFS) mede energia e nao ve que som de faixa estreita soa mais baixo que
um de faixa larga com a mesma energia. Diz quantos dB cada efeito soa abaixo/acima da
voz crua, com a fala do TTS e com ela 6 semitons abaixo (perto de voz masculina).

    python dev/audibilidade.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import efeitos as ef  # noqa: E402
import fx  # noqa: E402

SR, B, N = fx.SR, 480, 2048
f = np.fft.rfftfreq(N, 1 / SR)
bark = 13 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500) ** 2)
BANDAS = [(bark >= z) & (bark < z + 1) & (f >= 50) & (f <= 15000) for z in range(25)]


def sones(x, mascara_fala):
    """Audibilidade media dos quadros de fala (unidade relativa)."""
    w = np.hanning(N)
    tot = []
    for i in range(0, len(x) - N, N // 2):
        if not mascara_fala[min(i // B, len(mascara_fala) - 1)]:
            continue
        p = np.abs(np.fft.rfft(x[i:i + N] * w)) ** 2
        tot.append(sum((p[m].sum() + 1e-12) ** 0.23 for m in BANDAS if m.any()))
    return float(np.mean(tot))


def diferenca_db(x, y, fala):
    # N cresce com g^0,46 (potencia g^2 elevada a 0,23): converte a razao em dB
    return 20 * np.log10((sones(y, fala) / sones(x, fala)) ** (1 / 0.46))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    voz = ef.ler_wav(ef.OUT / "_original.wav")
    voz = voz[:len(voz) // B * B]
    grave, _ = ef.stream(fx.Efeito(antes=[fx.PitchShifter(-6, w=2048, x=1024)]), voz)
    for nome, x in (("voz do TTS", voz), ("6 semitons abaixo", grave)):
        fala = np.sqrt(np.mean(x[:len(x) // B * B].reshape(-1, B) ** 2, axis=1)) > 10 ** (-40 / 20)
        fala[: SR // B] = False  # o nivelador assenta no primeiro segundo
        linha = []
        for _, eid, *_ in fx.CATALOGO + fx.MODOS:
            y, _ = ef.stream(fx.criar(eid), x)
            linha.append(f"{eid} {diferenca_db(x, y, fala):+.1f}")
        print(f"{nome}: " + " | ".join(linha))


if __name__ == "__main__":
    main()
