"""Efeitos de voz do soundboard (estilo Voicemod), aplicados bloco a bloco na voz antes da
mistura com o som. Regra: todo efeito devolve o mesmo numero de amostras que recebe e
nao passa de ~30 ms de atraso, senao a voz atrasa no jogo.

Medido em 17/10 com blocos de 10 ms: o PitchShift da pedalboard so devolve som depois de
~51 mil amostras (1 s) e o GSM/MP3 perdem amostras no caminho, entao ficam de fora; o
tom e mudado aqui (PitchShifter, linha de atraso com duas leituras em cruzamento, o
transpose classico do Faust). Filtros, distorcao, compressor, reverb, eco, chorus,
phaser e bitcrush da pedalboard tem atraso zero e custam menos de 0,1 ms por bloco.
O HighpassFilter/LowpassFilter dela e de primeira ordem (6 dB/oitava): numa faixa de
radio de 450 a 2800 Hz cortava so 5 a 13 dB fora dela e a voz passava quase inteira
(17/10). Faixa estreita de verdade = FiltroBanda (Butterworth do scipy).
"""
import importlib.util

import numpy as np
import pedalboard as pb
from scipy import signal

SR = 48000


class PitchShifter:
    """Muda o tom sem mudar a duracao: le a linha de atraso numa velocidade 2^(s/12) com
    duas leituras defasadas de w amostras, trocando de uma para a outra por cruzamento
    de x amostras quando a leitura da a volta. Atraso medio ~0,75*w; sem preservar
    formante (o timbre de desenho animado e o que se quer em voz grossa e esquilo)."""

    def __init__(self, semitons, w=1536, x=768):
        self.i = 1 - 2 ** (semitons / 12)
        self.w, self.x = w, x
        self.d = 0.0 if self.i >= 0 else w - 1e-3
        self.hist = np.zeros(2 * w + 4, np.float32)

    def __call__(self, blk):
        n = len(blk)
        buf = np.concatenate([self.hist, blk])
        h = len(self.hist)
        k = np.arange(n)
        d = (self.d + self.i * (k + 1)) % self.w
        self.d = float(d[-1])
        g = np.minimum(d / self.x, 1.0)
        last = len(buf) - 1

        def tap(delay):
            pos = h + k - delay
            i0 = np.floor(pos).astype(np.int64)
            fr = pos - i0
            return buf[i0] * (1 - fr) + buf[np.minimum(i0 + 1, last)] * fr

        y = tap(d) * g + tap(d + self.w) * (1 - g)
        self.hist = buf[-h:]
        return y.astype(np.float32)

    @property
    def latencia_ms(self):
        return 0.75 * self.w / SR * 1000


class RingMod:
    """Multiplica a voz por uma senoide grave: a voz de robo classica."""

    def __init__(self, hz, mix=1.0):
        self.hz, self.mix, self.fase = hz, mix, 0.0

    def __call__(self, blk):
        n = len(blk)
        f = self.fase + 2 * np.pi * self.hz * np.arange(1, n + 1) / SR
        self.fase = float(f[-1] % (2 * np.pi))
        return (blk * (1 - self.mix + self.mix * np.sin(f))).astype(np.float32)


