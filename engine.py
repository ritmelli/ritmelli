"""Motor de audio do soundboard: arquivo + microfone -> CABLE Input (o VRChat usa
o CABLE Output como microfone, entao a voz segue passando) e so o arquivo -> fone
de quem toca (sem ouvir a propria voz). Sucessor do mic_mix.py de 16/10:
o controle e por metodo (o server.py expoe por HTTP), nao por arquivo PAUSA/VOL."""
import base64
import collections
import contextlib
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import zlib

import numpy as np
import sounddevice as sd
from pedalboard import time_stretch
from scipy import signal

import batida
import compasso
import fx
import pastas

try:  # o pedal da mina: modulo de fora deste repo, posto ao lado do codigo so onde ela roda
    import mina
except ImportError:
    mina = None

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
STREAM_CAIU_S = 5.0  # o stream que para mais que isso antes do fim (ou sem audio nenhum) caiu: o servidor religa
RAPIDO_MAX_S = 120  # o posto nos Sons rapidos pela mao toca inteiro por cima ate isso (2 minutos)
# o stream aberto antes (09/11, a latencia do pedido falado): o servidor abre o ffmpeg do endereco adiantado logo que
# ele sai, antes de o disco entrar no prato; o leitor que toca esse endereco do comeco continua desse ffmpeg (o
# ffmpeg novo levava ~0,1 a 0,25 s ate o primeiro bloco: processo, TLS e o comeco do googlevideo). False desliga
PREABRE = True
PRE_S = 2.0        # o tanto do comeco que o aberto antes decodifica e guarda; depois o cano cheio segura o ffmpeg
PRE_VALE_S = 20.0  # o aberto antes que ninguem pegou nisso fecha sozinho
PRE_MAX = 2        # abertos antes ao mesmo tempo (o palpite torto da mina pode adiantar outro): o mais velho fecha
MINA_FOLGA_S = 0.1  # a voz da mina (mina.py) chega em pedacos de 100 ms, com folga de rede: a fila vazia recomeca com isso
MINA_FILA_MAX_S = 1.0  # fila dela maior que isso (a rede segurou e despejou): o silencio do comeco sai
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
# a passagem como a de um DJ (pedido dele, 06/11: no phonk o grave morria no comeco da queda e a proxima subia devagar,
# 6 s de trecho baixo em media): a troca e o fim do corpo da que sai (o comeco da queda, na batida dela mais perto); a
# proxima entra por baixo antes, no tempo e sem grave, subindo ate ficar cheia na troca; na troca os graves trocam em
# meia batida e a que sai some em poucas batidas
# (por baixo so entra a proxima que comeca quase sem som, como no final seco; a que se ouve desde o comeco entra na troca,
# pedido dele, 06/11: o funk tocava 22 s de voz sobre voz)
DJ_BATIDAS = 16            # a proxima entra isso de batidas deste antes da troca (4 compassos), sem o corpo dela medido...
DJ_MIN_BATIDAS = 8         # ... ou o tanto que o drop dela pede (a introducao inteira por baixo), em degraus de 4, entre
DJ_MAX_BATIDAS = 32        # estes dois...
DJ_MAX_S = 24.0            # ... e no maximo isso de segundos; com a introducao maior, ela comeca ja dentro dela
CORPO_DB = 3.0             # o corpo da proxima (o drop depois da introducao) comeca onde o nivel chega a isso do normal...
CORPO_FICA_S = 2.0         # ... e fica pelo menos isso
CORPO_MAX_S = 45.0         # drop medido depois disso do comeco nao vale (a proxima decodifica 75 s adiante)
DJ_SAI_BATIDAS = 4         # depois da troca, a que sai some nisso de batidas dela
DJ_NIVEL_ANTES = 0.5       # antes da troca a proxima sobe so ate a metade (-6 dB, o fader do DJ): os masters ja batem
                           # no teto e as duas cheias somavam o dobro; na troca ela vai a cheia, junto com o grave
ENTRA_SECO_S = 0.005       # no final seco no tempo, a proxima entra cheia (so o que evita o estalo)
FIM_CORTE_S = 1.0          # no final seco no tempo, a proxima entra no maximo isso antes do fim do som (o resto abaixa)
RABO_SECO_S = 3.0          # no final seco no tempo, o resto abaixo de FIM_DB depois da queda que dura ate isso e rabo
                           # (eco do ultimo golpe): a proxima entra na batida depois do fim para o ouvido, nao depois do
                           # rabo (a FATALITY tem 1,8 s dele, e a virada no fim do som deixava um vazio, 06/11); mais longo
                           # e musica baixinha que se toca (o Bota Tudo Em Mim, 18 s depois de 2 s de silencio)
INTRO_SECO_BATIDAS = 8     # no final seco no tempo, a proxima que comeca quase sem som (os primeiros INTRO_SECO_OUVE_S
INTRO_SECO_OUVE_S = 2.0    # FIM_DB abaixo do normal dela) e so chega ao corpo (medir_corpo) depois de pelo menos isso de
                           # batidas deste entra por baixo antes, como no fade, e o corpo dela cai onde o deste acaba (a
                           # WAKE UP sobe de -60 dB por 14 s; do comeco, depois de um final seco, era um vazio). Introducao
                           # que se ouve (a do Better, a -12 dB) entra do comeco, como sempre: por baixo seria voz sobre voz
SEGURA_BATIDAS = 8         # no final seco no tempo, a proxima fica no andamento deste isso de batidas dele depois da
                           # primeira dela e so entao volta devagar ao dela (escolhida em 24/10 entre a anterior, a
                           # esticada e a que entra por baixo antes do corte)
GOLPE_DB = 6.0             # o corte no 1 do final seco no tempo (a djeco, escolha dele, 06/11): o golpe final e a ultima
GOLPE_VOLTA = 8            # batida da grade com o pico a ate GOLPE_DB do normal das de antes, ate GOLPE_VOLTA batidas
GOLPE_PERTO = 2            # antes da que a proxima pegaria e no maximo GOLPE_PERTO batidas antes do fim do corpo; a
                           # primeira batida dela cai nele e o canal deste fecha ali (o 1 dela substitui o golpe dele)
CORTE_RAMPA_S = 0.010      # o fecho do canal deste, terminando CORTE_ANTES_S antes do golpe
CORTE_ANTES_S = 0.005
CORTE_TAU_MAX = 0.35       # com mais disso dela antes da primeira batida, o comeco dela tocaria por cima deste: sem corte
ECO_VOLTAS = 6             # o eco do mixer ligado antes de fechar o canal: o ultimo tempo deste (no tempo da proxima, o
ECO_NIVEL = 0.6            # do mixer depois da troca), sem grave, volta ECO_VOLTAS vezes, a primeira a ECO_NIVEL e cada
ECO_CAI = 0.5              # uma ECO_CAI da anterior (-6 dB)
ECO_MEDE_S = 30.0          # o tempo da proxima sai da rede nesse tanto do comeco dela: a rede ve 30 s por vez, e com
                           # menos as batidas saem irregulares (a Amo Minha Favela: 12 s irregulares, 30 s a 0,46 s)
_GRAVE_LP = signal.butter(2, GRAVE_HZ, "lowpass", fs=SR, output="sos")  # ida e volta: 4a ordem, fase zero
_GRAVE_HP = np.vstack([signal.butter(2, GRAVE_HZ, "highpass", fs=SR, output="sos")] * 2)  # Linkwitz-Riley
# o visor de DJ do tema (a onda do disco correndo, a grade de batidas e a proxima entrando na passagem): a onda sai em
# colunas de VISOR_PASSO com a energia de tres faixas, como a onda colorida do Rekordbox
VISOR_PASSO = 1 / 30       # 30 colunas por segundo: uma celula de pixel do visor por coluna (07/11, pedido do dono: com 25
                           # o passo da tela caia em 2 e 3 quadros de 60 Hz; com 30, sempre 2, e 4 em 120 Hz)
VISOR_SR = 12000           # o arquivo da prateleira se decodifica a parte so para a onda, nessa taxa
VISOR_FAIXAS = ((30.0, 200.0), (200.0, 2000.0), (2000.0, 6000.0))  # grave (bumbo e baixo), medio (voz, caixa), agudo
VISOR_DB = (-60.0, 0.0)    # a escala de cada faixa no byte: -60 dBFS = 0, 0 dBFS = 255
VISOR_CACHE = 8            # ondas guardadas na memoria (a do prato e a da proxima nunca saem)
ABAIXO_DO_NORMAL = 0x00004000 if sys.platform == "win32" else 0  # o ffmpeg da onda cede o processador ao audio


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


FIM_RETRATO_S = 40.0       # o resumo do fim no log: as janelas de FIM_JANELA_S nos ultimos isso antes do som acabar
FIM_JANELA_S = 5.0


def retrato_fim(niv, fim):
    """O nivel do fim do disco para o registro das passagens: (normal, t0, decimos, janelas). normal e o mesmo
    do medir_fim (o percentil 90 alisado, em dBFS); decimos e o nivel (dBFS) de cada decimo de segundo desde t0;
    janelas e o nivel medio de cada FIM_JANELA_S dos ultimos FIM_RETRATO_S antes do fim, relativo ao normal (dB).
    None sem nivel."""
    if not niv or fim is None:
        return None
    t, q, r = _niveis(niv)
    db = 20 * np.log10(np.maximum(r, 1e-6))
    alis = np.convolve(np.pad(db, 25, mode="edge"), np.ones(51) / 51, mode="valid")
    normal = float(np.percentile(alis, 90))
    t0 = float(t[0])
    n = max(0, int((fim - t0) / 0.1) + 1)
    k = np.clip(((t - t0) / 0.1).astype(int), 0, max(0, n - 1))
    soma, conta = np.bincount(k, r ** 2, minlength=n)[:n], np.bincount(k, minlength=n)[:n]
    decimos = [round(float(10 * np.log10(soma[i] / conta[i] + 1e-12)), 1) if conta[i] else None for i in range(n)]
    janelas = []
    a = fim - FIM_RETRATO_S
    while a < fim - 1e-6:
        sel = (t >= a) & (t < a + FIM_JANELA_S)
        janelas.append(round(float(10 * np.log10(np.mean(r[sel] ** 2) + 1e-12)) - normal, 1) if sel.any() else None)
        a += FIM_JANELA_S
    return round(normal, 1), t0, decimos, janelas


