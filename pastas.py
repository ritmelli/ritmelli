"""Onde moram as coisas. Os dados de quem usa ficam fora da pasta do app, porque instalado em Program Files
ela nao aceita escrita: audio baixado, biblioteca e escolhas em library/; os logs do servidor em logs/. Os logs
das ferramentas de dev/ (logs/efeitos/) seguem na pasta do codigo. O ffmpeg, o ffprobe e o deno vem na bin/ do
app (o instalador poe); sem ela, saem do PATH, como no codigo. A porta do servidor e a pagina que o app abre moram
aqui tambem: o ritmelli.py precisa delas antes de carregar o servidor. E o jeito de gravar os .json dos dados
(save_json), o mesmo para o servidor e para o pareamento, e a regra da pasta protegida (pasta_protegida), que as
duas tarefas que rodam como SYSTEM conferem antes de usar a pasta do app."""
import json
import ntpath
import os
import re
import sys
import time
from pathlib import Path

_BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home())
DADOS_NOVA = _BASE / "Ritmelli"
# a pasta de antes da troca de nome (#58; ate a 0.4.1 o app se chamava Vitrola): enquanto o migra() nao a renomeia,
# os dados seguem nela, e nenhum processo grava em duas pastas
DADOS_VELHA = _BASE / "Vitrola"


def _tem_discos(pasta):
    """A prateleira da pasta de dados tem algum disco: a library.json maior que o [] vazio. Pelo tamanho que a listagem
    da pasta ja traz, sem abrir o arquivo: todo processo que carrega este modulo passa por aqui, e o Windows nao deixa o
    save_json do servidor ligado trocar a library.json enquanto outro processo a tem aberta."""
    try:
        with os.scandir(pasta / "library") as itens:
            return any(e.name == "library.json" and e.stat().st_size > 2 for e in itens)
    except OSError:
        return False


# os dados seguem na de antes quando so ela existe, e tambem (#111) com as duas, a nova sem discos e a de antes com eles:
# o soundboard.ps1 criava a nova (a dos logs) antes de o migra() rodar, que achava a troca feita, e o app abria a
# prateleira vazia
DADOS = (DADOS_VELHA if DADOS_VELHA.is_dir() and (not DADOS_NOVA.exists()
                                                  or (not _tem_discos(DADOS_NOVA) and _tem_discos(DADOS_VELHA)))
         else DADOS_NOVA)
LIB = DADOS / "library"
LOGS = DADOS / "logs"
# a pasta do executavel no app congelado (PyInstaller), a do codigo fora dele
APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BIN = APP / "bin"
PORTA = 8799  # a do servidor: o PC abre em 127.0.0.1, o celular no IP da rede de casa
# o tema, e nao a galeria de temas (que segue em /): quem acabou de instalar cai direto no toca-discos. Ate a 0.6.0 o
# tema era o /t/vitrola/, e o servidor leva o endereco de antes para este (TEMA_DE_ANTES, no server.py)
PAGINA = "/t/ritmelli/"