class CambioRadio:
    """Rádio de polícia: chiado enquanto o canal está aberto e, quando a fala para, o bip
    de câmbio com o rabo de estática. Duas etapas que dividem o estado: `detecta` antes do
    compressor (ouve a voz crua) e `injeta` depois dele, antes do filtro de faixa. Com o
    chiado antes do compressor, ele subia ate o nivel da voz quando a fala parava (o
    compressor soltava): medido -22,6 dBFS de chiado contra -23,1 da voz
    (17/10). Depois do compressor o nivel e fixo."""

    # 70 blocos = 700 ms calado: com 300 ms bipava em toda pausa entre frases
    LIGA, DESLIGA, SILENCIO = 10 ** (-40 / 20), 10 ** (-48 / 20), 70
    # niveis no ponto de injecao: chiado ~21 dB abaixo da voz, bip e kssh perto dela
    CHIADO, ESTALO, BIP, RABO = 0.022, 0.6, 0.3, 0.6

    def __init__(self):
        self.falando = False
        self.quieto = 0
        self.fila = np.zeros(0, np.float32)
        self.rng = np.random.default_rng(3)

    def _ruido(self, seg, nivel, cai=False):
        n = int(seg * SR)
        r = self.rng.standard_normal(n) * nivel
        return (r * np.linspace(1, 0, n) if cai else r).astype(np.float32)

    def _bip(self):
        t = np.arange(int(0.16 * SR)) / SR
        tom = self.BIP * np.sin(2 * np.pi * np.where(t < 0.08, 1200, 1600) * t)
        tom *= np.minimum(1, np.minimum(t, t[-1] - t) / 0.004)  # sem estalo nas pontas
        return np.concatenate([tom.astype(np.float32), self._ruido(0.14, self.RABO, cai=True)])

    def detecta(self, blk):
        rms = float(np.sqrt(np.mean(blk * blk)))
        if not self.falando and rms > self.LIGA:
            self.falando, self.quieto = True, 0
            self.fila = self._ruido(0.04, self.RABO, cai=True)  # abre o squelch
        elif self.falando:
            self.quieto = self.quieto + 1 if rms < self.DESLIGA else 0
            if self.quieto >= self.SILENCIO:
                self.falando = False
                self.fila = np.concatenate([self.fila, self._bip()])
        return blk

    def som(self, n):
        """So os sons do canal (chiado, estalo, squelch, bip) num bloco de n amostras: o
        Efeito soma isso depois do nivelador, para o nivelador medir so a voz."""
        return self.injeta(np.zeros(n, np.float32))

    def injeta(self, blk):
        y = blk.copy()
        if self.falando:
            y += self._ruido(len(blk) / SR, self.CHIADO)
            if self.rng.random() < 0.03:  # estalo de estatica de vez em quando
                k = int(self.rng.integers(0, len(blk) - 96))
                y[k:k + 96] += (self.rng.standard_normal(96) * self.ESTALO).astype(np.float32)
        if len(self.fila):
            m = min(len(self.fila), len(y))
            y[:m] += self.fila[:m]
            self.fila = self.fila[m:]
        return y


class PortaoRuido:
    """Fecha o microfone fora da fala, como o microfone de boca colada de um megafone, que
    so pega o que esta quase tao forte quanto a voz de quem fala.

    Abre so para som a no maximo ABRE_VOZ abaixo do nivel tipico da fala do usuario (media em dB
    dos blocos fortes com o portao aberto) e nunca abaixo de fundo + 12 dB; antes de
    ouvir fala, so abre a fundo + 24 dB. Uma vez aberto, segura as caudas fracas das
    palavras ate o som cair perto do fundo (fundo + 8 dB) por 150 ms. Abre no bloco em que
    o som chega (rampa de 1 ms) e fecha em ~100 ms.

    Historico de 17/10: a 1a versao abria a fundo + 12 dB e o megafone pegava um cachorro
    latindo que sem efeito nao aparecia; com latidos sinteticos nas pausas
    de uma gravacao de voz, um latido 24 dB abaixo da fala saia +1,2 dB acima dela (o compressor
    e o ganho levantam o que passa). dev/latido.py mede isso."""

    ABRE_FUNDO, FECHA, SEM_VOZ = 10 ** (12 / 20), 10 ** (8 / 20), 10 ** (24 / 20)
    ABRE_VOZ, PISO = 10 ** (-12 / 20), 10 ** (-60 / 20)  # -15 deixava passar latido de -18
    SEGURA, FECHAR_EM, MEMORIA_VOZ = 15, 10, 0.98  # blocos de 10 ms; voz com ~0,5 s

    def __init__(self, piso_db=-60):
        self.piso = 10 ** (piso_db / 20)
        self.fundo = None
        self.voz_db = None
        self.n = 0
        self.g = self.piso
        self.aberto = False
        self.resta = 0

    def __call__(self, blk):
        rms = float(np.sqrt(np.mean(blk * blk))) + 1e-9
        self.n += 1
        if self.fundo is None or self.n <= 30:  # primeiros 300 ms: menor nivel visto
            self.fundo = rms if self.fundo is None else min(self.fundo, rms)
        elif not self.aberto:
            # o fundo desce na hora e sobe devagar (~3 dB/s) so com o portao fechado
            self.fundo = min(rms, self.fundo * 10 ** (0.03 / 20))
        if self.voz_db is None:
            abre = self.fundo * self.SEM_VOZ
        else:
            abre = max(self.fundo * self.ABRE_FUNDO, 10 ** (self.voz_db / 20) * self.ABRE_VOZ)
        if rms > abre:
            self.aberto, self.resta = True, self.SEGURA
        elif self.aberto and rms < self.fundo * self.FECHA:
            self.resta -= 1
            if self.resta <= 0:
                self.aberto = False
        if self.aberto and rms > self.fundo * self.SEM_VOZ:  # bloco de fala de verdade
            db = 20 * np.log10(rms)
            m = self.MEMORIA_VOZ
            self.voz_db = db if self.voz_db is None else m * self.voz_db + (1 - m) * db
        alvo = 1.0 if self.aberto else self.piso
        n = len(blk)
        if alvo > self.g:  # abre rapido: 1 ms
            k = min(n, int(0.001 * SR))
            rampa = np.concatenate([np.linspace(self.g, 1.0, k), np.ones(n - k)])
        else:  # fecha em ~FECHAR_EM blocos, em escala de dB
            fim = max(alvo, self.g * (self.piso ** (1 / self.FECHAR_EM)))
            rampa = np.geomspace(self.g, fim, n)
        self.g = float(rampa[-1])
        return (blk * rampa).astype(np.float32)