def ganho_sai(u, segura, n):
    """O volume do que sai na amostra u desde a virada: cheio ate segura, depois um quarto de cosseno ate n."""
    return np.cos(np.clip((u - segura) / max(1, n - segura), 0.0, 1.0) * (np.pi / 2)).astype(np.float32)


def ganho_entra(u, n, nivel=1.0, cheia=0):
    """O volume da proxima na amostra u desde a virada: um quarto de seno ate nivel em n; com nivel abaixo de 1, dali
    sobe reto ate cheio em cheia (a troca de grave da passagem de DJ)."""
    g = nivel * np.sin(np.minimum(u / max(1, n), 1.0) * (np.pi / 2))
    if nivel < 1.0:
        g = g + (1.0 - nivel) * np.clip((u - n) / max(1, cheia - n), 0.0, 1.0)
    return g.astype(np.float32)


def nivel_trecho(niv, a, b):
    """O nivel medio (potencia) dos blocos entre a e b, em dB relativos ao normal do que esta decodificado (o percentil 90
    alisado em meio segundo, o mesmo do medir_corpo). None sem nivel no trecho."""
    if not niv:
        return None
    t, q, r = _niveis(niv)
    db = 20 * np.log10(np.maximum(r, 1e-6))
    alis = np.convolve(np.pad(db, 25, mode="edge"), np.ones(51) / 51, mode="valid")
    no = (t >= a) & (t < b)
    if not no.any():
        return None
    return float(10 * np.log10(np.mean(r[no] ** 2) + 1e-12) - np.percentile(alis, 90))


def medir_corpo(niv, ini):
    """Onde comeca o corpo do disco (o drop depois da introducao): o primeiro ponto desde ini em que o nivel alisado
    (meio segundo) chega a CORPO_DB do normal (o percentil 90 do que esta decodificado) e fica CORPO_FICA_S. None sem
    nivel ou sem corpo ate CORPO_MAX_S."""
    if not niv:
        return None
    t, q, r = _niveis(niv)
    db = 20 * np.log10(np.maximum(r, 1e-6))
    alis = np.convolve(np.pad(db, 25, mode="edge"), np.ones(51) / 51, mode="valid")
    ok = alis >= np.percentile(alis, 90) - CORPO_DB
    fica = int(CORPO_FICA_S * SR / BLOCK)
    for i in np.nonzero(ok & (t >= ini) & (t <= ini + CORPO_MAX_S))[0]:
        if ok[i:i + fica].all():
            return float(t[i])
    return None


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


