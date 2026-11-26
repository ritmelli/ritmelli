"""Motor de audio do Ritmelli: o arquivo (e a voz da mina) -> o microfone escolhido, pelo filtro do Ritmelli (microfone/),
que soma dentro do audio do Windows, e o jogo (ou o Discord) segue usando esse microfone; so o arquivo -> fone de quem
toca (sem ouvir a propria voz). A voz vai crua pelo proprio microfone, e o efeito de voz roda no filtro; com efeito
que o filtro nao roda, ou cortada, ela volta por aqui: o filtro devolve a voz crua e poe no lugar dela a que o app
manda (ver Injetor). O app passa a voz pelo mesmo motor de efeitos do filtro (microfone/voz.py). Sucessor do mic_mix.py de
16/10: o controle e por metodo (o server.py expoe por HTTP), nao por arquivo PAUSA/VOL."""
import base64
import collections
import contextlib
import copy
import ctypes
import datetime
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
import i18n
import metricas
import pastas
import sonoridade
import transicao
from microfone import preset  # o preset do efeito no filtro: importado aqui, nunca na thread da saida para o jogo
from microfone import voz  # o mesmo motor de efeitos do filtro, para a voz com efeito que sai pelo app
# as contas da passagem sem audio (o nivel, o fade ou o final seco, a entrada da proxima e os tempos) moram no
# transicao.py; o motor, e quem le daqui (o andamento.py), segue com os mesmos nomes
from transicao import (BLOCK, FADE_MIN_S, FASE_ANTES_S, FASE_MIN_S, FOLGA_S, RAMPA_MAX_S, RAMPA_MIN_S, RAMPA_TAXA,
                       SAI_MAX, SR, TEMPO_MAX, TRANS_MAX_S, TRANS_SECO_S, _niveis, medir_fim, medir_inicio)

try:  # o pedal da mina: modulo de fora deste repo, posto ao lado do codigo so onde ela roda
    import mina
except ImportError:
    mina = None

# o modo compartilhado do Windows so aceita a taxa em que o aparelho esta configurado: sem converter, o som da
# VirtualBox, a 44,1 kHz, recusava os 48 kHz e o app nem abria (29/10)
WASAPI = sd.WasapiSettings(auto_convert=True)
AHEAD = 200  # blocos decodificados adiante (~2 s)
MIC_MAX = 8  # nunca mais de ~80 ms de atraso na voz
# a voz da pista chega em rajadas do tamanho do bloco do conversor (80 ms no modo de 380 ms), e a conta varia de bloco a
# bloco: com o teto de 8 a fila do fone ou secava ou jogava pedaco fora em ~14% dos blocos de 10 ms (o estalo forte do
# "ouvir a propria voz" no teste de 16/11). O fone dela guarda ate PISTA_MAX e, quando seca, so volta com PISTA_ENCHE
PISTA_MAX = 32   # 320 ms
PISTA_ENCHE = 12  # 120 ms
DECAY = 0.85  # queda do medidor por bloco de 10 ms
SOBRE_MAX = 8  # sons por cima tocando juntos (o mais antigo sai)
SOBRE_CACHE = 24  # sons por cima decodificados guardados (buzina repetida sai na hora)
SOBRE_CACHE_MB = 512  # e no maximo isso de memoria neles: o posto pela mao pode ser uma musica inteira
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FFMPEG = pastas.ferramenta("ffmpeg") or "ffmpeg"  # o que vem com o app, ou o do PATH
FFPROBE = pastas.ferramenta("ffprobe") or "ffprobe"
CURTO_MAX_S = 15  # ate isso o pad toca por cima da musica em vez de trocar
ABAIXA_MAX_DB = 40.0   # o POST /api/abaixa: ate quanto a musica abaixa no jogo
ABAIXA_MAX_MS = 30000  # e por quanto tempo no maximo; no prazo, volta sozinha
SINAL_S, SINAL_HZ, SINAL_DB = 0.4, 880.0, -18.0  # o POST /api/sinal: o bipe curto de teste no microfone
FILE_TAIL_S = 2.0
STREAM_CAIU_S = 5.0  # o stream que para mais que isso antes do fim (ou sem audio nenhum) caiu: o servidor religa
# o stream que congela (13/11: a Toxic parou de chegar em 2:12 com a conexao aberta, e o ffmpeg esperou pra sempre com
# o Ritmelli carregando): isso sem receber nada e o ffmpeg reconecta uma vez no mesmo endereco e, congelado de novo,
# desiste, o que vira a queda acima (sem o limite de uma, ele tentava 4 vezes: ~4x isso no endereco morto); e do stream
# o leitor guarda STREAM_AHEAD adiante (~30 s, ~11 MB), folga que cobre as duas esperas e o endereco novo (15 s naquele
# dia): sem buraco (dev/testa_congela.py)
STREAM_SEM_DADO_S = 5.0
STREAM_AHEAD = 3000
RAPIDO_MAX_S = 120  # o posto nos Sons rapidos pela mao toca inteiro por cima ate isso (2 minutos)
# o volume automatico (sonoridade.py): o ganho de um disco anda ate isso por segundo quando a medida chega com ele
# tocando (o stream medido no comeco, o arquivo que acabou de baixar, o liga e desliga), e o stream sem medida e
# estimado quando o leitor passa destes pontos (s decodificados desde o comeco)
GANHO_RAMPA_DB_S = 6.0
STREAM_ESTIMA_S = (8.0, 30.0)
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
# o anel do filtro de microfone (microfone/injeta.py): INJ_FOLGA = blocos escritos a frente do microfone (~30 ms), a
# folga contra a thread do Python atrasar; a voz crua que o filtro devolve vale como viva ate VOZ_VIVA_S sem chegar.
# A thread pede ao Windows a prioridade de audio (MMCSS "Pro Audio", a que o PortAudio pede para o callback dele) e o
# processo roda acima do normal (PROCESSO_ACIMA). Medido em 14/11 (dev/mede_folga.py --ciclo, uma troca de musica de
# verdade a cada ~40 s, 8 nucleos): so tocando, nem com o dobro dos nucleos em processos ocupando a CPU a thread passa de
# ~5 ms; o que a atrasa e a troca de musica, por tres coisas: o kill do ffmpeg segurava o interpretador (ver mata), a
# thread que segura o interpretador perdia a CPU para o jogo e a thread de audio esperava junto (inversao de prioridade:
# paradas de ~90 ms com o dobro dos nucleos ocupados), e sem a prioridade de audio a propria thread acordava tarde. Com
# os tres consertos (e sem console, como o executavel e o pythonw), a pior parada em 22 trocas foi de 6 ms, com a CPU cheia
# e com o dobro dela (com 50 ms de folga, antes, secava: o jogo ouvia o buraco). Preso a um console, o Python pergunta ao
# conhost a cada io.open (o Popen faz um por PIPE) e a cada thread nova, e com a CPU cheia o interpretador fica preso
# ~10 a 25 ms (rastro do xperf, 14/11): por isso o soundboard.ps1 sobe pelo pythonw. 30 ms cobre ainda uma coleta grande
# do coletor de lixo (~11 ms medida); 20 passou nas medidas, mas sem essa margem.
# VOLTA_MS = casas de 1 ms do histograma das voltas da thread (a ultima junta as maiores)
INJ_FOLGA = 3
VOZ_VIVA_S = 0.2
INJ_MMCSS = True
PROCESSO_ACIMA = True
VOLTA_MS = 200
# o efeito de voz no filtro (issue #63): ate isso sem o filtro responder ao preset, a voz crua segue; depois, pelo app
PRESET_ESPERA_S = 0.2
VIGIA_TENTATIVAS = 3  # reaberturas por mudanca da lista (o PortAudio as vezes ainda nao ve o aparelho)
# o filtro do microfone em uso que para de ler com o motor ainda capturando o mesmo microfone e a lista parada: depois
# de LEITOR_PERDIDO_S sem leitor (o filtro que o Windows remonta sozinho volta antes), o vigia reabre o audio, a cada
# LEITOR_INTERVALO_S, no maximo LEITOR_TENTATIVAS vezes; o leitor que volta zera a conta. Cada reabertura corta uns
# 90 ms do som, e a musica, sem leitor, ja segue so no fone
LEITOR_PERDIDO_S = 10.0
LEITOR_INTERVALO_S = 30.0
LEITOR_TENTATIVAS = 3
# passagem de uma musica para a proxima da fila (a transicao de DJ)
TRANS_PREP_S = 180         # o servidor prepara a proxima quando falta isso para o fim (o fim deste fica na
                           # memoria, ~70 MB, para medir e planejar com folga: com 60 s, num notebook com o VRChat
                           # aberto, o plano do Boys Will Be Bugs -> Sailor Song ficou pronto depois do comeco da
                           # rampa da que sai, 22/10; num PC mais fraco o atraso nao pode acontecer nunca)
PRONTO_AHEAD = 7500        # a proxima decodifica 75 s adiante: o comeco dela e medido e esticado ate o fim da
                           # volta lenta ao andamento dela (~29 MB, so durante a passagem)
PRONTO_MIN = 1000          # com o fim deste perto, 10 s da proxima ja bastam (o stream lento nao atrasa a virada)
NIVEIS_MAX = PRONTO_AHEAD + 1500  # o nivel dos ultimos 90 s de cada deck: cobre a proxima inteira que esta
                                  # decodificada (com menos, o comeco dela saia do historico e ela entrava 15 s
                                  # depois do comeco, 21/10)
# a batida na passagem: como o DJ, a proxima entra no tempo
BATIDA_S = 20.0            # o trecho de cada lado medido para achar a grade de batidas
BATIDA_MIN_S = 12.0        # com menos que isso de um lado, a passagem segue sem alinhar
NOTA_MIN = 3.0             # o pente da fase nesse trecho tem de cair nos ataques pelo menos isso acima da media
SAI_FOLGA_S = 12.0         # a rampa da que sai so vale se ainda falta isso para ela comecar quando o plano comeca
GRAVE_HZ = 180.0           # a troca de grave: abaixo disso, um disco de cada vez
# a passagem como a de um DJ (a entrada da proxima, o DJ_BATIDAS e o corpo dela, no transicao.py)
DJ_SAI_BATIDAS = 4         # depois da troca, a que sai some nisso de batidas dela
DJ_NIVEL_ANTES = 0.5       # antes da troca a proxima sobe so ate a metade (-6 dB, o fader do DJ): os masters ja batem
                           # no teto e as duas cheias somavam o dobro; na troca ela vai a cheia, junto com o grave
ENTRA_SECO_S = 0.005       # no final seco no tempo, a proxima entra cheia (so o que evita o estalo)
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
    """Um toca-discos do motor: o disco, a fila de blocos decodificados (t0, bloco), a geracao do
    leitor (o leitor para quando ela muda) e a linha de reproducao. A linha sobe no load, no stop, no seek e no
    resume que recomeca do fim, e e ela que valida o bloco ja retirado pelo _mixa: o bloco so publica se o deck e a
    linha dele ainda sao os do prato. O gen so invalida o que um leitor substituido ainda tentar por na fila: a troca
    do stream pelo arquivo sobe o gen e mantem a linha (os blocos ja decodificados seguem valendo)."""

    def __init__(self, track=None):
        self.track = track
        self.q = collections.deque()
        self.gen = 0
        self.linha = 0
        self.eof_gen = -1
        self.file_wait = None
        self.ahead = AHEAD
        # o nivel de cada bloco decodificado (t0, quadros, rms), o ja tocado inclusive: a medicao do fim
        # precisa do trecho de antes da queda, que pode ja ter saido da fila
        self.niveis = collections.deque(maxlen=NIVEIS_MAX)
        # o volume automatico do disco (linear): aonde ele vai e onde esta (o _mixa anda de um ao outro)
        self.ganho_alvo = 1.0
        self.ganho = 1.0


# o que estava no prato num instante, lido sob o _qlock: a faixa, a posicao, o estado (o status()), o deck e a linha
Captura = collections.namedtuple("Captura", "track pos status deck linha")
# the platter's line as a token (Engine.line): the deck and the line on it. A Captura, a comandos.Reserva and a
# comandos.Proximo carry the same two fields, and Engine.on_line checks any of them
Line = collections.namedtuple("Line", "deck linha")


class Pausa:
    """O pedido de pausa de uma linha do prato (Engine.pause). Vale no limite entre blocos: com um bloco do prato
    retirado e ainda nao publicado, a confirmacao espera a publicacao dele; sem bloco, e na hora. Confirmado, guarda a
    faixa e a posicao daquele instante (ok); o resume, o load, o stop, o seek, o fim do disco e o close resolvem o
    pendente como substituido (sem ok). Os pedidos da mesma linha sao o mesmo objeto."""

    def __init__(self, deck, linha):
        self.deck, self.linha = deck, linha
        self.track = self.pos = None
        self.ok = False
        self.feita = threading.Event()

    def resolve(self, track=None, pos=None, ok=False):
        """Com o _qlock do motor: uma vez so."""
        if not self.feita.is_set():
            # uma copia: o dicionario do prato ainda muda depois (o canal que chega, o nome novo da prateleira)
            self.track, self.pos, self.ok = (dict(track) if track is not None else None), pos, ok
            self.feita.set()

    def espera(self, prazo):
        """Ate prazo segundos pela resolucao; True so se foi confirmada."""
        return self.feita.wait(prazo) and self.ok


class _Bloco:
    """Um bloco do _mixa: o que o _captura tirou sob o _qlock (o deck e a linha do prato, os pedacos do disco, o estado
    da passagem e o do limitador, em copias), o que o _renderiza calculou fora da trava e o _publica aplica se o deck e
    a linha ainda sao os do prato."""
    __slots__ = ("deck", "linha", "track", "prato", "item", "fim", "pos", "ganho", "g1", "entrando", "ent",
                 "ent_feitos", "saindo", "sai_blk", "sai", "sai_ganho", "sai_g1", "sai_zi", "sai_feitos",
                 "sai_acabou", "eco", "eco_estado", "eco_p", "auto", "lim", "zera")

    def __init__(self, deck, linha):
        for k in self.__slots__:
            setattr(self, k, None)
        self.deck, self.linha = deck, linha


FIM_RETRATO_S = 40.0       # o resumo do fim no log: as janelas de FIM_JANELA_S nos ultimos isso antes do som acabar
FIM_JANELA_S = 5.0
PASSAGENS_DIAS = 7         # logs/passagens/ guarda os registros dos ultimos isso de dias; os mais velhos saem


def poda_passagens(pasta, hoje, dias=PASSAGENS_DIAS):
    """Apaga de logs/passagens/ os AAAA-MM-DD.jsonl de mais de `dias` dias antes de `hoje` (um date) pelo nome, sem
    mexer em outro arquivo. Sem isto a pasta crescia um arquivo por dia de uso para sempre. Volta os nomes apagados."""
    apagados = []
    for p in pasta.glob("*.jsonl"):
        try:
            dia = datetime.date.fromisoformat(p.stem)
        except ValueError:
            continue
        if p.name == f"{dia.isoformat()}.jsonl" and (hoje - dia).days > dias:  # nem 20260101 nem .JSONL
            try:
                p.unlink()
                apagados.append(p.name)
            except OSError:
                pass  # aberto por outro programa: sai na proxima vez
    return sorted(apagados)


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


def _junta(blocos, t_ini, t_fim):
    """O audio dos blocos (t0, bloco) que cabem inteiros entre t_ini e t_fim: (t0 do primeiro, n x 2)."""
    sel = [a for t, a in blocos if t >= t_ini - 1e-9 and t + len(a) / SR <= t_fim + 1e-9]
    if not sel:
        return None, None
    t0 = next(t for t, a in blocos if t >= t_ini - 1e-9)
    return t0, np.concatenate(sel)


def _catmull(x, phi):
    """x (n x 2) lido nas posicoes fracionarias phi (interpolacao cubica de Catmull-Rom), em pedacos de 1 s:
    a conta inteira de uma vez prende o interpretador e o audio do jogo espera."""
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


# as chamadas a Rubber Band (o esticar e o esticar_saida), de qualquer thread: a janela do evento "audio" conta quantas
# comecaram, o tempo com alguma em curso e as secas do anel no meio delas (o metricas.SaudeAudio)
RUBBER_BAND = metricas.EmCurso()
RUBBER_BAND_WARMUP = int(0.06 * SR)
RUBBER_BAND_CROSSFADE = int(0.02 * SR)
PASSAGEM_DEPOIS_S = 5.0  # a seca ate isso depois da virada ainda conta como da passagem (secas_passagem)