class PassaAlta:
    """Passa-alta Butterworth com estado entre blocos: tira o ronco abaixo da voz."""

    def __init__(self, corte, ordem=4):
        self.sos = signal.butter(ordem, corte, btype="high", fs=SR, output="sos")
        self.zi = np.zeros((self.sos.shape[0], 2))

    def __call__(self, blk):
        y, self.zi = signal.sosfilt(self.sos, blk, zi=self.zi)
        return y.astype(np.float32)


class FiltroBanda:
    """Passa-faixa Butterworth com estado entre blocos (sos + zi): corta 30 a 60 dB fora
    da faixa, o que o filtro de 6 dB/oitava da pedalboard nao faz."""

    def __init__(self, lo, hi, ordem=6):
        self.sos = signal.butter(ordem, [lo, hi], btype="band", fs=SR, output="sos")
        self.zi = np.zeros((self.sos.shape[0], 2))

    def __call__(self, blk):
        y, self.zi = signal.sosfilt(self.sos, blk, zi=self.zi)
        return y.astype(np.float32)


class Decimador:
    """Amostra e segura a cada `fator` amostras (48 kHz / 6 = 8 kHz) sem filtro: a
    aspereza de audio digital de radio. 480 e multiplo de 6, entao o bloco fecha certo."""

    def __init__(self, fator):
        self.f = fator

    def __call__(self, blk):
        n = len(blk) - len(blk) % self.f
        y = blk.copy()
        y[:n] = np.repeat(blk[:n:self.f], self.f)
        return y


class KPeso:
    """Ponderacao K da BS.1770 (a do LUFS) a 48 kHz, com estado: o volume como o ouvido
    percebe, para comparar a voz crua com a voz com efeito."""

    SOS = np.array([[1.53512485958697, -2.69169618940638, 1.19839281085285,
                     1.0, -1.69065929318241, 0.73248077421585],
                    [1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621]])

    def __init__(self):
        self.zi = np.zeros((2, 2))

    def energia(self, x):
        y, self.zi = signal.sosfilt(self.SOS, x, zi=self.zi)
        return float(np.mean(y * y))


def _bandas_bark(n):
    """Matriz 25 x (n/2+1) que soma a potencia do rfft em cada banda critica (1 Bark)."""
    f = np.fft.rfftfreq(n, 1 / SR)
    z = 13 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500) ** 2)
    return np.array([((z >= b) & (z < b + 1) & (f >= 50) & (f <= 15000)).astype(np.float64)
                     for b in range(25)])


