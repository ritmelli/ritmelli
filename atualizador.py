"""A atualizacao automatica, sem UAC (#45 e #98), como a do Chrome: a tarefa do Windows "Vitrola Atualiza", que o
instalador cria, roda como SYSTEM o proprio vitrola.exe instalado com --atualizador, no logon e de 4 em 4 horas. Ela
consulta o manifesto assinado, baixa a versao nova (a parcial, quando serve, ou o completo) e, com a Vitrola fechada,
roda o instalador em silencio. Com a Vitrola aberta, a versao fica baixada e conferida, e entra quando ela fechar: a
Vitrola, ao sair, dispara a tarefa (ao_sair). Ninguem clica em nada e o Windows nao pergunta.

Seguranca: a tarefa roda como SYSTEM um arquivo baixado da internet, entao nada do que ela usa sai de onde quem usa o PC
grava. O comando e fixo (o vitrola.exe da pasta do app, em Program Files) e quem usa o PC so pode disparar a tarefa,
nao muda-la. A versao instalada e a da propria tarefa (o versao.py do executavel). O manifesto so vale assinado pela
chave que mora no executavel, e so para uma versao mais nova. O setup e baixado e conferido (o hash do manifesto) na
pasta atualizacao\\ do app, que so administrador grava, e conferido de novo logo antes de rodar: conferir onde o usuario
grava e rodar depois deixaria um programa dele trocar o arquivo no meio. O estado.json da mesma pasta e so leitura para
quem usa o PC: e por ele que a tela da Vitrola mostra o andamento.

Para testar fora do GitHub (a esteira faz), o endereco do manifesto e a chave podem vir do HKLM\\SOFTWARE\\Vitrola\\
Atualizador (Manifesto, Chave em base64 e SoHttps 0), que so administrador grava.

    vitrola.exe --atualizador            a rodada da tarefa (como SYSTEM)
    vitrola.exe --atualizador tarefa     cria (ou refaz) a tarefa: o instalador chama
    vitrola.exe --atualizador remove     apaga a tarefa e a pasta: o desinstalador chama"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import atualizacao as atu
import pastas
from versao import VERSAO

TAREFA = "Vitrola Atualiza"
PASTA = pastas.APP / "atualizacao"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REG = r"SOFTWARE\Vitrola\Atualizador"
# a Vitrola acabou de pedir (ao sair): ela ainda esta terminando de fechar, e os auxiliares dela (o --yt) vao junto
ESPERA_FECHAR_S = 20.0
# o instalador em silencio, sem /reabrir: rodando como SYSTEM, a Vitrola abriria como SYSTEM. Quem reabre e o
# reabre(), como quem usa o PC
PARAMETROS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
ESPERA_INSTALAR_S = 300.0  # quanto o reabre() espera o instalador terminar, antes de abrir a Vitrola assim mesmo
TENTATIVAS = 2  # instalador da mesma versao que terminou sem trocar a versao: depois disso, so a proxima versao

TAREFA_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Ritmelli: baixa e instala as atualizações quando o Ritmelli está fechado.</Description>
    <SecurityDescriptor>D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;AU)</SecurityDescriptor>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><Delay>PT2M</Delay></LogonTrigger>
    <TimeTrigger>
      <Repetition><Interval>PT4H</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary><Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Sistema"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Sistema">
    <Exec><Command>{exe}</Command><Arguments>--atualizador</Arguments></Exec>
  </Actions>
</Task>
"""


def log(texto):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {texto}", flush=True)


# ---------- o estado, que a tela le ----------

def estado():
    """O estado.json da pasta do app ({} sem ele, ou ilegivel)."""
    try:
        e = json.loads((PASTA / "estado.json").read_text(encoding="utf-8"))
        return e if isinstance(e, dict) else {}
    except (OSError, ValueError):
        return {}


def _grava(**kw):
    """Grava o estado. A tela le o estado.json a cada mudanca (o progresso do download muda a cada pedaco), e o Windows
    nao troca um arquivo que alguem esta lendo (Access is denied): tenta de novo por ate uns 5 s, em vez de a rodada
    inteira desistir no meio do download, como aconteceu na esteira (18/11)."""
    e = {k: v for k, v in estado().items() if k not in ("erro",)}
    e.update(kw, quando=time.strftime("%Y-%m-%dT%H:%M:%S"))
    PASTA.mkdir(parents=True, exist_ok=True)
    for i in range(GRAVA_TENTATIVAS):
        try:
            pastas.save_json(PASTA / "estado.json", e)
            return e
        except PermissionError:
            if i == GRAVA_TENTATIVAS - 1:
                raise
            time.sleep(min(0.05 * (i + 1), 0.5))
    return e


