"""Os dados de uso e os erros do Ritmelli (#102), para saber quantas pessoas usam, se a versao nova esta chegando, que
erro acontece agora e o que se usa de verdade (cada efeito de voz, a musica). O que vai, para onde e como desligar
esta no PRIVACIDADE.md, na raiz do repo; a SignPath pede que a politica apareca na instalacao e que de para desligar
la (o ritmelli.iss), e o app tambem desliga, no Microfone e fone.

Quem decide se envia: a escolha feita no Ritmelli (o "metricas" do config.json), senao a da pagina do instalador (o
Metricas do HKLM\\SOFTWARE\\Ritmelli, 1 ou 0). Sem nenhuma das duas (quem atualizou em silencio de uma versao sem
metricas), nada sai ate a pessoa ver o aviso na tela e escolher. Pelo codigo e no --mock, nunca envia
(RITMELLI_METRICAS=1 liga nos dois, para testar).

O que vai, sempre com um ID aleatorio da instalacao (o metricas.json da pasta de dados; o desinstalador apaga), a
versao, a do Windows e a lingua: um "ativo" por dia de uso, o "atualizou" na primeira vez de uma versao nova, o
"efeito" quando um efeito de voz liga e, a cada meia hora e ao fechar, o "uso" (os segundos de musica e de voz com
efeito) e um "efeito_tempo" por efeito usado (os segundos dele). Os erros vao para o Sentry, com a pilha (arquivo, funcao e linha) e a mensagem sem o que
esta entre aspas, sem endereco e sem caminho. Nunca vai nome, conta, musica, busca, link, audio, voz nem o nome de
um aparelho: o EVENTOS abaixo e a lista inteira, e o dev/testa_metricas.py confere.

As chaves daqui so enviam (o PostHog e o Sentry chamam de chave publica): podem morar no codigo aberto."""
import ctypes
import json
import os
import platform
import queue
import re
import sys
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import date
from pathlib import Path

import pastas
from versao import VERSAO

POSTHOG = "https://eu.i.posthog.com/batch/"
POSTHOG_CHAVE = "phc_yK9GS3bzj4qdDhYSGgPpfD7zpXcxA9GoRPJFw7xAkhoa"
SENTRY_DSN = "https://44a4c1749ce862fbfeb8b3153468aeb9@o4512454104907776.ingest.de.sentry.io/4512454111395920"
POLITICA = "https://github.com/ritmelli/ritmelli/blob/main/PRIVACIDADE.md"
ESTADO = pastas.DADOS / "metricas.json"
REG, REG_VALOR = r"SOFTWARE\Ritmelli", "Metricas"

USO_S = 30 * 60  # de quanto em quanto tempo sai o "uso"
AMOSTRA_S = 5.0  # de quanto em quanto tempo o motor e olhado
ENVIO_S = 60.0  # os eventos saem juntos, no maximo uma vez por minuto
FILA_MAX = 500  # sem rede por muito tempo, o mais velho sai
ERROS_POR_SESSAO = 20
TEMPO_S = 10.0

# a lista inteira do que pode ir: o evento e as propriedades dele (alem das COMUNS). O que nao esta aqui nao sai
EVENTOS = {
    "ativo": {"primeira_vez"},
    "atualizou": {"de"},
    "efeito": {"efeito"},
    "uso": {"musica_s", "voz_s"},
    "efeito_tempo": {"efeito", "segundos"},  # um por efeito usado, junto do "uso": o painel soma por efeito
}
COMUNS = {"versao", "windows", "lingua", "sessao"}
SEM_EFEITO = "nenhum"


def _lingua():
    """A lingua do Windows de quem usa (pt-BR, en-US): a da interface do sistema, que e a da tela do Ritmelli."""
    if sys.platform != "win32":
        return ""
    buf = ctypes.create_unicode_buffer(85)
    try:
        k32 = ctypes.windll.kernel32
        if k32.LCIDToLocaleName(k32.GetUserDefaultUILanguage(), buf, 85, 0):
            return buf.value[:20]
    except (AttributeError, OSError):
        pass
    return ""


def escolha_do_instalador():
    """O que a pagina do instalador gravou: True, False, ou None (nao passou por ela)."""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            v = winreg.QueryValueEx(k, REG_VALOR)[0]
    except OSError:
        return None
    return bool(int(v)) if str(v).strip() in ("0", "1") else None


def limpa(txt):
    """A mensagem de um erro sem o que pode ser da pessoa: o que esta entre aspas (um titulo, um arquivo, uma busca),
    endereco e caminho. Fica o tipo do problema ("[Errno 2] No such file or directory: '...'")."""
    txt = re.sub(r"[a-z][a-z0-9+.-]*://\S+", "<url>", str(txt), flags=re.I)
    txt = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "'...'", txt)
    txt = re.sub(r"\b[A-Za-z]:[\\/][^\s,;:)]*", "<path>", txt)
    txt = re.sub(r"\\\\[^\s,;:)]+", "<path>", txt)
    txt = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", txt)
    return txt[:300]


