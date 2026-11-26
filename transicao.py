"""As contas da passagem de um disco para o proximo, sem audio: o fim, o comeco e o corpo de cada disco pelo nivel dos
blocos que o leitor do motor guarda (t0, quadros, rms), a escolha entre o fade-out e o final seco, quantas batidas a
proxima entra antes da troca, e os tempos da passagem no tempo a partir das grades e das fases ja medidas: a
velocidade de cada lado, a batida em que a proxima cai, a virada num comeco de bloco e a troca de grave.

O motor (engine.py) le o audio, mede a fase antes e depois de esticar, estica, poe o eco, filtra o grave e monta os
blocos; aqui so entram numeros e o nivel, e sai a decisao, para o dev/testa_transicao.py rodar sem som nem ffmpeg."""
import numpy as np

SR = 48000
BLOCK = 480  # 10 ms
TRANS_MAX_S = 8.0          # a sobreposicao mais longa, a do fade-out
TRANS_SECO_S = 0.25        # final seco: so o tanto que evita o estalo
SILENCIO = 10 ** (-48 / 20)  # bloco abaixo disso (-48 dBFS) e silencio
FADE_DB = 3.0              # o fade-out comeca onde o nivel deixa de ficar a 3 dB do normal do fim
FADE_MIN_S = 1.5           # queda mais curta que isso e final seco
FIM_DB = 20.0              # 20 dB abaixo do normal o fade ja acabou para o ouvido: o rabo dele e cortado
FASE_ANTES_S = 4.0         # no que sai, a fase comeca a ser medida isso antes da virada
FASE_MIN_S = 4.0
TEMPO_MAX = 0.05           # a proxima estica ate 5% para casar o andamento: 3,5% (Despacito -> Paper
                           # Planes) e 4,9% (Without Me -> Overdose) passaram sem se notar, e o Hino do Gremio a 6,4% ja soou
                           # diferente do original (21/10); os 8% de antes eram o curso do pitch do toca-discos
SAI_MAX = 0.02             # o que falta alem disso, ate 2%, a que sai anda devagar antes da sobreposicao: no Macetada
                           # -> Hino do Gremio com 2% nela e 3,9% no hino nao se ouviu diferenca dos originais; 4,9% na
                           # que sai (a NWA) se ouviu (21/10)
# depois da sobreposicao, a proxima volta ao andamento dela devagar, como o DJ que empurra o pitch aos poucos
# (8 s era pouco; 3,5% em 8 s soava como a musica freando)
RAMPA_TAXA = 0.001         # em media 0,1% de andamento por segundo (meio cosseno: no meio da volta, 0,16%)
RAMPA_MIN_S = 8.0          # e nunca em menos que isso, nem em mais que RAMPA_MAX_S
RAMPA_MAX_S = 60.0
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


def medir_inicio(niv):
    """Onde comeca o som: o primeiro bloco acima do silencio (0 se nao ha)."""
    if not niv:
        return 0.0
    t, _, r = _niveis(niv)
    som = np.nonzero(r > SILENCIO)[0]
    return float(t[som[0]]) if len(som) else 0.0


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


def escolha(fim, queda, baixo, pos):
    """Fade-out ou final seco, pelo que o medir_fim achou no fim deste, com o disco em pos: (fim, caindo, fade, virar,
    sobrepor). Sem som no resto deste (fim None), a proxima entra ja (fim = pos)."""
    if fim is None:  # o resto deste e silencio: a proxima entra ja
        fim = pos
    caindo = baixo - queda if queda is not None and baixo is not None else 0.0
    fade = caindo >= FADE_MIN_S
    if fade:  # fade-out: sem plano no tempo (os andamentos nao casam ou falta batida), o fade de sempre: a proxima
        # sobe do comeco enquanto ele cai, e o rabo baixinho fica para tras. A passagem de DJ (a troca no fim do
        # corpo, a introducao por baixo) e so a do plano no tempo: no fade, a introducao por baixo juntava dois
        # andamentos e o corte no drop soou estranho (GigaChad 64 BPM -> Close Eyes 88,5, pedido dele, 06/11)
        sobrepor = min(caindo, TRANS_MAX_S)
        virar = baixo - sobrepor
    if not fade or virar < pos:
        # final seco (ou a medicao chegou depois do ponto, com a rede lenta): emenda no fim do som,
        # tirando o silencio entre os dois, sem cortar o que ainda esta tocando
        fade = False
        sobrepor, virar = TRANS_SECO_S, fim - TRANS_SECO_S
    return fim, caindo, fade, virar, sobrepor


def razao(pa, pb):
    """A velocidade da proxima para a grade dela (periodo pb) cair na deste (pa): em meia, igual ou dobrada, a mais
    perto de 1."""
    return min((pb / (pa * m) for m in (0.5, 1.0, 2.0)), key=lambda v: abs(np.log(v)))


def velocidade_saida(s):
    """No fade com os andamentos a mais de TEMPO_MAX: a proxima fica em TEMPO_MAX e a que sai anda o resto (sa). None
    se o resto passa de SAI_MAX."""
    sa = (1 + TEMPO_MAX if s > 1 else 1 - TEMPO_MAX) / s
    return None if abs(sa - 1) > SAI_MAX else sa


def rampa_saida(sa, virar):
    """A volta da que sai a velocidade sa: (amostras da rampa, onde ela comeca no disco). A rampa acaba antes do trecho
    onde a fase deste e medida: ali a velocidade ja e constante."""
    n_ra = int(min(max(abs(sa - 1) / RAMPA_TAXA, RAMPA_MIN_S), RAMPA_MAX_S) * SR)
    return n_ra, virar - FASE_ANTES_S - 0.5 - n_ra * (1 + sa) / 2 / SR


