"""Confere se a passagem no tempo do motor (engine.py) pos bumbo em cima de bumbo (e nao no contratempo), com
um detector de bumbo proprio, independente do pente do motor: o grave abaixo de 120 Hz, o nivel dele em janelas
de 5 ms, cada subida de 9 dB em 25 ms perto do nivel forte do trecho e um bumbo. A linha de bumbo de uma musica
e a fase, no periodo da batida dela, em que mais bumbos caem (o bumbo do rap e sincopado: um bumbo solto no
contratempo nao muda a linha). Bumbo forte nos dois meios tempos so gera aviso: a linha vale (o Overdose tem
10 x 8 e no meio tempo errado se ouviu o contratempo, 21/10). Mas o aviso e para valer: no Stay With Me -> NWA o
teste deu CONTRATEMPO (+272 ms, a NWA com 17 x 12) e o ouvido confirmou (21/10): na intro falada da NWA o bumbo
que mais cai e o do contratempo, e a linha dela sai ali.

Roda o motor sem aparelho de som, do fim de A ao comeco de B (como o servidor): depois que o plano entra, guarda
e cala o que sai (da virada em diante); a que sai sozinha e a saida antes da virada mais o que foi guardado, e o
motor diz, bloco a bloco, que ponto do arquivo da que entra esta tocando (a posicao). A linha de bumbo da que sai vem dos 12 s antes da virada e da
sobreposicao, na saida; a da que entra vem de 20 s do arquivo dela, desde o comeco do som, e vai para a saida
pela posicao (com o esticamento e a virada do motor no meio, que e o que se confere).
  - fade-out no tempo: as linhas de bumbo da que entra que caem na sobreposicao, contra a da que sai;
  - final seco no tempo: a primeira linha de bumbo da que entra, contra a da que sai estendida. Com o comeco
    dela quase sem bumbo (intro sem bateria, como o piano do Lose Yourself), vale o que o motor poe na batida: a
    primeira batida da grade do batida.py quando ela e firme (a mesma regua do motor, porque sem bumbo nao ha
    regua independente), senao a primeira nota dela. A grade de bumbo de mais adiante na musica nao serve: a
    musica pode mudar de andamento (o Lose Yourself vai de 65 BPM no piano a 86 quando entra a guitarra, aos
    31 s), e mesmo sem mudar, estendida ate a intro, ela caia fora dos ataques dela em 9 musicas (21/10).
Veredito (e saida): NO TEMPO (0, bumbo no bumbo), CONTRATEMPO ou FORA (1), SEM PLANO (a passagem foi so de
volume) ou SEM BUMBO (pouco bumbo para julgar) (3). O teste que pegou o contratempo do Overdose (21/10): com o
codigo de antes da correcao (--codigo numa pasta com o engine.py e o batida.py do commit c8930a5a e o fx.py), os
tres pares com bumbo dao CONTRATEMPO; com o de hoje, NO TEMPO.

    python dev/bumbo.py <arquivo A> <arquivo B> [--codigo <pasta com engine.py e batida.py>]

Os arquivos sao os da prateleira (library/), pelo nome (ex. xQAuZnie2G0.webm H08YWE4CIFQ.webm)."""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy import signal

SB = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
codigo = SB
if "--codigo" in args:
    i = args.index("--codigo")
    codigo = Path(args[i + 1])
    del args[i:i + 2]
sys.path.insert(0, str(codigo))
import batida  # noqa: E402
import engine as eng  # noqa: E402

SR = eng.SR
LIB = SB / "library"
lib = {x["file"]: x for x in json.load(open(LIB / "library.json", encoding="utf-8"))}
TOL = 0.040        # bumbo ate 40 ms da linha conta como em cima dela
LP = signal.butter(4, 120, "lowpass", fs=SR, output="sos")


def faixa(arq):
    return dict(lib[arq], path=str(LIB / arq))


