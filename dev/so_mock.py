"""As ferramentas de dev/ so falam com um servidor --mock, nunca com o Ritmelli de verdade (a porta 8799, que toca no
jogo de quem esta jogando). So da biblioteca padrao: o dev/testa_mock.py usa este modulo, e a esteira roda ele antes de
instalar as bibliotecas do app.

O servidor --mock poe "mock": true no GET /api/state, no JSON de quem pode ler e no 401 do pareamento. A conferencia:
- a porta nao e a 8799 (pastas.PORTA);
- o GET /api/state na origem pedida, sem seguir redirecionamento e sem proxy, e um desses dois JSON com o marcador.
Servidor sem o marcador e recusado: nao ha excecao.

Quem abre o tema (shot, fitcheck, perfcheck, celular) chama o confere antes de abrir a pagina e o confere_pagina antes
de agir; no Chrome, o DOCUMENTOS e o libera_ou_barra barram o documento de outra origem (o redirecionamento).
Quem sobe o proprio servidor (compara, previews, testa_mock) usa o sobe: a porta recusada antes do Popen se e a 8799 ou
se alguem ja responde nela, e cada pedido, o /api/shutdown inclusive, so com o filho vivo e o marcador na origem; se
nao, so o filho sai, pelo handle. Os medidores que abrem o anel de verdade saem antes com o sai_se_o_app_ligado."""
import ctypes
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pastas import PORTA as PORTA_DO_APP  # noqa: E402 - 8799

# no Fetch.enable do CDP: cada documento (a pagina, um iframe, um redirecionamento dele) para antes do pedido
DOCUMENTOS = [{"urlPattern": "*", "resourceType": "Document", "requestStage": "Request"}]


class Recusa(Exception):
    """O servidor nao e um --mock que a ferramenta pode usar; a mensagem diz por que."""


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913 - a assinatura do urllib
        return None  # o 3xx vira HTTPError, e quem chamou decide


# sem proxy (o testa_mock aponta o HTTP_PROXY do servidor para uma armadilha) e sem seguir redirecionamento
_DIRETO = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SemRedirecionar())


def abre(req, espera=15):
    """O urlopen das ferramentas: sem proxy e sem seguir redirecionamento (o 3xx sai como HTTPError)."""
    return _DIRETO.open(req, timeout=espera)


def free_port():
    """Uma porta livre em 127.0.0.1, nunca a do app."""
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p != PORTA_DO_APP:
            return p


def porta_responde(porta, host="127.0.0.1", espera=0.5):
    """Alguem aceita conexao nessa porta."""
    try:
        with socket.create_connection((host, porta), timeout=espera):
            return True
    except OSError:
        return False


def origem(url):
    """(a origem do url como o location.origin a escreve, a porta). So http, com a porta dita."""
    u = urllib.parse.urlsplit(url)
    try:
        porta = u.port
    except ValueError:
        porta = None
    if u.scheme != "http" or not u.hostname or porta is None:
        raise Recusa(f"{url}: o endereco de um --mock e http://<host>:<porta>/...")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    return f"http://{host}:{porta}", porta


def mesma_origem(url, base):
    try:
        return origem(url)[0] == base
    except Recusa:
        return False


def estado(base, espera=5):
    """O GET /api/state da origem base, se e de um --mock: o JSON de quem pode ler ou o 401 do pareamento, os dois com
    "mock": true. Recusa se responde outra coisa (um redirecionamento inclusive); OSError se ninguem respondeu."""
    try:
        with abre(base + "/api/state", espera) as r:
            status, corpo = r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            status, corpo = e.code, e.read()
        if 300 <= status < 400:
            raise Recusa(f"{base}/api/state redireciona ({status}) para {e.headers.get('Location')}: so vale a "
                         "origem pedida") from None
    if status not in (200, 401):
        raise Recusa(f"{base}/api/state respondeu {status}")
    try:
        j = json.loads(corpo)
    except ValueError:
        j = None
    if not isinstance(j, dict) or j.get("mock") is not True:
        raise Recusa(f"{base} nao e um servidor --mock (o /api/state sem o \"mock\": true)")
    if status == 401 and j.get("parear") is not True:
        raise Recusa(f"{base}/api/state respondeu 401 sem ser o do pareamento")
    return j


