r"""A banca das passagens: o motor de verdade (engine.py), sem aparelho de som, passando de um disco ao outro em pares
sinteticos, do fim de A ao comeco de B, como o servidor faz. O _plano_batida e o _plano_dois medem e esticam o audio no
meio da decisao, entao a banca nao chama nenhum dos dois: grava cada par como WAV numa pasta temporaria, para os
leitores que o Engine.load e o Engine.preparar abrem com o ffmpeg, e avanca o _mixa um bloco por vez. Ate a posicao de
preparo, consome so os blocos que o leitor ja entregou; depois de chamar o preparar, mantem a posicao ate o planejador
publicar a decisao (ou estourar o prazo): sem isso, o resultado dependeria da velocidade da maquina. Falta de plano, de
virada ou de bloco do leitor dentro do prazo e falha.

Os ataques sao estalos de ruido com o mesmo jeito nos dois lados (subida de 1 ms, queda de 30 ms), os de A de 200 a
500 Hz e os de B de 3 a 6 kHz: o detector do dev/bumbo_mede.py (o mesmo do dev/bumbo.py, marcando no pico, que o
pre-eco da Rubber Band nao adianta) acha cada um na faixa dele, no que o _mixa devolve, e o vies dele em cada faixa sai
dos proprios WAV. Por baixo dos ataques, tons fixos fora das duas faixas, para o nivel do fim e do comeco ficar firme.
Os pares:
  - seco: A corta 20 ms antes da batida que viria; B entra no tempo, a primeira batida dela no ultimo ataque de A (o
    golpe final), esticada no andamento de A (a 3%);
  - fade: A cai 6 dB num ataque e some em 7 s; B, a 2,5% de A, entra esticada no andamento de A, na batida da queda;
  - dois: o mesmo fade, com B a 6% de A: A muda de andamento devagar antes e B estica o resto;
  - meio: A a 70 BPM e B a 140, com um estalo forte e um fraco (12 dB abaixo): o forte cai na batida de A, o fraco no
    meio dela;
  - recusada: A a 90 e B a 110 BPM, longe demais para alinhar: a passagem e so de volume, no comeco da queda.
Cada par registra as posicoes dos ataques, do corte ou da queda, o ramo esperado e a janela da virada calculada delas
(onde B tem de comecar para a primeira batida dela cair no ataque de A esperado), sem tomar o _virar_em do motor como
resposta. A virada medida e a posicao de A no comeco do bloco em que o _mixa virou, e tem de cair a ate FOLGA_VIRADA da
janela. No par recusado, o motivo tem de ser o andamento, e no audio B so entra depois da virada e A cai. Nos pares
planejados, as primeiras 4 batidas de B tem de ter um ataque forte cada (nem um a mais, nem um a menos), no tempo da
regua de A (a grade dos ataques de A na saida, nos REGUA_S antes da virada), cada um a ate ALINHA dela; e o controle
negativo: o mesmo detector, com a mesma regua e a mesma amostra da virada, no sinal da faixa de B deslocado meio
periodo da regua, tem de dar contratempo.

    python dev/testa_passagem.py [--codigo <pasta>] [--par seco ...] [-v]

--codigo: o motor (engine.py, batida.py e o resto do app) de outra pasta, como um worktree da base: a banca e a mesma, e
so o motor muda. Assim um PR que mexe na passagem roda a banca igual no motor dele e no da base:

    git worktree add --detach ..\base origin/main
    python dev\testa_passagem.py                    o motor deste checkout
    python dev\testa_passagem.py --codigo ..\base   o da base

Do motor, a banca usa o Engine(mic, monitor), o active, o vol, o volume_auto, o load, o preparar, o _mixa(BLOCK), o pos,
o virou, o _virar_em, o _q, o _gen e o _eof_gen (para esperar o leitor), o _cancela_passagem e o _deck (para parar os
leitores no fim), o pastas.LOGS (trocado pela pasta temporaria) e o log da decisao no stderr ("transition: on beat:"
com "hard ending" ou "apart: the outgoing one at", e "transition: beats not aligned:"). Quem muda um deles muda a banca
junto, no mesmo PR.

-v: o log do motor de cada par. Sai 1 se algum par falhar.
"""
import argparse
import contextlib
import io
import shutil
import sys
import tempfile
import threading
import time
import wave
from collections import namedtuple
from pathlib import Path

import numpy as np