class Audibilidade:
    """Volume como o ouvido soma, em tempo real: energia por banda critica (escala Bark)
    de uma janela de 1024 amostras, cada banda elevada a 0,23 e somadas (lei de Stevens
    por banda, aproximacao do Zwicker sem limiar nem mascaramento). A ponderacao K mede
    energia e superestimava o radio numa voz grave: na gravacao real (17/10) o radio
    dava +2,2 dB pela K e -0,9 dB por este modelo, que bate com o que se ouvia."""

    N = 1024
    BANDAS = _bandas_bark(N)
    JANELA = np.hanning(N)
    EXPOENTE = 0.23

    def __init__(self):
        self.hist = np.zeros(self.N, np.float32)

    def __call__(self, blk):
        self.hist = np.concatenate([self.hist[len(blk):], blk])[-self.N:]
        p = np.abs(np.fft.rfft(self.hist * self.JANELA)) ** 2
        return float(np.sum((self.BANDAS @ p + 1e-12) ** self.EXPOENTE))


class Efeito:
    """Cadeia: etapas numpy antes, pedalboard no meio, etapas numpy depois, limite no fim."""

    # nivelador: so atualiza enquanto ha fala; iguala a audibilidade MEDIA (Audibilidade,
    # o mesmo modelo do dev/audibilidade.py, ~1 s de memoria) da voz com efeito a da voz
    # crua. Historico de 17/10 (radio um pouco mais baixo): igualar energia
    # K pela media ou pelos picos deixava o radio em -0,9 dB pelo ouvido numa voz grave,
    # porque a K superestima o grave que o radio corta. Ganho anda em ~120 ms, ate
    # 20 dB para cada lado.
    FALA, MEMORIA, PASSO, TETO = 10 ** (-50 / 10), 0.99, 0.08, 10 ** (20 / 20)

    def __init__(self, antes=(), placa=(), depois=(), nivelar=False, extra=None):
        # antes/depois aceitam etapa numpy ou lista de plugins da pedalboard
        self.antes, self.depois = [self._etapa(f) for f in antes], [self._etapa(f) for f in depois]
        self.ganho = 1.0
        self.placa = pb.Pedalboard(list(placa)) if placa else None
        # efeito com compressor sai quase no mesmo volume seja qual for a voz: a
        # compensacao fixa so acerta um nivel de microfone (o radio ficava 4,6 dB abaixo
        # da voz com o microfone 6 dB mais quente, 17/10); o nivelador iguala
        # o volume percebido (ponderacao K) da saida ao da voz crua enquanto ha fala
        self.nivelar = nivelar
        # extra = (gerador(n), etapas): som somado DEPOIS do nivelador, com a cor das
        # etapas; os ruidos do radio contavam como volume e o nivelador baixava a voz
        # para compensar (17/10: radio um pouco mais baixo que a voz)
        self.extra = None
        if extra is not None:
            self.extra = (extra[0], [self._etapa(f) for f in extra[1]])
        self.a_in, self.a_out = Audibilidade(), Audibilidade()
        self.m_in = self.m_out = 0.0
        self.g_auto = 1.0

    @staticmethod
    def _etapa(f):
        if isinstance(f, (list, tuple)):
            placa = pb.Pedalboard(list(f))
            return lambda x: placa(x.reshape(1, -1), SR, reset=False)[0]
        return f

    def __call__(self, x):
        x = x.astype(np.float32, copy=False)
        cru = x
        for f in self.antes:
            x = f(x)
        if self.placa is not None:
            x = self.placa(x.reshape(1, -1), SR, reset=False)[0]
        for f in self.depois:
            x = f(x)
        x = x * self.ganho
        if self.nivelar:
            # o volume e medido pelo ouvido (Audibilidade, em "sones" relativos); com ganho g
            # a audibilidade cresce como g^0,46, dai o expoente 1/0,46 na conversao
            ni, no = self.a_in(cru), self.a_out(x)
            if float(np.mean(cru * cru)) > self.FALA:
                m = self.MEMORIA
                self.m_in, self.m_out = m * self.m_in + (1 - m) * ni, m * self.m_out + (1 - m) * no
            if self.m_in > 0 and self.m_out > 0:
                razao = (self.m_in / self.m_out) ** (1 / (2 * Audibilidade.EXPOENTE))
                alvo = min(max(razao, 1 / self.TETO), self.TETO)
                self.g_auto += (alvo - self.g_auto) * self.PASSO
            x = x * self.g_auto
        if self.extra is not None:
            gerador, etapas = self.extra
            e = gerador(len(x))
            for f in etapas:
                e = f(e)
            x = x + e * self.ganho * (self.g_auto if self.nivelar else 1.0)
        return np.clip(x, -1, 1)

    @property
    def latencia_ms(self):
        return round(sum(getattr(f, "latencia_ms", 0) for f in self.antes + self.depois))