# os modulos do Ritmelli: a linha da pilha num deles e "do app" (o Sentry agrupa e destaca por ela)
NOSSOS = {"andamento", "atualizacao", "atualizador", "batida", "compasso", "engine", "fx", "i18n", "janela",
          "metricas", "microfone", "pareamento", "pastas", "ritmelli", "server", "versao", "winvol", "yt_erros",
          "yt_fora"}


def _arquivo(caminho):
    """O caminho do arquivo de uma linha da pilha sem a pasta de quem usa: o do app relativo a ele (server.py,
    microfone/injeta.py), o de biblioteca a partir dela (aiohttp/web_protocol.py). Volta (arquivo, e do app)."""
    p = str(caminho).replace("\\", "/")
    for raiz in (str(pastas.APP), str(Path(__file__).resolve().parent)):
        raiz = raiz.replace("\\", "/").rstrip("/") + "/"
        if p.lower().startswith(raiz.lower()):
            p = p[len(raiz):]
            break
    else:
        for m in ("site-packages/", "_internal/", "/Lib/", "/lib/"):
            i = p.rfind(m)
            if i >= 0:
                p = p[i + len(m):]
                break
        else:
            if re.match(r"[A-Za-z]:/|/", p):  # outro caminho inteiro: so o nome
                p = p.rsplit("/", 1)[-1]
    if p.startswith("_internal/"):
        p = p[len("_internal/"):]
    return p, p.split("/", 1)[0].removesuffix(".py") in NOSSOS


def evento_de_erro(tipo, valor, tb, onde, base):
    """O evento do Sentry de uma excecao (e das que vieram antes dela, ate 3), sem variavel, sem codigo e sem
    caminho de quem usa."""
    cadeia, e, vistos = [], valor, set()
    while e is not None and len(cadeia) < 3 and id(e) not in vistos:
        vistos.add(id(e))
        cadeia.append(e)
        e = e.__cause__ or e.__context__
    valores = []
    for i, ex in enumerate(reversed(cadeia)):
        t = type(ex) if i < len(cadeia) - 1 or tipo is None else tipo
        quadros = []
        for q in traceback.extract_tb(ex.__traceback__ if ex is not valor else tb)[-40:]:
            arq, do_app = _arquivo(q.filename)
            quadros.append({"filename": arq, "function": q.name, "lineno": q.lineno, "in_app": do_app})
        valores.append({"type": t.__name__, "module": t.__module__ if t.__module__ != "builtins" else None,
                        "value": limpa(ex), "stacktrace": {"frames": quadros}})
    return {
        "event_id": uuid.uuid4().hex, "timestamp": time.time(), "platform": "python", "level": "error",
        "logger": onde, "release": f"ritmelli@{VERSAO}", "environment": "app",
        "user": {"id": base["id"]},
        "tags": {"onde": onde, "windows": base["windows"], "lingua": base["lingua"]},
        "contexts": {"os": {"name": "Windows", "version": base["windows"]},
                     "runtime": {"name": "CPython", "version": platform.python_version()}},
        "exception": {"values": valores},
    }


def _posta(url, dados, cabecalhos):
    """Um POST com as raizes do Windows e do certifi (as mesmas da consulta da versao nova). Falha calada: sem rede,
    o evento fica para a proxima."""
    from atualizacao import _tls
    req = urllib.request.Request(url, data=dados, method="POST",
                                 headers={"User-Agent": f"Ritmelli/{VERSAO}", **cabecalhos})
    with urllib.request.urlopen(req, timeout=TEMPO_S, context=_tls()) as r:
        return r.status