DEV = Path(__file__).resolve().parent
RAIZ = DEV.parent

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--codigo", type=Path, default=RAIZ, help="a pasta do motor (padrao: este checkout)")
ap.add_argument("--par", nargs="+", help="so estes pares")
ap.add_argument("-v", action="store_true", help="mostra o log do motor")
ARGS = ap.parse_args()
sys.path.insert(0, str(ARGS.codigo.resolve()))
sys.path.insert(1, str(DEV))
import engine as eng  # noqa: E402
from bumbo_mede import ataques, desvio, filtro, veredito  # noqa: E402

SR, BLOCK = eng.SR, eng.BLOCK
FAIXA_A = (200.0, 500.0)    # os estalos de A
FAIXA_B = (3000.0, 6000.0)  # os de B
SOS_A, SOS_B = filtro(FAIXA_A, SR), filtro(FAIXA_B, SR)
TONS_A, TOM_B = (1013.0, 1201.0, 1427.0), 1800.0  # os tons fixos por baixo dos ataques
SOS_TOM_A, SOS_TOM_B = filtro((1150.0, 1250.0), SR), filtro((1750.0, 1850.0), SR)  # um tom de A, e o de B
TAU_B = 0.1        # a primeira batida de B, depois do comeco do som dela (o tom de baixo comeca no 0)
FOLGA_VIRADA = 0.010  # a virada medida pode cair isso fora da janela (um bloco)
ALINHA = 0.020     # cada ataque forte de B nas primeiras batidas, no maximo isso da regua de A
REGUA_S = 4.0      # a regua de A: os ataques dela nos ultimos isso antes da virada
FORTE_DB = 6.0     # ataque de B forte: o pico a ate isso do mais forte (o fraco do par meio fica 12 dB abaixo)
ANTES_S = 35.0     # A comeca a tocar isso antes do corte ou da queda
PREPARO_S = 1.0    # e o preparar entra depois disso tocado
DEPOIS_S = 8.0     # depois da virada, a banca segue isso
PRAZO_LEITOR_S = 10.0
PRAZO_PLANO_S = 90.0

# o par: os andamentos, o fim de A ("seco": corta; "fade": cai 6 dB e some), o ramo esperado e o acento de B (o
# estalo fraco no meio de cada batida, no par meio)
Par = namedtuple("Par", "nome bpm_a bpm_b fim ramo meio")
PARES = [
    Par("seco", 100.0, 103.0, "seco", "seco", False),
    Par("fade", 100.0, 102.5, "fade", "fade", False),
    Par("dois", 100.0, 94.0, "fade", "dois", False),
    Par("meio", 70.0, 140.0, "fade", "fade", True),
    Par("recusada", 90.0, 110.0, "fade", "recusada", False),
]
RECUSA = "transition: beats not aligned: tempos far apart,"  # a recusa por andamento no log do motor (par recusada)
RAMOS = {"seco": "final seco no tempo", "fade": "fade-out no tempo, B esticada",
         "dois": "fade-out no tempo, os dois esticados", "recusada": "so de volume (o plano no tempo recusou)"}


def _lenta(bpm):
    """O periodo (s) do andamento na oitava de 60 a 120 BPM, a do batida.py."""
    while bpm >= 120.0:
        bpm /= 2
    return 60.0 / bpm


def _estalo(rng, faixa):
    """Um ataque: ruido da faixa, com subida de 1 ms e queda de 30 ms (o mesmo jeito nos dois lados, para o pente do
    motor ver os dois do mesmo jeito)."""
    from scipy import signal
    n = int(0.12 * SR)
    x = signal.sosfilt(filtro(faixa, SR), rng.standard_normal(n + SR // 10))[SR // 10:]
    t = np.arange(n) / SR
    env = np.exp(-t / 0.03)
    k = int(0.001 * SR)
    env[:k] *= np.arange(k) / k
    x = x * env
    return 0.4 * x / np.abs(x).max()


def _fundo(n, rms, freqs):
    """O som fixo por baixo dos ataques: tons de 1000 a 1800 Hz (fora das duas faixas e sem ataque), de rms dado. Sob A,
    tres tons sem relacao entre si: com um tom so, a correlacao com que o motor acha o atraso da Rubber Band (o
    esticar_saida) cai num pico do tom, e a que sai toca ~50 ms antes da posicao que o motor da a ela."""
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * f * t + k) for k, f in enumerate(freqs))
    return rms * x / np.sqrt(np.mean(x * x))


