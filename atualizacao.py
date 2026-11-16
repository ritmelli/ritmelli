"""A versao nova da Vitrola, pelos caminhos A e B do PLANO.md do vitrola-server. O app baixa o manifesto das versoes e
a assinatura dele, confere a assinatura com a chave publica que mora aqui e, se a versao for mais nova que a dele, a
tela avisa. Quem aceita baixa o setup que o manifesto aponta, com o tamanho e o hash conferidos, e o app roda o
instalador em modo silencioso: o Windows pede a permissao, o instalador fecha a Vitrola, troca o que precisa na pasta
dela e abre de novo (o /reabrir=1 do vitrola.iss). Um download que para no meio continua de onde parou.

Sao dois setups. O completo (caminho A) troca a pasta inteira. A parcial (caminho B, uns 15 MB contra 160) traz so os
arquivos que mudaram desde a versao anterior: o app so a usa quando todo o resto do que esta instalado bate com a lista
de arquivos do manifesto (o tamanho ao consultar, o hash antes de baixar) e nao sobra arquivo de outra versao na
_internal\\ nem na bin\\. Senao, vai o completo. Por isso ela serve tambem a quem esta algumas versoes atras, desde que
as bibliotecas nao tenham mudado no meio. Um app que nao conhece a parcial nao olha para ela e segue no completo.

O ponto de confianca e a chave: so vale o manifesto assinado por ela, e so para uma versao mais nova que a que esta
rodando, entao um manifesto velho, mesmo assinado, nao volta a versao. A lista de arquivos e a parcial vao dentro do
manifesto, assinadas com ele.

As versoes ficam nas Releases do repo publico ritmelli/ritmelli-releases: o "latest" do GitHub e sempre a ultima
publicada, com o manifesto, a assinatura e o setup. A chave 1 e a que a esteira de publicacao (no repo privado ritmelli-server) usa para assinar.
Rodando pelo codigo, nada e consultado, porque ai quem atualiza e o git. Os testes (dev/testa_atualizacao.py) trocam
os tres."""
import base64
import ctypes
import hashlib
import http.client
import json
import re
import ssl
import sys
import threading
import time
import urllib.request
from pathlib import Path

import i18n
import pastas
from versao import VERSAO

# o endereco https do manifest.json; a assinatura e o mesmo endereco com ".sig" no fim
MANIFESTO = "https://github.com/ritmelli/ritmelli-releases/releases/latest/download/manifest.json"
# numero -> chave publica Ed25519 (os 32 bytes em base64); o .sig diz qual delas assinou
CHAVES = {1: "Bnvi5qyGzrl2bPDgG9UUCDHjhcTCU3lr9SHMKbkjLts="}
SO_HTTPS = True  # os testes servem por http, numa porta local
FORMATO = 1
PASTA = pastas.DADOS / "atualizacao"
# a pasta do app instalado (a do vitrola.exe), que a parcial confere; pelo codigo nao ha, e vai sempre o completo
PASTA_APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else None
CONSULTA_APOS_S = 30.0       # depois de abrir: a subida do app nao divide a rede com a consulta
CONSULTA_CADA_S = 6 * 3600.0
# a pagina do PC aberta de novo consulta, se a ultima consulta tem mais que isso (o ao_abrir)
CONSULTA_AO_ABRIR_S = 5 * 60.0
# depois de uma consulta que nao chegou ao manifesto (sem rede, tempo esgotado): de novo logo, e cada vez mais espacado,
# ate voltar aos 6 h. Um manifesto recusado (assinatura, formato) nao conta: tentar de novo logo nao muda a resposta
DE_NOVO_S = (2 * 60.0, 5 * 60.0, 15 * 60.0, 30 * 60.0, 60 * 60.0)
TEMPO_S = 20.0              # o manifesto e pequeno; o setup tem o mesmo prazo entre um pedaco e outro
# o download que parou no meio (a rede caiu, ou a conexao fechou antes do fim): de novo, de onde parou, depois de cada
# espera. Uma tentativa que avancou zera a conta; sem avancar em nenhuma, desiste, e a tela pede para tentar de novo
DE_NOVO_BAIXA_S = (2.0, 5.0, 15.0, 30.0)
MANIFESTO_MAX = 1 << 20
SETUP_MAX = 1 << 30
PEDACO = 1 << 20
# o instalador sem janela; /reabrir=1 abre a Vitrola de novo no fim, como quem instalou (vitrola.iss)
PARAMETROS = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /reabrir=1"
SE_ERR_ACCESSDENIED = 5      # o ShellExecute com o pedido de permissao recusado


class Recusado(ValueError):
    """O manifesto ou o arquivo nao passa na conferencia."""


