"""A versao nova da Vitrola, pelo caminho A do PLANO.md do vitrola-server. O app baixa o manifesto das versoes e a
assinatura dele, confere a assinatura com a chave publica que mora aqui e, se a versao for mais nova que a dele, a tela
avisa. Quem aceita baixa o setup.exe que o manifesto aponta, com o tamanho e o hash conferidos, e o app roda o
instalador em modo silencioso: o Windows pede a permissao, o instalador fecha a Vitrola, troca a pasta dela e abre de
novo (o /reabrir=1 do vitrola.iss).

O ponto de confianca e a chave: so vale o manifesto assinado por ela, e so para uma versao mais nova que a que esta
rodando, entao um manifesto velho, mesmo assinado, nao volta a versao. O manifesto ja traz cada arquivo do app com o
hash, no formato do caminho B (trocar so o que mudou), para o B entrar depois sem trocar o formato nem a chave.

As versoes ficam nas Releases do repo publico vitrola-app/vitrola-releases: o "latest" do GitHub e sempre a ultima
publicada, com o manifesto, a assinatura e o setup. A chave 1 e a que a esteira do vitrola-server usa para assinar.
Rodando pelo codigo, nada e consultado, porque ai quem atualiza e o git. Os testes (dev/testa_atualizacao.py) trocam
os tres."""
import base64
import ctypes
import hashlib
import json
import re
import ssl
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pastas
from versao import VERSAO

# o endereco https do manifest.json; a assinatura e o mesmo endereco com ".sig" no fim
MANIFESTO = "https://github.com/vitrola-app/vitrola-releases/releases/latest/download/manifest.json"
# numero -> chave publica Ed25519 (os 32 bytes em base64); o .sig diz qual delas assinou
CHAVES = {1: "Bnvi5qyGzrl2bPDgG9UUCDHjhcTCU3lr9SHMKbkjLts="}
SO_HTTPS = True  # os testes servem por http, numa porta local
FORMATO = 1
PASTA = pastas.DADOS / "atualizacao"
CONSULTA_APOS_S = 30.0       # depois de abrir: a subida do app nao divide a rede com a consulta
CONSULTA_CADA_S = 6 * 3600.0
TEMPO_S = 20.0               # o manifesto e pequeno; o setup tem o mesmo prazo entre um pedaco e outro
MANIFESTO_MAX = 1 << 20
SETUP_MAX = 1 << 30
PEDACO = 1 << 20
# o instalador sem janela; /reabrir=1 abre a Vitrola de novo no fim, como quem instalou (vitrola.iss)
PARAMETROS = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /reabrir=1"
SE_ERR_ACCESSDENIED = 5      # o ShellExecute com o pedido de permissao recusado


class Recusado(ValueError):
    """O manifesto ou o arquivo nao passa na conferencia."""


def versao(v):
    """"0.12.3" -> (0, 12, 3). Semver sem sufixo, como o versao.py."""
    m = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,6})", str(v))
    if not m:
        raise Recusado(f"versão fora do formato: {v!r}")
    return tuple(int(x) for x in m.groups())


def _sha(texto):
    return isinstance(texto, str) and re.fullmatch(r"[0-9a-f]{64}", texto) is not None


def confere(manifesto, assinatura, chaves=None):
    """O manifesto (bytes) como dict, se a assinatura (o .sig, bytes) for de uma das chaves e ele estiver no formato.
    Senao, Recusado."""
    from Cryptodome.Signature import eddsa
    chaves = CHAVES if chaves is None else chaves
    try:
        s = json.loads(assinatura)
        pub = eddsa.import_public_key(base64.b64decode(chaves[s["chave"]], validate=True))
        eddsa.new(pub, "rfc8032").verify(manifesto, base64.b64decode(s["assinatura"], validate=True))
    except (KeyError, TypeError, ValueError) as e:
        raise Recusado("a assinatura do manifesto não confere") from e
    m = json.loads(manifesto)
    if not isinstance(m, dict) or m.get("formato") != FORMATO or m.get("app") != "vitrola":
        raise Recusado("o manifesto não é de uma versão da Vitrola que este app entende")
    versao(m.get("versao"))
    notas = m.get("notas", [])
    if not (isinstance(notas, list) and len(notas) <= 30 and all(isinstance(n, str) and len(n) <= 500 for n in notas)):
        raise Recusado("as notas da versão estão fora do formato")
    inst = m.get("instalador")
    if not (isinstance(inst, dict) and isinstance(inst.get("url"), str) and _sha(inst.get("sha256"))
            and isinstance(inst.get("tamanho"), int) and 0 < inst["tamanho"] <= SETUP_MAX):
        raise Recusado("o instalador do manifesto está fora do formato")
    if not inst["url"].startswith("https://" if SO_HTTPS else ("https://", "http://")):
        raise Recusado("o instalador do manifesto não vem por https")
    for a in m.get("arquivos", []):
        if not (isinstance(a, dict) and isinstance(a.get("caminho"), str) and _sha(a.get("sha256"))
                and isinstance(a.get("tamanho"), int) and a["tamanho"] >= 0):
            raise Recusado("a lista de arquivos do manifesto está fora do formato")
        # o caminho B troca arquivo por arquivo: nada de sair da pasta do app
        c = a["caminho"].replace("\\", "/")
        if c.startswith("/") or ":" in c or ".." in c.split("/"):
            raise Recusado(f"caminho de arquivo recusado no manifesto: {a['caminho']!r}")
    return m