class PassaBaixa(PassaAlta):
    """Passa-baixa Butterworth com estado entre blocos."""

    def __init__(self, corte, ordem=8):
        self.sos = signal.butter(ordem, corte, btype="low", fs=SR, output="sos")
        self.zi = np.zeros((self.sos.shape[0], 2))


class AGC:
    """Controle de volume lento dos processadores de radio: leva a fala ao alvo (dBFS de
    RMS) em ~0,5 s para baixar e ~2 s para subir, e congela nas pausas (nao levanta o
    fundo). Deixa os limiares fixos do resto da cadeia valendo para qualquer microfone."""

    def __init__(self, alvo_db=-20, porta_db=-55, teto_db=30):
        self.alvo, self.porta, self.teto = alvo_db, porta_db, teto_db
        self.nivel, self.g = alvo_db, 0.0

    def __call__(self, blk):
        db = 10 * np.log10(float(np.mean(blk * blk)) + 1e-12)
        if db > self.porta:
            self.nivel += (db - self.nivel) * 0.1  # ~100 ms de media
            alvo = float(np.clip(self.alvo - self.nivel, -self.teto, self.teto))
            self.g += (alvo - self.g) * (0.02 if alvo < self.g else 0.005)
        return (blk * 10 ** (self.g / 20)).astype(np.float32)


class CompBanda:
    """Compressor de uma faixa com ganho por bloco (rampa dentro do bloco) e portao de
    congelamento: abaixo do portao o ganho fica parado em vez de soltar, e o fundo entre
    as palavras nao sobe com o makeup. O portao olha o bloco, nao o envelope: pelo
    envelope a reducao ja tinha soltado ate zero antes de congelar (17/10, a ventoinha
    entre palavras subia 10 dB acima do caricato; com o portao no bloco, 3 dB)."""

    def __init__(self, limiar_db, razao, ataque_ms, solta_ms, ganho_db):
        self.lim, self.razao, self.ganho = limiar_db, razao, ganho_db
        self.portao = limiar_db - 10
        self.a, self.s = np.exp(-10 / ataque_ms), np.exp(-10 / solta_ms)
        self.env, self.red = limiar_db - 30, 0.0

    def __call__(self, blk):
        db = 10 * np.log10(float(np.mean(blk * blk)) + 1e-12)
        ant = self.red
        if db > self.portao:
            k = self.a if db > self.env else self.s
            self.env = k * self.env + (1 - k) * db
            self.red = max(0.0, self.env - self.lim) * (1 - 1 / self.razao)
        rampa = 10 ** ((np.linspace(-ant, -self.red, len(blk), dtype=np.float32) + self.ganho) / 20)
        return (blk * rampa).astype(np.float32)


class Multibanda:
    """Divide em faixas por Linkwitz-Riley de 4a ordem em arvore (cada corte separa o resto
    em baixo e alto), passa cada faixa pelo seu compressor e soma."""

    def __init__(self, cortes, comps):
        bw = lambda f, t: signal.butter(2, f, btype=t, fs=SR, output="sos")
        self.pares = [(np.vstack([bw(c, "low")] * 2), np.vstack([bw(c, "high")] * 2)) for c in cortes]
        self.zi = [[np.zeros((lo.shape[0], 2)), np.zeros((hi.shape[0], 2))] for lo, hi in self.pares]
        self.comps = comps

    def __call__(self, blk):
        resto, out = blk, np.zeros_like(blk)
        for k, (lo, hi) in enumerate(self.pares):
            b, self.zi[k][0] = signal.sosfilt(lo, resto, zi=self.zi[k][0])
            resto, self.zi[k][1] = signal.sosfilt(hi, resto, zi=self.zi[k][1])
            out += self.comps[k](b.astype(np.float32))
        return (out + self.comps[-1](resto.astype(np.float32))).astype(np.float32)