class Parou(OSError):
    """O download parou no meio: e a rede, e nao o arquivo."""


def _recusado(e):
    """A mensagem da tela para o manifesto ou o arquivo que nao passou na conferencia, com o motivo como veio."""
    return i18n.msg("server.update.rejected", "The new version failed the check ({reason}).", reason=str(e))


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
        _caminho(a["caminho"])
    if "parcial" in m:
        _confere_parcial(m["parcial"], {a["caminho"] for a in m.get("arquivos", [])})
    return m


def _caminho(c):
    """Um caminho de arquivo do manifesto: o caminho B confere arquivo por arquivo, e nada sai da pasta do app."""
    p = c.replace("\\", "/")
    if not p or p.startswith("/") or ":" in p or ".." in p.split("/"):
        raise Recusado(f"caminho de arquivo recusado no manifesto: {c!r}")


def _confere_parcial(p, caminhos):
    """A parcial (o caminho B): o setup com o que mudou, o que ele traz (tudo da lista de arquivos) e o que apaga."""
    if not (isinstance(p, dict) and isinstance(p.get("url"), str) and _sha(p.get("sha256"))
            and isinstance(p.get("tamanho"), int) and 0 < p["tamanho"] <= SETUP_MAX
            and isinstance(p.get("arquivos"), list) and p["arquivos"] and isinstance(p.get("apaga", []), list)):
        raise Recusado("a atualização parcial do manifesto está fora do formato")
    if not p["url"].startswith("https://" if SO_HTTPS else ("https://", "http://")):
        raise Recusado("a atualização parcial do manifesto não vem por https")
    versao(p.get("de"))
    for c in p["arquivos"]:
        if not isinstance(c, str) or c not in caminhos:
            raise Recusado("a atualização parcial traz um arquivo fora da lista do manifesto")
    for c in p.get("apaga", []):
        if not isinstance(c, str) or c in caminhos:
            raise Recusado("a atualização parcial apaga um arquivo da lista do manifesto")
        _caminho(c)


