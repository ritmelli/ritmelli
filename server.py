"""Ritmelli: servidor local que toca audio no microfone do jogo (pelo filtro do Ritmelli, em microfone/) e
serve as interfaces de themes/. Contrato da API: API.md. Atende a propria maquina e o celular
pareado na rede de casa (para mexer enquanto joga; ver o pareamento.py). No PC, a interface abre numa janela
propria (janela.py), ou no navegador sem o WebView2; --no-browser nao abre nenhuma das duas.

    python server.py [--port 8799] [--no-browser] [--so-local]
    python server.py --mock --port 8801 [--data-dir <pasta>]   (sem som, pra testar tema; sem --data-dir, uma copia
                                                               da prateleira numa pasta temporaria)
"""
import argparse
import asyncio
import contextlib
import importlib
import json
import math
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import time
import types
import unicodedata
import uuid
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from aiohttp import web
from aiohttp.web_runner import GracefulExit

from microfone import microfone as filtro
from microfone import preset

import andamento as an
import atualizacao as atu
import comandos as cmd
import engine as eng
import fx
import i18n
import metricas as met
import pareamento as par
import permissao as perm
import pastas
import sonoridade
from pastas import save_json
from versao import VERSAO
from yt_erros import erro_do_video

HERE = Path(__file__).resolve().parent
LIB = pastas.LIB  # audio baixado; library.json e config.json moram em --data-dir
THEMES = HERE / "themes"
# o endereco do tema ate a 0.6.0, quando ele se chamava vitrola (#58): o celular pareado, o atalho na tela inicial e o
# favorito ainda abrem este, e o servidor leva cada caminho dele para o mesmo no tema de agora (o tema_de_antes)
TEMA_DE_ANTES = "/t/vitrola"
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_URL = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")
PAGINA_FOLGA = 8  # a busca pede tantos a mais na pagina de resultados: canal e playlist ocupam lugar e saem
TICK = 1 / 15
# a versao do contrato do Estado e do SSE (o "api" do snapshot, ver o API.md): sobe so quando muda o que um
# cliente de hoje ja le (um campo ou um evento sai, muda de nome ou de sentido); campo, evento ou rota nova nao sobe
API = 1
REMOTO_DURACAO_MAX_S = 24 * 3600  # a duracao que o remoto manda na fila: o visor (engine.Onda) aloca por ela
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
STREAM_RELIGA = 2  # enderecos novos que a parecida do Automatico ganha quando o stream cai, antes de passar adiante
TOCADAS_MAX = 2000  # GET /api/tocadas: os youtube_id que tocaram desde que o servidor subiu (o historico e do Anterior)
AUTO_FILA = 5  # o Automatico mantem tantas parecidas no fim do A seguir
AUTO_LOTE = 50  # quantas parecidas cada busca traz (o radio do YouTube Music da 50 em ~1 s, 21/10)
AUTO_DUR = (60, 600)  # fora disso nao entra: vinheta, compilado de 1 h, live sem fim
AUTO_ESPERA_S = 60.0  # busca de parecidas que falhou so tenta de novo depois disso
AUTO_JANELA_S = 3600  # a ordem por andamento escolhe entre as parecidas da proxima 1 h da lista
ANDAMENTO_APOS_S = 30.0  # o disco fica isso no prato antes de medir: pular de disco em disco nao le nada
ANDAMENTO_ESPERA_S = 600.0  # medida que falhou (stream fora do ar) so tenta de novo depois disso
CAPA_TAM = 544             # a capa do album do YouTube Music, quadrada, em px (o endereco aceita qualquer tamanho)
CAPA_PASSO_S = 2.0         # entre uma busca de capa e a proxima: a prateleira inteira sai devagar, sem rajada
SONORIDADE_PASSO_S = 2.0   # entre um disco da prateleira medido (volume automatico) e o proximo
ABAIXO_DO_NORMAL = 0x00004000  # prioridade do processo da medida no Windows: cede o processador ao audio

pool = ThreadPoolExecutor(4)
# o caminho do pedido falado (09/11): a /api/musica, o endereco adiantado e o canal que o endereco rapido nao traz, fora
# do pool dos downloads (o download segura a thread dele inteiro: com 3 ou 4 baixando, o adiantado esperava ate um
# acabar e o disco ficava carregando; revisao da r04)
pool_rapido = ThreadPoolExecutor(8, thread_name_prefix="ritmelli-rapido")
# a escolha de voz do pedal de troca de voz (o modulo de fora, ver o fx.py): numa thread so dela, na ordem dos pedidos,
# fora do pool dos downloads (com quatro baixando, a voz so trocava quando um acabasse; revisao da r03 da pedaleira). A
# thread e daemon (um escolhe() travado nao segura o processo nem a trava de instancia unica ao fechar), e cada pedido
# leva o Future que o handler espera
fila_voz = queue.SimpleQueue()
ESPERA_VOZ_S = 15   # o prazo do escolhe() do modulo (o contrato no API.md)


def _laco_voz():
    while True:
        fut, fn, arg = fila_voz.get()
        if not fut.set_running_or_notify_cancel():
            continue
        try:
            fut.set_result(fn(arg))
        except Exception as ex:  # noqa: BLE001 - o erro do modulo vai para quem pediu
            fut.set_exception(ex)
        except BaseException as ex:  # noqa: BLE001 - um SystemExit do modulo, relancado no handler, parava o laco do servidor
            fut.set_exception(RuntimeError(f"{type(ex).__name__}: {ex}"))


# com outro nome que a thread do liga() (o "pedal_voz" do engine.py): no log e no teste as duas se distinguem
threading.Thread(target=_laco_voz, name="pedal_voz_escolhe", daemon=True).start()


async def escolhe_voz(fn, voz, prazo=ESPERA_VOZ_S):
    """Pede a voz ao modulo na thread do pedal e espera ate o prazo: True quando ele voltou, False quando o prazo
    venceu (o pedido ainda na fila e cancelado e nao chega ao modulo; o que ja comecou acaba sozinho). O erro do modulo
    sobe como veio (um SystemExit dele chega como RuntimeError), inclusive um TimeoutError dele, que assim nao se
    confunde com o prazo (no Python 3.11 em diante o asyncio.TimeoutError do wait_for e o mesmo TimeoutError)."""
    fut = Future()
    fila_voz.put((fut, fn, voz))
    espera = asyncio.wrap_future(fut)
    try:
        feito, _ = await asyncio.wait({espera}, timeout=prazo)
    except asyncio.CancelledError:
        espera.cancel()
        raise
    if not feito:
        espera.cancel()
        return False
    espera.result()
    return True


# o canal que o endereco rapido nao traz sai so depois disso, com limite curto: ele so aparece na tela, e na hora em que
# o disco comeca ele tomava um processo de reserva de um "nao, toca Y" logo atras (revisao da r07)
CANAL_DEPOIS_S = 3.0
CANAL_LIMITE_S = 10.0
BUSCA_MUSICA_S = 4.0  # a busca do YouTube Music (/api/musica) que passa disso falha: quem pediu cai na do YouTube
# processos do YouTube abertos de reserva, com as bibliotecas carregadas (09/11: com um so, a busca antecipada da mina
# pegava a reserva e a busca do lote, logo atras, caia num processo frio, 1,3 a 1,55 s no placar)
RESERVAS = 2
FORA_LIMITE_S = 120.0  # pedido ao YouTube (fora o download) que nao volta nisso morre: o disco nao fica esperando
# o processo vivo dos enderecos (Fora._pede_vivo): quantos ele atende e por quanto tempo, antes de sair e o
# seguinte abrir outro. VIVO_MAX = 0 desliga: todo endereco num processo novo, como antes de 09/11
VIVO_MAX = 40
VIVO_MAX_S = 3600.0
# quantos vivos (cada um com o seu YoutubeDL quente): com um so, o endereco adiantado pelo palpite torto da mina
# ocupava o vivo e o do pedido certo, logo atras, caia num processo de reserva (0,55 s no placar r08, contra 0,15)
VIVOS = 2
# o erro do proprio video (indisponivel, privado, com idade: yt_erros.erro_do_video) nao e do processo: o vivo fica
# quente. Antes ele saia e o pedido seguinte pagava o vivo frio (0,51 e 0,55 s no placar r12, com o endereco
# especulativo de um candidato); "not a bot", 429, rate-limit e o resto seguem trocando o vivo
# os pedidos que vao de preferencia ao vivo: so o endereco (o mesmo YoutubeDL). A busca de musica no vivo nao ganhou
# nada (09/11, placar: ~0,7 s igual, o tempo e do YouTube Music) e ocupava o vivo na hora do endereco
VIVO_OPS = ("stream",)
# o aviso de que alguem comecou a falar (POST /api/aquece, a mina na fala que abre; r14): o YouTube fecha a conexao
# parada aos ~240 s, e com o Ritmelli parado o primeiro pedido pagava um TLS na busca e outro no endereco, em serie
# (~0,11 s cada), e o vivo vazio ainda o YoutubeDL novo. Fora.prepara renova o que esta parado ha mais disso e ja
# abre o vivo vazio. None desliga
AQUECE_OCIOSA_S = 180.0
# o endereco adiantado (09/11, a latencia do pedido falado): o do primeiro resultado da /api/musica sai logo atras da
# busca, enquanto a mina ainda poe na fila, e o tocar usa o que ja esta pronto ou a caminho. False desliga
ADIANTA = True
ADIANTA_S = 60.0  # o adiantado que ninguem tocou nisso some
# o endereco rapido (yt_fora.RAPIDO_ARGS, 09/11): so o cliente visionos, sem a pagina do video; falhou, o de sempre no
# mesmo processo. False = sempre o de sempre
ENDERECO_RAPIDO = True
REDE_VIGIA_S = 3.0  # a porta do celular se confere a cada isso, e se caiu (o PC dormiu) abre de novo


def nome_da_musica(titulo, inteiro=False):
    """O nome da musica no titulo, minusculo, sem acento e sem pontuacao: o que vem depois do " - ", sem parenteses nem
    colchetes ("O REI DA CACIMBINHA - MURIÇOCA (Ao Vivo)" -> "muricoca"), como o _musica da mina; inteiro = o titulo
    todo, so normalizado (onde a mina procura a que toca)."""
    t = titulo or ""
    if not inteiro:
        t = re.sub(r"[(\[].*?[)\]]", " ", t.split(" - ")[-1])
    t = "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z ]", " ", t).split())


def auxiliar(modo):
    """O comando de um processo auxiliar (--yt, --andamento; ver o ritmelli.py): no app congelado, o proprio
    executavel; no codigo, o mesmo caminho pelo python."""
    if getattr(sys, "frozen", False):
        return [sys.executable, modo]
    return [sys.executable, str(HERE / "ritmelli.py"), modo]