def confere(url, espera=5):
    """Antes de abrir a pagina: a porta do url nao e a do app e a origem dele responde como um --mock. Volta a origem;
    Recusa se nao (fora do ar inclusive)."""
    base, porta = origem(url)
    if porta == PORTA_DO_APP:
        raise Recusa(f"a porta {porta} e a do Ritmelli de verdade: as ferramentas de dev/ so usam um servidor --mock "
                     "noutra porta (python server.py --mock --port 8801 --no-browser)")
    try:
        estado(base, espera)
    except OSError as ex:
        raise Recusa(f"{base} nao respondeu ({ex})") from None
    return base


def confere_pagina(url, origem_da_pagina):
    """Antes de agir: a pagina segue na origem do url (o location.origin dela) e ela segue um --mock."""
    base = confere(url)
    if origem_da_pagina != base:
        raise Recusa(f"a pagina saiu de {base} para {origem_da_pagina}")
    return base


def libera_ou_barra(params, base):
    """A resposta ao Fetch.requestPaused do CDP: (metodo, params). O documento de outra origem e barrado."""
    if mesma_origem(params["request"]["url"], base):
        return "Fetch.continueRequest", {"requestId": params["requestId"]}
    return "Fetch.failRequest", {"requestId": params["requestId"], "errorReason": "BlockedByClient"}


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _Limits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _Members(ctypes.Structure):
    _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD), ("NumberOfProcessIdsInList", wintypes.DWORD),
                ("ProcessIdList", ctypes.c_size_t * 256)]


def _kernel():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.OpenProcess.restype = wintypes.HANDLE
    return k


class _Accounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


def _resume(process):
    return ctypes.WinDLL("ntdll").NtResumeProcess(wintypes.HANDLE(int(process)))