def migra():
    """Os dados da pasta de antes da troca de nome (%LOCALAPPDATA%\\Vitrola) passam para a %LOCALAPPDATA%\\Ritmelli,
    com a biblioteca, as escolhas, o codigo dos dados de uso e o que a janela guarda: so o servidor chama, ao ligar,
    antes de carregar os modulos que gravam nela. Renomear e instantaneo (mesmo disco); se a pasta velha estiver
    presa (o Explorer aberto nela, um arquivo em uso), os dados seguem nela nesta abertura e a troca tenta de novo na
    proxima. Com as duas pastas, a nova sem discos e a de antes com eles (#111), a nova sai do caminho antes, para a
    Ritmelli-no-records-<data e hora> ao lado: nada do que ela tem se perde. True se os dados estao na pasta nova."""
    global DADOS, LIB, LOGS
    if DADOS == DADOS_NOVA:
        return True
    if DADOS_NOVA.exists():
        lado = DADOS_NOVA.with_name(f"{DADOS_NOVA.name}-no-records-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            DADOS_NOVA.rename(lado)
        except OSError as e:
            print(f"data folder: {DADOS_NOVA} has no records and {DADOS_VELHA} has; couldn't move the empty one aside "
                  f"({e}); using the old one for now", flush=True)
            return False
        print(f"data folder: {DADOS_NOVA} had no records and {DADOS_VELHA} has; moved the empty one to {lado}", flush=True)
    try:
        DADOS_VELHA.rename(DADOS_NOVA)
    except OSError as e:
        print(f"data folder: couldn't move {DADOS_VELHA} to {DADOS_NOVA} ({e}); using the old one for now", flush=True)
        return False
    DADOS, LIB, LOGS = DADOS_NOVA, DADOS_NOVA / "library", DADOS_NOVA / "logs"
    return True


def dados_do_mock(pedida=None):
    """A pasta de dados do servidor no --mock (#117). O download de mentira copia o disco mais curto da prateleira com
    outro nome: na pasta de quem usa, cada musica adicionada no teste virava um disco falso, com a duracao do som curto
    (e entrava nos Sons rapidos). Sem --data-dir, uma pasta temporaria nova, que sai quando o servidor fecha (o App
    copia para ela a library.json de quem usa); a pasta de quem usa, nem pedida: None."""
    if pedida is None:
        import atexit
        import shutil
        import tempfile
        p = Path(tempfile.mkdtemp(prefix="ritmelli-mock-"))
        atexit.register(shutil.rmtree, p, True)
        return p
    p = Path(pedida)
    def igual(d):
        return os.path.normcase(os.path.realpath(d))   # a caixa, o ..\ e o nome curto do Windows (CHRIST~1)
    reais = {igual(d) for d in (LIB, DADOS_NOVA / "library", DADOS_VELHA / "library")}
    return None if igual(p) in reais else p


def ferramenta(nome):
    """O caminho de nome.exe na BIN, ou None (ai vale o do PATH)."""
    p = BIN / f"{nome}.exe"
    return str(p) if p.exists() else None


TROCA_ESPERA_S = 1.0  # quanto o save_json tenta de novo a troca que o Windows recusa


def save_json(path, data):
    """Grava num temporario e troca de uma vez: o app caindo no meio nunca deixa o arquivo pela metade. O temporario
    tem nome unico e fica na pasta do destino (a troca so e de uma vez no mesmo disco): duas gravacoes ao mesmo tempo
    no mesmo arquivo nao escrevem no mesmo temporario. O Windows recusa trocar o arquivo enquanto alguem o tem aberto,
    inclusive a outra gravacao trocando o dela (PermissionError): tenta de novo por ate TROCA_ESPERA_S. Se falha, o
    temporario sai."""
    import tempfile
    path = Path(path)
    texto = json.dumps(data, ensure_ascii=False, indent=1)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        fim = time.monotonic() + TROCA_ESPERA_S
        while True:
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if time.monotonic() >= fim:
                    raise
                time.sleep(0.01)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------- a pasta protegida ----------
# As duas tarefas do Windows (a do filtro de microfone e a da atualizacao) rodam como SYSTEM o ritmelli.exe da pasta do
# app, e a da atualizacao ainda roda dali o setup baixado. Isso so e seguro se ninguem alem do sistema e dos
# administradores consegue trocar o que esta na pasta. A regra (a mesma do instalador, o instalador\protegida.ps1):
# - o caminho, normalizado (sem ..), fica dentro da raiz (Program Files), e nem ele, nem nenhum ancestral, nem nada
#   dentro dele e ponto de reanalise (juncao, link simbolico);
# - o dono da pasta e de tudo que existe dentro dela e SYSTEM, Administradores ou TrustedInstaller;
# - nenhuma ACE de permissao da a outro principal escrita (dos dados, dos atributos ou dos atributos estendidos),
#   acrescimo ou criacao, exclusao (inclusive a de filhos), WRITE_DAC ou WRITE_OWNER. A so de heranca do CREATOR OWNER
#   fica de fora (toda subpasta de Program Files a herda, e ela vira a de quem cria o filho); as outras so de heranca
#   contam, porque o que nascer depois da conferencia as herdaria. A mesma regra de dono e de ACE vale para cada pasta
#   entre a raiz (inclusive) e o destino: um pai que deixe outro apagar ou trocar a pasta do app reprova. DACL nula ou
#   ilegivel reprova, e tambem um nome que o Windows nao abre como esta (terminado em ponto ou espaco);
# - a excecao: na microfone\log, onde nada se executa, o LocalService (o audiodg.exe grava o log do filtro) pode
#   escrever, criar e apagar, nunca WRITE_DAC nem WRITE_OWNER na pasta, e ser dono dos arquivos de log (e ter controle
#   total sobre os que sao dele), nunca da pasta.
# Destino que ainda nao existe e conferido pelos ancestrais que existem.
SID_SYSTEM = "S-1-5-18"
SID_ADMINS = "S-1-5-32-544"
SID_TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
SID_LOCAL_SERVICE = "S-1-5-19"
DONOS = frozenset((SID_SYSTEM, SID_ADMINS, SID_TRUSTED_INSTALLER))
LOG_DO_FILTRO = ("microfone", "log")
# FILE_WRITE_DATA, FILE_APPEND_DATA (criar arquivo e subpasta), FILE_WRITE_EA, FILE_DELETE_CHILD,
# FILE_WRITE_ATTRIBUTES (basta para transformar uma pasta vazia em juncao), DELETE, WRITE_DAC, WRITE_OWNER, e os
# genericos que valem por eles (GENERIC_WRITE, GENERIC_ALL)
_ESCRITA = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000
_TROCA_ACL = 0x40000 | 0x80000 | 0x10000000  # WRITE_DAC, WRITE_OWNER, GENERIC_ALL
_SO_HERANCA = 0x08  # INHERIT_ONLY_ACE: a ACE nao vale para o proprio objeto
# CREATOR OWNER: so de heranca, vira a ACE de quem cria o filho (um dos donos, ou o LocalService no log dele). Qualquer
# outra ACE so de heranca que de escrita reprova, inclusive a do CREATOR GROUP (vira a do grupo primario de quem cria,
# que numa conta local e o None, de todos os usuarios): o que nasce depois da conferencia (o setup baixado, a DLL
# copiada) a herdaria
_CRIADORES = ("S-1-3-0",)
_PERMITE = (0, 9)  # ACCESS_ALLOWED e ACCESS_ALLOWED_CALLBACK
# o MAX_PATH: um caminho desse tamanho em diante, sem o \\?\, o Windows diz que nao existe, e ele escaparia da regra.
# Reprova nas duas conferencias (nenhuma instalacao chega perto)
_MAX_PATH = 260
_NEGA = (1, 6, 10, 12)  # as de negacao (simples, de objeto e callback) so tiram acesso


class Reprovada:
    """A pasta nao passou na regra: falso num if, e o motivo no str."""

    def __init__(self, motivo):
        self.motivo = motivo

    def __bool__(self):
        return False

    def __str__(self):
        return self.motivo

    def __repr__(self):
        return f"Reprovada({self.motivo!r})"


def do_windows(nome):
    """O caminho completo de um programa do Windows (na System32). Pelo nome solto, o CreateProcess procura antes na
    pasta do executavel, que e justamente a que a regra da pasta protegida confere: com ela reprovada, o desarme das
    tarefas rodaria como SYSTEM um schtasks.exe posto la. Fora do Windows, o nome."""
    if sys.platform != "win32":
        return nome
    import ctypes
    b = ctypes.create_unicode_buffer(260)
    n = ctypes.windll.kernel32.GetSystemDirectoryW(b, 260)
    if not 0 < n < 260:
        raise OSError("GetSystemDirectoryW failed")
    return os.path.join(b.value, nome)


def raiz_protegida():
    """A Program Files de 64 bits (a do %ProgramW6432%), onde so administrador cria pasta."""
    return os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"


def _le_disco(caminho):
    """O objeto do disco como a regra le: None se nao existe; senao {dir, reparse, dono, dacl, filhos}, com a dacl como
    [(tipo, flags, mascara, sid)] ou None (nula) e os filhos como uma funcao que lista a pasta (so a arvore do destino a
    chama). Abre o proprio objeto, sem seguir ponto de reanalise. OSError se nao da para ler."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    adv.GetSecurityInfo.restype = wintypes.DWORD
    adv.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]

    class Info(ctypes.Structure):  # BY_HANDLE_FILE_INFORMATION
        _fields_ = [("atributos", wintypes.DWORD), ("t", wintypes.DWORD * 6), ("serie", wintypes.DWORD),
                    ("tam", wintypes.DWORD * 2), ("links", wintypes.DWORD), ("indice", wintypes.DWORD * 2)]

    def sid_texto(p):
        s = ctypes.c_wchar_p()
        if not adv.ConvertSidToStringSidW(p, ctypes.byref(s)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return s.value
        finally:
            k32.LocalFree(s)

    # READ_CONTROL | FILE_READ_ATTRIBUTES; FILE_FLAG_BACKUP_SEMANTICS (abre pasta) | FILE_FLAG_OPEN_REPARSE_POINT
    h = k32.CreateFileW(str(caminho), 0x20000 | 0x80, 7, None, 3, 0x02000000 | 0x00200000, None)
    if h in (None, wintypes.HANDLE(-1).value):
        erro = ctypes.get_last_error()
        if erro in (2, 3):  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND
            return None
        raise ctypes.WinError(erro)
    try:
        info = Info()
        if not k32.GetFileInformationByHandle(h, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        dono, dacl, sd = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        # SE_FILE_OBJECT; OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        r = adv.GetSecurityInfo(h, 1, 0x1 | 0x4, ctypes.byref(dono), None, ctypes.byref(dacl), None, ctypes.byref(sd))
        if r:
            raise ctypes.WinError(r)
        try:
            aces = None
            if dacl.value:
                aces = []
                n = ctypes.cast(dacl.value + 4, ctypes.POINTER(ctypes.c_uint16))[0]  # ACL.AceCount
                for i in range(n):
                    p = ctypes.c_void_p()
                    if not adv.GetAce(dacl, i, ctypes.byref(p)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    tipo, flags = ctypes.cast(p.value, ctypes.POINTER(ctypes.c_uint8))[0:2]
                    if tipo in (0, 1, 9, 10):  # a mascara em +4 e o SID em +8
                        mascara = ctypes.cast(p.value + 4, ctypes.POINTER(ctypes.c_uint32))[0]
                        aces.append((tipo, flags, mascara, sid_texto(p.value + 8)))
                    else:
                        aces.append((tipo, flags, 0, None))
            d = {"dir": bool(info.atributos & 0x10), "reparse": bool(info.atributos & 0x400),
                 "dono": sid_texto(dono.value) if dono.value else None, "dacl": aces}
        finally:
            k32.LocalFree(sd)
    finally:
        k32.CloseHandle(h)
    if d["dir"] and not d["reparse"]:
        # so quando a arvore pede (os ancestrais nao precisam): a listagem pode ser negada onde a leitura passa
        d["filhos"] = lambda: os.listdir(caminho)
    return d


def _confere_objeto(caminho, d, no_log):
    """O motivo pelo qual o dono ou a DACL do objeto reprovam, ou None."""
    dono = d.get("dono")
    if dono not in DONOS and not (no_log and not d["dir"] and dono == SID_LOCAL_SERVICE):
        return f"{caminho} is owned by {dono}"
    aces = d.get("dacl")
    if aces is None:
        return f"{caminho} has a null DACL"
    for tipo, flags, mascara, sid in aces:
        if flags & _SO_HERANCA and not d["dir"]:  # num arquivo, a so de heranca nao vale nem tem para quem passar
            continue
        if tipo in _NEGA:
            continue
        if tipo not in _PERMITE:
            return f"{caminho} has an ACE of type {tipo}"
        if sid in DONOS or not mascara & _ESCRITA:
            continue
        if flags & _SO_HERANCA and sid in _CRIADORES:  # vira a ACE de quem cria o filho, que ja e um dos donos
            continue
        # o LocalService na microfone\log: escrever, criar e apagar; o controle total so num arquivo que e dele (o
        # micfx.log que o audiodg.exe cria depois da rotacao herda o CREATOR OWNER como LocalService:F)
        if no_log and sid == SID_LOCAL_SERVICE and (not mascara & _TROCA_ACL
                                                     or (not d["dir"] and dono == SID_LOCAL_SERVICE)):
            continue
        return f"{caminho} lets {sid} write or change it (access 0x{mascara:08x})"
    return None


def _confere_arvore(caminho, d, le):
    """O motivo pelo qual o objeto ou algo dentro dele reprova, ou None. Nao entra em ponto de reanalise: reprova."""
    pilha = [(caminho, d, ())]
    while pilha:
        caminho, d, rel = pilha.pop()
        if d["reparse"]:
            return f"{caminho} is a reparse point"
        # a propria microfone\log so como pasta: um arquivo com esse nome nao e o log do filtro
        no_log = tuple(p.lower() for p in rel[:2]) == LOG_DO_FILTRO and (len(rel) > 2 or d["dir"])
        motivo = _confere_objeto(caminho, d, no_log)
        if motivo:
            return motivo
        filhos = d.get("filhos") if d["dir"] else None
        if callable(filhos):
            try:
                filhos = filhos()
            except OSError as e:
                return f"couldn't list {caminho}: {e}"
        for nome in filhos or ():
            filho = ntpath.join(caminho, nome)
            if nome[-1:] in (".", " "):  # o Windows corta o fim do nome ao abrir: a leitura acharia outro objeto
                return f"{filho} has a name Windows can't open"
            if _utf16(filho) >= _MAX_PATH:  # sem o \\?\, o Windows diria que nao existe, e ele passaria sem conferir
                return f"{filho} is too long to check"
            try:
                df = le(filho)
            except OSError as e:
                return f"couldn't read {filho}: {e}"
            if df is not None:  # o que sumiu no meio da conferencia ja nao esta la
                pilha.append((filho, df, (*rel, nome)))
    return None


def _utf16(s):
    """O tamanho em unidades UTF-16, como o Windows (e o .Length do PowerShell) conta."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def _nome_curto(nome):
    """O componente tem a forma de um alias 8.3 (PROGRA~1, RITMEL~1.EXE): ate 8 caracteres com um ~ seguido de digito e
    uma extensao de ate 3, sem o ponto ou o espaco do fim (o Windows os corta). Os tamanhos contam em UTF-16, como no
    instalador. Um nome longo com ~ (Ritmelli~2026, Ritmelli~Estudio) nao e alias."""
    base, ponto, ext = nome.rstrip(". ").partition(".")
    return ("." not in ext and 1 <= _utf16(base) <= 8 and (not ponto or 1 <= _utf16(ext) <= 3)
            and re.search(r"~[0-9]", base) is not None)


def motivo_desprotegida(pasta, raiz, le=_le_disco):
    """Por que a pasta nao passa na regra da pasta protegida, ou None se passa. le(caminho) e quem le cada objeto (o
    _le_disco, ou uma descricao em memoria nos testes)."""
    pasta, raiz = ntpath.normpath(str(pasta)), ntpath.normpath(str(raiz))
    unidade, resto = ntpath.splitdrive(pasta)
    if any(_nome_curto(p) for p in resto.split("\\")):
        # um nome curto (8.3, como PROGRA~1): o instalador (o GetFullPath do .NET Framework) o expandiria, e a regra tem
        # de dar o mesmo veredito nos dois
        return f"{pasta} has a short (8.3) name"
    if not unidade or not ntpath.isabs(pasta) or not ntpath.isabs(raiz):
        return f"{pasta} is not an absolute path"
    if not ntpath.normcase(pasta).startswith(ntpath.normcase(raiz).rstrip("\\") + "\\"):
        return f"{pasta} is outside {raiz}"
    if _utf16(pasta) >= _MAX_PATH:  # antes de andar: um pai que ainda nao existe pararia a conta antes do fim
        return f"{pasta} is too long to check"
    partes = [p for p in resto.split("\\") if p]
    na_raiz = len([p for p in ntpath.splitdrive(raiz)[1].split("\\") if p])
    caminho = unidade + "\\"
    for i in range(len(partes) + 1):
        if i:
            caminho = ntpath.join(caminho, partes[i - 1])
        try:
            d = le(caminho)
        except OSError as e:
            return f"couldn't read {caminho}: {e}"
        if d is None:
            # o destino (ou um pai dele) ainda nao existe: valem os ancestrais que existem, a raiz inclusive
            return f"{raiz} doesn't exist" if i <= na_raiz else None
        if d["reparse"]:
            return f"{caminho} is a reparse point"
        if not d["dir"]:
            return f"{caminho} is not a folder"
        if i == len(partes):
            return _confere_arvore(caminho, d, le)
        if i >= na_raiz:  # da raiz ao pai do destino: dono e ACEs, sem olhar o que mais tem dentro
            motivo = _confere_objeto(caminho, d, False)
            if motivo:
                return motivo
    return None


def pasta_protegida(pasta=None, raiz=None, le=None):
    """True se a pasta (sem ela, a do sys.executable) passa na regra da pasta protegida dentro da raiz (sem ela, a
    Program Files de 64 bits); senao uma Reprovada, falsa, com o motivo. le e a leitura de cada objeto (os testes passam
    uma em memoria)."""
    pasta = Path(sys.executable).parent if pasta is None else pasta
    raiz = raiz_protegida() if raiz is None else raiz
    motivo = motivo_desprotegida(pasta, raiz, le or _le_disco)
    return True if motivo is None else Reprovada(motivo)
