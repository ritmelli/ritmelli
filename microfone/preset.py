"""O preset do filtro: o efeito do fx.py virado na lista de etapas que o micfx.dll roda (microfone/apo/voz.h).

O fx.py segue sendo a unica definicao de cada efeito. Daqui se le o Efeito montado (antes, a placa da pedalboard,
depois, ganho, nivelador e o extra) e cada etapa vira um registro do voz.h com os parametros e os coeficientes ja
projetados na taxa do microfone: o scipy projeta aqui, o filtro so roda. Etapa sem par no voz.h levanta NaoPortado,
e o efeito segue pelo caminho do app (a voz vai ao app e volta pelo anel, com o atraso de antes).

O formato (little-endian) e o do voz.h: cabecalho de 80 bytes (magia, versao, taxa, ganho, nivelar, quantas etapas,
quantas do extra, gerador e os 5 numeros do nivelador) e, por etapa, tipo, quantos doubles e os doubles.
"""
import math
import struct
import threading

import numpy as np
import pedalboard as pb
from scipy import signal

import fx

MAGIA = 0x315A5652  # "RVZ1"
VERSAO = 1
CABECALHO = struct.Struct("<IIddIIII5d")
assert CABECALHO.size == 80

(T_SOS, T_FIR, T_GANHO, T_PITCH, T_RINGMOD, T_PORTAO, T_DECIMA, T_AGC, T_MULTIBANDA, T_COMPRESSOR, T_LIMITER,
 T_DISTORCAO, T_BITCRUSH, T_DELAY, T_CHORUS, T_PHASER, T_FREEVERB, T_RADIO) = range(1, 19)
T_TROCA = 21  # TrocaDeVoz (#77); o 19 e o 20 sao da FDN (#74) e da distorcao com oversampling (#75)
G_NENHUM, G_RADIO = 0, 1
NYQ = 0.49  # filtro com corte acima disso da taxa nao cabe nela: a etapa sai (corte de agudo) ou o efeito fica no app

# o que o fx.py escreve direto no codigo das etapas de blocos (o dev/testa_voz.py pega se um lado mudar sem o outro)
PORTAO_APRENDE_S = 0.3   # PortaoRuido: os primeiros 30 blocos aprendem o fundo
PORTAO_SOBE_DB_S = 3.0   # PortaoRuido: o fundo sobe 0,03 dB por bloco
PORTAO_ABRE_S = 0.001    # PortaoRuido: abre em 1 ms
AGC_COEF = (0.1, 0.02, 0.005)  # AGC: media do nivel, desce, sobe (por bloco de 10 ms)
RADIO_ESTALO = (0.03, 0.002)   # CambioRadio: chance de estalo por bloco e duracao (96 amostras a 48 kHz)


class NaoPortado(Exception):
    """O efeito tem etapa que o filtro nao roda: ele segue pelo app."""


def _sos_rows(sos):
    """As secoes do scipy (b0 b1 b2 a0 a1 a2, a0 = 1) no formato do voz.h: quantas e b0 b1 b2 a1 a2 de cada."""
    sos = np.atleast_2d(np.asarray(sos, float))
    out = [float(len(sos))]
    for s in sos:
        out += [s[0] / s[3], s[1] / s[3], s[2] / s[3], s[4] / s[3], s[5] / s[3]]
    return out


def _butter(ordem, corte, tipo, taxa):
    return signal.butter(ordem, corte, btype=tipo, fs=taxa, output="sos")


def _rbj(tipo, f, g_db, q, taxa):
    """Biquad do livro de receitas (RBJ), o mesmo da pedalboard (conferido em dev/testa_voz.py)."""
    a = 10 ** (g_db / 40)
    w = 2 * math.pi * f / taxa
    c = math.cos(w)
    if tipo == "pico":
        al = math.sin(w) / (2 * q)
        b, d = [1 + al * a, -2 * c, 1 - al * a], [1 + al / a, -2 * c, 1 - al / a]
    else:
        be = math.sin(w) * math.sqrt(a) / q
        if tipo == "grave":
            b = [a * ((a + 1) - (a - 1) * c + be), 2 * a * ((a - 1) - (a + 1) * c), a * ((a + 1) - (a - 1) * c - be)]
            d = [(a + 1) + (a - 1) * c + be, -2 * ((a - 1) + (a + 1) * c), (a + 1) + (a - 1) * c - be]
        else:
            b = [a * ((a + 1) + (a - 1) * c + be), -2 * a * ((a - 1) + (a + 1) * c), a * ((a + 1) + (a - 1) * c - be)]
            d = [(a + 1) - (a - 1) * c + be, 2 * ((a - 1) - (a + 1) * c), (a + 1) - (a - 1) * c - be]
    return np.array([b + d])


