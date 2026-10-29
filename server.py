"""Soundboard do VRChat: servidor local que toca audio no microfone do jogo pelo VB-Cable e
serve as interfaces de themes/. Contrato da API: API.md. Atende a propria maquina e o celular
na rede de casa (para mexer enquanto joga).

    python server.py [--port 8799] [--no-browser] [--so-local]
    python server.py --mock --port 8801 --data-dir <pasta>   (sem som, pra testar tema)
"""
import argparse
import asyncio
import importlib
import json
import random
import re
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from aiohttp import web
from aiohttp.web_runner import GracefulExit

import andamento as an
import engine as eng
import fx
import pastas
from versao import VERSAO

HERE = Path(__file__).resolve().parent
LIB = pastas.LIB  # audio baixado; library.json e config.json moram em --data-dir
THEMES = HERE / "themes"
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_URL = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")
TICK = 1 / 15
ESCUTA_S = 30.0  # tocando de fato esse tempo (ou 80% do disco, se for mais curto), conta uma escuta
BUSCA_MAX = 200  # o carregar mais da busca vai ate aqui
# o YouTube so libera todos os formatos com um runtime de JavaScript (pacote yt-dlp-ejs); o
# yt-dlp procura so o Deno por padrao, e aqui o que tem e o Node (sem nenhum, alguns formatos
# faltavam e o stream falhava de vez em quando; 18/10)
YDL = {"quiet": True, "no_warnings": True, "js_runtimes": {"deno": {}, "node": {}}}
# o deno e o ffmpeg que vem com o app (bin/): quem instala nao tem nenhum dos dois no PATH
if deno := pastas.ferramenta("deno"):
    YDL["js_runtimes"]["deno"]["path"] = deno
if ffmpeg := pastas.ferramenta("ffmpeg"):
    YDL["ffmpeg_location"] = ffmpeg
ANTERIOR_REINICIA_S = 3.0  # depois disso o Anterior volta ao comeco do disco, como no Spotify
HISTORICO_MAX = 50
AUTO_FILA = 5  # o Automatico mantem tantas parecidas no fim do A seguir
AUTO_LOTE = 50  # quantas parecidas cada busca traz (o radio do YouTube Music da 50 em ~1 s, 21/10)
AUTO_DUR = (60, 600)  # fora disso nao entra: vinheta, compilado de 1 h, live sem fim
AUTO_ESPERA_S = 60.0  # busca de parecidas que falhou so tenta de novo depois disso
AUTO_JANELA_S = 3600  # a ordem por andamento escolhe entre as parecidas da proxima 1 h da lista
ANDAMENTO_APOS_S = 30.0  # o disco fica isso no prato antes de medir: pular de disco em disco nao le nada
ANDAMENTO_ESPERA_S = 600.0  # medida que falhou (stream fora do ar) so tenta de novo depois disso
ABAIXO_DO_NORMAL = 0x00004000  # prioridade do processo da medida no Windows: cede o processador ao audio

pool = ThreadPoolExecutor(4)
FORA_LIMITE_S = 120.0  # pedido ao YouTube (fora o download) que nao volta nisso morre: o disco nao fica esperando
REDE_VIGIA_S = 3.0  # a porta do celular se confere a cada isso, e se caiu (o PC dormiu) abre de novo


def auxiliar(modo):
    """O comando de um processo auxiliar (--yt, --andamento; ver o vitrola.py): no app congelado, o proprio
    executavel; no codigo, o mesmo caminho pelo python."""
    if getattr(sys, "frozen", False):
        return [sys.executable, modo]
    return [sys.executable, str(HERE / "vitrola.py"), modo]