class _Job:
    def __init__(self, process):
        k = self.k = _kernel()
        self.job = k.CreateJobObjectW(None, None)
        limits = _Limits()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        ok = bool(self.job
                  and k.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                  and k.AssignProcessToJobObject(self.job, wintypes.HANDLE(int(process))))
        if not ok:
            error = ctypes.get_last_error()
            self.close()
            raise Recusa(f"o servidor de teste nao entrou num job (erro {error})")

    def active(self):
        info = _Accounting()
        if not self.k.QueryInformationJobObject(self.job, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise Recusa(f"o job do servidor de teste nao respondeu (erro {ctypes.get_last_error()})")
        return info.ActiveProcesses

    def members(self):
        listed = _Members()
        self.k.QueryInformationJobObject(self.job, 3, ctypes.byref(listed), ctypes.sizeof(listed), None)
        found = []
        for pid in listed.ProcessIdList[:listed.NumberOfProcessIdsInList]:
            handle = self.k.OpenProcess(0x00100000 | 0x1000, False, pid)
            inside = wintypes.BOOL()
            if handle and self.k.IsProcessInJob(wintypes.HANDLE(handle), self.job, ctypes.byref(inside)) and inside:
                found.append(handle)
            elif handle:
                self.k.CloseHandle(wintypes.HANDLE(handle))
        return found

    def end(self, seconds=10.0):
        if not self.job:
            return
        try:
            closed = _Limits()
            closed.BasicLimitInformation.LimitFlags = 0x2000 | 0x8
            closed.BasicLimitInformation.ActiveProcessLimit = 1
            if not self.k.SetInformationJobObject(self.job, 9, ctypes.byref(closed), ctypes.sizeof(closed)):
                raise Recusa(f"o job do servidor de teste nao fechou para processos novos (erro {ctypes.get_last_error()})")
            handles = self.members()
            try:
                if not self.k.TerminateJobObject(self.job, 1):
                    raise Recusa(f"o job do servidor de teste nao foi encerrado (erro {ctypes.get_last_error()})")
                fim = time.monotonic() + seconds
                for handle in handles:
                    left = max(0, int((fim - time.monotonic()) * 1000))
                    if self.k.WaitForSingleObject(wintypes.HANDLE(handle), left) != 0:
                        raise Recusa(f"os processos do servidor de teste nao sairam em {seconds:g} s")
            finally:
                for handle in handles:
                    self.k.CloseHandle(wintypes.HANDLE(handle))
            if self.active():
                raise Recusa("o job do servidor de teste ainda tem processos depois de encerrado")
        finally:
            self.close()

    def close(self):
        if self.job:
            self.k.CloseHandle(wintypes.HANDLE(self.job))
        self.job = None


def start_job(cmd, **popen):
    if sys.platform != "win32":
        return subprocess.Popen(cmd, **popen), None
    flags = popen.pop("creationflags", 0)
    proc = subprocess.Popen(cmd, creationflags=flags | 0x4, **popen)
    handle = getattr(proc, "_handle", None)
    if handle is None:
        return proc, None
    job = None
    try:
        job = _Job(handle)
        status = _resume(handle) & 0xFFFFFFFF
        if status:
            raise Recusa(f"o servidor de teste nao foi retomado (NTSTATUS {status:#010x})")
    except BaseException:
        _kernel().TerminateProcess(wintypes.HANDLE(int(handle)), 1)
        proc.wait(10)
        if job:
            job.close()
        raise
    return proc, job


class Filho:
    """O servidor --mock que a ferramenta subiu (srv, o Popen) na porta dela. Cada pedido, o /api/shutdown inclusive,
    so com ele vivo e a origem respondendo com o marcador; se nao, so ele sai, pelo handle."""

    def __init__(self, srv, porta, job=None):
        self.srv, self.porta, self.base, self.job = srv, porta, f"http://127.0.0.1:{porta}", job

    def confere(self):
        if self.srv.poll() is not None:
            raise Recusa(f"o servidor de teste saiu (codigo {self.srv.returncode})")
        try:
            estado(self.base)
        except OSError as ex:
            raise Recusa(f"{self.base} nao respondeu ({ex})") from None
        if self.srv.poll() is not None:  # saiu durante o GET: quem respondeu e outro
            raise Recusa(f"o servidor de teste saiu (codigo {self.srv.returncode})")

    def api(self, metodo, rota, corpo=None, espera=15):
        self.confere()
        req = urllib.request.Request(self.base + rota, method=metodo,
                                     data=None if corpo is None else json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json"})
        with abre(req, espera) as r:
            return json.load(r)

    def mata(self):
        if self.job:
            self.job.end()
            self.srv.wait(10)
            return
        if self.srv.poll() is None:
            self.srv.kill()
        self.srv.wait()

    def encerra(self, espera=10):
        """O /api/shutdown, se ele ainda e o --mock que subiu; se nao, ou se ele nao sai, o handle."""
        try:
            self.api("POST", "/api/shutdown", espera=5)
            self.srv.wait(espera)
        except (Recusa, OSError, ValueError, subprocess.TimeoutExpired):
            self.mata()
            return
        if self.job:
            self.job.end()


def sobe(cmd, porta, limite=30.0, **popen):
    """Sobe o servidor --mock (cmd e popen vao ao Popen) na porta. Antes, recusa a porta do app e a porta em que alguem
    ja responde; depois, so aceita a resposta com o filho vivo e o marcador. Volta o Filho; Recusa, com o filho
    encerrado pelo handle, se nao."""
    if porta == PORTA_DO_APP:
        raise Recusa(f"a porta {porta} e a do Ritmelli de verdade: o servidor de teste sobe noutra")
    if porta_responde(porta):
        raise Recusa(f"a porta {porta} ja responde: outro servidor esta nela")
    proc, job = start_job(cmd, **popen)
    f = Filho(proc, porta, job)
    fim = time.monotonic() + limite
    try:
        while True:
            if f.srv.poll() is not None:
                raise Recusa(f"o servidor de teste saiu ao subir (codigo {f.srv.returncode})")
            try:
                estado(f.base, 2)
            except OSError:
                if time.monotonic() > fim:
                    raise Recusa(f"o servidor de teste nao respondeu em {limite:g} s") from None
                time.sleep(0.1)
                continue
            if f.srv.poll() is None:  # quem respondeu pode ser outro, e o filho ter caido por nao achar a porta
                return f
    except BaseException:
        f.mata()
        raise


def sai_se_o_app_ligado(o_que):
    """Para os medidores que abrem o anel do filtro de verdade: com a porta do app aceitando conexao (o Ritmelli
    ligado), sai com erro antes de abrir qualquer coisa."""
    if porta_responde(PORTA_DO_APP):
        sys.exit(f"o Ritmelli esta ligado (a porta {PORTA_DO_APP} aceita conexao): {o_que} e manual, para um Windows "
                 "de teste com ele desligado; nada foi aberto")