def _tls():
    """As raizes do Windows e as do certifi, que vai junto no app (o yt-dlp usa). Num Windows novo faltam raizes: ele
    so baixa uma quando um programa dele precisa (o Edge, por exemplo), e o Python nao pede, entao num PC que nunca
    abriu o GitHub a consulta falhava (CERTIFICATE_VERIFY_FAILED). So o certifi tambem nao serve: o antivirus que
    inspeciona o https poe a raiz dele so na lista do Windows."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    return ctx


def _pega(url, maximo):
    req = urllib.request.Request(url, headers={"User-Agent": f"Vitrola/{VERSAO}"})
    with urllib.request.urlopen(req, timeout=TEMPO_S, context=_tls()) as r:
        dados = r.read(maximo + 1)
    if len(dados) > maximo:
        raise Recusado(f"{url} passou de {maximo} bytes")
    return dados


def _hash(arq):
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        while b := f.read(PEDACO):
            h.update(b)
    return h.hexdigest()


class Atualizacao:
    """O estado da versao nova para a tela: parado (nenhuma, ou ainda nao baixou), consultando, baixando, pronta
    (o setup baixado e conferido) e instalando."""

    def __init__(self, ativa=None):
        congelado = getattr(sys, "frozen", False)
        self.ativa = bool(MANIFESTO and CHAVES and congelado) if ativa is None else ativa
        self.lock = threading.Lock()
        self.nova = None        # o manifesto conferido de uma versao mais nova que a VERSAO
        self.estado = "parado"
        self.progresso = 0.0
        self.erro = None        # o que deu errado na ultima acao, para a tela
        self.consultada = None  # quando a ultima consulta deu certo
        self.setup = None       # o setup.exe baixado e conferido

    def resumo(self):
        """O pedaco que vai no estado ao vivo (o SSE): o tema so precisa saber se tem e em que pe esta."""
        with self.lock:
            return {"nova": self.nova["versao"] if self.nova else None, "estado": self.estado,
                    "progresso": round(self.progresso, 3), "erro": self.erro}

    def publico(self):
        with self.lock:
            n = self.nova
            return {"ativa": self.ativa, "versao": VERSAO, "estado": self.estado, "progresso": round(self.progresso, 3),
                    "erro": self.erro, "consultada": self.consultada,
                    "nova": n and {"versao": n["versao"], "data": n.get("data"), "notas": n.get("notas", []),
                                   "tamanho": n["instalador"]["tamanho"]}}

    def vigia(self):
        """A thread que consulta logo depois de abrir e de tempos em tempos. Sem rede, so tenta na proxima."""
        self._limpa()
        time.sleep(CONSULTA_APOS_S)
        while True:
            self.consultar()
            time.sleep(CONSULTA_CADA_S)

    def consultar(self):
        """Baixa e confere o manifesto. True se ha versao nova."""
        if not self.ativa:
            return False
        with self.lock:
            if self.estado != "parado":
                return self.nova is not None
            self.estado, self.erro = "consultando", None
        try:
            m = confere(_pega(MANIFESTO, MANIFESTO_MAX), _pega(MANIFESTO + ".sig", 4096))
        except (OSError, ValueError) as e:
            with self.lock:
                self.estado = "parado"
                self.erro = str(e) if isinstance(e, Recusado) else "Não deu para consultar se há versão nova."
            print(f"atualizacao: {e}", flush=True)
            return self.nova is not None
        with self.lock:
            self.estado, self.consultada = "parado", time.strftime("%Y-%m-%dT%H:%M:%S")
            if versao(m["versao"]) > versao(VERSAO):
                if not self.nova or self.nova["versao"] != m["versao"]:
                    self.nova, self.setup = m, None
                    print(f"atualizacao: versao nova {m['versao']}", flush=True)
            else:
                self.nova = self.setup = None
            return self.nova is not None

    def baixar(self):
        """Comeca o download do setup da versao nova, numa thread. False se nao ha o que baixar."""
        with self.lock:
            if not self.nova or self.estado not in ("parado",):
                return False
            if self.setup and self.setup.exists():
                self.estado = "pronta"
                return True
            self.estado, self.progresso, self.erro = "baixando", 0.0, None
            m = self.nova
        threading.Thread(target=self._baixa, args=(m,), daemon=True).start()
        return True

    def _baixa(self, m):
        inst = m["instalador"]
        PASTA.mkdir(parents=True, exist_ok=True)
        final = PASTA / f"Vitrola-{m['versao']}-setup.exe"
        parcial = final.with_name(final.name + ".parcial")
        try:
            h, n = hashlib.sha256(), 0
            req = urllib.request.Request(inst["url"], headers={"User-Agent": f"Vitrola/{VERSAO}"})
            with urllib.request.urlopen(req, timeout=TEMPO_S, context=_tls()) as r, open(parcial, "wb") as f:
                while b := r.read(PEDACO):
                    n += len(b)
                    if n > inst["tamanho"]:
                        raise Recusado("o instalador baixado é maior que o do manifesto")
                    h.update(b)
                    f.write(b)
                    with self.lock:
                        self.progresso = n / inst["tamanho"]
            if n != inst["tamanho"] or h.hexdigest() != inst["sha256"]:
                raise Recusado("o instalador baixado não confere com o manifesto")
            parcial.replace(final)
        except (OSError, ValueError) as e:
            parcial.unlink(missing_ok=True)
            with self.lock:
                self.estado = "parado"
                self.erro = str(e) if isinstance(e, Recusado) else "O download da versão nova parou. Tente de novo."
            print(f"atualizacao: {e}", flush=True)
            return
        with self.lock:
            self.setup, self.estado, self.progresso = final, "pronta", 1.0
        print(f"atualizacao: {final.name} baixado e conferido", flush=True)

    def instalar(self):
        """Confere o setup de novo e roda ele com o pedido de permissao do Windows. (True, None) se o instalador
        abriu, e ai a Vitrola deve fechar; senao (False, o motivo)."""
        with self.lock:
            if self.estado != "pronta" or not self.setup:
                return False, "A versão nova ainda não foi baixada."
            setup, m = self.setup, self.nova
        if not setup.exists() or _hash(setup) != m["instalador"]["sha256"]:
            with self.lock:
                self.estado, self.setup = "parado", None
            return False, "O instalador baixado mudou depois da conferência. Baixe de novo."
        log = PASTA / f"instalador-{m['versao']}.log"
        r = abre_instalador(setup, f'{PARAMETROS} /LOG="{log}"')
        if r <= 32:
            return False, ("O Windows não deu a permissão, e a atualização ficou para depois."
                           if r == SE_ERR_ACCESSDENIED else f"O instalador não abriu (erro {r}).")
        with self.lock:
            self.estado = "instalando"
        print(f"atualizacao: instalador da {m['versao']} aberto; a Vitrola fecha", flush=True)
        return True, None

    def _limpa(self):
        """Tira os setups de versoes que ja nao sao novas e os downloads que pararam no meio."""
        if not PASTA.exists():
            return
        for f in PASTA.iterdir():
            v = re.fullmatch(r"Vitrola-(.+)-setup\.exe", f.name)
            try:
                velho = f.name.endswith(".parcial") or (v and versao(v.group(1)) <= versao(VERSAO))
                if velho:
                    f.unlink()
            except (OSError, ValueError):
                pass


def abre_instalador(setup, parametros):
    """O ShellExecute com o verbo runas, o que pede a permissao de administrador: o instalador pede, e um subprocess
    comum falharia (WinError 740). Volta o codigo do ShellExecute: acima de 32 e sucesso."""
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", str(setup), parametros, None, 1)