class QuestComoSM58:
    """Faz o microfone do Quest soar como o SM58 colado na boca: equalizador fixo com a
    curva tirada de uma leitura gravada nos dois ao mesmo tempo (17/10: o Quest tinha 6,6 dB
    a menos de grave, 5 dB a mais em 400-500 Hz e 5 a 9 dB a menos em 3-5 kHz; numa
    segunda leitura que a curva nao viu ficou a 1,2 dB do SM58). FIR de fase minima: o
    atraso fica perto de zero. Sem tirar sala: o Quest ja limpa o fundo, e o removedor de
    sala depois da supressao dele soava robotico (a mesma soma do NVIDIA)."""

    # dB por sexto de oitava a partir de 50 Hz (50 * 2^(k/6)); abaixo, 0
    CURVA = (0.0, 0.8, 1.7, 2.7, 3.9, 5.2, 6.6, 6.5, 6.3, 6.1, 5.5, 4.4, 3.2, 1.9, 0.4, -0.9,
             -2.4, -3.8, -5.0, -4.4, -4.8, -5.3, -5.1, -4.1, -3.4, -3.3, -2.6, -1.6, -0.5, 0.1,
             0.2, -0.2, -0.1, 1.3, 4.2, 5.4, 5.1, 7.9, 8.7, 6.7, 5.3, 3.1, -0.8, -0.8, 0.0,
             -0.7, 0.0, -2.7, -9.9, -12.0, -12.0, -12.0)

    def __init__(self, taps=1023):
        f = np.linspace(0, SR / 2, 961)
        pts = 50 * 2 ** (np.arange(len(self.CURVA)) / 6)
        db = np.interp(np.log(np.maximum(f, 1)), np.log(pts), self.CURVA)
        self.h = signal.minimum_phase(signal.firwin2(taps, f / (SR / 2), 10 ** (db / 20)),
                                      method="homomorphic", half=False)
        self.zi = np.zeros(len(self.h) - 1)

    def __call__(self, blk):
        y, self.zi = signal.lfilter(self.h, 1.0, blk, zi=self.zi)
        return y.astype(np.float32)


def _locutor():
    # processador de radio FM (no molde dos de emissora): AGC lento -> EQ de locutor ->
    # 4 faixas com compressao de ataque lento no grave e ganho congelado nas pausas ->
    # compressor rapido (a densidade de radio no ar: o de 10 ms ou a compressao lenta das
    # faixas paravam em 7,3 a 9 dB de variacao entre silabas) -> limitador -> 15 kHz.
    # Ajustado no ouvido em 17/10 contra o "caricato" (grave +9, embolado -5, presenca
    # +6, compressor 6:1): mesma densidade e timbre, menos o cavado em 220-400 Hz que
    # tirava a cara de quem fala (no caricato soava como outra pessoa, no FM a voz
    # continua reconhecivel); o grave entra no makeup da faixa de baixo, porque um reforco
    # antes do compressor ele mesmo desfazia. Calibrado para o microfone do Quest (a voz do usuario
    # no VRChat): a curva QuestComoSM58 entra primeiro, sempre (o filtro
    # separado nem precisa)
    return Efeito(nivelar=True, antes=[QuestComoSM58(), PortaoRuido(piso_db=-24), PassaAlta(70), AGC()],
                  placa=[pb.PeakFilter(350, -3, 1.0), pb.PeakFilter(3000, 3, 0.8), pb.HighShelfFilter(8000, -1, 0.7)],
                  depois=[Multibanda((200, 1200, 5000), [
                              # limiares ~7 dB abaixo da fala de cada faixa com o AGC em -20
                              CompBanda(-30, 4, 30, 300, 9),
                              CompBanda(-35, 4, 15, 250, 6),
                              CompBanda(-45, 4, 8, 200, 8.5),
                              CompBanda(-46, 2, 5, 150, 8)]),
                          [pb.Compressor(threshold_db=-24, ratio=6, attack_ms=3, release_ms=80),
                           pb.Gain(7), pb.Limiter(-1.0, 60), pb.PeakFilter(6000, -2.5, 1.4)],
                          PassaBaixa(15000)])


