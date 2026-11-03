"""Motor de audio do soundboard: arquivo + microfone -> CABLE Input (o VRChat usa
o CABLE Output como microfone, entao a voz segue passando) e so o arquivo -> fone
de quem toca (sem ouvir a propria voz). Sucessor do mic_mix.py de 16/10:
o controle e por metodo (o server.py expoe por HTTP), nao por arquivo PAUSA/VOL."""
import collections
import contextlib
import ctypes
import queue
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from pedalboard import time_stretch
from scipy import signal

import batida
import compasso
import fx
import pastas

SR = 48000
# o modo compartilhado do Windows so aceita a taxa em que o aparelho esta configurado: sem converter, o som da
# VirtualBox, a 44,1 kHz, recusava os 48 kHz e o app nem abria (29/10)
WASAPI = sd.WasapiSettings(auto_convert=True)
BLOCK = 480  # 10 ms
AHEAD = 200  # blocos decodificados adiante (~2 s)
MIC_MAX = 8  # nunca mais de ~80 ms de atraso na voz
DECAY = 0.85  # queda do medidor por bloco de 10 ms
SOBRE_MAX = 8  # sons por cima tocando juntos (o mais antigo sai)
SOBRE_CACHE = 24  # sons por cima decodificados guardados (buzina repetida sai na hora)
SOBRE_CACHE_MB = 512  # e no maximo isso de memoria neles: o posto pela mao pode ser uma musica inteira
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FFMPEG = pastas.ferramenta("ffmpeg") or "ffmpeg"  # o que vem com o app, ou o do PATH
FFPROBE = pastas.ferramenta("ffprobe") or "ffprobe"
CURTO_MAX_S = 15  # ate isso o pad toca por cima da musica em vez de trocar
RAPIDO_MAX_S = 120  # o posto nos Sons rapidos pela mao toca inteiro por cima ate isso (2 minutos)
VIGIA_S = 2.0  # de quanto em quanto o vigia le a lista de aparelhos do Windows
VIGIA_TENTATIVAS = 3  # reaberturas por mudanca da lista (o PortAudio as vezes ainda nao ve o aparelho)
# passagem de uma musica para a proxima da fila (a transicao de DJ)
TRANS_PREP_S = 180         # o servidor prepara a proxima quando falta isso para o fim (o fim deste fica na
                           # memoria, ~70 MB, para medir e planejar com folga: com 60 s, num notebook com o VRChat
                           # aberto, o plano do Boys Will Be Bugs -> Sailor Song ficou pronto depois do comeco da
                           # rampa da que sai, 22/10; num PC mais fraco o atraso nao pode acontecer nunca)
TRANS_MAX_S = 8.0          # a sobreposicao mais longa, a do fade-out
TRANS_SECO_S = 0.25        # final seco: so o tanto que evita o estalo
SILENCIO = 10 ** (-48 / 20)  # bloco abaixo disso (-48 dBFS) e silencio
FADE_DB = 3.0              # o fade-out comeca onde o nivel deixa de ficar a 3 dB do normal do fim
FADE_MIN_S = 1.5           # queda mais curta que isso e final seco
FIM_DB = 20.0              # 20 dB abaixo do normal o fade ja acabou para o ouvido: o rabo dele e cortado
PRONTO_AHEAD = 7500        # a proxima decodifica 75 s adiante: o comeco dela e medido e esticado ate o fim da
                           # volta lenta ao andamento dela (~29 MB, so durante a passagem)
PRONTO_MIN = 1000          # com o fim deste perto, 10 s da proxima ja bastam (o stream lento nao atrasa a virada)
NIVEIS_MAX = PRONTO_AHEAD + 1500  # o nivel dos ultimos 90 s de cada deck: cobre a proxima inteira que esta
                                  # decodificada (com menos, o comeco dela saia do historico e ela entrava 15 s
                                  # depois do comeco, 21/10)
# a batida na passagem: como o DJ, a proxima entra no tempo
BATIDA_S = 20.0            # o trecho de cada lado medido para achar a grade de batidas
BATIDA_MIN_S = 12.0        # com menos que isso de um lado, a passagem segue sem alinhar
FASE_MIN_S = 4.0           # a fase sai do trecho onde as duas soam juntas, de pelo menos isso
FASE_ANTES_S = 4.0         # no que sai, a fase comeca a ser medida isso antes da virada
NOTA_MIN = 3.0             # o pente da fase nesse trecho tem de cair nos ataques pelo menos isso acima da media
TEMPO_MAX = 0.05           # a proxima estica ate 5% para casar o andamento: 3,5% (Despacito -> Paper
                           # Planes) e 4,9% (Without Me -> Overdose) passaram sem se notar, e o Hino do Gremio a 6,4% ja soou
                           # diferente do original (21/10); os 8% de antes eram o curso do pitch do toca-discos
SAI_MAX = 0.02             # o que falta alem disso, ate 2%, a que sai anda devagar antes da sobreposicao: no Macetada
                           # -> Hino do Gremio com 2% nela e 3,9% no hino nao se ouviu diferenca dos originais; 4,9% na
                           # que sai (a NWA) se ouviu (21/10)
SAI_FOLGA_S = 12.0         # a rampa da que sai so vale se ainda falta isso para ela comecar quando o plano comeca
# a rede (compasso.py) quando o batida.py nao firma: com ela, 35% das passagens da prateleira no tempo em vez de 28%
REDE_ATRASO = 0.038        # as batidas da rede caem ~38 ms depois das nossas (mediana de 9853 batidas, 21/10)
REDE_REGULAR = 0.9         # firme pela rede: 90% dos intervalos a 8% da mediana
# depois da sobreposicao, a proxima volta ao andamento dela devagar, como o DJ que empurra o pitch aos poucos
# (8 s era pouco; 3,5% em 8 s soava como a musica freando)
RAMPA_TAXA = 0.001         # em media 0,1% de andamento por segundo (meio cosseno: no meio da volta, 0,16%)
RAMPA_MIN_S = 8.0          # e nunca em menos que isso, nem em mais que RAMPA_MAX_S
RAMPA_MAX_S = 60.0
GRAVE_HZ = 180.0           # a troca de grave: abaixo disso, um disco de cada vez
FOLGA_S = 0.3              # o plano so entra se a virada ainda esta pelo menos isso adiante
ENTRA_SECO_S = 0.005       # no final seco no tempo, a proxima entra cheia (so o que evita o estalo)
FIM_CORTE_S = 1.0          # no final seco no tempo, a proxima entra no maximo isso antes do fim do som (o resto abaixa)
SEGURA_BATIDAS = 8         # no final seco no tempo, a proxima fica no andamento deste isso de batidas dele depois da
                           # primeira dela e so entao volta devagar ao dela (escolhida em 24/10 entre a anterior, a
                           # esticada e a que entra por baixo antes do corte)
_GRAVE_LP = signal.butter(2, GRAVE_HZ, "lowpass", fs=SR, output="sos")  # ida e volta: 4a ordem, fase zero
_GRAVE_HP = np.vstack([signal.butter(2, GRAVE_HZ, "highpass", fs=SR, output="sos")] * 2)  # Linkwitz-Riley


def sem_cursor():
    """O STARTUPINFO para abrir processo filho no Windows sem o cursor de carregando no mouse: o pythonw da medida de
    andamento nunca abre janela, e o Windows ficava esperando ela com o cursor girando, uma vez por parecida medida
    (num notebook). Fora do Windows, None."""
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= 0x80  # STARTF_FORCEOFFFEEDBACK
    return si


class Deck:
    """Um toca-discos do motor: o disco, a fila de blocos decodificados (t0, bloco) e a geracao do
    leitor (o leitor para quando ela muda)."""

    def __init__(self, track=None):
        self.track = track
        self.q = collections.deque()
        self.gen = 0
        self.eof_gen = -1
        self.ahead = AHEAD
        # o nivel de cada bloco decodificado (t0, quadros, rms), o ja tocado inclusive: a medicao do fim
        # precisa do trecho de antes da queda, que pode ja ter saido da fila
        self.niveis = collections.deque(maxlen=NIVEIS_MAX)


def _niveis(niv):
    niv = list(niv)
    return (np.array([v[0] for v in niv]), np.array([v[1] for v in niv]), np.array([v[2] for v in niv]))


def medir_fim(niv):
    """O fim do som, a queda e o fim para o ouvido: o nivel normal do fim e o que se sustenta (o
    percentil 90, alisado em meio segundo); a queda comeca onde o nivel alisado deixa de ficar a
    FADE_DB dele e acaba para o ouvido onde fica FIM_DB abaixo (no final seco, os tres quase juntos).
    (fim, queda, baixo), com None no que nao ha."""
    if not niv:
        return None, None, None
    t, q, r = _niveis(niv)
    som = np.nonzero(r > SILENCIO)[0]
    if not len(som):
        return None, None, None
    k = som[-1]
    fim = float(t[k] + q[k] / SR)
    db = 20 * np.log10(np.maximum(r[:k + 1], 1e-6))
    alis = np.convolve(np.pad(db, 25, mode="edge"), np.ones(51) / 51, mode="valid")
    ref = np.percentile(alis, 90)
    perto = np.nonzero(alis >= ref - FADE_DB)[0]
    if not len(perto):
        return fim, None, None
    i = perto[-1]
    abaixo = np.nonzero(alis[i:] < ref - FIM_DB)[0]
    return fim, float(t[i]), (float(t[i + abaixo[0]]) if len(abaixo) else fim)


def _junta(blocos, t_ini, t_fim):
    """O audio dos blocos (t0, bloco) que cabem inteiros entre t_ini e t_fim: (t0 do primeiro, n x 2)."""
    sel = [a for t, a in blocos if t >= t_ini - 1e-9 and t + len(a) / SR <= t_fim + 1e-9]
    if not sel:
        return None, None
    t0 = next(t for t, a in blocos if t >= t_ini - 1e-9)
    return t0, np.concatenate(sel)