class Fora:
    """O YouTube pelo yt_fora.py (auxiliar --yt), num processo a parte (o audio estalava com o yt-dlp aqui dentro): um
    processo fica aberto de reserva, com as bibliotecas ja carregadas; cada pedido leva o de reserva e abre o
    proximo, e pedidos ao mesmo tempo nao esperam um pelo outro."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reserva = None

    @staticmethod
    def _abre():
        # sem o cursor de carregando no mouse; o stderr (os erros do yt-dlp) vem por um cano e vai para o log do
        # servidor: herdar o stderr do servidor falha sem console (pelo pythonw, WinError 50 no DuplicateHandle)
        p = subprocess.Popen(auxiliar("--yt"), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", cwd=str(HERE), creationflags=eng.NO_WINDOW, startupinfo=eng.sem_cursor())
        threading.Thread(target=Fora._repassa, args=(p.stderr,), daemon=True).start()
        return p

    @staticmethod
    def _repassa(cano):
        for linha in cano:
            if sys.stderr:
                print(linha, end="", file=sys.stderr, flush=True)

    def aquece(self):
        """Abre o de reserva, se ainda nao ha um."""
        p = self._abre()
        with self.lock:
            if self.reserva is None or self.reserva.poll() is not None:
                self.reserva, p = p, None
        if p is not None:
            p.stdin.close()  # ja havia um: este sai sem pedido
            p.wait()

    def pede(self, op, progresso=None, limite=FORA_LIMITE_S, **args):
        """O resultado do pedido op (ver o yt_fora.py); progresso(f) recebe o andamento do download. Erro do
        YouTube vira RuntimeError com o motivo."""
        with self.lock:
            p, self.reserva = self.reserva, None
        if p is None or p.poll() is not None:
            p = self._abre()
        threading.Thread(target=self.aquece, daemon=True).start()
        estourou = threading.Event()
        relogio = threading.Timer(limite, lambda: (estourou.set(), p.kill())) if limite else None
        if relogio:
            relogio.start()
        try:
            p.stdin.write(json.dumps({"op": op, **args}))
            p.stdin.close()
            r = None
            for linha in p.stdout:
                try:
                    m = json.loads(linha)
                except ValueError:
                    continue  # linha que nao e do pedido (nao devia vir: o yt-dlp escreve no stderr)
                if not isinstance(m, dict):
                    continue
                if "progresso" in m:
                    if progresso:
                        progresso(m["progresso"])
                else:
                    r = m
            p.wait()
        finally:
            if relogio:
                relogio.cancel()
        if r is None:
            raise RuntimeError("o YouTube não respondeu a tempo" if estourou.is_set() else
                               "o processo do YouTube saiu sem resposta")
        if "erro" in r:
            raise RuntimeError(r["erro"])
        return r["r"]


fora = Fora()


def thumb(yid):
    return f"https://i.ytimg.com/vi/{yid}/mqdefault.jpg" if yid else None


def antes_das_parecidas(fila):
    """Onde entra o que o usuario poe na fila: antes da primeira parecida do Automatico."""
    return next((i for i, x in enumerate(fila) if x.get("auto")), len(fila))


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


def marca_auto(x):
    """As marcas do Automatico, que passam da entrada da fila para o disco do prato e dele para
    o historico: a parecida segue tocando so pelo stream, e tocar ela nao muda a semente."""
    return {"auto": True, "auto_de": x.get("auto_de")} if x.get("auto") else {}


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


class Library:
    def __init__(self, path, keep_files=False):
        LIB.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.keep_files = keep_files
        self.lock = threading.Lock()
        self.items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        self.version = 0

    def _save(self):
        save_json(self.path, self.items)
        self.version += 1

    def get(self, iid):
        return next((x for x in self.items if x["id"] == iid), None)

    def by_youtube(self, yid):
        return next((x for x in self.items if x.get("youtube_id") == yid), None)

    def add(self, item):
        with self.lock:
            self.items = [x for x in self.items if x["id"] != item["id"]] + [item]
            self._save()

    def update(self, iid, **kw):
        with self.lock:
            it = self.get(iid)
            if it:
                it.update(kw)
                self._save()
            return it

    def remove(self, iid):
        """Tira da lista; o arquivo o App apaga (apagar_audio), depois que o motor largar dele."""
        with self.lock:
            it = self.get(iid)
            if not it:
                return None
            self.items.remove(it)
            self._save()
        return it

    def public(self):
        return [dict(x) for x in self.items]


class App:
    def __init__(self, port, data_dir, mock=False):
        self.port = port
        self.mock = mock
        data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg_path = data_dir / "config.json"
        lib_json = data_dir / "library.json"
        if mock and not lib_json.exists() and (LIB / "library.json").exists():
            lib_json.write_text((LIB / "library.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.cfg = (json.loads(self.cfg_path.read_text(encoding="utf-8"))
                    if self.cfg_path.exists() else {})
        self.cfg.pop("lan_token", None)  # a chave do link do celular saiu
        self.lan_ip = None
        self.lib = Library(lib_json, keep_files=mock)
        self.jobs = {}
        self.jobs_version = 0
        self.fila = []  # A seguir: entradas que tocam quando o disco do prato acaba
        self.fila_ordem = None  # Aleatorio ligado: a fila na ordem que o usuario montou, para voltar
        self.historico = []  # discos que sairam do prato, o mais recente no fim (o Anterior)
        self.fila_lock = threading.Lock()
        # Automatico: a semente e o ultimo disco que o usuario escolheu; o mix, o Mix do YouTube ainda
        # nao usado de mix_base (a semente, ou a ultima parecida quando o da semente acaba);
        # fora, o que nao entra (tocou nesta sessao, ou o usuario tirou da fila)
        self.auto = bool(self.cfg.get("auto", False))
        self.semente = None
        self.mix, self.mix_base, self.ponte = None, None, None
        self.mix_buscando, self.mix_falhou = False, 0.0
        self.fora = set()
        self.fora_musica = set()  # a mesma musica do que esta no fora, em outro video
        self.mix_seq = 0  # cada parecida do Mix ganha um numero na ordem em que chegou (a ordem do Mix)
        # o andamento do comeco e do fim de cada disco (andamento.py), medido uma vez so: a ordem das parecidas
        self.andamentos_path = data_dir / "andamentos.json"
        self.andamentos = (json.loads(self.andamentos_path.read_text(encoding="utf-8"))
                           if self.andamentos_path.exists() else {})
        self.andamentos_versao = 0
        self.andamento_falhou = {}
        # a versao so de audio de cada parecida que veio como video (id do video -> a faixa, ou None), procurada uma
        # vez so: toca a faixa do album, que comeca na musica, e nao o clipe com intro
        self.versoes_path = data_dir / "versoes_audio.json"
        self.versoes = (json.loads(self.versoes_path.read_text(encoding="utf-8"))
                        if self.versoes_path.exists() else {})
        self.parado_sem_fila = None  # disco que acabou com a fila vazia: a parecida que chegar toca
        self.preparando = None  # (disco, qid) da passagem sendo preparada (o stream leva 1 a 3 s)
        self.passagem_falhou = None  # (disco, qid) que nao deu para preparar: toca no fim, como antes
        self.closing = False
        cls = eng.MockEngine if mock else eng.Engine
        self.engine = cls(mic=self.cfg.get("mic", "default"), out=self.cfg.get("out", "CABLE Input"),
                          monitor=self.cfg.get("monitor", "default"))
        self.cfg.pop("mic_vol", None)  # o nivel da voz e o do Windows, que guarda sozinho (18/10)
        for k in ("vol", "mon_vol", "monitor_on", "voice_mon_vol"):
            if k in self.cfg:
                v = self.cfg[k]
                setattr(self.engine, k, v if isinstance(v, bool) else max(0.0, min(1.0, float(v))))
        self.engine.liga()
        threading.Thread(target=self._vigia_fila, daemon=True).start()
        threading.Thread(target=self._conta_escuta, daemon=True).start()
        threading.Thread(target=self._vigia_auto, daemon=True).start()
        threading.Thread(target=self._vigia_passagem, daemon=True).start()
        threading.Thread(target=self._vigia_andamento, daemon=True).start()

    def snapshot(self):
        """Estado do motor mais a fila (A seguir), o Aleatorio, o Automatico e quantos discos o
        Anterior tem."""
        with self.fila_lock:
            extra = {"queue": [self._com_bpm(x) for x in self.fila], "shuffle": self.fila_ordem is not None,
                     "auto": self.auto, "history": len(self.historico), "versao": VERSAO}
        return {**self.engine.snapshot(), **extra}

    def _com_bpm(self, x):
        """A entrada da fila para a tela, com o andamento do comeco dela quando ja foi medido."""
        t = self._tempo(x)
        b = t and (t.get("ini") or t.get("fim"))
        return dict(x, bpm=round(b, 1)) if b else dict(x)

    def save_cfg(self):
        e = self.engine
        self.cfg.update(mic=e.devices["mic"], out=e.devices["out"], monitor=e.devices["monitor"],
                        vol=e.vol, mon_vol=e.mon_vol, monitor_on=e.monitor_on,
                        voice_mon_vol=e.voice_mon_vol, auto=self.auto)
        save_json(self.cfg_path, self.cfg)

    # jobs -----------------------------------------------------------------
    def new_job(self, label, play, alvo=None):
        j = {"id": uuid.uuid4().hex[:8], "kind": "download", "label": label, "status": "running",
             "progress": 0.0, "error": None, "item_id": None, "play": play, "alvo": alvo,
             "started": time.time()}
        self.jobs[j["id"]] = j
        self.jobs_version += 1
        return j

    def job_rodando(self, alvo):
        """Download em andamento do mesmo video ou link: tocar ou enfileirar de novo nao baixa
        duas vezes."""
        return next((j for j in self.jobs.values() if j["status"] == "running" and j.get("alvo") == alvo), None)

    def job_update(self, j, **kw):
        j.update(kw)
        self.jobs_version += 1

    def public_jobs(self):
        now = time.time()
        # job terminado some da lista depois de 20 s
        return [j for j in self.jobs.values()
                if j["status"] == "running" or now - j.get("finished", now) < 20]

    # youtube --------------------------------------------------------------
    @staticmethod
    def alvo_yt(target):
        """O que o yt-dlp abre: id de video, link, ou texto (vira a busca do primeiro)."""
        if YT_ID.match(target):
            return f"https://www.youtube.com/watch?v={target}"
        return target if target.startswith("http") else f"ytsearch1:{target}"

    @staticmethod
    def opts_stream(formato=None):
        """As opcoes do yt-dlp para o endereco do stream (o que toca e o que a medida de andamento le)."""
        return {**YDL, "noplaylist": True, "skip_download": True,
                "format": formato or "bestaudio[protocol^=http]/bestaudio/best"}

    def stream_info(self, target, formato=None):
        """Endereco direto do audio no YouTube, para o ffmpeg tocar sem baixar antes (sai em
        1 a 3 s; um download leva bem mais). Volta o info do yt-dlp (enxuto: o endereco em url, id, title,
        channel, uploader e duration) e os cabecalhos HTTP."""
        r = fora.pede("stream", alvo=self.alvo_yt(target), opts=self.opts_stream(formato))
        return r["info"], r["hdr"]

    @staticmethod
    def search(q, n, start=0):
        """Busca no YouTube: os resultados de start a start+n (o "carregar mais" da pagina pede a
        leva seguinte; o yt-dlp busca de novo do comeco e a fatia sai daqui)."""
        opts = {**YDL, "skip_download": True, "extract_flat": "in_playlist", "noplaylist": True}
        # link ou id colado vira o proprio video, nao uma busca pelo texto do link
        m = YT_URL.search(q)
        alvo = m.group(1) if m else (q if YT_ID.match(q) else None)
        if alvo:
            if start:
                return []  # link colado e um video so: nao ha mais
            info = {"entries": [fora.pede("info", alvo=f"https://www.youtube.com/watch?v={alvo}", opts=opts)]}
        else:
            info = fora.pede("info", alvo=f"ytsearch{start + n}:{q}", opts=opts)
        out = []
        for e in list(info.get("entries") or [])[0 if alvo else start:]:
            yid = e.get("id")
            if not yid or not YT_ID.match(yid):
                continue
            out.append({"youtube_id": yid, "title": e.get("title"),
                        "duration": e.get("duration"),
                        "channel": e.get("channel") or e.get("uploader"),
                        "thumb": thumb(yid), "in_library": False})
        return out

    def mock_download(self, j, target):
        # --mock: finge o download (3 s de progresso) e reaproveita um audio que ja existe
        for i in range(1, 11):
            time.sleep(0.3)
            self.job_update(j, progress=i / 10 * 0.99)
        bases = [x for x in self.lib.items if (LIB / x["file"]).exists()]
        if not bases:
            raise RuntimeError(f"--mock precisa de pelo menos um áudio em {LIB}")
        base = min(bases, key=lambda x: x.get("duration") or 1e9)  # o mais curto
        yid = target if YT_ID.match(target) else None
        title, channel = j["label"], None
        if yid:  # titulo e canal de verdade; a duracao e a do audio reaproveitado
            try:
                info = fora.pede("info", alvo=f"https://www.youtube.com/watch?v={yid}", opts={**YDL, "skip_download": True})
                title = info.get("title") or title
                channel = info.get("channel") or info.get("uploader")
            except Exception:  # noqa: BLE001 - o mock segue com o rotulo
                pass
        item = dict(base, id=yid or f"mock-{j['id']}", title=title, youtube_id=yid,
                    channel=channel, thumb=thumb(yid),
                    added=datetime.now().isoformat(timespec="seconds"), last_pos=0)
        self.lib.add(item)
        return item

    def download(self, j, target):
        if self.mock:
            return self.mock_download(j, target)
        opts = {**YDL, "noplaylist": True, "noprogress": True,
                "format": "bestaudio/best", "outtmpl": str(LIB / "%(id)s.%(ext)s")}
        r = fora.pede("baixar", progresso=lambda f: self.job_update(j, progress=min(0.99, f)), limite=None,
                      alvo=self.alvo_yt(target), opts=opts)
        info, path = r["info"], LIB / r["file"]
        if not path.exists():
            raise RuntimeError("o download terminou sem arquivo de áudio")
        yid = info.get("id")
        item = {"id": yid, "title": info.get("title") or yid, "file": path.name,
                "duration": info.get("duration") or eng.probe_duration(str(path)),
                "youtube_id": yid, "thumb": thumb(yid),
                "channel": info.get("channel") or info.get("uploader"),
                "added": datetime.now().isoformat(timespec="seconds"), "last_pos": 0}
        self.lib.add(item)
        return item

    def run_download(self, j, target):
        try:
            item = self.download(j, target)
            self.job_update(j, status="done", progress=1.0, item_id=item["id"],
                            label=item["title"], finished=time.time())
            # o disco no prato e deste download (tocando pelo stream ou ainda esperando): passa
            # para o arquivo sem cortar; se ele ja trocou de disco, nada toca
            tr = self.engine.track
            if tr is not None and tr.get("job") == j["id"]:
                self.engine.trocar_fonte(tr, dict(item, path=str(LIB / item["file"])))
        except Exception as ex:  # noqa: BLE001 - o erro vai pra tela
            self.job_update(j, status="error", finished=time.time(),
                            error=f"O download falhou ({yt_msg(ex)}). Confira o link ou tente outro vídeo.")
            tr = self.engine.track
            if tr is not None and tr.get("job") == j["id"] and (not tr.get("path") or self.engine.esperando_arquivo()):
                self.engine.stop()  # sem stream e sem arquivo: o prato nao fica carregando para sempre

    # tocar ----------------------------------------------------------------
    def remember_pos(self):
        e = self.engine
        if e.track is not None and e.status() in ("playing", "paused"):
            self.lib.update(e.track["id"], last_pos=round(e.pos, 1))

    def play_item(self, item, start, loop=None, historico=True, extra=None):
        self.remember_pos()
        if historico:
            self.guardar_historico(item["id"])
        tr = dict(item, path=str(LIB / item["file"]), **(extra or {}))
        if loop is not None:
            self.engine.set_loop(loop)
        self.engine.load(tr, start=start)

    def tocar_remoto(self, j, target, meta, historico=True):
        """Toca na hora pelo stream do YouTube enquanto o download do job segue por tras;
        quando o arquivo chega, o motor passa para ele sem cortar. Ate o
        endereco do stream sair, o disco fica no prato carregando; se o stream falhar, toca
        quando o download terminar, como antes. Sem job (parecida do Automatico), so stream."""
        yid = meta.get("youtube_id")
        tr = {"id": yid or f"job-{j['id']}", "title": meta.get("title") or (j["label"] if j else target),
              "channel": meta.get("channel"), "thumb": meta.get("thumb") or thumb(yid),
              "duration": meta.get("duration"), "youtube_id": yid, "alvo": None if yid else target,
              "path": None, "stream": True, "job": j["id"] if j else None, **marca_auto(meta)}
        self.remember_pos()
        if historico:
            self.guardar_historico(tr["id"])
        self.engine.espera(tr)
        threading.Thread(target=self._abre_stream, args=(tr, target, bool(meta.get("title"))),
                         daemon=True).start()

    def _abre_stream(self, tr, target, tem_titulo):
        """O YouTube as vezes recusa o endereco do audio e na tentativa seguinte libera (um disco de 1h45 so tocou depois de baixar, calado). Tenta tres vezes, a ultima
        aceitando qualquer formato de audio; cada falha vai para o log com o motivo, e sem stream
        a tela diz que o disco toca quando terminar de baixar."""
        info = hdr = None
        motivo = ""
        for i, formato in enumerate((None, None, "bestaudio/best")):
            if self.engine.track is not tr:
                return  # trocou de disco no meio
            try:
                info, hdr = self.stream_info(target, formato)
                break
            except Exception as ex:  # noqa: BLE001 - o motivo vai para o log e para a tela
                motivo = yt_msg(ex)
                print(f"stream: tentativa {i + 1} de 3 falhou para {target}: {motivo}", file=sys.stderr, flush=True)
                time.sleep(1.0)
        if info is None:
            if self.engine.track is not tr:
                return
            if tr["job"] is None:  # parecida do Automatico: nao vem download, pula para a seguinte
                x = self.proxima()
                if x:
                    self.tocar_entrada(x, historico=False)
                else:
                    self.engine.stop()
                return
            self.engine.error = (f"O YouTube não liberou o áudio para tocar na hora ({motivo}). "
                                 "Ele toca assim que terminar de baixar.")
            return
        yid = tr["youtube_id"] or info.get("id")
        novo = dict(tr, path=info["url"], headers=hdr, youtube_id=yid,
                    title=tr["title"] if tem_titulo else info.get("title") or tr["title"],
                    channel=tr["channel"] or info.get("channel") or info.get("uploader"),
                    thumb=tr["thumb"] or thumb(yid), duration=tr["duration"] or info.get("duration"))
        self.engine.trocar_fonte(tr, novo)

    # historico (Anterior) -------------------------------------------------
    def entrada_de(self, tr):
        """O disco do prato no formato de entrada da fila: o Anterior o devolve para o topo da
        fila, e o historico guarda assim. None quando nao ha como tocar de novo."""
        yid = tr.get("youtube_id")
        it = self.lib.get(tr["id"]) or (self.lib.by_youtube(yid) if yid else None)
        alvo = None if yid else tr.get("alvo")
        if not it and not yid and not alvo:
            return None
        return {"id": it["id"] if it else None, "youtube_id": yid, "url": alvo, "title": tr.get("title"),
                "channel": tr.get("channel"), "thumb": tr.get("thumb"), "duration": tr.get("duration"),
                "job": tr.get("job"), "qid": uuid.uuid4().hex[:8], **marca_auto(tr)}

    def guardar_historico(self, novo_id=None, tr=None):
        """O disco que sai do prato (ou `tr`, o que a passagem tirou dele) entra no historico, que o
        Anterior percorre de tras para frente. Tocar de novo o disco que ja esta no prato nao conta,
        nem o mesmo duas vezes seguidas."""
        tr = tr or self.engine.track
        if tr is None or tr["id"] == novo_id:
            return
        x = self.entrada_de(tr)
        if x is None:
            return
        x["chave"] = tr["id"]
        with self.fila_lock:
            if not self.historico or self.historico[-1]["chave"] != x["chave"]:
                self.historico.append(x)
                del self.historico[:-HISTORICO_MAX]

    def anterior(self):
        """Anterior do Spotify: com mais de 3 s de disco (ou nada antes dele), volta ao comeco;
        senao toca o disco de antes, e o do prato vai para o topo da fila. Volta o que fez."""
        e = self.engine
        with self.fila_lock:
            volta = e.track is not None and (e.pos > ANTERIOR_REINICIA_S or not self.historico)
            x = None if volta or not self.historico else self.historico.pop()
        if volta:
            e.seek(0.0)
            return "inicio"
        if x is None:
            return None
        if e.track is not None:
            y = self.entrada_de(e.track)
            if y:
                with self.fila_lock:
                    self._por_na_fila(y, seguir=True)
        self.tocar_entrada(x, historico=False)
        return "anterior"

    # fila (A seguir) --------------------------------------------------------
    def _por_na_fila(self, x, seguir=False):
        """Com fila_lock. Tocar a seguir vai logo depois do disco do prato; com o Aleatorio
        ligado, o Adicionar a fila cai num lugar sorteado, como no YouTube Music, e na ordem
        montada vai para o fim. As parecidas do Automatico ficam sempre depois do que o usuario pos."""
        if seguir:
            self.fila.insert(0, x)
            if self.fila_ordem is not None:
                self.fila_ordem.insert(0, x)
        elif self.fila_ordem is not None:
            self.fila.insert(random.randint(0, antes_das_parecidas(self.fila)), x)
            self.fila_ordem.insert(antes_das_parecidas(self.fila_ordem), x)
        else:
            self.fila.insert(antes_das_parecidas(self.fila), x)

    def _tirar(self, x):
        """Com fila_lock: sai da fila e da ordem montada."""
        self.fila.remove(x)
        if self.fila_ordem is not None and x in self.fila_ordem:
            self.fila_ordem.remove(x)

    def _recusar(self, x):
        """Com fila_lock: parecida que o usuario tirou da fila nao volta nesta sessao."""
        if x.get("auto") and x.get("youtube_id"):
            self.fora.add(x["youtube_id"])
            self.fora_musica |= chaves_musica(x)

    def aleatorio(self, on):
        """Aleatorio do YouTube Music: ligar embaralha o A seguir (a ordem nova aparece na
        lista); desligar volta a ordem que o usuario montou, sem os que ja sairam. As parecidas do
        Automatico seguem no fim, na ordem delas (a do andamento)."""
        with self.fila_lock:
            if on and self.fila_ordem is None:
                self.fila_ordem = list(self.fila)
                meus = [x for x in self.fila if not x.get("auto")]
                random.shuffle(meus)
                self.fila = meus + [x for x in self.fila if x.get("auto")]
            elif not on and self.fila_ordem is not None:
                vivos = {x["qid"] for x in self.fila}
                ordem = [x for x in self.fila_ordem if x["qid"] in vivos]
                na_ordem = {x["qid"] for x in ordem}
                self.fila = ordem + [x for x in self.fila if x["qid"] not in na_ordem]
                self.fila_ordem = None

    def enfileirar(self, b):
        """Entrada da fila pelo corpo do POST /api/queue. Disco que nao esta na prateleira ja
        comeca a baixar, para estar pronto (ou quase) na vez dele."""
        it = self.lib.get(b.get("id") or "")
        j = None
        if not it:
            target = (b.get("youtube_id") or b.get("url") or "").strip()
            if not target:
                raise ValueError("Mande o id de um disco da prateleira, um id de vídeo ou um link do YouTube.")
            m = YT_URL.search(target)
            yid = m.group(1) if m else (target if YT_ID.match(target) else None)
            it = self.lib.by_youtube(yid) if yid else None
        if it:
            x = {"id": it["id"], "youtube_id": it.get("youtube_id"), "url": None, "title": it["title"],
                 "channel": it.get("channel"), "thumb": it.get("thumb"), "duration": it.get("duration"),
                 "job": None}
        else:
            alvo = yid or target
            j = self.job_rodando(alvo)
            if j is None:
                j = self.new_job(b.get("title") or target, False, alvo)
                pool.submit(self.run_download, j, alvo)
            x = {"id": None, "youtube_id": yid, "url": None if yid else target,
                 "title": b.get("title") or target, "channel": b.get("channel"),
                 "thumb": b.get("thumb") or thumb(yid), "duration": b.get("duration"), "job": j["id"]}
        x["qid"] = uuid.uuid4().hex[:8]
        with self.fila_lock:
            self._por_na_fila(x, seguir=bool(b.get("next")))
        return x, j

    def tirar_da_fila(self, qid, recusar=False):
        with self.fila_lock:
            x = next((e for e in self.fila if e["qid"] == qid), None)
            if x:
                self._tirar(x)
                if recusar:
                    self._recusar(x)
            return x

    def proxima(self):
        """Tira o primeiro do A seguir (None com a fila vazia)."""
        with self.fila_lock:
            x = self.fila[0] if self.fila else None
            if x:
                self._tirar(x)
            return x

    def esquecer(self, iid, yid):
        """Disco apagado da prateleira sai da fila e do historico (senao baixaria de novo na
        vez dele, ou no Anterior)."""
        def fica(x):
            return x.get("id") != iid and not (yid and x.get("youtube_id") == yid)
        with self.fila_lock:
            self.fila = [x for x in self.fila if fica(x)]
            if self.fila_ordem is not None:
                self.fila_ordem = [x for x in self.fila_ordem if fica(x)]
            self.historico = [x for x in self.historico if fica(x)]

    def apagar_audio(self, nome):
        """O arquivo do disco que saiu da prateleira: na hora, ou, com o motor tocando dele (no prato, preparado
        para a passagem ou saindo nela), quando o motor largar. Voltou para a prateleira antes (o Desfazer),
        fica. No --mock os arquivos sao os da prateleira de verdade e nunca saem."""
        if self.lib.keep_files:
            return
        f = str(LIB / nome)

        def em_uso():
            e = self.engine
            pronto, saindo = e._pronto, e._saindo   # o motor troca os dois de outra thread: um retrato so
            decks = (pronto, saindo[0] if saindo else None)
            return any(t is not None and t.get("path") == f for t in (e.track, *(d.track for d in decks if d)))

        def apaga():
            while em_uso():
                time.sleep(5)
            for _ in range(6):  # o leitor do motor pode levar um instante para fechar o arquivo
                if any(x["file"] == nome for x in self.lib.items):
                    return
                try:
                    Path(f).unlink(missing_ok=True)
                    return
                except OSError:
                    time.sleep(5)
        threading.Thread(target=apaga, daemon=True).start()

    def limpar_fila(self):
        with self.fila_lock:
            for x in self.fila:
                self._recusar(x)
            self.fila = []
            if self.fila_ordem is not None:
                self.fila_ordem = []

    def mover_na_fila(self, qid, to):
        """Arrastar muda a ordem de tocar; com o Aleatorio ligado, a ordem montada fica como
        estava."""
        with self.fila_lock:
            x = next((e for e in self.fila if e["qid"] == qid), None)
            if not x:
                return False
            self.fila.remove(x)
            self.fila.insert(max(0, min(to, len(self.fila))), x)
            if x.get("auto"):
                x["fixa"] = True  # a parecida que o usuario arrastou fica onde ele pos: a ordem por andamento nao mexe nela
            return True

    def tocar_entrada(self, x, historico=True):
        """Toca uma entrada da fila (ou do historico): do arquivo se ja esta na prateleira;
        senao pelo stream, com o download (o da fila, ou um novo) trocando para o arquivo
        quando chegar. Parecida do Automatico fora da prateleira toca so pelo stream, sem
        baixar: a prateleira fica com o que o usuario escolheu."""
        j = self.jobs.get(x.get("job") or "")
        it = (self.lib.get(x["id"]) if x.get("id") else None) or \
             (self.lib.by_youtube(x["youtube_id"]) if x.get("youtube_id") else None) or \
             (self.lib.get(j["item_id"]) if j and j.get("item_id") else None)
        if it:
            self.play_item(it, 0.0, historico=historico, extra=marca_auto(x))
            return
        alvo = x.get("youtube_id") or x.get("url")
        if not alvo:
            raise ValueError("a entrada não tem vídeo nem link")
        if x.get("auto") and x.get("youtube_id"):
            self.tocar_remoto(None, alvo, x, historico=historico)
            return
        if not j or j["status"] != "running":
            j = self.new_job(x.get("title") or alvo, True, alvo)
            pool.submit(self.run_download, j, alvo)
        else:
            self.job_update(j, play=True)
        self.tocar_remoto(j, alvo, x, historico=historico)

    def _vigia_fila(self):
        """Quando o disco do prato acaba, o primeiro da fila entra. O Repetir manda: ligado, o
        disco nao acaba. So a passagem para o fim conta aqui; com o prato ja parado, quem toca
        e o POST /api/queue (o que entra na fila toca na hora)."""
        visto = None
        while True:
            time.sleep(0.1)
            e = self.engine
            tr = e.track
            if tr is None or e.status() != "ended":
                visto = None
                continue
            if visto is tr:
                continue
            visto = tr
            x = self.proxima()
            if x:
                try:
                    self.tocar_entrada(x)
                except Exception as ex:  # noqa: BLE001 - entrada quebrada nao trava a fila
                    e.error = f"Não deu para tocar \"{x.get('title')}\" da fila ({str(ex)[:120]})."
            else:
                self.parado_sem_fila = tr

    # passagem para a proxima (a transicao de DJ) --------------------------
    def fonte_de(self, x):
        """O disco da entrada da fila pronto para o segundo deck do motor, ou None quando a passagem
        nao vale para ela (o _vigia_fila toca no fim, como antes): da prateleira, o arquivo; a parecida
        do Automatico, o stream; o que o usuario pos e ainda baixa, o stream com o download que ja corre.
        Entrada sem download nenhum fica para o fim, que o comeca (a passagem nao abre download)."""
        j = self.jobs.get(x.get("job") or "")
        it = (self.lib.get(x["id"]) if x.get("id") else None) or \
             (self.lib.by_youtube(x["youtube_id"]) if x.get("youtube_id") else None) or \
             (self.lib.get(j["item_id"]) if j and j.get("item_id") else None)
        if it:
            return dict(it, path=str(LIB / it["file"]), **marca_auto(x))
        alvo = x.get("youtube_id") or x.get("url")
        auto = x.get("auto") and x.get("youtube_id")
        if not alvo or not (auto or (j and j["status"] == "running")):
            return None
        info, hdr = self.stream_info(alvo)
        yid = x.get("youtube_id") or info.get("id")
        return {"id": yid or f"job-{j['id']}", "title": x.get("title") or info.get("title") or alvo,
                "channel": x.get("channel") or info.get("channel") or info.get("uploader"),
                "thumb": x.get("thumb") or thumb(yid), "duration": x.get("duration") or info.get("duration"),
                "youtube_id": yid, "alvo": None if yid else alvo, "path": info["url"], "headers": hdr,
                "stream": True, "job": None if auto else j["id"], **marca_auto(x)}

    def _prepara(self, tr, x, chave):
        try:
            novo = self.fonte_de(x)
            if novo is None:
                self.passagem_falhou = chave
                return
            e = self.engine
            with self.fila_lock:
                ainda = bool(self.fila) and self.fila[0]["qid"] == x["qid"]
            if ainda and e.track is tr and e.pronto_tag is None:
                e.preparar(novo, x["qid"])
        except Exception as ex:  # noqa: BLE001 - sem a proxima pronta, ela toca no fim como antes
            self.passagem_falhou = chave
            print(f"passagem: nao preparei {x.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
        finally:
            self.preparando = None

    def _virou(self, sai, entrou, tag):
        """O motor passou para a proxima: o que o tocar_entrada faria, sem tocar (ja esta tocando)."""
        with self.fila_lock:
            x = next((y for y in self.fila if y["qid"] == tag), None)
            if x:
                self._tirar(x)
        self.guardar_historico(entrou["id"], tr=sai)
        self.parado_sem_fila = None

    def _vigia_passagem(self):
        """A eng.TRANS_PREP_S do fim, prepara a primeira da fila no segundo deck do motor, que mede o
        fim deste disco e o comeco dela e vira sozinho no ponto certo; aqui so a fila e o historico
        acompanham a virada. Repetir ligado, disco sem duracao ou fila vazia: fica como antes (o
        _vigia_fila toca no fim). A fila que muda antes da virada troca a preparada; a que nao deu para
        preparar (sem stream, ou o comeco dela nao decodificou) toca no fim, sem nova tentativa."""
        while True:
            time.sleep(0.2)
            e = self.engine
            v = e.virou
            if v is not None:
                e.virou = None
                try:
                    self._virou(*v)
                except Exception as ex:  # noqa: BLE001
                    print(f"passagem: a virada nao fechou a fila: {ex}", file=sys.stderr, flush=True)
            tr = e.track
            with self.fila_lock:
                x = self.fila[0] if self.fila else None
            if e.pronto_falhou is not None:
                self.passagem_falhou, e.pronto_falhou = (id(tr), e.pronto_falhou), None
            dur = tr.get("duration") if tr else None
            pode = (x is not None and dur and tr.get("path") and not e.loop
                    and e.status() in ("playing", "paused", "buffering"))
            if e.pronto_tag is not None and (not pode or x["qid"] != e.pronto_tag):
                e.cancelar_pronto()
            if not pode or e.pronto_tag is not None or dur - e.pos > eng.TRANS_PREP_S:
                continue
            chave = (id(tr), x["qid"])
            if self.preparando is not None or chave == self.passagem_falhou:
                continue
            self.preparando = chave
            threading.Thread(target=self._prepara, args=(tr, x, chave), daemon=True).start()

    # Automatico -------------------------------------------
    def mix_do(self, yid):
        """As parecidas do video, so o que cabe no Automatico (duracao entre AUTO_DUR, sem o proprio): o radio do
        YouTube Music (o catalogo de musicas, sem a versao com letra repetindo o clipe); sem a
        ytmusicapi, ou com ela falhando ou vazia, o Mix do YouTube."""
        try:
            out = self.radio_do(yid)
            if out:
                return out
            motivo = "veio vazio"
        except Exception as ex:  # noqa: BLE001 - sem o radio, o Mix do YouTube segura o Automatico
            motivo = yt_msg(ex)
        print(f"automatico: o radio do YouTube Music de {yid} falhou ({motivo}); vai o Mix do YouTube",
              file=sys.stderr, flush=True)
        return self.mix_yt(yid)

    @staticmethod
    def radio_do(yid):
        """O "Iniciar radio" do YouTube Music pela ytmusicapi, sem login (50 em ~1 s): artista e titulo separados
        (o artista vai no channel)."""
        out = []
        for t in fora.pede("radio", yid=yid, n=AUTO_LOTE):
            eid, dur = t.get("videoId"), segundos(t.get("length"))
            if not eid or not YT_ID.match(eid) or eid == yid or not dur or not AUTO_DUR[0] <= dur <= AUTO_DUR[1]:
                continue
            artistas = ", ".join(a["name"] for a in t.get("artists") or [] if a.get("name"))
            tipo = (t.get("videoType") or "")[-3:]  # ATV: a faixa so de audio; OMV: o clipe; UGC: video de alguem
            out.append({"youtube_id": eid, "title": t.get("title") or eid, "duration": dur,
                        "channel": artistas or None, "thumb": thumb(eid), "tipo": tipo, "audio": tipo == "ATV"})
        return out

    @staticmethod
    def mix_yt(yid):
        """O Mix do YouTube do video (a radio que o YouTube toca depois dele), pelo yt-dlp."""
        opts = {**YDL, "skip_download": True, "extract_flat": "in_playlist", "playlistend": AUTO_LOTE}
        info = fora.pede("info", alvo=f"https://www.youtube.com/watch?v={yid}&list=RD{yid}", opts=opts)
        out = []
        for e in info.get("entries") or []:
            eid, dur = e.get("id"), e.get("duration")
            if not eid or not YT_ID.match(eid) or eid == yid or not dur or not AUTO_DUR[0] <= dur <= AUTO_DUR[1]:
                continue
            out.append({"youtube_id": eid, "title": e.get("title") or eid, "duration": dur,
                        "channel": e.get("channel") or e.get("uploader"), "thumb": thumb(eid)})
        return out

    def ligar_auto(self, on):
        """Desligar tira as parecidas da fila; ligar enche na proxima volta do vigia."""
        with self.fila_lock:
            self.auto = bool(on)
            if not self.auto:
                for x in [x for x in self.fila if x.get("auto")]:
                    self._tirar(x)

    def _busca_mix(self, base):
        try:
            lista = self.mix_do(base)
        except Exception as ex:  # noqa: BLE001 - sem Mix, o Automatico espera e tenta de novo
            print(f"automatico: o Mix de {base} falhou: {yt_msg(ex)}", file=sys.stderr, flush=True)
            lista = None
        with self.fila_lock:
            self.mix_buscando = False
            if lista is None:
                self.mix_falhou = time.time()
            elif base == self.mix_base:  # a semente nao trocou no meio
                for m in lista:
                    self.mix_seq += 1
                    m["ordem"] = self.mix_seq
                    if m["youtube_id"] in self.versoes:  # a versao de audio ja procurada antes
                        self._poe_versao(m, self.versoes[m["youtube_id"]])
                self.mix = lista

    @staticmethod
    def chave_andamento(x):
        """Onde o andamento do disco fica guardado: o id do video, ou o do disco da prateleira sem video."""
        if not x:
            return None
        return x.get("youtube_id") or (f"lib:{x['id']}" if x.get("id") else None)

    def _tempo(self, x):
        """{"ini", "fim"} do disco, ou None ainda sem medida."""
        c = self.chave_andamento(x)
        return self.andamentos.get(c) if c else None

    @staticmethod
    def _janela(pool, n):
        """As de pool (na ordem do Mix) que cabem na proxima AUTO_JANELA_S, e pelo menos n."""
        out, soma = [], 0.0
        for c in pool:
            if len(out) >= n and soma >= AUTO_JANELA_S:
                break
            out.append(c)
            soma += c.get("duration") or 0
        return out

    def _livres(self):
        """Com fila_lock: as do Mix que podem entrar, na ordem do Mix: nem tocaram nesta sessao, nem o usuario tirou,
        nem estao na fila, nem sao a mesma musica de uma dessas ou de uma anterior do Mix."""
        vistas = set(self.fora_musica)
        for x in self.fila:
            vistas |= chaves_musica(x)
        na_fila = {x.get("youtube_id") for x in self.fila}
        out = []
        for m in sorted(self.mix or [], key=lambda c: c.get("ordem", 0)):
            ks = chaves_musica(m)
            if m["youtube_id"] in self.fora or m["youtube_id"] in na_fila or ks & vistas:
                continue
            vistas |= ks
            out.append(m)
        return out

    def _presa(self):
        """Com fila_lock: a primeira da fila nao troca mais (a passagem para ela ja esta sendo preparada, ou falta
        pouco para isso)."""
        if not self.fila:
            return False
        e, q = self.engine, self.fila[0]["qid"]
        tr = e.track
        dur = tr.get("duration") if tr else None
        return bool((dur and dur - e.pos <= eng.TRANS_PREP_S + 15) or e.pronto_tag == q
                    or (self.preparando is not None and self.preparando[1] == q))

    def _ordena_auto(self):
        """Com fila_lock: as parecidas do fim do A seguir em ordem de andamento (andamento.ordena: subindo no
        circulo das oitavas a partir do fim do disco antes delas), escolhidas entre as que ja estao la e as do Mix
        ainda nao usadas, so as da proxima AUTO_JANELA_S do Mix (as mais parecidas com a semente), ate AUTO_FILA. A
        que o usuario arrastou fica onde ele pos, e a primeira da fila fica se a passagem para ela ja vai ser preparada.
        A que sai da fila volta para o Mix. Sem medida ainda, fica a ordem do Mix; cada medida que chega ordena de
        novo. Volta quantas entraram."""
        k = len(self.fila)
        while k and self.fila[k - 1].get("auto") and not self.fila[k - 1].get("fixa"):
            k -= 1
        if k == 0 and self._presa():
            k = 1
        bloco = self.fila[k:]
        n = AUTO_FILA - sum(1 for x in self.fila[:k] if x.get("auto"))
        mix = self._livres()
        janela = self._janela(sorted(bloco + mix, key=lambda c: c.get("ordem", 0)), n)
        # o andamento do fim do disco antes delas: o ultimo da fila que fica, ou o do prato
        antes = list(reversed(self.fila[:k])) + ([self.engine.track] if self.engine.track else [])
        t = self._tempo(antes[0]) if antes else None
        cursor, salto = None, False
        if t:
            salto = t.get("fim") is None  # sem batida firme no fim dele: a passagem para a primeira vai ser de volume
            cursor = t.get("fim") or t.get("ini")
            for y in antes[1:]:  # nem o comeco dele: o circulo segue do ultimo andamento conhecido
                if cursor is not None:
                    break
                ty = self._tempo(y)
                cursor = ty and (ty.get("fim") or ty.get("ini"))
        escolha = an.ordena(cursor, salto, janela, self._tempo, max(0, n), autores, autores(antes[0]) if antes else frozenset())
        na_bloco = {x["qid"] for x in bloco}
        nova, entrou = [], 0
        for c in escolha:
            if c.get("qid") in na_bloco:
                nova.append(c)
            else:
                nova.append(dict(c, id=None, url=None, job=None, qid=uuid.uuid4().hex[:8],
                                 auto=True, auto_de=self.semente["title"]))
                entrou += 1
        if [x["qid"] for x in nova] == [x["qid"] for x in bloco]:
            return 0
        usadas = {c["youtube_id"] for c in escolha}
        if self.mix is not None:
            self.mix = sorted([m for m in mix if m["youtube_id"] not in usadas]
                              + [x for x in bloco if x["youtube_id"] not in usadas], key=lambda c: c.get("ordem", 0))
        self.fila[k:] = nova
        if self.fila_ordem is not None:
            self.fila_ordem = [x for x in self.fila_ordem if x["qid"] not in na_bloco] + nova
        return entrou

    def _vigia_auto(self):
        """Com o Automatico ligado, a fila nunca acaba (como no YouTube Music): o ultimo disco que
        o usuario escolheu (qualquer um que o Automatico nao pos) e a semente, e o radio dela (mix_do)
        mantem AUTO_FILA parecidas no fim do A seguir. Semente nova troca as parecidas; o que ja
        tocou nesta sessao nao volta; quando o Mix da semente acaba, segue do Mix da ultima
        parecida que tocou. As parecidas vao em ordem de andamento (_ordena_auto)."""
        visto, sinal = None, None
        while True:
            time.sleep(0.5)
            e = self.engine
            tr = e.track
            yid = tr.get("youtube_id") if tr else None
            if yid and yid != visto:
                visto = yid
                with self.fila_lock:
                    self.fora.add(yid)
                    self.fora_musica |= chaves_musica(tr)
                    if tr.get("auto"):
                        self.ponte = yid
                    else:
                        self.semente = {"youtube_id": yid, "title": tr.get("title")}
                        self.mix, self.mix_base = None, yid
                        for x in [x for x in self.fila if x.get("auto")]:
                            self._tirar(x)
            base, entrou = None, 0
            with self.fila_lock:
                if not self.auto or not self.semente:
                    continue
                falta = AUTO_FILA - sum(1 for x in self.fila if x.get("auto"))
                if falta > 0 and not self.mix_buscando:
                    if not self.mix and self.mix is not None and self.ponte and self.ponte != self.mix_base:
                        self.mix, self.mix_base = None, self.ponte  # o Mix da semente acabou
                    if self.mix is None and time.time() - self.mix_falhou >= AUTO_ESPERA_S:
                        self.mix_buscando, base = True, self.mix_base
                # a ordem por andamento se refaz quando muda a fila, o prato, o Mix ou chega uma medida
                agora = (id(tr), tuple(x["qid"] for x in self.fila), self.andamentos_versao, self.mix_seq,
                         self._presa())
                if agora != sinal and (self.mix or any(x.get("auto") for x in self.fila)):
                    entrou = self._ordena_auto()
                    sinal = (id(tr), tuple(x["qid"] for x in self.fila), self.andamentos_versao, self.mix_seq,
                             self._presa())
            if base:
                threading.Thread(target=self._busca_mix, args=(base,), daemon=True).start()
            # o disco acabou antes de chegar parecida (o Mix ainda vinha): a primeira toca agora
            if entrou and tr is not None and tr is self.parado_sem_fila and e.track is tr and e.status() == "ended":
                self.parado_sem_fila = None
                x = self.proxima()
                if x:
                    try:
                        self.tocar_entrada(x)
                    except Exception as ex:  # noqa: BLE001
                        e.error = f"Não deu para tocar \"{x.get('title')}\" da fila ({str(ex)[:120]})."


    # andamento das parecidas -------------------------------------
    @staticmethod
    def _poe_versao(x, v):
        """A parecida passa a tocar a versao so de audio v (sem versao, fica o video e so a marca de procurada)."""
        x["audio"] = True
        if v:
            x.update(v, video=x.get("video") or x["youtube_id"], thumb=thumb(v["youtube_id"]), tipo="ATV")

    @staticmethod
    def versao_audio(x):
        """A versao so de audio (a faixa do album no YouTube Music) da parecida que veio como video, pela busca de
        musicas com nome e artista: {"youtube_id", "duration", "title", "channel"} da primeira das 3 que e a mesma
        faixa (mesma_faixa), ou None (musica so do YouTube, ou a busca so traz outras)."""
        for r in fora.pede("musicas", q=busca_de(x)):
            if r.get("videoId") and YT_ID.match(r["videoId"]) and mesma_faixa(x, r):
                artistas = ", ".join(a["name"] for a in r.get("artists") or [] if a.get("name"))
                return {"youtube_id": r["videoId"],
                        "duration": r.get("duration_seconds") or segundos(r.get("duration")),
                        "title": r.get("title") or x.get("title"), "channel": artistas or x.get("channel")}
        return None

    def _troca_audio(self, vid, v):
        """Com fila_lock: a parecida do video vid (no Mix e na fila; a primeira da fila fica se ja esta presa)
        passa para a versao de audio v."""
        presa = self.fila[0] if self.fila and self._presa() else None
        for x in list(self.mix or []) + [y for y in self.fila if y.get("auto") and y is not presa]:
            if x.get("youtube_id") == vid and not x.get("audio"):
                self._poe_versao(x, v)

    def _a_medir(self):
        """Com fila_lock: o que falta fazer, pela ordem em que faz falta: ("medir", disco) sem andamento ou
        ("audio", parecida) sem a versao de audio procurada; o do prato, o ultimo que o usuario pos antes das parecidas
        e as parecidas da janela (as da fila e as do Mix), na ordem do Mix, cada uma com a versao antes da medida.
        (None, None) sem nada."""
        k = len(self.fila)
        while k and self.fila[k - 1].get("auto"):
            k -= 1
        mix = self._livres()
        pool = sorted([x for x in self.fila[k:]] + mix, key=lambda c: c.get("ordem", 0))
        agora = time.time()
        janela = self._janela(pool, AUTO_FILA)
        parecidas = {id(c) for c in janela}
        for x in [self.engine.track] + self.fila[k - 1:k] + janela:
            vid = x.get("youtube_id") if id(x) in parecidas else None
            if (vid and not x.get("audio") and vid not in self.versoes
                    and agora - self.andamento_falhou.get(f"audio:{vid}", 0.0) >= ANDAMENTO_ESPERA_S):
                return "audio", dict(x)
            c = self.chave_andamento(x)
            if c and c not in self.andamentos and agora - self.andamento_falhou.get(c, 0.0) >= ANDAMENTO_ESPERA_S:
                return "medir", dict(x)
        return None, None

    def _mede_andamento(self, x):
        """{"ini", "fim"} do disco pelo andamento.py num processo a parte, com prioridade baixa: da prateleira, o
        arquivo; senao o stream que toca (so os pedacos que a medida le, ~1 MB), com o endereco pedido ao YouTube la
        dentro: o yt-dlp aqui segurava o interpretador do servidor em rajadas e o audio estalava (22/10: 15
        parecidas medidas na primeira musica do radio). None sem como ler."""
        it = (self.lib.get(x["id"]) if x.get("id") else None) or \
             (self.lib.by_youtube(x["youtube_id"]) if x.get("youtube_id") else None)
        if it and (LIB / it["file"]).exists():
            if not it.get("duration"):
                return None
            pedido = {"fonte": str(LIB / it["file"]), "dur": it["duration"]}
        elif x.get("youtube_id"):
            pedido = {"yt": self.alvo_yt(x["youtube_id"]), "opts": self.opts_stream(), "dur": x.get("duration")}
        else:
            return None
        p = subprocess.run(auxiliar("--andamento"),
                           input=json.dumps(pedido), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180, cwd=str(HERE),
                           creationflags=eng.NO_WINDOW | ABAIXO_DO_NORMAL, startupinfo=eng.sem_cursor())
        r = json.loads(p.stdout.strip().splitlines()[-1])
        if r and r.get("erro"):
            raise RuntimeError(r["erro"])
        return {"ini": r.get("ini"), "fim": r.get("fim")} if r else None

    def _vigia_andamento(self):
        """Com o Automatico ligado, mede o andamento (_a_medir, _mede_andamento) um disco de cada vez, uma vez so
        por disco (fica no andamentos.json). So depois de o disco do prato ficar ANDAMENTO_APOS_S tocando (pular
        de disco em disco nao le nada; buscar nao mede nunca) e nunca com a passagem sendo planejada (a rede do
        motor e a da medida juntas). Antes da medida, a parecida que veio como video troca pela versao so de
        audio, quando ha (versao_audio). A medida que chega faz o _vigia_auto ordenar de novo."""
        prato, desde = None, 0.0
        while True:
            time.sleep(1.0)
            e = self.engine
            tr = e.track
            if (tr and tr.get("id")) != prato:
                prato, desde = tr and tr.get("id"), time.time()
            if not self.auto or not prato or time.time() - desde < ANDAMENTO_APOS_S or e.planejando:
                continue
            with self.fila_lock:
                o_que, x = self._a_medir()
            if x is None:
                continue
            if o_que == "audio":
                vid = x["youtube_id"]
                try:
                    v = self.versao_audio(x)
                except Exception as ex:  # noqa: BLE001 - sem a busca, a parecida toca o video
                    print(f"audio: nao busquei {x.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
                    with self.fila_lock:
                        self.andamento_falhou[f"audio:{vid}"] = time.time()
                    continue
                with self.fila_lock:
                    self.versoes[vid] = v
                    save_json(self.versoes_path, self.versoes)
                    self._troca_audio(vid, v)
                    self.andamentos_versao += 1
                print(f"audio: {x.get('title')!r}: " + (f"a versao de audio {v['youtube_id']} ({v['duration']} s)"
                                                         if v else "so o video"), file=sys.stderr, flush=True)
                continue
            c = self.chave_andamento(x)
            t0 = time.time()
            try:
                r = self._mede_andamento(x)
            except Exception as ex:  # noqa: BLE001 - sem medida, a parecida fica sem andamento (vai para o salto)
                r = None
                print(f"andamento: nao medi {x.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
            with self.fila_lock:
                if r is None:
                    self.andamento_falhou[c] = time.time()
                    continue
                self.andamentos[c] = r
                save_json(self.andamentos_path, self.andamentos)
                self.andamentos_versao += 1
            print(f"andamento: {x.get('title')!r}: comeco {r['ini']}, fim {r['fim']} BPM em {time.time() - t0:.1f} s",
                  file=sys.stderr, flush=True)

    def _conta_escuta(self):
        """Prateleira das mais escutadas primeiro: o disco ganha uma escuta
        (`plays` na biblioteca) quando toca de fato ESCUTA_S desde que entrou no prato. Pausado
        nao conta; voltar para o comeco (ou o Repetir dar a volta) e ouvir de novo conta outra
        vez; a troca do stream para o arquivo baixado segue sendo o mesmo disco."""
        disco, ouvido, contou, antes = None, 0.0, False, 0.0
        while True:
            time.sleep(0.5)
            e = self.engine
            tr = e.track
            if tr is None:
                disco = None
                continue
            pos = e.pos
            if tr.get("id") != disco or pos < antes - 2:
                disco, ouvido, contou = tr.get("id"), 0.0, False
            antes = pos
            if contou or e.status() != "playing":
                continue
            ouvido += 0.5
            dur = tr.get("duration") or 0
            if ouvido < (min(ESCUTA_S, dur * 0.8) if dur else ESCUTA_S):
                continue
            contou = True
            yid = tr.get("youtube_id")
            it = self.lib.get(tr["id"]) or (self.lib.by_youtube(yid) if yid else None)
            if it:
                self.lib.update(it["id"], plays=it.get("plays", 0) + 1)


def yt_msg(ex):
    """Erro do yt_dlp sem o prefixo 'ERROR:' nem o id entre colchetes."""
    m = re.sub(r"^(ERROR:\s*)?(\[[^\]]+\]\s*)*", "", str(ex)).strip()
    return m[:160] or type(ex).__name__


def j_ok(**kw):
    return web.json_response({"ok": True, **kw})


def j_err(msg, status=400):
    return web.json_response({"ok": False, "error": msg}, status=status)


async def body(request):
    if not request.can_read_body:
        return {}
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="O corpo precisa ser JSON em UTF-8.")


def build(app_state):
    A = app_state
    E = A.engine
    loop_ = asyncio.get_running_loop
    locais = {f"127.0.0.1:{A.port}", f"localhost:{A.port}"}

    @web.middleware
    async def guard(request, handler):
        # Host fixo (DNS rebinding) e Origin conhecida em escrita (CSRF). Sem chave na rede de
        # casa: qualquer aparelho do Wi-Fi alcanca (o python.exe tem
        # entrada liberada no firewall no perfil Publico); --so-local fecha. O IP da rede e o de
        # agora: a porta do celular pode reabrir em outro (servir)
        allowed = locais | {f"{A.lan_ip}:{A.port}"} if A.lan_ip else locais
        if request.host not in allowed:
            return web.Response(status=403, text="host não permitido")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] not in allowed:
                return web.Response(status=403, text="origem não permitida")
        return await handler(request)

    r = web.RouteTableDef()

    @r.get("/api/state")
    async def state(_):
        return web.json_response({**A.snapshot(), "pos": round(E.pos, 2),
                                  "levels": dict(E.levels)})

    @r.get("/api/library")
    async def library(_):
        return web.json_response(A.lib.public())

    @r.get("/api/jobs")
    async def jobs(_):
        return web.json_response(A.public_jobs())

    @r.get("/api/search")
    async def search(request):
        q = (request.query.get("q") or "").strip()
        try:
            n = max(1, min(20, int(request.query.get("n", 8))))
            start = max(0, min(BUSCA_MAX - n, int(request.query.get("start", 0))))
        except ValueError:
            return j_err("Os parâmetros n e start precisam ser números (n de 1 a 20).")
        if not q:
            return j_err("Digite o que procurar ou cole um link do YouTube.")
        try:
            res = await loop_().run_in_executor(pool, A.search, q, n, start)
        except Exception as ex:  # noqa: BLE001
            return j_err(f"A busca no YouTube falhou ({yt_msg(ex)}). Confira a internet e tente de novo.",
                         502)
        for x in res:
            it = A.lib.by_youtube(x["youtube_id"])
            x["in_library"] = bool(it)
            x["id"] = it["id"] if it else None
        return web.json_response(res)

    @r.post("/api/library")
    async def lib_add(request):
        b = await body(request)
        target = (b.get("youtube_id") or b.get("url") or b.get("query") or "").strip()
        if not target:
            return j_err("Mande um link do YouTube, um id de vídeo ou um texto de busca.")
        m = YT_URL.search(target)
        yid = m.group(1) if m else (target if YT_ID.match(target) else None)
        it = A.lib.by_youtube(yid) if yid else None
        if it:
            if b.get("play"):
                A.play_item(it, 0.0)
            return j_ok(item=it)
        alvo = yid or target
        j = A.job_rodando(alvo)  # ja baixando (da fila, ou um toque repetido): nao baixa de novo
        if j is None:
            j = A.new_job(b.get("title") or target, bool(b.get("play")), alvo)
            loop_().run_in_executor(pool, A.run_download, j, alvo)
        if not b.get("play"):
            return j_ok(job=j)
        A.job_update(j, play=True)
        A.tocar_remoto(j, alvo, {"youtube_id": yid, "title": b.get("title"), "channel": b.get("channel"),
                                 "thumb": b.get("thumb"), "duration": b.get("duration")})
        return j_ok(job=j, streaming=True)

    @r.patch("/api/library/{iid}")
    async def lib_patch(request):
        b = await body(request)
        kw = {k: b[k] for k in ("title",) if isinstance(b.get(k), str) and b[k].strip()}
        if isinstance(b.get("rapido"), bool):
            kw["rapido"] = b["rapido"]  # nos Sons rapidos do celular pela mao, mesmo com mais de 15 s
        it = A.lib.update(request.match_info["iid"], **kw)
        if it and E.track is not None and E.track["id"] == it["id"]:
            E.track = dict(E.track, **kw)  # o Estado mostra o nome novo na hora
        return j_ok(item=it) if it else j_err("Esse som não está mais na biblioteca.", 404)

    @r.delete("/api/library/{iid}")
    async def lib_del(request):
        # tirar da prateleira nao mexe no prato:
        # o disco que toca do arquivo segue ate sair, e o arquivo sai depois
        iid = request.match_info["iid"]
        it = A.lib.remove(iid)
        if it:
            A.apagar_audio(it["file"])
        A.esquecer(iid, it and it.get("youtube_id"))
        return j_ok() if it else j_err("Esse som não está mais na biblioteca.", 404)

    # fila (A seguir): o primeiro toca quando o disco do prato acaba
    @r.post("/api/queue")
    async def queue_add(request):
        b = await body(request)
        try:
            x, j = A.enfileirar(b)
        except ValueError as ex:
            return j_err(str(ex))
        # nada no prato (parado, ou o disco ja acabou): o que acabou de entrar toca na hora, sem
        # esperar a vez; pausado ainda e disco no prato, e a fila so guarda
        if E.status() in ("idle", "ended") and A.tirar_da_fila(x["qid"]):
            A.tocar_entrada(x)
            return j_ok(entry=x, job=j, playing=True)
        return j_ok(entry=x, job=j, playing=False)

    @r.delete("/api/queue")
    async def queue_clear(_):
        A.limpar_fila()
        return j_ok()

    @r.delete("/api/queue/{qid}")
    async def queue_del(request):
        x = A.tirar_da_fila(request.match_info["qid"], recusar=True)
        return j_ok() if x else j_err("Esse disco já saiu da fila.", 404)

    @r.post("/api/queue/move")
    async def queue_move(request):
        b = await body(request)
        try:
            to = int(b.get("to"))
        except (TypeError, ValueError):
            return j_err("Faltou a posição nova (to, a partir de 0).")
        if not A.mover_na_fila(b.get("qid"), to):
            return j_err("Esse disco já saiu da fila.", 404)
        return j_ok()

    @r.post("/api/queue/play")
    async def queue_play(request):
        b = await body(request)
        x = A.tirar_da_fila(b.get("qid") or "")
        if not x:
            return j_err("Esse disco já saiu da fila.", 404)
        A.tocar_entrada(x)
        return j_ok()

    # transporte do Spotify: Proxima toca o primeiro do A seguir; Anterior volta ao comeco do
    # disco ou toca o de antes
    @r.post("/api/next")
    async def next_(_):
        x = A.proxima()
        if not x:
            return j_err("A fila está vazia: não há próximo disco.", 409)
        A.tocar_entrada(x)
        return j_ok(entry=x)

    @r.post("/api/prev")
    async def prev(_):
        feito = A.anterior()
        if not feito:
            return j_err("Nada tocou antes deste disco.", 409)
        return j_ok(did=feito)

    @r.post("/api/play")
    async def play(request):
        b = await body(request)
        it = A.lib.get(b.get("id", ""))
        if not it:
            return j_err("Esse som não está mais na biblioteca.", 404)
        start = b.get("start")
        # som curto (buzina, bordao) toca por cima da musica em vez de trocar; "por_cima" no
        # corpo forca um ou outro; continuar de onde parou e sempre a faixa principal
        curto = (it.get("duration") or 1e9) <= eng.CURTO_MAX_S and start is None and not b.get("resume")
        if b.get("por_cima", curto):
            E.por_cima(dict(it, path=str(LIB / it["file"])))
            return j_ok(por_cima=True)
        if start is None:
            start = it.get("last_pos", 0) if b.get("resume") else 0
        A.play_item(it, float(start), b.get("loop"))
        return j_ok()

    @r.post("/api/pause")
    async def pause(_):
        E.pause()
        A.remember_pos()
        return j_ok()

    @r.post("/api/resume")
    async def resume(_):
        E.resume()
        return j_ok()

    @r.post("/api/toggle")
    async def toggle(_):
        if E.status() in ("playing", "buffering"):
            E.pause()
            A.remember_pos()
        else:
            E.resume()
        return j_ok()

    @r.post("/api/stop")
    async def stop(_):
        A.remember_pos()
        A.guardar_historico()  # o Anterior toca de novo o disco parado
        E.stop()
        return j_ok()

    @r.post("/api/seek")
    async def seek(request):
        b = await body(request)
        if "t" not in b:
            return j_err("Faltou o tempo do pulo (t, em segundos).")
        E.seek(float(b["t"]))
        return j_ok()

    @r.post("/api/settings")
    async def settings(request):
        b = await body(request)
        for k in ("vol", "mon_vol", "voice_mon_vol"):
            if k in b:
                setattr(E, k, max(0.0, min(1.0, float(b[k]))))
        if "mic_vol" in b:
            E.set_mic_vol(b["mic_vol"])  # nivel do mic no Windows
        for k in ("mic_mute", "monitor_on", "voice_monitor"):
            if k in b:
                setattr(E, k, bool(b[k]))
        if "effect" in b:
            try:
                E.set_effect(str(b["effect"]))
            except ValueError as ex:
                return j_err(str(ex))
        if "loop" in b:
            E.set_loop(b["loop"])
        if "shuffle" in b:
            A.aleatorio(bool(b["shuffle"]))
        if "auto" in b:
            A.ligar_auto(bool(b["auto"]))
        A.save_cfg()
        return j_ok()

    efeitos = fx.lista()

    @r.get("/api/effects")
    async def effects(_):
        return web.json_response(efeitos)

    @r.post("/api/effects/reload")
    async def effects_reload(_):
        # ajustar efeito sem reiniciar o servidor (e sem cortar a musica que toca)
        try:
            importlib.reload(fx)
            efeitos[:] = fx.lista()
            E.set_effect(E.effect if E.effect in {e["id"] for e in efeitos} else "nenhum")
        except Exception as ex:  # noqa: BLE001
            return j_err(f"Não consegui recarregar os efeitos ({str(ex)[:200]}).", 500)
        return j_ok(effects=len(efeitos), effect=E.effect)

    @r.get("/api/devices")
    async def devices(_):
        d = await loop_().run_in_executor(pool, eng.list_devices_live)
        return web.json_response({**d, "current": dict(E.devices), "active": dict(E.active)})

    @r.post("/api/devices")
    async def set_devices(request):
        b = await body(request)
        try:
            await loop_().run_in_executor(pool, lambda: E.set_devices(
                mic=b.get("mic"), out=b.get("out"), monitor=b.get("monitor")))
        except ValueError as ex:  # mensagem nossa, ja em portugues
            return j_err(str(ex)[:300])
        except Exception as ex:  # noqa: BLE001 - PortAudio fala ingles
            return j_err(f"Não consegui abrir esse dispositivo ({str(ex)[:160]}). "
                         "Voltei para o anterior; confira se ele está livre e conectado.")
        A.save_cfg()
        return j_ok()

    @r.get("/api/themes")
    async def themes(_):
        out = []
        for d in sorted(p for p in THEMES.iterdir() if (p / "index.html").exists()):
            meta = {}
            if (d / "meta.json").exists():
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            out.append({"slug": d.name, "url": f"/t/{d.name}/", **meta})
        return web.json_response(out)

    @r.post("/api/shutdown")
    async def shutdown(_):
        A.closing = True  # os SSE abertos terminam no proximo tick
        A.remember_pos()
        def _exit():
            raise GracefulExit()  # SystemExit: sai do asyncio.run, o finally fecha o audio
        loop_().call_later(0.3, _exit)
        return j_ok()

    @r.get("/api/events")
    async def events(request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-cache"})
        await resp.prepare(request)
        last = {"state": None, "library": -1, "jobs": None}

        async def send(ev, data):
            await resp.write(f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                             .encode("utf-8"))
        try:
            while not A.closing:
                s = A.snapshot()
                if s != last["state"]:
                    last["state"] = s
                    await send("state", s)
                if A.lib.version != last["library"]:
                    last["library"] = A.lib.version
                    await send("library", A.lib.public())
                jb = A.public_jobs()
                if jb != last["jobs"]:
                    last["jobs"] = [dict(x) for x in jb]
                    await send("jobs", jb)
                await send("tick", {"pos": round(E.pos, 2),
                                    "levels": {k: round(v, 4) for k, v in E.levels.items()}})
                await asyncio.sleep(TICK)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    @r.get("/api/lan")
    async def lan(request):
        return web.json_response({"url": f"http://{A.lan_ip}:{A.port}/" if A.lan_ip else None})

    @r.get("/favicon.ico")
    async def favicon(_):
        return web.Response(status=204)

    @r.get("/")
    async def index(_):
        return web.FileResponse(HERE / "gallery.html")

    @r.get("/t/{slug}/")
    async def theme_index(request):
        p = THEMES / request.match_info["slug"] / "index.html"
        if not p.exists() or THEMES not in p.resolve().parents:
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    @r.get("/t/{slug}")
    async def theme_redirect(request):
        raise web.HTTPFound(f"/t/{request.match_info['slug']}/")

    app = web.Application(middlewares=[guard])
    app.add_routes(r)
    app.router.add_static("/t/", THEMES, show_index=False)
    return app


def ip_da_rede():
    """IP do PC na rede de casa: a interface da rota padrao (connect de UDP nao manda nada)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith(("127.", "169.254.")) else ip