def arquivo(track, ini, dur):
    ff = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ini), "-t", str(dur), "-i", track["path"], "-f", "f32le",
                         "-ac", "1", "-ar", str(SR), "-"], capture_output=True)
    return np.frombuffer(ff.stdout[: len(ff.stdout) // 4 * 4], np.float32)


def bumbos(x):
    """Os bumbos de x (mono), em s desde o comeco de x."""
    g = signal.sosfiltfilt(LP, x)
    e = np.sqrt(np.convolve(g * g, np.ones(240) / 240, mode="same"))[::48]  # 1 valor por ms
    db = 20 * np.log10(e + 1e-6)
    sobe = np.full_like(db, -99.0)
    sobe[25:] = db[25:] - db[:-25]
    forte = np.percentile(db, 95)
    cand = np.nonzero((sobe > 9) & (db > forte - 18))[0]
    picos = []
    for i in cand:
        if picos and i - picos[-1][-1] <= 150:
            picos[-1].append(i)
        else:
            picos.append([i])
    # o bumbo vale onde o grave comeca a subir (3 dB acima do vale de antes), nao no meio da subida: o bumbo
    # grave e comprido sobe por dezenas de ms (o do Otonoke marcava 58 ms depois do ataque e reprovava a
    # primeira nota do Lose Yourself, que caiu certa)
    ts = []
    for g in map(np.array, picos):
        i = int(g[int(np.argmax(sobe[g]))])
        j0 = max(0, i - 60)
        vale = j0 + int(np.argmin(db[j0:i]))
        acima = np.nonzero(db[vale:i + 1] > db[vale] + 3)[0]
        ts.append(vale + (acima[0] if len(acima) else i - vale))
    return np.array(ts) / 1000.0


def desvio(ts, f, p):
    """O desvio de cada t ate a linha mais perto da grade (fase f, periodo p), de -p/2 a p/2."""
    return (ts - f + p / 2) % p - p / 2


def grade(ts, p):
    """A linha de bumbo (fase em s) no periodo p: a fase, entre as dos proprios bumbos, com mais bumbos a ate
    TOL dela (afinada pela media deles); e quantos caem nela e no meio tempo dela."""
    cont = [int((np.abs(desvio(ts, t, p)) < TOL).sum()) for t in ts]
    t = ts[int(np.argmax(cont))]
    d = desvio(ts, t, p)
    f = (t + d[np.abs(d) < TOL].mean()) % p
    d = desvio(ts, f, p)
    return f, int((np.abs(d) < TOL).sum()), int((np.abs(np.abs(d) - p / 2) < TOL).sum())


A, B = faixa(args[0]), faixa(args[1])
e = eng.Engine("x", "y", "")
e.active = {"mic": "x", "out": "y", "monitor": ""}
e.vol = 1.0
e.load(A, start=max(0.0, A["duration"] - 55))
buf = np.zeros((eng.BLOCK, 2), np.float32)
saida, preparado, virou_em, guardado, a_depois, mapa = [], False, None, False, [], []
while True:
    for _ in range(30000):  # ate 60 s: o plano no tempo com a volta lenta leva uns 9 s, e a vitrola espera
        tem = e._q or e._eof_gen == e._gen
        medindo = e._pronto is not None and e._virar_em is None
        if tem and not medindo:
            break
        time.sleep(0.002)
    if not preparado and e.track is A and A["duration"] - e.pos <= eng.TRANS_PREP_S:
        e.preparar(B, "teste")
        preparado = True
    if e._virar_em is not None and not guardado:
        with e._qlock:
            v = e._virar_em + eng.BLOCK / (2 * SR)
            for i, (t, a) in enumerate(list(e._deck.q)):
                if t >= v - 1e-6:
                    a_depois.append(a.copy())
                    e._deck.q[i] = (t, np.zeros_like(a))
        guardado = True
        sob, entra, troca_grave = e._sobrepor, e._entrar, e._grave
    e._out_cb(buf, eng.BLOCK, None, None)
    saida.append(buf.copy())
    if e.virou is not None and virou_em is None:
        virou_em = len(saida) * eng.BLOCK - eng.BLOCK
    if virou_em is not None:
        mapa.append((len(saida) * eng.BLOCK, e.pos))  # a amostra da saida e o ponto do arquivo da que entra
    if virou_em is not None and len(saida) * eng.BLOCK - virou_em >= 22 * SR:
        break
x = np.concatenate(saida).mean(axis=1)
so_a = np.concatenate([x[:virou_em], np.concatenate(a_depois).mean(axis=1)]) if a_depois else x[:virou_em]
v = virou_em / SR  # a virada, em s da saida

if troca_grave is not None:
    jeito = "fade-out no tempo"
elif entra <= 0.05 * SR + eng.BLOCK:
    jeito = "final seco no tempo"
else:
    print("VEREDITO: SEM PLANO (a passagem foi so de volume)")
    sys.exit(3)

# a que sai, na saida: a linha de bumbo nos 12 s antes da virada e na sobreposicao
ga = batida.medir(so_a[virou_em - 20 * SR:virou_em], SR)
fim_a = v + (sob / SR if jeito.startswith("fade") else 0.0)
antes_s = 12
pa = ga.periodo
# a batida da que sai na saida pelo plano do motor (a regua dele; a linha continua saindo dos bumbos): na passagem
# dos dois lados a que sai muda de andamento ate 4,5 s antes da virada, e os 20 s antes dela mediam a rampa (a Boa
# Sorte deu 74,3 em vez de 111,9); a linha sai entao do trecho de andamento constante
if e.periodo_saida is not None:
    if abs(e.periodo_saida / ga.periodo - 1) > 0.002 and jeito.startswith("fade"):
        antes_s = 4
    pa = e.periodo_saida
ka = bumbos(so_a[virou_em - antes_s * SR:int(fim_a * SR)]) + v - antes_s
fa, na, na_meio = grade(ka, pa)
dois = na_meio >= 0.5 * na
print(f"{jeito}; a que sai: {ga.bpm:.1f} BPM, {len(ka)} bumbos, {na} na linha e {na_meio} no meio tempo"
      + (" (bumbo forte nos dois meios tempos)" if dois else ""))
if na < 4:
    print("VEREDITO: SEM BUMBO (a que sai tem pouco bumbo para fazer a linha)")
    sys.exit(3)

# a que entra, no arquivo dela: a linha de bumbo nos 20 s desde o comeco do som
cab = arquivo(B, 0.0, 25.0)
som = np.nonzero(np.abs(cab) > 10 ** (-48 / 20))[0]
ini = som[0] / SR if len(som) else 0.0
xb = cab[int(ini * SR):int((ini + 20) * SR)]
gb = batida.medir(xb, SR)
if not gb.firme:  # a regua do motor quando o batida.py nao firma: a rede (a primeira batida no comeco do som, se ali)
    gr = eng._grade_rede(xb)
    if gr is not None:
        gb = gr._replace(fase=gr.fase - gr.periodo if gr.fase - gr.periodo >= -0.06 else gr.fase)
pb = gb.periodo
kb = bumbos(xb) + ini
fb, nb, nb_meio = grade(kb, pb) if len(kb) else (0.0, 0, 0)
dois_b = nb_meio >= 0.5 * nb > 0
print(f"a que entra: {gb.bpm:.1f} BPM, {len(kb)} bumbos em 20 s do arquivo, {nb} na linha e {nb_meio} no meio tempo"
      + (" (bumbo forte nos dois meios tempos)" if dois_b else ""))
# sem linha de bumbo no comeco, ou sem andamento firme para tracar a linha (o comeco do Macetada da 86,5, o 4/3
# do funk de 130): no final seco vale o que o motor pos na batida, a grade firme ou a primeira nota
nota = nb < 4 or not gb.firme
if nota and jeito.startswith("fade"):
    print("VEREDITO: SEM BUMBO (a que entra tem pouco bumbo ou andamento sem firmeza para fazer a linha)")
    sys.exit(3)
amostra, pos = np.array([m[0] for m in mapa], float), np.array([m[1] for m in mapa])
inc = (amostra[1] - amostra[0]) / (pos[1] - pos[0])  # antes do primeiro ponto, na inclinacao do primeiro bloco


def na_saida(tau):
    """O ponto tau do arquivo da que entra, em s da saida (pela posicao que o motor deu a cada bloco)."""
    s = np.where(tau < pos[0], amostra[0] + (tau - pos[0]) * inc, np.interp(tau, pos, amostra))
    return s / SR


linhas = fb + np.arange(np.ceil((ini - TOL - fb) / pb), np.ceil((ini + 12 - fb) / pb)) * pb
o_que = "bumbo"
if nota and gb.firme:
    linhas_t = na_saida(np.array([ini + gb.fase]))
    regua = "da rede" if gb.motivo.startswith("pela rede") else "do batida.py"
    quem = f"a primeira batida dela pela grade {regua} ({gb.bpm:.1f} BPM; o comeco dela quase sem bumbo)"
    o_que = "a primeira batida"
elif nota:
    linhas_t = na_saida(np.array([ini]))
    quem, o_que = "a primeira nota dela (o comeco dela sem batida firme)", "a primeira nota"
elif jeito.startswith("fade"):
    t_saida = na_saida(linhas)
    linhas_t = t_saida[(t_saida >= v) & (t_saida <= v + sob / SR)]
    quem = f"as {len(linhas_t)} linhas de bumbo dela na sobreposicao de {sob / SR:.1f} s"
else:
    linhas_t = na_saida(linhas[:1])
    quem = f"a primeira linha de bumbo dela ({(linhas[0] - ini) * 1000:.0f} ms depois do comeco do som)"
d = desvio(linhas_t, fa, pa)
print(f"{quem}: a " + " ".join(f"{x * 1000:+.0f}" for x in d) + " ms da linha de bumbo da que sai")
if not len(d):
    veredito = "SEM BUMBO (nenhuma linha de bumbo dela na sobreposicao)"
else:
    dm = float(np.median(d))
    if abs(dm) < TOL:
        veredito = f"NO TEMPO ({o_que} no bumbo, {dm * 1000:+.0f} ms)"
    elif abs(abs(dm) - pa / 2) < TOL:
        veredito = f"CONTRATEMPO ({o_que} dela no meio tempo da que sai, {dm * 1000:+.0f} ms)"
    else:
        veredito = f"FORA ({o_que} a {dm * 1000:+.0f} ms da linha de bumbo da que sai)"
    if dois or dois_b:  # quase empate entre os meios tempos: a linha vale, mas o ouvido confirma
        veredito += "; aviso: bumbo forte nos dois meios tempos, conferir de ouvido"
print("VEREDITO:", veredito)
sys.exit(0 if veredito.startswith("NO TEMPO") else 3 if veredito.startswith("SEM") else 1)