def _golpe_final(blocos, b1, pa, queda):
    """O golpe final deste para o corte no 1 do final seco: a ultima batida da grade antes de b1 (a batida em que a
    proxima entraria depois do fim para o ouvido) com o pico a ate GOLPE_DB do normal das de antes (o percentil 75 dos
    picos de 2 a 29 batidas antes de b1), no maximo GOLPE_VOLTA batidas antes de b1 e GOLPE_PERTO antes do fim do corpo
    (queda). None sem o audio ou sem golpe: no SENTADAO o golpe e o 1 do ultimo compasso, a 1,4 s do b1 e 0,4 s antes da
    queda, e o resto e o eco gravado dele."""
    t, x = _junta(blocos, b1 - 30 * pa - 0.1, b1 + 0.2)
    if x is None:
        return None
    m = x.mean(axis=1)
    h = int(0.01 * SR)

    def pico(tb):
        i, j = int(round((tb - 0.05 - t) * SR)), int(round((tb + 0.15 - t) * SR))
        if i < 0 or j > len(m):
            return None
        a = m[i:j]
        a = a[:len(a) // h * h].reshape(-1, h)
        return 10 * np.log10(max(1e-10, float((a * a).mean(axis=1).max())))

    picos = [p for p in (pico(b1 - k * pa) for k in range(2, 30)) if p is not None]
    if len(picos) < 8:
        return None
    ref = float(np.percentile(picos, 75))
    for k in range(1, GOLPE_VOLTA + 1):
        tb = b1 - k * pa
        if tb < queda - GOLPE_PERTO * pa:
            return None
        p = pico(tb)
        if p is not None and p >= ref - GOLPE_DB:
            return tb
    return None


def _batida_tocada(x, reserva):
    """O tempo da proxima como ela vai tocar (o periodo mediano das batidas da rede no comeco dela, ja esticado), para o
    eco do corte: a grade dos juizes pode cair no 3 por 2 (a Amo Minha Favela, de 130 BPM, medida a 86,6). Sem a rede,
    com pouco audio ou com as batidas irregulares, reserva."""
    r = compasso.uns(x, SR) if x is not None and len(x) >= 0.8 * ECO_MEDE_S * SR else None
    if r is None or len(r[0]) < 6:
        return reserva
    ibi, ok = _regular(r[0])
    return float(np.median(ibi)) if ok else reserva


def _eco_corte(blocos, golpe, d):
    """O eco do corte no 1: o ultimo tempo (d s) deste antes do golpe, com o fecho do canal, sem grave, repetido a cada d
    s a partir do golpe, ECO_NIVEL na primeira volta e ECO_CAI a cada uma das ECO_VOLTAS. None sem o audio."""
    t, x = _junta(blocos, golpe - d - 0.1, golpe + 0.1)
    if x is None:
        return None
    i0, i1 = int(round((golpe - d - t) * SR)), int(round((golpe - CORTE_ANTES_S - t) * SR))
    if i0 < 0 or i1 > len(x) or i1 - i0 < int(0.05 * SR):
        return None
    y = x[i0:i1].astype(np.float32)
    nr, nf = min(len(y), int(CORTE_RAMPA_S * SR)), int(0.005 * SR)
    g = np.ones(len(y), np.float32)
    g[len(y) - nr:] = ganho_sai(np.arange(nr), 0, nr)
    g[:nf] *= np.linspace(0.0, 1.0, nf, dtype=np.float32)
    y = signal.sosfilt(_GRAVE_HP, y * g[:, None], axis=0).astype(np.float32)
    nd = int(round(d * SR))
    eco = np.zeros(((ECO_VOLTAS - 1) * nd + len(y), 2), np.float32)
    for r in range(ECO_VOLTAS):
        eco[r * nd:r * nd + len(y)] += y * np.float32(ECO_NIVEL * ECO_CAI ** r)
    return eco


def colunas_onda(x, sr):
    """As colunas da onda do visor do audio mono x, que comeca num limite de coluna: (n, 3) bytes, a energia do grave,
    do medio e do agudo (VISOR_FAIXAS) em cada coluna inteira de VISOR_PASSO, em dB na escala VISOR_DB. A mesma conta a
    12 kHz (o arquivo, a parte) e a 48 kHz (o stream, no leitor): as faixas de frequencia sao as mesmas (30 Hz por
    faixa da FFT nas duas, com o passo de 1/30) e a potencia sai normalizada pela janela, entao as duas ondas batem. Em pedacos de 1 s: a
    conta inteira de uma vez prende o interpretador e o audio do cabo espera."""
    m = int(round(sr * VISOR_PASSO))
    n = len(x) // m
    out = np.zeros((n, 3), np.uint8)
    if not n:
        return out
    w = np.hanning(m).astype(np.float32)
    f = np.fft.rfftfreq(m, 1.0 / sr)
    faixas = [(f >= a) & (f < b) for a, b in VISOR_FAIXAS]
    esc = 2.0 / (m * float((w * w).sum()))  # soma do espectro -> media quadratica do sinal na faixa (Parseval)
    lo, hi = VISOR_DB
    por = int(round(1.0 / VISOR_PASSO))
    for a in range(0, n, por):
        q = np.asarray(x[a * m:min(n, a + por) * m], np.float32).reshape(-1, m) * w
        p = np.abs(np.fft.rfft(q, axis=1)) ** 2
        for j, fx_ in enumerate(faixas):
            db = 10.0 * np.log10(p[:, fx_].sum(axis=1) * esc + 1e-12)
            out[a:a + len(q), j] = np.clip((db - lo) / (hi - lo) * 255.0, 0.0, 255.0).astype(np.uint8)
    return out


class Onda:
    """A onda de um disco para o visor do tema: colunas de VISOR_PASSO (grave, medio, agudo), escritas aos pedacos. O
    disco da prateleira e lido inteiro a parte (fonte "arquivo"); o do stream, conforme o leitor decodifica (fonte
    "stream": o futuro so aparece ate onde ja decodificou, ~2 s, e na passagem o fim deste e o comeco da proxima
    inteiros). Coluna nao escrita fica zero."""

    def __init__(self, fonte, dur=None):
        self.fonte = fonte
        self.cols = np.zeros((int(np.ceil((dur or 0) / VISOR_PASSO)) + 1, 3), np.uint8)
        self.n = 0              # colunas ate a ultima escrita
        self.completa = False
        self.versao = 0

    def escreve(self, c0, cols):
        fim = c0 + len(cols)
        if c0 < 0 or not len(cols):
            return
        if fim > len(self.cols):
            mais = np.zeros((max(fim, len(self.cols) * 3 // 2) - len(self.cols), 3), np.uint8)
            self.cols = np.concatenate([self.cols, mais])
        self.cols[c0:fim] = cols
        self.n = max(self.n, fim)
        self.versao += 1


class _AcumOnda:
    """A onda do stream feita no leitor: junta 1 s de audio decodificado e escreve as colunas dele (uma FFT de 25
    colunas por segundo de audio, fora do lock do callback). Um por leitor: os blocos chegam em seguida, sem buraco."""

    def __init__(self, motor, onda):
        self.motor, self.onda = motor, onda
        self.t0, self.buf, self.tam = None, [], 0

    def bloco(self, t, arr):
        if not len(arr):
            return
        if self.t0 is None:
            self.t0 = t
        self.buf.append(arr.mean(axis=1))
        self.tam += len(arr)
        if self.tam >= SR:
            self.escreve()

    def escreve(self):
        if not self.buf:
            return
        x = np.concatenate(self.buf)
        m = int(round(SR * VISOR_PASSO))
        c0 = int(np.ceil(self.t0 / VISOR_PASSO - 1e-6))
        de = max(0, int(round((c0 * VISOR_PASSO - self.t0) * SR)))
        k = (len(x) - de) // m
        if k > 0:
            cols = colunas_onda(x[de:de + k * m], SR)
            with self.motor._olock:
                self.onda.escreve(c0, cols)
            resto = x[de + k * m:]
            self.t0 = (c0 + k) * VISOR_PASSO
        else:
            resto = x
        self.buf, self.tam = ([resto], len(resto)) if len(resto) else ([], 0)
        if not len(resto):
            self.t0 = None


def _visor_grade(g, fase, de, ate):
    """A grade de batidas para o visor: o periodo e uma batida no tempo do proprio disco, e o trecho onde ela vale."""
    return {"bpm": round(float(g.bpm), 2), "periodo": float(g.periodo), "fase": float(fase), "de": float(de),
            "ate": float(ate)}


def _visor_rampa(ini, ate, s, n_sob, n_rampa):
    """A velocidade da proxima no visor, a mesma conta do esticar: s por n_sob amostras de saida e a volta a 1 em
    n_rampa, meio cosseno de amplitude k (a soma do meio cosseno de n amostras e n/2 + 1/2). (vb, sob, rampa, k), os
    tempos em s de saida."""
    alvo = int(round((ate - ini) * SR))
    return float(s), n_sob / SR, n_rampa / SR, float((alvo - s * n_sob - n_rampa) / (n_rampa / 2 + 0.5))


def _visor_publico(de, para, visor):
    """A passagem no formato do visor (ver o Engine.snapshot), com os numeros arredondados para o estado sair curto."""
    def r(v):
        if isinstance(v, dict):
            return {k: r(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [r(x) for x in v]
        if isinstance(v, (float, np.floating)):
            return round(float(v), 4)
        return v
    return {"de": (de or {}).get("id"), "para": (para or {}).get("id"), **r(visor)}


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


def _mic_padrao(d):
    """O microfone padrao do Windows; se ele e o cabo, o primeiro microfone de verdade da lista (None sem nenhum). No
    notebook do bot o padrao de gravacao e o CABLE Output, por onde o VRChat dele fala, e o cabo como microfone e
    recusado (a voz voltaria em eco): com o microfone escolhido desligado o audio nem abria (08/11)."""
    pad = d["default_input"]
    if pad is None or "cable" not in pad.lower():
        return pad
    return next((x for x in d["inputs"] if "cable" not in x.lower()), None)


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


def _aviso_reserva(faltou):
    """A frase da tela quando a partida usou a reserva: o que faltou e o que entrou no lugar."""
    sumiu = " nem o ".join(f'{nome} "{escolhido}"' for nome, escolhido, _ in faltou)
    usou = " e ".join(f'"{usado}"' if usado else "nenhum fone" for _, _, usado in faltou)
    volta = "ele voltar" if len(faltou) == 1 else "eles voltarem"
    return f"Não achei o {sumiu}; usei {usou} até {volta}."


class Preaberto:
    """O ffmpeg de um stream aberto antes de o disco entrar no prato (Engine.preabre): uma thread le ate PRE_S do
    comeco em blocos e para (o cano cheio segura o ffmpeg). pega() para essa thread (espera o bloco em curso) e entrega
    os blocos lidos e o ffmpeg ao leitor do prato, uma vez; ninguem pegou em PRE_VALE_S, ele fecha sozinho."""

    def __init__(self, url, entrada):
        self.url, self.t = url, time.monotonic()
        self.blocos = []
        self.morto = False
        self._pego = False
        self._lk = threading.Lock()
        self.ff = subprocess.Popen([FFMPEG, "-v", "error", *entrada, "-ss", "0.0", "-i", url,
                                    "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        self._th = threading.Thread(target=self._le, daemon=True, name="vitrola-preabre")
        self._th.start()
        self._vence = threading.Timer(PRE_VALE_S, self.fecha)
        self._vence.daemon = True
        self._vence.start()

    def _le(self):
        n, teto = 0, int(PRE_S * SR) * 8
        try:
            while n < teto:
                with self._lk:
                    if self._pego:
                        return
                b = self.ff.stdout.read(BLOCK * 8)
                if not b:
                    return
                self.blocos.append(b)
                n += len(b)
        except (OSError, ValueError):  # fechado no meio
            return

    def pega(self):
        """(blocos ja lidos, ffmpeg) para o leitor do prato, ou None se ele ja fechou (venceu ou foi o mais velho)."""
        with self._lk:
            if self._pego:
                return None
            self._pego = True
        self._vence.cancel()
        self._th.join()
        return self.blocos, self.ff

    def fecha(self):
        with self._lk:
            if self._pego:
                return
            self._pego = self.morto = True
        self.ff.kill()
        try:
            self.ff.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


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
        # a mina do pedal MINA (mina.py): a voz dela vai pro cabo e pro fone como a voz de quem toca
        self.mina_permitida = True
        self._mina = None
        self._mina_buf = np.zeros(0, np.float32)
        self._mina_lock = threading.Lock()
        self._mina_voz_em = -1e9  # monotonic do ultimo pedaco com voz dela que tocou
        self._mina_int_n = 0  # amostras da frente da fila que sao a interjeicao dela (nao seguram o guarda)
        self._fone_calado = False  # a mina ouvindo o aparelho inteiro que e o fone: o fone fica mudo (mina_cala_fone)
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
        # o primeiro som do disco que entrou no prato (09/11, a latencia do pedido falado): espera e load marcam
        # (id, hora do relogio), o _out_cb troca pelo (titulo, stream?, entrou, soou) no primeiro bloco dele, e o
        # servidor tira e escreve no log (nada de print no callback)
        self._prato = None
        self._soou = None
        self._preabertos = {}  # url -> Preaberto (ver preabre), sob _pre_lock
        self._pre_usados = {}  # url -> monotonic em que um leitor o pediu: o aberto antes que chega depois nao abre
        self._pre_lock = threading.Lock()
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
        self._segura = 0         # quadros depois da virada em que o que sai segue cheio (a passagem de DJ: ate a troca)
        self._nivel_entra = 1.0  # ate onde a proxima sobe em _entrar quadros (a passagem de DJ: a metade)...
        self._cheia = 0          # ... e em que quadro ela fica cheia (o fim da troca de grave)
        self._grave = None       # (de, ate) em quadros desde a virada: a troca de grave da passagem no tempo
        self._saindo = None      # [deck, quadros, feitos, grave, segura]: o disco que sai, abaixando por baixo
        self._eco = None         # [audio, feitos]: o eco do corte no 1, por cima da que entra (feitos < 0: ainda nao)
        self._eco_plano = None   # (audio, quadros depois da virada) do plano medido, ate a virada
        self._entrando = None    # [quadros, feitos, nivel, cheia]: a proxima subindo
        self.virou = None        # (o que saiu, o que entrou, a tag) para o servidor tirar da fila
        self.periodo_saida = None  # a batida do que sai na saida (s), pelo plano no tempo: a regua dos testes (dev/)
        self.pronto_falhou = None  # a tag da proxima que nao decodificou: o servidor nao prepara de novo
        # o servidor religa a parecida do Automatico cujo stream caiu: religar_stream(disco, onde parou, desistir), na
        # thread do leitor; sem ele (ou desistindo), o disco acaba e a fila segue, como antes
        self.religar_stream = None
        # o visor de DJ do tema: as ondas por id do disco (_onda_pede, onda) e a passagem que vem e a que acabou de
        # acontecer, no formato do visor (_mede, _vira; ver o snapshot)
        self._ondas = collections.OrderedDict()
        self._olock = threading.Lock()
        self._ondas_versao = 0   # sobe quando uma onda do arquivo fica pronta: o tema pede de novo
        self._onda_fila = None   # a fila da thread da onda do arquivo (sobe no primeiro pedido)
        self._onda_lendo = set()  # os ids com a onda do arquivo na fila ou sendo lida
        self._visor_pas = None   # a passagem medida deste para a proxima
        self._visor_feita = None  # a que trouxe este disco, enquanto o tema ainda desenha a sobreposicao
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
            mic = _mic_padrao(d)
        if mon == "default":
            mon = d["default_output"] or ""
            if "cable" in mon.lower():
                mon = ""
        return {"mic": mic, "out": self.devices["out"], "monitor": mon}

    def _reserva(self, act, d=None, fixos=()):
        """O mic ou o fone escolhidos que nao estao conectados caem no padrao do Windows (o mic
        pula o cabo, ver _mic_padrao): o Quest desligado leva o fone do Virtual Desktop junto, e o
        servidor nao subia (20/10). Devolve (o que abrir, o que faltou: nome, escolhido, usado); a
        escolha do usuario continua gravada. fixos = o que a pessoa acabou de escolher na tela: esse
        nao cai na reserva, e o find_dev do start recusa se nao existe."""
        d = d or list_devices()
        faltou = []
        for k, lista, nome in (("mic", d["inputs"], "microfone"), ("monitor", d["outputs"], "fone")):
            if k in fixos or not act[k] or _na_lista(act[k], lista):
                continue
            pad = _mic_padrao(d) if k == "mic" else d["default_output"] or ""
            if pad is None:
                continue  # sem microfone nenhum: o find_dev do start avisa
            if k == "monitor" and "cable" in pad.lower():
                pad = ""
            faltou.append((nome, act[k], pad))
            act[k] = pad
        return act, faltou

    def _desejado(self, d):
        """Os nomes que a partida com reserva abriria com a lista d."""
        act, _ = self._reserva(self.resolve(d), d)
        return {"mic": _na_lista(act["mic"], d["inputs"]),
                "monitor": _na_lista(act["monitor"], d["outputs"]) or ""}

    def start(self, reserva=False, fixos=()):
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
            act, faltou = self._reserva(act, fixos=fixos)
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
            self._aviso = self.error = _aviso_reserva(faltou)
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
        if self._mina is not None:
            self._mina.desliga()
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
            # so o que veio na troca tem que existir; o outro escolhido que esta desligado segue na reserva: trocar o
            # mic pro do notebook com o fone da UMC desligada recusava tudo (08/11)
            fixos = tuple(k for k, v in (("mic", mic), ("monitor", monitor)) if v is not None)
            try:
                self.start(reserva=True, fixos=fixos)
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
        mi = self._mina
        # a mina ouve quem toca tambem (a voz crua, sem o efeito), mas so com a voz indo pro jogo: com a voz cortada
        # (o notebook do bot) o mic nao e a voz de ninguem no mapa, e ela ouvia quem estava do lado do notebook (03/11)
        if mi is not None and not self.mic_mute:
            mi.microfone(x)
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
        if effect_id == "mina":
            self._mina_liga()
        elif self._mina is not None:
            self._mina.desliga()

    # a mina (mina.py) -----------------------------------------------------
    def _mina_liga(self):
        if not self.mina_permitida or mina is None:
            return
        if self._mina is None:
            self._mina = mina.Mina(self)
        try:
            self._mina.liga()
        except ValueError as ex:  # sem a chave: o pedal fica aceso e o aviso sai na interface
            self.error = str(ex)

    def mina_voz(self, x):
        """A voz dela, float32 48 kHz mono, na fila do cabo. Volta em quantos segundos ela comeca a tocar (a gravacao
        da mina poe o texto dela na hora do som)."""
        n = len(x)
        with self._mina_lock:
            if not len(self._mina_buf):
                x = np.concatenate([np.zeros(int(MINA_FOLGA_S * SR), np.float32), x])
            b = np.concatenate([self._mina_buf, x])
            if len(b) > MINA_FILA_MAX_S * SR:  # a rede despejou: o silencio do comeco sai
                k = 0
                while len(b) - k > MINA_FOLGA_S * SR and np.max(np.abs(b[k:k + BLOCK])) < mina.QUIET_RMS:
                    k += BLOCK
                b = b[k:]
                self._mina_int_n = max(0, self._mina_int_n - k)
            self._mina_buf = b
            return (len(b) - n) / SR

    def mina_cala(self):
        """Interromperam a mina (ElevenAgents, mina.CEDE_EL): a voz dela que ainda nao tocou sai da fila."""
        with self._mina_lock:
            self._mina_buf = self._mina_buf[:0]
            self._mina_int_n = 0

    def mina_interjeicao(self, x):
        """A interjeicao dela (mina.py), float32 48 kHz mono, na hora em que quem fala com ela parou: so entra com a
        fila so de silencio (a resposta do GPT-Live ainda nao chegou; quando chega, toca logo depois dela) e nao
        conta como a voz dela pro guarda, que segue mandando o jogo pro GPT-Live. Volta se entrou."""
        with self._mina_lock:
            b = self._mina_buf
            if len(b) and float(np.max(np.abs(b))) >= mina.QUIET_RMS:  # a voz da resposta ja esta na fila
                return False
            # o que estava na fila e o silencio que o GPT-Live manda sem parar com a sessao aberta (a fila vazia,
            # como era a condicao, nunca acontecia: no jogo de 01/11 nenhuma interjeicao entrou)
            self._mina_buf = np.asarray(x, np.float32)
            self._mina_int_n = len(self._mina_buf)
        return True

    def mina_cala_fone(self, aparelho):
        """A mina ouvindo o aparelho inteiro (sem o loopback por processo): se o fone e ele, o fone fica mudo
        enquanto ela esta ligada, senao a musica e a voz dela entram no ouvido dela. None devolve o fone."""
        fone = (self.active.get("monitor") or "").strip().lower()
        a = (aparelho or "").strip().lower()
        calar = bool(a and fone and (a == fone or a.startswith(fone) or fone.startswith(a)))
        if calar != self._fone_calado:
            self._fone_calado = calar
            print(f"mina: {'calei o fone (' + self.active['monitor'] + '), que e o aparelho que ela ouve' if calar else 'fone de volta'}",
                  file=sys.stderr, flush=True)

    def mina_falando(self):
        """A voz dela tocando agora (ou ate mina.TAIL_S depois): o guarda dela segura o jogo."""
        return time.monotonic() - self._mina_voz_em < mina.TAIL_S

    def _mina_tira(self, frames):
        if not len(self._mina_buf):
            return None
        with self._mina_lock:
            m, self._mina_buf = self._mina_buf[:frames], self._mina_buf[frames:]
            k = min(len(m), self._mina_int_n)  # a interjeicao nao segura o guarda
            self._mina_int_n -= k
        v = m[k:]
        if len(v) and float(np.sqrt(np.mean(v * v))) >= mina.QUIET_RMS:
            self._mina_voz_em = time.monotonic()
        return m

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
            p, tr = self._prato, self.track
            if item and p is not None and tr.get("id") == p[0]:
                self._prato = None
                self._soou = (tr.get("title"), str(tr.get("path") or "").startswith("http"), p[1], time.time())
        som = None  # arquivo + sons por cima, antes do volume
        if item:
            som = np.zeros((frames, 2), np.float32)
            n = 0
            for _, s in item:
                som[n:n + len(s)] = s
                n += len(s)
            self.pos = item[-1][0] + len(item[-1][1]) / SR
            ent = self._entrando
            if ent is not None:  # a proxima subindo: um quarto de seno (e na passagem de DJ, ate cheia na troca)
                g = ganho_entra(ent[1] + np.arange(n), ent[0], ent[2], ent[3])
                som[:n] *= g[:, None]
                ent[1] += n
                if ent[1] >= max(ent[0], ent[3]):
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
                g = ganho_sai(u, sai[4], sai[1])
                if sai[3] is not None:  # a troca de grave: o grave dele sai enquanto o da proxima entra
                    gr = sai[3]
                    agudo, gr[1] = signal.sosfilt(_GRAVE_HP, s, axis=0, zi=gr[1])
                    fica = (1 - np.clip((u - gr[2]) / (gr[3] - gr[2]), 0.0, 1.0)).astype(np.float32)
                    s = agudo + fica[:, None] * (s - agudo)
                if som is None:
                    som = np.zeros((frames, 2), np.float32)
                som[:n] += s * g[:, None]
                sai[2] += n
        eco = self._eco
        if eco is not None and not self.paused:  # o eco do corte no 1, comecando no golpe
            a, p = eco
            i0 = max(0, -p)
            if i0 < frames:
                k = min(frames - i0, len(a) - max(0, p))
                if k > 0:
                    if som is None:
                        som = np.zeros((frames, 2), np.float32)
                    som[i0:i0 + k] += a[max(0, p):max(0, p) + k]
            eco[1] = p + frames
            if eco[1] >= len(a):
                self._eco = None
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
        mv = self._mina_tira(frames)
        if mv is not None and len(mv):  # a mina: no cabo como a voz, e no fone pra quem toca ouvir o que ela fala
            if self._mina is not None:
                self._mina.tocou(mv)  # so enfileira: a gravacao dela
            n = len(mv)
            buf[:n, 0] += mv
            buf[:n, 1] += mv
            if com_fone:
                if fone is None:
                    fone = np.zeros((frames, 2), np.float32)
                fone[:n, 0] += mv * self.voice_mon_vol
                fone[:n, 1] += mv * self.voice_mon_vol
        if fone is not None and not self._fone_calado:
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

    # o stream aberto antes (ver PREABRE) ------------------------------------
    def preabre(self, url, headers=None):
        """Abre ja o ffmpeg do stream de url (o endereco adiantado de um pedido falado), sem tocar: o leitor que tocar
        esse url do comeco em PRE_VALE_S continua dele. Volta se abriu agora."""
        if not PREABRE or not str(url or "").startswith("http"):
            return False
        with self._pre_lock:
            self._pre_poda()
            if url in self._preabertos or url in self._pre_usados:  # o leitor ja abriu o dele: este ficaria orfao
                return False
        p = Preaberto(url, self._entrada({"stream": True, "path": url, "headers": headers}))  # o Popen fora da trava
        fora = []
        with self._pre_lock:
            # outro abriu o mesmo junto, ou o leitor pediu esse endereco durante o Popen (o set_result acorda o leitor
            # e o _preabre juntos: sem conferir de novo, o deste ficava orfao; revisao da r09, 20 em 20)
            if url in self._preabertos or url in self._pre_usados:
                fora.append(p)
            else:
                while len(self._preabertos) >= PRE_MAX:
                    fora.append(self._preabertos.pop(next(iter(self._preabertos))))
                self._preabertos[url] = p
        for x in fora:
            x.fecha()
        return p not in fora

    def _pre_pega(self, url):
        """O (blocos, ffmpeg) aberto antes para url, uma vez, ou None."""
        with self._pre_lock:
            self._pre_poda()
            p = self._preabertos.pop(url, None)
            self._pre_usados[url] = time.monotonic()
        return p.pega() if p is not None else None

    def _pre_poda(self):
        for u in [u for u, p in self._preabertos.items() if p.morto]:
            del self._preabertos[u]
        agora = time.monotonic()
        for u in [u for u, t in self._pre_usados.items() if agora - t > PRE_VALE_S]:
            del self._pre_usados[u]

    def _reader(self, gen, track, start, deck):
        t = start
        path = track["path"]
        stream = str(path).startswith("http")  # o YouTube direto, antes de o download chegar
        pre = self._pre_pega(path) if stream and start == 0 else None
        while gen == deck.gen:
            if pre is not None:
                blocos, ff = pre
                pre = None
                print(f"stream: {track.get('title')!r} entrou pelo ffmpeg aberto antes "
                      f"({sum(map(len, blocos)) / 8 / SR:.2f} s ja decodificados)", file=sys.stderr, flush=True)
            else:
                blocos = []
                ff = subprocess.Popen([FFMPEG, "-v", "error", *self._entrada(track), "-ss", str(t), "-i", path,
                                       "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      creationflags=NO_WINDOW)
            n = 0
            # o stream nao tem arquivo para a onda do visor ler a parte: ela sai do que este leitor decodifica
            acc = self._onda_acumulador(track) if stream else None
            try:
                while gen == deck.gen:
                    if len(deck.q) > deck.ahead:
                        time.sleep(0.01)
                        continue
                    b = blocos.pop(0) if blocos else ff.stdout.read(BLOCK * 8)
                    if not b:
                        break
                    arr = np.frombuffer(b[: len(b) // 8 * 8], np.float32).reshape(-1, 2)
                    rms = float(np.sqrt(np.mean(arr * arr))) if len(arr) else 0.0  # fora do lock do callback
                    if acc is not None:
                        acc.bloco(t + n / SR, arr)
                    with self._qlock:
                        if gen != deck.gen:
                            break
                        deck.q.append((t + n / SR, arr))
                        deck.niveis.append((t + n / SR, len(arr), rms))
                    n += len(arr)
            finally:
                ff.kill()
                ff.wait()
                if acc is not None:
                    acc.escreve()
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
            # a parecida do Automatico (stream sem download) que o YouTube parou de mandar: sem audio nenhum, ou mais
            # que STREAM_CAIU_S antes do fim; o servidor tira um endereco novo e toca de onde parou (08/11: a H.S.K.T.
            # acabou na hora que entrou e a fila pulou calada para a seguinte, com a mina dizendo o nome dela)
            fim, dur = t + n / SR, track.get("duration") or 0
            caiu = fim < dur - STREAM_CAIU_S if dur else n == 0
            religar = self.religar_stream
            if stream and caiu and not track.get("job") and deck is self._deck and religar is not None:
                religar(track, fim, lambda: self._stream_desistiu(deck, gen, track, fim))
                return
            if n == 0:
                self._erro_de_leitura(track, t)
                deck.eof_gen = gen
                return
            if not self.loop or deck is not self._deck:
                deck.eof_gen = gen
                return
            t = 0.0
        if pre is not None:  # o disco trocou entre pegar o aberto antes e comecar a ler: ninguem le esse ffmpeg
            pre[1].kill()
            pre[1].wait()

    def _erro_de_leitura(self, track, t):
        nome = track.get("title") or "o arquivo"
        quando = f"{int(t // 60)}:{int(t % 60):02d}"
        if track.get("stream"):
            self.error = (f"O YouTube parou de mandar o áudio de \"{nome}\" em {quando}. "
                          "Toque de novo, ou espere ele chegar na prateleira.")
        else:
            self.error = (f"Não consegui ler o áudio de \"{nome}\" a partir de {quando}. "
                          "O arquivo pode estar corrompido; apague e baixe de novo.")

    def _stream_desistiu(self, deck, gen, track, t):
        """O servidor nao religou o stream que caiu: o disco acaba ali e a fila segue, se ele ainda esta no prato."""
        with self._qlock:
            if deck is not self._deck or deck.gen != gen or self.track is not track:
                return
            self._erro_de_leitura(track, t)
            deck.eof_gen = gen

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
        self._onda_pede(self.track)
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
            self._onda_pede(track)
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
            self._visor_pas = None
        self._pronto = self.pronto_tag = self._virar_em = None
        self._eco_plano = None
        self._deck.ahead = AHEAD
        if tudo:
            if self._saindo is not None:
                self._saindo[0].gen += 1
            self._saindo = self._entrando = self._eco = None
            self._visor_pas = self._visor_feita = None  # pulou: a sobreposicao e a velocidade dela nao valem mais

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
        if fade:  # fade-out: sem plano no tempo (os andamentos nao casam ou falta batida), o fade de sempre: a proxima
            # sobe do comeco enquanto ele cai, e o rabo baixinho fica para tras. A passagem de DJ (a troca no fim do
            # corpo, a introducao por baixo) e so a do plano no tempo: no fade, a introducao por baixo juntava dois
            # andamentos e o corte no drop soou estranho (GigaChad 64 BPM -> Close Eyes 88,5, pedido dele, 06/11)
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
                self._segura = plano.get("segura", 0)
                self._nivel_entra, self._cheia = plano.get("nivel", 1.0), plano.get("cheia", 0)
                self._eco_plano = plano.get("eco")
                self.periodo_saida = plano["periodo_saida"]
                self._virar_em = plano["virar"] - BLOCK / (2 * SR)  # vira no fim do bloco que acaba ali
                visor = plano["visor"]
            else:
                while prox.q and prox.q[0][0] + len(prox.q[0][1]) / SR <= ini:  # a proxima comeca no som
                    prox.q.popleft()
                self._sobrepor = self._entrar = int(sobrepor * SR)
                self._segura, self._nivel_entra, self._cheia = 0, 1.0, 0
                self._grave = None
                self._eco_plano = None
                self._virar_em = max(self.pos, virar)
                # o visor: so o cruzamento de volume, sem grade nenhuma (nada promete batida casada)
                visor = {"no_tempo": False, "v": self._virar_em, "t0": self._virar_em,
                         "ini": prox.q[0][0] if prox.q else ini, "va": 1.0, "vb": 1.0, "sob": 0.0, "rampa": 0.0,
                         "k": 0.0, "sai": sobrepor, "entra": sobrepor, "grave": None, "grade_de": None,
                         "grade_para": None, "motivo": motivo}
            self._visor_pas = _visor_publico(tr_atual, prox.track, visor)
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
        self._registra_fim(cauda, tr_atual, prox.track, fim, queda, baixo, fade, caindo, virar, sobrepor,
                           plano, motivo)

    def _registra_fim(self, cauda, tr_atual, tr_prox, fim, queda, baixo, fade, caindo, virar, sobrepor, plano, motivo):
        """O fim de cada disco que passou, para estudar a passagem (o final baixo e comprido que atrasa a virada): no
        log, o nivel de 5 em 5 s dos ultimos 40 s relativo ao normal do fim; em logs/passagens/AAAA-MM-DD.jsonl, o
        nivel em decimos dos ultimos 90 s, as tres faixas do visor no mesmo trecho e o plano. Nunca derruba a passagem."""
        try:
            ret = retrato_fim(cauda, fim)
            if ret is None:
                return
            normal, t0, decimos, janelas = ret
            virou = plano["virar"] if plano is not None else virar
            print(f"passagem: fim de {tr_atual.get('title')!r}: normal {normal:.1f} dBFS; de 5 em 5 s nos ultimos "
                  f"{FIM_RETRATO_S:.0f} s: {' '.join('-' if j is None else f'{j:+.0f}' for j in janelas)} dB; "
                  f"queda em {queda if queda is None else round(queda, 2)} s, baixo em "
                  f"{baixo if baixo is None else round(baixo, 2)} s, vira em {virou:.2f} s ({fim - virou:.1f} s antes "
                  f"do fim do som)", file=sys.stderr, flush=True)
            faixas = None
            with self._olock:
                o = self._ondas.get(tr_atual.get("id"))
                if o is not None:
                    c0, c1 = max(0, int(t0 / VISOR_PASSO)), min(o.n, int(np.ceil(fim / VISOR_PASSO)))
                    if c1 > c0:
                        faixas = {"c0": c0, "b64": base64.b64encode(o.cols[c0:c1].tobytes()).decode("ascii")}
            reg = {"quando": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "sai": {k: tr_atual.get(k) for k in ("id", "title", "channel", "duration")},
                   "entra": {k: tr_prox.get(k) for k in ("id", "title", "channel", "duration")},
                   "fim": round(fim, 3), "queda": None if queda is None else round(queda, 3),
                   "baixo": None if baixo is None else round(baixo, 3), "fade": fade, "caindo": round(caindo, 3),
                   "vira": round(virou, 3), "sobrepor": round(sobrepor, 3), "no_tempo": plano is not None,
                   "motivo": motivo, "normal": normal, "t0": round(t0, 3), "decimos": decimos, "janelas": janelas,
                   "visor": {"passo": VISOR_PASSO, "db": list(VISOR_DB), "faixas": faixas}}
            pasta = pastas.LOGS / "passagens"
            pasta.mkdir(parents=True, exist_ok=True)
            with open(pasta / (time.strftime("%Y-%m-%d") + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        except Exception as ex:  # noqa: BLE001 - o registro e so estudo: falhando, a passagem segue igual
            print(f"passagem: o registro do fim falhou: {ex!r}", file=sys.stderr, flush=True)

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
        intro = False
        if not fade and gb.firme:  # final seco com a introducao baixa da proxima: ela entra por baixo antes
            with self._qlock:
                niv_b = list(prox.niveis)
            corpo, comeco = medir_corpo(niv_b, ini), nivel_trecho(niv_b, ini, ini + INTRO_SECO_OUVE_S)
            intro = (corpo is not None and corpo - ini >= INTRO_SECO_BATIDAS * pa
                     and comeco is not None and comeco < -FIM_DB)

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

        if not fade and not intro:
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
            fim_o = baixo if baixo is not None and fim - baixo <= RABO_SECO_S else fim   # o rabo curto fica para tras
            k = int(np.ceil((fim_o - TRANS_SECO_S - a0) / pa))
            while a0 + k * pa - tau < fim_o - FIM_CORTE_S:
                k += 1
            # o corte no 1 do DJ (a djeco, escolha dele, 06/11): a primeira batida dela cai no golpe final deste, o canal
            # deste fecha ali e o eco do ultimo tempo dele fica por baixo dela; sem golpe, ou com o comeco dela longo
            # antes da primeira batida (tocaria por cima deste), ela entra na batida depois do fim para o ouvido
            golpe = _golpe_final(blocos_a, a0 + k * pa, pa, queda) if tau <= CORTE_TAU_MAX else None
            b1 = golpe if golpe is not None else a0 + k * pa
            t0 = b1 - tau
            if golpe is not None:  # a virada antes do fecho do canal deste, que vai inteiro depois dela; ela comeca em t0
                v, silencio, pad = virada(min(t0, golpe - CORTE_ANTES_S - CORTE_RAMPA_S))
                if v is None:  # o golpe ficou perto demais (plano tardio): a batida depois do fim, como antes
                    golpe, b1 = None, a0 + k * pa
                    t0 = b1 - tau
                else:
                    pad = int(round((t0 - v) * SR))
            if golpe is None:
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
            segura, eco, corte = 0, None, ""
            if golpe is None:
                sai = int(min(max(fim - t0, TRANS_SECO_S), 1.0) * SR)
            else:
                sai = max(1, int(round((golpe - CORTE_ANTES_S - v) * SR)))
                segura = max(0, sai - int(CORTE_RAMPA_S * SR))
                # o tempo dela pela rede no audio cru (esticada, ela toca 1/s mais devagar durante o eco)
                d = _batida_tocada(_junta(blocos_b, ini, ini + ECO_MEDE_S)[1], pb) / (1.0 if esticada is None else s)
                e = _eco_corte(blocos_a, golpe, d)
                if e is not None:
                    eco = (e, int(round((golpe - v) * SR)))
                corte = (f"; corte no 1 do golpe final ({fim - golpe:.2f} s antes do fim do som)"
                         + (f", eco de {d:.3f} s" if e is not None else ", sem o eco"))
            # o visor: a proxima esticada pelas SEGURA_BATIDAS deste e de volta devagar (ou no andamento dela); a grade
            # deste vai ate a batida em que a primeira dela cai, mesmo passado o fim do som dele
            vb, sob, rampa, kr = ((1.0, 0.0, 0.0, 0.0) if esticada is None else
                                  _visor_rampa(ini, ate, s, int((pb / s + SEGURA_BATIDAS * pa) * SR), n_rampa))
            visor = {"no_tempo": True, "v": v, "t0": t0, "ini": ini, "va": 1.0, "vb": vb, "sob": sob, "rampa": rampa,
                     "k": kr, "sai": sai / SR, "entra": (pad + int(ENTRA_SECO_S * SR)) / SR, "grave": None,
                     "grade_de": _visor_grade(ga, a0, t_a, max(fim, a0 + k * pa) + 0.01),
                     "grade_para": _visor_grade(gb, ini + vb * tau, ini, ini + BATIDA_S) if gb.firme else None}
            return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": silencio, "sai": sai, "segura": segura,
                    "entra": pad + int(ENTRA_SECO_S * SR), "grave": None, "periodo_saida": pa, "visor": visor,
                    "eco": eco, "log": (f"final seco, {quem} em {b1:.2f} s, na grade deste ({ga.bpm:.1f} BPM), "
                                        f"ela comeca em {t0:.3f} s{corte}")}, None
        s, m = min(((pb / (pa * m), m) for m in (0.5, 1.0, 2.0)), key=lambda v: abs(np.log(v[0])))
        if abs(s - 1) > TEMPO_MAX:
            # a proxima fica em TEMPO_MAX e a que sai anda o resto, se couber em SAI_MAX
            sa = (1 + TEMPO_MAX if s > 1 else 1 - TEMPO_MAX) / s
            if abs(sa - 1) > SAI_MAX:
                return None, f"andamentos longe, {ga.bpm:.1f} e {gb.bpm:.1f} BPM ({(s - 1) * 100:+.1f}%)"
            nb, ini = self._entrada_dj(prox, ini, pa, pb, s * sa, b_longa)
            return self._plano_dois(blocos_a, blocos_b, ga, gb, s, sa, a_longa, b_longa, queda - nb * pa,
                                    (nb + DJ_SAI_BATIDAS) * pa, queda, ini, fase_em)
        troca_t = queda
        nb, ini = self._entrada_dj(prox, ini, pa, pb, s, b_longa)
        virar = troca_t - nb * pa
        a0, motivo = fase_em(blocos_a, virar - FASE_ANTES_S, troca_t, pa, "do fim deste", a_longa)
        if a0 is None:
            return None, motivo
        n_fade = int(DJ_SAI_BATIDAS * pa * SR)
        n_sob = int(nb * pa * SR) + n_fade
        sobrepor = n_sob / SR
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
        # os graves trocam na batida dele mais perto da troca (o fim do corpo), em meia batida: ate la a proxima vem
        # sem grave, dali em diante e o que sai que fica sem (no callback); a que sai segue cheia ate ali e some em
        # DJ_SAI_BATIDAS; a proxima chega cheia no meio da troca
        tm = a0 + round((troca_t - a0) / pa) * pa
        w0 = max(pad, pad + int((tm - t0 - pa / 4) * SR))
        w1 = w0 + int(pa / 2 * SR)
        segura, entra = w0, w0
        corte = min(len(z), w1 - pad + SR // 2)
        grave = signal.sosfiltfilt(_GRAVE_LP, z[:corte], axis=0).astype(np.float32)
        entra_grave = np.clip((np.arange(corte) + pad - w0) / (w1 - w0), 0.0, 1.0).astype(np.float32)
        z[:corte] -= (1 - entra_grave)[:, None] * grave
        saida = np.concatenate([np.zeros((pad, 2), np.float32), z]) if pad else z
        cabeca = []
        for u in range(0, len(saida), BLOCK):
            t = ini + (phi[u - pad] / SR if u >= pad else (u - pad) / SR)
            cabeca.append((max(0.0, t), saida[u:u + BLOCK]))
        vb, sob, rampa, kr = _visor_rampa(ini, ate, s, n_sob, n_rampa)
        sai = segura + n_fade
        visor = {"no_tempo": True, "v": v, "t0": t0, "ini": ini, "va": 1.0, "vb": vb, "sob": sob, "rampa": rampa,
                 "k": kr, "sai": sai / SR, "entra": entra / SR, "segura": segura / SR, "nivel": DJ_NIVEL_ANTES,
                 "cheia": w1 / SR, "grave": [w0 / SR, w1 / SR],
                 "grade_de": _visor_grade(ga, a0, t_a, baixo),
                 "grade_para": _visor_grade(gb, ini + s * tau, ini, ini + BATIDA_S)}
        return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": 0, "sai": sai, "entra": entra, "segura": segura,
                "nivel": DJ_NIVEL_ANTES, "cheia": w1, "grave": (w0, w1), "periodo_saida": pa, "visor": visor,
                "log": (f"{ga.bpm:.1f} BPM saindo, {gb.bpm:.1f} BPM entrando, a proxima a {s * 100 - 100:+.2f}% "
                        f"por {nb} batidas antes da troca e {DJ_SAI_BATIDAS} depois, e de volta em {n_rampa / SR:.1f} s; "
                        f"a primeira batida dela em {t0 + tau:.3f} s, na grade deste; os graves trocam em {tm:.2f} s "
                        f"(o corpo deste acaba em {troca_t:.2f} s)")}, None

    def _entrada_dj(self, prox, ini, pa, pb, s, b_longa):
        """Quantas batidas deste (nb) a proxima entra antes da troca, e de onde dela (ini). So a que comeca quase sem som
        (INTRO_SECO_OUVE_S a FIM_DB abaixo do normal dela) entra por baixo antes; a que se ouve desde o comeco entra na
        troca (nb = 0). A que entra por baixo leva o bastante para o drop dela
        (medir_corpo, numa batida dela) cair na troca, em degraus de 4, de DJ_MIN_BATIDAS a DJ_MAX_BATIDAS e ate
        DJ_MAX_S; com a introducao maior, ela comeca dentro dela, um numero inteiro de compassos antes do drop. Sem o
        corpo medido, DJ_BATIDAS desde o comeco dela. s e a velocidade dela na sobreposicao."""
        teto = DJ_MAX_BATIDAS
        while teto > DJ_MIN_BATIDAS and teto * pa > DJ_MAX_S:
            teto -= 4
        with self._qlock:
            niv = list(prox.niveis)
        comeco_db = nivel_trecho(niv, ini, ini + INTRO_SECO_OUVE_S)
        if comeco_db is None or comeco_db >= -FIM_DB:
            # o comeco dela se ouve: nada dela por baixo da que sai, que seria voz sobre voz (o funk tocava 22 s junto,
            # pedido dele, 06/11). Ela entra na troca, cheia em meia batida, e a que sai some por baixo dela
            return 0, ini
        corpo = medir_corpo(niv, ini)
        if corpo is None:
            return min(DJ_BATIDAS, teto), ini
        corpo = b_longa + round((corpo - b_longa) / pb) * pb   # o drop numa batida dela
        nb = int(round((corpo - ini) / (s * pa) / 4)) * 4      # a introducao, em compassos deste
        nb = max(DJ_MIN_BATIDAS, min(teto, nb))
        comeco = corpo - nb * pa * s
        if comeco < ini - 1e-6:   # introducao curta: ela entra do comeco (o drop chega antes da troca)
            return nb, ini
        print(f"passagem: a introducao da proxima vai ate {corpo:.2f} s; ela entra de {comeco:.2f} s, {nb} batidas "
              f"antes da troca", file=sys.stderr, flush=True)
        return nb, comeco

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
        i1, i2 = saida_a(virar - FASE_ANTES_S), saida_a(baixo)   # baixo aqui e a troca (o fim do corpo)
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
        tm = a0 + round((saida_a(baixo) - a0) / P) * P  # a troca de grave na batida deste mais perto da troca
        w0 = max(pad, pad + int(tm - t0 - P / 4))
        w1 = w0 + int(P / 2)
        segura, entra = w0, w0
        sai = segura + int(DJ_SAI_BATIDAS * P)
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

        def disco_a(i):
            """A posicao deste disco na amostra i da saida dele (desde t_r)."""
            return t_r + phi_a[min(len(phi_a) - 1, max(0, int(round(i))))] / SR

        vb, sob, rampa, kr = _visor_rampa(ini, ate, sb, n_sob, n_rampa)
        visor = {"no_tempo": True, "v": v, "t0": disco_a(t0), "ini": ini, "va": sa, "vb": vb, "sob": sob,
                 "rampa": rampa, "k": kr, "sai": sai / SR, "entra": entra / SR, "segura": segura / SR,
                 "nivel": DJ_NIVEL_ANTES, "cheia": w1 / SR, "grave": [w0 / SR, w1 / SR], "grade_de": _visor_grade(ga, disco_a(a0), a_longa - ga.fase, baixo),
                 "grade_para": _visor_grade(gb, ini + sb * tau, ini, ini + BATIDA_S)}
        return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": 0, "sai": sai, "entra": entra, "segura": segura,
                "nivel": DJ_NIVEL_ANTES, "cheia": w1, "grave": (w0, w1), "sai_q": (t_r, novos), "periodo_saida": P / SR,
                "visor": visor,
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
            self._saindo = [velho, n, 0, grave, self._segura if medida else 0] if n and velho.q else None
            self._segura = 0
            if self._saindo is None:
                velho.gen += 1
            ne = self._entrar if medida else 0
            self._entrando = [ne, 0, self._nivel_entra if medida else 1.0, self._cheia if medida else 0] if ne else None
            self._nivel_entra, self._cheia = 1.0, 0
            self._eco = [self._eco_plano[0], -self._eco_plano[1]] if medida and self._eco_plano is not None else None
            self._eco_plano = None
            self._deck = prox
            # o visor segue desenhando a passagem que acabou de virar (a sobreposicao vem toda depois da virada)
            self._visor_feita, self._visor_pas = (self._visor_pas if medida else None), None
            self._pronto = self.pronto_tag = self._virar_em = None
            prox.ahead = AHEAD
            self.track = prox.track
            self.pos = prox.q[0][0] if prox.q else 0.0
            self.ended = False
            self.virou = (sai, prox.track, tag)

    # visor de DJ do tema ----------------------------------------------------
    def _onda_pede(self, track):
        """Garante a onda do disco para o visor (o tema pede pelo GET /api/onda/<id>, ver onda): o da prateleira e lido
        inteiro uma vez, numa thread a parte, pelo ffmpeg em prioridade baixa e a VISOR_SR (o leitor do prato segue so
        2 s adiante e nao serve para mostrar o que vem); o do stream sai do proprio leitor (_onda_acumulador), sem
        abrir o stream de novo. Nada disso passa pelo callback de audio."""
        iid = track.get("id") if track else None
        path = str(track.get("path") or "") if track else ""
        if not iid or not path:
            return
        dur = track.get("duration")
        with self._olock:
            o = self._ondas.get(iid)
            if o is not None:
                self._ondas.move_to_end(iid)
            if path.startswith("http"):
                if o is None:
                    self._guarda_onda(iid, Onda("stream", dur))
                return
            if (o is not None and o.fonte == "arquivo") or iid in self._onda_lendo:
                return
            self._onda_lendo.add(iid)
            if self._onda_fila is None:
                self._onda_fila = queue.Queue()
                threading.Thread(target=self._onda_loop, daemon=True).start()
        self._onda_fila.put((iid, path, dur))

    def _guarda_onda(self, iid, o):
        """Com _olock: poe a onda no cache; sai a mais antiga que nao e a do prato nem a da proxima."""
        self._ondas[iid] = o
        self._ondas.move_to_end(iid)
        vivas = {(self.track or {}).get("id"), (self._pronto.track or {}).get("id") if self._pronto else None}
        for k in [k for k in self._ondas if k not in vivas][:max(0, len(self._ondas) - VISOR_CACHE)]:
            del self._ondas[k]

    def _onda_viva(self, iid):
        """A onda de iid ainda serve: e o disco do prato ou o proximo (07/11: o pulado ficava na frente da fila e o disco
        novo esperava a leitura inteira dele, com o visor so ate a agulha)."""
        return iid in ((self.track or {}).get("id"), (self._pronto.track or {}).get("id") if self._pronto else None)

    def _onda_loop(self):
        while True:
            iid, path, dur = self._onda_fila.get()
            try:
                if self._onda_viva(iid):
                    self._onda_arquivo(iid, path, dur)
            except Exception as ex:  # noqa: BLE001 - sem a onda, o visor fica so com a linha do meio
                print(f"visor: nao li a onda de {iid}: {ex!r}", file=sys.stderr, flush=True)
            finally:
                with self._olock:
                    self._onda_lendo.discard(iid)

    def _onda_arquivo(self, iid, path, dur):
        """A onda do arquivo inteiro, 1 s de audio por vez (o ffmpeg decodifica no processo dele; aqui, uma FFT de 25
        colunas por segundo). Aparece no cache a cada 30 s lidos (um disco de 1 h leva uns segundos) e de vez no fim,
        quando o _ondas_versao sobe; a do stream do mesmo disco so sai quando esta termina."""
        if not os.path.exists(path):
            return
        # estereo, e o mono pela media dos dois lados aqui, como o leitor do stream faz: o -ac 1 do ffmpeg soma os dois
        # a -3 dB, e a onda do mesmo disco saia 3 dB mais alta que a do stream
        ff = subprocess.Popen([FFMPEG, "-v", "error", "-nostdin", "-i", path, "-vn", "-f", "f32le", "-ac", "2",
                               "-ar", str(VISOR_SR), "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=NO_WINDOW | ABAIXO_DO_NORMAL, startupinfo=sem_cursor())
        o = Onda("arquivo", dur)
        m = int(round(VISOR_SR * VISOR_PASSO))
        c, resto, mostra = 0, np.zeros(0, np.float32), int(30 / VISOR_PASSO)
        try:
            while True:
                b = ff.stdout.read(VISOR_SR * 8)
                if not b:
                    break
                if not self._onda_viva(iid):
                    return   # o disco saiu do prato no meio da leitura: o proximo da fila nao espera
                lr = np.frombuffer(b[: len(b) // 8 * 8], np.float32).reshape(-1, 2)
                x = np.concatenate([resto, lr.mean(axis=1)])
                k = len(x) // m
                if k:
                    cols = colunas_onda(x[:k * m], VISOR_SR)
                    with self._olock:
                        o.escreve(c, cols)
                        if c // mostra != (c + k) // mostra:
                            atual = self._ondas.get(iid)
                            if atual is None or atual.fonte == "arquivo":
                                self._guarda_onda(iid, o)
                    c += k
                resto = x[k * m:]
        finally:
            ff.kill()
            ff.wait()
        with self._olock:
            o.completa = True
            if o.n:
                self._guarda_onda(iid, o)
                self._ondas_versao += 1

    def _onda_acumulador(self, track):
        """O _AcumOnda do leitor de stream de track, ou None (sem id, ou a onda do arquivo dele ja lida)."""
        iid = track.get("id")
        if not iid:
            return None
        with self._olock:
            o = self._ondas.get(iid)
            if o is None:
                o = Onda("stream", track.get("duration"))
                self._guarda_onda(iid, o)
            if o.fonte != "stream":
                return None
        return _AcumOnda(self, o)

    def onda(self, iid):
        """A onda do disco iid para o visor do tema, ou None se o motor nao tem (ainda nao tocou ou saiu do cache):
        {"id", "passo": VISOR_PASSO, "n": colunas, "completa": bool, "fonte": "arquivo" | "stream", "versao",
        "onda": base64 de n x 3 bytes}. Cada coluna e (grave, medio, agudo), em dB de -60 a 0 dBFS lineares no byte
        (0 = -60 dB ou menos, 255 = 0 dB), coluna i = o audio de i*passo a (i+1)*passo s do disco. Incompleta (o
        arquivo ainda sendo lido, ou o stream, que so chega ate onde o leitor decodificou), vale pedir de novo; coluna
        ainda nao lida vem zero. ~18 KB para 4 min (24 KB em base64)."""
        with self._olock:
            o = self._ondas.get(iid)
            if o is None:
                return None
            dados, n, completa, fonte, versao = o.cols[:o.n].tobytes(), o.n, o.completa, o.fonte, o.versao
        return {"id": iid, "passo": VISOR_PASSO, "n": n, "completa": completa, "fonte": fonte, "versao": versao,
                "onda": base64.b64encode(dados).decode("ascii")}

    # comandos -------------------------------------------------------------
    def espera(self, track):
        """Poe o disco no prato carregando, ainda sem audio: o endereco do stream do YouTube
        leva 1 a 3 s para sair, e a tela ja mostra o que vai tocar."""
        with self._lock:
            self.track = track
            self.paused = False
            self._prato = (track.get("id"), time.time())
            self._restart(0.0)

    def tira_soou(self):
        """O primeiro som do ultimo disco que entrou no prato, uma vez: (titulo, stream?, entrou, soou) ou None."""
        s, self._soou = self._soou, None
        return s

    def trocar_fonte(self, atual, novo):
        """Troca o audio do disco no prato sem cortar: da espera para o stream, ou do stream
        para o arquivo que acabou de baixar. O leitor novo comeca onde o
        audio ja decodificado termina, e o que esta na fila do cabo segue tocando. So vale se
        o prato ainda tem `atual` (o mesmo objeto): se ele trocou de disco no meio, nada muda."""
        with self._lock:
            if self.track is not atual:
                return False
            self._onda_pede(novo)
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
            self._prato = (track.get("id"), time.time())
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
        """O estado do motor para a tela. O "visor" e o do visor de DJ do tema: "ondas" sobe quando uma onda de
        arquivo fica pronta (pedir de novo o GET /api/onda/<id>), e "passagens" traz ate duas, a que trouxe o disco do
        prato (enquanto ele e o "para" dela) e a medida dele para a proxima (ele e o "de"):
        {"de", "para": ids dos discos, "no_tempo": bool (false = so o cruzamento de volume, sem grade),
         "t0": onde a proxima comeca, no tempo do "de"; "ini": onde ela comeca no tempo dela;
         "v": onde os volumes comecam a cruzar, no tempo do "de" (a virada do motor; ate uns ms antes do t0);
         "va": a velocidade do "de" ali (1, ou a dele ja mudada quando os dois mudam);
         "vb", "sob", "rampa", "k": a velocidade da proxima em s de saida desde o t0: vb por sob s, depois
           1 + k * (1 + cos(pi * r / rampa)) / 2 por rampa s (r desde o fim do sob), depois 1;
         "sai", "entra": quanto o "de" leva para calar (cosseno) e a proxima para subir (seno), em s de saida desde o v;
         "grave": [g0, g1] em s de saida desde o v, a troca de grave (ate g0 o grave e do "de", depois de g1 da
           proxima), ou null;
         "grade_de", "grade_para": a grade de cada um no tempo do proprio disco, {"bpm", "periodo", "fase" (uma batida),
           "de", "ate" (o trecho onde ela foi medida e vale)}, ou null;
         "motivo": por que nao foi no tempo (texto do log), so quando no_tempo e false}.
        Tempo de saida = o do relogio do som; no tempo de um disco que anda na velocidade v, 1 s de saida e v s dele."""
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
            "mina": self._mina.estado if self._mina is not None else "desligada",
            "visor": {"ondas": self._ondas_versao,
                      "passagens": [p for p in (self._visor_feita, self._visor_pas) if p is not None]},
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

    def _mina_liga(self):
        pass  # sem som, sem a mina: a sessao custaria e nao tocaria em lugar nenhum

    def set_devices(self, mic=None, out=None, monitor=None):
        for k, v in (("mic", mic), ("out", out), ("monitor", monitor)):
            if v is not None:
                self.devices[k] = v
        self.active = self._real_names()

    # o visor de DJ sem medir nada: a onda e a grade de mentira saem do id do disco (sempre as mesmas para ele), e a
    # passagem e montada no fim do disco no mesmo formato da do motor, para o tema ter o que desenhar e printar
    @staticmethod
    def _falso(iid):
        """O andamento de mentira do disco: (bpm na oitava lenta, periodo, a primeira batida), de 96 a 104 BPM (quase
        toda passagem cai no alcance da passagem no tempo; a que nao cai mostra o cruzamento)."""
        h = zlib.crc32(str(iid).encode())
        bpm = 96.0 + h % 9
        periodo = 60.0 / bpm
        return bpm, periodo, 0.15 + (h >> 8) % 100 / 100 * periodo

    def _onda_falsa(self, iid, dur):
        """A onda de mentira: o bumbo em cada batida da grade, a caixa no meio, o chimbal em quatro, partes de 16
        batidas com forca sorteada (as 4 primeiras batidas e uma ou outra parte sem bateria, nunca nos ultimos 30 s: a
        passagem de mentira mostra as batidas das duas) e o fade dos ultimos 10 s."""
        _, p, fase = self._falso(iid)
        dur = float(dur or 180.0)
        rng = np.random.default_rng(zlib.crc32(str(iid).encode()))
        t = (np.arange(int(dur / VISOR_PASSO)) + 0.5) * VISOR_PASSO
        b = (t - fase) / p
        bumbo = np.exp(-(b % 1.0) * p / 0.09)
        caixa = np.exp(-((b + 0.5) % 1.0) * p / 0.1)
        chimbal = np.exp(-((b * 4) % 1.0) * p / 4 / 0.025)
        parte = np.floor(np.maximum(b, 0) / 16).astype(int)
        forca = rng.uniform(0.55, 1.0, parte.max() + 2)[parte]
        bateria = ~(((b < 4) | (rng.random(parte.max() + 2) < 0.15)[parte]) & (t < dur - 30))
        g = np.clip((dur - t) / 10.0, 0.02, 1.0) ** 1.5 * forca

        def ruido():
            return rng.uniform(0.9, 1.1, len(t))
        # perto dos niveis da onda do Without Me (05/11): o grave a -21 dB entre os bumbos e -10 neles, o medio a -23 e -16
        # na caixa, o agudo a -33 e -24 no chimbal
        a = np.stack([(0.09 + 0.23 * bumbo * bateria) * g * ruido(),
                      (0.07 + 0.09 * caixa * bateria) * g * ruido(),
                      (0.022 + 0.04 * chimbal * bateria) * g * ruido()], axis=1)
        lo, hi = VISOR_DB
        return np.clip((20 * np.log10(np.maximum(a, 1e-6)) - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)

    def _onda_pede(self, track):
        iid = track.get("id") if track else None
        if not iid:
            return
        with self._olock:
            if iid in self._ondas:
                self._ondas.move_to_end(iid)
                return
        o = Onda("arquivo", track.get("duration"))
        o.escreve(0, self._onda_falsa(iid, track.get("duration")))
        o.completa = True
        with self._olock:
            self._guarda_onda(iid, o)
            self._ondas_versao += 1

    def _mede(self, atual, prox, tr_atual):
        """A passagem de mentira: espera o comeco da proxima decodificar (ou falhar, e ai ela toca no fim, como no
        motor) e marca a virada 12 s antes do fim deste, com a primeira batida dela numa batida dele e 8 s de
        sobreposicao; com os andamentos longe ou a batida ja passada, so o cruzamento de 6 s. O som dela entra sem
        esticar: o visor e que mostra a velocidade do plano."""
        limite = time.monotonic() + 5.0
        while True:
            if self._pronto is not prox or self._deck is not atual:
                return
            if prox.q or prox.eof_gen == prox.gen or time.monotonic() > limite:
                break
            time.sleep(0.05)
        dur = float(tr_atual.get("duration") or 0)
        with self._qlock:
            if self._pronto is not prox or self._deck is not atual:
                return
            if not prox.q or not dur:
                self.pronto_falhou = self.pronto_tag
                self._cancela_passagem()
                return
            ini = prox.q[0][0]
            bpm_a, pa, fa = self._falso(tr_atual.get("id"))
            bpm_b, pb, fb = self._falso(prox.track.get("id"))
            s = min((pb / (pa * m) for m in (0.5, 1.0, 2.0)), key=lambda v: abs(np.log(v)))
            primeira = fb + max(0, np.ceil((ini - fb) / pb)) * pb  # a primeira batida dela, no tempo dela
            u_b = (primeira - ini) / s
            t0 = fa + round((dur - 12.0 + u_b - fa) / pa) * pa - u_b
            if abs(s - 1) <= TEMPO_MAX and t0 - self.pos >= FOLGA_S:
                sob = TRANS_MAX_S
                tm = fa + round((t0 + sob / 2 - fa) / pa) * pa  # a troca de grave na batida dele do meio
                visor = {"no_tempo": True, "v": t0, "t0": t0, "ini": ini, "va": 1.0, "vb": s, "sob": sob,
                         "rampa": min(max(abs(s - 1) / RAMPA_TAXA, RAMPA_MIN_S), RAMPA_MAX_S), "k": s - 1,
                         "sai": sob, "entra": sob, "grave": [tm - t0 - pa / 4, tm - t0 + pa / 4],
                         "grade_de": {"bpm": bpm_a, "periodo": pa, "fase": fa, "de": dur - 4.0 - BATIDA_S, "ate": dur},
                         "grade_para": {"bpm": bpm_b, "periodo": pb, "fase": primeira, "de": ini,
                                        "ate": ini + BATIDA_S}}
            else:
                sob, t0 = 6.0, max(self.pos + 1.0, dur - 8.0)
                visor = {"no_tempo": False, "v": t0, "t0": t0, "ini": ini, "va": 1.0, "vb": 1.0, "sob": 0.0,
                         "rampa": 0.0, "k": 0.0, "sai": sob, "entra": sob, "grave": None, "grade_de": None,
                         "grade_para": None, "motivo": (f"andamentos longe, {bpm_a:.1f} e {bpm_b:.1f} BPM"
                                                        if abs(s - 1) > TEMPO_MAX else "a batida da virada ja passou")}
            self._sobrepor = self._entrar = int(sob * SR)
            self._grave = None
            self._virar_em = t0 - BLOCK / (2 * SR)
            self._visor_pas = _visor_publico(tr_atual, prox.track, visor)
        print(f"passagem (mock): {tr_atual.get('title')!r} -> {prox.track.get('title')!r}: "
              f"{'no tempo' if visor['no_tempo'] else 'so o cruzamento'}, vira em {t0:.2f} s", file=sys.stderr, flush=True)

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