def phase_excerpt_start(before_switch, swap):
    return min(before_switch, swap - int(FASE_MIN_S * SR))


def intro_baixa(niv, ini, pa):
    """No final seco: a proxima comeca quase sem som (os primeiros INTRO_SECO_OUVE_S a FIM_DB abaixo do normal dela) e
    so chega ao corpo depois de INTRO_SECO_BATIDAS deste (periodo pa)? Entao ela entra por baixo antes."""
    corpo, comeco = medir_corpo(niv, ini), nivel_trecho(niv, ini, ini + INTRO_SECO_OUVE_S)
    return (corpo is not None and corpo - ini >= INTRO_SECO_BATIDAS * pa
            and comeco is not None and comeco < -FIM_DB)


def entrada_dj(niv, ini, pa, pb, s, b_longa):
    """Quantas batidas deste (nb) a proxima entra antes da troca, e de onde dela: (nb, comeco, drop), com o drop so
    quando ela comeca dentro da introducao. So a que comeca quase sem som (INTRO_SECO_OUVE_S a FIM_DB abaixo do normal
    dela) entra por baixo antes; a que se ouve desde o comeco entra na troca (nb = 0). A que entra por baixo leva o
    bastante para o drop dela (medir_corpo, numa batida dela, b_longa e o periodo pb) cair na troca, em degraus de 4, de
    DJ_MIN_BATIDAS a DJ_MAX_BATIDAS e ate DJ_MAX_S; com a introducao maior, ela comeca dentro dela, um numero inteiro de
    compassos antes do drop. Sem o corpo medido, DJ_BATIDAS desde o comeco dela. s e a velocidade dela na
    sobreposicao."""
    teto = DJ_MAX_BATIDAS
    while teto > DJ_MIN_BATIDAS and teto * pa > DJ_MAX_S:
        teto -= 4
    comeco_db = nivel_trecho(niv, ini, ini + INTRO_SECO_OUVE_S)
    if comeco_db is None or comeco_db >= -FIM_DB:
        # o comeco dela se ouve: nada dela por baixo da que sai, que seria voz sobre voz (o funk tocava 22 s junto,
        # pedido dele, 06/11). Ela entra na troca, cheia em meia batida, e a que sai some por baixo dela
        return 0, ini, None
    corpo = medir_corpo(niv, ini)
    if corpo is None:
        return min(DJ_BATIDAS, teto), ini, None
    corpo = b_longa + round((corpo - b_longa) / pb) * pb   # o drop numa batida dela
    nb = int(round((corpo - ini) / (s * pa) / 4)) * 4      # a introducao, em compassos deste
    nb = max(DJ_MIN_BATIDAS, min(teto, nb))
    comeco = corpo - nb * pa * s
    if comeco < ini - 1e-6:   # introducao curta: ela entra do comeco (o drop chega antes da troca)
        return nb, ini, None
    return nb, comeco, corpo


def batida_do_fim(a0, pa, tau, fim, baixo):
    """No final seco no tempo: o k da batida deste (a0 + k * pa) em que a primeira da proxima (tau depois do comeco
    dela) cai. A batida dele logo depois do fim do som (onde a passagem de volume viraria), e a proxima nunca
    entra mais de FIM_CORTE_S antes desse fim: o que a passagem de volume toca, a no tempo nao corta
    (o Bota Tudo Em Mim tem 2 s de silencio e 18 s baixinhos depois da musica; o plano mirava a queda
    de 20 dB e cortava os 20 s)."""
    fim_o = baixo if baixo is not None and fim - baixo <= RABO_SECO_S else fim   # o rabo curto fica para tras
    k = int(np.ceil((fim_o - TRANS_SECO_S - a0) / pa))
    while a0 + k * pa - tau < fim_o - FIM_CORTE_S:
        k += 1
    return k


def na_grade(a0, periodo, alvo, tau):
    """O comeco da proxima para a primeira batida dela, tau depois desse comeco, cair na batida da grade (a0, periodo)
    mais perto de alvo + tau. Os quatro em segundos do disco, ou todos em amostras da saida."""
    return a0 + round((alvo + tau - a0) / periodo) * periodo - tau


def troca_grave(a0, periodo, troca, t0, pad, sr=SR):
    """A troca de grave na batida da grade (a0, periodo) mais perto da troca, em meia batida: (tm, w0, w1), com w0 e w1
    em amostras da proxima desde t0, que leva pad de silencio na frente. Os tempos em segundos (sr = SR) ou ja em
    amostras (sr = 1)."""
    tm = a0 + round((troca - a0) / periodo) * periodo
    w0 = max(pad, pad + int((tm - t0 - periodo / 4) * sr))
    w1 = w0 + int(periodo / 2 * sr)
    return tm, w0, w1


def virada(inicios, fim_arq, t0):
    """O comeco do bloco deste (inicios, os comecos dos blocos na fila; fim_arq, onde o arquivo acaba) em que t0 cai,
    quantos blocos de silencio faltam depois do arquivo e quantas amostras de silencio a proxima leva na frente para
    comecar exatamente em t0 (None se t0 ja passou ou esta perto demais)."""
    if t0 < inicios[0] + FOLGA_S:
        return None, 0, 0
    if t0 >= fim_arq:
        k = int((t0 - fim_arq) * SR // BLOCK)
        v = fim_arq + k * BLOCK / SR
        return v, k, int(round((t0 - v) * SR))
    v = float(inicios[max(0, np.searchsorted(inicios, t0, side="right") - 1)])
    return v, 0, int(round((t0 - v) * SR))