def _catmull(x, phi):
    """x (n x 2) lido nas posicoes fracionarias phi (interpolacao cubica de Catmull-Rom), em pedacos de 1 s:
    a conta inteira de uma vez prende o interpretador e o audio do cabo espera."""
    y = np.empty((len(phi), 2), np.float32)
    n = len(x)
    for a in range(0, len(phi), SR):
        p = phi[a:a + SR]
        i = np.floor(p).astype(np.int64)
        f = (p - i).astype(np.float32)[:, None]
        xm, x0 = x[np.clip(i - 1, 0, n - 1)], x[np.clip(i, 0, n - 1)]
        x1, x2 = x[np.clip(i + 1, 0, n - 1)], x[np.clip(i + 2, 0, n - 1)]
        y[a:a + SR] = x0 + 0.5 * f * (x1 - xm + f * (2 * xm - 5 * x0 + 4 * x1 - x2 + f * (3 * (x0 - x1) + x2 - xm)))
    return y


def esticar(x, s, n_sob, n_rampa, alvo):
    """A proxima no andamento da que sai: x (n x 2) tocado na velocidade s por n_sob amostras de saida, voltando
    a 1 em n_rampa (meio cosseno) e consumindo exatamente alvo amostras de x, para o resto do disco seguir sem
    degrau. A velocidade sai como no vinil (reamostrando: a posicao de cada batida e exata) e o tom volta ao
    original pela Rubber Band, que mexendo so no tom erra o tempo em poucos ms (esticando direto, com a
    velocidade variando, errava dezenas). Devolve (saida, a posicao em x de cada amostra de saida)."""
    c = 0.5 * (1 + np.cos(np.linspace(0.0, np.pi, n_rampa, endpoint=False)))  # 1 -> 0
    k = (alvo - s * n_sob - n_rampa) / c.sum()  # o (s - 1) da rampa afinado para cair exato no alvo
    vel = np.concatenate([np.full(n_sob, s), 1 + k * c])
    phi = np.concatenate([[0.0], np.cumsum(vel)[:-1]])
    y = _catmull(x, phi)
    z = time_stretch(np.ascontiguousarray(y.T), SR, stretch_factor=1.0,
                     pitch_shift_in_semitones=-12 * np.log2(vel)).T
    # a Rubber Band atrasa uns ms: o atraso no fim (velocidade 1, tom intacto) sai pela correlacao com y
    m, janela = len(y), SR // 2
    busca = min(SR // 10, len(z) - m)
    d = 0
    if busca > 0:
        cor = signal.correlate(z[m - janela:m + busca, 0], y[m - janela:, 0], mode="valid", method="fft")
        d = int(np.argmax(cor))
    z = z[d:d + m]
    if len(z) < m:
        z = np.concatenate([z, y[len(z):]])
    # os ultimos 20 ms voltam ao y (velocidade 1, sem a Rubber Band), que emenda no resto do disco sem degrau
    w = int(0.02 * SR)
    g = np.linspace(0.0, 1.0, w, dtype=np.float32)[:, None]
    z[-w:] = z[-w:] * (1 - g) + y[-w:] * g
    return np.ascontiguousarray(z, np.float32), phi


def esticar_saida(x, s, n_rampa):
    """A que sai indo para a velocidade s antes da sobreposicao: x (n x 2) de 1 a s em n_rampa (meio cosseno) e
    em s ate o fim de x, como no esticar (vinil e o tom de volta pela Rubber Band). O atraso da Rubber Band sai
    pela correlacao no comeco, onde a velocidade ainda e 1, e os primeiros 20 ms sao o proprio x, que emenda no
    que ja tocou sem degrau. Devolve (saida, a posicao em x de cada amostra de saida)."""
    c = 0.5 * (1 - np.cos(np.linspace(0.0, np.pi, n_rampa, endpoint=False)))  # 0 -> 1
    resto = len(x) - 2 - (n_rampa + (s - 1) * c.sum())  # o que sobra de x depois da rampa, em amostras de x
    vel = np.concatenate([1 + (s - 1) * c, np.full(max(0, int(resto / s)), s)])
    phi = np.concatenate([[0.0], np.cumsum(vel)[:-1]])
    y = _catmull(x, phi)
    z = time_stretch(np.ascontiguousarray(y.T), SR, stretch_factor=1.0,
                     pitch_shift_in_semitones=-12 * np.log2(vel)).T
    m, janela = len(y), SR // 2
    busca = min(SR // 10, len(z) - janela)
    d = 0
    if busca > 0:
        cor = signal.correlate(z[:janela + busca, 0], y[:janela, 0], mode="valid", method="fft")
        d = int(np.argmax(cor))
    z = z[d:d + m]
    if len(z) < m:
        z = np.concatenate([z, y[len(z):]])
    w = int(0.02 * SR)
    g = np.linspace(0.0, 1.0, w, dtype=np.float32)[:, None]
    z[:w] = y[:w] * (1 - g) + z[:w] * g
    return np.ascontiguousarray(z, np.float32), phi


def _esticar_comeco(blocos_b, ini, s, n_sob):
    """O comeco da proxima (os blocos dela desde ini) pelo esticar: na velocidade s por n_sob amostras de saida e de
    volta a 1 devagar (RAMPA_TAXA, de RAMPA_MIN_S a RAMPA_MAX_S), ate um comeco de bloco, onde o resto do disco segue.
    ((saida, posicao em x de cada amostra, o bloco onde o resto segue, a volta em amostras), None), ou (None, por que
    nao) quando o que ja decodificou dela nao cobre a volta."""
    t_b_fim = blocos_b[-1][0]  # o ultimo bloco fica de folga para a interpolacao
    n_rampa = int(min(max(abs(s - 1) / RAMPA_TAXA, RAMPA_MIN_S), RAMPA_MAX_S) * SR)
    cabe = int(((t_b_fim - ini) * SR - s * n_sob) / ((1 + s) / 2))
    if cabe < n_rampa:  # a proxima nao decodificou o bastante (stream lento): sem volta lenta, sem esticar
        return None, (f"o comeco da proxima na fila ({t_b_fim - ini:.0f} s) nao cobre a volta lenta ao andamento "
                      f"dela ({n_rampa / SR:.0f} s)")
    alvo_t = ini + (s * n_sob + n_rampa * (1 + s) / 2) / SR
    ate = min((t for t, _ in blocos_b if ini < t <= t_b_fim), key=lambda t: abs(t - alvo_t))
    _, xs = _junta(blocos_b, ini, ate + BLOCK / SR)
    alvo = int(round((ate - ini) * SR))
    n_rampa = max(int(RAMPA_MIN_S * SR), n_rampa + int(round((alvo - (alvo_t - ini) * SR) / ((1 + s) / 2))))
    z, phi = esticar(xs, s, n_sob, n_rampa, alvo)
    return (z, phi, ate, n_rampa), None


def _regular(bt):
    """Os intervalos entre as batidas da rede e se sao regulares (REDE_REGULAR deles a 8% da mediana)."""
    ibi = np.diff(bt)
    if len(ibi) < 4:
        return ibi, False
    m = float(np.median(ibi))
    return ibi, bool(np.mean(np.abs(ibi / m - 1) <= 0.08) >= REDE_REGULAR)


def _grade_rede(x):
    """A Grade do trecho x pela rede, para quando o batida.py nao firma (None sem o modelo ou com as batidas
    irregulares): o andamento pelo ajuste de reta nas batidas (o numero de cada uma pela soma dos intervalos: pela
    distancia ao comeco dividida pela mediana, que vem presa nos quadros de 20 ms dela, a 40a virava a 41a), na
    oitava lenta do batida.py, com o lado pelos 1 dela (a grade lenta cai no 1 e no 3) e REDE_ATRASO antes."""
    r = compasso.uns(x, SR)
    if r is None or len(r[0]) < 8:
        return None
    bt, ut = r
    ibi, ok = _regular(bt)
    if not ok:
        return None
    k = np.r_[0, np.cumsum(np.maximum(np.round(ibi / np.median(ibi)), 1))]
    p, c = np.polyfit(k, bt, 1)
    P = float(p)
    while 60 / P >= 2 * batida.LENTA:
        P *= 2
    while 60 / P < batida.LENTA:
        P /= 2
    ancora = float(ut[0]) if len(ut) else float(bt[0])
    f = (float(c + np.round((ancora - c) / p) * p) - REDE_ATRASO) % P
    # entre a batida e o contratempo quem decide e o bumbo, como no batida.py (o Overdose, 21/10): na intro falada
    # da NWA a rede pos a batida no meio tempo do bumbo, e ela entrava no contratempo do Stay With Me
    mono = x.mean(axis=1) if x.ndim > 1 else x
    fps = SR / batida.HOP
    meios = np.array([f, (f + P / 2) % P]) * fps
    ng = batida._notas(batida._suave(batida.ataques(np.asarray(mono, np.float32), SR, batida.GRAVE_HZ)), P * fps, meios)
    virou = bool(ng[1] > ng[0] and ng[0] <= batida.GRAVE_DECIDE * ng[1])
    if virou:
        f = (f + P / 2) % P
    return batida.Grade(60 / P, P, f, True, f"pela rede: {60 / float(p):.1f} BPM{', o bumbo virou o lado' if virou else ''}")


def _fase_rede(x, periodo, perto):
    """A fase (s desde o comeco de x) da grade de periodo dado pelas batidas da rede em x, perto de perto: a
    mediana do desvio das batidas que caem a menos de um quarto de periodo da grade (as do meio tempo ficam de
    fora); None sem batidas regulares ou sem nenhuma na grade."""
    r = compasso.uns(x, SR)
    if r is None:
        return None
    bt = r[0] - REDE_ATRASO
    if not _regular(bt)[1]:
        return None
    d = (bt - perto + periodo / 2) % periodo - periodo / 2
    d = d[np.abs(d) < periodo / 4]
    return float((perto + np.median(d)) % periodo) if len(d) >= 3 else None


def medir_inicio(niv):
    """Onde comeca o som: o primeiro bloco acima do silencio (0 se nao ha)."""
    if not niv:
        return 0.0
    t, _, r = _niveis(niv)
    som = np.nonzero(r > SILENCIO)[0]
    return float(t[som[0]]) if len(som) else 0.0


def _com_init():
    """WASAPI exige COM na thread que abre o stream; a troca de dispositivo roda numa
    thread do pool do servidor, e sem isto o start falha com PaErrorCode -9999."""
    if sys.platform == "win32":
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # MTA; S_FALSE/RPC_E_CHANGED_MODE servem


def _wasapi():
    return next(i for i, h in enumerate(sd.query_hostapis()) if "WASAPI" in h["name"])


def list_devices():
    """Nomes WASAPI de entrada e saida, e os padroes do Windows."""
    w = _wasapi()
    ins, outs = [], []
    for d in sd.query_devices():
        if d["hostapi"] != w:
            continue
        if d["max_input_channels"] > 0:
            ins.append(d["name"])
        if d["max_output_channels"] > 0:
            outs.append(d["name"])
    ha = sd.query_hostapis(w)
    di, do = ha["default_input_device"], ha["default_output_device"]
    return {"inputs": ins, "outputs": outs,
            "default_input": sd.query_devices(di)["name"] if di >= 0 else None,
            "default_output": sd.query_devices(do)["name"] if do >= 0 else None}


def list_devices_live():
    """A lista do seletor: a do list_devices e a do dia em que o PortAudio subiu, e o que
    conectou depois (o Quest pelo Virtual Desktop com o soundboard ja ligado) nao aparecia
    (19/10). O Core Audio le de novo a cada chamada sem fechar o audio; se falhar, fica a
    do PortAudio."""
    try:
        _com_init()
        import winvol  # noqa: PLC0415 - comtypes so em thread MTA (ver _winvol_loop)
        return winvol.dispositivos()
    except Exception:  # noqa: BLE001
        return list_devices()


def _rescan():
    """Rele a lista do PortAudio, para abrir o que conectou depois de ele subir. Reiniciar o
    PortAudio derruba todo stream aberto: so com o motor fechado."""
    _com_init()
    sd._terminate()  # noqa: SLF001 - o sounddevice nao tem releitura publica
    sd._initialize()  # noqa: SLF001


def _na_lista(nome, lista):
    """O nome como o find_dev acha (pedaco do nome, sem caixa) numa lista de nomes; None se
    nao tem."""
    if not nome:
        return None
    n = nome.lower()
    return next((x for x in lista if n in x.lower()), None)


def find_dev(name, kind):
    w = _wasapi()
    key = "max_output_channels" if kind == "out" else "max_input_channels"
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == w and name.lower() in d["name"].lower() and d[key] > 0:
            return i, d
    raise ValueError(f"Não achei o dispositivo \"{name}\". Confira se ele está conectado.")


def probe_duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


class Engine:
    def __init__(self, mic, out, monitor):
        self.devices = {"mic": mic, "out": out, "monitor": monitor}  # nome, 'default' ou '' (sem fone)
        self.active = dict(self.devices)  # nomes reais abertos
        self.vol = 0.6         # arquivo no cabo (o que o jogo ouve)
        self.mon_vol = 0.6     # arquivo no fone de quem toca
        self.mic_vol = 1.0     # nivel do mic no Windows (a thread do winvol le e grava)
        self._wv = None        # pedidos de nivel para essa thread
        self._wv_n = 0         # conta os pedidos: leitura velha nao pisa num pedido novo
        self.mic_mute = False
        self.monitor_on = True
        self.loop = False
        self.effect = "nenhum"  # efeito de voz (fx.py); sempre comeca sem efeito
        self._fx = None
        self.voice_monitor = False  # ouvir a propria voz (com o efeito) no fone
        self.voice_mon_vol = 0.8
        # sons por cima (buzina, bordao): tocam junto da musica sem parar ela; cada um e
        # [item, audio inteiro (n x 2), posicao], misturados no _out_cb
        self._sobre = []
        self._slock = threading.Lock()
        self._sobre_cache = collections.OrderedDict()
        self.track = None      # item da biblioteca carregado
        self.paused = False
        self.ended = False
        self.pos = 0.0
        self.error = None
        self._espera_arquivo = None  # o _gen do stream que falhou com o download a caminho (esperando_arquivo)
        self.levels = {"mic": 0.0, "track": 0.0, "out": 0.0}
        self._deck = Deck()    # o disco do prato: _q, _gen e _eof_gen sao os dele
        self._qlock = threading.Lock()
        # a passagem para a proxima: o servidor prepara a proxima da fila num segundo deck antes do fim;
        # o motor mede o fim deste e o comeco dela e vira no ponto certo, a do fade-out por baixo dele
        self._pronto = None      # o Deck da proxima, com o leitor enchendo a fila
        self.pronto_tag = None   # quem o servidor preparou (o qid da entrada da fila)
        self._virar_em = None    # a posicao deste disco em que a proxima entra (None: medindo)
        self._sobrepor = 0       # quadros em que o que sai abaixa (a sobreposicao da passagem medida)
        self._entrar = 0         # quadros em que a proxima sobe (no final seco no tempo, quase nada)
        self._grave = None       # (de, ate) em quadros desde a virada: a troca de grave da passagem no tempo
        self._saindo = None      # [deck, quadros, feitos, grave]: o disco que sai, abaixando por baixo
        self._entrando = None    # [quadros, feitos]: a proxima subindo
        self.virou = None        # (o que saiu, o que entrou, a tag) para o servidor tirar da fila
        self.periodo_saida = None  # a batida do que sai na saida (s), pelo plano no tempo: a regua dos testes (dev/)
        self.pronto_falhou = None  # a tag da proxima que nao decodificou: o servidor nao prepara de novo
        self._mic = collections.deque()
        self._mon = collections.deque()
        self._stack = None
        self._lock = threading.RLock()
        self._vigia = None        # thread que segue o aparelho escolhido (_vigia_loop)
        self._fechado = False     # close() de proposito: o vigia nao reabre
        self._caiu_no_vigia = False  # a reabertura do vigia falhou: ele pode tentar de novo
        self._aviso = None        # aviso dos aparelhos (reserva, reabertura que falhou): so ele sai quando voltam

    # o deck do prato (o resto do motor fala com ele por estes nomes)
    @property
    def _q(self):
        return self._deck.q

    @property
    def _gen(self):
        return self._deck.gen

    @_gen.setter
    def _gen(self, v):
        self._deck.gen = v

    @property
    def _eof_gen(self):
        return self._deck.eof_gen

    @_eof_gen.setter
    def _eof_gen(self, v):
        self._deck.eof_gen = v

    # dispositivos ---------------------------------------------------------
    def resolve(self, d=None):
        """'default' = o padrao do Windows na hora (no VR vira o Virtual Desktop sozinho).
        d = a lista a usar (a do vigia vem do Core Audio); sem ela, a do PortAudio."""
        d = d or list_devices()
        mic = self.devices["mic"]
        mon = self.devices["monitor"]
        if mic == "default":
            mic = d["default_input"]
        if mon == "default":
            mon = d["default_output"] or ""
            if "cable" in mon.lower():
                mon = ""
        return {"mic": mic, "out": self.devices["out"], "monitor": mon}

    def _reserva(self, act, d=None):
        """O mic ou o fone escolhidos que nao estao conectados caem no padrao do Windows: o
        Quest desligado leva o fone do Virtual Desktop junto, e o servidor nao subia (20/10).
        Devolve (o que abrir, o que faltou); a escolha do usuario continua gravada, e a troca pela
        interface segue recusando o que nao existe."""
        d = d or list_devices()
        faltou = []
        for k, lista, nome in (("mic", d["inputs"], "microfone"), ("monitor", d["outputs"], "fone")):
            if not act[k] or _na_lista(act[k], lista):
                continue
            pad = d["default_input"] if k == "mic" else d["default_output"] or ""
            if pad is None:
                continue  # sem microfone nenhum: o find_dev do start avisa
            if k == "monitor" and "cable" in pad.lower():
                pad = ""
            faltou.append(f"{nome} \"{act[k]}\"")
            act[k] = pad
        return act, faltou

    def _desejado(self, d):
        """Os nomes que a partida com reserva abriria com a lista d."""
        act, _ = self._reserva(self.resolve(d), d)
        return {"mic": _na_lista(act["mic"], d["inputs"]),
                "monitor": _na_lista(act["monitor"], d["outputs"]) or ""}

    def start(self, reserva=False):
        _com_init()
        # o modelo da rede abre ja e fica aberto (~100 MB): abrir segura o interpretador ~0,6 s, e reabrindo a cada
        # plano o audio estalava (num notebook, aos ~30 s do Where's My Love, 22/10); aqui ainda nao toca nada
        threading.Thread(target=compasso.abre_ja, daemon=True).start()
        self._fechado = False
        # antes de procurar os aparelhos: a partida que nao acha o cabo fica esperando ele pelo vigia
        if self._wv is None:
            self._wv = queue.Queue()
            threading.Thread(target=self._winvol_loop, daemon=True).start()
        if self._vigia is None:
            self._vigia = threading.Thread(target=self._vigia_loop, daemon=True)
            self._vigia.start()
        act = self.resolve()
        faltou = []
        if reserva:
            act, faltou = self._reserva(act)
        mic_i, mic_d = find_dev(act["mic"], "in")
        out_i, out_d = find_dev(act["out"], "out")
        mon_i = find_dev(act["monitor"], "out")[0] if act["monitor"] else None
        self.active = {"mic": mic_d["name"], "out": out_d["name"],
                       "monitor": sd.query_devices(mon_i)["name"] if mon_i is not None else ""}
        if "cable" in mic_d["name"].lower():
            raise ValueError("O microfone não pode ser o próprio cabo: a voz voltaria em eco sem fim.")
        if mon_i is not None and "cable" in self.active["monitor"].lower():
            raise ValueError("O fone não pode ser o cabo: o som iria duas vezes para o jogo.")
        st = contextlib.ExitStack()
        try:
            st.enter_context(sd.InputStream(device=mic_i, channels=mic_d["max_input_channels"],
                                            samplerate=SR, blocksize=BLOCK, dtype="float32",
                                            extra_settings=WASAPI, callback=self._mic_cb))
            st.enter_context(sd.OutputStream(device=out_i, channels=2, samplerate=SR,
                                             blocksize=BLOCK, dtype="float32",
                                             extra_settings=WASAPI, callback=self._out_cb))
            if mon_i is not None:
                st.enter_context(sd.OutputStream(device=mon_i, channels=2, samplerate=SR,
                                                 blocksize=BLOCK, dtype="float32",
                                                 extra_settings=WASAPI, callback=self._mon_cb))
        except Exception:
            st.close()
            raise
        self._stack = st
        if faltou:
            self._aviso = self.error = (
                f"Não achei o {' nem o '.join(faltou)}; usei o padrão do Windows até "
                f"{'ele voltar' if len(faltou) == 1 else 'eles voltarem'}.")
        elif self._aviso is not None and self.error == self._aviso:
            self.error = None  # o aparelho escolhido voltou: sai so o aviso, nunca um erro de tocar

    def liga(self):
        """A partida do servidor. Se o audio nao abre (sem o CABLE Input, aparelho que recusa), o servidor sobe mesmo
        assim com o erro na tela, e o vigia (logo depois, e de novo quando a lista muda) ou a troca de aparelho pela
        interface tentam de novo. Antes, o app inteiro caia com o erro do Python (29/10)."""
        with self._lock:
            try:
                self.start(reserva=True)
            except Exception as ex:  # noqa: BLE001
                self._sem_audio(ex)

    def close(self):
        with self._lock:
            self._fechado = True
            self._gen += 1
            if self._stack:
                self._stack.close()
                self._stack = None

    def _vigia_loop(self):
        """Segue sozinho o aparelho escolhido quando ele conecta ou desconecta (o Quest pelo
        Virtual Desktop, 20/10): le a lista do Windows a cada VIGIA_S e, so quando ela muda,
        reabre o que a partida com reserva abriria, se for diferente do que esta aberto. Lista
        parada nao reabre nada (cada reabertura corta uns 90 ms); a escolha do usuario (devices) e o
        config nunca mudam daqui."""
        _com_init()
        assin, resta = None, 0
        while True:
            time.sleep(VIGIA_S)
            if self._fechado:
                continue
            try:
                d = list_devices_live()
            except Exception:  # noqa: BLE001 - leitura falhou: tenta na volta
                continue
            a = (tuple(d["inputs"]), tuple(d["outputs"]), d["default_input"], d["default_output"])
            if a != assin:
                assin, resta = a, VIGIA_TENTATIVAS
            if resta <= 0:
                continue
            # sob o lock da troca manual: o desejado sai das escolhas de agora, nunca de antes
            # de um set_devices que terminou no meio
            with self._lock:
                if self._fechado or (self._stack is None and not self._caiu_no_vigia):
                    resta = 0  # fechado de proposito (ou por quem nao e o vigia): nao reabre
                    continue
                quer = self._desejado(d)
                if quer["mic"] is None or (self._stack is not None and all(
                        self.active[k] == quer[k] for k in ("mic", "monitor"))):
                    resta = 0  # nada a mudar, ou microfone nenhum no Windows para abrir
                    continue
                resta -= 1
                self._reabre()

    def _reabre(self):
        """Fecha so os streams (o disco segue no prato), rele o PortAudio e abre com reserva.
        Chamar com self._lock."""
        if self._stack:
            self._stack.close()
            self._stack = None
        try:
            _rescan()
            self.start(reserva=True)
            self._caiu_no_vigia = False
        except Exception as ex:  # noqa: BLE001 - tenta de novo na volta, dentro do VIGIA_TENTATIVAS
            self._sem_audio(ex)

    def _sem_audio(self, ex):
        """O audio nao abriu: o erro fica na tela e o vigia pode tentar de novo. A mesma frase na partida e na
        reabertura: a partida que falha tambem passa pelo vigia logo depois."""
        self._caiu_no_vigia = True
        self._aviso = self.error = f"Não consegui abrir o áudio ({str(ex)[:160]})."

    # nivel do mic no Windows ----------------------------------------------
    def set_mic_vol(self, v):
        """A "Voz" da interface e o nivel do mic em uso nas configuracoes de som do
        Windows: a barra mostra na hora e a thread do winvol grava."""
        self._wv_n += 1
        self.mic_vol = max(0.0, min(1.0, float(v)))
        if self._wv is not None:
            self._wv.put(self.mic_vol)

    def _winvol_loop(self):
        """Dona do COM do nivel do Windows: grava o ultimo pedido e le o nivel a cada
        0,3 s, para a barra acompanhar quando o usuario muda o volume pelo proprio Windows."""
        _com_init()
        # o comtypes inicia o COM de quem importa: aqui, em MTA (a thread principal ja e STA
        # pelo sounddevice, e la o import quebraria)
        import winvol  # noqa: PLC0415
        ep, nome = None, None
        while True:
            try:
                v = self._wv.get(timeout=0.3)
                while not self._wv.empty():  # arrastando: so o ultimo valor importa
                    v = self._wv.get_nowait()
            except queue.Empty:
                v = None
            try:
                if self.active["mic"] != nome:
                    nome = self.active["mic"]
                    # o nivel do cabo e o microfone do VRChat: esse nunca se mexe daqui
                    ep = None if "cable" in (nome or "").lower() else winvol.volume_do(nome)
                if ep is None:
                    if v is not None:
                        self.error = f"Não achei o volume do Windows do microfone \"{nome}\"."
                    continue
                if v is not None:
                    winvol.gravar(ep, v)
                n = self._wv_n
                lido = winvol.ler(ep)
                if n == self._wv_n:  # pedido novo no meio da leitura: a barra fica com ele
                    self.mic_vol = lido
            except Exception:  # noqa: BLE001 - mic desconectado: procura de novo na volta
                ep, nome = None, None

    def set_devices(self, mic=None, out=None, monitor=None):
        with self._lock:
            old = dict(self.devices)
            new = dict(old)
            for k, v in (("mic", mic), ("out", out), ("monitor", monitor)):
                if v is not None:
                    new[k] = v
            if self._stack:
                self._stack.close()
                self._stack = None
            _rescan()
            self.devices = new
            try:
                self.start()
            except Exception:
                self.devices = old
                self.start(reserva=True)  # a escolha antiga pode ser o fone que sumiu
                raise

    # callbacks de audio ---------------------------------------------------
    def _meter(self, key, x):
        rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
        self.levels[key] = max(rms, self.levels[key] * DECAY)

    def _mic_cb(self, indata, frames, t, status):
        self._push_mic(indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0].copy())

    def _push_mic(self, x):
        f = self._fx
        if f is not None:
            try:
                x = f(x)
            except Exception as ex:  # noqa: BLE001 - efeito quebrado nao pode calar a voz
                self._fx, self.effect = None, "nenhum"
                self.error = f"O efeito de voz falhou ({str(ex)[:120]}). Voltei para sem efeito."
        self._mic.append(x)
        while len(self._mic) > MIC_MAX:
            self._mic.popleft()

    def set_effect(self, effect_id):
        self._fx = fx.criar(effect_id)  # instancia nova: estado zerado; ValueError se nao existe
        self.effect = effect_id

    def _mon_cb(self, outdata, frames, t, status):
        if self._mon:
            b = self._mon.popleft()
            n = min(len(b), frames)
            outdata[:n] = b[:n]
            outdata[n:] = 0
        else:
            outdata[:] = 0
        while len(self._mon) > MIC_MAX:
            self._mon.popleft()

    def _out_cb(self, outdata, frames, t, status):
        buf = np.zeros((frames, 2), np.float32)
        item = None
        if self._pronto is not None and self.track is not None and not self.paused:
            fim_deste = not self._q and self._eof_gen == self._gen
            if (self._virar_em is not None and self.pos >= self._virar_em) or (fim_deste and self._pronto.q):
                self._vira()
        if self.track is not None and not self.paused:
            with self._qlock:
                item = self._tira(self._q, frames)
            if not item and self._eof_gen == self._gen:
                self.ended = True
        som = None  # arquivo + sons por cima, antes do volume
        if item:
            som = np.zeros((frames, 2), np.float32)
            n = 0
            for _, s in item:
                som[n:n + len(s)] = s
                n += len(s)
            self.pos = item[-1][0] + len(item[-1][1]) / SR
            ent = self._entrando
            if ent is not None:  # a proxima subindo: um quarto de seno, potencia constante com a que sai
                g = np.sin(np.minimum((ent[1] + np.arange(n)) / ent[0], 1.0) * (np.pi / 2)).astype(np.float32)
                som[:n] *= g[:, None]
                ent[1] += n
                if ent[1] >= ent[0]:
                    self._entrando = None
        sai = self._saindo
        if sai is not None and not self.paused:  # o que sai: o fim dele, abaixando em cosseno
            with self._qlock:
                blk = self._tira(sai[0].q, frames)
            if not blk or sai[2] >= sai[1]:
                sai[0].gen += 1
                self._saindo = None
            else:
                s = blk[0][1] if len(blk) == 1 else np.concatenate([b[1] for b in blk])
                n = len(s)
                u = sai[2] + np.arange(n)
                g = np.cos(np.minimum(u / sai[1], 1.0) * (np.pi / 2)).astype(np.float32)
                if sai[3] is not None:  # a troca de grave: o grave dele sai enquanto o da proxima entra
                    gr = sai[3]
                    agudo, gr[1] = signal.sosfilt(_GRAVE_HP, s, axis=0, zi=gr[1])
                    fica = (1 - np.clip((u - gr[2]) / (gr[3] - gr[2]), 0.0, 1.0)).astype(np.float32)
                    s = agudo + fica[:, None] * (s - agudo)
                if som is None:
                    som = np.zeros((frames, 2), np.float32)
                som[:n] += s * g[:, None]
                sai[2] += n
        if self._sobre:
            with self._slock:
                vivos = []
                for sb in self._sobre:
                    a, p = sb[1], sb[2]
                    k = min(frames, len(a) - p)
                    if som is None:
                        som = np.zeros((frames, 2), np.float32)
                    som[:k] += a[p:p + k]
                    sb[2] = p + k
                    if sb[2] < len(a):
                        vivos.append(sb)
                self._sobre = vivos
        com_fone = self.monitor_on and self.active["monitor"]
        if som is not None:
            buf += som * self.vol
            # o DISCO mostra o disco no mais alto dos volumes que estao soando, o do jogo ou o do
            # fone: com o jogo em zero e o fone em 15% ele parava, com o disco tocando no fone.
            # O JOGO segue sendo so o que o jogo recebe
            self._meter("track", som * max(self.vol, self.mon_vol if com_fone else 0.0))
        else:
            self.levels["track"] *= DECAY
        fone = None  # o que vai pro fone de quem toca: o som e, se pedido, a propria voz
        if som is not None and com_fone:
            fone = som * self.mon_vol
        if self._mic:
            m = self._mic.popleft()  # o nivel da voz e o do Windows (winvol)
            self._meter("mic", m)
            n = min(len(m), frames)
            if not self.mic_mute:
                buf[:n, 0] += m[:n]
                buf[:n, 1] += m[:n]
            # ouvir a propria voz vale mesmo com a voz cortada: testar o efeito sem ir pro jogo
            if self.voice_monitor and self.active["monitor"]:
                if fone is None:
                    fone = np.zeros((frames, 2), np.float32)
                v = m[:n] * self.voice_mon_vol
                fone[:n, 0] += v
                fone[:n, 1] += v
        else:
            self.levels["mic"] *= DECAY
        if fone is not None:
            self._mon.append(np.clip(fone, -1, 1))
        np.clip(buf, -1, 1, out=buf)
        self._meter("out", buf)
        outdata[:] = buf

    @staticmethod
    def _tira(q, n):
        """Com _qlock: ate n amostras do comeco da fila q, em [(t0, pedaco)], partindo o bloco que passa (o
        resto dele fica na fila): o comeco da proxima no tempo nao cai em fronteira de bloco."""
        partes = []
        while n > 0 and q:
            t0, s = q[0]
            if len(s) <= n:
                q.popleft()
            else:
                q[0] = (t0 + n / SR, s[n:])
                s = s[:n]
            partes.append((t0, s))
            n -= len(s)
        return partes

    # decodificacao --------------------------------------------------------
    @staticmethod
    def _entrada(track):
        """Argumentos do ffmpeg antes do -i: o stream do YouTube reconecta sozinho se a rede
        piscar e leva os cabecalhos que o yt-dlp mandou; arquivo local nao precisa de nada."""
        if not track.get("stream") or not str(track.get("path") or "").startswith("http"):
            return []
        a = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4"]
        if track.get("headers"):
            a += ["-headers", track["headers"]]
        return a

    def _reader(self, gen, track, start, deck):
        t = start
        path = track["path"]
        stream = str(path).startswith("http")  # o YouTube direto, antes de o download chegar
        while gen == deck.gen:
            ff = subprocess.Popen([FFMPEG, "-v", "error", *self._entrada(track), "-ss", str(t), "-i", path,
                                   "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=NO_WINDOW)
            n = 0
            try:
                while gen == deck.gen:
                    if len(deck.q) > deck.ahead:
                        time.sleep(0.01)
                        continue
                    b = ff.stdout.read(BLOCK * 8)
                    if not b:
                        break
                    arr = np.frombuffer(b[: len(b) // 8 * 8], np.float32).reshape(-1, 2)
                    rms = float(np.sqrt(np.mean(arr * arr))) if len(arr) else 0.0  # fora do lock do callback
                    with self._qlock:
                        if gen != deck.gen:
                            break
                        deck.q.append((t + n / SR, arr))
                        deck.niveis.append((t + n / SR, len(arr), rms))
                    n += len(arr)
            finally:
                ff.kill()
                ff.wait()
            if gen != deck.gen:
                return
            if n == 0 and stream and track.get("job") and deck is self._deck:
                # o download do mesmo disco esta a caminho (27/10: o YouTube deu 403 ao ffmpeg em 2 de ~15 streams, e
                # o download chegava 2 s depois): sem erro e sem fim, o prato fica carregando e o trocar_fonte toca
                # o arquivo de onde parou; se o download falhar, o servidor para o prato (esperando_arquivo)
                self._espera_arquivo = gen
                return
            if n == 0 and deck is not self._deck:  # a proxima que nao decodifica so nao entra
                deck.eof_gen = gen
                return
            if n == 0:
                nome = track.get("title") or "o arquivo"
                quando = f"{int(t // 60)}:{int(t % 60):02d}"
                if track.get("stream"):
                    self.error = (f"O YouTube parou de mandar o áudio de \"{nome}\" em {quando}. "
                                  "Toque de novo, ou espere ele chegar na prateleira.")
                else:
                    self.error = (f"Não consegui ler o áudio de \"{nome}\" a partir de {quando}. "
                                  "O arquivo pode estar corrompido; apague e baixe de novo.")
                deck.eof_gen = gen
                return
            if not self.loop or deck is not self._deck:
                deck.eof_gen = gen
                return
            t = 0.0

    def _decodifica(self, path, limite):
        ff = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-t", str(limite),
                             "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                            capture_output=True, creationflags=NO_WINDOW)
        a = np.frombuffer(ff.stdout[: len(ff.stdout) // 8 * 8], np.float32).reshape(-1, 2)
        return a.copy()

    def _toca_sobre(self, track):
        # o curto toca ate CURTO_MAX_S; o posto nos Sons rapidos pela mao ("rapido" no disco), inteiro
        limite = RAPIDO_MAX_S if track.get("rapido") else CURTO_MAX_S
        chave = (track["id"], limite)
        try:
            a = self._sobre_cache.get(chave)
            if a is None:
                a = self._decodifica(track["path"], limite)
                if not len(a):
                    raise ValueError("vazio")
                self._sobre_cache[chave] = a
                while len(self._sobre_cache) > 1 and (
                        len(self._sobre_cache) > SOBRE_CACHE
                        or sum(x.nbytes for x in self._sobre_cache.values()) > SOBRE_CACHE_MB * 2 ** 20):
                    self._sobre_cache.popitem(last=False)
            else:
                self._sobre_cache.move_to_end(chave)
        except Exception:  # noqa: BLE001 - som por cima quebrado nao derruba o resto
            self.error = (f"Não consegui ler o áudio de \"{track.get('title') or 'o arquivo'}\". "
                          "O arquivo pode estar corrompido; apague e baixe de novo.")
            return
        with self._slock:
            self._sobre.append([{"id": track["id"], "title": track.get("title")}, a, 0])
            del self._sobre[:-SOBRE_MAX]

    def _restart(self, start):
        with self._qlock:
            self._cancela_passagem(tudo=True)
            self._gen += 1
            self._q.clear()
            self._deck.niveis.clear()  # a posicao pulou: o nivel de antes nao e mais o caminho ate o fim
            self._eof_gen = -1
            gen = self._gen
        self.pos = start
        self.ended = False
        self.error = None
        if not self.track.get("path"):  # disco ainda esperando o stream abrir: sem leitor
            return
        threading.Thread(target=self._reader, args=(gen, self.track, start, self._deck), daemon=True).start()

    # passagem para a proxima ------------------------------------------------
    def preparar(self, track, tag):
        """A proxima da fila no segundo deck (o servidor chama a TRANS_PREP_S do fim): o leitor dela
        decodifica o comeco, o deste vai ate o fim, e o _mede marca onde virar."""
        with self._lock:
            if self.track is None or not track.get("path"):
                return False
            with self._qlock:
                self._cancela_passagem()
                d = Deck(track)
                d.gen, d.ahead = 1, PRONTO_AHEAD
                self._pronto, self.pronto_tag = d, tag
                self._deck.ahead = 10 ** 9  # o fim deste inteiro na memoria para medir (45 s sao ~17 MB)
                atual = self._deck
            threading.Thread(target=self._reader, args=(1, track, 0.0, d), daemon=True).start()
            threading.Thread(target=self._mede, args=(atual, d, self.track), daemon=True).start()
            return True

    def cancelar_pronto(self):
        with self._qlock:
            self._cancela_passagem()

    def _cancela_passagem(self, tudo=False):
        """Com _qlock: a proxima preparada sai (o leitor dela para) e o disco do prato volta a
        decodificar so AHEAD adiante; tudo=True (recomecar, parar, outro disco) corta tambem a
        passagem que esta soando."""
        if self._pronto is not None:
            self._pronto.gen += 1
        self._pronto = self.pronto_tag = self._virar_em = None
        self._deck.ahead = AHEAD
        if tudo:
            if self._saindo is not None:
                self._saindo[0].gen += 1
            self._saindo = self._entrando = None

    def _mede(self, atual, prox, tr_atual):
        """Espera o fim deste disco e o comeco da proxima decodificados e marca a virada: o final
        seco emenda tirando o silencio entre os dois; o fade-out recebe a proxima por baixo, do
        comeco da queda ao fim do som (ate TRANS_MAX_S). Com as batidas dos dois firmes, a passagem
        vai no tempo (_plano_batida)."""
        t_prep = time.perf_counter()
        while True:
            if self._pronto is not prox or self._deck is not atual:
                return
            with self._qlock:
                resta = atual.q[-1][0] - self.pos if atual.q else 0.0
            pronta = (prox.eof_gen == prox.gen or len(prox.q) >= PRONTO_AHEAD
                      or (len(prox.q) >= PRONTO_MIN and resta < 20))
            if atual.eof_gen == atual.gen and pronta:
                break
            time.sleep(0.05)
        t_plano, pos_plano = time.perf_counter(), self.pos
        with self._qlock:
            cauda, cabeca = list(atual.niveis), list(prox.niveis)
        if not cabeca:  # a proxima nao decodificou: o servidor toca ela no fim, como antes
            with self._qlock:
                if self._pronto is prox:
                    self.pronto_falhou = self.pronto_tag
                    self._cancela_passagem()
            return
        fim, queda, baixo = medir_fim(cauda)
        ini = medir_inicio(cabeca)
        if fim is None:  # o resto deste e silencio: a proxima entra ja
            fim = self.pos
        caindo = baixo - queda if queda is not None and baixo is not None else 0.0
        fade = caindo >= FADE_MIN_S
        if fade:  # fade-out: a proxima sobe enquanto ele cai, e o rabo baixinho fica para tras
            sobrepor = min(caindo, TRANS_MAX_S)
            virar = baixo - sobrepor
        if not fade or virar < self.pos:
            # final seco (ou a medicao chegou depois do ponto, com a rede lenta): emenda no fim do som,
            # tirando o silencio entre os dois, sem cortar o que ainda esta tocando
            fade = False
            sobrepor, virar = TRANS_SECO_S, fim - TRANS_SECO_S
        try:
            plano, motivo = (self._plano_batida(atual, prox, fade, fim, queda, baixo, ini, virar, sobrepor)
                             if queda is not None else (None, "sem a queda do fim"))
        except Exception as ex:  # noqa: BLE001 - a passagem no tempo e um extra: sem ela, a de volume
            plano, motivo = None, f"erro: {ex!r}"
        with self._qlock:
            if self._pronto is not prox or self._deck is not atual:
                return
            if plano is not None and plano["virar"] - self.pos < FOLGA_S:
                plano, motivo = None, "o plano ficou pronto depois da hora"
            if plano is not None and plano.get("sai_q") and (not atual.q or atual.q[0][0] > plano["sai_q"][0] + 1e-7):
                plano, motivo = None, "o plano ficou pronto depois do comeco da rampa da que sai"
            if plano is not None:
                if plano.get("sai_q"):  # a que sai, da rampa em diante, pelos blocos reamostrados
                    t_r, novos = plano["sai_q"]
                    while atual.q and atual.q[-1][0] >= t_r - 1e-7:
                        atual.q.pop()
                    atual.q.extend(novos)
                while prox.q and prox.q[0][0] < plano["ate"] - 1e-7:  # sai o comeco que o plano refez
                    prox.q.popleft()
                prox.q.extendleft(reversed(plano["cabeca"]))
                if plano["silencio"]:  # a proxima entra depois do fim do arquivo deste: silencio ate la
                    t, a = atual.q[-1]
                    t += len(a) / SR
                    for _ in range(plano["silencio"]):
                        atual.q.append((t, np.zeros((BLOCK, 2), np.float32)))
                        t += BLOCK / SR
                self._sobrepor, self._entrar, self._grave = plano["sai"], plano["entra"], plano["grave"]
                self.periodo_saida = plano["periodo_saida"]
                self._virar_em = plano["virar"] - BLOCK / (2 * SR)  # vira no fim do bloco que acaba ali
            else:
                while prox.q and prox.q[0][0] + len(prox.q[0][1]) / SR <= ini:  # a proxima comeca no som
                    prox.q.popleft()
                self._sobrepor = self._entrar = int(sobrepor * SR)
                self._grave = None
                self._virar_em = max(self.pos, virar)
        jeito = f"fade-out de {caindo:.1f} s" if fade else "final seco"
        print(f"passagem: {tr_atual.get('title')!r} -> {prox.track.get('title')!r}: som ate "
              f"{fim:.2f} s, {jeito}, vira em {virar:.2f} s sobrepondo {sobrepor:.2f} s, a proxima comeca em {ini:.2f} s",
              file=sys.stderr, flush=True)
        print(f"passagem: no tempo: {plano['log']}" if plano is not None else f"passagem: sem alinhar a batida: {motivo}",
              file=sys.stderr, flush=True)
        # quanto a preparacao esperou (os dois decodificados) e quanto o plano levou, e a folga que sobrou ate a virada
        print(f"passagem: preparada a {fim - pos_plano + (t_plano - t_prep):.0f} s do fim; esperou "
              f"{t_plano - t_prep:.1f} s pelo audio, planejou em {time.perf_counter() - t_plano:.1f} s; a virada ficou "
              f"{virar - self.pos:.1f} s adiante", file=sys.stderr, flush=True)

    def _plano_batida(self, atual, prox, fade, fim, queda, baixo, ini, virar, sobrepor):
        """A passagem no tempo, pela grade de batidas do fim deste e do comeco da proxima. No fade-out com os
        andamentos perto (TEMPO_MAX, a menos de oitava), a proxima entra esticada no andamento deste com as
        batidas em cima das dele, os graves trocam numa batida do meio da sobreposicao e ela volta ao
        andamento dela devagar (RAMPA_TAXA). No final seco, a primeira batida dela cai na primeira batida deste depois
        que o som dele acabou para o ouvido, e ela entra cheia, esticada no andamento deste por SEGURA_BATIDAS dele e
        de volta devagar ao dela, como no fade. Devolve (plano, None) ou (None, por que nao);
        o plano so mexe nas filas depois, com o _qlock, se ainda der tempo."""
        with self._qlock:
            blocos_a, blocos_b = list(atual.q), list(prox.q)
        if not blocos_a or not blocos_b:
            return None, "sem audio na fila"
        fim_a = baixo if fade else fim
        t_a, xa = _junta(blocos_a, fim_a - BATIDA_S, fim_a)
        t_b, xb = _junta(blocos_b, ini, ini + BATIDA_S)
        if xa is None or len(xa) < BATIDA_MIN_S * SR:
            return None, "pouco do fim deste na fila para medir"
        if xb is None or len(xb) < BATIDA_MIN_S * SR:
            return None, "pouco do comeco da proxima para medir"
        ga, gb = batida.medir(xa, SR), batida.medir(xb, SR)
        if not ga.firme:
            # a rede, so antes do fade: com ele junto as batidas que vao sumindo puxam o andamento (o fim do
            # Despacito media 90,0 em vez de 89,0, e 1% em 14 s de sobreposicao e mais de 100 ms)
            antes = queda if fade else fim
            t_r, xr = _junta(blocos_a, antes - BATIDA_S, antes)
            g = _grade_rede(xr) if xr is not None and len(xr) >= BATIDA_MIN_S * SR else None
            if g is not None:
                ga, t_a = g, t_r
        if not gb.firme:
            g = _grade_rede(xb)
            if g is not None:
                gb = g
        if not ga.firme:
            return None, f"o fim deste sem batida firme, {ga.motivo}"
        # a grade da proxima e a do comeco dela, que e o que toca junto: a musica pode mudar de andamento depois
        # (o Lose Yourself vai de 65 BPM no piano a 86 quando entra a guitarra, aos 31 s)
        if not gb.firme and fade:
            return None, f"o comeco da proxima sem batida firme, {gb.motivo}"
        pa, pb = ga.periodo, gb.periodo
        a_longa, b_longa = t_a + ga.fase, t_b + gb.fase  # uma batida de cada grade dos 20 s (o bumbo escolheu o lado)

        def fase_em(blocos, t1, t2, periodo, quem, longa, x=None):
            """Uma batida (em s do disco) da grade de periodo dado, afinada em t1-t2 (ou no audio x, que comeca
            em t1), onde as duas soam juntas, perto da batida da grade longa: o pequeno erro do andamento soma
            ao estender a grade, e o esticamento desvia uns ms. O lado (batida ou contratempo) e o da grade
            longa, que o bumbo decidiu: o trecho curto sozinho caiu no contratempo do Overdose (21/10)."""
            t = t1
            if x is None:
                t, x = _junta(blocos, t1, t2)
            if x is None or len(x) < FASE_MIN_S * SR:
                return None, f"pouco {quem} para a fase"
            f, nota = batida.fase(x, SR, periodo, (longa - t) % periodo)
            if nota < NOTA_MIN:  # sem ataque claro para o pente (violao, piano, fala): as batidas da rede
                f = _fase_rede(x, periodo, (longa - t) % periodo)
                if f is None:
                    return None, f"{quem} sem batida clara onde as duas soam juntas (pente {nota:.1f}, nem pela rede)"
            return t + f, None

        inicios = np.array([t for t, _ in blocos_a])
        fim_arq = blocos_a[-1][0] + len(blocos_a[-1][1]) / SR

        def virada(t0):
            """O comeco do bloco deste em que t0 cai, quantos blocos de silencio faltam depois do arquivo e
            quantas amostras de silencio a proxima leva na frente para comecar exatamente em t0 (None se t0
            ja passou ou esta perto demais)."""
            if t0 < inicios[0] + FOLGA_S:
                return None, 0, 0
            if t0 >= fim_arq:
                k = int((t0 - fim_arq) * SR // BLOCK)
                v = fim_arq + k * BLOCK / SR
                return v, k, int(round((t0 - v) * SR))
            v = float(inicios[max(0, np.searchsorted(inicios, t0, side="right") - 1)])
            return v, 0, int(round((t0 - v) * SR))

        if not fade:
            a0, motivo = fase_em(blocos_a, fim - 8.0, fim, pa, "do fim deste", a_longa)
            if a0 is None:
                return None, motivo
            # a proxima no andamento deste, esticada como no fade: SEGURA_BATIDAS dele depois da primeira dela, e de
            # volta devagar ao dela. Sem batida firme no comeco dela, com os andamentos longe ou sem o comeco dela
            # decodificado para a volta, ela entra no andamento dela
            s = min((pb / (pa * m) for m in (0.5, 1.0, 2.0)), key=lambda v: abs(np.log(v)))
            esticada, sem = None, f"andamentos longe, {(s - 1) * 100:+.1f}%"
            if gb.firme and abs(s - 1) <= TEMPO_MAX:
                esticada, sem = _esticar_comeco(blocos_b, ini, s, int((pb / s + SEGURA_BATIDAS * pa) * SR))
            if esticada is not None:
                z, phi, ate, n_rampa = esticada
                # a primeira batida dela no que vai tocar, ja esticado: o desvio da Rubber Band fica de fora da conta
                tau, sem = fase_em(None, 0.0, None, pb / s, "do comeco da proxima", (b_longa - ini) / s,
                                   x=z[:int(6.0 * SR)])
                if tau is None:
                    esticada = None
                else:
                    if tau - pb / s >= -0.06:  # a primeira batida e o proprio comeco do som (ver o b1 abaixo)
                        tau -= pb / s
                    quem = (f"a primeira batida da proxima ({gb.bpm:.1f} BPM, a {(s - 1) * 100:+.2f}% por "
                            f"{SEGURA_BATIDAS} batidas deste e de volta em {n_rampa / SR:.1f} s)")
            if esticada is None:
                b1, motivo2 = (fase_em(blocos_b, ini, ini + 6.0, pb, "do comeco da proxima", b_longa)
                               if gb.firme else (None, gb.motivo))
                if b1 is None:  # comeco sem batida firme (intro sem bateria): a primeira nota dela cai na batida dele
                    b1, quem = ini, f"a primeira nota da proxima (o comeco dela sem batida firme: {motivo2})"
                else:
                    if b1 - pb >= ini - 0.06:
                        # a primeira batida e o proprio comeco do som: a grade da rede vem REDE_ATRASO antes dele, fora
                        # do trecho, e a fase caia uma batida adiante (o Mirage entrava meia batida fora do DATEN, 21/10)
                        b1 -= pb
                    quem = f"a primeira batida da proxima ({gb.bpm:.1f} BPM, no andamento dela: {sem})"
                tau = b1 - ini
            # a batida dele logo depois do fim do som (onde a passagem de volume viraria), e a proxima nunca
            # entra mais de FIM_CORTE_S antes desse fim: o que a passagem de volume toca, a no tempo nao corta
            # (o Bota Tudo Em Mim tem 2 s de silencio e 18 s baixinhos depois da musica; o plano mirava a queda
            # de 20 dB e cortava os 20 s)
            k = int(np.ceil((fim - TRANS_SECO_S - a0) / pa))
            while a0 + k * pa - tau < fim - FIM_CORTE_S:
                k += 1
            t0 = a0 + k * pa - tau
            v, silencio, pad = virada(t0)
            if v is None:
                return None, "a batida da virada ja passou"
            if esticada is None:
                ate = ini
                cabeca = [(max(0.0, ini - pad / SR), np.zeros((pad, 2), np.float32))] if pad else []
            else:
                saida = np.concatenate([np.zeros((pad, 2), np.float32), z]) if pad else z
                cabeca = []
                for u in range(0, len(saida), BLOCK):
                    t = ini + (phi[u - pad] / SR if u >= pad else (u - pad) / SR)
                    cabeca.append((max(0.0, t), saida[u:u + BLOCK]))
            sai = int(min(max(fim - t0, TRANS_SECO_S), 1.0) * SR)
            return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": silencio, "sai": sai,
                    "entra": pad + int(ENTRA_SECO_S * SR), "grave": None, "periodo_saida": pa,
                    "log": (f"final seco, {quem} em {a0 + k * pa:.2f} s, na grade deste ({ga.bpm:.1f} BPM), "
                            f"ela comeca em {t0:.3f} s")}, None
        s, m = min(((pb / (pa * m), m) for m in (0.5, 1.0, 2.0)), key=lambda v: abs(np.log(v[0])))
        if abs(s - 1) > TEMPO_MAX:
            # a proxima fica em TEMPO_MAX e a que sai anda o resto, se couber em SAI_MAX
            sa = (1 + TEMPO_MAX if s > 1 else 1 - TEMPO_MAX) / s
            if abs(sa - 1) > SAI_MAX:
                return None, f"andamentos longe, {ga.bpm:.1f} e {gb.bpm:.1f} BPM ({(s - 1) * 100:+.1f}%)"
            return self._plano_dois(blocos_a, blocos_b, ga, gb, s, sa, a_longa, b_longa, virar, sobrepor, baixo,
                                    ini, fase_em)
        a0, motivo = fase_em(blocos_a, virar - FASE_ANTES_S, baixo, pa, "do fim deste", a_longa)
        if a0 is None:
            return None, motivo
        n_sob = int(sobrepor * SR)
        esticada, motivo = _esticar_comeco(blocos_b, ini, s, n_sob)
        if esticada is None:
            return None, motivo
        z, phi, ate, n_rampa = esticada
        # a fase dela sai do que vai tocar, ja esticado: o pequeno desvio da Rubber Band fica de fora da conta
        tau, motivo = fase_em(None, 0.0, None, pb / s, "do comeco da proxima", (b_longa - ini) / s,
                              x=z[:int(max(FASE_MIN_S, sobrepor + 1.0) * SR)])
        if tau is None:
            return None, motivo
        t0 = a0 + round((virar + tau - a0) / pa) * pa - tau  # a primeira batida dela cai numa dele
        v, silencio, pad = virada(t0)
        if v is None:
            return None, "a batida da virada ja passou"
        if silencio:
            return None, "a virada no tempo caiu depois do fim do arquivo"
        # os graves trocam na batida dele mais perto do meio da sobreposicao, em meia batida: ate la a
        # proxima vem sem grave, dali em diante e o que sai que fica sem (no callback)
        tm = a0 + round((t0 + sobrepor / 2 - a0) / pa) * pa
        w0 = max(pad, pad + int((tm - t0 - pa / 4) * SR))
        w1 = w0 + int(pa / 2 * SR)
        corte = min(len(z), w1 - pad + SR // 2)
        grave = signal.sosfiltfilt(_GRAVE_LP, z[:corte], axis=0).astype(np.float32)
        entra_grave = np.clip((np.arange(corte) + pad - w0) / (w1 - w0), 0.0, 1.0).astype(np.float32)
        z[:corte] -= (1 - entra_grave)[:, None] * grave
        saida = np.concatenate([np.zeros((pad, 2), np.float32), z]) if pad else z
        cabeca = []
        for u in range(0, len(saida), BLOCK):
            t = ini + (phi[u - pad] / SR if u >= pad else (u - pad) / SR)
            cabeca.append((max(0.0, t), saida[u:u + BLOCK]))
        return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": 0, "sai": pad + n_sob, "entra": pad + n_sob,
                "grave": (w0, w1), "periodo_saida": pa,
                "log": (f"{ga.bpm:.1f} BPM saindo, {gb.bpm:.1f} BPM entrando, a proxima a {s * 100 - 100:+.2f}% "
                        f"ate o fim da sobreposicao e de volta em {n_rampa / SR:.1f} s, a primeira batida dela em "
                        f"{t0 + tau:.3f} s, na grade deste; os graves trocam em {tm:.2f} s")}, None

    def _plano_dois(self, blocos_a, blocos_b, ga, gb, s, sa, a_longa, b_longa, virar, sobrepor, baixo, ini, fase_em):
        """O fade-out no tempo com os andamentos a mais de TEMPO_MAX: a que sai vai devagar (RAMPA_TAXA) para a
        velocidade sa antes da sobreposicao, e a proxima entra esticada em TEMPO_MAX no andamento a que ela
        chegou. Os blocos deste a partir da rampa sao trocados pelos reamostrados, com a posicao do disco no
        rotulo (a tela e a virada leem a posicao); a batida deste na sobreposicao sai do audio ja mudado (pega o
        atraso da Rubber Band), e a virada e a troca de grave se contam em amostras da saida dele."""
        pa, pb = ga.periodo, gb.periodo
        sb = s * sa  # a velocidade da proxima: a grade dela cai na deste ja mudada
        n_ra = int(min(max(abs(sa - 1) / RAMPA_TAXA, RAMPA_MIN_S), RAMPA_MAX_S) * SR)
        # a rampa acaba antes do trecho onde a fase deste e medida: ali a velocidade ja e constante
        t_r = virar - FASE_ANTES_S - 0.5 - n_ra * (1 + sa) / 2 / SR
        if t_r < self.pos + SAI_FOLGA_S:
            return None, f"sem tempo para a que sai mudar {(sa - 1) * 100:+.1f}% antes da virada"
        t_r = next((t for t, _ in blocos_a if t >= t_r), None)
        if t_r is None:
            return None, "a rampa da que sai caiu depois do fim do arquivo"
        fim_arq = blocos_a[-1][0] + len(blocos_a[-1][1]) / SR
        _, xs_a = _junta(blocos_a, t_r, fim_arq)
        z_a, phi_a = esticar_saida(xs_a, sa, n_ra)

        def saida_a(t):
            """A amostra da saida deste (desde t_r) em que o disco passa em t."""
            return int(np.searchsorted(phi_a, (t - t_r) * SR))

        P = pa / sa * SR  # o periodo deste na saida, em amostras
        i1, i2 = saida_a(virar - FASE_ANTES_S), saida_a(baixo)
        perto = (saida_a(a_longa + round((virar - a_longa) / pa) * pa) - i1) / SR
        f, motivo = fase_em(None, 0.0, None, P / SR, "do fim deste (ja mudado)", perto, x=z_a[i1:i2])
        if f is None:
            return None, motivo
        a0 = i1 + f * SR  # uma batida deste, em amostras da saida dele
        n_sob = int(sobrepor * SR / sa)  # a sobreposicao, em amostras da saida
        # a proxima: como no caminho de um lado so, com a velocidade sb e a sobreposicao na saida
        esticada, motivo = _esticar_comeco(blocos_b, ini, sb, n_sob)
        if esticada is None:
            return None, motivo
        z, phi, ate, n_rampa = esticada
        tau, motivo = fase_em(None, 0.0, None, pb / sb, "do comeco da proxima", (b_longa - ini) / sb,
                              x=z[:int(max(FASE_MIN_S, n_sob / SR + 1.0) * SR)])
        if tau is None:
            return None, motivo
        # a primeira batida dela numa deste, a partir da virada; a proxima comeca na amostra t0 da saida deste
        i_v = saida_a(virar)
        t0 = int(round(a0 + round((i_v + tau * SR - a0) / P) * P - tau * SR))
        j, pad = divmod(t0, BLOCK)
        if j * BLOCK >= len(z_a):
            return None, "a virada no tempo caiu depois do fim do arquivo"
        v = t_r + phi_a[j * BLOCK] / SR
        tm = a0 + round((t0 + n_sob / 2 - a0) / P) * P  # a troca de grave na batida deste mais perto do meio
        w0 = max(pad, pad + int(tm - t0 - P / 4))
        w1 = w0 + int(P / 2)
        corte = min(len(z), w1 - pad + SR // 2)
        grave = signal.sosfiltfilt(_GRAVE_LP, z[:corte], axis=0).astype(np.float32)
        entra_grave = np.clip((np.arange(corte) + pad - w0) / (w1 - w0), 0.0, 1.0).astype(np.float32)
        z[:corte] -= (1 - entra_grave)[:, None] * grave
        saida = np.concatenate([np.zeros((pad, 2), np.float32), z]) if pad else z
        cabeca = []
        for u in range(0, len(saida), BLOCK):
            t = ini + (phi[u - pad] / SR if u >= pad else (u - pad) / SR)
            cabeca.append((max(0.0, t), saida[u:u + BLOCK]))
        novos = [(t_r + phi_a[u] / SR, z_a[u:u + BLOCK]) for u in range(0, len(z_a), BLOCK)]
        return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": 0, "sai": pad + n_sob, "entra": pad + n_sob,
                "grave": (w0, w1), "sai_q": (t_r, novos), "periodo_saida": P / SR,
                "log": (f"{ga.bpm:.1f} BPM saindo, {gb.bpm:.1f} BPM entrando, longe {(s - 1) * 100:+.1f}%: a que sai a "
                        f"{(sa - 1) * 100:+.2f}% em {n_ra / SR:.0f} s desde {t_r:.2f} s, a proxima a "
                        f"{(sb - 1) * 100:+.2f}% ate o fim da sobreposicao e de volta em {n_rampa / SR:.1f} s, a "
                        f"primeira batida dela na de {t_r + phi_a[min(len(phi_a) - 1, int(t0 + tau * SR))] / SR:.3f} s "
                        f"deste; os graves trocam "
                        f"{(tm - t0) / SR:.2f} s depois da entrada")}, None

    def _vira(self):
        """No callback de saida: a proxima vai para o prato; o que sai segue por baixo o tempo da
        sobreposicao, abaixando (sem sobreposicao, o resto dele, silencio, fica para tras)."""
        with self._qlock:
            prox = self._pronto
            if prox is None:
                return
            velho, sai, tag = self._deck, self.track, self.pronto_tag
            medida = self._virar_em is not None
            n = self._sobrepor if medida else 0
            grave = None
            if medida and self._grave is not None:
                grave = [_GRAVE_HP, np.zeros((_GRAVE_HP.shape[0], 2, 2)), *self._grave]
            self._saindo = [velho, n, 0, grave] if n and velho.q else None
            if self._saindo is None:
                velho.gen += 1
            ne = self._entrar if medida else 0
            self._entrando = [ne, 0] if ne else None
            self._deck = prox
            self._pronto = self.pronto_tag = self._virar_em = None
            prox.ahead = AHEAD
            self.track = prox.track
            self.pos = prox.q[0][0] if prox.q else 0.0
            self.ended = False
            self.virou = (sai, prox.track, tag)

    # comandos -------------------------------------------------------------
    def espera(self, track):
        """Poe o disco no prato carregando, ainda sem audio: o endereco do stream do YouTube
        leva 1 a 3 s para sair, e a tela ja mostra o que vai tocar."""
        with self._lock:
            self.track = track
            self.paused = False
            self._restart(0.0)

    def trocar_fonte(self, atual, novo):
        """Troca o audio do disco no prato sem cortar: da espera para o stream, ou do stream
        para o arquivo que acabou de baixar. O leitor novo comeca onde o
        audio ja decodificado termina, e o que esta na fila do cabo segue tocando. So vale se
        o prato ainda tem `atual` (o mesmo objeto): se ele trocou de disco no meio, nada muda."""
        with self._lock:
            if self.track is not atual:
                return False
            if not atual.get("path"):
                self.track = novo
                self._restart(self._clamp(self.pos))
                return True
            with self._qlock:
                t = self._q[-1][0] + len(self._q[-1][1]) / SR if self._q else self.pos
                dur = novo.get("duration") or 0
                self.track = novo
                if self.ended or self._eof_gen == self._gen or (dur and t >= dur - 2):
                    return True  # no fim (ou quase): o leitor de agora termina o disco
                self._gen += 1
                gen = self._gen
                self._eof_gen = -1
            threading.Thread(target=self._reader, args=(gen, novo, t, self._deck), daemon=True).start()
            return True

    def esperando_arquivo(self):
        """O stream do disco no prato falhou e ele espera o download para tocar (ver o _reader)."""
        return self._espera_arquivo is not None and self._espera_arquivo == self._gen

    def por_cima(self, track):
        """Toca o item junto do que estiver tocando, sem trocar a musica nem mexer na barra
        (decodifica inteiro, ate CURTO_MAX_S, ou RAPIDO_MAX_S no posto pela mao, numa thread;
        repetido sai do cache)."""
        threading.Thread(target=self._toca_sobre, args=(track,), daemon=True).start()

    def load(self, track, start=0.0, paused=False):
        with self._lock:
            self.track = track
            self.paused = paused
            self._restart(self._clamp(start))

    def _clamp(self, t):
        t = max(0.0, float(t))
        dur = (self.track or {}).get("duration") or 0
        return min(t, max(0.0, dur - 0.05)) if dur else t

    def pause(self):
        """Pausa o disco e cala os sons por cima: sem o Parar na tela (transporte do Spotify), o Pausar e o que silencia tudo."""
        self.paused = True
        self.calar_sobre()

    def calar_sobre(self):
        with self._slock:
            self._sobre = []

    def resume(self):
        with self._lock:
            if self.track is None:
                return
            if self.ended:
                self._restart(0.0)
            self.paused = False

    def stop(self):
        with self._lock:
            with self._qlock:
                self._cancela_passagem(tudo=True)
                self._gen += 1
                self._q.clear()
            self.track = None
            self.loop = False  # o Repetir vale para o disco do prato, e ele saiu
            self.paused = False
            self.ended = False
            self.error = None
            self.pos = 0.0
        self.calar_sobre()  # parar cala os sons por cima tambem

    def seek(self, t):
        with self._lock:
            if self.track is None:
                return
            self._restart(self._clamp(t))

    def set_loop(self, on):
        with self._lock:
            self.loop = bool(on)
            # ligou o loop depois que o leitor ja chegou ao fim: emenda outra volta
            if self.loop and self.track is not None and self._eof_gen == self._gen:
                if self.ended:
                    self._restart(0.0)
                else:
                    self._eof_gen = -1
                    threading.Thread(target=self._reader, args=(self._gen, self.track, 0.0, self._deck),
                                     daemon=True).start()

    @property
    def planejando(self):
        """A proxima esta preparada e a virada ainda nao foi marcada (o _mede espera o fim deste e planeja): o
        servidor nao mede andamento no meio (a rede de la e a de ca juntas passam de 1,5 GB)."""
        return self._pronto is not None and self._virar_em is None

    def status(self):
        if self.track is None:
            return "idle"
        if self.ended:
            return "ended"
        if self.paused:
            return "paused"
        if not self._q and self._eof_gen != self._gen:
            return "buffering"
        return "playing"

    def snapshot(self):
        tr = self.track
        return {
            "status": self.status(),
            "track": None if tr is None else {k: v for k, v in tr.items() if k not in ("path", "headers")},
            "duration": None if tr is None else tr.get("duration"),
            "vol": round(self.vol, 3), "mon_vol": round(self.mon_vol, 3),
            "mic_vol": round(self.mic_vol, 3), "mic_mute": self.mic_mute,
            "monitor_on": self.monitor_on, "loop": self.loop,
            "effect": self.effect, "voice_monitor": self.voice_monitor,
            "por_cima": [sb[0] for sb in self._sobre],
            "voice_mon_vol": round(self.voice_mon_vol, 3),
            "devices": dict(self.devices), "active_devices": dict(self.active),
            "error": self.error,
        }


class MockEngine(Engine):
    """Sem dispositivo de audio: um relogio de 10 ms chama o mesmo _out_cb e joga uma
    voz falsa no microfone. Serve pra testar interface sem som (server.py --mock)."""

    def _real_names(self):
        act = self.resolve()
        for k, kind in (("mic", "in"), ("out", "out"), ("monitor", "out")):
            if act[k]:
                try:
                    act[k] = find_dev(act[k], kind)[1]["name"]
                except ValueError:
                    pass
        return act

    def start(self, reserva=False):
        self.active = self._real_names()
        self._run = True
        threading.Thread(target=self._clock, daemon=True).start()

    def close(self):
        self._gen += 1
        self._run = False

    def set_devices(self, mic=None, out=None, monitor=None):
        for k, v in (("mic", mic), ("out", out), ("monitor", monitor)):
            if v is not None:
                self.devices[k] = v
        self.active = self._real_names()

    def _clock(self):
        out = np.zeros((BLOCK, 2), np.float32)
        rng = np.random.default_rng(7)
        k = 0
        nxt = time.perf_counter()
        while self._run:
            k += 1
            talk = (k // 100) % 3 == 0  # ~1 s de fala a cada 3 s
            self._push_mic((rng.standard_normal(BLOCK) * (0.08 if talk else 0.002))
                           .astype(np.float32))
            self._out_cb(out, BLOCK, None, None)
            self._mon.clear()
            nxt += BLOCK / SR
            time.sleep(max(0.0, nxt - time.perf_counter()))