class Metricas:
    """O envio, de uma thread so. cfg e o config.json do app (o metricas que a pessoa escolheu no Ritmelli mora nele);
    gravar e quem grava o config (App.save_cfg). Sem ligar(), nada sai."""

    def __init__(self, cfg, gravar, mock=False, estado=ESTADO):
        self.cfg, self.gravar, self.estado_path = cfg, gravar, estado
        liga = os.environ.get("RITMELLI_METRICAS") == "1"  # pelo codigo ou no --mock, para testar
        self.fora = not liga and (mock or not getattr(sys, "frozen", False))
        self.sessao = uuid.uuid4().hex[:16]
        self.fila = queue.Queue()
        self.engine = None
        self.erros = set()
        self.base = {"id": "", "windows": platform.version(), "lingua": _lingua()}
        self._uso = {"musica_s": 0.0, "voz_s": 0.0, "efeitos": {}}
        self._ultimo_uso = time.monotonic()
        self._efeito = SEM_EFEITO
        self._dia = None
        self._lock = threading.Lock()
        self._acorda = threading.Event()
        self._parar = False
        self.envia = _posta  # o teste troca

    # a escolha --------------------------------------------------------------------------------------------------------
    def situacao(self):
        """"ligada", "desligada", "decidir" (ninguem escolheu: o aviso na tela) ou "fora" (codigo, --mock)."""
        if self.fora:
            return "fora"
        e = self.cfg.get("metricas")
        if isinstance(e, bool):
            return "ligada" if e else "desligada"
        i = escolha_do_instalador()
        if i is None:
            return "decidir"
        return "ligada" if i else "desligada"

    def ativa(self):
        return self.situacao() == "ligada"

    def escolhe(self, ligar):
        """A escolha feita no Ritmelli (o aviso ou o Microfone e fone). Desligar joga fora o que nao saiu."""
        self.cfg["metricas"] = bool(ligar)
        self.gravar()
        if not ligar:
            with self._lock:
                while not self.fila.empty():
                    self.fila.get_nowait()
        else:
            self._acorda.set()

    def publico(self):
        return {"situacao": self.situacao(), "politica": POLITICA}

    # o estado da instalacao -------------------------------------------------------------------------------------------
    def _le_estado(self):
        try:
            e = json.loads(Path(self.estado_path).read_text(encoding="utf-8"))
            return e if isinstance(e, dict) else {}
        except (OSError, ValueError):
            return {}

    def _grava_estado(self, e):
        try:
            Path(self.estado_path).parent.mkdir(parents=True, exist_ok=True)
            pastas.save_json(Path(self.estado_path), e)
        except OSError:
            pass

    def _id(self):
        e = self._le_estado()
        if not re.fullmatch(r"[0-9a-f]{32}", str(e.get("id", ""))):
            e = {"id": uuid.uuid4().hex}
            self._grava_estado(e)
        return e

    # os eventos -------------------------------------------------------------------------------------------------------
    def evento(self, nome, **props):
        """Poe um evento na fila, se as metricas estao ligadas. Evento ou propriedade fora do EVENTOS e erro de
        quem chamou (o teste pega)."""
        if nome not in EVENTOS or not set(props) <= EVENTOS[nome]:
            raise ValueError(f"metrics: {nome} {sorted(props)} isn't on the list")
        if not self.ativa():
            return
        p = {**props, "versao": VERSAO, "windows": self.base["windows"], "lingua": self.base["lingua"],
             "sessao": self.sessao, "$process_person_profile": False, "$geoip_disable": True, "$lib": "ritmelli"}
        with self._lock:
            if self.fila.qsize() >= FILA_MAX:
                self.fila.get_nowait()
            self.fila.put({"event": nome, "distinct_id": self.base["id"], "properties": p,
                           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    def erro(self, tipo, valor, tb, onde):
        """Um erro para o Sentry, uma vez por sessao cada um (o mesmo tipo no mesmo lugar), no maximo
        ERROS_POR_SESSAO. Nunca levanta: quem chama ja esta tratando outro erro."""
        try:
            if not self.ativa() or valor is None or isinstance(valor, (KeyboardInterrupt, SystemExit)):
                return
            if not self.base["id"]:
                self.base["id"] = self._id()["id"]
            ult = traceback.extract_tb(tb)[-1:] if tb else []
            chave = (getattr(tipo, "__name__", "?"), tuple((q.filename, q.lineno) for q in ult))
            if chave in self.erros or len(self.erros) >= ERROS_POR_SESSAO:
                return
            self.erros.add(chave)
            ev = evento_de_erro(tipo, valor, tb, onde, self.base)
            threading.Thread(target=self._manda_erro, args=(ev,), daemon=True, name="metricas-erro").start()
        except Exception:  # noqa: BLE001 - o relato de um erro nunca vira outro
            pass

    def _manda_erro(self, ev):
        m = re.match(r"https://([0-9a-f]+)@([^/]+)/(\d+)$", SENTRY_DSN)
        chave, host, projeto = m.groups()
        cab = json.dumps({"event_id": ev["event_id"], "dsn": SENTRY_DSN}) + "\n" + json.dumps({"type": "event"})
        corpo = (cab + "\n" + json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self.envia(f"https://{host}/api/{projeto}/envelope/", corpo, {
                "Content-Type": "application/x-sentry-envelope",
                "X-Sentry-Auth": f"Sentry sentry_version=7, sentry_key={chave}, sentry_client=ritmelli/{VERSAO}"})
        except Exception:  # noqa: BLE001 - sem rede, o erro nao vai
            pass

    def _manda_fila(self):
        if not self.ativa():
            return
        with self._lock:
            lote = []
            while not self.fila.empty() and len(lote) < 100:
                lote.append(self.fila.get_nowait())
        if not lote:
            return
        try:
            self.envia(POSTHOG, json.dumps({"api_key": POSTHOG_CHAVE, "batch": lote}).encode("utf-8"),
                       {"Content-Type": "application/json"})
        except Exception:  # noqa: BLE001 - sem rede: volta para a fila, e o FILA_MAX segura o tamanho
            with self._lock:
                for x in lote:
                    if self.fila.qsize() < FILA_MAX:
                        self.fila.put(x)

    # o uso ------------------------------------------------------------------------------------------------------------
    def _olha(self, dt):
        """Soma dt segundos ao que o motor esta fazendo: musica tocando, voz com efeito (com o microfone aberto)."""
        e = self.engine
        if e is None:
            return
        try:
            tocando = e.status() == "playing"
            ef = str(e.effect or SEM_EFEITO)
            mudo = bool(getattr(e, "mic_mute", False))
        except Exception:  # noqa: BLE001 - o motor fechando
            return
        if tocando:
            self._uso["musica_s"] += dt
        if ef != SEM_EFEITO and not mudo:
            self._uso["voz_s"] += dt
            self._uso["efeitos"][ef] = self._uso["efeitos"].get(ef, 0.0) + dt
        if ef != self._efeito:
            self._efeito = ef
            if ef != SEM_EFEITO:
                self.evento("efeito", efeito=ef)

    def _fecha_uso(self):
        u, self._uso = self._uso, {"musica_s": 0.0, "voz_s": 0.0, "efeitos": {}}
        self._ultimo_uso = time.monotonic()
        if u["musica_s"] >= 1 or u["voz_s"] >= 1:
            self.evento("uso", musica_s=round(u["musica_s"]), voz_s=round(u["voz_s"]))
        for ef, s in u["efeitos"].items():
            if s >= 1:
                self.evento("efeito_tempo", efeito=ef, segundos=round(s))

    def _dia_novo(self):
        """O "ativo" do dia (e o "atualizou", na primeira vez desta versao), uma vez por dia por instalacao."""
        hoje = date.today().isoformat()
        if hoje == self._dia or not self.ativa():
            return
        e = self._id()
        self.base["id"] = e["id"]
        if e.get("dia") != hoje:
            self.evento("ativo", primeira_vez="dia" not in e)
        if e.get("versao") and e["versao"] != VERSAO:
            self.evento("atualizou", de=str(e["versao"])[:20])
        e.update(dia=hoje, versao=VERSAO)
        self._grava_estado(e)
        self._dia = hoje

    def vigia(self, engine):
        """A thread do envio: olha o motor a cada AMOSTRA_S, fecha o uso a cada USO_S e manda a fila a cada ENVIO_S."""
        self.engine = engine
        if self.fora:
            return
        ultimo_envio = ultimo = time.monotonic()
        while not self._parar:
            self._acorda.wait(AMOSTRA_S)
            self._acorda.clear()
            agora = time.monotonic()
            if self.ativa():
                if not self.base["id"]:
                    self.base["id"] = self._id()["id"]
                self._dia_novo()
                self._olha(min(agora - ultimo, AMOSTRA_S * 3))
                if agora - self._ultimo_uso >= USO_S:
                    self._fecha_uso()
                if agora - ultimo_envio >= ENVIO_S:
                    self._manda_fila()
                    ultimo_envio = agora
            ultimo = agora

    def fecha(self):
        """Ao desligar: o uso ate aqui e o que ficou na fila saem agora (com o tempo do envio, no maximo)."""
        self._parar = True
        self._acorda.set()
        if self.ativa():
            self._fecha_uso()
            t = threading.Thread(target=self._manda_fila, daemon=True, name="metricas-fim")
            t.start()
            t.join(3.0)  # sem rede, o desligar nao espera os 10 s do envio

    # os erros que ninguem pegou ---------------------------------------------------------------------------------------
    def instala_ganchos(self):
        """O erro que derrubaria uma thread ou o programa vai para o Sentry, e segue o caminho de sempre (o log)."""
        antes_sys, antes_thr = sys.excepthook, threading.excepthook

        def no_sys(t, v, tb):
            self.erro(t, v, tb, "main")
            antes_sys(t, v, tb)

        def na_thread(a):
            self.erro(a.exc_type, a.exc_value, a.exc_traceback, f"thread:{getattr(a.thread, 'name', '?')}"[:60])
            antes_thr(a)

        sys.excepthook, threading.excepthook = no_sys, na_thread

    def no_loop(self, loop):
        """O erro de uma tarefa do asyncio que ninguem esperou."""
        antes = loop.get_exception_handler()

        def trata(lp, ctx):
            ex = ctx.get("exception")
            if ex is not None:
                self.erro(type(ex), ex, ex.__traceback__, "asyncio")
            if antes is not None:
                antes(lp, ctx)
            else:
                lp.default_exception_handler(ctx)

        loop.set_exception_handler(trata)