class Fora:
    """O YouTube pelo yt_fora.py (auxiliar --yt), num processo a parte (o audio estalava com o yt-dlp aqui dentro): um
    processo fica aberto de reserva, com as bibliotecas ja carregadas; cada pedido leva o de reserva e abre o
    proximo, e pedidos ao mesmo tempo nao esperam um pelo outro. O endereco de stream vai de preferencia a um
    processo que fica vivo (ver _pede_vivo)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reservas = []  # os abertos esperando pedido (ate RESERVAS), sob lock
        # os processos vivos dos enderecos (ate VIVOS): cada um com p (o processo), n (pedidos atendidos), desde e
        # a trava dele, sob a qual o resto se mexe
        # usado: o ultimo pedido ou aquecimento dele; aviso: aberto pelo aviso da fala (Fora.prepara)
        self.vivos = [types.SimpleNamespace(p=None, n=0, desde=0.0, usado=0.0, aviso=False, lock=threading.Lock())
                      for _ in range(VIVOS)]

    @staticmethod
    def _abre():
        # sem o cursor de carregando no mouse; o stderr (os erros do yt-dlp) vem por um cano e vai para o log do
        # servidor: herdar o stderr do servidor falha sem console (pelo pythonw, WinError 50 no DuplicateHandle)
        p = subprocess.Popen(auxiliar("--yt"), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", cwd=str(HERE), creationflags=eng.NO_WINDOW, startupinfo=eng.sem_cursor())
        threading.Thread(target=Fora._repassa, args=(p.stderr,), daemon=True).start()
        p.aquecido = time.monotonic()  # as conexoes dele abrem agora (Fora.prepara)
        return p

    @staticmethod
    def _repassa(cano):
        for linha in cano:
            if sys.stderr:
                print(linha, end="", file=sys.stderr, flush=True)

    def aquece(self):
        """Abre os de reserva que faltam ate RESERVAS."""
        while True:
            with self.lock:
                self.reservas = [p for p in self.reservas if p.poll() is None]
                if len(self.reservas) >= RESERVAS:
                    return
            p = self._abre()
            with self.lock:
                if len(self.reservas) < RESERVAS:
                    self.reservas.append(p)
                    p = None
            if p is not None:
                p.stdin.close()  # outra thread ja completou: este sai sem pedido
                p.wait()
                return

    def _tira_reserva(self):
        """Um de reserva (ou um novo, se nao ha), ja abrindo o que falta."""
        p = None
        with self.lock:
            while self.reservas and p is None:
                q = self.reservas.pop(0)
                if q.poll() is None:
                    p = q
        if p is None:
            p = self._abre()
        threading.Thread(target=self.aquece, daemon=True).start()
        return p

    def pede(self, op, progresso=None, limite=FORA_LIMITE_S, **args):
        """O resultado do pedido op (ver o yt_fora.py); progresso(f) recebe o andamento do download. Erro do
        YouTube vira RuntimeError com o motivo."""
        if op in VIVO_OPS and VIVO_MAX:
            # o livre quente antes do livre vazio: o vazio (o que saiu no VIVO_MAX ou no erro) paga o primeiro pedido
            # cheio, ~0,35 s, com o outro quente parado ao lado (k12 do placar r12b); todos ocupados, vai pelo de
            # reserva
            for v in sorted(self.vivos, key=lambda v: not self._quente(v)):
                if v.lock.acquire(blocking=False):
                    try:
                        return self._pede_vivo(v, op, limite, args)
                    finally:
                        v.lock.release()
        p, t0 = self._tira_reserva(), time.monotonic()
        estourou = threading.Event()
        relogio = threading.Timer(limite, lambda: (estourou.set(), eng.mata(p))) if limite else None
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
            raise RuntimeError("YouTube didn't answer in time" if estourou.is_set() else
                               "the YouTube process quit without an answer")
        if "erro" in r:
            raise RuntimeError(r["erro"])
        if op == "stream":
            print(f"stream: {time.monotonic() - t0:.2f} s in a new process"
                  f"{' (the live one was busy)' if VIVO_MAX else ''}", file=sys.stderr, flush=True)
        return r["r"]

    @staticmethod
    def _quente(v):
        """O vivo v tem um processo que atende o proximo pedido sem sair antes (lido sem a trava: so ordena a escolha)."""
        p = v.p
        return p is not None and p.poll() is None and time.monotonic() - v.desde <= VIVO_MAX_S

    def _pede_vivo(self, v, op, limite, args):
        """(sob v.lock) O pedido pelo processo vivo v: no yt_fora o YoutubeDL e o mesmo de um pedido ao outro e
        guarda o player do YouTube ja lido, e o endereco sai em 0,80 s em vez de 1,48 (notebook, 09/11). Um pedido
        por vez em cada um dos VIVOS: quem chega com todos ocupados vai pelo de reserva. Ele sai depois de VIVO_MAX
        pedidos ou
        VIVO_MAX_S, e no erro e no estouro do limite (o YouTube recusando pode ser estado velho dele); o seguinte
        abre outro com o de reserva."""
        p = v.p
        if p is not None and (p.poll() is not None or time.monotonic() - v.desde > VIVO_MAX_S):
            self._solta_vivo(v)
            p = None
        novo = p is None
        if novo:
            p = v.p = self._tira_reserva()
            v.n, v.desde, v.aviso = 0, time.monotonic(), False
        v.n += 1
        n, t0 = v.n, time.monotonic()
        estourou = threading.Event()
        relogio = threading.Timer(limite, lambda: (estourou.set(), eng.mata(p))) if limite else None
        if relogio:
            relogio.start()
        r = None
        try:
            p.stdin.write(json.dumps({"op": op, "vivo": True, **args}) + "\n")
            p.stdin.flush()
            while r is None:
                linha = p.stdout.readline()
                if not linha:
                    break  # o processo saiu (o relogio, ou caiu)
                try:
                    m = json.loads(linha)
                except ValueError:
                    continue
                if isinstance(m, dict) and ("r" in m or "erro" in m):
                    r = m
        except OSError:
            pass  # o cano fechou no meio: o processo morreu
        finally:
            if relogio:
                relogio.cancel()
        v.usado = time.monotonic()
        if r is None or n >= VIVO_MAX or ("erro" in r and not erro_do_video(r["erro"])):
            self._solta_vivo(v)
        if r is None:
            raise RuntimeError("YouTube didn't answer in time" if estourou.is_set() else
                               "the YouTube process quit without an answer")
        if "erro" in r:
            raise RuntimeError(r["erro"])
        print(f"{op}: {time.monotonic() - t0:.2f} s in the live process (its request #{n}"
              f"{', the first one pays full price' if novo else ', opened on the speech heads-up' if n == 1 and v.aviso else ''})",
              file=sys.stderr, flush=True)
        return r["r"]

    def prepara(self, opts, rapido):
        """Alguem comecou a falar (AQUECE_OCIOSA_S): o vivo livre parado ha mais disso (ou vazio, ou vencido) e a reserva
        aberta ha mais disso recebem o {"op": "aquece"} (yt_fora.aquece), que nao responde nada; o vivo vazio ja
        abre com o YoutubeDL do endereco. O pedido chega ~1 s depois (a fala, o detector, o Scribe). O vivo ocupado
        esta em uso, quente. Volta quantos aqueceu."""
        if AQUECE_OCIOSA_S is None:
            return 0
        feitos, agora = 0, time.monotonic()
        if VIVO_MAX and "stream" in VIVO_OPS:
            for v in self.vivos:
                if not v.lock.acquire(blocking=False):
                    continue
                try:
                    # o quase vencido tambem: o pedido chega uns segundos depois e o acharia vencido (revisao da r14)
                    if v.p is not None and (not self._quente(v) or agora - v.desde > VIVO_MAX_S - 60):
                        self._solta_vivo(v)
                    if v.p is None:
                        # so tira a reserva quente se sobrar outra: a busca chega antes do endereco e cairia num
                        # processo aberto agora (~1 s para ficar pronto; revisao da r14). Senao, um novo
                        with self.lock:
                            sobra = sum(1 for p in self.reservas if p.poll() is None) >= 2
                        v.p = self._tira_reserva() if sobra else self._abre()
                        v.n, v.desde, v.aviso = 0, agora, True
                    elif agora - v.usado <= AQUECE_OCIOSA_S:
                        continue
                    v.p.stdin.write(json.dumps({"op": "aquece", "vivo": True, "opts": opts, "rapido": rapido}) + "\n")
                    v.p.stdin.flush()
                    v.usado, feitos = agora, feitos + 1
                except OSError:
                    self._solta_vivo(v)  # o cano fechou: o processo morreu, o pedido abre outro
                finally:
                    v.lock.release()
        with self.lock:  # sob a trava: quem tira a reserva so escreve o pedido depois desta linha
            for p in self.reservas:
                if p.poll() is None and agora - getattr(p, "aquecido", agora) > AQUECE_OCIOSA_S:
                    try:
                        p.stdin.write(json.dumps({"op": "aquece"}) + "\n")
                        p.stdin.flush()
                        p.aquecido, feitos = agora, feitos + 1
                    except OSError:
                        pass  # morreu: o _tira_reserva pula a que saiu
        return feitos

    def _solta_vivo(self, v):
        """(sob v.lock) O vivo v sai: le o fim da entrada e termina; se nao terminar em 5 s, morre."""
        p, v.p = v.p, None
        if p is None:
            return
        try:
            p.stdin.close()
        except OSError:
            pass

        def espera():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                eng.mata(p)
                p.wait()
            p.stdout.close()
        threading.Thread(target=espera, daemon=True).start()


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


def capa_da_musica(r):
    """A capa quadrada (a do album) da faixa r da busca de musicas do YouTube Music em CAPA_TAM px, ou None: o endereco
    do googleusercontent traz o tamanho no fim (=w120-h120) e serve qualquer um."""
    ts = [t for t in r.get("thumbnails") or [] if t.get("url")]
    if not ts:
        return None
    url = max(ts, key=lambda t: t.get("width") or 0)["url"]
    return re.sub(r"=w\d+-h\d+", f"=w{CAPA_TAM}-h{CAPA_TAM}", url)


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
    def __init__(self, port, data_dir, mock=False, metricas_teste=False, vigias=True, relogio=True):
        """vigias=False e relogio=False sao dos testes (dev/testa_comandos.py): sem as threads dos vigias (quem testa
        chama cada volta, _volta_fila, _volta_passagem e _volta_auto, a mao) e, no --mock, sem o relogio de 10 ms do
        MockEngine (quem testa chama o engine._mixa)."""
        self.port = port
        self.mock = mock
        data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg_path = data_dir / "config.json"
        lib_json = data_dir / "library.json"
        if mock and not lib_json.exists() and (LIB / "library.json").exists():
            lib_json.write_text((LIB / "library.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.cfg = (json.loads(self.cfg_path.read_text(encoding="utf-8"))
                    if self.cfg_path.exists() else {})
        self.cfg_lock = threading.Lock()  # quem muda o cfg depois de ligar muda e grava com ela (grava_cfg)
        self.cfg.pop("lan_token", None)  # a chave do link do celular de antes, que saiu (hoje e o pareamento.py)
        self.lan_ip = None
        self.celulares = par.Pareamento(data_dir / "celulares.json")
        self.remotos = perm.Remotos()  # os tokens das sessoes remotas aceitas (permissao.py); por ora, nenhuma
        if fx.pistavoz is not None and callable(getattr(fx.pistavoz, "dados", None)):
            fx.pistavoz.dados(data_dir)  # as vozes e o estado do pedal de voz (no --mock, na pasta temporaria)
        self._adiantados = {}  # youtube_id -> (Future do endereco, hora em que saiu): ver adianta_endereco
        self._adi_lock = threading.Lock()
        self.lib = Library(lib_json, keep_files=mock)
        self.jobs = {}
        self.jobs_version = 0
        self.fila = []  # A seguir: entradas que tocam quando o disco do prato acaba
        self.fila_ordem = None  # Aleatorio ligado: a fila na ordem que o usuario montou, para voltar
        self.historico = []  # discos que sairam do prato, o mais recente no fim (o Anterior)
        # os youtube_id de todo disco que saiu do prato nesta sessao, sem teto curto e sem o Anterior tirar: quem pede
        # "outra do mesmo artista" (o bot) pula o que ja tocou hoje
        self.tocadas = []
        self.fila_lock = threading.Lock()
        # Automatico: a semente e o ultimo disco que o usuario escolheu; o mix, o Mix do YouTube ainda
        # nao usado de mix_base (a semente, ou a ultima parecida quando o da semente acaba);
        # fora, o que nao entra (tocou nesta sessao, ou o usuario tirou da fila). Vem ligado na instalacao nova; quem ja
        # usava guardou o "auto" no config.json (o save_cfg grava a cada mudanca) e segue como estava
        self.auto = bool(self.cfg.get("auto", True))
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
        # o volume automatico: o LUFS de quem tocou sem estar na prateleira (o stream das parecidas), por youtube_id; o
        # da prateleira mora no library.json, em cada disco ("lufs")
        self.sonoridades_path = data_dir / "sonoridades.json"
        self.sonoridades = (json.loads(self.sonoridades_path.read_text(encoding="utf-8"))
                            if self.sonoridades_path.exists() else {})
        self.sonoridade_falhou = set()  # os discos da prateleira que o ffmpeg nao mediu: nao tenta de novo
        self._son_lock = threading.Lock()
        self.parado_sem_fila = None  # disco que acabou com a fila vazia: a parecida que chegar toca
        self.preparando = None  # (disco, qid) da passagem sendo preparada (o stream leva 1 a 3 s)
        self.passagem_falhou = None  # (disco, qid) que nao deu para preparar: toca no fim, como antes
        self.closing = False
        # a janela propria (janela.py), quando ha: fechar ela desliga o servidor (pede_desligar), e o servidor que
        # para sozinho fecha ela (main). O loop e o desliga sao do servir e do build
        self.janela = None
        self.loop = None
        self.desliga = None
        self.pediu_desligar = False
        # a versao nova (atualizacao.py); sem endereco e chave, fica parada, e no --mock tambem (#128: nada vai a rede
        # sozinho, abaixo)
        self.atualizacao = atu.Atualizacao(ativa=False if mock else None)
        cls = eng.MockEngine if mock else eng.Engine
        self.cfg.pop("out", None)  # a saida pelo cabo saiu: a musica vai sempre pelo filtro do microfone
        self.engine = cls(mic=self.cfg.get("mic", "default"), monitor=self.cfg.get("monitor", "default"))
        if mock:
            self.engine.relogio = relogio
        self.engine.porta = port  # a mina chama a API daqui pelas ferramentas dela
        self.engine.religar_stream = self.religar_stream
        self.engine.sonoridade_de, self.engine.mediu = self.sonoridade_de, self.mediu
        self.engine.volume_auto = bool(self.cfg.get("volume_auto", True))
        self.cfg.pop("mic_vol", None)  # o nivel da voz e o do Windows, que guarda sozinho (18/10)
        for k in ("vol", "mon_vol", "monitor_on", "voice_mon_vol"):
            if k in self.cfg:
                v = self.cfg[k]
                setattr(self.engine, k, v if isinstance(v, bool) else max(0.0, min(1.0, float(v))))
        self.engine.liga()
        # os dados de uso e os erros (metricas.py, #102): so saem com a escolha de quem usa, e nunca no --mock. No
        # --mock, o metricas.json (o id e o dia) fica na pasta de dados dele; o --metricas-teste liga o aviso e a escolha
        # sem ler o instalador, e o envio so guarda na memoria
        self.metricas = met.Metricas(self.cfg, self.grava_cfg, mock=mock, teste=metricas_teste,
                                     **({"estado": data_dir / "metricas.json"} if mock else {}))
        self.metricas.instala_ganchos()
        if vigias:
            self._liga_vigias()

    def _liga_vigias(self):
        """As threads que acompanham o motor e a fila, cada uma no seu laco."""
        threading.Thread(target=self.metricas.vigia, args=(self.engine,), daemon=True, name="metricas").start()
        threading.Thread(target=self._vigia_fila, daemon=True).start()
        threading.Thread(target=self._conta_escuta, daemon=True).start()
        threading.Thread(target=self._vigia_auto, daemon=True).start()
        threading.Thread(target=self._vigia_passagem, daemon=True).start()
        threading.Thread(target=self._vigia_andamento, daemon=True).start()
        # (#128) no --mock nada vai a rede sozinho: as capas do YouTube Music, as parecidas do Automatico (mix_do, e com
        # elas a versao de audio e o andamento pelo stream), o aquecimento do processo do YouTube (main, /api/aquece) e
        # a versao nova ficam de fora. A prateleira de quem testa nao vira busca no YouTube Music, e o dev/compara.py
        # tira os mesmos prints toda vez. O que a pessoa pede (buscar, colar um link, tocar um resultado) vai ao YouTube
        if not self.mock:
            threading.Thread(target=self._vigia_capas, daemon=True).start()
        threading.Thread(target=self._vigia_sonoridade, daemon=True).start()
        if self.atualizacao.ativa:
            threading.Thread(target=self.atualizacao.vigia, daemon=True).start()

    def pede_desligar(self):
        """De qualquer thread (a janela fechou): o mesmo do botao Desligar, no loop do servidor. Antes de o loop
        subir, fica pedido e o servir desliga assim que sobe."""
        if self.pediu_desligar:
            return
        self.pediu_desligar = True
        if self.loop is not None and self.desliga is not None:
            try:
                self.loop.call_soon_threadsafe(self.desliga)
            except RuntimeError:
                pass  # o loop ja fechou: o servidor parou antes (o Desligar da pagina)

    def leitura(self):
        """O estado para a tela (o do motor mais a fila, o Aleatorio, o Automatico e quantos discos o Anterior tem) e a
        posicao do disco, da mesma captura: (estado, pos). A faixa, a posicao, o estado de reproducao, a fila e a virada
        que o motor ja confirmou saem juntos, sob a fila_lock e depois o _qlock do motor (a ordem do comandos.py), e a
        fila exposta ja nao tem a entrada da virada que o _volta_passagem ainda vai conciliar. O resto do motor e a
        formatacao ficam fora das travas. A posicao vai a parte: ela anda a cada bloco, e o SSE so manda o state quando
        ele muda (a posicao vai no tick da mesma volta)."""
        e = self.engine
        with self.fila_lock:
            with e._qlock:
                tr, pos, status, virou = e.track, e.pos, e.status(), e.virou
                tr = None if tr is None else dict(tr)
            fora = virou[2] if virou is not None else None
            fila = [dict(x) for x in self.fila if x["qid"] != fora]
            shuffle, auto, historico = self.fila_ordem is not None, self.auto, len(self.historico)
        snap = e.snapshot()
        snap.update(status=status, duration=None if tr is None else tr.get("duration"),
                    track=None if tr is None else self._com_bpm(  # o andamento ja medido, para o deck do tema
                        {k: v for k, v in tr.items() if k not in ("path", "headers")}))
        snap.update(queue=[self._com_bpm(x) for x in fila], shuffle=shuffle, auto=auto, history=historico,
                    versao=VERSAO, atualizacao=self.atualizacao.resumo())
        pv = self.pedal_voz()
        if pv is not None:
            snap["pedal_voz"] = pv
        return snap, pos

    _pedal_voz_erro = None   # o ultimo erro do estado() do pedal de voz: o log diz cada erro uma vez, nao a cada tick

    @classmethod
    def pedal_voz(cls):
        """O estado do pedal de troca de voz (o modulo de fora, ver o fx.py): a voz escolhida, o passo do visor e o
        progresso dele; None sem o modulo. Roda uma vez a cada volta do SSE, a mesma para as paginas abertas: o
        progresso vai em passos de 1/12 (a barra do visor tem 6 blocos), para o Estado inteiro nao mudar a cada leitura.
        Um estado que nao deu para ler sai como a primeira voz sem passo."""
        mod = fx.pistavoz
        if mod is None:
            return None
        try:
            e = dict(mod.estado() or {})
            cls._pedal_voz_erro = None
        except Exception as ex:  # noqa: BLE001 - o modulo e de fora: o estado dele nao derruba o do app
            msg = f"{type(ex).__name__}: {str(ex)[:120]}"
            if msg != cls._pedal_voz_erro:
                cls._pedal_voz_erro = msg
                print(f"pedal_voz: estado() failed ({msg})", file=sys.stderr, flush=True)
            e = {}
        visor = e.get("visor") if e.get("visor") in ("fale", "ouvindo", "pronto") else None
        prog = e.get("progresso")
        if visor == "ouvindo" and isinstance(prog, (int, float)) and not isinstance(prog, bool) and prog == prog:
            prog = round(round(max(0.0, min(1.0, float(prog))) * 12) / 12, 3)
        else:
            prog = None
        voz = e.get("voz")
        return {"voz": voz if voz in mod.VOZES else mod.VOZES[0], "visor": visor, "progresso": prog}

    def _com_bpm(self, x):
        """A entrada da fila para a tela, com o andamento do comeco dela quando ja foi medido."""
        t = self._tempo(x)
        b = t and (t.get("ini") or t.get("fim"))
        return dict(x, bpm=round(b, 1)) if b else dict(x)

    def grava_cfg(self, **mudancas):
        """Muda e grava o config.json sob uma trava so: as escolhas do som, as boas-vindas e as metricas vem de threads
        diferentes, e o json.dumps de uma nao pode ver o cfg mudando no meio (dictionary changed size during
        iteration), nem uma gravacao velha trocar o arquivo depois da nova."""
        with self.cfg_lock:
            self.cfg.update(mudancas)
            save_json(self.cfg_path, self.cfg)

    def save_cfg(self):
        e = self.engine
        self.grava_cfg(mic=e.devices["mic"], monitor=e.devices["monitor"],
                       vol=e.vol, mon_vol=e.mon_vol, monitor_on=e.monitor_on,
                       voice_mon_vol=e.voice_mon_vol, auto=self.auto, volume_auto=e.volume_auto)

    def boas_vindas_pendentes(self):
        """As boas-vindas aparecem na primeira vez: prateleira vazia e nunca fechadas. Quem ja usava o app antes delas
        (com disco na prateleira) nao ve."""
        return not self.cfg.get("boas_vindas") and not self.lib.items

    def boas_vindas_vistas(self):
        self.grava_cfg(boas_vindas=True)

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
        channel, uploader e duration) e os cabecalhos HTTP. O endereco rapido nao traz o canal: canal_depois."""
        r = fora.pede("stream", alvo=self.alvo_yt(target), opts=self.opts_stream(formato),
                      rapido=ENDERECO_RAPIDO and formato is None)
        return r["info"], r["hdr"]

    def canal_depois(self, tr, no_prato=False):
        """O canal do disco tr que veio sem (o endereco rapido pula o initial data, de onde o yt-dlp tira o canal), pelo
        YouTube Music, depois de o disco ja tocar: grava no proprio dict. Antes ele vinha junto do endereco, +0,15 a
        0,3 s no primeiro som do link colado (revisao da r04)."""
        yid = tr.get("youtube_id")
        if tr.get("channel") or not yid or not YT_ID.match(yid):
            return

        def faz():
            try:
                ch = fora.pede("canal", yid=yid, limite=CANAL_LIMITE_S).get("channel")
            except Exception as ex:  # noqa: BLE001 - fica sem o canal
                print(f"stream: the channel of {yid} didn't come ({yt_msg(ex)})", file=sys.stderr, flush=True)
                return
            if ch and not tr.get("channel"):
                tr["channel"] = ch
        def sai():  # no_prato: o disco que saiu nesse meio tempo (o "nao, toca Y") nao pede (revisao da r09)
            if not no_prato or self.engine.track is tr:
                pool_rapido.submit(faz)
        t = threading.Timer(CANAL_DEPOIS_S, sai)
        t.daemon = True
        t.start()

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
            # a pagina de resultados do YouTube, a mesma do site, com a correcao de digitacao dele: "ma meillere
            # enemy c'est toi" acha Ma Meilleure Ennemie. O ytsearch do yt-dlp desliga essa correcao e devolvia
            # nada pra pedido torto (03/11). Canal e playlist vem misturados na pagina: saem no filtro de id abaixo,
            # e a folga de PAGINA_FOLGA cobre o lugar deles pra fatia de start a start+n sair cheia.
            from urllib.parse import quote
            opts = {**opts, "playlistend": start + n + PAGINA_FOLGA}
            info = fora.pede("info", alvo=f"https://www.youtube.com/results?search_query={quote(q)}", opts=opts)
        out = []
        for e in list(info.get("entries") or []):
            yid = e.get("id")
            if not yid or not YT_ID.match(yid):
                continue
            out.append({"youtube_id": yid, "title": e.get("title"),
                        "duration": e.get("duration"),
                        "channel": e.get("channel") or e.get("uploader"),
                        "thumb": thumb(yid), "in_library": False})
        return out if alvo else out[start:start + n]

    def mock_download(self, j, target):
        # --mock: finge o download (3 s de progresso) e reaproveita um audio que ja existe
        for i in range(1, 11):
            time.sleep(0.3)
            self.job_update(j, progress=i / 10 * 0.99)
        bases = [x for x in self.lib.items if (LIB / x["file"]).exists()]
        if not bases:
            raise RuntimeError(f"--mock needs at least one audio file in {LIB}")
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
            raise RuntimeError("the download finished without an audio file")
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
                            error=i18n.msg("server.download.failed", "The download failed ({reason}). Check the "
                                           "link or try another video.", reason=yt_msg(ex)))
            tr = self.engine.track
            if tr is not None and tr.get("job") == j["id"] and (not tr.get("path") or self.engine.esperando_arquivo()):
                self.engine.stop()  # sem stream e sem arquivo: o prato nao fica carregando para sempre

    # tocar ----------------------------------------------------------------
    def remember_pos(self):
        e = self.engine
        if e.track is not None and e.status() in ("playing", "paused"):
            self.lib.update(e.track["id"], last_pos=round(e.pos, 1))

    def repetir_so_neste(self, novo_id):
        """O Repetir vale para o disco do prato (o "repetir uma" do Spotify): outro disco entrando desliga. O mesmo
        disco tocado de novo e o prato vazio (ligou antes de escolher) nao contam."""
        tr = self.engine.track
        if tr is not None and tr["id"] != novo_id:
            self.engine.set_loop(False)

    def play_item(self, item, start, loop=None, historico=True, extra=None):
        self.remember_pos()
        if historico:
            self.guardar_historico(item["id"])
        tr = dict(item, path=str(LIB / item["file"]), **(extra or {}))
        if loop is not None:
            self.engine.set_loop(loop)
        else:
            self.repetir_so_neste(item["id"])
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
        self.repetir_so_neste(tr["id"])
        self.engine.espera(tr)
        threading.Thread(target=self._abre_stream, args=(tr, target, bool(meta.get("title"))),
                         daemon=True).start()

    def adianta_endereco(self, yid):
        """Pede ja o endereco do stream de yid (o primeiro resultado da busca do pedido falado), sem tocar: o tocar
        que vier em ADIANTA_S usa este em vez de pedir outro."""
        if not ADIANTA or not yid or not YT_ID.match(yid):
            return
        agora = time.monotonic()
        with self._adi_lock:
            for k in [k for k, (_, t) in self._adiantados.items() if agora - t > ADIANTA_S]:
                del self._adiantados[k]
            if yid in self._adiantados:
                return
            fut = pool_rapido.submit(self.stream_info, yid)
            self._adiantados[yid] = (fut, agora)
        fut.add_done_callback(self._preabre)

    def _preabre(self, fut):
        """O endereco adiantado saiu: o ffmpeg dele ja abre (engine.PREABRE), e o tocar comeca sem esperar o ffmpeg."""
        if fut.cancelled() or fut.exception() is not None:
            return
        info, hdr = fut.result()
        try:
            self.engine.preabre(info.get("url"), hdr)
        except Exception as ex:  # noqa: BLE001 - sem o aberto antes, o leitor abre o dele como antes
            print(f"stream: the ffmpeg opened earlier failed ({str(ex)[:120]})", file=sys.stderr, flush=True)

    def adianta_da_busca(self, res, n):
        """O endereco que a busca de musica falada (/api/musica) adianta: ate 3 resultados, o do primeiro; o "outra" (n
        maior), o do primeiro que nao toca, nao esta na fila e nao tocou, como a mina escolhe (antes o outra nao
        adiantava nada: 0,47 s ate o som no placar r08). O da prateleira toca do arquivo: nada."""
        if not res:
            return
        x = res[0]
        if n > 3:
            tr = self.engine.track or {}
            fora = set(self.tocadas) | {tr.get("youtube_id")} | {f.get("youtube_id") for f in self.fila}
            atual = nome_da_musica(tr.get("title"))  # outra versao da que toca (o ao vivo dela) a mina pula
            x = next((r for r in res if r.get("youtube_id") not in fora
                      and not (len(atual) >= 4 and atual in nome_da_musica(r.get("title"), inteiro=True))), None)
        if x is not None and not x.get("in_library"):
            self.adianta_endereco(x["youtube_id"])

    def endereco_adiantado(self, yid):
        """O Future do endereco adiantado de yid (uma vez so), ou None."""
        with self._adi_lock:
            x = self._adiantados.pop(yid, None) if yid else None
            if x is not None and x[0] is not None:  # a marca do usado: a busca que chega depois (a da LLM, a do
                self._adiantados[yid] = (None, time.monotonic())  # lote) nao pede de novo o endereco do disco que ja
                # toca (revisao da r12: um endereco e um ffmpeg orfao a cada uso da antecipada)
        return x[0] if x and x[0] is not None and time.monotonic() - x[1] <= ADIANTA_S else None

    def _abre_stream(self, tr, target, tem_titulo):
        """O YouTube as vezes recusa o endereco do audio e na tentativa seguinte libera (um disco de 1h45 so tocou depois de baixar, calado). Tenta tres vezes, a ultima
        aceitando qualquer formato de audio; cada falha vai para o log com o motivo, e sem stream
        a tela diz que o disco toca quando terminar de baixar."""
        info = hdr = None
        motivo = ""
        adiantado = self.endereco_adiantado(tr.get("youtube_id"))
        if adiantado is not None and adiantado.cancel():  # nem comecou (o executor cheio): pede aqui mesmo
            adiantado = None
        for i, formato in enumerate((None, None, "bestaudio/best")):
            if self.engine.track is not tr:
                return  # trocou de disco no meio
            try:
                if i == 0 and adiantado is not None:
                    t0 = time.monotonic()
                    info, hdr = adiantado.result(timeout=FORA_LIMITE_S)
                    print(f"stream: the early request for {tr.get('youtube_id')} waited {time.monotonic() - t0:.2f} s more",
                          file=sys.stderr, flush=True)
                else:
                    info, hdr = self.stream_info(target, formato)
                break
            except Exception as ex:  # noqa: BLE001 - o motivo vai para o log e para a tela
                motivo = yt_msg(ex)
                print(f"stream: attempt {i + 1} of 3 failed for {target}: {motivo}", file=sys.stderr, flush=True)
                if erro_do_video(ex):  # o video nao toca pra ninguem: tentar de novo so gasta ~2 s e o IP de casa
                    break
                time.sleep(1.0)
        if info is None:
            if self.engine.track is not tr:
                return
            if tr["job"] is None:  # parecida do Automatico: nao vem download, pula para a seguinte
                if cmd.avanca(self, historico=False) is None:
                    self.engine.stop()
                return
            self.engine.error = i18n.msg("server.player.streamRefused", "YouTube didn't allow the audio to play "
                                                                        "right away ({reason}). It will play as soon "
                                                                        "as the download finishes.",
                                         reason=motivo)
            return
        yid = tr["youtube_id"] or info.get("id")
        novo = dict(tr, path=info["url"], headers=hdr, youtube_id=yid,
                    title=tr["title"] if tem_titulo else info.get("title") or tr["title"],
                    channel=tr["channel"] or info.get("channel") or info.get("uploader"),
                    thumb=tr["thumb"] or thumb(yid), duration=tr["duration"] or info.get("duration"))
        if self.engine.trocar_fonte(tr, novo):
            self.canal_depois(novo, no_prato=True)

    def religar_stream(self, tr, pos, desistir):
        """O leitor do motor (na thread dele): o stream da parecida do Automatico caiu em pos, sem audio ou antes do
        fim (o YouTube corta o endereco as vezes: 2 de ~15 em 27/10). Ate STREAM_RELIGA vezes por disco, um endereco
        novo toca de onde parou; depois disso, ou sem endereco, desistir() acaba o disco e a fila segue. Toda queda
        vai para o log."""
        nome = tr.get("title") or tr.get("youtube_id")
        quando = f"{int(pos // 60)}:{int(pos % 60):02d}"
        k = tr.get("religou", 0) + 1
        if k > STREAM_RELIGA:
            print(f"stream: {nome!r} dropped again at {quando} after {STREAM_RELIGA} new addresses: "
                  "moving on to the next one", file=sys.stderr, flush=True)
            desistir()
            return
        print(f"stream: {nome!r} dropped at {quando}: getting a new address ({k} of {STREAM_RELIGA})",
              file=sys.stderr, flush=True)
        try:
            info, hdr = self.stream_info(tr.get("youtube_id") or tr.get("alvo"))
        except Exception as ex:  # noqa: BLE001 - sem endereco, o disco acaba como antes
            print(f"stream: the new address of {nome!r} failed ({yt_msg(ex)}): moving on to the next one",
                  file=sys.stderr, flush=True)
            desistir()
            return
        self.engine.trocar_fonte(tr, dict(tr, path=info["url"], headers=hdr, religou=k))

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
        with self.fila_lock:
            self._guardar_historico(novo_id, tr)

    def _guardar_historico(self, novo_id=None, tr=None):
        """Com fila_lock: o guardar_historico (o entrada_de so le a prateleira, sem trava nem arquivo). A virada da
        passagem (comandos.avanca) guarda o que saiu sem soltar a trava de quando tirou a entrada da fila."""
        tr = tr or self.engine.track
        if tr is None or tr["id"] == novo_id:
            return
        if tr.get("youtube_id") and (not self.tocadas or self.tocadas[-1] != tr["youtube_id"]):
            self.tocadas.append(tr["youtube_id"])
            del self.tocadas[:-TOCADAS_MAX]
        x = self.entrada_de(tr)
        if x is None:
            return
        x["chave"] = tr["id"]
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

    def enfileirar(self, b, remoto=False):
        """Entrada da fila pelo corpo do POST /api/queue. Disco que nao esta na prateleira ja
        comeca a baixar, para estar pronto (ou quase) na vez dele. O remoto (permissao.py) so poe o disco da
        prateleira ou um video do YouTube, com a capa dele: nada de link de outro endereco para o PC baixar, nem de
        capa que o tema abriria."""
        iid = b.get("id")
        it = self.lib.get(iid or "") if not remoto or isinstance(iid, str) else None
        j = None
        if not it:
            target = b.get("youtube_id") or b.get("url") or ""
            if remoto and not isinstance(target, str):
                target = ""
            target = target.strip()
            if not target:
                raise ValueError("Send the id of a record on the shelf, a video id or a YouTube link.")
            m = YT_URL.search(target)
            yid = m.group(1) if m else (target if YT_ID.match(target) else None)
            if remoto and not yid:
                raise ValueError("A remote session can only queue a record on the shelf or a YouTube video.")
            if remoto and not (all(b.get(k) is None or isinstance(b[k], str) for k in ("title", "channel"))
                               and (b.get("duration") is None or (isinstance(b["duration"], (int, float))
                                                                  and not isinstance(b["duration"], bool)
                                                                  and 0 <= b["duration"] <= REMOTO_DURACAO_MAX_S))):
                # o tema e as passagens leem estes campos: texto (ou null) e a duracao em segundos (ou null, ate um dia)
                raise ValueError("A remote session sends title and channel as text and duration as seconds (up to a "
                                 "day).")
            if remoto:
                try:  # o texto vai a todo SSE: um substituto solto do JSON (\ud800) derrubaria o evento de todos
                    for v in (target, b.get("title"), b.get("channel")):
                        (v or "").encode("utf-8")
                except UnicodeEncodeError:
                    raise ValueError("A remote session sends text in valid Unicode.") from None
            it = self.lib.by_youtube(yid) if yid else None
        if it:
            x = {"id": it["id"], "youtube_id": it.get("youtube_id"), "url": None, "title": it["title"],
                 "channel": it.get("channel"), "thumb": it.get("thumb"), "duration": it.get("duration"),
                 "ytm_titulo": it.get("ytm_titulo"), "ytm_artista": it.get("ytm_artista"), "job": None}
        else:
            alvo = yid or target
            j = self.job_rodando(alvo)
            if j is None:
                j = self.new_job(b.get("title") or target, False, alvo)
                pool.submit(self.run_download, j, alvo)
            x = {"id": None, "youtube_id": yid, "url": None if yid else target,
                 "title": b.get("title") or target, "channel": b.get("channel"),
                 "thumb": thumb(yid) if remoto else b.get("thumb") or thumb(yid), "duration": b.get("duration"),
                 "job": j["id"]}
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
        """Tira o primeiro do A seguir (None com a fila vazia). Antes, sob a mesma fila_lock, fecha a virada que o motor
        ja confirmou e o _volta_passagem ainda nao conciliou (comandos.fecha_virada: o Anterior guarda o que saiu nela
        primeiro). O primeiro e escolhido sob o _qlock sem virada pendente: a virada so acontece com o _qlock na mao,
        entao ele nunca e a entrada que o motor ja pos no prato."""
        e = self.engine
        with self.fila_lock:
            while True:
                with e._qlock:
                    virou, e.virou = e.virou, None
                    if virou is None:
                        x = self.fila[0] if self.fila else None
                        break
                cmd.fecha_virada(self, virou)
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
        estava. O to e o lugar na fila que a tela ve (leitura): sem a entrada da virada que o motor ja confirmou e o
        _volta_passagem ainda vai conciliar, que tambem nao se move."""
        with self.fila_lock:
            with self.engine._qlock:
                virou = self.engine.virou
            fora = virou[2] if virou is not None else None
            x = next((e for e in self.fila if e["qid"] == qid and qid != fora), None)
            if not x:
                return False
            self.fila.remove(x)
            vistas = [e for e in self.fila if e["qid"] != fora]
            to = max(0, min(to, len(vistas)))
            self.fila.insert(self.fila.index(vistas[to]) if to < len(vistas) else len(self.fila), x)
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
            raise ValueError("the queue entry has no video and no link")
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
        """Quando o disco do prato acaba, o primeiro da fila entra (_volta_fila, a cada 0,1 s)."""
        visto = None
        while True:
            time.sleep(0.1)
            visto = self._volta_fila(visto)

    def _volta_fila(self, visto=None):
        """Uma volta do _vigia_fila: o disco do prato que acabou (e que nao e o visto, o da volta de antes) faz a fila
        avancar. O Repetir manda: ligado, o disco nao acaba. So a passagem para o fim conta aqui; com o prato ja
        parado, quem toca e o POST /api/queue (o que entra na fila toca na hora). Volta o visto da proxima volta."""
        e = self.engine
        soou = e.tira_soou()
        if soou:  # a hora do primeiro som de cada disco (relogio = a do Windows, pra alinhar com quem pediu)
            titulo, stream, entrou, em = soou
            print(f"sound: {titulo!r} played {em - entrou:.2f} s after entering the platter "
                  f"({'stream' if stream else 'file'}; clock={em:.3f})", file=sys.stderr, flush=True)
        tr = e.track
        if tr is None or e.status() != "ended":
            return None
        if visto is tr:
            return visto
        if cmd.avanca(self, na_tela=True) is None:
            self.parado_sem_fila = tr
        return tr

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
        d = {"id": yid or f"job-{j['id']}", "title": x.get("title") or info.get("title") or alvo,
             "channel": x.get("channel") or info.get("channel") or info.get("uploader"),
             "thumb": x.get("thumb") or thumb(yid), "duration": x.get("duration") or info.get("duration"),
             "youtube_id": yid, "alvo": None if yid else alvo, "path": info["url"], "headers": hdr,
             "stream": True, "job": None if auto else j["id"], **marca_auto(x)}
        self.canal_depois(d)
        return d

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
            print(f"transition: couldn't prepare {x.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
        finally:
            self.preparando = None

    def _vigia_passagem(self):
        """A passagem para a proxima (_volta_passagem, a cada 0,2 s)."""
        while True:
            time.sleep(0.2)
            self._volta_passagem()

    def _volta_passagem(self):
        """Uma volta do _vigia_passagem. A eng.TRANS_PREP_S do fim, prepara a primeira da fila no segundo deck do
        motor, que mede o fim deste disco e o comeco dela e vira sozinho no ponto certo; aqui so a fila e o historico
        acompanham a virada (o avanco da fila, sem tocar). Repetir ligado, disco sem duracao ou fila vazia: fica como
        antes (o _vigia_fila toca no fim). A fila que muda antes da virada troca a preparada; a que nao deu para
        preparar (sem stream, ou o comeco dela nao decodificou) toca no fim, sem nova tentativa."""
        e = self.engine
        v = e.virou
        if v is not None:
            try:
                cmd.avanca(self, virada=v)  # tira a virada do motor junto com a entrada dela da fila
            except Exception as ex:  # noqa: BLE001
                print(f"transition: the switch didn't close the queue: {ex}", file=sys.stderr, flush=True)
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
            return
        chave = (id(tr), x["qid"])
        if self.preparando is not None or chave == self.passagem_falhou:
            return
        self.preparando = chave
        threading.Thread(target=self._prepara, args=(tr, x, chave), daemon=True).start()

    # Automatico -------------------------------------------
    def mix_do(self, yid):
        """As parecidas do video, so o que cabe no Automatico (duracao entre AUTO_DUR, sem o proprio): o radio do
        YouTube Music (o catalogo de musicas, sem a versao com letra repetindo o clipe); sem a
        ytmusicapi, ou com ela falhando ou vazia, o Mix do YouTube. No --mock, nenhuma (#128)."""
        if self.mock:
            return []
        try:
            out = self.radio_do(yid)
            if out:
                return out
            motivo = "veio vazio"
        except Exception as ex:  # noqa: BLE001 - sem o radio, o Mix do YouTube segura o Automatico
            motivo = yt_msg(ex)
        print(f"auto: the YouTube Music radio of {yid} failed ({motivo}); using the YouTube Mix",
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
            print(f"auto: the Mix of {base} failed: {yt_msg(ex)}", file=sys.stderr, flush=True)
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
        parecida que tocou. As parecidas vao em ordem de andamento (_ordena_auto). Cada volta e o _volta_auto."""
        visto, sinal = None, None
        while True:
            time.sleep(0.5)
            visto, sinal = self._volta_auto(visto, sinal)

    def _volta_auto(self, visto=None, sinal=None):
        """Uma volta do _vigia_auto. visto: o youtube_id do prato na volta de antes; sinal: o que a ordem por
        andamento viu da ultima vez que ordenou. Volta os dois da proxima volta."""
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
                return visto, sinal
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
            cmd.avanca(self, na_tela=True)
        return visto, sinal


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

    # capa do album dos discos da prateleira ---------------------------
    @staticmethod
    def capa_musica(it):
        """A faixa do YouTube Music do disco da prateleira que veio de um video do YouTube, a da busca de musicas que e a
        mesma (mesma_faixa, a regra das parecidas): {"thumb": a capa do album ou None, "ytm_titulo": o nome da musica,
        "ytm_artista": os artistas}, ou None (musica so do YouTube, ou a busca so traz outras)."""
        for r in fora.pede("musicas", q=busca_de(it)):
            if r.get("videoId") and YT_ID.match(r["videoId"]) and mesma_faixa(it, r):
                artistas = ", ".join(a["name"] for a in r.get("artists") or [] if a.get("name"))
                return {"thumb": capa_da_musica(r), "ytm_titulo": r.get("title") or None, "ytm_artista": artistas or None}
        return None

    def _vigia_capas(self):
        """(07/11, pedido do dono) A capa do album no lugar da miniatura do video nos discos da prateleira, como as
        parecidas do Automatico: um disco por vez, CAPA_PASSO_S entre eles, uma vez so por disco (o capa_procurada fica
        no library.json; o disco novo entra na volta seguinte). Sem a mesma faixa no YouTube Music fica a miniatura do
        video; a dela fica guardada em thumb_video. Junto vem o nome da musica e o artista do YouTube Music (ytm_titulo,
        ytm_artista), que a etiqueta mostra no lugar do titulo do video."""
        while True:
            time.sleep(CAPA_PASSO_S)
            with self.lib.lock:
                alvo = next((dict(x) for x in self.lib.items
                             if not x.get("capa_procurada") and x.get("title") and x.get("duration")), None)
            if alvo is None:
                continue
            try:
                v = self.capa_musica(alvo)
            except Exception as ex:  # noqa: BLE001 - sem a busca, o disco fica com a miniatura e tenta de novo depois
                print(f"cover: couldn't look up {alvo.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
                time.sleep(60)
                continue
            kw = {"capa_procurada": True}
            if v:
                kw.update(ytm_titulo=v["ytm_titulo"], ytm_artista=v["ytm_artista"])
                if v["thumb"]:
                    kw.update(thumb=v["thumb"], thumb_video=alvo.get("thumb_video") or alvo.get("thumb"))
            self.lib.update(alvo["id"], **kw)
            print(f"cover: {alvo.get('title')!r}: " + (f"the album one ({v['ytm_artista']} - {v['ytm_titulo']})" if v
                                                        else "keeping the video one"), file=sys.stderr, flush=True)

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
        elif x.get("youtube_id") and not self.mock:  # no --mock, so o arquivo: o stream iria a rede sozinho (#128)
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
                    print(f"audio: couldn't look up {x.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
                    with self.fila_lock:
                        self.andamento_falhou[f"audio:{vid}"] = time.time()
                    continue
                # grava fora da fila_lock (o disco lento nao segura a fila) e so depois aplica, na ordem de antes: a
                # medida entra na memoria mesmo se a gravacao falha; a troca na fila e o andamentos_versao (a nova
                # ordem do Automatico) so vem com a gravacao feita
                with self.fila_lock:
                    versoes = {**self.versoes, vid: v}
                gravou = False
                try:
                    save_json(self.versoes_path, versoes)
                    gravou = True
                finally:
                    with self.fila_lock:
                        self.versoes[vid] = v
                        if gravou:
                            self._troca_audio(vid, v)
                            self.andamentos_versao += 1
                print(f"audio: {x.get('title')!r}: " + (f"the audio version {v['youtube_id']} ({v['duration']} s)"
                                                         if v else "only the video"), file=sys.stderr, flush=True)
                continue
            c = self.chave_andamento(x)
            t0 = time.time()
            try:
                r = self._mede_andamento(x)
            except Exception as ex:  # noqa: BLE001 - sem medida, a parecida fica sem andamento (vai para o salto)
                r = None
                print(f"tempo: couldn't measure {x.get('title')!r}: {yt_msg(ex)}", file=sys.stderr, flush=True)
            with self.fila_lock:
                if r is None:
                    self.andamento_falhou[c] = time.time()
                    continue
                andamentos = {**self.andamentos, c: r}
            gravou = False
            try:  # fora da fila_lock e antes de valer, como a versao de audio
                save_json(self.andamentos_path, andamentos)
                gravou = True
            finally:
                with self.fila_lock:
                    self.andamentos[c] = r
                    if gravou:
                        self.andamentos_versao += 1
            print(f"tempo: {x.get('title')!r}: start {r['ini']}, end {r['fim']} BPM in {time.time() - t0:.1f} s",
                  file=sys.stderr, flush=True)

    # volume automatico ---------------------------------------------------------
    def _disco_da_prateleira(self, tr):
        if tr.get("id") and self.lib.get(tr["id"]):
            return self.lib.get(tr["id"])
        return self.lib.by_youtube(tr["youtube_id"]) if tr.get("youtube_id") else None

    def sonoridade_de(self, tr):
        """O LUFS ja medido do disco (o motor pergunta quando ele entra no prato), ou None."""
        it = self._disco_da_prateleira(tr)
        if it is not None and it.get("lufs") is not None:
            return it["lufs"]
        return self.sonoridades.get(tr.get("youtube_id") or "")

    def mediu(self, tr, lufs):
        """O motor mediu o disco inteiro: a medida fica com ele na prateleira, ou no sonoridades.json."""
        it = self._disco_da_prateleira(tr)
        if it is not None:
            self.lib.update(it["id"], lufs=round(lufs, 1))
        elif tr.get("youtube_id"):
            with self._son_lock:
                self.sonoridades[tr["youtube_id"]] = round(lufs, 1)
                save_json(self.sonoridades_path, self.sonoridades)

    def _vigia_sonoridade(self):
        """Mede a prateleira, um disco por vez (o ebur128 do ffmpeg, abaixo do normal, ~1 s por disco), para o volume
        automatico ja saber o ganho quando ele entrar no prato; o que acabou de baixar entra na proxima volta. Nao mede
        com a passagem sendo planejada."""
        while True:
            time.sleep(SONORIDADE_PASSO_S)
            if self.closing or self.engine.planejando:
                continue
            x = next((x for x in self.lib.items if x.get("lufs") is None and x.get("file")
                      and x["id"] not in self.sonoridade_falhou and (LIB / x["file"]).is_file()), None)
            if x is None:
                continue
            lufs = sonoridade.mede_arquivo(LIB / x["file"], eng.FFMPEG, eng.NO_WINDOW | ABAIXO_DO_NORMAL,
                                           eng.sem_cursor())
            if lufs is None:
                self.sonoridade_falhou.add(x["id"])
                print(f"volume: nao medi {x.get('title')!r}", file=sys.stderr, flush=True)
                continue
            self.lib.update(x["id"], lufs=round(lufs, 1))

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


class Voltas:
    """A publicacao do SSE: uma volta a cada intervalo, montada uma vez para todas as conexoes abertas. A volta e a
    captura (o state e o tick saem do mesmo App.leitura) com cada evento ja em bytes; a conexao manda dela o que mudou
    desde a ultima que entregou, e o caps e a autorizacao ficam com a conexao. A que esta com o envio suspenso segura a
    sua volta inteira e, ao voltar, pula para a mais nova: as outras nao esperam por ela. Sem conexao aberta, nada e
    montado.

    monta(volta de antes ou None) -> dict da volta; o n (o numero dela) e daqui."""

    def __init__(self, monta, intervalo):
        self.monta, self.intervalo = monta, intervalo
        self.volta = None  # a ultima montada; None sem ninguem ligado (a proxima conexao nao recebe uma velha)
        self.n = 0  # quantas ja montou: so cresce, e a conexao que ficou de uma rodada antiga nao espera para sempre
        self.ouvintes = 0
        self._tarefa = self._nova = None  # o laco que monta e o futuro da proxima volta

    @contextlib.contextmanager
    def ouvinte(self):
        self.ouvintes += 1
        try:
            yield
        finally:
            self.ouvintes -= 1
            if not self.ouvintes:
                self.volta = None

    async def proxima(self, n):
        """A volta mais nova depois da de numero n (0: a de agora, se houver); sem ela ainda, espera a seguinte. O erro
        de montar a volta sobe para quem a espera, como quando cada conexao lia a sua."""
        while self.volta is None or self.volta["n"] <= n:
            if self._nova is None:
                self._nova = asyncio.get_running_loop().create_future()
            if self._tarefa is None or self._tarefa.done():
                self._tarefa = asyncio.ensure_future(self._gira())
            await asyncio.shield(self._nova)  # a conexao que fecha no meio nao cancela a espera das outras
        return self.volta

    async def _gira(self):
        while self.ouvintes:
            pronta, self._nova = self._nova, asyncio.get_running_loop().create_future()
            try:
                v = self.monta(self.volta)
            except Exception as ex:  # noqa: BLE001 - vai para quem espera esta volta; a proxima conexao recomeca
                self.volta = None
                pronta.set_exception(ex)
                pronta.exception()  # ninguem esperando: o asyncio nao reclama do erro sem leitor
                return
            self.n += 1
            v["n"], self.volta = self.n, v
            pronta.set_result(None)
            await asyncio.sleep(self.intervalo)


def j_ok(**kw):
    return web.json_response({"ok": True, **kw})


def j_err(m, status=400):
    """A recusa da API: m e a mensagem (i18n.msg, que o tema traduz, ou i18n.so_texto, a que nenhuma tela mostra)."""
    return web.json_response({"ok": False, "error": m}, status=status)


def sem_disco():
    return i18n.msg("server.library.missing", "That record is no longer on the shelf.")


def fora_da_fila():
    return i18n.msg("server.queue.gone", "That record has already left the queue.")


async def body(request):
    if not request.can_read_body:
        return {}
    await request.read()  # o corpo inteiro (o aiohttp guarda: o json() abaixo le dele)
    vale = request.get("ainda_vale")  # o remoto: a sessao pode ter acabado enquanto o corpo chegava (o guard)
    if vale is not None and not vale(request):
        raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": i18n.so_texto(
            "The remote session token is invalid or has expired.")}), content_type="application/json")
    try:
        b = await request.json()
    except (ValueError, LookupError, RecursionError):  # o JSON quebrado, o inteiro com digitos demais, o UTF-8
        # torto (o UnicodeDecodeError e um ValueError), o charset que nao existe e o aninhamento fundo demais
        raise web.HTTPBadRequest(text="The body must be JSON in UTF-8.")
    # toda rota le campos: uma lista ou um numero dava o erro 500, e o /api/parear e aberto a rede de casa
    if not isinstance(b, dict):
        raise web.HTTPBadRequest(text="The body must be a JSON object ({...}).")
    return b


def build(app_state):
    A = app_state
    E = A.engine
    loop_ = asyncio.get_running_loop
    locais = {f"127.0.0.1:{A.port}", f"localhost:{A.port}"}

    def do_pc(request):
        # pelo endereco de quem conectou: o Host quem pede escreve o que quiser
        return request.remote in ("127.0.0.1", "::1")

    def com_chave(resp, chave, velho=False):
        resp.set_cookie(par.COOKIE, chave, max_age=par.COOKIE_S, path="/", httponly=True, samesite="Strict")
        if velho:  # o celular pareado antes da troca de nome: fica so o cookie novo
            resp.del_cookie(par.COOKIE_VELHO, path="/")
        return resp

    def marca():
        # o "mock": true do /api/state, tambem no 401: as ferramentas de dev/ (dev/so_mock.py) so falam com o --mock
        return {"mock": True} if A.mock else {}

    # a recusa de quem nao pode, pela rota: as tres areas que tinham a frase propria seguem com ela
    so_no_pc = (
        ("/api/pareamento", "The connection code and connected phones can only be viewed on the computer."),
        ("/api/atualizacao", "New versions can only be installed from the computer."),
        ("/api/metricas", "Sending usage data and error reports can only be turned on or off on the computer."),
    )

    def recusa(request, papel, pode, chave):
        if papel == "publico" and "celular" in pode:
            # chave: a do cookie, ja sem a que nao e ASCII (o guard); com uma, o PC desconectou este aparelho
            return web.json_response({
                "ok": False, "parear": True, "desconectado": bool(chave),
                "error": i18n.msg("server.pair.required", "This phone isn't connected to Ritmelli. On the "
                                  "computer, click Phone and scan the QR code."),
                "caps": perm.caps(papel), **marca()}, status=401)
        if papel == "remoto":
            return j_err(i18n.so_texto("A remote session can't do this."), 403)
        frase = next((f for p, f in so_no_pc if request.path.startswith(p)), "This can only be done on the computer.")
        return j_err(i18n.so_texto(frase), 403)

    @web.middleware
    async def guard(request, handler):
        # Host fixo (DNS rebinding) e Origin conhecida em escrita (CSRF). Depois, a tabela de quem pode cada rota
        # (permissao.py): da rede de casa, so o tema e o pareamento sem a chave (pareamento.py); com ela, o que o
        # celular usa; o remoto (o token da sessao, so do 127.0.0.1), a lista dele; o resto, so o PC. O instalador
        # libera a entrada no firewall tambem no perfil Publico; --so-local fecha a rede. O IP da rede e o de agora:
        # a porta do celular pode reabrir em outro (servir)
        allowed = locais | {f"{A.lan_ip}:{A.port}"} if A.lan_ip else locais
        if request.host not in allowed:
            return web.Response(status=403, text="host not allowed")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] not in allowed:
                return web.Response(status=403, text="origin not allowed")
        rota = getattr(request.match_info.route.resource, "canonical", None)  # /api/library/{iid}, sem o id
        pode = perm.papeis(request.method, rota)
        token = request.headers.get(perm.REMOTO)
        chave = None
        if token is not None:
            # o cabecalho do remoto nunca cai no papel do PC: token que nao vale, ou de fora do 127.0.0.1, e 401
            if not (request.remote == "127.0.0.1" and A.remotos.vale(token)):
                return web.json_response({"ok": False, "error": i18n.so_texto(
                    "The remote session token is invalid or has expired."), **marca()}, status=401)
            papel = "remoto"
        elif do_pc(request):
            papel = "pc"
        else:
            chave = par.chave_do(request.cookies)
            chave = chave if chave and chave.isascii() else None  # a chave e ASCII: outra coisa no cookie nao vale
            # so a rota que o celular usa (e que nao e livre) marca o aparelho como visto; a livre (o tema, cada
            # arquivo dele) e a que nao e dele so olham a chave
            usa = "celular" in pode and "publico" not in pode
            pareado = A.celulares.confere(chave) if usa else A.celulares.vale(chave)
            papel = "celular" if pareado else "publico"
        if papel not in pode:
            return recusa(request, papel, pode, chave)
        request["papel"], request["remoto"] = papel, token
        if papel == "remoto":
            request["ainda_vale"] = ainda_vale  # o body() confere de novo depois de ler o corpo
        try:
            resp = await handler(request)
        except web.HTTPException:
            raise
        except Exception as ex:  # o erro que viraria um 500: vai para o Sentry (metricas.py) e segue igual
            A.metricas.erro(type(ex), ex, ex.__traceback__, f"api:{request.method} {rota or '?'}"[:80])
            raise
        if papel == "celular" and request.path == "/api/state":
            # cada abertura do tema renova o prazo do cookie
            com_chave(resp, par.chave_do(request.cookies), velho=par.COOKIE_VELHO in request.cookies)
        return resp

    def ainda_vale(request):
        """A conexao segue autorizada (o SSE pergunta a cada tick): o celular nao foi desconectado, a sessao remota
        nao acabou."""
        papel = request.get("papel")
        if papel == "celular":
            return A.celulares.vale(par.chave_do(request.cookies))
        if papel == "remoto":
            return A.remotos.vale(request.get("remoto"))
        return True

    r = web.RouteTableDef()

    def leitura():
        """O snapshot base, o mesmo para toda conexao: o App.leitura (o estado e a posicao da mesma captura) com o
        "api" e o "mock". O que e de cada conexao (o caps) entra depois."""
        s, pos = A.leitura()
        return {**s, "api": API, **marca()}, pos

    def evento(nome, dados):
        return f"event: {nome}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n".encode("utf-8")

    def monta_volta(antes):
        """A volta do SSE (Voltas): o state, a prateleira e os jobs com a chave de cada um e o evento em bytes, e o tick
        da mesma captura. O que nao mudou desde a volta de antes e o mesmo objeto: a conexao compara por identidade."""
        s, pos = leitura()
        jb = A.public_jobs()
        v = {"tick": evento("tick", {"pos": round(pos, 2), "levels": {k: round(x, 4) for k, x in E.levels.items()}})}
        for nome, chave, dados in (("state", s, lambda: s), ("library", A.lib.version, A.lib.public),
                                   ("jobs", [dict(x) for x in jb], lambda: jb)):
            v[nome] = antes[nome] if antes is not None and antes[nome][0] == chave else (chave, evento(nome, dados()))
        return v

    voltas = Voltas(monta_volta, TICK)

    @r.get("/api/state")
    async def state(request):
        # o caps: o que quem pede pode fazer (o papel do guard, permissao.caps)
        s, pos = leitura()  # o estado e a posicao da mesma captura
        return web.json_response({**s, "pos": round(pos, 2),
                                  "levels": dict(E.levels), "caps": perm.caps(request["papel"])})

    @r.get("/api/onda/{iid}")
    async def onda(request):
        # a onda do disco para o visor de DJ do tema (o formato no Engine.onda); o motor guarda as dos discos que
        # passaram pelo prato ou pela proxima, e o estado avisa quando uma fica pronta (visor.ondas)
        o = E.onda(request.match_info["iid"])
        if o is None:
            return j_err(i18n.so_texto("This record's waveform isn't ready yet."), 404)
        return web.json_response(o)

    @r.get("/api/library")
    async def library(_):
        return web.json_response(A.lib.public())

    @r.get("/api/tocadas")
    async def tocadas(_):
        """Os youtube_id que sairam do prato desde que o servidor subiu, o mais recente no fim."""
        return web.json_response(list(A.tocadas))

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
            return j_err(i18n.so_texto("The n and start parameters must be numbers (n from 1 to 20)."))
        if not q:
            return j_err(i18n.msg("server.search.empty", "Type what you want to search for, or paste a YouTube link."))
        try:
            res = await loop_().run_in_executor(pool, A.search, q, n, start)
        except Exception as ex:  # noqa: BLE001
            return j_err(i18n.msg("server.search.failed", "The YouTube search failed ({reason}). Check your "
                                  "internet connection and try again.", reason=yt_msg(ex)), 502)
        for x in res:
            it = A.lib.by_youtube(x["youtube_id"])
            x["in_library"] = bool(it)
            x["id"] = it["id"] if it else None
        return web.json_response(res)

    @r.get("/api/musica")
    async def busca_musica(request):
        """A busca de musica pelo YouTube Music (yt_fora.musica), no processo do YouTube como as outras: o pedido
        falado da mina usa esta e, se ela falha ou nao acha nada, a /api/search."""
        q = (request.query.get("q") or "").strip()
        try:
            n = max(1, min(20, int(request.query.get("n", 3))))
        except ValueError:
            return j_err(i18n.so_texto("The n parameter must be a number from 1 to 20."))
        if not q:
            return j_err(i18n.so_texto("Missing search text (q)."))
        try:
            res = await loop_().run_in_executor(
                pool_rapido, lambda: fora.pede("musica", q=q, n=n, limite=BUSCA_MUSICA_S))
        except Exception as ex:  # noqa: BLE001
            return j_err(i18n.so_texto(f"The YouTube Music search failed ({yt_msg(ex)})."), 502)
        for x in res:
            it = A.lib.by_youtube(x["youtube_id"])
            x["in_library"] = bool(it)
            x["id"] = it["id"] if it else None
        A.adianta_da_busca(res, n)
        return web.json_response(res)

    @r.post("/api/aquece")
    async def aquece_(_):
        """Alguem comecou a falar e pode pedir musica (a mina chama na fala que abre): as conexoes paradas com o
        YouTube e o vivo vazio ficam prontos antes do pedido (Fora.prepara). Responde na hora. No --mock, nada
        (#128)."""
        if A.mock:
            return j_ok(aquecidos=0)
        n = await loop_().run_in_executor(
            pool_rapido, lambda: fora.prepara(App.opts_stream(), ENDERECO_RAPIDO))
        return j_ok(aquecidos=n)

    @r.post("/api/library")
    async def lib_add(request):
        b = await body(request)
        target = (b.get("youtube_id") or b.get("url") or b.get("query") or "").strip()
        if not target:
            return j_err(i18n.so_texto("Send a YouTube link, a video ID, or search text."))
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
        return j_ok(item=it) if it else j_err(sem_disco(), 404)

    @r.delete("/api/library/{iid}")
    async def lib_del(request):
        # tirar da prateleira nao mexe no prato:
        # o disco que toca do arquivo segue ate sair, e o arquivo sai depois
        iid = request.match_info["iid"]
        it = A.lib.remove(iid)
        if it:
            A.apagar_audio(it["file"])
        A.esquecer(iid, it and it.get("youtube_id"))
        return j_ok() if it else j_err(sem_disco(), 404)

    # fila (A seguir): o primeiro toca quando o disco do prato acaba. A regra de cada comando de musica mora no
    # comandos.py: a rota le o corpo, chama o comando e responde
    @r.post("/api/queue")
    async def queue_add(request):
        b = await body(request)
        try:
            x, j, tocou = cmd.enfileirar(A, b, remoto=request["papel"] == "remoto")
        except cmd.CorpoRecusado as ex:
            return j_err(i18n.so_texto(str(ex)))
        return j_ok(entry=x, job=j, playing=tocou)

    @r.delete("/api/queue")
    async def queue_clear(_):
        cmd.limpar_fila(A)
        return j_ok()

    @r.delete("/api/queue/{qid}")
    async def queue_del(request):
        x = cmd.tirar_da_fila(A, request.match_info["qid"])
        return j_ok() if x else j_err(fora_da_fila(), 404)

    @r.post("/api/queue/move")
    async def queue_move(request):
        b = await body(request)
        try:
            to = int(b.get("to"))
        except (TypeError, ValueError):
            return j_err(i18n.so_texto("Missing the new position (to, starting at 0)."))
        if not cmd.mover_na_fila(A, b.get("qid"), to):
            return j_err(fora_da_fila(), 404)
        return j_ok()

    @r.post("/api/queue/play")
    async def queue_play(request):
        b = await body(request)
        if not cmd.tocar_da_fila(A, b.get("qid")):
            return j_err(fora_da_fila(), 404)
        return j_ok()

    # transporte do Spotify: Proxima toca o primeiro do A seguir; Anterior volta ao comeco do
    # disco ou toca o de antes
    @r.post("/api/next")
    async def next_(_):
        x = cmd.pular(A)
        if not x:
            return j_err(i18n.msg("server.queue.empty", "The queue is empty: there's no next record."), 409)
        return j_ok(entry=x)

    @r.post("/api/prev")
    async def prev(_):
        feito = cmd.voltar(A)
        if not feito:
            return j_err(i18n.msg("server.queue.noPrevious", "No record played before this one."), 409)
        return j_ok(did=feito)

    @r.post("/api/play")
    async def play(request):
        b = await body(request)
        feito = cmd.tocar(A, b.get("id", ""), start=b.get("start"), retomar=bool(b.get("resume")),
                          loop=b.get("loop"), por_cima=b.get("por_cima", cmd.CURTO))
        if feito is None:
            return j_err(sem_disco(), 404)
        return j_ok(por_cima=True) if feito == "por_cima" else j_ok()

    @r.post("/api/pause")
    async def pause(_):
        cmd.pausar(A)
        return j_ok()

    @r.post("/api/resume")
    async def resume(_):
        cmd.retomar(A)
        return j_ok()

    @r.post("/api/toggle")
    async def toggle(_):
        cmd.alternar(A)
        return j_ok()

    @r.post("/api/stop")
    async def stop(_):
        cmd.parar(A)
        return j_ok()

    @r.post("/api/seek")
    async def seek(request):
        b = await body(request)
        if "t" not in b:
            return j_err(i18n.so_texto("Missing the position to seek to (t, in seconds)."))
        cmd.ir_para(A, float(b["t"]))
        return j_ok()

    def volume(v):
        """Um volume do corpo, de 0 a 1 (fora disso, o limite); None se nao e um numero."""
        v = numero(v)
        return None if v is None else max(0.0, min(1.0, v))

    def numero(v):
        """O numero finito do corpo (o JSON true nao conta); None se nao e um."""
        if isinstance(v, bool):
            return None
        try:
            v = float(v)
        except (TypeError, ValueError, OverflowError):
            return None
        return v if math.isfinite(v) else None

    @r.post("/api/settings")
    async def settings(request):
        b = await body(request)
        vols = {k: volume(b[k]) for k in ("vol", "mon_vol", "voice_mon_vol") if k in b}
        ruim = next((k for k, v in vols.items() if v is None), None)
        if ruim:  # antes de mudar qualquer coisa
            return j_err(i18n.so_texto(f"The {ruim} must be a number from 0 to 1."))
        for k, v in vols.items():
            setattr(E, k, v)
        if "mic_vol" in b:
            E.set_mic_vol(b["mic_vol"])  # nivel do mic no Windows
        for k in ("mic_mute", "monitor_on", "voice_monitor", "volume_auto"):
            if k in b:
                setattr(E, k, bool(b[k]))
        if "effect" in b:
            try:
                E.set_effect(str(b["effect"]))
            except i18n.Recusa as ex:  # o id que nao existe, o preset que o filtro recusou
                return j_err(ex.msg)
            except ValueError as ex:  # outro erro do efeito: o texto, em ingles
                return j_err(i18n.so_texto(str(ex)[:300]))
        if "loop" in b:
            E.set_loop(b["loop"])
        if "shuffle" in b:
            A.aleatorio(bool(b["shuffle"]))
        if "auto" in b:
            A.ligar_auto(bool(b["auto"]))
        A.save_cfg()
        return j_ok()

    # o volume da musica no jogo, sozinho: o que o remoto pode mudar (o /api/settings segue com o vol para os temas, e
    # fora do remoto)
    @r.post("/api/volume")
    async def volume_(request):
        b = await body(request)
        v = numero(b.get("vol"))  # o limite de 0 a 1 e do comando
        if v is None:
            return j_err(i18n.so_texto("Missing the music volume (vol, a number from 0 to 1)."))
        return j_ok(vol=round(cmd.volume(A, v), 6))

    @r.post("/api/abaixa")
    async def abaixa(request):
        """Abaixa a musica no jogo por um tempo (quem fala por cima dela), sem gravar nada: volta sozinha no prazo."""
        b = await body(request)
        db, ms = numero(b.get("db")), numero(b.get("ms"))
        if db is None or ms is None or not (0 <= db <= eng.ABAIXA_MAX_DB and 0 <= ms <= eng.ABAIXA_MAX_MS
                                            and ms == int(ms)):
            return j_err(i18n.so_texto(f"Send db (0 to {eng.ABAIXA_MAX_DB:g}) and ms (a whole number from 0 to "
                                       f"{eng.ABAIXA_MAX_MS}); zero in either one ends the ducking."))
        E.abaixa(db, ms)
        return j_ok(abaixa=E.abaixamento())

    @r.post("/api/sinal")
    async def sinal(_):
        if not E.sinal():
            return j_err(i18n.so_texto("The microphone is muted: the test signal didn't play."), 409)
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
            preset.esquece()  # o filtro e o app montam o efeito do preset: o projetado com o fx.py velho sai
            efeitos[:] = fx.lista()
            E.set_effect(E.effect if fx.existe(E.effect) else "nenhum")  # o efeito que saiu da lista desliga
        except Exception as ex:  # noqa: BLE001
            return j_err(i18n.so_texto(f"Couldn't reload the effects ({str(ex)[:200]})."), 500)
        return j_ok(effects=len(efeitos), effect=E.effect)

    @r.post("/api/pedal_voz")
    async def pedal_voz(request):
        # a voz do pedal de troca de voz: so com o modulo dele (ver o fx.py); sem ele, o pedal nao existe
        mod = fx.pistavoz
        if mod is None:
            return j_err(i18n.so_texto("There's no voice changer pedal here."), 404)
        b = await body(request)
        voz = str(b.get("voz") or "")
        if voz not in mod.VOZES:
            return j_err(i18n.so_texto(f"Unknown voice \"{voz[:40]}\"."))
        try:
            # o modulo travado nao prende a tela na voz clicada: no prazo, 504; o erro dele (qualquer um), 500
            if not await escolhe_voz(mod.escolhe, voz):
                return j_err(i18n.so_texto("The voice changer pedal didn't answer."), 504)
        except Exception as ex:  # noqa: BLE001 - o modulo e de fora: o erro dele vira a resposta
            return j_err(i18n.so_texto(f"Couldn't change the voice ({str(ex)[:200]})."), 500)
        return j_ok(pedal_voz=A.pedal_voz())

    def _filtro_do_mic():
        """O filtro no microfone em uso: {"filtro", "melhorias"} (null se nao deu para ler)."""
        try:
            m = filtro.do_microfone(E.active.get("mic"))
        except Exception:  # noqa: BLE001 - sem ler o registro, a tela segue sem o estado do filtro
            return None
        return {"filtro": m["filtro"], "melhorias": m["melhorias"]} if m else None

    @r.get("/api/devices")
    async def devices(_):
        d = await loop_().run_in_executor(pool, eng.list_devices_live)
        f = await loop_().run_in_executor(pool, _filtro_do_mic)
        return web.json_response({**d, "current": dict(E.devices), "active": dict(E.active), "filtro": f})

    @r.post("/api/devices")
    async def set_devices(request):
        b = await body(request)
        try:
            await loop_().run_in_executor(pool, lambda: E.set_devices(mic=b.get("mic"), monitor=b.get("monitor")))
        except i18n.Recusa as ex:  # a nossa: o aparelho que sumiu
            return j_err(ex.msg)
        except Exception as ex:  # noqa: BLE001 - PortAudio fala ingles
            return j_err(i18n.msg("server.devices.openFailed", "Ritmelli couldn't open that device ({reason}) and "
                                                               "went back to the previous one. Make sure that device "
                                                               "is connected and that no recording or audio editing "
                                                               "program has taken exclusive control of it.", reason=str(ex)[:160]))
        A.save_cfg()
        return j_ok()

    # as boas-vindas da primeira vez, so no PC: e nele que se escolhe o microfone e o fone
    @r.get("/api/boas-vindas")
    async def boas_vindas(request):
        return web.json_response({"mostrar": do_pc(request) and A.boas_vindas_pendentes()})

    @r.post("/api/boas-vindas")
    async def boas_vindas_vistas(request):
        if not do_pc(request):
            return j_err(i18n.so_texto("The welcome screen is only available on the computer."), 403)
        A.boas_vindas_vistas()
        return j_ok()

    @r.get("/api/themes")
    async def themes(request):
        # o nome, a direcao e a frase podem vir por lingua no meta.json: vao na de quem pede, como a pagina
        lingua = i18n.escolher(request.query.get("lang"), request.headers.get("Accept-Language", ""))
        out = []
        for d in sorted(p for p in THEMES.iterdir() if (p / "index.html").exists()):
            meta = {}
            if (d / "meta.json").exists():
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            out.append({"slug": d.name, "url": f"/t/{d.name}/", **{k: i18n.na_lingua(v, lingua) for k, v in meta.items()}})
        return web.json_response(out, headers={"Vary": "Accept-Language"})

    def desliga():
        A.closing = True  # os SSE abertos terminam no proximo tick
        A.remember_pos()
        def _exit():
            raise GracefulExit()  # SystemExit: sai do asyncio.run, o finally fecha o audio
        loop_().call_later(0.3, _exit)

    A.desliga = desliga  # a janela fechando chama, pelo loop (App.pede_desligar)

    @r.post("/api/shutdown")
    async def shutdown(_):
        desliga()
        return j_ok()

    # o Ritmelli aberto de novo (o atalho clicado com ele ligado, ritmelli.py): a janela dele vem para a frente
    @r.post("/api/janela/foco")
    async def janela_foco(request):
        if not do_pc(request) or A.janela is None:
            return j_err("no window", 404)
        ok = await loop_().run_in_executor(pool, A.janela.foco)
        return j_ok() if ok else j_err("the window didn't come to the front", 409)

    # os dados de uso e os erros (metricas.py), so no PC: a situacao ("ligada", "desligada", "decidir" ou "fora") e o
    # endereco da politica; o POST e a escolha de quem usa (o aviso e o Microfone e fone), que vale sobre a do instalador
    @r.get("/api/metricas")
    async def metricas_get(_):
        return web.json_response(A.metricas.publico())

    @r.post("/api/metricas")
    async def metricas_post(request):
        b = await body(request)
        if not isinstance(b.get("ligar"), bool):
            return j_err(i18n.so_texto("Missing the choice (ligar: true or false)."))
        if A.metricas.situacao() == "fora":
            return j_err(i18n.so_texto("Usage data and error reports are off in this build."), 409)
        await loop_().run_in_executor(pool, A.metricas.escolhe, b["ligar"])
        return web.json_response(A.metricas.publico())

    # a versao nova (atualizacao.py), so no PC: e nele que o instalador roda
    @r.get("/api/atualizacao")
    async def atualizacao(_):
        return web.json_response(A.atualizacao.publico())

    @r.post("/api/atualizacao/consultar")
    async def atualizacao_consulta(_):
        await loop_().run_in_executor(pool, A.atualizacao.consultar)
        return web.json_response(A.atualizacao.publico())

    @r.post("/api/atualizacao/baixar")
    async def atualizacao_baixa(_):
        if not A.atualizacao.baixar():
            return j_err(i18n.msg("server.update.nothingToDownload", "There's no new version to download right now."), 409)
        return j_ok()

    @r.post("/api/atualizacao/instalar")
    async def atualizacao_instala(_):
        # espera a resposta do pedido de permissao do Windows, fora do loop
        ok, motivo = await loop_().run_in_executor(pool, A.atualizacao.instalar)
        if not ok:
            return j_err(motivo, 409)
        desliga()  # o instalador fecharia o Ritmelli; saindo antes, nada fica no meio de uma gravacao
        return j_ok()

    @r.get("/api/events")
    async def events(request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-cache"})
        await resp.prepare(request)
        if request["papel"] == "pc":
            A.atualizacao.ao_abrir()  # a pagina do PC abriu: consulta a versao nova, se faz tempo (atualizacao.py)
        try:
            # o papel nao muda na conexao: a revogacao a encerra
            await resp.write(evento("caps", perm.caps(request["papel"])))
            with voltas.ouvinte():
                n, entregue = 0, {}
                while not A.closing:
                    v = await voltas.proxima(n)  # a mesma volta de todas as conexoes (Voltas)
                    if A.closing:
                        break
                    if not ainda_vale(request):
                        # desconectado no PC, ou a sessao remota acabou: o tema pede o codigo sem esperar a reconexao
                        await resp.write(evento("desconectado", {}))
                        break
                    # o state e o tick desta volta saem da mesma captura, valendo ate o fim do envio dela, mesmo se o
                    # motor virar no meio: cada posicao e da faixa que esta volta entregou
                    for nome in ("state", "library", "jobs"):
                        if v[nome] is not entregue.get(nome):
                            entregue[nome] = v[nome]
                            await resp.write(v[nome][1])
                    await resp.write(v["tick"])
                    n = v["n"]
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    @r.get("/api/lan")
    async def lan(request):
        return web.json_response({"url": f"http://{A.lan_ip}:{A.port}/" if A.lan_ip else None})

    @r.post("/api/parear")
    async def parear(request):
        b = await body(request)
        # "482 913" vale. So 0 a 9: o \D deixa passar digito de outro alfabeto, e o compare_digest recusa com excecao
        codigo = re.sub(r"[^0-9]", "", str(b.get("codigo") or ""))
        nome = par.nome_do_aparelho(request.headers.get("User-Agent", ""))
        chave, motivo = A.celulares.parear(codigo, nome)
        if chave is None:
            if motivo == "queimado":
                return j_err(i18n.msg("server.pair.blocked", "Code blocked after too many incorrect attempts. On the "
                                                             "computer, generate a new code."), 403)
            return j_err(i18n.msg("server.pair.invalid", "Invalid or expired code. Each code is valid for {minutes} "
                                                         "minutes and can only be used once. Check the code shown on "
                                                         "the computer.",
                                  minutes=par.CODIGO_S // 60), 403)
        print(f"phone: paired ({nome})", flush=True)
        return com_chave(j_ok(), chave)

    @r.get("/api/pareamento")
    async def pareamento(request):
        # o tema manda o proprio caminho: o QR abre o mesmo tema no celular
        caminho = request.query.get("caminho", "/")
        if not re.fullmatch(r"/(t/[A-Za-z0-9_-]+/)?", caminho):
            caminho = "/"
        out = {"url": None, "codigo": None, "vale_s": 0, "queimado": False, "qr": None,
               "celulares": A.celulares.publico()}
        if A.lan_ip:
            codigo, vale_s = A.celulares.codigo_atual()
            out.update(url=f"http://{A.lan_ip}:{A.port}{caminho}", codigo=codigo, vale_s=vale_s,
                       queimado=codigo is None)
            if codigo:
                out["qr"] = par.qr(f"{out['url']}?parear={codigo}")
        return web.json_response(out)

    @r.post("/api/pareamento/codigo")
    async def outro_codigo(_):
        A.celulares.outro_codigo()
        return j_ok()

    @r.delete("/api/pareamento/{aid}")
    async def desconecta(request):
        if not A.celulares.desconecta(request.match_info["aid"]):
            return j_err(i18n.msg("server.phone.alreadyDisconnected", "That phone was already disconnected."), 404)
        return j_ok()

    # o icone vale para todo tema: a aba pede o /favicon.ico sozinha, e o iPhone o /apple-touch-icon.png
    # ao salvar na tela inicial (o Android so com o <link> no tema)
    @r.get("/favicon.ico")
    async def favicon(_):
        return web.FileResponse(HERE / "icone" / "ritmelli.ico")

    @r.get("/apple-touch-icon.png")
    async def icone_celular(_):
        return web.FileResponse(HERE / "icone" / "toque.png")

    @r.get("/")
    async def index(request):
        return await pagina_com_textos(request, HERE / "gallery" / "index.html")

    # antes do /t/{slug}/ e do static do /t/, que tambem casam com o /t/vitrola/... e dariam 404 (a pasta nao existe
    # mais): o aiohttp tenta as rotas do mesmo prefixo na ordem em que entraram. O mesmo caminho e a mesma query (o
    # ?parear= do QR, o ?lang=), e o 302, como o /t/{slug} logo abaixo: um 301 ficaria guardado no navegador e, de
    # volta a uma versao de antes, o /t/vitrola/ dela nunca mais abriria
    @r.get(TEMA_DE_ANTES + "{resto:(?:/.*)?}")
    async def tema_de_antes(request):
        destino = request.rel_url.with_path(pastas.PAGINA.rstrip("/") + (request.match_info["resto"] or "/"))
        raise web.HTTPFound(destino.with_query(request.rel_url.query))

    @r.get("/t/{slug}/")
    async def theme_index(request):
        p = THEMES / request.match_info["slug"] / "index.html"
        if not p.exists() or THEMES not in p.resolve().parents:
            raise web.HTTPNotFound()
        return await pagina_com_textos(request, p)

    async def pagina_com_textos(request, p):
        """Uma pagina com a pasta i18n/ ao lado (um tema, a galeria): os textos da lingua de quem abre (i18n.py) vao
        dentro dela. O ETag muda com a pagina, com os textos e com a lingua: a pagina igual a que o navegador ja tem
        volta como 304, sem baixar o 1,2 MB do tema de novo"""
        textos = p.parent / "i18n"
        lingua = i18n.escolher(request.query.get("lang"), request.headers.get("Accept-Language", ""))
        etag = f'"{p.stat().st_mtime_ns}-{i18n.versao(textos)}-{lingua}"'
        cab = {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Language"}
        if etag in (x.strip() for x in request.headers.get("If-None-Match", "").split(",")):
            return web.Response(status=304, headers=cab)
        html = await asyncio.get_running_loop().run_in_executor(
            None, lambda: i18n.injeta(p.read_text(encoding="utf-8"), textos, lingua))
        return web.Response(text=html, content_type="text/html", headers=cab)

    @r.get("/t/{slug}")
    async def theme_redirect(request):
        raise web.HTTPFound(f"/t/{request.match_info['slug']}/")

    app = web.Application(middlewares=[guard])
    app.add_routes(r)
    app.router.add_static("/t/", THEMES, show_index=False)

    async def tema_sem_guardar(request, resp):
        # todo arquivo do tema (o .js, o .css, a fonte) como a pagina: o navegador confere com o servidor antes de
        # usar o que guardou (o que nao mudou volta como 304, sem o corpo), e nao usa um arquivo de antes sem conferir
        if request.path.startswith("/t/"):
            resp.headers.setdefault("Cache-Control", "no-cache")
    app.on_response_prepare.append(tema_sem_guardar)
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
    A.loop = asyncio.get_running_loop()
    A.metricas.no_loop(A.loop)
    if A.pediu_desligar:  # a janela fechou antes de o servidor subir
        A.desliga()
    try:
        await web.TCPSite(runner, "127.0.0.1", porta).start()
        sock = site = None
        falhou = False  # o erro de abrir sai no log uma vez, nao a cada volta
        while True:
            ip = ip_da_rede() if rede else None
            caiu = site is not None and sock.fileno() == -1
            if caiu or (site and ip and ip != A.lan_ip):
                print(f"phone: the port on {A.lan_ip} went down" if caiu
                      else f"phone: the IP changed from {A.lan_ip} to {ip}", flush=True)
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
                        print(f"phone: no port on {ip} ({e}); trying again every {REDE_VIGIA_S:.0f} s",
                              flush=True)
                    falhou = True
                    if sock:
                        sock.close()
                    sock = site = None
                else:
                    A.lan_ip, falhou = ip, False
                    print(f"phone: http://{ip}:{porta}/", flush=True)
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
    ap.add_argument("--mock", action="store_true", help="no audio: fake clock, pretend downloads")
    ap.add_argument("--data-dir", help="where library.json and config.json live (default: the user's; with --mock, a "
                                       "new temporary folder, never the user's)")
    ap.add_argument("--so-local", action="store_true", help="don't serve the home network (phone)")
    ap.add_argument("--metricas-teste", action="store_true",
                    help="with --mock: the usage data notice and choice work, but nothing is read from the installer "
                         "and nothing is sent (the events stay in memory)")
    ap.add_argument("--version", action="version", version=f"Ritmelli {VERSAO}")
    a = ap.parse_args()
    if a.metricas_teste and not a.mock:
        sys.exit("--metricas-teste only works with --mock")
    dados = Path(a.data_dir) if a.data_dir else LIB
    if a.mock:  # o download de mentira na pasta de quem usa virava disco falso na prateleira (#117)
        dados = pastas.dados_do_mock(a.data_dir)
        if dados is None:
            sys.exit(f"--mock never uses the user's data ({a.data_dir}): pass another --data-dir, or none for a "
                     "temporary copy")
    A = App(a.port, dados, mock=a.mock, metricas_teste=a.metricas_teste)
    if not a.mock:  # no --mock, o processo do YouTube so abre no primeiro pedido de quem testa (#128)
        threading.Thread(target=fora.aquece, daemon=True).start()  # o primeiro pedido ao YouTube ja acha o de reserva
    d = A.engine.active
    print(f"mic: {d['mic']} | headphones: {d['monitor'] or '-'}", flush=True)
    url = f"http://127.0.0.1:{a.port}{pastas.PAGINA}"
    print(f"Ritmelli {VERSAO} at {url}{' (MOCK, no sound)' if a.mock else ''} | data in {dados if a.mock else pastas.DADOS}",
          flush=True)
    # a janela propria (janela.py, #99), quando o WebView2 esta no PC; senao, a pagina no navegador, como antes.
    # --no-browser (a atualizacao reabrindo, os testes) nao abre nenhuma das duas
    if not a.no_browser:
        import janela
        A.janela = janela.se_der(url)
        if A.janela is None:
            threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    if A.janela is None:
        roda(A, a)
        return
    # a janela tem de rodar na thread principal: o servidor vai para outra. Fechar a janela desliga o servidor; o
    # servidor que para sozinho (o Desligar da pagina, a atualizacao) fecha a janela
    t = threading.Thread(target=roda, args=(A, a), name="servidor")
    t.start()
    try:
        A.janela.abre(ao_fechar=A.pede_desligar)
    finally:
        A.pede_desligar()
        t.join(timeout=20)


def roda(A, a):
    """O servidor ate desligar, e o audio fechado no fim. Com a janela, ela fecha junto."""
    try:
        asyncio.run(servir(A, build(A), a.port, rede=not (a.so_local or a.mock)))
    except (GracefulExit, KeyboardInterrupt):
        pass
    finally:
        A.metricas.fecha()  # o uso ate aqui e o que ficou na fila, antes de o audio fechar (no maximo 3 s sem rede)
        A.engine.close()
        if A.janela is not None:
            A.janela.fecha()


if __name__ == "__main__":
    main()
