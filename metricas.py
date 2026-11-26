"""Os dados de uso e os erros do Ritmelli (#102), para saber quantas pessoas usam, se a versao nova esta chegando, que
erro acontece agora e o que se usa de verdade (cada efeito de voz, a musica). O que vai, para onde e como desligar
esta no PRIVACIDADE.md, na raiz do repo; a SignPath pede que a politica apareca na instalacao e que de para desligar
la (o ritmelli.iss), e o app tambem desliga, no Microfone e fone.

Quem decide se envia: a escolha feita no Ritmelli (o "metricas" do config.json), senao a da pagina do instalador (o
Metricas do HKLM\\SOFTWARE\\Ritmelli, 1 ou 0). Sem nenhuma das duas (quem atualizou em silencio de uma versao sem
metricas), nada sai ate a pessoa ver o aviso na tela e escolher. Pelo codigo e no --mock, nunca envia
(RITMELLI_METRICAS=1 liga nos dois, para testar; o --mock --metricas-teste liga sem rede nenhuma, para o teste do aviso).

A versao do texto que a pessoa aceitou (TEXTO): o app grava o metricas_texto junto do metricas, e o instalador o
MetricasVersao junto do Metricas. O "audio" so sai com a escolha feita no texto de agora; quem ligou num texto de antes
ve o aviso de novo, e os outros eventos seguem saindo ate la.

O que vai, sempre com um ID aleatorio da instalacao (o metricas.json da pasta de dados; o desinstalador apaga), a
versao, a do Windows e a lingua: um "ativo" por dia de uso, o "atualizou" na primeira vez de uma versao nova, o
"efeito" quando um efeito de voz liga e, a cada meia hora e ao fechar, o "uso" (os segundos de musica e de voz com
efeito) e um "efeito_tempo" por efeito usado (os segundos dele) e, com o texto de agora, o "audio" (a saude da saida
para o jogo naquela janela: SaudeAudio). Os erros vao para o Sentry, com a pilha (arquivo, funcao e linha) e a
mensagem sem o que esta entre aspas, sem endereco e sem caminho. Nunca vai nome, conta, musica, busca, link, audio, voz nem o nome de
um aparelho: o EVENTOS abaixo e a lista inteira, e o dev/testa_metricas.py confere.

As chaves daqui so enviam (o PostHog e o Sentry chamam de chave publica): podem morar no codigo aberto."""
import contextlib
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
REG, REG_VALOR, REG_TEXTO = r"SOFTWARE\Ritmelli", "Metricas", "MetricasVersao"
# a versao do texto do consentimento (o do aviso, o metrics.text, e o da pagina do instalador, o MetricasTexto do
# ritmelli.iss, que grava o MetricasVersao com este numero). Mudou o que vai, muda os textos e sobe este numero
TEXTO = 2

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
    # a saude da saida para o jogo na janela (SaudeAudio.fecha), a cada USO_S dela (o _audio_desde) e ao fechar, so
    # com o texto de agora aceito
    "audio": {"secas", "folga_min_ms", "volta_max_ms", "passagens", "esticamentos", "esticamento_ms",
              "secas_passagem", "secas_esticamento", "leitor_perdido", "leitor_perdido_s", "fx_no_filtro_s",
              "mic_reserva_s", "voz_taxa"},
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


def _do_instalador(nome):
    """Um valor que a pagina do instalador gravou (no REG do HKLM), ou None."""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, nome)[0]
    except OSError:
        return None


def escolha_do_instalador():
    """O que a pagina do instalador gravou: True, False, ou None (nao passou por ela)."""
    v = _do_instalador(REG_VALOR)
    return bool(int(v)) if str(v).strip() in ("0", "1") else None


def texto_do_instalador():
    """A versao do texto que a pagina do instalador mostrou (o MetricasVersao), ou None (um instalador de antes dela)."""
    return _versao(_do_instalador(REG_TEXTO))