async def servir(A, app, porta, rede):
    """O que o web.run_app fazia, com a porta do celular sempre de pe. Ao dormir, o Windows derruba o Wi-Fi, o
    accept no IP da rede falha (WinError 64) e o asyncio fecha esse socket de vez: num notebook, o
    disco voltou a tocar ao abrir a tampa, mas o celular nunca mais achou o servidor. A cada REDE_VIGIA_S, se a
    porta do celular fechou ou o IP mudou, ela abre de novo no IP de agora (sem rede, tenta na volta seguinte)."""
    runner = web.AppRunner(app, handle_signals=True, shutdown_timeout=1)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", porta).start()
        sock = site = None
        falhou = False  # o erro de abrir sai no log uma vez, nao a cada volta
        while True:
            ip = ip_da_rede() if rede else None
            caiu = site is not None and sock.fileno() == -1
            if caiu or (site and ip and ip != A.lan_ip):
                print(f"celular: a porta em {A.lan_ip} caiu" if caiu
                      else f"celular: o IP mudou de {A.lan_ip} para {ip}", flush=True)
                await site.stop()
                sock.close()
                sock = site = None
            if site is None and ip:
                try:
                    sock = socket.create_server((ip, porta))
                    site = web.SockSite(runner, sock)
                    await site.start()
                except OSError as e:
                    if not falhou:
                        print(f"celular: sem a porta em {ip} ({e}); tento de novo a cada {REDE_VIGIA_S:.0f} s",
                              flush=True)
                    falhou = True
                    if sock:
                        sock.close()
                    sock = site = None
                else:
                    A.lan_ip, falhou = ip, False
                    print(f"celular: http://{ip}:{porta}/", flush=True)
            await asyncio.sleep(REDE_VIGIA_S)
    finally:
        await runner.cleanup()