def cabe_parcial(m, pasta, hash_=False):
    """Se a parcial do manifesto m serve para o app instalado em pasta: cada arquivo da lista que ela nao traz ja esta
    la, igual (o tamanho; com hash_, tambem o sha256, uns segundos para os ~350 MB), e nao sobra na _internal\\ nem na
    bin\\ arquivo que a versao nova nao tem (fora os que a parcial apaga). Sem pasta (pelo codigo), nunca."""
    p = m.get("parcial")
    if not p or not pasta:
        return False
    traz = set(p["arquivos"])
    # o Windows nao diferencia maiuscula de minuscula no nome
    conhecidos = {a["caminho"].lower() for a in m["arquivos"]} | {c.lower() for c in p.get("apaga", [])}
    try:
        for a in m["arquivos"]:
            if a["caminho"] in traz:
                continue
            f = pasta / a["caminho"]
            if f.stat().st_size != a["tamanho"] or (hash_ and _hash(f) != a["sha256"]):
                return False
        for raiz in ("_internal", "bin"):
            for f in (pasta / raiz).rglob("*"):
                if f.is_file() and f.relative_to(pasta).as_posix().lower() not in conhecidos:
                    return False
    except OSError:
        return False
    return True


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
    (o setup baixado e conferido) e instalando. O setup e a parcial, quando ela serve, ou o completo."""

    def __init__(self, ativa=None):
        congelado = getattr(sys, "frozen", False)
        self.ativa = bool(MANIFESTO and CHAVES and congelado) if ativa is None else ativa
        self.lock = threading.Lock()
        self.nova = None        # o manifesto conferido de uma versao mais nova que a VERSAO
        self.estado = "parado"
        self.progresso = 0.0
        self.erro = None        # o que deu errado na ultima acao, para a tela (a mensagem, i18n.msg)
        self.consultada = None  # quando a ultima consulta deu certo
        self.ultima = None      # o time.monotonic() da ultima consulta, certa ou nao
        self.falhas = 0         # consultas seguidas que nao chegaram ao manifesto
        self.parcial = False    # se a parcial da versao nova serve para o que esta instalado (pelo tamanho, ate baixar)
        self.setup = None       # o setup baixado e conferido (o completo ou a parcial)
        self.alvo = None        # o que o manifesto diz desse setup: o "instalador" ou a "parcial"

    def _escolhido(self):
        """O setup que vai ser baixado: a parcial, quando serve, ou o completo."""
        return self.nova["parcial"] if self.parcial else self.nova["instalador"]

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
                                   "tamanho": self._escolhido()["tamanho"], "parcial": self.parcial}}

    def vigia(self):
        """A thread que consulta logo depois de abrir e de tempos em tempos (o proxima)."""
        self._limpa()
        time.sleep(CONSULTA_APOS_S)
        while True:
            self.consultar()
            time.sleep(self.proxima())

    def proxima(self):
        """Segundos ate a proxima consulta: 6 h, ou o DE_NOVO_S depois de consultas que nao chegaram ao manifesto. Num
        PC lento ou numa rede que ainda subia, a primeira consulta, 30 s depois de abrir, estourava o prazo, e a versao
        nova so aparecia 6 h depois."""
        with self.lock:
            f = self.falhas
        if not f or f > len(DE_NOVO_S):  # sem falha, ou ja tentou todas: o PC deve estar sem rede
            return CONSULTA_CADA_S
        return min(DE_NOVO_S[f - 1], CONSULTA_CADA_S)

    def ao_abrir(self):
        """A pagina do PC abriu: o atalho clicado de novo com a Vitrola ligada, ou a aba recarregada. Fechar a janela
        nao fecha a Vitrola, entao sem isto a versao nova so aparecia na consulta seguinte, ate 6 h depois. Consulta
        numa thread se a ultima consulta tem mais de CONSULTA_AO_ABRIR_S; nao antes da primeira da vigia, que vem logo
        depois de abrir, nem no meio de um download. True se foi consultar."""
        if not self.ativa:
            return False
        with self.lock:
            if self.estado != "parado" or self.ultima is None or time.monotonic() - self.ultima < CONSULTA_AO_ABRIR_S:
                return False
            self.ultima = time.monotonic()  # duas paginas abrindo juntas: so uma consulta
        threading.Thread(target=self.consultar, daemon=True).start()
        return True

    def consultar(self):
        """Baixa e confere o manifesto. True se ha versao nova."""
        if not self.ativa:
            return False
        with self.lock:
            if self.estado != "parado":
                return self.nova is not None
            self.estado, self.erro, self.ultima = "consultando", None, time.monotonic()
        try:
            m = confere(_pega(MANIFESTO, MANIFESTO_MAX), _pega(MANIFESTO + ".sig", 4096))
        except (OSError, ValueError) as e:
            with self.lock:
                self.estado = "parado"
                if isinstance(e, Recusado):
                    self.erro, self.falhas = _recusado(e), 0
                else:
                    self.erro = i18n.msg("server.update.checkFailed", "Couldn't check for a new version.")
                    self.falhas += 1
            print(f"atualizacao: {e}", flush=True)
            return self.nova is not None
        nova = versao(m["versao"]) > versao(VERSAO)
        serve = nova and cabe_parcial(m, PASTA_APP)  # so o tamanho de cada arquivo: rapido
        with self.lock:
            self.estado, self.consultada, self.falhas = "parado", time.strftime("%Y-%m-%dT%H:%M:%S"), 0
            if nova:
                if not self.nova or self.nova["versao"] != m["versao"]:
                    self.nova, self.parcial, self.setup, self.alvo = m, serve, None, None
                    serve_mb = f" (a parcial serve: {m['parcial']['tamanho'] / 2**20:.1f} MB)" if serve else ""
                    print(f"atualizacao: versao nova {m['versao']}{serve_mb}", flush=True)
            else:
                self.nova = self.setup = self.alvo = None
                self.parcial = False
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
        with self.lock:
            parcial = self.parcial
        # a consulta so conferiu o tamanho: antes de baixar a parcial, o hash de tudo que ela nao traz
        if parcial and not cabe_parcial(m, PASTA_APP, hash_=True):
            print("atualizacao: o que esta instalado nao bate com o manifesto; vai o setup completo", flush=True)
            parcial = False
            with self.lock:
                self.parcial = False
        inst = m["parcial"] if parcial else m["instalador"]
        PASTA.mkdir(parents=True, exist_ok=True)
        final = PASTA / f"Vitrola-{m['versao']}-{'parcial' if parcial else 'setup'}.exe"
        meio = final.with_name(final.name + ".baixando")
        try:
            with open(meio, "wb") as f:
                self._puxa(inst, f)
            # o hash do que ficou no disco, que veio em pedacos quando o download parou no meio
            if _hash(meio) != inst["sha256"]:
                raise Recusado("o instalador baixado não confere com o manifesto")
            meio.replace(final)
        except (OSError, ValueError) as e:
            meio.unlink(missing_ok=True)
            with self.lock:
                self.estado = "parado"
                self.erro = _recusado(e) if isinstance(e, Recusado) else i18n.msg(
                    "server.update.downloadStopped", "The new version download stopped. Try again.")
                if parcial and isinstance(e, Recusado):
                    self.parcial = False  # a parcial veio errada: na proxima, o completo
            print(f"atualizacao: {e}", flush=True)
            return
        with self.lock:
            self.setup, self.alvo, self.estado, self.progresso = final, inst, "pronta", 1.0
        print(f"atualizacao: {final.name} baixado e conferido", flush=True)

    def _puxa(self, inst, f):
        """Baixa o setup no f, ate o tamanho do manifesto. Se a rede cai ou a conexao fecha antes do fim (o http.client
        nao acusa: so entrega menos bytes), pede de novo so o que falta (o Range), depois de uma espera do
        DE_NOVO_BAIXA_S; se o servidor manda o arquivo inteiro outra vez, recomeca do zero. Parou quando nenhuma das
        tentativas seguidas avancou."""
        tam, seguidas = inst["tamanho"], 0
        while True:
            n = antes = f.tell()
            cab = {"User-Agent": f"Vitrola/{VERSAO}"}
            if n:
                cab["Range"] = f"bytes={n}-"
            try:
                req = urllib.request.Request(inst["url"], headers=cab)
                with urllib.request.urlopen(req, timeout=TEMPO_S, context=_tls()) as r:
                    if n and not (r.status == 206 and r.headers.get("Content-Range", "").startswith(f"bytes {n}-")):
                        # o servidor nao continuou de onde parou: o que vier e do comeco
                        f.seek(0)
                        f.truncate()
                        n = 0
                        if r.status != 200:
                            raise Parou(f"o servidor respondeu {r.status} sem continuar de onde parou")
                    while b := r.read(PEDACO):
                        if n + len(b) > tam:
                            raise Recusado("o instalador baixado é maior que o do manifesto")
                        f.write(b)
                        n += len(b)
                        with self.lock:
                            self.progresso = n / tam
                motivo = "a conexão fechou antes do fim"
            except (OSError, http.client.HTTPException) as e:
                motivo = e
            n = f.tell()
            if n == tam:
                return
            seguidas = 0 if n > antes else seguidas + 1
            if seguidas > len(DE_NOVO_BAIXA_S):
                raise Parou(f"o download parou em {n / 2**20:.1f} de {tam / 2**20:.1f} MB ({motivo})")
            espera = DE_NOVO_BAIXA_S[max(seguidas - 1, 0)]
            print(f"atualizacao: o download parou em {n / 2**20:.1f} de {tam / 2**20:.1f} MB ({motivo}); "
                  f"de novo em {espera:.0f} s", flush=True)
            time.sleep(espera)

    def instalar(self):
        """Confere o setup de novo e roda ele com o pedido de permissao do Windows. (True, None) se o instalador
        abriu, e ai a Vitrola deve fechar; senao (False, a mensagem do motivo)."""
        with self.lock:
            if self.estado != "pronta" or not self.setup:
                return False, i18n.msg("server.update.notDownloaded", "The new version hasn't been downloaded yet.")
            setup, m, alvo = self.setup, self.nova, self.alvo
        if not setup.exists() or _hash(setup) != alvo["sha256"]:
            with self.lock:
                self.estado, self.setup, self.alvo = "parado", None, None
            return False, i18n.msg("server.update.changed", "The downloaded installer changed after it was checked. "
                                   "Download it again.")
        log = PASTA / f"instalador-{m['versao']}.log"
        r = abre_instalador(setup, f'{PARAMETROS} /LOG="{log}"')
        if r <= 32:
            if r == SE_ERR_ACCESSDENIED:
                return False, i18n.msg("server.update.permissionDenied", "Windows didn't give permission, so the "
                                       "update was postponed.")
            return False, i18n.msg("server.update.installerFailed", "The installer didn't open (error {code}).", code=r)
        with self.lock:
            self.estado = "instalando"
        print(f"atualizacao: instalador da {m['versao']} aberto; a Vitrola fecha", flush=True)
        return True, None

    def _limpa(self):
        """Tira os setups de versoes que ja nao sao novas e os downloads que pararam no meio."""
        if not PASTA.exists():
            return
        for f in PASTA.iterdir():
            v = re.fullmatch(r"Vitrola-(.+)-(?:setup|parcial)\.exe", f.name)
            try:
                # .baixando: o download pela metade (o .parcial e o nome de antes da parcial existir)
                velho = f.name.endswith((".baixando", ".parcial")) or (v and versao(v.group(1)) <= versao(VERSAO))
                if velho:
                    f.unlink()
            except (OSError, ValueError):
                pass


def abre_instalador(setup, parametros):
    """O ShellExecute com o verbo runas, o que pede a permissao de administrador: o instalador pede, e um subprocess
    comum falharia (WinError 740). Volta o codigo do ShellExecute: acima de 32 e sucesso."""
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", str(setup), parametros, None, 1)
