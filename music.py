"""Pure functions about music titles, artists and YouTube ids: no state, no lock, no network. The server and the
Automatico (automatico.py) both use them: whether two videos are the same song (chaves_musica), who sings it
(autores), whether a YouTube Music track is the audio version of a video (mesma_faixa), the search for that version
(busca_de), a "3:06" duration in seconds (segundos) and a video's thumbnail (thumb)."""
import re
import unicodedata

YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def thumb(yid):
    return f"https://i.ytimg.com/vi/{yid}/mqdefault.jpg" if yid else None


# o que nao conta para saber se dois videos sao a mesma musica: o que vem entre parenteses e colchetes, o
# participante (do "ft" em diante) e as palavras de video ("Shape of You (Lyrics)" e "(Official Music Video)")
MESMA_CORTA = {"ft", "feat", "featuring", "prod"}
MESMA_FORA = {"official", "oficial", "video", "videoclipe", "music", "musica", "audio", "lyrics", "lyric", "letra",
              "clipe", "clip", "hd", "4k", "visualizer", "mv", "x", "e", "y", "and"}


def musica(titulo):
    """A mesma musica em outro video vira a mesma chave (o Mix traz o clipe e a versao com letra, e na ordem por
    andamento as duas cairiam em seguida)."""
    t = re.sub(r"[(\[【][^)\]】]*[)\]】]", " ", sem_acento(titulo))
    out = []
    for parte in re.split(r"\s[-‒–—|]\s|\|", t):  # o "ft" corta so ate o separador (artista - titulo)
        for w in re.findall(r"\w+", parte):
            if w in MESMA_CORTA:
                break
            if w not in MESMA_FORA:
                out.append(w)
    out = set(out)
    return " ".join(sorted(out)) if len(out) >= 2 else ""  # chave de uma palavra so juntaria musicas diferentes


def chaves_musica(x):
    """As chaves de musica de um disco ou parecida: pelo titulo e, com o artista em separado (o radio do YouTube
    Music da "S91" e "KAROL G"; o video da "KAROL G - S91 (Official Video)"), pelo artista e titulo juntos."""
    ks = {musica(x.get("title")), x.get("musica") or ""}
    if x.get("channel"):
        ks.add(musica(f"{x['channel']} - {x.get('title') or ''}"))
    return ks - {""}


# o que separa os artistas de um nome ("Snoop Dogg, Wiz Khalifa", "Shakira & Bizarrap", "MC X e MC Y", "A x B", o ft)
AUTORES_SEP = r",|&|\+|/|\s(?:x|e|y|and|feat\.?|ft\.?|featuring|with|part\.?)\s"


def autores(x):
    """Os artistas do disco, cada um so com letras e numeros ("Mary J. Blige" e o canal "MaryJBligeVEVO" dao
    "maryjblige"), para a ordem por andamento nao por duas do mesmo em seguida: o channel (os artistas no radio do
    YouTube Music, o canal no Mix do YouTube e na prateleira), o que vem antes do " - " no titulo e quem participa
    (o "feat. Mary J. Blige" do The Message: a mesma voz). No video de alguem (UGC) o canal e de quem subiu (o
    7clouds de letra), entao so o titulo."""
    nomes = [] if x.get("tipo") == "UGC" else [x.get("channel") or ""]
    titulo = sem_acento(x.get("title"))
    partes = re.split(r"\s[-‒–—]\s", titulo, maxsplit=1)
    if len(partes) == 2:
        nomes.append(partes[0])
    nomes += re.findall(r"[(\[](?:feat\.?|ft\.?|featuring|with)\s+([^)\]]+)", titulo)
    nomes += re.findall(r"\s(?:feat\.|ft\.|featuring)\s+([^(\[]+)", titulo)
    out = set()
    for nome in nomes:
        nome = re.sub(r"\s-\stopic$", "", sem_acento(nome).strip())
        for a in re.split(AUTORES_SEP, re.sub(r"[(\[].*?[)\]]", " ", nome)):
            a = re.sub(r"vevo$", "", re.sub(r"[^a-z0-9]", "", a))
            if len(a) >= 2:
                out.add(a)
    return frozenset(out)


def sem_acento(t):
    """O texto em minusculas e sem acento ("Échame" e "Echame" sao o mesmo titulo)."""
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def palavras(t):
    """As palavras que contam de um titulo ou nome, para achar a mesma faixa: o que vem entre parenteses vira uma
    parte (o "Remix" de "Calma (Remix)" fica; "(Official Video)" sai pelas palavras de video), o "ft" corta so a
    parte dele."""
    t = re.sub(r"[(\[【)\]】]", " | ", sem_acento(t))
    out = set()
    for parte in re.split(r"\s[-‒–—|]\s|\|", t):
        for w in re.findall(r"\w+", parte):
            if w in MESMA_CORTA:
                break
            if w not in MESMA_FORA:
                out.add(w)
    return out


def mesma_faixa(c, r):
    """A faixa r da busca de musicas do YouTube Music e a parecida c (que veio como video)? O titulo da faixa esta
    inteiro no da parecida, o que sobra la e nome de artista (o video com letra traz "Ed Sheeran - Shape Of You"),
    um artista bate e a duracao cabe (o clipe tem intro e final a mais; a faixa nunca e bem mais longa). A primeira
    da busca as vezes e outra (o Bota Tudo Em Mim trazia outra musica, de outros MCs) ou o remix."""
    ra = palavras(", ".join(a["name"] for a in r.get("artists") or []))
    rt, ct, cc = palavras(r.get("title")), palavras(c.get("title")), palavras(c.get("channel"))
    d, dc = r.get("duration_seconds") or segundos(r.get("duration")), c.get("duration") or 0
    return bool(rt and rt <= ct and (ct - rt) <= (ra | cc) and (ra & (ct | cc)) and d and dc - 150 <= d <= dc + 20)


def find_track(item, search):
    return next((r for r in search(busca_de(item))
                 if r.get("videoId") and YT_ID.match(r["videoId"]) and mesma_faixa(item, r)), None)


def track_artists(track):
    return ", ".join(a["name"] for a in track.get("artists") or [] if a.get("name"))


def busca_de(x):
    """O texto da busca da versao de audio da parecida: o titulo sem os parenteses so de video ("[Official Video]";
    o "(Remix)" fica) e, no clipe oficial, os artistas na frente quando o titulo nao os traz (no video com letra o
    canal e de quem subiu, nao do artista)."""
    t = re.sub(r"[(\[【]([^)\]】]*)[)\]】]", lambda m: m.group(0) if palavras(m.group(1)) else " ",
               x.get("title") or "")
    if x.get("tipo") != "UGC" and x.get("channel") and not palavras(x["channel"]) <= palavras(t):
        t = f"{x['channel']} {t}"
    return " ".join(t.split())


def segundos(txt):
    """'3:06' ou '1:02:03' em segundos (None se nao der)."""
    try:
        s = 0
        for p in str(txt).split(":"):
            s = s * 60 + int(p)
        return s
    except ValueError:
        return None