def main():
    # o soundboard.ps1 manda a saida para arquivo, e ai o Python escreve em cp1252: um caractere fora dele (27/10,
    # uma seta num print) derrubava o pedido, e o "you're" do yt-dlp virava lixo no log
    for cano in (sys.stdout, sys.stderr):
        if cano:
            cano.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=pastas.PORTA)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--mock", action="store_true", help="sem audio: relogio falso, download fingido")
    ap.add_argument("--data-dir", default=str(LIB), help="onde moram library.json e config.json")
    ap.add_argument("--so-local", action="store_true", help="nao atende a rede de casa (celular)")
    ap.add_argument("--version", action="version", version=f"Vitrola {VERSAO}")
    a = ap.parse_args()
    A = App(a.port, Path(a.data_dir), mock=a.mock)
    threading.Thread(target=fora.aquece, daemon=True).start()  # o primeiro pedido ao YouTube ja acha o de reserva
    d = A.engine.active
    print(f"mic: {d['mic']} | cabo: {d['out']} | fone: {d['monitor'] or '-'}", flush=True)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Vitrola {VERSAO} em {url}{' (MOCK, sem som)' if a.mock else ''} | dados em {pastas.DADOS}", flush=True)
    if not a.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        asyncio.run(servir(A, build(A), a.port, rede=not (a.so_local or a.mock)))
    except (GracefulExit, KeyboardInterrupt):
        pass
    finally:
        A.engine.close()


if __name__ == "__main__":
    main()