GRAVA_TENTATIVAS = 20


# ---------- os processos ----------

class _PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _processos():
    """[(pid, nome do exe)] de todo processo da maquina (sem abrir nenhum: vale para os de outra sessao e os do
    SYSTEM)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return []
    out, pe = [], _PE()
    pe.dwSize = ctypes.sizeof(_PE)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            out.append((pe.th32ProcessID, pe.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return out


def _caminho(pid):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
    finally:
        k32.CloseHandle(h)


def app_aberta():
    """Algum vitrola.exe desta pasta rodando, fora este: a Vitrola, os auxiliares dela ou a tarefa do microfone. O que
    nao deu para olhar conta como aberto: na duvida, a versao espera."""
    meu = os.getpid()
    for pid, nome in _processos():
        if pid == meu or nome.lower() != "vitrola.exe":
            continue
        c = _caminho(pid)
        if c is None or Path(c).parent.resolve() == pastas.APP.resolve():
            return True
    return False


def vivo(pid):
    return any(p == pid for p, _ in _processos())


# ---------- a rodada da tarefa (SYSTEM) ----------

def _config():
    """O endereco do manifesto, as chaves e se exige https: os do atualizacao.py, ou os do HKLM (os testes)."""
    url, chaves, so_https = atu.MANIFESTO, atu.CHAVES, True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG) as k:
            def le(nome):
                try:
                    return winreg.QueryValueEx(k, nome)[0]
                except OSError:
                    return None
            if le("Manifesto"):
                url = str(le("Manifesto"))
            if le("Chave"):
                chaves = {1: str(le("Chave"))}
            if le("SoHttps") == 0:
                so_https = False
    except OSError:
        pass
    return url, chaves, so_https


def _limpa():
    """Os setups de versoes que ja nao sao novas e os downloads pela metade."""
    if not PASTA.exists():
        return
    for f in PASTA.glob("Vitrola-*"):
        nome = f.name
        try:
            v = nome.split("-")[1]
            if nome.endswith(".baixando") or atu.versao(v) <= atu.versao(VERSAO):
                f.unlink()
        except (OSError, ValueError, IndexError):
            pass


def _baixa(m, parcial):
    """Baixa o setup na PASTA e confere o hash. O caminho do arquivo conferido."""
    inst = m["parcial"] if parcial else m["instalador"]
    final = PASTA / f"Vitrola-{m['versao']}-{'parcial' if parcial else 'setup'}.exe"
    if final.exists() and atu._hash(final) == inst["sha256"]:
        return final
    meio = final.with_name(final.name + ".baixando")
    puxa = atu.Atualizacao(ativa=True)  # o download que continua de onde parou (o _puxa do app)
    fim = threading.Event()

    def andamento():
        while not fim.wait(2.0):
            with puxa.lock:
                p = puxa.progresso
            _grava(estado="baixando", progresso=round(p, 3))
    t = threading.Thread(target=andamento, daemon=True)
    t.start()
    try:
        with open(meio, "wb") as f:
            puxa._puxa(inst, f)
        if atu._hash(meio) != inst["sha256"]:
            raise atu.Recusado("the downloaded installer doesn't match the manifest")
        meio.replace(final)
    finally:
        fim.set()
        t.join()
        meio.unlink(missing_ok=True)
    return final


def _lanca(setup, log_setup):
    """O instalador, solto: ele troca o vitrola.exe desta rodada, entao a rodada sai logo depois de abrir ele."""
    cf = 0x00000008 | 0x00000200 | NO_WINDOW  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    args = [str(setup), *PARAMETROS, f"/LOG={log_setup}"]
    try:
        return subprocess.Popen(args, creationflags=cf | 0x01000000, close_fds=True).pid  # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        return subprocess.Popen(args, creationflags=cf, close_fds=True).pid


def rodada(espera_fechar=ESPERA_FECHAR_S):
    """Consulta, baixa e, com a Vitrola fechada, instala. Sai com o estado gravado; nunca levanta."""
    e = estado()
    if e.get("estado") == "instalando" and not vivo(e.get("pid") or -1):
        # o instalador da rodada anterior terminou: esta rodada ja e a versao nova (ou nao, e ai conta a falha)
        ok = e.get("versao") == VERSAO
        falhas = {} if ok else dict(e.get("falhas") or {})
        if not ok:
            falhas[str(e.get("versao"))] = int(falhas.get(str(e.get("versao")), 0)) + 1
        _grava(estado="instalada" if ok else "parado", instalada=VERSAO if ok else e.get("instalada"), falhas=falhas,
               erro=None if ok else f"the installer for {e.get('versao')} didn't finish (see {e.get('log')})")
        log(f"previous install: {'done' if ok else 'failed'} ({e.get('versao')})")
    _limpa()
    url, chaves, so_https = _config()
    atu.SO_HTTPS = so_https
    try:
        m = atu.confere(atu._pega(url, atu.MANIFESTO_MAX), atu._pega(url + ".sig", 4096), chaves)
    except (OSError, ValueError) as ex:
        _grava(estado=estado().get("estado") if estado().get("estado") == "pronta" else "parado", erro=str(ex))
        log(f"check: {ex}")
        return
    if atu.versao(m["versao"]) <= atu.versao(VERSAO):
        _grava(estado="parado", nova=None, progresso=0.0)
        log(f"no new version (installed {VERSAO}, published {m['versao']})")
        return
    tentou = int((estado().get("falhas") or {}).get(m["versao"], 0))
    if tentou >= TENTATIVAS:
        # o instalador desta versao ja falhou de novo e de novo: espera a proxima, em vez de rodar de 4 em 4 horas
        _grava(estado="parado", progresso=0.0,
               erro=f"the installer for {m['versao']} failed {tentou} times; waiting for the next version")
        log(f"{m['versao']}: the installer failed {tentou} times; not trying again")
        return
    publico = {"versao": m["versao"], "data": m.get("data"), "notas": m.get("notas", []), "notas_en": m.get("notas_en", [])}
    parcial = atu.cabe_parcial(m, pastas.APP, hash_=True)
    inst = m["parcial"] if parcial else m["instalador"]
    _grava(estado="baixando", progresso=0.0, nova=dict(publico, tamanho=inst["tamanho"], parcial=parcial))
    try:
        setup = _baixa(m, parcial)
    except (OSError, ValueError) as ex:
        _grava(estado="parado", progresso=0.0, erro=str(ex))
        log(f"download: {ex}")
        return
    _grava(estado="pronta", progresso=1.0, setup=setup.name, sha256=inst["sha256"])
    log(f"{setup.name} downloaded and checked")
    fim = time.monotonic() + espera_fechar
    while app_aberta():
        if time.monotonic() >= fim:
            log("Vitrola is open: the new version goes in when it closes")
            return
        time.sleep(1.0)
    instala(setup, inst["sha256"], m["versao"])


def instala(setup, sha256, versao_nova):
    """Confere o setup de novo, aqui mesmo, e roda ele em silencio."""
    if not setup.exists() or atu._hash(setup) != sha256:
        setup.unlink(missing_ok=True)
        _grava(estado="parado", progresso=0.0, erro="the downloaded installer changed after it was checked")
        log("the installer changed after it was checked; it will be downloaded again")
        return
    log_setup = PASTA / f"instalador-{versao_nova}.log"
    pid = _lanca(setup, log_setup)
    _grava(estado="instalando", pid=pid, versao=versao_nova, de=VERSAO, log=log_setup.name)
    log(f"installer for {versao_nova} started (pid {pid})")


# ---------- a tarefa ----------

def tarefa_existe():
    if sys.platform != "win32":
        return False
    r = subprocess.run(["schtasks", "/query", "/tn", TAREFA], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def tarefa_cria():
    """Cria (ou refaz) a tarefa, so no executavel instalado: pelo codigo, a tarefa rodaria como SYSTEM um .py que o
    usuario pode mudar."""
    if not getattr(sys, "frozen", False):
        print("the update task is only created by the installed executable")
        return 0
    import tempfile
    from xml.sax.saxutils import escape
    fd, xml = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(xml, "w", encoding="utf-16") as f:
            f.write(TAREFA_XML.replace("{exe}", escape(sys.executable)))
        r = subprocess.run(["schtasks", "/create", "/tn", TAREFA, "/xml", xml, "/f"], capture_output=True, text=True,
                           encoding="oem", errors="replace", creationflags=NO_WINDOW)
    finally:
        os.remove(xml)
    if r.returncode:
        print(f"couldn't create the task ({r.returncode}): {r.stdout.strip()} {r.stderr.strip()}")
        return r.returncode
    print(f"task {TAREFA} created")
    return 0


def tarefa_apaga():
    """Para a rodada que estiver no meio (esperando a Vitrola fechar, ela instalaria por cima do desinstalador) e apaga
    a tarefa."""
    for args in (["/end"], ["/delete", "/f"]):
        subprocess.run(["schtasks", *args, "/tn", TAREFA], capture_output=True, creationflags=NO_WINDOW)


def dispara():
    """Roda a tarefa agora (quem usa o PC pode: so nao pode muda-la). False se ela nao existe ou nao rodou."""
    r = subprocess.run(["schtasks", "/run", "/tn", TAREFA], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


# ---------- o lado do app (quem usa o PC) ----------

def automatica():
    """A atualizacao vai pela tarefa: o app instalado e a tarefa existe (a versao que a criou em diante)."""
    return getattr(sys, "frozen", False) and tarefa_existe()


def ao_sair(reabrir=False):
    """A Vitrola fechou: com a versao nova baixada, a tarefa instala agora. reabrir (o Instalar agora da tela): a
    Vitrola abre de novo quando o instalador terminar."""
    if estado().get("estado") != "pronta" or not dispara():
        return
    log("Vitrola closed with a new version ready: the update task runs now")
    if reabrir:
        reabre()


def reabre():
    """Abre a Vitrola de novo quando o instalador terminar, como quem usa o PC. Quem espera e um PowerShell solto, fora
    da pasta do app: um vitrola.exe esperando seguraria os arquivos que o instalador troca. Espera a tarefa comecar a
    instalar e o instalador sair, ate ESPERA_INSTALAR_S, e abre a Vitrola assim mesmo."""
    e = str(PASTA / "estado.json").replace("'", "''")
    exe = str(pastas.APP / "vitrola.exe").replace("'", "''")
    ps = (f"$e='{e}';$fim=(Get-Date).AddSeconds({ESPERA_INSTALAR_S:.0f});$s=$null;"
          "do{Start-Sleep 1;try{$s=Get-Content -LiteralPath $e -Raw|ConvertFrom-Json}catch{}}"
          "while(($s -eq $null -or $s.estado -ne 'instalando') -and (Get-Date) -lt $fim);"
          "if($s -and $s.estado -eq 'instalando'){while((Get-Process -Id $s.pid -ErrorAction SilentlyContinue) -and "
          "(Get-Date) -lt $fim){Start-Sleep 1}};"
          f"Start-Process -FilePath '{exe}'")
    args = ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps]
    # com um console escondido (o NO_WINDOW), e nao sem nenhum: o PowerShell aberto com DETACHED_PROCESS sai sem rodar
    # o comando. Fora do job de quem abriu a Vitrola, quando der: ela fecha logo depois
    cf = NO_WINDOW | 0x00000200  # CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(args, creationflags=cf | 0x01000000, close_fds=True)  # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen(args, creationflags=cf, close_fds=True)


def instalando_agora():
    """O instalador da tarefa esta rodando (a Vitrola foi aberta no meio da atualizacao)."""
    e = estado()
    return e.get("estado") == "instalando" and isinstance(e.get("pid"), int) and vivo(e["pid"])


def main(args):
    modo = args[0] if args else "rodada"
    if modo == "tarefa":
        return tarefa_cria()
    if modo == "remove":
        tarefa_apaga()
        return 0
    if modo != "rodada":
        print(f"unknown mode: {modo}")
        return 2
    if not getattr(sys, "frozen", False):
        print("the update round only runs in the installed executable")
        return 0
    PASTA.mkdir(parents=True, exist_ok=True)
    arq = PASTA / "atualizador.log"
    try:
        if arq.stat().st_size > 1 << 20:  # o log de meses: fica so o da vez anterior
            arq.replace(arq.with_name("atualizador.anterior.log"))
    except OSError:
        pass
    with open(arq, "a", encoding="utf-8", buffering=1) as f:
        sys.stdout = sys.stderr = f
        try:
            rodada()
        except Exception as ex:  # noqa: BLE001 - a rodada nunca derruba a tarefa sem dizer por que
            log(f"error: {type(ex).__name__}: {ex}")
            _grava(estado="parado", erro=f"{type(ex).__name__}: {ex}")
    return 0