def _locutor_caricato():
    # o modo CARICATO do Locutor: a versao exagerada de 17/10 que serviu de referencia para o
    # processador de FM (grave +9, embolado -5, presenca +6, brilho +4, compressor 6:1 e um
    # pouco de saturacao, como o clipador das emissoras). Soa como outro locutor, nao como
    # quem fala; a comparacao no ouvido foi com o microfone do Quest ja passado pela curva
    # QuestComoSM58, e assim ela entra aqui
    return Efeito(nivelar=True, antes=[QuestComoSM58(), PortaoRuido(piso_db=-24), PassaAlta(70)],
                  placa=[pb.LowShelfFilter(180, 9, 0.7), pb.PeakFilter(350, -5, 1.0),
                         pb.PeakFilter(3000, 6, 0.9), pb.HighShelfFilter(9000, 4, 0.7),
                         pb.Compressor(threshold_db=-30, ratio=6, attack_ms=3, release_ms=80),
                         pb.Distortion(6), pb.Limiter(-1.0, 50)])


def _radio():
    # radio portatil de policia: microfone comprimido e estourado, audio digital de 8 kHz,
    # faixa estreita de 350 a 2700 Hz com o meio na cara; o chiado e o bip vem antes de tudo
    canal = CambioRadio()
    cor = lambda: [Decimador(6), FiltroBanda(350, 2700), [pb.PeakFilter(1800, 6, 1.2), pb.Gain(-4)]]
    return Efeito(nivelar=True, antes=[canal.detecta],
                  placa=[pb.Compressor(threshold_db=-32, ratio=12, attack_ms=2, release_ms=60),
                         pb.Gain(14), pb.Distortion(18), pb.Bitcrush(8)],
                  depois=cor(), extra=(canal.som, cor()))


# grupo, id, nome, o que faz, fabrica
CATALOGO = [
    ("", "nenhum", "Sem efeito", "Sua voz como ela é.", lambda: None),
    ("Rádio e alto-falante", "radio-policia", "Rádio de polícia",
     "Voz de rádio com chiado e o bip de câmbio quando você para de falar.", _radio),
    ("Rádio e alto-falante", "megafone", "Megafone", "Voz estourada de megafone.",
     # sem compressor: megafone distorce o que e forte e deixa fraco o que e fraco; o
     # compressor + drive 26 levantava tudo que passava ao maximo (latido 6 dB abaixo da
     # fala saia +19,9 dB acima dos trechos fortes dela; agora +3,7)
     lambda: Efeito(nivelar=True, antes=[PortaoRuido()], placa=[pb.Distortion(18)],
                    depois=[FiltroBanda(550, 4200, 4), [pb.PeakFilter(1700, 8, 1.4), pb.Gain(-8)]])),
    ("Rádio e alto-falante", "locutor", "Locutor de rádio FM",
     "Voz densa e encorpada de rádio FM, ainda com a sua cara (calibrado no microfone do Quest).", _locutor),
    ("Ambiente", "eco", "Eco", "Repete o fim das suas frases.",
     lambda: Efeito(nivelar=True, placa=[pb.Delay(0.28, 0.45, 0.4)])),
    ("Ambiente", "banheiro", "Banheiro", "Sala pequena de azulejo.",
     lambda: Efeito(nivelar=True, placa=[pb.Reverb(room_size=0.35, damping=0.3, wet_level=0.35, dry_level=0.8)])),
    ("Ambiente", "catedral", "Catedral", "Sala enorme, a voz some devagar.",
     lambda: Efeito(nivelar=True, placa=[pb.Reverb(room_size=0.97, damping=0.25, wet_level=0.5, dry_level=0.7)])),
    ("Personagem", "robo", "Robô", "Voz metálica de robô.",
     lambda: Efeito(nivelar=True, antes=[RingMod(48)], placa=[pb.Chorus(rate_hz=0.6, depth=0.15, mix=0.3), pb.Gain(3)])),
    ("Personagem", "voz-grossa", "Voz grossa", "Cinco semitons abaixo.",
     lambda: Efeito(nivelar=True, antes=[PitchShifter(-5)], placa=[pb.LowShelfFilter(180, 3)])),
    ("Personagem", "esquilo", "Esquilo", "Oito semitons acima.",
     lambda: Efeito(nivelar=True, antes=[PitchShifter(8, w=1024, x=512)])),
    ("Personagem", "demonio", "Demônio", "Dez semitons abaixo, com distorção e sala.",
     lambda: Efeito(nivelar=True, antes=[PitchShifter(-10, w=2048, x=1024)],
                    placa=[pb.Distortion(8), pb.LowShelfFilter(150, 4),
                           pb.Reverb(room_size=0.5, wet_level=0.25, dry_level=0.85), pb.Gain(-3)])),
    ("Personagem", "alien", "Alienígena", "Um pouco mais agudo, ondulando.",
     lambda: Efeito(nivelar=True, antes=[PitchShifter(4, w=1024, x=512)],
                    placa=[pb.Phaser(rate_hz=1.2, depth=0.8, mix=0.6), pb.Chorus(rate_hz=2, depth=0.3, mix=0.4)])),
    ("Personagem", "estourado", "Alto-falante estourado", "Distorção pesada, como caixa no talo.",
     lambda: Efeito(nivelar=True, placa=[pb.Distortion(32), pb.LowpassFilter(5000), pb.Gain(-12)])),
]
# o pedal da mina (mina.py, modulo de fora deste repo, ver o engine.py): onde o modulo esta ao lado do codigo, ele
# entra no lugar do alto-falante estourado e liga a DJ que conversa com quem chega; a voz de quem toca passa sem efeito
if importlib.util.find_spec("mina") is not None:
    CATALOGO = [c for c in CATALOGO if c[1] != "estourado"] + [
        ("Personagem", "mina", "Mina DJ", "Liga a DJ que conversa com quem chega e toca o que pedirem.",
         lambda: None)]