def _rubber_band(y, vel):
    """O tom de y (n x 2) de volta ao original pela Rubber Band, com a velocidade vel de cada amostra."""
    x, tom = np.ascontiguousarray(y.T), -12 * np.log2(vel)
    with RUBBER_BAND.roda():  # so a chamada: o tempo dela e o que o evento conta
        z = time_stretch(x, SR, stretch_factor=1.0, pitch_shift_in_semitones=tom)
    return z.T


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
    z = _rubber_band(y, vel)
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
    """The outgoing track going to speed s before the overlap: x (n x 2) from 1 to s over n_rampa (half cosine) and
    at s to the end of x, as in esticar (vinyl, and the pitch back through the Rubber Band). The Rubber Band output
    is aligned with its input but silent for its first tens of ms: the first RUBBER_BAND_WARMUP samples are x itself,
    resampled, crossfading into the Rubber Band output over RUBBER_BAND_CROSSFADE, which joins what already played
    without a step. Returns (output, the position in x of each output sample)."""
    c = 0.5 * (1 - np.cos(np.linspace(0.0, np.pi, n_rampa, endpoint=False)))
    resto = len(x) - 2 - (n_rampa + (s - 1) * c.sum())
    vel = np.concatenate([1 + (s - 1) * c, np.full(max(0, int(resto / s)), s)])
    phi = np.concatenate([[0.0], np.cumsum(vel)[:-1]])
    y = _catmull(x, phi)
    m = len(y)
    z = _rubber_band(y, vel)[:m]
    a = min(m, RUBBER_BAND_WARMUP)
    b = min(m, a + RUBBER_BAND_CROSSFADE)
    g = np.linspace(0.0, 1.0, RUBBER_BAND_CROSSFADE, dtype=np.float32)[:b - a, None]
    z[:a] = y[:a]
    z[a:b] = y[a:b] * (1 - g) + z[a:b] * g
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
        return None, (f"the start of the next one in the queue ({t_b_fim - ini:.0f} s) doesn't cover the slow return to "
                      f"its tempo ({n_rampa / SR:.0f} s)")
    alvo_t = ini + (s * n_sob + n_rampa * (1 + s) / 2) / SR
    ate = min((t for t, _ in blocos_b if ini < t <= t_b_fim), key=lambda t: abs(t - alvo_t))
    _, xs = _junta(blocos_b, ini, ate + BLOCK / SR)
    alvo = int(round((ate - ini) * SR))
    n_rampa = max(int(RAMPA_MIN_S * SR), n_rampa + int(round((alvo - (alvo_t - ini) * SR) / ((1 + s) / 2))))
    z, phi = esticar(xs, s, n_sob, n_rampa, alvo)
    return (z, phi, ate, n_rampa), None


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
    ibi, ok = batida.network_intervals(r[0])
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
    conta inteira de uma vez prende o interpretador e o audio do jogo espera."""
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


def _processo_acima():
    """O processo inteiro um degrau acima do normal (ABOVE_NORMAL), uma vez: a thread que segura o interpretador nao perde
    a CPU para o jogo enquanto a thread de audio espera por ela. Os ffmpeg que ele abre nascem normais (o Windows so
    passa a classe adiante quando ela e abaixo do normal), e o trabalho pesado daqui e curto (a analise da passagem,
    uma vez por musica)."""
    if sys.platform != "win32" or not PROCESSO_ACIMA:
        return
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
    k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    eu = k32.GetCurrentProcess()
    if k32.GetPriorityClass(eu) == 0x20:  # NORMAL_PRIORITY_CLASS: quem rodou acima ou abaixo de proposito fica como esta
        k32.SetPriorityClass(eu, 0x8000)  # ABOVE_NORMAL_PRIORITY_CLASS


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
        import winvol  # comtypes so em thread MTA (ver _winvol_loop)
        return winvol.dispositivos()
    except Exception:
        return list_devices()


def _rescan():
    """Rele a lista do PortAudio, para abrir o que conectou depois de ele subir. Reiniciar o
    PortAudio derruba todo stream aberto: so com o motor fechado."""
    _com_init()
    sd._terminate()  # o sounddevice nao tem releitura publica
    sd._initialize()


def _mic_padrao(d):
    """O microfone padrao do Windows; se ele e um cabo virtual, o primeiro microfone de verdade da lista (None sem
    nenhum): um cabo nao leva a voz de ninguem. No notebook do bot o padrao de gravacao era um cabo, e com o microfone
    escolhido desligado o audio nem abria (08/11)."""
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


if sys.platform == "win32":
    _termina = ctypes.WinDLL("kernel32", use_last_error=True).TerminateProcess
    _termina.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    _termina.restype = ctypes.c_int


def mata(p):
    """O Popen.kill sem prender o interpretador. No Windows o kill do subprocess chama o TerminateProcess segurando o
    interpretador, e com a CPU cheia matar um ffmpeg pode levar dezenas de ms (14/11: paradas de 33 a 155 ms com outro
    processo nascendo ao mesmo tempo), em que a thread da saida para o jogo espera e o microfone fica sem musica. Pelo
    ctypes a chamada solta o interpretador. O processo que ja saiu so faz a chamada falhar; o wait de quem chamou recolhe."""
    if p.returncode is not None:
        return
    h = getattr(p, "_handle", None)
    if sys.platform != "win32" or h is None:
        p.kill()
        return
    _termina(int(h), 1)


def find_dev(name, kind):
    w = _wasapi()
    key = "max_output_channels" if kind == "out" else "max_input_channels"
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] == w and name.lower() in d["name"].lower() and d[key] > 0:
            return i, d
    raise i18n.Recusa("server.devices.notFound", "Couldn't find the device \"{name}\". Check that it's connected.",
                      name=name)


def probe_duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _aviso_reserva(faltou):
    """A mensagem da tela quando a partida usou a reserva: o que faltou e o que entrou no lugar. faltou vem do
    _reserva: o microfone, o fone ou os dois; o fone pode ter ficado em nenhum."""
    f = {nome: (escolhido, usado) for nome, escolhido, usado in faltou}
    if "microfone" in f and "fone" in f:
        (mic, mic_usado), (fone, fone_usado) = f["microfone"], f["fone"]
        if fone_usado:
            return i18n.msg("server.devices.fallback.both", "Couldn't find the microphone \"{mic}\" or the "
                                                            "headphones \"{monitor}\"; using \"{micUsed}\" and "
                                                            "\"{monitorUsed}\" until they're reconnected.", mic=mic, micUsed=mic_usado, monitor=fone, monitorUsed=fone_usado)
        return i18n.msg("server.devices.fallback.bothMonitorNone", "Couldn't find the microphone \"{mic}\" or the "
                                                                   "headphones \"{monitor}\"; using \"{micUsed}\" "
                                                                   "and no headphones until they're reconnected.",
                        mic=mic, micUsed=mic_usado, monitor=fone)
    if "microfone" in f:
        return i18n.msg("server.devices.fallback.mic", "Couldn't find the microphone \"{chosen}\"; using \"{used}\" "
                                                       "until it's reconnected.", chosen=f["microfone"][0], used=f["microfone"][1])
    fone, usado = f["fone"]
    if usado:
        return i18n.msg("server.devices.fallback.monitor", "Couldn't find the headphones \"{chosen}\"; using "
                                                           "\"{used}\" until they're reconnected.", chosen=fone, used=usado)
    return i18n.msg("server.devices.fallback.monitorNone", "Couldn't find the headphones \"{chosen}\"; using no "
                                                           "headphones until they're reconnected.", chosen=fone)


def _erro_da_tarefa(r):
    """A mensagem da tela quando a tarefa que prepara o microfone nao deu (o motivo do pede_tarefa, em
    microfone/microfone.py)."""
    motivo = r.get("motivo")
    if motivo == "sem_tarefa":
        return i18n.msg("server.mic.noTask", "The Ritmelli component that prepares microphones is missing. "
                        "Reinstall Ritmelli.")
    if motivo == "audio":
        return i18n.msg("server.mic.audioSlow", "Windows audio didn't restart in time. Close and reopen Ritmelli to "
                                                "try again.")
    return i18n.msg("server.mic.taskFailed", "Couldn't prepare the microphone ({reason}). Close and reopen Ritmelli "
                                             "to try again.",
                    reason=r.get("detalhe") or motivo or "?")


def _confere_fora(nomes=None):
    """O confere_aparelhos (microfone/microfone.py) num processo a parte, com o PortAudio dele: o daqui e o dos streams
    do motor, e abrir aparelhos nele de outra thread enquanto o vigia rele a lista (_rescan) derrubaria tudo. O
    processo novo ainda le a lista do Windows de agora. {"conferidos", "mudos", "falhas"}, ou None se nao deu."""
    cmd = [sys.executable]
    if not getattr(sys, "frozen", False):  # no codigo, o mesmo caminho pelo python (o server.auxiliar)
        cmd.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ritmelli.py"))
    # o nome junto do --aparelho=: um nome que comeca com "-" nao vira outra opcao do argparse
    cmd += ["--microfone", "confere"] + [f"--aparelho={n}" for n in nomes or ()]
    p = None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           creationflags=NO_WINDOW, startupinfo=sem_cursor())
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as ex:  # sem a conferencia, nenhum aviso: nunca um aviso falso
        motivo = p.stderr.strip()[-300:] if p is not None and p.stderr.strip() else f"{type(ex).__name__}: {ex}"
        print(f"devices: not checked ({motivo})")
        return None


def _aviso_mudos(mudos):
    """A mensagem da tela com os aparelhos que abrem e nao entregam som (#136): um nome por aparelho, o que se tira do
    cabo ("BEHRINGER UMC 404HD 192k", e nao cada entrada e saida dele)."""
    from microfone import microfone as filtro
    return i18n.msg("server.devices.silent", "Windows stopped receiving sound from the device \"{name}\". Unplug its "
                                             "USB cable and plug it back in.",
                    name="\", \"".join(filtro.aparelhos_de(mudos)))


def _do_microfone(mic):
    """O estado do filtro no microfone (o item do microfone.estado_dados: guid, filtro, melhorias), ou None se nao deu
    para ler ou o Windows nao conhece esse nome."""
    try:
        from microfone import microfone as filtro  # le o registro do Windows
        return filtro.do_microfone(mic)
    except Exception:
        return None


class _Para48k:
    """A voz crua na taxa do microfone -> 48 kHz, por interpolacao linear com estado entre os pedacos (voz: o linear
    basta, e a maioria dos microfones ja roda a 48 kHz, que passa direto)."""

    def __init__(self):
        self.taxa, self.ult, self.fase = 0, 0.0, 0.0

    def __call__(self, x, taxa):
        if taxa in (0, SR) or not len(x):
            return x
        if taxa != self.taxa:
            self.taxa, self.ult, self.fase = taxa, float(x[0]), 0.0
        passo = taxa / SR
        y = np.concatenate([[self.ult], x]).astype(np.float64)
        t = np.arange(self.fase, len(x), passo)
        out = np.interp(t, np.arange(len(y)), y).astype(np.float32)
        self.fase = (t[-1] + passo - len(x)) if len(t) else self.fase - len(x)
        self.ult = float(x[-1])
        return out


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
        self._th = threading.Thread(target=self._le, daemon=True, name="ritmelli-preabre")
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
        mata(self.ff)
        try:
            self.ff.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _prioridade_audio():
    """Poe a thread que chama na prioridade de audio do Windows (MMCSS, tarefa "Pro Audio"), como o PortAudio faz com o
    callback dele: com o jogo ocupando a CPU, a thread comum acorda tarde. Devolve (avrt, handle) para o revert, ou None
    sem o servico."""
    try:
        avrt = ctypes.WinDLL("avrt")
    except OSError:
        return None
    avrt.AvSetMmThreadCharacteristicsW.restype = ctypes.c_void_p
    avrt.AvSetMmThreadCharacteristicsW.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong))
    avrt.AvRevertMmThreadCharacteristics.argtypes = (ctypes.c_void_p,)
    tarefa = ctypes.c_ulong(0)
    h = avrt.AvSetMmThreadCharacteristicsW("Pro Audio", ctypes.byref(tarefa))
    return (avrt, h) if h else None


class Injetor:
    """A saida para o jogo: uma thread chama o misturador do motor (_mixa) e escreve no anel do filtro de microfone
    (microfone/injeta.py), que o micfx.dll soma no microfone escolhido (o alvo do anel) dentro do audio do Windows. Com
    leitor vivo (o proprio motor abre o microfone, entao ha), anda no ritmo dele, INJ_FOLGA blocos a frente; sem o anel
    ou sem leitor (o microfone sem o filtro), anda pelo relogio do PC, e o som segue no fone. Da volta, tira a voz crua
    que o filtro devolve e entrega ao motor (_push_mic), na hora: o efeito, a mina e o medidor sao dela. O pulso do anel
    leva o "poe a voz do app no lugar" (voz cortada ou com efeito): o filtro so troca com o pulso vivo, entao o app que
    cai nao deixa o microfone mudo.

    O efeito de voz que o filtro sabe rodar (microfone/preset.py monta do fx.py) vai pelo anel como preset: o filtro
    passa a voz pela cadeia no proprio bloco, sem esta ida e volta (issue #63), e devolve a voz com efeito para o fone
    e o medidor (_push_voz_fx). Enquanto o filtro nao responde (ate PRESET_ESPERA_S) a voz crua segue; recusou, ou o
    efeito tem etapa que ele nao roda nessa taxa, a voz vai pelo app, que passa ela pelo mesmo motor (o voz.dll, a
    48 kHz) e manda no lugar da crua."""

    def __init__(self, motor, saude=None):
        self.motor = motor
        self.m = None
        self.leitores = 0
        self._teve_leitor = False
        self.perdeu_em = None  # monotonic em que o ultimo leitor do alvo sumiu; None com leitor, ou se nunca teve um
        self._vai = True
        self._tentou = -1e9
        self._para48k = _Para48k()
        self._resto = np.zeros(0, np.float32)
        # a medida da folga: o menor tanto no anel (quadros) antes de completar, com o leitor ja servido; as vezes que
        # ele estava vazio (o filtro pode ter soltado silencio no lugar da musica: um engasgo no jogo); a maior volta da
        # thread (s) e quantas voltas de cada ms
        self.mmcss = None
        self.folga_min = None
        self.secas = 0
        self.volta_max = 0.0
        self.voltas = np.zeros(VOLTA_MS, np.int64)
        self._seca_dita = -1e9
        # a mesma medida e mais um pouco por janela, para o evento "audio" (metricas.py): a de cima segue a do
        # /api/state, desde que o Injetor abriu. Na reabertura do leitor perdido, a janela do de antes continua (saude)
        self.saude = saude if saude is not None else metricas.SaudeAudio(SR)
        self._para48k_fx = _Para48k()  # a voz com efeito que o filtro devolve tem a sua
        self._resto_fx = np.zeros(0, np.float32)
        self._resto_pista = np.zeros(0, np.float32)  # e a voz da pista (ja a 48 kHz)
        self._preset = None      # (efeito, taxa, geracao) do preset escrito no anel: o reload (preset.esquece) reenvia
        self._preset_seq = 0     # o seq dele, que o filtro devolve quando le
        self._preset_ok = False  # o efeito tem preset (o filtro roda)
        self._preset_em = 0.0    # monotonic da escrita
        self.efeito_no_filtro = False
        self.voz_taxa = 0  # a taxa do microfone alvo, copiada do anel pela thread: quem esta fora dela le daqui, e nao
        # da vista, que a thread fecha quando o anel falha
        self._th = threading.Thread(target=self._loop, daemon=True, name="ritmelli-microfone")
        self._th.start()

    def estado(self):
        return {"anel": self.m is not None, "leitores": self.leitores,
                "folga_min_ms": None if self.folga_min is None else round(self.folga_min * 1000 / SR, 1),
                "secas": self.secas, "volta_max_ms": round(self.volta_max * 1000, 1),
                "efeito_no_filtro": self.efeito_no_filtro}

    def _volta(self, s):
        self.volta_max = max(self.volta_max, s)
        self.voltas[min(int(s * 1000), VOLTA_MS - 1)] += 1

    def _confere_fila(self, fila, volta):
        """O tanto no anel quando a thread chegou, antes de completar: guarda o menor e conta (e diz, no maximo a cada
        10 s) quando secou."""
        if self.folga_min is None or fila < self.folga_min:
            self.folga_min = fila
        seca = fila == 0
        self.saude.fila(fila, passagem=seca and self.motor.em_passagem(), esticando=seca and RUBBER_BAND.em_curso())
        if seca:
            self.secas += 1
            if time.monotonic() - self._seca_dita > 10.0:
                self._seca_dita = time.monotonic()
                print(f"game output: the microphone ring ran dry (the thread came back after {volta * 1000:.0f} ms; "
                      f"{self.secas} so far)", file=sys.stderr, flush=True)

    def para(self):
        self._vai = False
        self._th.join(timeout=1.0)
        m, self.m = self.m, None
        if m is not None:
            try:
                m.pulso(False)  # a voz volta na hora, sem esperar o pulso vencer
                m.alvo(0)       # e nenhum filtro mexe mais no som
                m.fecha()
            except Exception:  # fechando: o filtro devolve a voz sozinho em 1 s
                pass

    def _abre(self):
        """O anel, tentando de novo a cada 1 s: ele so existe com algum microfone com o filtro em uso."""
        if self.m is not None or time.monotonic() - self._tentou < 1.0:
            return self.m
        self._tentou = time.monotonic()
        from microfone import injeta  # so no Windows
        try:
            self.m = injeta.Microfone()
        except injeta.SemFiltro:
            self.m = None
        return self.m

    def _efeito(self, m):
        """O preset do efeito escolhido no anel (na taxa do microfone alvo) e o estado do filtro com ele: roda
        (efeito_no_filtro), ainda nao respondeu (_fx_pendente: a voz crua segue) ou recusou (a voz vai pelo app)."""
        mo = self.motor
        eid = mo._fx_id
        taxa = self.voz_taxa = int(m.a.voz_taxa)
        chave = (eid, taxa, preset.geracao())
        if chave != self._preset:
            dados = preset.pede(eid, taxa) if eid and taxa else None
            if dados is preset.PENDENTE:  # o projeto roda a parte (ate ~70 ms): a voz crua segue ate ficar pronto
                self.efeito_no_filtro = False
                mo._fx_filtro, mo._fx_pendente = False, True
                return
            self._preset_seq = m.preset(dados or b"")
            self._preset, self._preset_ok, self._preset_em = chave, dados is not None, time.monotonic()
        feito, erro = m.preset_estado()
        respondeu = feito == self._preset_seq
        self.efeito_no_filtro = self._preset_ok and respondeu and erro == 0
        mo._fx_filtro = self.efeito_no_filtro
        mo._fx_pendente = (self._preset_ok and not respondeu
                           and time.monotonic() - self._preset_em < PRESET_ESPERA_S)

    def _solta_efeito(self):
        self.efeito_no_filtro = False
        self.motor._fx_filtro = self.motor._fx_pendente = False
        self.motor._pista_viva = False
        self._preset = None
        self.voz_taxa = 0  # o anel que vier depois diz a dele

    def _voz(self, m):
        """A voz crua que chegou, a 48 kHz, em blocos de BLOCK para o motor (o que sobra fica para a proxima); com o
        efeito no filtro, tambem a voz com efeito que ele devolveu (fone e medidor)."""
        y, taxa_fx = m.voz_fx()  # sempre le: a posicao anda junto com o filtro
        if self.efeito_no_filtro and len(y):
            y = np.concatenate([self._resto_fx, self._para48k_fx(y, taxa_fx)])
            n = len(y) // BLOCK * BLOCK
            for k in range(0, n, BLOCK):
                self.motor._push_voz_fx(y[k:k + BLOCK])
            self._resto_fx = y[n:]
        # a pista da voz no comando (um processo converte a voz e o filtro poe no lugar da do microfone): o fone e o
        # medidor levam a voz dela, que e o que o jogo ouve, e nao a crua
        p = m.pista_le()  # sempre le: a posicao anda junto com o escritor
        viva = m.pista_viva()
        self.motor._pista_viva = viva
        if viva and len(p):
            p = np.concatenate([self._resto_pista, p])
            n = len(p) // BLOCK * BLOCK
            for k in range(0, n, BLOCK):
                self.motor._push_voz_fx(p[k:k + BLOCK])
            self._resto_pista = p[n:]
        elif not viva:
            self._resto_pista = self._resto_pista[:0]
        x, taxa = m.voz()
        if not len(x):
            return
        x = np.concatenate([self._resto, self._para48k(x, taxa)])
        n = len(x) // BLOCK * BLOCK
        for k in range(0, n, BLOCK):
            self.motor._push_mic(x[k:k + BLOCK])
        self._resto = x[n:]
        self.motor._voz_anel_em = time.monotonic()

    def _loop(self):
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)  # o sleep de 2 ms dorme 2 ms, e nao 15
        mm = _prioridade_audio() if INJ_MMCSS else None
        self.mmcss = mm is not None
        prox = antes = time.perf_counter()
        servidos = ()  # os leitores que ja receberam o anel cheio: o vazio de quem acabou de chegar nao e seca
        try:
            while self._vai:
                agora = time.perf_counter()
                volta, antes = agora - antes, agora
                self._volta(volta)
                contou = False  # a janela do "audio" ja recebeu esta volta
                try:
                    m = self._abre()
                    if m is not None:
                        m.alvo(self.motor._alvo)
                        self._efeito(m)
                        m.pulso(self.motor.voz_pelo_app())
                        self._voz(m)
                    else:
                        self._solta_efeito()
                    vivos = m.vivos() if m is not None else []
                    self.leitores = len(vivos)
                    mo = self.motor
                    self.saude.volta(volta, anel=m is not None, leitores=self.leitores,
                                     fx_no_filtro=self.efeito_no_filtro, voz_taxa=self.voz_taxa,
                                     totais=(*mo.totais_saude(), *RUBBER_BAND.total()))
                    contou = True
                    if vivos:
                        self._teve_leitor, self.perdeu_em = True, None
                        donos = tuple(sorted(lt.dono for lt in vivos))
                        fila = m.na_fila()
                        if donos == servidos:
                            self._confere_fila(fila, volta)
                        # no maximo INJ_FOLGA blocos (o que enche o anel vazio): o leitor que some no meio deixa o
                        # na_fila em 0, e sem o limite a thread nao saia daqui nem via a perda
                        for _ in range(INJ_FOLGA):
                            if not self._vai or fila > (INJ_FOLGA - 1) * BLOCK:
                                break
                            m.escreve(self.motor._mixa(BLOCK))
                            fila = m.na_fila()
                        servidos = donos
                        prox = time.perf_counter() + BLOCK / SR
                    else:
                        servidos = ()
                        if self._teve_leitor and self.perdeu_em is None:
                            self.perdeu_em = time.monotonic()  # o vigia reabre se ele nao voltar (_recupera_leitor)
                        if agora - prox > 0.2:  # voltou de um leitor, ou a thread atrasou: nao corre atras
                            prox = agora
                        while self._vai and agora >= prox:
                            self.motor._mixa(BLOCK)  # o fone e o relogio da musica seguem
                            prox += BLOCK / SR
                except Exception as ex:  # a thread nao morre calada: o erro vai pra tela
                    self.motor.set_error(i18n.msg("server.mic.outputFailed", "Couldn't send audio to the microphone "
                                                  "({reason}). If the music doesn't come back through the "
                                                  "microphone, close and reopen Ritmelli.", reason=str(ex)[:160]))
                    # o anel que falhou fecha (o mapa e o handle nao ficam abertos ate o app sair) e o _abre tenta um
                    # novo; o estado do efeito zera mesmo se o fechamento falhar
                    falhou, self.m = self.m, None
                    servidos = ()
                    self.saude.anel_caiu(volta, contou)  # a pausa abaixo nao conta no estado do anel que caiu
                    try:
                        if falhou is not None:
                            falhou.fecha()
                    except Exception:  # o erro que vale ja esta na tela
                        pass
                    finally:
                        self._solta_efeito()
                    time.sleep(0.5)
                time.sleep(0.002)
        finally:
            if mm is not None:
                mm[0].AvRevertMmThreadCharacteristics(mm[1])
            winmm.timeEndPeriod(1)


class Engine:
    _stream_warning = None

    def __init__(self, mic, monitor):
        self.devices = {"mic": mic, "monitor": monitor}  # nome, 'default' ou '' (sem fone)
        self.active = dict(self.devices)  # nomes reais abertos
        self.vol = 0.6         # arquivo no microfone (o que o jogo ouve)
        self.mon_vol = 0.6     # arquivo no fone de quem toca
        self.mic_vol = 1.0     # nivel do mic no Windows (a thread do winvol le e grava)
        self._wv = None        # pedidos de nivel para essa thread
        self._wv_n = 0         # conta os pedidos: leitura velha nao pisa num pedido novo
        self.mic_mute = False
        self._injetor = None   # o Injetor (a saida para o jogo), com o audio aberto
        self._alvo = 0         # o hash do microfone em uso no anel do filtro (0 = nenhum, ainda)
        self._voz_anel_em = -1e9  # monotonic da ultima voz crua que o filtro devolveu (a do microfone fica de reserva)
        self.preparando = None  # o microfone que o Windows esta preparando para o Ritmelli (a tarefa do instalador)
        self._preparados = set()  # os microfones em que a preparacao ja rodou nesta sessao (nao repete)
        self._mudos_vistos = False  # os aparelhos mudos que o instalador ou a tarefa acharam ja foram conferidos
        self.monitor_on = True
        self.loop = False
        self.effect = "nenhum"  # efeito de voz (fx.py); sempre comeca sem efeito
        self._fx_id = None  # o efeito que mexe na voz (o filtro recebe o preset dele); None sem efeito e com a mina
        self._fx = None     # a cadeia dele no app (voz.Cadeia, a 48 kHz); None sem efeito ou sem o voz.dll
        self._fx_falta_dito = False  # o aviso de efeito sem o voz.dll ja saiu para o efeito escolhido
        self._fx_filtro = False    # o filtro do microfone roda o efeito (o Injetor marca): a voz nao passa pelo app
        self._fx_pendente = False  # o preset foi pro filtro e ele ainda nao respondeu: a voz crua segue
        self._pista_viva = False   # a pista da voz do anel esta no comando (o Injetor marca): o fone leva a voz dela
        self._pista_enche = True   # a fila do fone da pista secou: espera PISTA_ENCHE antes de voltar a tocar
        if not voz.disponivel():  # o app sobe igual: o efeito segue no filtro, e so a voz que sairia daqui vai crua
            print(f"voice effect: no voz.dll ({voz.caminho()}); the effect only runs in the microphone filter",
                  file=sys.stderr, flush=True)
        # a mina do pedal MINA (mina.py): a voz dela vai pro jogo e pro fone como a voz de quem toca
        self.mina_permitida = True
        self._mina = None
        self._pv_fila = None   # a fila do liga() do pedal de troca de voz, lida pela thread dele (so com o modulo dele)
        self._pv_fechada = False
        self._mina_buf = np.zeros(0, np.float32)
        self._mina_lock = threading.Lock()
        self._mina_voz_em = -1e9  # monotonic do ultimo pedaco com voz dela que tocou
        self._mina_int_n = 0  # amostras da frente da fila que sao a interjeicao dela (nao seguram o guarda)
        self._fone_calado = False  # a mina ouvindo o aparelho inteiro que e o fone: o fone fica mudo (mina_cala_fone)
        self.voice_monitor = False  # ouvir a propria voz (com o efeito) no fone
        self.voice_mon_vol = 0.8
        # sons por cima (buzina, bordao): tocam junto da musica sem parar ela; cada um e
        # [item, audio inteiro (n x 2), posicao], misturados no _mixa
        self._sobre = []
        self._slock = threading.Lock()
        self._sobre_cache = collections.OrderedDict()
        self._abaixa = None    # (ganho, monotonic do fim, db, ms): a musica abaixada no jogo ate o fim (abaixa)
        self._abaixa_g = 1.0   # o ganho do abaixamento no ultimo bloco: o proximo sai dele em rampa, sem estalo
        self._sinal = None     # [bipe (n), posicao, prazo]: o sinal de teste no microfone (sinal); so ele escreve
        #                        aqui, e o bipe que nao comecou ate o prazo (monotonic) nao toca mais
        self.track = None      # item da biblioteca carregado
        self.paused = False
        self.ended = False
        self.pos = 0.0
        self._error = None
        # o primeiro som do disco que entrou no prato (09/11, a latencia do pedido falado): espera e load marcam
        # (id, hora do relogio), o _mixa troca pelo (titulo, stream?, entrou, soou) no primeiro bloco dele, e o
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
        self._eco = None         # [audio, feitos, deck que saiu]: o eco do corte no 1 (feitos < 0: ainda nao)
        self._eco_plano = None   # (audio, quadros depois da virada) do plano medido, ate a virada
        self._entrando = None    # [quadros, feitos, nivel, cheia]: a proxima subindo
        # o bloco do prato que o _mixa retirou e ainda nao publicou, (deck, linha, onde ele acaba), sob o _qlock: a
        # pausa espera a publicacao dele, e a troca do stream pelo arquivo comeca o leitor novo depois dele
        self._bloco = None
        self._pausa = None       # a Pausa da linha do prato (pendente ou confirmada), sob o _qlock
        self.virou = None        # (o que saiu, o que entrou, a tag) para o servidor tirar da fila
        self.preparos = 0        # as passagens preparadas desde que o motor abriu (o evento "audio" conta por janela)
        self.reserva_quadros = 0  # os quadros da voz que vieram do microfone de reserva (o _mic_cb), idem
        self._virou_em = -1e9    # monotonic da ultima virada (a seca logo depois dela e da passagem)
        self.periodo_saida = None  # a batida do que sai na saida (s), pelo plano no tempo: a regua dos testes (dev/)
        self._prepare_failure_tag = None
        # o servidor religa a parecida do Automatico cujo stream caiu: religar_stream(disco, onde parou, desistir), na
        # thread do leitor; sem ele (ou desistindo), o disco acaba e a fila segue, como antes
        self.religar_stream = None
        self._stream_silent = None
        # o volume automatico (sonoridade.py): as musicas mais baixas sobem ate o alvo, com o limitador na musica (a
        # musica sai sonoridade.LIMITE_ANTES amostras atrasada, sempre). O servidor diz a medida que ja tem de um disco
        # (sonoridade_de(disco) -> LUFS ou None) e guarda a que o motor mede (mediu(disco, LUFS)); sem os dois, a
        # medida fica so nesta sessao
        self.volume_auto = True
        self.sonoridade_de = None
        self.mediu = None
        self._medidas = {}  # chave do disco -> (LUFS, inteira?): o que o motor ja mediu nesta sessao
        self._medindo = set()  # as chaves com o arquivo sendo medido
        self._med_lock = threading.Lock()
        self._limitador = sonoridade.Limitador()
        self._limitador_zera = False  # o prato trocou ou pulou: o _mixa joga fora os 2 ms que o limitador segura
        # o visor de DJ do tema: as ondas por id do disco (_onda_pede, onda) e a passagem que vem e a que acabou de
        # acontecer, no formato do visor (_mede, _vira; ver o snapshot)
        self._ondas = collections.OrderedDict()
        self._olock = threading.Lock()
        self._ondas_versao = 0   # sobe quando uma onda do arquivo fica pronta: o tema pede de novo
        self._onda_fila = None   # a fila da thread da onda do arquivo (sobe no primeiro pedido)
        self._onda_lendo = set()  # os ids com a onda do arquivo na fila ou sendo lida
        self._visor_pas = None   # a passagem medida deste para a proxima
        self._visor_feita = None  # a que trouxe este disco, enquanto o tema ainda desenha a sobreposicao
        self._passagens_dia = None  # o dia (AAAA-MM-DD) em que o _registra_fim ja podou logs/passagens/
        self._mic = collections.deque()
        self._mon = collections.deque()
        self._stack = None
        self._lock = threading.RLock()
        self._vigia = None        # thread que segue o aparelho escolhido (_vigia_loop)
        self._fechado = False     # close() de proposito: o vigia nao reabre
        self._caiu_no_vigia = False  # a reabertura do vigia falhou: ele pode tentar de novo
        self._recupera = None     # (microfone, reaberturas, monotonic da ultima) do leitor perdido (_recupera_leitor)
        # (o microfone, a janela do "audio") que o Injetor da reabertura do leitor perdido continua, no mesmo microfone
        self._saude_segue = None
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
        return {"mic": mic, "monitor": mon}

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
        _processo_acima()
        # o modelo da rede abre ja e fica aberto (~100 MB): abrir segura o interpretador ~0,6 s, e reabrindo a cada
        # plano o audio estalava (num notebook, aos ~30 s do Where's My Love, 22/10); aqui ainda nao toca nada
        threading.Thread(target=compasso.abre_ja, daemon=True).start()
        self._fechado = False
        # antes de procurar os aparelhos: a partida que nao acha o microfone fica esperando ele pelo vigia
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
        mon_i = find_dev(act["monitor"], "out")[0] if act["monitor"] else None
        self.active = {"mic": mic_d["name"],
                       "monitor": sd.query_devices(mon_i)["name"] if mon_i is not None else ""}
        self._alvo = 0  # ate a thread do filtro achar o microfone: nenhum filtro mexe no som
        st = contextlib.ExitStack()
        try:
            # o microfone aberto daqui mantem o filtro dele rodando (e o anel vivo) mesmo com o jogo fechado; o que se
            # le aqui so vale sem a voz crua do filtro (o microfone sem ele), porque ja leva a musica
            st.enter_context(sd.InputStream(device=mic_i, channels=mic_d["max_input_channels"],
                                            samplerate=SR, blocksize=BLOCK, dtype="float32",
                                            extra_settings=WASAPI, callback=self._mic_cb))
            segue = self._saude_segue
            inj = Injetor(self, segue[1] if segue and segue[0] == self.active["mic"] else None)
            st.callback(inj.para)
            if mon_i is not None:
                st.enter_context(sd.OutputStream(device=mon_i, channels=2, samplerate=SR,
                                                 blocksize=BLOCK, dtype="float32",
                                                 extra_settings=WASAPI, callback=self._mon_cb))
        except Exception:
            st.close()
            raise
        self._stack = st
        self._injetor = inj
        if faltou:
            self._aviso = self._error = _aviso_reserva(faltou)
        elif self._aviso is not None and self._error == self._aviso:
            self._error = None  # the chosen device came back: only the warning leaves, never a playback error
        threading.Thread(target=self._confere_filtro, args=(self.active["mic"],), daemon=True).start()

    def _confere_filtro(self, mic):
        """O microfone em uso com o filtro: o alvo do anel e o hash dele. Sem o filtro (um microfone que apareceu depois
        da instalacao) ou com as melhorias de audio desligadas, roda a tarefa do instalador, que prepara como SYSTEM
        sem pedir nada a ninguem, e reabre o audio (o do Windows reinicia uns segundos). Uma vez por microfone. Depois
        de reiniciar o audio, e uma vez com o filtro pronto, confere se algum aparelho parou de entregar som (#136)."""
        _com_init()
        st = _do_microfone(mic)
        if st and st["filtro"] and st["melhorias"]:
            from microfone import injeta
            if self.active.get("mic") == mic:
                self._alvo = injeta.hash_microfone(st["guid"])
                with self._lock:  # o dos mudos fica: ele acabou de sair desta pilha e sai quando o audio reabre
                    if (self._aviso is not None and self._error == self._aviso
                            and self._aviso.get("key") != "server.devices.silent"):
                        self._error = None
            with self._lock:  # uma vez, so os que o instalador ou a tarefa acharam mudos: abrir todos a cada partida
                ver = not self._mudos_vistos  # incomodaria
                self._mudos_vistos = True
            if ver:
                from microfone import microfone as filtro
                mudos = filtro.le_mudos()
                if mudos:
                    self._confere_mudos(mudos)
            return
        if mic in self._preparados:
            if self.active.get("mic") == mic:
                self._aviso = self._error = i18n.msg("server.mic.notReadyReinstall", "Couldn't prepare the microphone "
                                                                                    "\"{name}\" for Ritmelli, so the "
                                                                                    "music can't reach it. Try "
                                                                                    "reinstalling Ritmelli.", name=mic)
            return
        self._preparados.add(mic)
        from microfone import microfone as filtro
        self.preparando = mic
        # o som do PC some enquanto o Windows reinicia o audio: a tela diz por que
        prep = self._aviso = self._error = i18n.msg("server.mic.preparing", "Preparing the microphone \"{name}\" for "
                                                   "Ritmelli: the computer's sound will cut out for a few seconds.", name=mic)
        try:
            r = filtro.pede_tarefa(mic)
        finally:
            self.preparando = None
        if not r.get("ok") and not r.get("reopen"):
            self._aviso = self._error = _erro_da_tarefa(r)
            return
        if self._error == prep:
            self._aviso = self._error = None
        with self._lock:
            if self._fechado:
                return
            # os do registro entram nesta, e antes do _reabre: o _confere_filtro que ele abre nao confere junto
            self._mudos_vistos = True
            self._reabre()
        self._confere_mudos()  # todos: o reinicio do audio pode ter deixado qualquer aparelho mudo

    def _confere_mudos(self, nomes=None):
        """Confere (num processo a parte, _confere_fora) se os aparelhos, ou so esses nomes, entregam som, e avisa na
        tela os que abrem e nao entregam nada (#136: uma interface USB depois do reinicio do audio, ate tirar o cabo).
        O aviso e dos aparelhos (_aviso), como o da reserva: sai quando o audio reabre (o vigia reabre quando o
        aparelho em uso e tirado e posto de volta), e ao tocar, parar ou pular, como todo erro da tela. O audio que
        reabriu (ou caiu) enquanto a conferencia rodava deixa o resultado de fora: ele e de antes, e a reabertura que
        falhou tem o aviso dela. Sem audio aberto (a reabertura depois da tarefa que falhou), nem abre os aparelhos:
        os mudos do registro (a conferencia da propria tarefa) ficam para quando o audio abrir (_confere_filtro)."""
        with self._lock:  # o _reabre fecha e abre sob o _lock: aqui, nunca a pilha do meio dele
            pilha = self._stack
            if pilha is None:
                self._mudos_vistos = False
                return
        r = _confere_fora(nomes)
        mudos = (r or {}).get("mudos")
        if mudos:
            print(f"devices: silent: {'; '.join(mudos)}")
        with self._lock:
            if self._stack is None:  # o audio caiu durante a conferencia: os do registro, para quando ele voltar
                self._mudos_vistos = False
            elif mudos and not self._fechado and self._stack is pilha:
                self._aviso = self._error = _aviso_mudos(mudos)

    def liga(self):
        """A partida do servidor. Se o audio nao abre (sem microfone, aparelho que recusa), o servidor sobe mesmo
        assim com o erro na tela, e o vigia (logo depois, e de novo quando a lista muda) ou a troca de aparelho pela
        interface tentam de novo. Antes, o app inteiro caia com o erro do Python (29/10)."""
        with self._lock:
            try:
                self.start(reserva=True)
            except Exception as ex:
                self._sem_audio(ex)

    def close(self):
        self._pedal_voz_fecha()
        if self._mina is not None:
            self._mina.desliga()
        with self._lock:
            self._fechado = True
            self._recupera = None
            with self._qlock:
                self._gen += 1
                self._solta_pausa()
            if self._stack:
                self._stack.close()
                self._stack = None
                self._injetor = None

    def voz_pelo_app(self):
        """A voz que vai para o jogo sai daqui (o filtro poe a do app no lugar da crua): cortada, ou com o efeito que o
        filtro nao roda (o app roda, pelo voz.dll; sem ele, a voz crua segue no microfone)."""
        return self.mic_mute or (self._fx is not None and not self._fx_filtro and not self._fx_pendente)

    def _vigia_loop(self):
        """Segue sozinho o aparelho escolhido quando ele conecta ou desconecta (o Quest pelo
        Virtual Desktop, 20/10): le a lista do Windows a cada VIGIA_S e, so quando ela muda,
        reabre o que a partida com reserva abriria, se for diferente do que esta aberto. Lista
        parada so reabre o filtro que parou de ler (_recupera_leitor; cada reabertura corta uns 90 ms);
        a escolha do usuario (devices) e o config nunca mudam daqui."""
        _com_init()
        assin, resta = None, 0
        while True:
            time.sleep(VIGIA_S)
            if self._fechado:
                continue
            try:
                d = list_devices_live()
            except Exception:  # leitura falhou: tenta na volta
                continue
            a = (tuple(d["inputs"]), tuple(d["outputs"]), d["default_input"], d["default_output"])
            if a != assin:
                assin, resta = a, VIGIA_TENTATIVAS
            if resta <= 0:
                self._recupera_leitor()
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

    def _recupera_leitor(self):
        """O filtro do microfone em uso parou de ler e nao voltou, com o motor ainda capturando o mesmo microfone e a
        lista de aparelhos parada (o vigia so reabria quando ela mudava): reabre depois de LEITOR_PERDIDO_S sem leitor,
        a cada LEITOR_INTERVALO_S, no maximo LEITOR_TENTATIVAS vezes. O microfone que nunca teve leitor (sem o filtro)
        nao conta; o leitor que volta (mesmo que some de novo entre duas voltas do vigia), o motor fechado e a troca
        manual zeram a conta. A reabertura daqui que falha (sem stream nenhum) segue na conta, no mesmo ritmo."""
        with self._lock:
            inj, r = self._injetor, self._recupera
            mic = self.active.get("mic")
            sem_audio = self._stack is None
            if (self._fechado or inj is None or (r and r[0] != mic)
                    or (sem_audio and not (r and self._caiu_no_vigia))):
                self._recupera = None
                return
            agora = time.monotonic()
            if not sem_audio:
                if inj.leitores:  # leitor vivo: zera e sai, sem olhar o prazo de um perdeu_em lido antes
                    self._recupera = None
                    return
                perda = (inj, inj.perdeu_em)  # muda quando o leitor volta: o Injetor zera e marca de novo
                if r and r[3] != perda:
                    r = self._recupera = None
                if r is None:
                    if perda[1] is None or agora - perda[1] < LEITOR_PERDIDO_S:
                        return  # nunca teve leitor (sem o filtro), ou ainda cedo: o que o Windows remonta volta antes
                    r = (mic, 0, -1e9, perda)
            _, n, em, _ = self._recupera = r
            if n >= LEITOR_TENTATIVAS or agora - em < LEITOR_INTERVALO_S:
                return
            print(f"game output: the microphone filter stopped reading \"{mic}\"; reopening the audio "
                  f"(attempt {n + 1} of {LEITOR_TENTATIVAS})", file=sys.stderr, flush=True)
            self._saude_segue = (mic, inj.saude)  # a perda que pede a reabertura fica na janela do evento "audio"
            try:
                self._reabre()
            finally:
                self._saude_segue = None
            # o Injetor novo (ou o de antes, se a reabertura falhou) ainda sem perda marcada
            self._recupera = (mic, n + 1, agora, (self._injetor, None))

    def _reabre(self):
        """Fecha so os streams (o disco segue no prato), rele o PortAudio e abre com reserva.
        Chamar com self._lock. A conta do leitor perdido zera (o _recupera_leitor guarda a dele depois)."""
        self._recupera = None
        if self._stack:
            self._stack.close()
            self._stack = None
        try:
            _rescan()
            self.start(reserva=True)
            self._caiu_no_vigia = False
        except Exception as ex:  # tenta de novo na volta, dentro do VIGIA_TENTATIVAS
            self._sem_audio(ex)

    def _sem_audio(self, ex):
        """O audio nao abriu: o erro fica na tela e o vigia pode tentar de novo. A mesma frase na partida e na
        reabertura: a partida que falha tambem passa pelo vigia logo depois."""
        self._caiu_no_vigia = True
        self._aviso = self._error = i18n.msg("server.audio.openFailed", "Couldn't start the audio ({reason}). Make "
                                                                       "sure the microphone and headphones are "
                                                                       "connected. If the problem continues, close "
                                                                       "and reopen Ritmelli.",
                                            reason=i18n.motivo(ex))

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
        import winvol
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
                    ep = winvol.volume_do(nome)
                if ep is None:
                    if v is not None:
                        self._error = i18n.msg("server.devices.micVolumeMissing", "Couldn't find the Windows volume "
                                                                                 "control for the microphone "
                                                                                 "\"{name}\".", name=nome)
                    continue
                if v is not None:
                    winvol.gravar(ep, v)
                n = self._wv_n
                lido = winvol.ler(ep)
                if n == self._wv_n:  # pedido novo no meio da leitura: a barra fica com ele
                    self.mic_vol = lido
            except Exception:  # mic desconectado: procura de novo na volta
                ep, nome = None, None

    def set_devices(self, mic=None, monitor=None):
        with self._lock:
            old = dict(self.devices)
            new = dict(old)
            for k, v in (("mic", mic), ("monitor", monitor)):
                if v is not None:
                    new[k] = v
            if self._stack:
                self._stack.close()
                self._stack = None
            self._recupera = None  # a escolha de agora: a conta do leitor perdido recomeca
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
        if time.monotonic() - self._voz_anel_em < VOZ_VIVA_S:
            return  # a voz vem crua do filtro; a daqui ja leva a musica
        self.reserva_quadros += frames
        self._push_mic(indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0].copy())

    def _push_mic(self, x):
        mi = self._mina
        # a mina ouve quem toca tambem (a voz crua, sem o efeito), mas so com a voz indo pro jogo: com a voz cortada
        # (o notebook do bot) o mic nao e a voz de ninguem no mapa, e ela ouvia quem estava do lado do notebook (03/11)
        if mi is not None and not self.mic_mute:
            mi.microfone(x)
        if self._fx_filtro or self._pista_viva:
            return  # o efeito roda no filtro (ou a voz vem da pista): a que o jogo ouve chega pelo _push_voz_fx
        f = self._fx
        if f is not None:
            try:
                x = f(x)  # o motor do filtro (voz.h) pelo voz.dll, a 48 kHz
            except Exception as ex:  # efeito quebrado nao pode calar a voz
                self._fx_id, self._fx, self.effect = None, None, "nenhum"
                self._error = i18n.msg("server.effect.failed", "The voice effect failed ({reason}). You're back to "
                                                              "your natural voice.", reason=str(ex)[:120])
        elif self._fx_id is not None and not self._fx_pendente and not self._fx_falta_dito:
            # o efeito sairia daqui e o voz.dll nao carregou: a voz segue crua, e o aviso sai uma vez por efeito
            self._fx_falta_dito = True
            self._error = i18n.msg("server.effect.noVozDll", "Ritmelli's voz.dll file is missing, so voice effects "
                                                            "won't work on this microphone. Your voice still reaches "
                                                            "the game as usual. Reinstall Ritmelli.")
        self._mic.append(x)
        while len(self._mic) > MIC_MAX:
            self._mic.popleft()

    def _push_voz_fx(self, x):
        """A voz com efeito que o filtro do microfone devolveu, ou a da pista da voz: o fone (ouvir a propria voz) e o
        medidor."""
        self._mic.append(x)
        teto = PISTA_MAX if self._pista_viva else MIC_MAX
        while len(self._mic) > teto:
            self._mic.popleft()

    def set_effect(self, effect_id):
        try:
            nova = fx.criar(effect_id)  # a definicao do efeito: None sem efeito (e a mina)
        except ValueError:
            raise i18n.Recusa("server.effect.unknown", "Unknown voice effect \"{id}\".", id=effect_id) from None
        cadeia = self._cadeia(effect_id) if nova is not None else None
        inj = self._injetor
        taxa = inj.voz_taxa if inj is not None and inj.m is not None else 0
        if nova is not None and taxa:
            # o preset do filtro fica pronto aqui, e nao na thread da saida para o jogo (o do Locutor projeta um FIR de
            # 1023, ate ~70 ms): o Injetor so acha o efeito novo depois disso
            preset.preset(effect_id, taxa)
        self.effect = effect_id
        self._fx_falta_dito = False
        self._fx = cadeia  # antes do _fx_id: quando o Injetor acha o efeito novo, a cadeia do app ja e a dele
        self._fx_id = effect_id if nova is not None else None
        if effect_id == "mina":
            self._mina_liga()
        elif self._mina is not None:
            self._mina.desliga()
        self._pedal_voz_liga(effect_id == "pistavoz")

    def _pedal_voz_liga(self, ligado):
        """Conta ao modulo do pedal de troca de voz (pistavoz.py, ver o fx.py) cada troca de efeito: ligado so no pistavoz.
        O liga() dele roda numa thread so dele (daemon), na ordem das trocas, e nunca no laco do servidor (a troca vem do
        handler do /api/settings); o erro dele vai para o log e nao derruba nada."""
        pv = fx.pistavoz
        if pv is None or self._pv_fechada:
            return
        if self._pv_fila is None:
            self._pv_fila = queue.SimpleQueue()
            threading.Thread(target=self._pedal_voz_laco, args=(pv, self._pv_fila), name="pedal_voz", daemon=True).start()
        self._pv_fila.put((ligado, None))

    @staticmethod
    def _pedal_voz_laco(pv, fila):
        """A thread do liga(): um pedido por vez, na ordem; a sentinela (None, Event) do fechar acaba com ela."""
        while True:
            ligado, feito = fila.get()
            if ligado is None:
                feito.set()
                return
            try:
                pv.liga(ligado)
            except Exception as ex:  # o modulo e de fora: o erro dele nao derruba a troca de efeito
                print(f"pedal_voz: liga() failed ({str(ex)[:120]})", file=sys.stderr, flush=True)

    def _pedal_voz_fecha(self):
        """O app fechando: o modulo do pedal de voz ouve o liga(False) e a thread dele acaba. Espera ate 2 s; a thread e
        daemon, entao um modulo travado nao segura o processo depois de fechar a janela."""
        if fx.pistavoz is None or self._pv_fechada:
            return
        self._pedal_voz_liga(False)
        self._pv_fechada = True
        feito = threading.Event()
        self._pv_fila.put((None, feito))
        feito.wait(2)

    @staticmethod
    def _cadeia(effect_id):
        """A cadeia do efeito para a voz que sai pelo app (o filtro recusou o efeito, ou o microfone sem o filtro e a
        voz so no fone): o preset a 48 kHz no mesmo motor do filtro, pelo voz.dll. None sem o voz.dll (a partida ja
        disse no log): o efeito segue no filtro, e a voz que sairia daqui vai crua, com o aviso do _push_mic."""
        dados = preset.preset(effect_id, SR)  # a 48 kHz todo efeito tem par no voz.h (o dev/testa_voz.py confere)
        if dados is None:
            print(f"voice effect: {effect_id} has no 48 kHz preset; through the app the voice stays raw", file=sys.stderr,
                  flush=True)
            return None
        try:
            return voz.Cadeia(dados, SR)
        except OSError:
            return None
        except ValueError as ex:  # o filtro recusou o preset (o voz.ERROS): o efeito nao troca
            raise i18n.Recusa("server.effect.refused", "Couldn't set up the voice effect ({reason}).",
                              reason=str(ex)) from None

    # a mina (mina.py) -----------------------------------------------------
    def _mina_liga(self):
        if not self.mina_permitida or mina is None:
            return
        try:
            if self._mina is None:
                self._mina = mina.Mina(self)
            self._mina.liga()
        except i18n.Recusa as ex:
            self._error = ex.msg
        except ValueError as ex:
            self._error = i18n.msg("server.mina.notConfigured", "This effect isn't configured ({reason}).", reason=str(ex))

    def mina_voz(self, x):
        """A voz dela, float32 48 kHz mono, na fila do jogo. Volta em quantos segundos ela comeca a tocar (a gravacao
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
        with self._mina_lock:
            self._mina_buf = self._mina_buf[:0]
            self._mina_int_n = 0

    def mina_interjeicao(self, x):
        with self._mina_lock:
            b = self._mina_buf
            if len(b) and float(np.max(np.abs(b))) >= mina.QUIET_RMS:  # a voz da resposta ja esta na fila
                return False
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
            print(f"mina: {'muted the headphones (' + self.active['monitor'] + '), the device she listens to' if calar else 'headphones back'}",
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

    def _mixa(self, frames):
        """O bloco que vai para o jogo, e o do fone na fila dele: o disco, os sons por cima, a voz (so a que volta pelo
        app: com efeito) e a da mina. Quem chama e o relogio da saida, o Injetor. O disco vem em tres passos: o
        _captura tira o bloco e o estado da passagem sob o _qlock, o _renderiza calcula fora dele e o _publica aplica
        sob o _qlock so se o deck e a linha ainda sao os do prato; senao, a musica deste bloco sai e nada dele vale."""
        buf = np.zeros((frames, 2), np.float32)
        b = self._captura(frames)
        som = self._publica(b, self._renderiza(b, frames))  # arquivo + sons por cima, antes do volume
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
        ab = self._abaixa
        alvo = ab[0] if ab is not None and time.monotonic() < ab[1] else 1.0
        g0, self._abaixa_g = self._abaixa_g, alvo
        if som is not None:
            # o abaixamento so no jogo (o fone segue igual), em rampa no bloco quando muda
            g = alvo if g0 == alvo else np.linspace(g0, alvo, frames, dtype=np.float32)[:, None]
            buf += som * (self.vol * g)
            # o DISCO mostra o disco no mais alto dos volumes que estao soando, o do jogo ou o do
            # fone: com o jogo em zero e o fone em 15% ele parava, com o disco tocando no fone.
            # O JOGO segue sendo so o que o jogo recebe
            self._meter("track", som * max(self.vol * alvo, self.mon_vol if com_fone else 0.0))
        else:
            self.levels["track"] *= DECAY
        fone = None  # o que vai pro fone de quem toca: o som e, se pedido, a propria voz
        if som is not None and com_fone:
            fone = som * self.mon_vol
        if not self._pista_viva:
            self._pista_enche = True
        elif not self._mic:
            self._pista_enche = True
        elif self._pista_enche and len(self._mic) >= PISTA_ENCHE:
            self._pista_enche = False
        if self._mic and not (self._pista_viva and self._pista_enche):
            m = self._mic.popleft()  # o nivel da voz e o do Windows (winvol)
            self._meter("mic", m)
            n = min(len(m), frames)
            # a voz crua vai pelo proprio microfone, e a com o efeito que o filtro roda tambem; so a com o efeito que ele
            # nao roda sai daqui (o filtro poe no lugar da crua)
            if not self.mic_mute and self.voz_pelo_app():
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
        if mv is not None and len(mv):  # a mina: no jogo como a voz, e no fone pra quem toca ouvir o que ela fala
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
        si = self._sinal
        if si is not None and si[1] < len(si[0]):  # o bipe de teste: no jogo, nunca com a voz cortada
            a, p = si[0], si[1]
            k = min(frames, len(a) - p)
            if self.mic_mute or (p == 0 and time.monotonic() > si[2]):
                k = len(a) - p  # a voz cortada, ou a saida parada passou do prazo: o resto dele nao toca mais
            else:
                buf[:k] += a[p:p + k, None]
            si[1] = p + k  # so a posicao: um bipe novo do sinal() troca a lista inteira, e este nao o apaga
        if fone is not None and not self._fone_calado:
            self._mon.append(np.clip(fone, -1, 1))
        np.clip(buf, -1, 1, out=buf)
        self._meter("out", buf)
        return buf

    def _captura(self, frames):
        """O comeco do bloco, num trecho so do _qlock: a virada, se e a hora (o deck preparado e a condicao dela
        conferidos ali mesmo), e o que o bloco toca, do deck e da linha do prato desse instante. O estado da passagem
        (a proxima subindo, o que sai, o eco), o ganho e o limitador vao em copias para o _renderiza."""
        with self._qlock:
            if self._pronto is not None and self.track is not None and not self.paused:
                fim_deste = not self._q and self._eof_gen == self._gen
                if (self._virar_em is not None and self.pos >= self._virar_em) or (fim_deste and self._pronto.q):
                    self._vira()
            d = self._deck
            b = _Bloco(d, d.linha)
            b.track, b.prato, b.auto = self.track, self._prato, self.volume_auto
            if self.track is not None and not self.paused:
                b.item = self._tira(d.q, frames)
                b.fim = not b.item and d.eof_gen == d.gen
                if b.item:
                    t, s = b.item[-1]
                    self._bloco = (d, d.linha, t + len(s) / SR)
                elif b.fim and not self.ended:  # o bloco que publica o fim: a pausa no meio sai substituida por ele
                    self._bloco = (d, d.linha, self.pos)
            b.ganho = (d.ganho, d.ganho_alvo if b.auto else 1.0)
            b.entrando = self._entrando
            if b.entrando is not None:
                b.ent = tuple(b.entrando)
            sai = self._saindo
            if sai is not None and not self.paused:
                b.saindo, b.sai = sai, (sai[1], sai[2], sai[3], sai[4])
                b.sai_blk = self._tira(sai[0].q, frames)
                b.sai_ganho = (sai[0].ganho, sai[0].ganho_alvo if b.auto else 1.0)
            eco = self._eco
            if eco is not None and not self.paused:
                b.eco, b.eco_estado = eco, (eco[0], eco[1], eco[2], eco[2].ganho)
            if self._bloco is None and self.track is not None and not self.paused and (b.sai_blk or b.eco is not None):
                self._bloco = (d, d.linha, self.pos)  # so a passagem soando: a pausa no meio espera este bloco
            # o prato trocou ou pulou: os 2 ms do disco de antes nao saem (o pedido so se consome na publicacao)
            b.zera = self._limitador_zera
            b.lim = sonoridade.Limitador() if b.zera else copy.copy(self._limitador)
        return b

    @staticmethod
    def _rampa_ganho(g0, alvo, n):
        """O ganho automatico nas n amostras de um bloco, de g0 rumo ao alvo: (escalar, ou a rampa n x 1; onde ele
        para, ou None se nao mudou)."""
        if g0 == alvo:
            return g0, None
        k = 10 ** (GANHO_RAMPA_DB_S * n / SR / 20)
        g1 = min(alvo, g0 * k) if alvo > g0 else max(alvo, g0 / k)
        return np.geomspace(g0, g1, n, dtype=np.float32)[:, None], g1

    def _renderiza(self, b, frames):
        """Fora das travas: o som do disco do bloco b (o do prato, o que sai, o eco e o limitador), so sobre o que o
        _captura copiou; o avanco de cada estado fica no b para o _publica. None sem som nenhum."""
        som = None  # o disco, antes do volume
        cru = None  # o disco sem o volume automatico, quando algum ganho dele nao e 1 (o limitador compara)
        if b.item:
            som = np.zeros((frames, 2), np.float32)
            n = 0
            for _, s in b.item:
                som[n:n + len(s)] = s
                n += len(s)
            b.pos = b.item[-1][0] + len(b.item[-1][1]) / SR
            if b.ent is not None:  # a proxima subindo: um quarto de seno (e na passagem de DJ, ate cheia na troca)
                quadros, feitos, nivel, cheia = b.ent
                g = ganho_entra(feitos + np.arange(n), quadros, nivel, cheia)
                som[:n] *= g[:, None]
                b.ent_feitos = feitos + n
            ga, b.g1 = self._rampa_ganho(*b.ganho, n)
            if not np.isscalar(ga) or ga != 1.0:
                cru = som.copy()
                som[:n] *= ga
        if b.saindo is not None:  # o que sai: o fim dele, abaixando em cosseno
            quadros, feitos, gr, segura = b.sai
            if not b.sai_blk or feitos >= quadros:
                b.sai_acabou = True
            else:
                blk = b.sai_blk
                s = blk[0][1] if len(blk) == 1 else np.concatenate([x[1] for x in blk])
                n = len(s)
                u = feitos + np.arange(n)
                g = ganho_sai(u, segura, quadros)
                if gr is not None:  # a troca de grave: o grave dele sai enquanto o da proxima entra
                    agudo, b.sai_zi = signal.sosfilt(_GRAVE_HP, s, axis=0, zi=gr[1])
                    fica = (1 - np.clip((u - gr[2]) / (gr[3] - gr[2]), 0.0, 1.0)).astype(np.float32)
                    s = agudo + fica[:, None] * (s - agudo)
                if som is None:
                    som = np.zeros((frames, 2), np.float32)
                s = s * g[:, None]
                ga, b.sai_g1 = self._rampa_ganho(*b.sai_ganho, n)
                if cru is None and (not np.isscalar(ga) or ga != 1.0):
                    cru = som.copy()
                if cru is not None:
                    cru[:n] += s
                som[:n] += s * ga
                b.sai_feitos = feitos + n
        if b.eco is not None:  # o eco do corte no 1, comecando no golpe
            a, p, dono, gd = b.eco_estado
            # o ganho do disco que saiu, parado onde ele parou (o deste bloco, se ele ainda andou nele)
            if b.saindo is not None and dono is b.saindo[0] and b.sai_g1 is not None:
                gd = b.sai_g1
            elif dono is b.deck and b.g1 is not None:
                gd = b.g1
            i0 = max(0, -p)
            if i0 < frames:
                k = min(frames - i0, len(a) - max(0, p))
                if k > 0:
                    if som is None:
                        som = np.zeros((frames, 2), np.float32)
                    e = a[max(0, p):max(0, p) + k]
                    ga = gd if b.auto else 1.0
                    if cru is None and ga != 1.0:
                        cru = som.copy()
                    if cru is not None:
                        cru[i0:i0 + k] += e
                    som[i0:i0 + k] += e * ga
            b.eco_p = p + frames
        if som is not None or np.any(b.lim.hist):
            # o disco passa sempre pelo limitador (o mesmo atraso com ou sem ganho); ele so age no que o ganho
            # acrescentou acima de 0 dBFS. Parado (pausa, fim do disco), ele solta o que ainda segura
            if som is None:
                som = np.zeros((frames, 2), np.float32)
            som = b.lim(som, cru)
        return som

    def _publica(self, b, som):
        """Sob o _qlock, o fim do bloco: com o deck e a linha do bloco ainda no prato, a posicao, o fim, o primeiro som,
        o avanco da passagem, do ganho e do limitador e a confirmacao da pausa que esperava este bloco. Sem eles (o
        load, o stop, o seek ou o recomeco do fim passaram no meio), nada disso vale e a musica do bloco sai: volta
        None no lugar do som."""
        with self._qlock:
            self._bloco = None  # uma thread so faz blocos: o que estava retirado era este
            if self._deck is not b.deck or b.deck.linha != b.linha:
                return None
            if b.item:
                self.pos = b.pos
                p, tr = b.prato, b.track
                if p is not None and self._prato is p and tr.get("id") == p[0]:
                    self._prato = None
                    self._soou = (tr.get("title"), str(tr.get("path") or "").startswith("http"), p[1], time.time())
            if b.fim and not b.deck.q and b.deck.eof_gen == b.deck.gen:  # o Repetir ligado no meio emenda outra volta
                self.ended = True
                self._solta_pausa()
            ent = b.entrando
            if b.ent_feitos is not None and self._entrando is ent:
                ent[1] = b.ent_feitos
                if ent[1] >= max(ent[0], ent[3]):
                    self._entrando = None
            if b.g1 is not None:
                b.deck.ganho = b.g1
            sai = b.saindo
            if sai is not None and self._saindo is sai:
                if b.sai_acabou:
                    sai[0].gen += 1
                    self._saindo = None
                elif b.sai_feitos is not None:
                    sai[2] = b.sai_feitos
                    if b.sai_zi is not None:
                        sai[3][1] = b.sai_zi
                    if b.sai_g1 is not None:
                        sai[0].ganho = b.sai_g1
            if b.eco is not None and self._eco is b.eco:
                b.eco[1] = b.eco_p
                if b.eco_p >= len(b.eco[0]):
                    self._eco = None
            self._limitador = b.lim
            if b.zera:
                self._limitador_zera = False
            pa = self._pausa
            if pa is not None and not pa.feita.is_set() and pa.deck is b.deck and pa.linha == b.linha:
                self.paused = True
                pa.resolve(self.track, self.pos, ok=True)
        return som

    def _solta_pausa(self):
        """Com _qlock: o pedido de pausa pendente (load, stop, seek, resume, fim, close) sai como substituido, sem
        pausar nada; o ja confirmado deixa de valer para a gravacao da posicao."""
        if self._pausa is not None:
            self._pausa.resolve()
            self._pausa = None

    def pausa_vale(self, p):
        """Com _qlock: a pausa p confirmada ainda e a do prato (a mesma linha, sem retomar nem trocar de disco)."""
        return (self._pausa is p and p.ok and self.paused and not self.ended and self._deck is p.deck
                and p.deck.linha == p.linha)

    def line(self):
        """With _qlock: the platter's line now (a Line), the token that on_line checks later."""
        return Line(self._deck, self._deck.linha)

    def on_line(self, token):
        """With _qlock: the platter is still the deck and the line of token (a Line, a Captura, or anything with deck
        and linha); None never is."""
        return token is not None and self._deck is token.deck and self._deck.linha == token.linha

    @property
    def error(self):
        return self._error if self._error is not None else self._stream_warning

    def set_error(self, message):
        self._error = message

    def on_silent_stream(self, f):
        self._stream_silent = f

    def take_prepare_failure(self):
        with self._qlock:
            tag, self._prepare_failure_tag = self._prepare_failure_tag, None
            return tag

    @contextlib.contextmanager
    def state_section(self):
        with self._qlock:
            yield

    def with_lock(self, outer, f):
        after = []
        try:
            while True:
                with outer:
                    if self._lock.acquire(blocking=False):
                        try:
                            return f(after)
                        finally:
                            self._lock.release()
                with self._lock:
                    pass
        finally:
            for g in after:
                g()

    def take_switch(self, switch):
        """With _qlock: the switch the engine already made on its own (virou, the DJ transition) leaves the engine and
        comes back, only if the pending one is still switch; None otherwise. Whoever takes it reconciles it with the
        queue (comandos.concilia)."""
        if switch is None or self.virou is not switch:
            return None
        self.virou = None
        return switch

    def platter_state(self):
        """The platter's track, position, status() and pending switch, read in one stretch of the _qlock. The caller
        holds no engine lock (the server holds its fila_lock, which comes before)."""
        with self._qlock:
            return self.track, self.pos, self.status(), self.virou

    def captura(self):
        """O que esta no prato agora, sob o _qlock (Captura)."""
        with self._qlock:
            return self._captura_atual()

    def _captura_atual(self):
        """Com _qlock: a Captura de agora. Com o bloco do prato em curso, a fila vazia e so dele: conta como tocando."""
        d, st, bl = self._deck, self.status(), self._bloco
        if st == "buffering" and bl is not None and bl[0] is d and bl[1] == d.linha:
            st = "playing"
        return Captura(self.track, self.pos, st, d, d.linha)

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
        """Argumentos do ffmpeg antes do -i: o stream do YouTube reconecta sozinho (uma vez) se a
        rede piscar ou congelar por STREAM_SEM_DADO_S, e leva os cabecalhos que o yt-dlp mandou;
        arquivo local nao precisa de nada."""
        if not track.get("stream") or not str(track.get("path") or "").startswith("http"):
            return []
        a = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4",
             "-reconnect_max_retries", "1", "-rw_timeout", str(int(STREAM_SEM_DADO_S * 1e6))]
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
        med = sonoridade.Medidor() if stream and not self._lufs(track)[1] else None
        estima = list(STREAM_ESTIMA_S)
        while gen == deck.gen:
            if pre is not None:
                blocos, ff = pre
                pre = None
                print(f"stream: {track.get('title')!r} came in through the ffmpeg opened earlier "
                      f"({sum(map(len, blocos)) / 8 / SR:.2f} s already decoded)", file=sys.stderr, flush=True)
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
                    if len(deck.q) > (max(deck.ahead, STREAM_AHEAD) if stream else deck.ahead):
                        time.sleep(0.01)
                        continue
                    b = blocos.pop(0) if blocos else ff.stdout.read(BLOCK * 8)
                    if not b:
                        ff.wait()
                        break
                    arr = np.frombuffer(b[: len(b) // 8 * 8], np.float32).reshape(-1, 2)
                    rms = float(np.sqrt(np.mean(arr * arr))) if len(arr) else 0.0  # fora do lock do callback
                    if acc is not None:
                        acc.bloco(t + n / SR, arr)
                    if med is not None:
                        med(arr)
                        if estima and med.segundos >= estima[0]:
                            estima.pop(0)
                            self.sonoridade(track, med.lufs(), inteira=False)
                    with self._qlock:
                        if gen != deck.gen:
                            break
                        deck.q.append((t + n / SR, arr))
                        deck.niveis.append((t + n / SR, len(arr), rms))
                    n += len(arr)
            finally:
                mata(ff)
                ff.wait()
                if acc is not None:
                    acc.escreve()
            if gen != deck.gen:
                return
            if med is not None:
                dur = float(track.get("duration") or 0)
                if t == 0 and n and (not dur or t + n / SR >= dur - STREAM_CAIU_S):
                    self.sonoridade(track, med.lufs())
                elif estima and n:  # o disco curto que acabou antes da estimativa
                    self.sonoridade(track, med.lufs(), inteira=False)
                med = None  # a volta do Repetir nao mede de novo
            if n == 0 and stream and track.get("job") and deck is self._deck:
                with self._qlock:
                    waits = deck is self._deck and deck.gen == gen
                    if waits:
                        deck.file_wait = gen
                if waits and self._stream_silent is not None:
                    self._stream_silent(track)
                return
            if n == 0 and deck is not self._deck:  # a proxima que nao decodifica so nao entra
                self._fim_do_leitor(deck, gen)
                return
            fim, dur = t + n / SR, track.get("duration") or 0
            caiu = fim < dur - STREAM_CAIU_S if dur else n == 0
            religar = self.religar_stream
            if stream and caiu and not track.get("job") and deck is self._deck and religar is not None:
                religar(track, fim, lambda: self._stream_desistiu(deck, gen, track, fim))
                return
            if n == 0 and (stream or not t or not dur or t < dur - FILE_TAIL_S or ff.returncode):
                self._fim_do_leitor(deck, gen, erro=(track, t))
                return
            if not self._repete(deck, gen):
                return
            t = 0.0
        if pre is not None:  # o disco trocou entre pegar o aberto antes e comecar a ler: ninguem le esse ffmpeg
            mata(pre[1])
            pre[1].wait()

    def _fim_do_leitor(self, deck, gen, erro=None):
        """O leitor do gen acabou (no fim do disco, ou, com erro=(disco, t), sem ler nada): sob o _qlock, e so se ele
        ainda e o leitor do deck. O de uma linha que ja acabou nao marca o fim nem o erro da linha nova."""
        with self._qlock:
            if deck.gen != gen:
                return
            if erro is not None and deck is self._deck:  # o que ja saiu do prato nao poe erro na faixa nova
                self._erro_de_leitura(*erro)
            deck.eof_gen = gen

    def _repete(self, deck, gen):
        """O leitor do gen chegou ao fim do disco: sob o _qlock, ou a volta seguinte (o Repetir ligado no prato), ou o
        fim. O set_loop liga o Repetir no mesmo trecho em que confere o fim: um dos dois emenda."""
        with self._qlock:
            if deck.gen != gen:
                return False
            if self.loop and deck is self._deck:
                return True
            deck.eof_gen = gen
            return False

    def _erro_de_leitura(self, track, t):
        nome = track.get("title") or "?"
        quando = f"{int(t // 60)}:{int(t % 60):02d}"
        if track.get("stream"):
            self._error = i18n.msg("server.player.streamStopped", "YouTube stopped sending the audio of \"{title}\" "
                                                                 "at {time}. Play it again, or wait for the download "
                                                                 "to the shelf to finish.", title=nome, time=quando)
        else:
            self._error = i18n.msg("server.player.readFailedAt", "Couldn't read the audio of \"{title}\" from {time} "
                                                                "on. The file may be corrupted. Delete the record "
                                                                "and download it again.", title=nome,
                                  time=quando)

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
                    raise ValueError("empty")
                self._sobre_cache[chave] = a
                while len(self._sobre_cache) > 1 and (
                        len(self._sobre_cache) > SOBRE_CACHE
                        or sum(x.nbytes for x in self._sobre_cache.values()) > SOBRE_CACHE_MB * 2 ** 20):
                    self._sobre_cache.popitem(last=False)
            else:
                self._sobre_cache.move_to_end(chave)
        except Exception:  # som por cima quebrado nao derruba o resto
            self._error = i18n.msg("server.player.readFailed", "Couldn't read the audio of \"{title}\". The file may "
                                                              "be corrupted. Delete the record and download it "
                                                              "again.", title=track.get("title") or "?")
            return
        with self._slock:
            self._sobre.append([{"id": track["id"], "title": track.get("title")}, a, 0])
            del self._sobre[:-SOBRE_MAX]

    def _restart(self, start, track=None, alvo=None, paused=None, nova_linha=True, prato=False, pode=None,
                 loop=None):
        """O disco do prato recomeca em start, publicado sob o _qlock como uma mudanca so: a faixa (track, quando troca;
        prato: e um disco entrando, e o primeiro som dele vai para o log), a linha nova (nova_linha; a troca da espera
        para o stream, sem audio ainda, fica na mesma), a posicao, o fim, o ganho do disco que entra sem rampa (alvo), a
        pausa (paused), o Repetir (loop; sem ele, um disco entrando no lugar de outro o desliga) e a passagem desfeita,
        com o pedido de pausa da linha que acabou substituido. O leitor recebe a faixa, o deck e o gen dessa mudanca e
        comeca fora das travas. Volta (a Captura do que estava no prato logo antes, a posicao que o servidor grava, ou
        None; e quem comeca o leitor, ou None): quem chama o comeca depois de soltar o _lock."""
        with self._qlock:
            if pode is not None and not pode():
                return None, None
            if callable(start):
                start = start()
            antes = self._captura_atual()
            self._cancela_passagem(tudo=True)
            d = self._deck
            if loop is None and prato and self.track is not None and self.track.get("id") != track.get("id"):
                loop = False  # o Repetir vale para o disco do prato: outro disco entrando desliga
            if track is not None:
                self.track = d.track = track
            if prato:  # o disco que entra no prato agora: o primeiro som dele vai para o log
                self._prato = (track.get("id"), time.time())
            if alvo is not None:
                d.ganho_alvo = d.ganho = alvo
            if paused is not None:
                self.paused = paused
            if loop is not None:  # o leitor da faixa nova ja decide o fim com ele (_repete)
                self.loop = bool(loop)
            if nova_linha:
                d.linha += 1
            d.gen += 1
            d.q.clear()
            d.niveis.clear()  # a posicao pulou: o nivel de antes nao e mais o caminho ate o fim
            d.eof_gen = -1
            gen, tr = d.gen, self.track
            self._limitador_zera = True
            self.pos = start
            self.ended = False
            self._stream_warning = None
            if nova_linha:
                self._error = None
                self._solta_pausa()
        if not tr.get("path"):  # sem caminho, o disco ainda espera o stream abrir: sem leitor
            return antes, None

        def comeca():
            self._onda_pede(tr)
            threading.Thread(target=self._reader, args=(gen, tr, start, d), daemon=True).start()
        return antes, comeca

    @staticmethod
    def _comeca(leitor):
        if leitor is not None:
            leitor()

    # passagem para a proxima ------------------------------------------------
    @staticmethod
    def _segue(depois, f):
        """O resto de um comando, que roda fora das travas: agora, ou, com a lista depois de quem chama com travas na
        mao (o servidor, App.with_engine), quando ele as soltar."""
        if depois is None:
            f()
        else:
            depois.append(f)

    def preparar(self, track, tag, pode=None, ganho=None, depois=None):
        """A proxima da fila no segundo deck (o servidor chama a TRANS_PREP_S do fim): o leitor dela
        decodifica o comeco, o deste vai ate o fim, e o _mede marca onde virar. O deck novo so aparece para o _mixa
        sob o _qlock, ja com o ganho dele. pode(): conferido sob o _qlock antes de publicar (o servidor confere ali a
        reserva de avanco, a primeira da fila, o deck e a linha que viu); falso, nada e publicado e volta False.
        ganho: o (alvo, mede) do _ganho_de, ja medido por quem chama (o servidor mede antes de pegar as travas).
        depois: o leitor dela e a medida comecam quando quem chama soltar as travas dele (_segue)."""
        if not track.get("path"):
            return False
        alvo, mede = self._ganho_de(track) if ganho is None else ganho  # fora das travas: pergunta ao servidor
        d = Deck(track)
        d.gen, d.ahead = 1, PRONTO_AHEAD
        d.ganho = d.ganho_alvo = alvo  # o deck ainda e so daqui
        with self._lock:
            with self._qlock:
                if self.track is None or (pode is not None and not pode()):
                    return False
                self._cancela_passagem()
                self._pronto, self.pronto_tag = d, tag
                self._deck.ahead = 10 ** 9  # o fim deste inteiro na memoria para medir (45 s sao ~17 MB)
                atual, tr_atual = self._deck, self.track
                self.preparos += 1

        def segue():
            self._onda_pede(track)
            self._mede_se(track, mede)
            threading.Thread(target=self._reader, args=(1, track, 0.0, d), daemon=True).start()
            threading.Thread(target=self._mede, args=(atual, d, tr_atual), daemon=True).start()
        self._segue(depois, segue)
        return True

    def em_passagem(self):
        """Do comeco do preparo da proxima ate PASSAGEM_DEPOIS_S depois da virada."""
        return self._pronto is not None or time.monotonic() - self._virou_em < PASSAGEM_DEPOIS_S

    def totais_saude(self):
        """O que o Injetor passa a janela do evento "audio" a cada volta, desde que o motor abriu: (as passagens
        preparadas, os segundos de voz pelo microfone de reserva)."""
        return self.preparos, self.reserva_quadros / SR

    def saude_audio(self, aberto=True):
        """A janela do evento "audio" do Injetor de agora (metricas.SaudeAudio), ou None sem audio aberto (o Injetor
        de uma reabertura que falhou fica parado: nao conta). aberto=False devolve tambem a do Injetor parado, que a
        reabertura do leitor perdido ainda continua: o descarte da janela a alcanca."""
        inj = self._injetor if self._stack is not None or not aberto else None
        return inj.saude if inj is not None else None

    def cancelar_pronto(self):
        """drop_prepared, taking the _qlock itself."""
        with self._qlock:
            self.drop_prepared()

    def drop_prepared(self):
        """With _qlock: the prepared next record leaves (its reader stops), and the engine does not switch to it. The
        passage already sounding stays (stop, seek and load cut that one)."""
        self._cancela_passagem()

    def tracks_in_use(self):
        """The tracks the engine reads from now: the platter's, the prepared next one's and the one still leaving in a
        transition. No lock: the mixer thread swaps the prepared and the leaving deck, so each is read once."""
        pronto, saindo = self._pronto, self._saindo
        decks = (pronto, saindo[0] if saindo else None)
        return [t for t in (self.track, *(d.track for d in decks if d)) if t is not None]

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
                    self._prepare_failure_tag = self.pronto_tag
                    self._cancela_passagem()
            return
        fim, queda, baixo = medir_fim(cauda)
        ini = medir_inicio(cabeca)
        fim, caindo, fade, virar, sobrepor = transicao.escolha(fim, queda, baixo, self.pos)
        try:
            plano, motivo = (self._plano_batida(atual, prox, fade, fim, queda, baixo, ini, virar, sobrepor)
                             if queda is not None else (None, "no drop at the end"))
        except Exception as ex:  # a passagem no tempo e um extra: sem ela, a de volume
            plano, motivo = None, f"error: {ex!r}"
        with self._qlock:
            if self._pronto is not prox or self._deck is not atual:
                return
            if plano is not None and plano["virar"] - self.pos < FOLGA_S:
                plano, motivo = None, "the plan was ready too late"
            if plano is not None and plano.get("sai_q") and (not atual.q or atual.q[0][0] > plano["sai_q"][0] + 1e-7):
                plano, motivo = None, "the plan was ready after the outgoing one's ramp started"
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
        jeito = f"{caindo:.1f} s fade-out" if fade else "hard ending"
        print(f"transition: {tr_atual.get('title')!r} -> {prox.track.get('title')!r}: sound until "
              f"{fim:.2f} s, {jeito}, switches at {virar:.2f} s overlapping {sobrepor:.2f} s, the next one starts at {ini:.2f} s",
              file=sys.stderr, flush=True)
        print(f"transition: on beat: {plano['log']}" if plano is not None else f"transition: beats not aligned: {motivo}",
              file=sys.stderr, flush=True)
        # quanto a preparacao esperou (os dois decodificados) e quanto o plano levou, e a folga que sobrou ate a virada
        print(f"transition: prepared {fim - pos_plano + (t_plano - t_prep):.0f} s before the end; waited "
              f"{t_plano - t_prep:.1f} s for the audio, planned in {time.perf_counter() - t_plano:.1f} s; the switch was "
              f"{virar - self.pos:.1f} s ahead", file=sys.stderr, flush=True)
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
            print(f"transition: end of {tr_atual.get('title')!r}: normal {normal:.1f} dBFS; every 5 s in the last "
                  f"{FIM_RETRATO_S:.0f} s: {' '.join('-' if j is None else f'{j:+.0f}' for j in janelas)} dB; "
                  f"drop at {queda if queda is None else round(queda, 2)} s, low at "
                  f"{baixo if baixo is None else round(baixo, 2)} s, switches at {virou:.2f} s ({fim - virou:.1f} s before "
                  f"the end of the sound)", file=sys.stderr, flush=True)
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
            hoje = time.strftime("%Y-%m-%d")
            if self._passagens_dia != hoje:  # a primeira passagem do dia nesta sessao: os de mais de uma semana saem
                self._passagens_dia = hoje
                podados = poda_passagens(pasta, datetime.date.fromisoformat(hoje))
                if podados:
                    print(f"transition: removed {len(podados)} end records older than {PASSAGENS_DIAS} days",
                          file=sys.stderr, flush=True)
            with open(pasta / (hoje + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        except Exception as ex:  # o registro e so estudo: falhando, a passagem segue igual
            print(f"transition: the end record failed: {ex!r}", file=sys.stderr, flush=True)

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
            return None, "no audio in the queue"
        fim_a = baixo if fade else fim
        t_a, xa = _junta(blocos_a, fim_a - BATIDA_S, fim_a)
        t_b, xb = _junta(blocos_b, ini, ini + BATIDA_S)
        if xa is None or len(xa) < BATIDA_MIN_S * SR:
            return None, "too little of the end of this one in the queue to measure"
        if xb is None or len(xb) < BATIDA_MIN_S * SR:
            return None, "too little of the start of the next one to measure"
        ga, gb = batida.medir(xa, SR), batida.medir(xb, SR)
        if not ga.firme:
            # a rede, so antes do fade: com ele junto as batidas que vao sumindo puxam o andamento (o fim do
            # Despacito media 90,0 em vez de 89,0, e 1% em 14 s de sobreposicao e mais de 100 ms)
            antes = queda if fade else fim
            t_r, xr = _junta(blocos_a, antes - BATIDA_S, antes)
            g = batida.network_beat_grid(xr, SR) if xr is not None and len(xr) >= BATIDA_MIN_S * SR else None
            if g is not None:
                ga, t_a = g, t_r
        if not gb.firme:
            g = batida.network_beat_grid(xb, SR)
            if g is not None:
                gb = g
        if not ga.firme:
            return None, f"the end of this one has no steady beat, {ga.motivo}"
        # a grade da proxima e a do comeco dela, que e o que toca junto: a musica pode mudar de andamento depois
        # (o Lose Yourself vai de 65 BPM no piano a 86 quando entra a guitarra, aos 31 s)
        if not gb.firme and fade:
            return None, f"the start of the next one has no steady beat, {gb.motivo}"
        pa, pb = ga.periodo, gb.periodo
        a_longa, b_longa = t_a + ga.fase, t_b + gb.fase  # uma batida de cada grade dos 20 s (o bumbo escolheu o lado)
        intro = False
        if not fade and gb.firme:  # final seco com a introducao baixa da proxima: ela entra por baixo antes
            with self._qlock:
                niv_b = list(prox.niveis)
            intro = transicao.intro_baixa(niv_b, ini, pa)

        def fase_em(blocos, t1, t2, periodo, quem, longa, x=None):
            """Uma batida (em s do disco) da grade de periodo dado, afinada em t1-t2 (ou no audio x, que comeca
            em t1), onde as duas soam juntas, perto da batida da grade longa: o pequeno erro do andamento soma
            ao estender a grade, e o esticamento desvia uns ms. O lado (batida ou contratempo) e o da grade
            longa, que o bumbo decidiu: o trecho curto sozinho caiu no contratempo do Overdose (21/10)."""
            t = t1
            if x is None:
                t, x = _junta(blocos, t1, t2)
            if x is None or len(x) < FASE_MIN_S * SR:
                return None, f"too little of {quem} for the phase"
            f, nota = batida.fase(x, SR, periodo, (longa - t) % periodo)
            if nota < NOTA_MIN:  # sem ataque claro para o pente (violao, piano, fala): as batidas da rede
                f = batida.network_phase(x, SR, periodo, (longa - t) % periodo)
                if f is None:
                    return None, f"{quem} has no clear beat where both play together (comb {nota:.1f}, nor by the network)"
            return t + f, None

        inicios = np.array([t for t, _ in blocos_a])
        fim_arq = blocos_a[-1][0] + len(blocos_a[-1][1]) / SR

        def virada(t0):
            """O comeco do bloco deste em que t0 cai, os blocos de silencio depois do arquivo e o silencio na frente
            da proxima (o transicao.virada)."""
            return transicao.virada(inicios, fim_arq, t0)

        if not fade and not intro:
            a0, motivo = fase_em(blocos_a, fim - 8.0, fim, pa, "the end of this one", a_longa)
            if a0 is None:
                return None, motivo
            # a proxima no andamento deste, esticada como no fade: SEGURA_BATIDAS dele depois da primeira dela, e de
            # volta devagar ao dela. Sem batida firme no comeco dela, com os andamentos longe ou sem o comeco dela
            # decodificado para a volta, ela entra no andamento dela
            s = transicao.razao(pa, pb)
            esticada, sem = None, f"tempos far apart, {(s - 1) * 100:+.1f}%"
            if gb.firme and abs(s - 1) <= TEMPO_MAX:
                esticada, sem = _esticar_comeco(blocos_b, ini, s, int((pb / s + SEGURA_BATIDAS * pa) * SR))
            if esticada is not None:
                z, phi, ate, n_rampa = esticada
                # a primeira batida dela no que vai tocar, ja esticado: o desvio da Rubber Band fica de fora da conta
                tau, sem = fase_em(None, 0.0, None, pb / s, "the start of the next one", (b_longa - ini) / s,
                                   x=z[:int(6.0 * SR)])
                if tau is None:
                    esticada = None
                else:
                    if tau - pb / s >= -0.06:  # a primeira batida e o proprio comeco do som (ver o b1 abaixo)
                        tau -= pb / s
                    quem = (f"the first beat of the next one ({gb.bpm:.1f} BPM, at {(s - 1) * 100:+.2f}% for "
                            f"{SEGURA_BATIDAS} beats of this one and back in {n_rampa / SR:.1f} s)")
            if esticada is None:
                b1, motivo2 = (fase_em(blocos_b, ini, ini + 6.0, pb, "the start of the next one", b_longa)
                               if gb.firme else (None, gb.motivo))
                if b1 is None:  # comeco sem batida firme (intro sem bateria): a primeira nota dela cai na batida dele
                    b1, quem = ini, f"the first note of the next one (its start has no steady beat: {motivo2})"
                else:
                    if b1 - pb >= ini - 0.06:
                        # a primeira batida e o proprio comeco do som: a grade da rede vem REDE_ATRASO antes dele, fora
                        # do trecho, e a fase caia uma batida adiante (o Mirage entrava meia batida fora do DATEN, 21/10)
                        b1 -= pb
                    quem = f"the first beat of the next one ({gb.bpm:.1f} BPM, at its own tempo: {sem})"
                tau = b1 - ini
            # a batida dele logo depois do fim do som (onde a passagem de volume viraria), e a proxima nunca
            # entra mais de FIM_CORTE_S antes desse fim
            k = transicao.batida_do_fim(a0, pa, tau, fim, baixo)
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
                return None, "the beat of the switch already passed"
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
                corte = (f"; cut on the 1 of the final hit ({fim - golpe:.2f} s before the end of the sound)"
                         + (f", {d:.3f} s echo" if e is not None else ", no echo"))
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
                    "eco": eco, "log": (f"hard ending, {quem} at {b1:.2f} s, on this one's grid ({ga.bpm:.1f} BPM), "
                                        f"it starts at {t0:.3f} s{corte}")}, None
        s = transicao.razao(pa, pb)
        if abs(s - 1) > TEMPO_MAX:
            # a proxima fica em TEMPO_MAX e a que sai anda o resto, se couber em SAI_MAX
            sa = transicao.velocidade_saida(s)
            if sa is None:
                return None, f"tempos far apart, {ga.bpm:.1f} and {gb.bpm:.1f} BPM ({(s - 1) * 100:+.1f}%)"
            nb, ini = self._entrada_dj(prox, ini, pa, pb, s * sa, b_longa)
            return self._plano_dois(blocos_a, blocos_b, ga, gb, s, sa, a_longa, b_longa, queda - nb * pa,
                                    (nb + DJ_SAI_BATIDAS) * pa, queda, ini, fase_em)
        troca_t = queda
        nb, ini = self._entrada_dj(prox, ini, pa, pb, s, b_longa)
        virar = troca_t - nb * pa
        a0, motivo = fase_em(blocos_a, virar - FASE_ANTES_S, troca_t, pa, "the end of this one", a_longa)
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
        tau, motivo = fase_em(None, 0.0, None, pb / s, "the start of the next one", (b_longa - ini) / s,
                              x=z[:int(max(FASE_MIN_S, sobrepor + 1.0) * SR)])
        if tau is None:
            return None, motivo
        t0 = transicao.na_grade(a0, pa, virar, tau)  # a primeira batida dela cai numa dele
        v, silencio, pad = virada(t0)
        if v is None:
            return None, "the beat of the switch already passed"
        if silencio:
            return None, "the on-beat switch fell after the end of the file"
        # os graves trocam na batida dele mais perto da troca (o fim do corpo), em meia batida: ate la a proxima vem
        # sem grave, dali em diante e o que sai que fica sem (no callback); a que sai segue cheia ate ali e some em
        # DJ_SAI_BATIDAS; a proxima chega cheia no meio da troca
        tm, w0, w1 = transicao.troca_grave(a0, pa, troca_t, t0, pad)
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
                "log": (f"{ga.bpm:.1f} BPM going out, {gb.bpm:.1f} BPM coming in, the next one at {s * 100 - 100:+.2f}% "
                        f"for {nb} beats before the swap and {DJ_SAI_BATIDAS} after, and back in {n_rampa / SR:.1f} s; "
                        f"its first beat at {t0 + tau:.3f} s, on this one's grid; the bass swaps at {tm:.2f} s "
                        f"(the body of this one ends at {troca_t:.2f} s)")}, None

    def _entrada_dj(self, prox, ini, pa, pb, s, b_longa):
        """Quantas batidas deste (nb) a proxima entra antes da troca, e de onde dela (ini): o transicao.entrada_dj no
        nivel da proxima ja decodificado."""
        with self._qlock:
            niv = list(prox.niveis)
        nb, comeco, corpo = transicao.entrada_dj(niv, ini, pa, pb, s, b_longa)
        if corpo is not None:
            print(f"transition: the intro of the next one lasts until {corpo:.2f} s; it comes in from {comeco:.2f} s, {nb} beats "
                  f"before the swap", file=sys.stderr, flush=True)
        return nb, comeco

    def _plano_dois(self, blocos_a, blocos_b, ga, gb, s, sa, a_longa, b_longa, virar, sobrepor, swap, ini, fase_em):
        """O fade-out no tempo com os andamentos a mais de TEMPO_MAX: a que sai vai devagar (RAMPA_TAXA) para a
        velocidade sa antes da sobreposicao, e a proxima entra esticada em TEMPO_MAX no andamento a que ela
        chegou. Os blocos deste a partir da rampa sao trocados pelos reamostrados, com a posicao do disco no
        rotulo (a tela e a virada leem a posicao). The outgoing beat during the overlap is measured on the stretched
        audio, which captures the Rubber Band drift over the ramp. The switch and the bass swap use sample positions
        in that output."""
        pa, pb = ga.periodo, gb.periodo
        sb = s * sa  # a velocidade da proxima: a grade dela cai na deste ja mudada
        # a rampa acaba antes do trecho onde a fase deste e medida: ali a velocidade ja e constante
        n_ra, t_r = transicao.rampa_saida(sa, virar)
        if t_r < self.pos + SAI_FOLGA_S:
            return None, f"no time for the outgoing one to change {(sa - 1) * 100:+.1f}% before the switch"
        t_r = next((t for t, _ in blocos_a if t >= t_r), None)
        if t_r is None:
            return None, "the outgoing one's ramp fell after the end of the file"
        fim_arq = blocos_a[-1][0] + len(blocos_a[-1][1]) / SR
        _, xs_a = _junta(blocos_a, t_r, fim_arq)
        z_a, phi_a = esticar_saida(xs_a, sa, n_ra)

        def saida_a(t):
            """A amostra da saida deste (desde t_r) em que o disco passa em t."""
            return int(np.searchsorted(phi_a, (t - t_r) * SR))

        P = pa / sa * SR  # o periodo deste na saida, em amostras
        i2 = saida_a(swap)
        i1 = transicao.phase_excerpt_start(saida_a(virar - FASE_ANTES_S), i2)
        perto = (saida_a(a_longa + round((virar - a_longa) / pa) * pa) - i1) / SR
        f, motivo = fase_em(None, 0.0, None, P / SR, "the end of this one (already changed)", perto, x=z_a[i1:i2])
        if f is None:
            return None, motivo
        a0 = i1 + f * SR  # uma batida deste, em amostras da saida dele
        n_sob = int(sobrepor * SR / sa)  # a sobreposicao, em amostras da saida
        # a proxima: como no caminho de um lado so, com a velocidade sb e a sobreposicao na saida
        esticada, motivo = _esticar_comeco(blocos_b, ini, sb, n_sob)
        if esticada is None:
            return None, motivo
        z, phi, ate, n_rampa = esticada
        tau, motivo = fase_em(None, 0.0, None, pb / sb, "the start of the next one", (b_longa - ini) / sb,
                              x=z[:int(max(FASE_MIN_S, n_sob / SR + 1.0) * SR)])
        if tau is None:
            return None, motivo
        # a primeira batida dela numa deste, a partir da virada; a proxima comeca na amostra t0 da saida deste
        i_v = saida_a(virar)
        t0 = int(round(transicao.na_grade(a0, P, i_v, tau * SR)))
        j, pad = divmod(t0, BLOCK)
        if j * BLOCK >= len(z_a):
            return None, "the on-beat switch fell after the end of the file"
        v = t_r + phi_a[j * BLOCK] / SR
        # a troca de grave na batida deste mais perto da troca, em amostras da saida dele
        tm, w0, w1 = transicao.troca_grave(a0, P, saida_a(swap), t0, pad, sr=1)
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
                 "nivel": DJ_NIVEL_ANTES, "cheia": w1 / SR, "grave": [w0 / SR, w1 / SR], "grade_de": _visor_grade(ga, disco_a(a0), a_longa - ga.fase, swap),
                 "grade_para": _visor_grade(gb, ini + sb * tau, ini, ini + BATIDA_S)}
        return {"cabeca": cabeca, "ate": ate, "virar": v, "silencio": 0, "sai": sai, "entra": entra, "segura": segura,
                "nivel": DJ_NIVEL_ANTES, "cheia": w1, "grave": (w0, w1), "sai_q": (t_r, novos), "periodo_saida": P / SR,
                "visor": visor,
                "log": (f"{ga.bpm:.1f} BPM going out, {gb.bpm:.1f} BPM coming in, {(s - 1) * 100:+.1f}% apart: the outgoing one at "
                        f"{(sa - 1) * 100:+.2f}% in {n_ra / SR:.0f} s from {t_r:.2f} s, the next one at "
                        f"{(sb - 1) * 100:+.2f}% until the end of the overlap and back in {n_rampa / SR:.1f} s, "
                        f"its first beat on this one's beat at {t_r + phi_a[min(len(phi_a) - 1, int(t0 + tau * SR))] / SR:.3f} s; "
                        f"the bass swaps "
                        f"{(tm - t0) / SR:.2f} s after it comes in")}, None

    def _vira(self):
        """Com _qlock, no _captura, no mesmo trecho da trava em que ele conferiu a proxima preparada e a condicao
        da virada: a proxima vai para o prato; o que sai segue por baixo o tempo da sobreposicao, abaixando (sem
        sobreposicao, o resto dele, silencio, fica para tras)."""
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
        # o eco e do disco que sai: leva o ganho automatico dele
        self._eco = ([self._eco_plano[0], -self._eco_plano[1], velho]
                     if medida and self._eco_plano is not None else None)
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
        self._virou_em = time.monotonic()

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
            except Exception as ex:  # sem a onda, o visor fica so com a linha do meio
                print(f"waveform: couldn't read the waveform of {iid}: {ex!r}", file=sys.stderr, flush=True)
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
            mata(ff)
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

    # o volume automatico ------------------------------------------------------
    @staticmethod
    def _chave(track):
        """O mesmo disco no stream e no arquivo baixado: o id do YouTube, ou o id, ou o caminho."""
        return track.get("youtube_id") or track.get("id") or track.get("path")

    def _lufs(self, track):
        """(LUFS, inteira?) do disco: o que ele traz, o que o servidor guardou, o que se mediu nesta sessao; ou
        (None, False)."""
        if track.get("lufs") is not None:
            return float(track["lufs"]), True
        if self.sonoridade_de is not None:
            try:
                v = self.sonoridade_de(track)
            except Exception:  # sem a medida guardada, mede de novo
                v = None
            if v is not None:
                return float(v), True
        return self._medidas.get(self._chave(track), (None, False))

    def gain_for(self, track):
        """Outside every lock (it asks the server): what load, espera and preparar take as ganho, measured ahead by
        whoever calls them (_ganho_de)."""
        return self._ganho_de(track)

    def update_track(self, iid, **fields):
        """The platter's record iid gets fields (the shelf renamed it): the state shows them right away, and the
        platter's track is swapped under the _qlock, never outside it. Returns whether the platter held it."""
        with self._qlock:
            tr = self.track
            if tr is None or tr["id"] != iid:
                return False
            self.track = dict(tr, **fields)
            if self._deck.track is tr:
                self._deck.track = self.track
            return True

    def _ganho_de(self, track):
        """Fora das travas (pergunta ao servidor): o ganho do disco pela medida que ja se tem, e se o arquivo local
        ainda precisa ser medido (sem a medida inteira; o stream o leitor mede)."""
        lufs, inteira = self._lufs(track)
        path = str(track.get("path") or "")
        return 10 ** (sonoridade.ganho_db(lufs) / 20), not inteira and bool(path) and not path.startswith("http")

    def _mede_se(self, track, mede):
        """A medida do arquivo, fora daqui e das travas, quando o _ganho_de pediu."""
        if mede:
            threading.Thread(target=self._mede_arquivo, args=(track,), daemon=True).start()

    def _mede_arquivo(self, track):
        k = self._chave(track)
        with self._med_lock:
            if k in self._medindo:
                return
            self._medindo.add(k)
        try:
            lufs = sonoridade.mede_arquivo(track["path"], FFMPEG, NO_WINDOW | ABAIXO_DO_NORMAL, sem_cursor())
        finally:
            with self._med_lock:
                self._medindo.discard(k)
        if lufs is not None:
            self.sonoridade(track, lufs)

    def sonoridade(self, track, lufs, inteira=True):
        """A medida do disco chegou (o arquivo inteiro, o stream inteiro, ou a estimativa do comeco dele): o ganho do
        deck que toca ou vai tocar esse disco anda ate o novo, e a medida inteira vai pro servidor guardar."""
        if lufs is None:
            return
        k = self._chave(track)
        if not inteira and self._medidas.get(k, (None, False))[1]:
            return  # a do disco inteiro vale mais que a do comeco
        self._medidas[k] = (float(lufs), inteira)
        alvo = 10 ** (sonoridade.ganho_db(lufs) / 20)
        with self._qlock:
            sai = self._saindo[0] if self._saindo is not None else None
            for d in (self._deck, self._pronto, sai):
                if d is not None and d.track is not None and self._chave(d.track) == k:
                    d.ganho_alvo = alvo
        if inteira and self.mediu is not None:
            try:
                self.mediu(track, float(lufs))
            except Exception as ex:  # sem guardar, mede de novo na proxima vez
                print(f"volume: nao guardei a medida de {track.get('title')!r}: {ex}", file=sys.stderr, flush=True)

    # comandos -------------------------------------------------------------
    def espera(self, track, pode=None, ganho=None, depois=None):
        """Poe o disco no prato carregando, ainda sem audio: o endereco do stream do YouTube
        leva 1 a 3 s para sair, e a tela ja mostra o que vai tocar. Outro disco entrando desliga o Repetir. Volta a
        Captura do que estava no prato antes, ou None se o pode() (conferido sob o _qlock) recusou. ganho: o do
        _ganho_de, ja medido por quem chama; depois: o leitor comeca quando quem chama soltar as travas (_segue)."""
        alvo, mede = self._ganho_de(track) if ganho is None else ganho
        with self._lock:
            antes, leitor = self._restart(0.0, track=track, alvo=alvo, paused=False, prato=True, pode=pode)
        if antes is not None:
            self._segue(depois, lambda: (self._comeca(leitor), self._mede_se(track, mede)))
        return antes

    def tira_soou(self):
        """O primeiro som do ultimo disco que entrou no prato, uma vez: (titulo, stream?, entrou, soou) ou None."""
        s, self._soou = self._soou, None
        return s

    def trocar_fonte(self, atual, novo):
        alvo, mede = self._ganho_de(novo)
        if not atual.get("path"):  # da espera para o stream: ainda sem audio, nem leitor
            with self._lock:
                antes, leitor = self._restart(lambda: self._clamp(self.pos, novo), track=novo, alvo=alvo,
                                              nova_linha=False, pode=lambda: self.track is atual)
            if antes is None:
                return False
            self._comeca(leitor)
            self._mede_se(novo, mede)
            return True
        with self._lock:
            with self._qlock:
                if self.track is not atual:
                    return False
                d, bl = self._deck, self._bloco
                if d.q:
                    t = d.q[-1][0] + len(d.q[-1][1]) / SR
                elif bl is not None and bl[0] is d and bl[1] == d.linha:
                    t = bl[2]  # o bloco em curso ja saiu da fila: o leitor novo comeca depois dele
                else:
                    t = self.pos
                dur = novo.get("duration") or 0
                self.track = d.track = novo
                d.ganho_alvo = alvo
                self._stream_warning = None
                to_file = str(atual.get("path")).startswith("http") and not str(novo.get("path") or "").startswith("http")
                if self.ended or d.eof_gen == d.gen or (not to_file and dur and t >= dur - FILE_TAIL_S):
                    gen = None  # no fim (ou quase): o leitor de agora termina o disco
                else:
                    d.gen += 1
                    gen = d.gen
                    d.eof_gen = -1
                    if not str(novo.get("path") or "").startswith("http"):
                        self._cancela_passagem()  # o arquivo substitui o stream em que a preparada foi medida
        self._onda_pede(novo)
        self._mede_se(novo, mede)
        if gen is not None:
            threading.Thread(target=self._reader, args=(gen, novo, t, d), daemon=True).start()
        return True

    def warn_on(self, track, message, waiting=False):
        with self._qlock:
            if self.track is not track or (waiting and not self.esperando_arquivo()):
                return False
            self._stream_warning = message
            return True

    def esperando_arquivo(self):
        return self._deck.file_wait == self._deck.gen

    def abaixa(self, db, ms):
        """Abaixa a musica no jogo db decibeis por ms milissegundos, sem gravar nada: no prazo, ela volta sozinha. Um
        novo pedido troca o de antes; db ou ms em zero tira o abaixamento."""
        db = max(0.0, min(ABAIXA_MAX_DB, float(db)))
        ms = max(0, min(ABAIXA_MAX_MS, int(ms)))
        self._abaixa = (10 ** (-db / 20), time.monotonic() + ms / 1000, db, ms) if db > 0 and ms > 0 else None

    def abaixamento(self):
        """O abaixamento valendo agora, {"db", "ms"} (o pedido), ou None."""
        ab = self._abaixa
        return {"db": ab[2], "ms": ab[3]} if ab is not None and time.monotonic() < ab[1] else None

    def sinal(self):
        """O bipe curto de teste no microfone (o que o jogo ouve), com as pontas suaves. Com a voz cortada, nada."""
        if self.mic_mute:
            self._sinal = None  # o de antes tambem nao toca quando a voz voltar
            return False
        n = int(SINAL_S * SR)
        t = np.arange(n, dtype=np.float32) / SR
        borda = np.minimum(1.0, np.minimum(t, SINAL_S - t) / 0.02).astype(np.float32)  # 20 ms de rampa em cada ponta
        self._sinal = [(10 ** (SINAL_DB / 20) * np.sin(2 * np.pi * SINAL_HZ * t) * borda).astype(np.float32), 0,
                       time.monotonic() + SINAL_S]
        return True

    def por_cima(self, track):
        """Toca o item junto do que estiver tocando, sem trocar a musica nem mexer na barra
        (decodifica inteiro, ate CURTO_MAX_S, ou RAPIDO_MAX_S no posto pela mao, numa thread;
        repetido sai do cache)."""
        threading.Thread(target=self._toca_sobre, args=(track,), daemon=True).start()

    def load(self, track, start=0.0, paused=False, loop=None, pode=None, ganho=None, depois=None):
        """O disco no prato a partir de start, numa linha nova; loop: o Repetir, na mesma publicacao (None: fica como
        esta no mesmo disco, e outro disco entrando o desliga). Volta a Captura do que estava no prato antes, ou None se
        o pode() (conferido sob o _qlock: o servidor confere ali a reserva de avanco) recusou. ganho: o do _ganho_de,
        ja medido por quem chama; depois: o leitor comeca quando quem chama soltar as travas (_segue)."""
        alvo, mede = self._ganho_de(track) if ganho is None else ganho
        with self._lock:
            antes, leitor = self._restart(self._clamp(start, track), track=track, alvo=alvo, paused=paused,
                                          prato=True, loop=loop, pode=pode)
        if antes is not None:
            self._segue(depois, lambda: (self._comeca(leitor), self._mede_se(track, mede)))
        return antes

    def _clamp(self, t, track=None):
        t = max(0.0, float(t))
        dur = (track or self.track or {}).get("duration") or 0
        return min(t, max(0.0, dur - 0.05)) if dur else t

    def pause(self):
        """Pausa o disco e cala os sons por cima: sem o Parar na tela (transporte do Spotify), o Pausar e o que silencia tudo.
        A pausa vale no limite entre blocos: com um bloco do prato retirado e ainda nao publicado, ela fica pendente (o
        paused so liga na confirmacao) e se confirma quando o _mixa o publicar; sem ele, na hora. Volta a Pausa (os
        pedidos da mesma linha sao a mesma)."""
        with self._qlock:
            p = self._pede_pausa()
        self.calar_sobre()
        return p

    def _pede_pausa(self):
        """Com _qlock: o pause, sem calar os sons por cima. Volta a Pausa."""
        d, p = self._deck, self._pausa
        if self.track is None or self.ended:  # nada tocando: pausa como antes, sem posicao para gravar
            self.paused = True
            p = Pausa(d, d.linha)
            p.resolve()
            return p
        if p is None or p.deck is not d or p.linha != d.linha:
            p = self._pausa = Pausa(d, d.linha)
        bl = self._bloco
        if not p.feita.is_set() and (bl is None or bl[0] is not d or bl[1] != d.linha):
            self.paused = True  # sem bloco em curso: a confirmacao e na hora
            p.resolve(self.track, self.pos, ok=True)
        return p

    def _retoma_sob_trava(self):
        """Com _qlock: o resume da pausa comum (o pedido pendente sai substituido). Volta True se o disco esta no fim:
        quem chama recomeca do zero (o _restart, que confere o fim de novo)."""
        if self.track is None:
            return False
        if self.ended:
            return True
        self.paused = False
        self._solta_pausa()
        return False

    def alterna(self):
        """O botao principal (o /api/toggle): tocando ou carregando, pausa e volta a Pausa; senao retoma e volta None.
        A escolha e a acao vao no mesmo trecho do _qlock, sob o _lock: o segundo toggle ve a pausa do primeiro, uma
        pausa ainda pendente conta como pausa (ele a retoma), e o fim publicado no meio nao vira pausa."""
        leitor = None
        with self._lock:
            with self._qlock:
                p = self._pausa
                pendente = p is not None and not p.feita.is_set()
                if not pendente and self.status() in ("playing", "buffering"):
                    p, fim = self._pede_pausa(), False
                else:
                    p, fim = None, self._retoma_sob_trava()
            if fim:
                leitor = self._restart(0.0, paused=False, pode=lambda: self.track is not None and self.ended)[1]
        if p is not None:
            self.calar_sobre()
        self._comeca(leitor)
        return p

    def calar_sobre(self):
        with self._slock:
            self._sobre = []

    def resume(self):
        """Retoma a pausa na mesma linha (o pedido de pausa pendente sai como substituido); no fim do disco, recomeca
        do zero numa linha nova."""
        leitor = None
        with self._lock:
            with self._qlock:
                fim = self._retoma_sob_trava()
            if fim:  # o _vira do _mixa pode tirar o fim no meio (sem o _lock): o pode do _restart confere de novo
                leitor = self._restart(0.0, paused=False, pode=lambda: self.track is not None and self.ended)[1]
        self._comeca(leitor)

    def stop(self, pode=None):
        with self._lock:
            with self._qlock:
                if pode is not None and not pode():
                    return None
                antes = self._captura_atual()
                self._cancela_passagem(tudo=True)
                d = self._deck
                d.linha += 1
                d.gen += 1
                d.q.clear()
                self._limitador_zera = True
                self.track = None
                self.loop = False  # o Repetir vale para o disco do prato, e ele saiu
                self.paused = False
                self.ended = False
                self._error = self._stream_warning = None
                self.pos = 0.0
                self._solta_pausa()
        self.calar_sobre()  # parar cala os sons por cima tambem
        return antes

    def seek(self, t, pode=None):
        """O disco do prato a partir de t, numa linha nova. pode(): conferido sob o _qlock antes de mudar qualquer
        coisa (o Anterior confere ali o deck e a linha que viu); falso, nada muda. Volta se mudou."""
        with self._lock:  # o limite pela duracao e o da faixa no prato no mesmo trecho do _qlock
            antes, leitor = self._restart(lambda: self._clamp(t),
                                          pode=lambda: self.track is not None and (pode is None or pode()))
        self._comeca(leitor)
        return antes is not None

    def set_loop(self, on):
        with self._lock:
            # ligou o loop depois que o leitor ja chegou ao fim: emenda outra volta
            with self._qlock:
                self.loop = bool(on)  # no mesmo trecho do _qlock em que o leitor decide repetir (_repete)
                d = self._deck
                emenda = self.loop and self.track is not None and d.eof_gen == d.gen
                fim = emenda and self.ended
                if emenda and not fim:
                    d.eof_gen = -1
                gen, tr = d.gen, self.track
            leitor = None
            if fim:  # recomeca so se ainda esta no fim, no mesmo trecho do _qlock
                leitor = self._restart(0.0, pode=lambda: self.ended)[1]
        if leitor is not None:
            leitor()
        elif emenda and not fim:
            threading.Thread(target=self._reader, args=(gen, tr, 0.0, d), daemon=True).start()

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
        Tempo de saida = o do relogio do som; no tempo de um disco que anda na velocidade v, 1 s de saida e v s dele.
        The status, the track and its duration are not here: the server reads them with the position and the queue in
        one capture (platter_state, under its fila_lock) and adds them (App.leitura)."""
        return {
            # 6 casas: a tela mostra o volume do disco ao cubo, e o baixo dele fica abaixo de 0,001
            "vol": round(self.vol, 6), "mon_vol": round(self.mon_vol, 6),
            # o volume automatico: ligado, e o ganho dele no disco do prato agora (dB; 0 = como veio)
            "volume_auto": self.volume_auto, "ganho_db": round(20 * float(np.log10(self._deck.ganho)), 1),
            "mic_vol": round(self.mic_vol, 3), "mic_mute": self.mic_mute,
            "monitor_on": self.monitor_on, "loop": self.loop,
            "effect": self.effect, "voice_monitor": self.voice_monitor,
            "por_cima": [sb[0] for sb in self._sobre],
            "abaixa": self.abaixamento(),
            "voice_mon_vol": round(self.voice_mon_vol, 3),
            "devices": dict(self.devices), "active_devices": dict(self.active),
            # o filtro do microfone: o anel aberto, os leitores do microfone em uso (0 = a musica nao chega nele) e
            # o microfone que o Windows esta preparando agora (null fora disso)
            "microfone": dict(self._injetor.estado() if self._injetor is not None and self._stack is not None
                              else {"anel": False, "leitores": 0}, preparando=self.preparando),
            "error": self.error,
            "mina": self._mina.estado if self._mina is not None else "desligada",
            "visor": {"ondas": self._ondas_versao,
                      "passagens": [p for p in (self._visor_feita, self._visor_pas) if p is not None]},
        }


class MockEngine(Engine):
    """Sem dispositivo de audio: um relogio de 10 ms chama o mesmo _mixa e joga uma
    voz falsa no microfone. Serve pra testar interface sem som (server.py --mock)."""

    def _real_names(self):
        act = self.resolve()
        for k, kind in (("mic", "in"), ("monitor", "out")):
            if act[k]:
                try:
                    act[k] = find_dev(act[k], kind)[1]["name"]
                except ValueError:
                    pass
        return act

    relogio = True  # False (os testes, server.App(relogio=False)): sem o _clock, quem testa chama o _mixa

    def start(self, reserva=False):
        self.active = self._real_names()
        self._run = True
        if self.relogio:
            threading.Thread(target=self._clock, daemon=True).start()

    def close(self):
        self._pedal_voz_fecha()
        with self._qlock:
            self._gen += 1
            self._solta_pausa()
        self._run = False

    def _mina_liga(self):
        pass  # sem som, sem a mina: a sessao custaria e nao tocaria em lugar nenhum

    def _pedal_voz_liga(self, ligado):
        pass  # sem som, sem a troca de voz: o processo dela leria e escreveria no anel do filtro de verdade

    def _pedal_voz_fecha(self):
        pass

    def set_devices(self, mic=None, monitor=None):
        for k, v in (("mic", mic), ("monitor", monitor)):
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
                self._prepare_failure_tag = self.pronto_tag
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
                         "grade_para": None, "motivo": (f"tempos far apart, {bpm_a:.1f} and {bpm_b:.1f} BPM"
                                                        if abs(s - 1) > TEMPO_MAX else "the beat of the switch already passed")}
            self._sobrepor = self._entrar = int(sob * SR)
            self._grave = None
            self._virar_em = t0 - BLOCK / (2 * SR)
            self._visor_pas = _visor_publico(tr_atual, prox.track, visor)
        print(f"transition (mock): {tr_atual.get('title')!r} -> {prox.track.get('title')!r}: "
              f"{'on beat' if visor['no_tempo'] else 'crossfade only'}, switches at {t0:.2f} s", file=sys.stderr, flush=True)

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
            self._mixa(BLOCK)
            self._mon.clear()
            nxt += BLOCK / SR
            time.sleep(max(0.0, nxt - time.perf_counter()))