def _plugin(p, taxa):
    """Uma etapa da pedalboard: [(tipo, doubles)]; lista vazia = a etapa nao faz nada nessa taxa."""
    if isinstance(p, pb.Compressor):
        return [(T_COMPRESSOR, [p.threshold_db, p.ratio, p.attack_ms, p.release_ms])]
    if isinstance(p, pb.Limiter):
        return [(T_LIMITER, [p.threshold_db, p.release_ms])]
    if isinstance(p, pb.Gain):
        return [(T_GANHO, [10 ** (p.gain_db / 20)])]
    if isinstance(p, pb.Distortion):
        return [(T_DISTORCAO, [p.drive_db])]
    if isinstance(p, pb.Bitcrush):
        return [(T_BITCRUSH, [p.bit_depth])]
    if isinstance(p, pb.Delay):
        return [(T_DELAY, [p.delay_seconds, p.feedback, p.mix])]
    if isinstance(p, pb.Chorus):
        return [(T_CHORUS, [p.rate_hz, p.depth, p.centre_delay_ms, p.feedback, p.mix])]
    if isinstance(p, pb.Phaser):
        return [(T_PHASER, [p.rate_hz, p.depth, p.centre_frequency_hz, p.feedback, p.mix])]
    if isinstance(p, pb.Reverb):
        if p.freeze_mode:
            raise NaoPortado("Reverb congelado")
        return [(T_FREEVERB, [p.room_size, p.damping, p.wet_level, p.dry_level, p.width])]
    for cls, tipo in ((pb.PeakFilter, "pico"), (pb.LowShelfFilter, "grave"), (pb.HighShelfFilter, "agudo")):
        if isinstance(p, cls):
            if p.cutoff_frequency_hz >= NYQ * taxa:
                return []
            return [(T_SOS, _sos_rows(_rbj(tipo, p.cutoff_frequency_hz, p.gain_db, p.q, taxa)))]
    if isinstance(p, pb.LowpassFilter):  # primeira ordem, transformada bilinear
        if p.cutoff_frequency_hz >= NYQ * taxa:
            return []
        n = math.tan(math.pi * p.cutoff_frequency_hz / taxa)
        return [(T_SOS, _sos_rows([[n / (n + 1), n / (n + 1), 0.0, 1.0, (n - 1) / (n + 1), 0.0]]))]
    raise NaoPortado(type(p).__name__)


def _radio(r):
    c = fx.CambioRadio
    return [r.LIGA, r.DESLIGA, c.SILENCIO * 0.01, r.CHIADO, r.ESTALO, r.BIP, r.RABO, RADIO_ESTALO[0],
            RADIO_ESTALO[1], 3.0]