# os modos de um pedal: efeito que liga pelo botao do modo (o CARICATO do Locutor) e nao vira
# pedal na lista do /api/effects; o primeiro campo e o pedal dono, no lugar do grupo
MODOS = [
    ("locutor", "locutor-caricato", "Locutor de rádio FM caricato",
     "Locutor de FM exagerado, com cara de outra pessoa falando.", _locutor_caricato),
]
_POR_ID = {c[1]: c for c in CATALOGO + MODOS}

# compensa o volume de cada efeito para a troca nao sumir nem estourar a voz: o inverso do
# nivel medido durante a fala pelo dev/efeitos.py (17/10, fala do TTS a ~-14 dBFS de pico;
# radio e megafone remedidos depois do filtro de faixa estreita; o locutor entrou no lugar
# do telefone em 17/10 e virou o processador de FM no mesmo dia: o AGC dele
# sobe a voz fraca ate 30 dB e o nivelador so desce 20, entao com -4 a voz 24 dB mais baixa
# saia +5,3 dB acima da crua; com -10, +2,5 no TTS e +0,4 no Quest; o caricato, medido em
# 29/10 sem o nivelador, sai +3,0 dB no TTS e +2,0 no Quest)
COMPENSA_DB = {"radio-policia": -8.6, "megafone": -2.4, "locutor": -10.0, "locutor-caricato": -3.0,
               "eco": 2.7, "banheiro": -4.3, "catedral": -5.8, "robo": 2.2, "esquilo": 0.7,
               "demonio": -10.2, "alien": 5, "estourado": -7.4}


def criar(efeito_id):
    """Instancia nova (estado zerado) do efeito; None para 'nenhum'."""
    if efeito_id not in _POR_ID:
        raise ValueError(f"Não conheço o efeito \"{efeito_id}\".")
    e = _POR_ID[efeito_id][4]()
    if e is not None:
        e.ganho = 10 ** (COMPENSA_DB.get(efeito_id, 0) / 20)
    return e


def existe(efeito_id):
    """O efeito da lista ou o de um modo de pedal."""
    return efeito_id in _POR_ID


def lista():
    out = []
    for grupo, eid, nome, desc, fab in CATALOGO:
        e = fab()
        out.append({"id": eid, "nome": nome, "grupo": grupo, "descricao": desc,
                    "latencia_ms": e.latencia_ms if e else 0})
    return out