def _poe(x, som, t):
    i = int(round(t * SR))
    k = min(len(som), len(x) - i)
    if k > 0:
        x[i:i + k] += som[:k]


def _grava(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


def monta(par, pasta):
    """Grava os WAV do par e devolve o que a banca espera dele: as posicoes dos ataques de A, o corte ou a queda, o
    ataque de A onde a primeira batida de B tem de cair e a janela da virada (posicao de A)."""
    rng = np.random.default_rng(7)
    pa, pb = 60.0 / par.bpm_a, 60.0 / par.bpm_b
    a0 = 0.5
    fixa = {}
    if par.fim == "seco":
        # o corte 20 ms antes da batida seguinte: o fim do som fica entre dois ataques, longe dos dois
        k = int(round((ANTES_S + 20.0) / pa))
        ultimo = a0 + k * pa
        corte = ultimo + pa - 0.02
        dur = corte + 1.0
        ts_a = a0 + np.arange(k + 1) * pa
        nivel = np.where(np.arange(int(dur * SR)) / SR < corte, 1.0, 0.0)
        fixa.update(corte=corte, ultimo=ultimo, alvo=ultimo, inicio=corte - ANTES_S)
    else:
        k = int(round((ANTES_S + 20.0) / pa))
        queda = a0 + k * pa
        some = queda + 7.0  # 6 dB de degrau e 6 dB/s: a -48 dB do normal em 7 s
        dur = some + 0.5
        ts_a = a0 + np.arange(int((some - a0) / pa) + 1) * pa
        t = np.arange(int(dur * SR)) / SR
        db = np.where(t < queda, 0.0, -6.0 - 6.0 * (t - queda))
        nivel = np.where(t < some, 10 ** (db / 20), 0.0)
        fixa.update(queda=queda, alvo=queda, inicio=queda - ANTES_S)
    n = int(dur * SR)
    xa = _fundo(n, 0.14, TONS_A)
    for t in ts_a:
        _poe(xa, _estalo(rng, FAIXA_A), t)
    xa *= nivel
    # B: o tom desde o comeco, os estalos desde TAU_B (no par meio, o fraco no meio de cada batida, 12 dB abaixo)
    dur_b = 75.0  # a volta lenta de B ao andamento dela leva ate o RAMPA_MAX_S do motor (60 s), e tem de caber em B
    nb = int(dur_b * SR)
    xb = _fundo(nb, 0.085, (TOM_B,))
    ts_b = TAU_B + np.arange(int((dur_b - TAU_B - 0.2) / pb)) * pb
    for i, t in enumerate(ts_b):
        _poe(xb, _estalo(rng, FAIXA_B) * (10 ** (-12 / 20) if par.meio and i % 2 else 1.0), t)
    pasta.mkdir(parents=True, exist_ok=True)
    _grava(pasta / "a.wav", xa)
    _grava(pasta / "b.wav", xb)
    # a janela: B comeca TAU_B antes da primeira batida dela, e na sobreposicao toca no andamento de A (na lenta)
    lead = TAU_B * _lenta(par.bpm_a) / _lenta(par.bpm_b)
    if par.ramo == "recusada":
        # a passagem de volume vira no comeco da queda: onde o nivel alisado em meio segundo sai a 3 dB do normal,
        # no degrau ou ate 50 ms antes dele (o alisamento ja pega o degrau e a descida depois)
        janela = (fixa["queda"] - 0.05, fixa["queda"])
    else:
        janela = (fixa["alvo"] - lead - BLOCK / SR, fixa["alvo"] - lead)
    # o vies do detector em cada lado (onde ele marca o ataque, contra onde o ataque foi gravado), medido nos proprios
    # WAV: a regua e os ataques de B se comparam pelas posicoes gravadas, e nao pelo jeito do detector em cada faixa
    vies = (_vies(xa, ts_a, SOS_A), _vies(xb, ts_b, SOS_B))
    return dict(fixa, ts_a=ts_a, ts_b=ts_b, dur_a=dur, dur_b=dur_b, lead=lead, janela=janela, vies=vies,
                a={"id": f"{par.nome}-a", "title": f"{par.nome} A", "path": str(pasta / "a.wav"), "duration": dur},
                b={"id": f"{par.nome}-b", "title": f"{par.nome} B", "path": str(pasta / "b.wav"), "duration": dur_b})


def _vies(x, ts, sos):
    """A mediana de (onde o detector marca - onde o ataque foi gravado), nos ataques de 5 a 25 s de x."""
    i0, i1 = 5 * SR, 25 * SR
    achou = ataques(x[i0:i1], sos, SR, no_pico=True) + i0 / SR
    perto = ts[(ts > 5.5) & (ts < 24.5)]
    d = np.array([t - perto[np.argmin(np.abs(perto - t))] for t in achou])
    d = d[np.abs(d) < 0.05]
    if len(d) < 8:
        raise Falha(f"o detector achou so {len(d)} ataques nos WAV do par")
    return float(np.median(d))


class Log(io.TextIOBase):
    """O stderr do motor (as threads dele escrevem aqui): guarda as linhas e, com -v, repassa."""

    def __init__(self, repassa):
        self.linhas, self._resto, self._lock, self._repassa = [], "", threading.Lock(), repassa

    def write(self, s):
        with self._lock:
            if self._repassa:
                sys.__stderr__.write(s)
            partes = (self._resto + s).split("\n")
            self._resto = partes.pop()
            self.linhas += partes
        return len(s)

    def acha(self, comeco):
        with self._lock:
            return next((linha for linha in self.linhas if linha.startswith(comeco)), None)


class Falha(Exception):
    pass


def _espera(cond, prazo, o_que):
    t = time.monotonic()
    while not cond():
        if time.monotonic() - t > prazo:
            raise Falha(f"{o_que} em {prazo:.0f} s")
        time.sleep(0.002)


def toca(fx, log):
    """O motor do comeco de A ate DEPOIS_S depois da virada. Volta (a saida mono, o bloco da virada, a posicao de A no
    comeco dele, a linha da decisao no log)."""
    e = eng.Engine("banca", "")
    e.active = {"mic": "banca", "monitor": ""}
    e.vol = 1.0
    e.volume_auto = False  # o ganho automatico mexe so no nivel, e mediria os WAV numa thread a parte
    e.load(fx["a"], start=fx["inicio"])
    preparo = fx["inicio"] + PREPARO_S
    saida, decisao, virada = [], None, None
    limite = int((ANTES_S + DEPOIS_S + 5.0) * SR / BLOCK)
    try:
        for n in range(limite):
            if decisao is None and e.pos >= preparo:
                if not e.preparar(fx["b"], "banca"):
                    raise Falha("o preparar recusou B")
                # a posicao fica parada ate o plano sair: sem isso, a banca mediria a velocidade da maquina
                _espera(lambda: e._virar_em is not None and (log.acha("transition: on beat:")
                                                              or log.acha("transition: beats not aligned:")),
                        PRAZO_PLANO_S, "o planejador nao publicou a decisao")
                decisao = log.acha("transition: on beat:") or log.acha("transition: beats not aligned:")
            _espera(lambda: e._q or e._eof_gen == e._gen, PRAZO_LEITOR_S, "o leitor nao entregou o bloco")
            antes = e.pos
            saida.append(e._mixa(BLOCK).mean(axis=1))
            if virada is None and e.virou is not None:
                virada = (n, antes)
            if virada is not None and (n - virada[0]) * BLOCK >= DEPOIS_S * SR:
                break
        else:
            raise Falha(f"sem virada em {limite} blocos" if decisao else f"sem preparo em {limite} blocos")
    finally:
        e._cancela_passagem(tudo=True)
        e._deck.gen += 1
    return np.concatenate(saida), virada[0] * BLOCK, virada[1], decisao


def _ramo(decisao):
    if decisao.startswith("transition: beats not aligned:"):
        return "recusada"
    if "hard ending" in decisao:
        return "seco"
    return "dois" if "apart: the outgoing one at" in decisao else "fade"


def regua(x, vo, vies):
    """A grade dos ataques de A na saida, nos REGUA_S antes da virada, sem o vies do detector: (fase, periodo), pelo
    ajuste de reta."""
    i0 = vo - int((REGUA_S + 1.0) * SR)  # 1 s a mais: o filtro inventa um ataque na borda do trecho
    ts = ataques(x[i0:vo], SOS_A, SR, no_pico=True) + i0 / SR - vies
    ts = ts[(ts >= vo / SR - REGUA_S) & (ts < vo / SR - 0.05)]
    if len(ts) < 4:
        raise Falha(f"a regua de A tem {len(ts)} ataques nos {REGUA_S:.0f} s antes da virada")
    p0 = float(np.median(np.diff(ts)))
    k = np.round((ts - ts[0]) / p0)
    p, f = np.polyfit(k, ts, 1)
    return float(f % p), float(p)


def ataques_b(yb, vo, ate, vies):
    """Os ataques de B (no sinal da faixa de B) da virada ate ate (s da saida), sem o vies do detector: (fortes,
    fracos), em s da saida."""
    i0 = max(0, vo - SR)
    i1 = min(len(yb), int((ate + 1.0) * SR))
    ts, lv = ataques(yb[i0:i1], SOS_B, SR, com_nivel=True, no_pico=True)
    ts = ts + i0 / SR - vies
    no = (ts >= vo / SR) & (ts <= ate)
    ts, lv = ts[no], lv[no]
    if not len(ts):
        return ts, ts
    forte = lv >= lv.max() - FORTE_DB
    return ts[forte], ts[~forte]


def julga(yb, vo, f, p, lead, vies):
    """O veredito dos ataques fortes de B nas primeiras 4 batidas contra a regua de A: (veredito, desvios, fracos). A
    janela vai ate 3,75 periodos depois da primeira batida de B: pega a quarta dela, e tambem a quarta deslocada meio
    periodo do controle negativo, mas nao a quinta."""
    fortes, fracos = ataques_b(yb, vo, vo / SR + lead + 3.75 * p, vies)
    if len(fortes) != 4:
        raise Falha(f"{len(fortes)} ataques fortes de B nas primeiras 4 batidas depois da virada, e nao 4")
    d = desvio(fortes, f, p)
    return veredito(d, p), d, desvio(fracos, f, p)


def _rms_db(y, de, ate):
    """O nivel (dB) de y entre de e ate (s da saida)."""
    z = y[int(de * SR):int(ate * SR)]
    return 10 * np.log10(np.mean(z * z) + 1e-20)


def confere(par, pasta, verboso):
    from scipy import signal
    fx = monta(par, pasta)
    log = Log(verboso)
    try:
        with contextlib.redirect_stderr(log):
            x, vo, virada_a, decisao = toca(fx, log)
    except Falha as ex:
        ex.log = log
        raise
    ramo = _ramo(decisao)
    msgs = [f"{RAMOS[ramo]}; virada com A em {virada_a:.3f} s (janela {fx['janela'][0]:.3f} a {fx['janela'][1]:.3f})"]
    falhas = []
    if ramo != par.ramo:
        falhas.append(f"o ramo foi {RAMOS[ramo]!r}, e o esperado {RAMOS[par.ramo]!r} ({decisao})")
    elif ramo == "recusada" and not decisao.startswith(RECUSA):
        falhas.append(f"a recusa nao foi por andamento ({decisao})")
    lo, hi = fx["janela"]
    if not lo - FOLGA_VIRADA <= virada_a <= hi + FOLGA_VIRADA:
        fora = virada_a - hi if virada_a > hi else virada_a - lo
        falhas.append(f"a virada caiu {fora * 1000:+.0f} ms fora da janela")
    yb = signal.sosfiltfilt(SOS_B, x)
    if ramo == "recusada":
        # a passagem de volume no audio: B nao soa antes da virada (a faixa dela fica 30 dB abaixo do que soa depois),
        # entra depois dela, e A some. E e cruzada, e nao corte: pelos tons fixos, logo depois da virada A ainda soa e B
        # ja soa, baixa, e sobe
        v = vo / SR
        ta, tb = signal.sosfiltfilt(SOS_TOM_A, x), signal.sosfiltfilt(SOS_TOM_B, x)
        a_fica = _rms_db(ta, v + 0.2, v + 0.6) - _rms_db(ta, v - 0.5, v)
        b_sobe = _rms_db(tb, v + 1.5, v + 2.0) - _rms_db(tb, v + 0.05, v + 0.35)
        b_junto = _rms_db(tb, v + 0.2, v + 0.6) - _rms_db(tb, v + 2.5, v + 3.0)  # B ja soa enquanto A ainda soa
        sobe = _rms_db(yb, v + 1.0, v + 3.0) - _rms_db(yb, v - 3.0, v)
        depois = ataques_b(yb, vo, v + 3.0, fx["vies"][1])
        ya = signal.sosfiltfilt(SOS_A, x)
        cai = _rms_db(ya, v - 1.0, v) - _rms_db(ya, v + 2.5, v + 3.5)
        msgs.append(f"B sobe {sobe:.0f} dB e tem {len(depois[0]) + len(depois[1])} ataques nos 3 s depois da virada; "
                    f"A cai {cai:.0f} dB; sobrepondo, A a {a_fica:+.0f} dB e B a {b_junto:+.0f} dB logo depois, "
                    f"e B {b_sobe:+.0f} dB em 2 s")
        if a_fica < -15:
            falhas.append(f"A ficou a {a_fica:.0f} dB logo depois da virada: corte, e nao cruzamento")
        if b_junto < -25:
            falhas.append(f"B a {b_junto:.0f} dB de 0,2 a 0,6 s depois da virada: sem sobreposicao com A")
        if b_sobe < 6:
            falhas.append(f"B subiu so {b_sobe:.0f} dB na sobreposicao: entrou cheia, e nao cruzada")
        if sobe < 30:
            falhas.append(f"a faixa de B subiu so {sobe:.0f} dB na virada")
        if len(depois[0]) + len(depois[1]) < 4:
            falhas.append("B nao entrou depois da virada")
        if cai < 20:
            falhas.append(f"A caiu so {cai:.0f} dB em 3 s depois da virada")
    elif par.ramo != "recusada":
        f, p = regua(x, vo, fx["vies"][0])
        v, d, fracos = julga(yb, vo, f, p, fx["lead"], fx["vies"][1])
        msgs.append(f"regua de A {60 / p:.2f} BPM; B: " + " ".join(f"{t * 1000:+.0f}" for t in d) + " ms"
                    + f" (vies do detector: A {fx['vies'][0] * 1000:+.0f}, B {fx['vies'][1] * 1000:+.0f} ms)")
        if v != "no tempo":
            falhas.append(f"B ficou {v} ({np.median(d) * 1000:+.0f} ms da regua de A)")
        elif np.abs(d).max() > ALINHA:
            falhas.append(f"B a {np.abs(d).max() * 1000:.0f} ms da regua de A (o maximo e {ALINHA * 1000:.0f})")
        if par.meio:
            vf = veredito(fracos, p) if len(fracos) else "sem ataque fraco"
            msgs.append(f"fracos: {vf}")
            if vf != "contratempo":
                falhas.append(f"os ataques fracos de B ficaram {vf}, e nao no meio da batida de A")
        # o controle negativo: so o sinal de B, meio periodo da regua adiante
        h = int(round(p / 2 * SR))
        vc, dc, _ = julga(np.concatenate([np.zeros(h), yb[:-h]]), vo, f, p, fx["lead"], fx["vies"][1])
        msgs.append(f"controle (B meio periodo adiante): {vc}")
        if vc != "contratempo":
            falhas.append(f"o controle negativo deu {vc!r} ({np.median(dc) * 1000:+.0f} ms), e nao contratempo")
    return falhas, msgs, decisao, log


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    nomes = [p.nome for p in PARES]
    sem = sorted(set(ARGS.par or ()) - set(nomes))
    if sem:
        print(f"par desconhecido: {', '.join(sem)} (os pares: {', '.join(nomes)})")
        return 1
    pares = [p for p in PARES if not ARGS.par or p.nome in ARGS.par]
    print(f"o motor: {Path(eng.__file__).resolve()}")
    tmp = Path(tempfile.mkdtemp(prefix="ritmelli-banca-"))
    # os logs do motor (o registro do fim de cada passagem e a poda dele) vao para a pasta temporaria ate o processo
    # acabar: a thread do planejador grava depois de publicar a decisao, e nunca pode gravar no logs/ de verdade
    eng.pastas.LOGS = tmp / "logs"
    ruins = []
    try:
        for par in pares:
            t0 = time.monotonic()
            try:
                falhas, msgs, decisao, log = confere(par, tmp / par.nome, ARGS.v)
            except Falha as ex:
                falhas, msgs, decisao, log = [str(ex)], [], None, getattr(ex, "log", None)
            dt = time.monotonic() - t0
            print(f"{'ok   ' if not falhas else 'FALHA'} {par.nome} ({dt:.1f} s): " + "; ".join(msgs + falhas),
                  flush=True)
            if falhas:
                ruins.append(par.nome)
                if decisao:
                    print(f"      {decisao}")
                if log is not None and not ARGS.v:
                    for linha in log.linhas:
                        if linha.startswith("transition:"):
                            print(f"      {linha}")
    finally:
        time.sleep(0.2)  # os leitores e a onda fecham o ffmpeg dos WAV
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(pares) - len(ruins)} de {len(pares)} pares passaram"
          + (f"; falharam: {', '.join(ruins)}" if ruins else ""))
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