def _versao(v):
    """A versao de um texto (um inteiro de 1 para cima), ou None."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None


def limpa(txt):
    """A mensagem de um erro sem o que pode ser da pessoa: o que esta entre aspas (um titulo, um arquivo, uma busca),
    endereco e caminho. Fica o tipo do problema ("[Errno 2] No such file or directory: '...'")."""
    txt = re.sub(r"[a-z][a-z0-9+.-]*://\S+", "<url>", str(txt), flags=re.I)
    txt = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "'...'", txt)
    txt = re.sub(r"\b[A-Za-z]:[\\/][^\s,;:)]*", "<path>", txt)
    txt = re.sub(r"\\\\[^\s,;:)]+", "<path>", txt)
    txt = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", txt)
    return txt[:300]


# os modulos do Ritmelli: a linha da pilha num deles e "do app" (o Sentry agrupa e destaca por ela, e o filtro da
# conexao fechada pelo outro lado, abaixo, deixa passar). O dev/testa_metricas.py confere que nenhum ficou de fora
NOSSOS = {"andamento", "atualizacao", "atualizador", "automatico", "batida", "comandos", "compasso", "conversor",
          "engine", "fx", "i18n", "janela", "metricas", "microfone", "migra", "music", "pareamento", "pastas",
          "permissao", "pista", "pistavoz", "ritmelli", "server", "sonoridade", "theme_page", "transicao", "versao", "winvol",
          "yt_erros", "yt_fora"}


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


# o outro lado fechou a conexao de repente: a aba do Ritmelli fechada ou recarregada no meio de uma resposta, o celular
# que saiu do Wi-Fi. No Windows, o loop Proactor do asyncio entrega isso ao tratador do loop (o shutdown do socket no
# _call_connection_lost), com a pilha so do asyncio (#116)
CONEXAO_FECHADA = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


def so_conexao_fechada(ex):
    """O erro e so a conexao que o outro lado fechou: um dos CONEXAO_FECHADA sem nenhuma linha do app na pilha (o
    in_app do evento_de_erro). Nao e falha do Ritmelli e nao vai para o Sentry; com linha do app, vai como sempre."""
    if not isinstance(ex, CONEXAO_FECHADA):
        return False
    return not any(_arquivo(q.filename)[1] for q in traceback.extract_tb(ex.__traceback__))


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


class EmCurso:
    """O que o motor roda em mais de uma thread ao mesmo tempo (a Rubber Band): quantas vezes comecou e o tempo com
    pelo menos uma em curso, desde que o processo abriu. A janela do audio (SaudeAudio) guarda a diferenca entre o
    comeco e o fim dela. O relogio e trocavel para o teste."""

    def __init__(self, relogio=time.monotonic):
        self._rel, self._lock = relogio, threading.Lock()
        self._iniciadas, self._em_curso, self._desde, self._ocupado = 0, 0, 0.0, 0.0

    @contextlib.contextmanager
    def roda(self):
        with self._lock:
            self._iniciadas += 1
            if not self._em_curso:
                self._desde = self._rel()
            self._em_curso += 1
        try:
            yield
        finally:
            with self._lock:
                self._em_curso -= 1
                if not self._em_curso:
                    self._ocupado += self._rel() - self._desde

    def em_curso(self):
        return self._em_curso > 0

    def total(self):
        """(quantas comecaram, os segundos com alguma em curso), ate agora."""
        with self._lock:
            return self._iniciadas, self._ocupado + (self._rel() - self._desde if self._em_curso else 0.0)


class SaudeAudio:
    """A saude da saida para o jogo numa janela, para o evento "audio". Quem conta e a thread da saida (o Injetor do
    engine.py), a cada volta; quem fecha e o vigia daqui, a cada USO_S e ao desligar (fecha: o que ela contou, e a
    proxima comeca). Cada Injetor tem a sua: trocar de Injetor (o audio reaberto) comeca outra, salvo na reabertura do
    leitor perdido (Engine._recupera_leitor), em que o novo continua a do de antes (o tempo da propria reabertura, com
    o audio fechado, nao entra no leitor_perdido_s). Os acumulados do
    Injetor que o /api/state mostra seguem a parte, como estavam.

    O que o motor conta desde que abriu (os preparos de passagem, a voz pelo microfone de reserva e a Rubber Band, pelo
    EmCurso) chega em totais a cada volta, e a janela guarda a diferenca desde o comeco dela: a chamada a Rubber Band
    que atravessa o fim de uma janela entra no esticamento_ms das duas, cada uma com o tempo dela."""

    def __init__(self, sr):
        self.sr = sr
        self._lock = threading.Lock()
        # (preparos, s de voz pelo microfone de reserva, esticamentos, s com a Rubber Band em curso), os da ultima volta
        self._totais = None
        self._leitores = 0  # os da ultima volta, com o anel aberto
        self._perdido = self._fx = False  # o estado da ultima volta: o tempo ate a proxima conta nele
        self._zera()

    def _zera(self):
        self._base, self._andou = self._totais, False
        self.secas = self.secas_passagem = self.secas_esticamento = self.leitor_perdido = 0
        self.folga_min = None
        self.volta_max = self.leitor_perdido_s = self.fx_no_filtro_s = 0.0
        self.voz_taxa = 0

    def volta(self, s, *, anel, leitores, fx_no_filtro, voz_taxa, totais):
        """Uma volta da thread da saida, de s segundos, que passaram no estado da volta de antes. leitores: os do anel
        (aberto ou nao); fx_no_filtro: o efeito de voz rodando no filtro; voz_taxa: a taxa do microfone alvo do anel (0
        sem ele)."""
        with self._lock:
            self._andou = True
            self.volta_max = max(self.volta_max, s)
            self.leitor_perdido_s += s * self._perdido
            self.fx_no_filtro_s += s * self._fx
            leitores = leitores if anel else 0
            if anel and self._leitores and not leitores:
                self.leitor_perdido += 1
                self._perdido = True
            elif leitores or not anel:
                self._perdido = False
            self._leitores, self._fx = leitores, bool(fx_no_filtro)
            if voz_taxa:
                self.voz_taxa = int(voz_taxa)
            if self._base is None:
                self._base = totais
            self._totais = totais

    def anel_caiu(self, s, contou=True):
        """O anel fechou por erro numa volta de s segundos: ela conta na maior volta (e, se a volta nao chegou a contar,
        no estado da de antes), e a perda e o efeito dele param de contar ja (a pausa ate o proximo nao entra)."""
        with self._lock:
            self.volta_max = max(self.volta_max, s)
            if not contou and self._totais is not None:
                self._andou = True
                self.leitor_perdido_s += s * self._perdido
                self.fx_no_filtro_s += s * self._fx
            self._leitores, self._perdido, self._fx = 0, False, False

    def fila(self, quadros, *, passagem=False, esticando=False):
        """O tanto no anel quando a thread chegou, com o leitor ja servido: o menor e as secas (vazio), contando a
        parte as do meio de uma passagem e as de uma chamada a Rubber Band em curso."""
        with self._lock:
            self._andou = self._andou or self._totais is not None
            if self.folga_min is None or quadros < self.folga_min:
                self.folga_min = quadros
            if quadros == 0:
                self.secas += 1
                self.secas_passagem += bool(passagem)
                self.secas_esticamento += bool(esticando)

    def fecha(self):
        """O que a janela contou, nas propriedades do "audio" (None se a thread da saida nao andou nela), e a proxima
        comeca."""
        with self._lock:
            if not self._andou:
                self._zera()
                return None
            (p0, r0, e0, s0), (p, r, e, s) = self._base, self._totais
            props = {"secas": self.secas,
                     "folga_min_ms": None if self.folga_min is None else round(self.folga_min * 1000 / self.sr, 1),
                     "volta_max_ms": round(self.volta_max * 1000, 1),
                     "passagens": p - p0, "esticamentos": e - e0, "esticamento_ms": round((s - s0) * 1000),
                     "secas_passagem": self.secas_passagem, "secas_esticamento": self.secas_esticamento,
                     "leitor_perdido": self.leitor_perdido, "leitor_perdido_s": round(self.leitor_perdido_s),
                     "fx_no_filtro_s": round(self.fx_no_filtro_s), "mic_reserva_s": round(r - r0),
                     "voz_taxa": self.voz_taxa}
            self._zera()
            return props


class Metricas:
    """O envio, de uma thread so. cfg e o config.json do app (o metricas que a pessoa escolheu no Ritmelli mora nele),
    que aqui so se le; gravar(**mudancas) e quem muda o cfg e grava o config (App.grava_cfg, sob a trava do cfg). Sem
    ligar(), nada sai. teste (o --mock --metricas-teste): liga sem ler o instalador, o envio so guarda o lote na
    memoria (guardados) e o dos erros nem liga, para o teste do aviso no tema."""

    def __init__(self, cfg, gravar, mock=False, estado=ESTADO, teste=False):
        self.cfg, self.gravar, self.estado_path, self.teste = cfg, gravar, estado, teste
        liga = os.environ.get("RITMELLI_METRICAS") == "1"  # pelo codigo ou no --mock, para testar
        self.fora = not teste and not liga and (mock or not getattr(sys, "frozen", False))
        self.guardados = []  # o que o --metricas-teste "enviou"
        self._audio_vale = False  # a janela do "audio" comecou com a escolha no texto de agora
        self._audio_lock = threading.RLock()  # o vigia, a escolha e o fecha mexem nela
        self._audio_desde = time.monotonic()  # o comeco da janela do "audio" que vale (o prazo dela e o USO_S)
        self._geracao = 0  # sobe a cada desligar: o lote que estava saindo antes nao volta para a fila
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
        self.envia = self._guarda if teste else _posta  # o teste troca

    def _guarda(self, url, dados, cabecalhos):
        """O envio do --metricas-teste: o lote fica na memoria, e nada vai a rede."""
        self.guardados += json.loads(dados).get("batch", [])
        return 200

    # a escolha --------------------------------------------------------------------------------------------------------
    def _instalador(self):
        return None if self.teste else escolha_do_instalador()

    def situacao(self):
        """"ligada", "desligada", "decidir" (ninguem escolheu: o aviso na tela) ou "fora" (codigo, --mock)."""
        if self.fora:
            return "fora"
        e = self.cfg.get("metricas")
        if isinstance(e, bool):
            return "ligada" if e else "desligada"
        i = self._instalador()
        if i is None:
            return "decidir"
        return "ligada" if i else "desligada"

    def texto(self):
        """A versao do texto da escolha que vale: a do app (o metricas_texto do cfg) quando a escolha e dele, senao a do
        instalador (o MetricasVersao); 1 quando essa escolha veio sem versao (de antes dela), 0 sem escolha ou
        fora."""
        if self.fora:
            return 0
        if isinstance(self.cfg.get("metricas"), bool):
            return _versao(self.cfg.get("metricas_texto")) or 1
        if self._instalador() is not None:
            return texto_do_instalador() or 1
        return 0

    def ativa(self):
        return self.situacao() == "ligada"

    def escolhe(self, ligar):
        """A escolha feita no Ritmelli (o aviso ou o Microfone e fone), sempre no texto de agora. Desligar joga fora o
        que nao saiu e a janela do "audio"."""
        with self._audio_lock:  # a escolha e a janela do "audio" juntas: duas escolhas seguidas nao se cruzam
            try:
                self.gravar(metricas=bool(ligar), metricas_texto=TEXTO)
            finally:
                if not ligar:  # mesmo com a gravacao falhando (o cfg ja diz desligada): nada do que veio antes fica
                    with self._lock:
                        while not self.fila.empty():
                            self.fila.get_nowait()
                        self._geracao += 1
                    self._fecha_audio(manda=False)
                    self._audio_vale = False
            if ligar:
                self._confere_audio()  # a janela comeca na hora da escolha
        if ligar:
            self._acorda.set()

    def publico(self):
        """O GET /api/metricas: a situacao, a politica e a versao do texto da escolha (texto) e a de agora
        (texto_atual). O tema mostra o aviso de novo a quem ligou num texto de antes."""
        return {"situacao": self.situacao(), "politica": POLITICA, "texto": self.texto(), "texto_atual": TEXTO}

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
            if not self.ativa():  # desligou agora: o desligar ja limpou a fila sob esta trava
                return
            if self.fila.qsize() >= FILA_MAX:
                self.fila.get_nowait()
            self.fila.put({"event": nome, "distinct_id": self.base["id"], "properties": p,
                           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    def erro(self, tipo, valor, tb, onde):
        """Um erro para o Sentry, uma vez por sessao cada um (o mesmo tipo no mesmo lugar), no maximo
        ERROS_POR_SESSAO. Nunca levanta: quem chama ja esta tratando outro erro."""
        try:
            if self.teste or not self.ativa() or valor is None or isinstance(valor, (KeyboardInterrupt, SystemExit)):
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
        except Exception:  # o relato de um erro nunca vira outro
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
        except Exception:  # sem rede, o erro nao vai
            pass

    def _manda_fila(self):
        with self._lock:  # sob a trava da fila: o desligar que limpa a fila nao deixa um lote escapar
            if not self.ativa():
                return
            lote, geracao = [], self._geracao
            while not self.fila.empty() and len(lote) < 100:
                lote.append(self.fila.get_nowait())
        if not lote:
            return
        try:
            self.envia(POSTHOG, json.dumps({"api_key": POSTHOG_CHAVE, "batch": lote}).encode("utf-8"),
                       {"Content-Type": "application/json"})
        except Exception:  # sem rede: volta para a fila, e o FILA_MAX segura o tamanho
            with self._lock:
                if geracao != self._geracao:
                    return  # desligou durante o envio: o que nao saiu fica fora, como o resto da fila
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
        except Exception:  # o motor fechando
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

    def _manda_audio(self, prazo=False):
        """O "audio" da janela que vale (a cada USO_S dela, com prazo, e ao desligar), e a proxima comeca. O prazo se
        confere sob a trava: a janela que comecou agora (uma escolha no meio) nao fecha pelo prazo da de antes."""
        with self._audio_lock:
            if prazo and time.monotonic() - self._audio_desde < USO_S:
                return
            self._fecha_audio(manda=self._audio_vale and self.texto() >= TEXTO)
            self._audio_desde = time.monotonic()

    def _fecha_audio(self, manda):
        """Fecha a janela do "audio" do Injetor de agora (sem ele, o audio fechado ou o --mock, nada) e, com manda,
        poe o evento na fila. Sem manda, o que ela contou some: a janela que vale comeca ali, e o descarte alcanca
        tambem a do Injetor parado, que a reabertura do leitor perdido continuaria."""
        f = getattr(self.engine, "saude_audio", None)
        j = f(aberto=manda) if callable(f) else None
        p = j.fecha() if j is not None else None
        if manda and p is not None:
            self.evento("audio", **p)

    def _confere_audio(self):
        """A janela do "audio" comeca quando a escolha no texto de agora passa a valer, e o que veio antes some."""
        with self._audio_lock:
            pode = self.ativa() and self.texto() >= TEXTO
            if pode != self._audio_vale:
                self._fecha_audio(manda=False)
                self._audio_vale, self._audio_desde = pode, time.monotonic()

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
        # a escolha no texto de agora que ja valia ao abrir: a janela do Injetor conta desde a abertura do audio
        with self._audio_lock:
            self._audio_vale, self._audio_desde = self.ativa() and self.texto() >= TEXTO, time.monotonic()
        ultimo_envio = ultimo = time.monotonic()
        while not self._parar:
            self._acorda.wait(AMOSTRA_S)
            self._acorda.clear()
            if self._parar:
                break  # o fecha fecha o uso e manda a fila
            agora = time.monotonic()
            self._confere_audio()
            if self.ativa():
                if not self.base["id"]:
                    self.base["id"] = self._id()["id"]
                self._dia_novo()
                self._olha(min(agora - ultimo, AMOSTRA_S * 3))
                if agora - self._ultimo_uso >= USO_S:
                    self._fecha_uso()
                self._manda_audio(prazo=True)
                if agora - ultimo_envio >= ENVIO_S:
                    self._manda_fila()
                    ultimo_envio = agora
            ultimo = agora

    def fecha(self):
        """Ao desligar: o uso ate aqui e o que ficou na fila saem agora (com o tempo do envio, no maximo)."""
        self._parar = True
        self._acorda.set()
        if self.ativa():
            if not self.base["id"]:  # fechado antes da primeira volta do vigia
                self.base["id"] = self._id()["id"]
            self._fecha_uso()
            self._manda_audio()
            t = threading.Thread(target=self._manda_fila, daemon=True, name="metricas-fim")
            t.start()
            t.join(3.0)  # sem rede, o desligar nao espera os 10 s do envio
        if self.teste:  # o que o --metricas-teste teria enviado, no log de quem testa
            nomes = sorted({e.get("event") for e in self.guardados})
            print(f"metrics test: {len(self.guardados)} event(s) kept in memory ({', '.join(nomes) or 'none'}), "
                  "nothing sent", file=sys.stderr, flush=True)

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
        """O erro de uma tarefa do asyncio que ninguem esperou. A conexao fechada pelo outro lado
        (so_conexao_fechada) nao vai para o Sentry; o log registra tudo, como antes."""
        antes = loop.get_exception_handler()

        def trata(lp, ctx):
            ex = ctx.get("exception")
            if ex is not None and not so_conexao_fechada(ex):
                self.erro(type(ex), ex, ex.__traceback__, "asyncio")
            if antes is not None:
                antes(lp, ctx)
            else:
                lp.default_exception_handler(ctx)

        loop.set_exception_handler(trata)