def _etapa(f, taxa):
    """Uma etapa do fx.py (antes/depois/extra): [(tipo, doubles)]."""
    placa = getattr(f, "placa", None)
    if isinstance(placa, pb.Pedalboard):  # lista da pedalboard dentro do antes/depois (Efeito._etapa)
        return [r for p in placa for r in _plugin(p, taxa)]
    if getattr(f, "__func__", None) is fx.CambioRadio.detecta:
        return [(T_RADIO, _radio(f.__self__))]
    k = taxa / fx.SR
    if isinstance(f, fx.PitchShifter):
        return [(T_PITCH, [f.i, f.w * k, f.x * k])]
    if isinstance(f, fx.TrocaDeVoz):  # o voz.h refaz a troca_geometria na taxa; o passa-baixa do detector vem daqui
        d = max(1, int(taxa // 12000))
        sos = f.sos if taxa == fx.SR else _butter(4, min(fx.TrocaDeVoz.CORTE, 0.4 * taxa / d), "low", taxa)
        return [(T_TROCA, [f.beta, f.formante, f.fmin, f.fmax, f.grao, f.limiar, f.porta, f.surdo_s, f.passo_s,
                           float(d), *_sos_rows(sos)])]
    if isinstance(f, fx.RingMod):
        return [(T_RINGMOD, [f.hz, f.mix])]
    if isinstance(f, fx.PortaoRuido):
        c = fx.PortaoRuido
        return [(T_PORTAO, [f.piso, c.ABRE_FUNDO, c.FECHA, c.SEM_VOZ, c.ABRE_VOZ, c.SEGURA * 0.01,
                            c.FECHAR_EM * 0.01, c.MEMORIA_VOZ, PORTAO_APRENDE_S, PORTAO_SOBE_DB_S, PORTAO_ABRE_S])]
    if isinstance(f, fx.PassaBaixa):
        if f.corte >= NYQ * taxa:
            return []
        return [(T_SOS, _sos_rows(f.sos if taxa == fx.SR else _butter(f.ordem, f.corte, "low", taxa)))]
    if isinstance(f, fx.PassaAlta):
        if f.corte >= NYQ * taxa:
            raise NaoPortado("passa-alta acima da taxa")
        return [(T_SOS, _sos_rows(f.sos if taxa == fx.SR else _butter(f.ordem, f.corte, "high", taxa)))]
    if isinstance(f, fx.FiltroBanda):
        hi = min(f.hi, NYQ * taxa)
        if f.lo >= hi:
            raise NaoPortado("faixa acima da taxa")
        sos = f.sos if taxa == fx.SR else _butter(f.ordem, [f.lo, hi], "band", taxa)
        return [(T_SOS, _sos_rows(sos))]
    if isinstance(f, fx.Decimador):
        return [(T_DECIMA, [f.f * k])]
    if isinstance(f, fx.AGC):
        return [(T_AGC, [f.alvo, f.porta, f.teto, *AGC_COEF])]
    if isinstance(f, fx.Multibanda):
        dados = [float(len(f.cortes))]
        for c, (lo, hi) in zip(f.cortes, f.pares):
            if c >= NYQ * taxa:
                raise NaoPortado("corte da multibanda acima da taxa")
            if taxa != fx.SR:
                lo = np.vstack([_butter(2, c, "low", taxa)] * 2)
                hi = np.vstack([_butter(2, c, "high", taxa)] * 2)
            dados += _sos_rows(lo) + _sos_rows(hi)
        for cb in f.comps:
            dados += [cb.lim, cb.razao, -10 / math.log(cb.a), -10 / math.log(cb.s), cb.ganho]
        return [(T_MULTIBANDA, dados)]
    if isinstance(f, fx.QuestComoSM58):
        h = f.h if taxa == fx.SR else _sm58(len(f.h), taxa)
        return [(T_FIR, [float(len(h)), *h])]
    raise NaoPortado(getattr(f, "__qualname__", type(f).__name__))


def _sm58(taps, taxa):
    """A curva do QuestComoSM58 projetada na taxa (o fx.py projeta a 48 kHz)."""
    f = np.linspace(0, taxa / 2, 961)
    pts = 50 * 2 ** (np.arange(len(fx.QuestComoSM58.CURVA)) / 6)
    db = np.interp(np.log(np.maximum(f, 1)), np.log(pts), fx.QuestComoSM58.CURVA)
    return signal.minimum_phase(signal.firwin2(taps, f / (taxa / 2), 10 ** (db / 20)), method="homomorphic",
                                half=False)


def compila(e, taxa, extra=True):
    """O preset (bytes) do Efeito e na taxa do microfone. extra=False deixa o som do canal (o chiado do radio) de fora,
    para conferir o resto contra o fx.py amostra a amostra. NaoPortado se alguma etapa nao tem par no filtro."""
    taxa = float(taxa)
    etapas = [r for f in e.antes for r in _etapa(f, taxa)]
    if e.placa is not None:
        etapas += [r for p in e.placa for r in _plugin(p, taxa)]
    etapas += [r for f in e.depois for r in _etapa(f, taxa)]
    gerador, ext = G_NENHUM, []
    if e.extra is not None and extra:
        ger, passos = e.extra
        radio = getattr(ger, "__self__", None)
        if getattr(ger, "__func__", None) is not fx.CambioRadio.som or not any(
                getattr(f, "__self__", None) is radio for f in e.antes):
            raise NaoPortado("gerador do extra")
        gerador = G_RADIO
        ext = [r for f in passos for r in _etapa(f, taxa)]
    if len(etapas) > 32 or len(ext) > 32:
        raise NaoPortado("etapas demais")
    corpo = b"".join(struct.pack(f"<II{len(d)}d", t, len(d), *map(float, d)) for t, d in etapas + ext)
    cab = CABECALHO.pack(MAGIA, VERSAO, taxa, float(e.ganho), 1 if e.nivelar else 0, len(etapas), len(ext), gerador,
                         fx.Efeito.FALA, fx.Efeito.MEMORIA, fx.Efeito.PASSO, fx.Efeito.TETO, fx.Audibilidade.EXPOENTE)
    return cab + corpo


# os presets ja projetados, por (efeito, taxa): o projeto leva ate ~70 ms (o FIR do Locutor fora dos 48 kHz), entao a
# thread da saida para o jogo so le daqui (pede) e nunca projeta
_prontos = {}
_projetando = set()
_trava = threading.Lock()
PENDENTE = object()


def _projeta(efeito_id, taxa):
    try:
        e = fx.criar(efeito_id)
        return None if e is None else compila(e, taxa)
    except Exception:  # noqa: BLE001 - NaoPortado, efeito que sumiu do catalogo, scipy: o efeito segue pelo app
        return None


def preset(efeito_id, taxa):
    """O preset do efeito do catalogo na taxa, ou None: sem efeito, ou efeito que segue pelo app. Projeta na hora se
    ainda nao tem (fora da thread de audio: o set_effect do motor, os testes)."""
    chave = (efeito_id, int(taxa))
    with _trava:
        if chave in _prontos:
            return _prontos[chave]
    dados = _projeta(*chave)
    with _trava:
        _prontos[chave] = dados
        _projetando.discard(chave)
    return dados


def pede(efeito_id, taxa):
    """Sem esperar, para a thread de audio: o preset pronto (bytes ou None) ou PENDENTE, e ai o projeto comeca numa
    thread a parte (uma por chave); a proxima volta acha pronto."""
    chave = (efeito_id, int(taxa))
    with _trava:
        if chave in _prontos:
            return _prontos[chave]
        if chave in _projetando:
            return PENDENTE
        _projetando.add(chave)
    threading.Thread(target=preset, args=chave, daemon=True, name="vitrola-preset").start()
    return PENDENTE
