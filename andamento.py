"""O andamento do comeco e do fim de um disco e a ordem das parecidas do Automatico por ele (a
radio que sobe de andamento em circulo, para quase toda passagem cair no tempo).

A medida le so 25 s do comeco e 45 s do fim (do arquivo, ou direto do stream do YouTube, ~1 MB por disco, sem
baixar nada: baixar 1 h de musica a cada disco que troca e demais), acha o som e a queda do fade como o
motor (medir_inicio, medir_fim) e mede a batida nos mesmos 20 s que a passagem mede: o batida.py e, sem batida
firme, a rede. O stream e o mesmo que toca (~130 kbps): no formato leve (~50 kbps) a intro de ukulele da Riptide dava
98,1 firme, e no que toca o motor nao firmava, e a fila tinha posto ela no lugar de uma passagem no tempo (22/10).
Roda num processo a parte (python andamento.py, o pedido em JSON na entrada): a rede pesa ~800 MB e uns segundos
de processador, e o audio do servidor nao divide nada com ela.

A ordem anda no circulo das oitavas (60 e 120 BPM no mesmo lugar: a passagem casa em meia ou dobrada), sempre
subindo: a proxima e a que fica menos acima do fim da anterior. Quando nenhuma cabe no alcance da passagem (o
ALCANCE, ~7%), uma um pouco abaixo serve; senao a passagem vai ser so de volume de qualquer jeito, e esse salto fica
para a que nao tem andamento conhecido, ou para a mais baixa do resto (a volta do circulo)."""
import json
import math
import subprocess
import sys

import numpy as np

import batida
import engine as eng

INI_LE_S = 25.0  # do comeco: o som e os BATIDA_S depois dele
FIM_LE_S = 45.0  # do fim: a queda do fade, os BATIDA_S antes dela e o nivel normal do fim em volta
# a maior diferenca que a passagem alinha: a proxima estica ate TEMPO_MAX e a que sai anda ate SAI_MAX (em oitavas)
ALCANCE = math.log2((1 + eng.TEMPO_MAX) * (1 + eng.SAI_MAX))


def le(fonte, hdr, de, dur):
    """dur segundos de audio a partir de de, do arquivo ou do stream (com os cabecalhos que o yt-dlp mandou)."""
    a = ["-headers", hdr] if hdr else []
    ff = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *a, "-ss", f"{de:.3f}", "-i", fonte, "-t", f"{dur:.3f}",
                         "-f", "f32le", "-ac", "2", "-ar", str(eng.SR), "-"],
                        capture_output=True, timeout=90, creationflags=eng.NO_WINDOW, startupinfo=eng.sem_cursor())
    return np.frombuffer(ff.stdout[: len(ff.stdout) // 8 * 8], np.float32).reshape(-1, 2)


def niveis(x, t0):
    """O nivel de cada bloco, como o leitor do motor guarda: (t, amostras, rms)."""
    n = len(x) // eng.BLOCK
    r = np.sqrt(np.mean(x[:n * eng.BLOCK].reshape(n, eng.BLOCK, 2) ** 2, axis=(1, 2)))
    return [(t0 + i * eng.BLOCK / eng.SR, eng.BLOCK, float(v)) for i, v in enumerate(r)]


def bpm(x):
    """O andamento do trecho, ou None sem batida firme nem pelo batida.py nem pela rede."""
    if len(x) < eng.BATIDA_MIN_S * eng.SR:
        return None
    g = batida.medir(x, eng.SR)
    if not g.firme:
        g = eng._grade_rede(x)
    return round(float(g.bpm), 2) if g is not None and g.firme else None


def mede(fonte, dur, hdr=""):
    """{"ini": BPM do comeco, "fim": BPM do fim}, None no lado sem batida firme."""
    sr, n = eng.SR, int(eng.BATIDA_S * eng.SR)
    x = le(fonte, hdr, 0.0, INI_LE_S)
    i = int(eng.medir_inicio(niveis(x, 0.0)) * sr)
    ini = bpm(x[i:i + n])
    de = max(0.0, dur - FIM_LE_S)
    y = le(fonte, hdr, de, dur - de + 2.0)  # a duracao do YouTube vem em segundos inteiros
    fim, queda, baixo = eng.medir_fim(niveis(y, de))
    fim_bpm = None
    if fim is not None:
        # a batida antes do fade, como a passagem mede pela rede (com ele junto as batidas que somem puxam o andamento)
        fade = queda is not None and baixo is not None and baixo - queda >= eng.FADE_MIN_S
        j = int(((queda if fade else fim) - de) * sr)
        fim_bpm = bpm(y[max(0, j - n):j])
    return {"ini": ini, "fim": fim_bpm}


def subida(de, para):
    """Quanto para fica acima de de no circulo das oitavas, subindo (de 0 a 1 oitava)."""
    return (math.log2(para) - math.log2(de)) % 1.0


MESMO_AUTOR = 10.0  # acima de todo custo de andamento: a do mesmo artista da anterior so entra sem outra


def ordena(cursor, salto, cands, tempo, n, autores=lambda c: frozenset(), antes=frozenset()):
    """As n primeiras de cands (na ordem do Mix: a mais parecida com a semente primeiro) na ordem de tocar.
    cursor: o andamento do fim do disco antes delas (None sem medida); salto: a passagem para a primeira ja vai ser
    so de volume (o fim dele sem batida firme); tempo(c): {"ini", "fim"} medidos, ou None ainda sem medida.
    Sem cursor, fica a ordem do Mix (a medida chega e o servidor ordena de novo). Duas do mesmo artista nunca em
    seguida enquanto houver outra: autores(c) sao os artistas de
    cada uma e antes os do disco antes delas."""
    resto, saida, ultimos = list(cands), [], set(antes)
    while resto and len(saida) < n:
        def andamento(c):
            t = tempo(c)
            b = t.get("ini") if t else None
            if b is None or cursor is None:
                return 2.0  # sem andamento: fica com o salto (empate: a ordem do Mix)
            u = subida(cursor, b)
            if salto:
                return 3.0 + u  # o salto e de volume de qualquer jeito: a que casaria fica para depois
            if u <= ALCANCE:
                return u  # sobe pouco: no tempo
            if 1.0 - u <= ALCANCE:
                return 1.0 + (1.0 - u)  # um pouco abaixo: no tempo tambem, mas so sem uma acima
            return 3.0 + u  # a volta do circulo: a mais baixa do resto
        c = min(resto, key=lambda c: andamento(c) + (MESMO_AUTOR if autores(c) & ultimos else 0.0))
        resto.remove(c)
        saida.append(c)
        ultimos = set(autores(c))
        t = tempo(c)
        if t:
            cursor = t.get("fim") or t.get("ini") or cursor
            salto = t.get("fim") is None
    return saida


if __name__ == "__main__":
    p = json.loads(sys.stdin.read())
    try:
        fonte, hdr, dur = p.get("fonte"), p.get("hdr") or "", p.get("dur")
        if p.get("yt"):
            # o endereco do stream sai aqui mesmo, e nao no servidor (ver o yt_fora.py): eram 15 parecidas medidas
            # durante a primeira musica do radio (22/10)
            from yt_fora import stream_yt
            info, hdr = stream_yt(p["yt"], p["opts"])
            fonte, dur = info["url"], dur or info.get("duration")
        print(json.dumps(mede(fonte, float(dur), hdr) if dur else None))
    except Exception as ex:  # noqa: BLE001 - o servidor poe o motivo no log
        print(json.dumps({"erro": str(ex) or type(ex).__name__}))
    finally:
        import compasso
        compasso.fecha()
