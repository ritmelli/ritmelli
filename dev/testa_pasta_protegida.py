r"""Testa a regra da pasta protegida (pastas.pasta_protegida), a que as duas tarefas do Windows que rodam como SYSTEM
conferem antes de usar a pasta do app.

    python dev/testa_pasta_protegida.py           a avaliacao em memoria: roda em qualquer lugar, sem UAC
    python dev/testa_pasta_protegida.py --disco   no disco de verdade, numa pasta nova em Program Files (precisa de
                                                  administrador; sem ele, sai com erro)

Em memoria, um disco descrito objeto por objeto (dono, ACEs e ponto de reanalise) no lugar do de verdade: a pasta como
o setup cria em Program Files passa (com o CREATOR OWNER so de heranca, o TrustedInstaller, o SYSTEM, os
Administradores e o LocalService na microfone\log); reprovam o LocalService fora da microfone\log, com WRITE_DAC ou
dono da pasta de log, a escrita de Usuarios (S-1-5-32-545), o FILE_DELETE_CHILD de Usuarios num pai, a DACL nula, o
dono comum, o ponto de reanalise no caminho ou dentro da pasta, o caminho fora da raiz e o destino que ainda nao existe
dentro de um pai gravavel.

No disco, cria %ProgramW6432%\RitmelliTeste-<aleatorio>, que herda a ACL de Program Files e nasce com dono
Administradores, como a pasta que o setup cria, e confere os mesmos casos com icacls e juncoes de verdade; o finally
apaga a pasta. Sai 1 se algo falha."""
import ctypes
import ntpath
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pastas  # noqa: E402

SY, BA, TI, LS = pastas.SID_SYSTEM, pastas.SID_ADMINS, pastas.SID_TRUSTED_INSTALLER, pastas.SID_LOCAL_SERVICE
US = "S-1-5-32-545"  # Usuarios
CO = "S-1-3-0"  # CREATOR OWNER
APP = "S-1-15-2-1"  # ALL APPLICATION PACKAGES
EU = "S-1-5-21-1111111111-2222222222-3333333333-1001"  # quem roda o teste
F, M, RX, DC, WD = 0x1F01FF, 0x1301BF, 0x1200A9, 0x40, 0x40000
GA, GRGE = 0x10000000, 0xA0000000
HERDADA, OICI, IO = 0x10, 0x03, 0x08
RAIZ = r"C:\Program Files"
DESTINO = RAIZ + r"\Ritmelli"

falhas = []


def confere(nome, ok, detalhe=""):
    print(f"[{'ok' if ok else 'FALHOU'}] {nome}" + (f": {detalhe}" if detalhe and not ok else ""))
    if not ok:
        falhas.append(nome)


# ---------- em memoria ----------

def acl_raiz():
    """A ACL da Program Files de um Windows novo."""
    return [(0, 0, F, TI), (0, OICI | IO, GA, TI), (0, 0, M, SY), (0, OICI | IO, GA, SY), (0, 0, M, BA),
            (0, OICI | IO, GA, BA), (0, 0, RX, US), (0, OICI | IO, GRGE, US), (0, OICI | IO, GA, CO), (0, 0, RX, APP),
            (0, OICI | IO, GRGE, APP)]


def acl_pasta():
    """A ACL que uma pasta nova dentro da Program Files herda."""
    return [(0, HERDADA, F, TI), (0, HERDADA, M, SY), (0, HERDADA | OICI | IO, GA, SY), (0, HERDADA, M, BA),
            (0, HERDADA | OICI | IO, GA, BA), (0, HERDADA, RX, US), (0, HERDADA | OICI | IO, GRGE, US),
            (0, HERDADA | OICI | IO, GA, CO), (0, HERDADA, RX, APP), (0, HERDADA | OICI | IO, GRGE, APP)]


def acl_arquivo():
    return [(0, HERDADA, F, SY), (0, HERDADA, F, BA), (0, HERDADA, RX, US), (0, HERDADA, RX, APP)]


class Disco:
    """O disco descrito objeto por objeto, no formato do pastas._le_disco. ILEGIVEL na dacl: a leitura falha."""

    ILEGIVEL = "ilegivel"

    def __init__(self):
        self.obj = {}

    def poe(self, caminho, pasta=True, dono=BA, dacl=None, reparse=False):
        self.obj[caminho.lower()] = (caminho, {"dir": pasta, "reparse": reparse, "dono": dono,
                                               "dacl": (acl_pasta() if pasta else acl_arquivo()) if dacl is None else
                                               dacl})

    def muda(self, caminho, **kw):
        self.obj[caminho.lower()][1].update(kw)

    def le(self, caminho):
        achado = self.obj.get(ntpath.normpath(caminho).lower())
        if achado is None:
            return None
        d = dict(achado[1])
        if d["dacl"] == self.ILEGIVEL:
            raise PermissionError(13, "Access is denied", caminho)
        if d["dir"] and not d["reparse"]:
            pai = ntpath.normpath(caminho).lower()

            def filhos():  # so quando a regra pede, como no _le_disco; sem_lista: a listagem e negada
                if d.get("sem_lista"):
                    raise PermissionError(13, "Access is denied", caminho)
                return [ntpath.basename(c) for k, (c, _) in self.obj.items() if k != pai and ntpath.dirname(k) == pai]
            d["filhos"] = filhos
        return d


def disco_base():
    """A instalacao como o setup deixa em Program Files, com o log do filtro e a pasta da atualizacao."""
    d = Disco()
    d.poe("C:\\", dono=TI, dacl=[(0, 0, F, SY), (0, 0, 0x4, "S-1-5-11")])  # acima da raiz so conta o ponto de reanalise
    d.poe(RAIZ, dono=TI, dacl=acl_raiz())
    d.poe(DESTINO)
    d.poe(DESTINO + r"\ritmelli.exe", pasta=False)
    d.poe(DESTINO + r"\_internal")
    d.poe(DESTINO + r"\_internal\python312.dll", pasta=False)
    d.poe(DESTINO + r"\_internal\pasta-protegida.txt", pasta=False, dono=TI)
    d.poe(DESTINO + r"\bin")
    d.poe(DESTINO + r"\bin\ffmpeg.exe", pasta=False)
    d.poe(DESTINO + r"\microfone")
    d.poe(DESTINO + r"\microfone\micfx.dll", pasta=False)
    d.poe(DESTINO + r"\microfone\log", dacl=acl_pasta() + [(0, OICI, M, LS)])
    d.poe(DESTINO + r"\microfone\log\micfx.log", pasta=False, dono=LS, dacl=acl_arquivo() + [(0, HERDADA, M, LS)])
    d.poe(DESTINO + r"\atualizacao", dono=SY)
    d.poe(DESTINO + r"\atualizacao\estado.json", pasta=False, dono=SY)
    return d


def avalia(d, pasta=DESTINO, raiz=RAIZ):
    return pastas.pasta_protegida(pasta, raiz, le=d.le)


def reprova(nome, d, trecho, pasta=DESTINO, raiz=RAIZ):
    r = avalia(d, pasta, raiz)
    confere(f"reprova {nome}", not r and r is not True and trecho in str(r), repr(r))


def em_memoria():
    print("--- em memoria")
    d = disco_base()
    r = avalia(d)
    confere("a pasta como o setup cria: CREATOR OWNER so de heranca, donos TrustedInstaller, SYSTEM e Administradores, "
            "e o LocalService na microfone\\log", r is True, repr(r))
    d.muda(DESTINO, dacl=acl_pasta() + [(0, OICI | IO, M, US)])
    reprova("uma ACE so de heranca que da escrita a Usuarios (o que nascer depois a herdaria)", d, US)
    d = disco_base()
    d.muda(DESTINO, dacl=acl_pasta() + [(0, OICI | IO, F, "S-1-3-1")])
    reprova("a ACE so de heranca do CREATOR GROUP (vira a do grupo primario de quem cria, o None de todos)", d,
            "S-1-3-1")
    for direito, nome in ((0x2, "FILE_WRITE_DATA"), (0x4, "FILE_APPEND_DATA"), (0x10, "FILE_WRITE_EA"),
                          (0x40, "FILE_DELETE_CHILD"), (0x100, "FILE_WRITE_ATTRIBUTES"), (0x10000, "DELETE"),
                          (WD, "WRITE_DAC"), (0x80000, "WRITE_OWNER"), (0x40000000, "GENERIC_WRITE")):
        d = disco_base()
        d.poe(RAIZ + r"\Pai", dacl=acl_pasta() + [(0, 0, RX | direito, US)])
        d.poe(RAIZ + r"\Pai\Ritmelli")
        reprova(f"so o {nome} de Usuarios num pai", d, US, RAIZ + r"\Pai\Ritmelli")
    d = disco_base()
    # o micfx.log que o audiodg.exe cria depois da rotacao: dono LocalService, e o CREATOR OWNER herdado vira
    # LocalService:(F)
    d.muda(DESTINO + r"\microfone\log\micfx.log", dono=LS,
           dacl=acl_arquivo() + [(0, HERDADA, M, LS), (0, HERDADA, F, LS)])
    d.poe(DESTINO + r"\microfone\log\micfx.log.1", pasta=False, dacl=acl_arquivo() + [(0, HERDADA, M, LS)])
    confere("o log que o audiodg.exe cria depois da rotacao (LocalService dono, com controle total)", avalia(d) is True,
            repr(avalia(d)))
    d.muda(DESTINO + r"\microfone\log\micfx.log", dono=BA)
    reprova("o controle total do LocalService num log que nao e dele", d, LS)
    d = disco_base()
    d.muda(DESTINO + r"\ritmelli.exe", dacl=acl_arquivo() + [(1, 0, M, US)])
    confere("uma ACE de negacao so tira acesso", avalia(d) is True)
    d = disco_base()
    d.muda(DESTINO + r"\microfone\log\micfx.log", dono=LS)
    d.poe(DESTINO + r"\MICROFONE\LOG\micfx.anterior.log", pasta=False, dono=LS,
          dacl=acl_arquivo() + [(0, HERDADA, M, LS)])
    confere("a excecao da microfone\\log sem diferenca de caixa", avalia(d) is True, repr(avalia(d)))
    confere("um destino que ainda nao existe, dentro de uma pasta protegida", avalia(d, DESTINO + r"\Novo") is True)
    confere("um destino que ainda nao existe, direto na raiz", avalia(d, RAIZ + r"\Ritmelli-2") is True)
    d = disco_base()
    d.muda("C:\\", sem_lista=True)
    d.muda(RAIZ, sem_lista=True)
    confere("os ancestrais nao precisam ser listados (so a arvore do destino)", avalia(d) is True, repr(avalia(d)))
    d.muda(DESTINO + r"\_internal", sem_lista=True)
    reprova("uma pasta da arvore que nao se lista", d, "couldn't list")

    d = disco_base()
    d.muda(DESTINO + r"\_internal", dacl=acl_pasta() + [(0, OICI, M, LS)])
    reprova("a escrita do LocalService fora da microfone\\log", d, LS)
    d = disco_base()
    d.muda(DESTINO + r"\microfone\log", dacl=acl_pasta() + [(0, OICI, M | WD, LS)])
    reprova("o LocalService com WRITE_DAC na microfone\\log", d, LS)
    d = disco_base()
    d.muda(DESTINO + r"\microfone\log", dono=LS)
    reprova("o LocalService dono da pasta de log", d, "owned by " + LS)
    d = disco_base()
    d.muda(DESTINO + r"\_internal\python312.dll", dono=LS)
    reprova("o LocalService dono de um arquivo fora da microfone\\log", d, "owned by " + LS)
    d = disco_base()
    d.muda(DESTINO, dacl=acl_pasta() + [(0, OICI, M, US)])
    reprova("a escrita de *S-1-5-32-545 na pasta do app", d, US)
    d = disco_base()
    d.muda(DESTINO + r"\_internal\python312.dll", dacl=acl_arquivo() + [(0, 0, 0x2, US)])
    reprova("a escrita de Usuarios num arquivo da _internal", d, US)
    d = disco_base()
    d.poe(DESTINO + r"\atualizacao", dono=SY, dacl=acl_pasta() + [(0, OICI, M, US)])
    reprova("uma atualizacao\\ gravavel por Usuarios", d, "atualizacao")
    d = disco_base()
    d.muda(DESTINO + r"\bin\ffmpeg.exe", dacl=acl_arquivo() + [(0, 0, GA, US)])
    reprova("o GENERIC_ALL de Usuarios", d, US)
    d = disco_base()
    d.muda(RAIZ, dacl=acl_raiz() + [(0, 0, RX | DC, US)])
    reprova("o FILE_DELETE_CHILD de Usuarios na raiz", d, US)
    d = disco_base()
    d.poe(RAIZ + r"\Pai", dacl=acl_pasta() + [(0, 0, RX | DC, US)])
    d.poe(RAIZ + r"\Pai\Ritmelli")
    reprova("a pasta do app protegida num pai que da FILE_DELETE_CHILD a Usuarios", d, "Pai", RAIZ + r"\Pai\Ritmelli")
    d = disco_base()
    d.poe(RAIZ + r"\Pai", dono=EU)
    d.poe(RAIZ + r"\Pai\Ritmelli")
    reprova("um pai com dono comum", d, "owned by " + EU, RAIZ + r"\Pai\Ritmelli")
    d = disco_base()
    d.poe(RAIZ + r"\Gravavel", dacl=acl_pasta() + [(0, OICI, M, US)])
    reprova("um destino que ainda nao existe dentro de um pai gravavel por Usuarios", d, US, RAIZ + r"\Gravavel\Novo")
    d = disco_base()
    d.muda(DESTINO + r"\ritmelli.exe", dacl=None)
    reprova("a DACL nula", d, "null DACL")
    d = disco_base()
    d.muda(DESTINO + r"\_internal\python312.dll", dacl=Disco.ILEGIVEL)
    reprova("um arquivo ilegivel", d, "couldn't read")
    d = disco_base()
    d.muda(DESTINO + r"\ritmelli.exe", dono=EU)
    reprova("o dono comum", d, "owned by " + EU)
    d = disco_base()
    d.muda(DESTINO + r"\ritmelli.exe", dacl=acl_arquivo() + [(5, 0, 0, None)])
    reprova("uma ACE de um tipo que a regra nao conhece", d, "type 5")
    d = disco_base()
    d.muda(DESTINO + r"\_internal", reparse=True)
    reprova("uma juncao na _internal", d, "reparse point")
    d = disco_base()
    d.poe(DESTINO + r"\microfone\log\j", reparse=True)
    reprova("uma juncao dentro da microfone\\log", d, "reparse point")
    d = disco_base()
    d.poe(DESTINO + r"\microfone\log\x.", dono=LS)
    reprova("um nome terminado em ponto (o Windows abriria outro)", d, "can't open")
    d = disco_base()
    d.poe(DESTINO + r"\_internal\a ", pasta=False)
    reprova("um nome terminado em espaco", d, "can't open")
    d = disco_base()
    d.poe(DESTINO + "\\microfone\\log\\" + "x" * 230, dono=LS, reparse=True)
    reprova("um caminho de 260 caracteres ou mais na arvore (sem o \\\\?\\ o Windows diria que nao existe)", d,
            "too long")
    reprova("um destino de 260 caracteres ou mais", disco_base(), "too long", RAIZ + "\\" + "x" * 250)
    d = disco_base()
    d.poe(DESTINO + "\\microfone\\log\\" + "\U0001F3B5" * 115, dono=LS, reparse=True)
    reprova("um caminho de 260 ou mais em UTF-16 na arvore, com caracteres fora do BMP", d, "too long")
    reprova("um destino de 260 ou mais em UTF-16, com caracteres fora do BMP (contam dois, como no Windows)", disco_base(),
            "too long", RAIZ + "\\" + "\U0001F3B5" * 125)
    reprova("um destino de 260 ou mais com um pai que ainda nao existe", disco_base(), "too long",
            RAIZ + "\\novo\\" + "x" * 245)
    d = disco_base()
    del d.obj[(DESTINO + r"\microfone\log\micfx.log").lower()]
    d.muda(DESTINO + r"\microfone\log", dir=False, dono=LS, dacl=acl_arquivo() + [(0, 0, F, LS)])
    reprova("um arquivo do LocalService no lugar da microfone\\log (a excecao e so da pasta)", d, "owned by")
    d = disco_base()
    d.poe(DESTINO + "\\microfone\\log‍", dacl=acl_pasta() + [(0, OICI, M, LS)])
    reprova("o LocalService numa pasta irma com um caractere invisivel no nome (log + U+200D)", d, "lets " + LS)
    d = Disco()
    for chave, (caminho, desc) in disco_base().obj.items():
        caminho = caminho.replace(r"\microfone\log", r"\MICROFONE\LOG")
        d.obj[caminho.lower()] = (caminho, desc)
    confere("a microfone\\log em maiusculas (MICROFONE\\LOG) segue com a excecao", avalia(d) is True, repr(avalia(d)))
    d = disco_base()
    d.muda(DESTINO, reparse=True)
    reprova("a propria pasta do app como juncao", d, "reparse point")
    d = disco_base()
    d.obj.pop(DESTINO.lower())
    d.poe(DESTINO, pasta=False)
    for k in [k for k in d.obj if k.startswith(DESTINO.lower() + "\\")]:
        d.obj.pop(k)
    reprova("o proprio destino como arquivo", d, "not a folder")
    d = disco_base()
    d.poe(RAIZ + r"\J", reparse=True)
    reprova("uma juncao no caminho", d, "reparse point", RAIZ + r"\J\Ritmelli")
    reprova("um destino que ainda nao existe sob uma juncao", d, "reparse point", RAIZ + r"\J\Novo")
    reprova("uma pasta fora da raiz", disco_base(), "outside", r"C:\Ritmelli")
    reprova("um .. que sai da raiz", disco_base(), "outside", RAIZ + r"\Ritmelli\..\..\Ritmelli")
    reprova("a propria raiz", disco_base(), "outside", RAIZ)
    reprova("uma raiz que nao existe", disco_base(), "doesn't exist", r"C:\Outra\Ritmelli", r"C:\Outra")
    reprova("um caminho relativo", disco_base(), "absolute", r"Ritmelli")
    reprova("um nome curto 8.3 no caminho (o instalador o expandiria)", disco_base(), "short", r"C:\PROGRA~1\Ritmelli")
    reprova("um nome curto 8.3 dentro da raiz", disco_base(), "short", RAIZ + r"\RITMEL~1")
    reprova("um nome curto 8.3 com extensao", disco_base(), "short", RAIZ + r"\Ritmelli\RITMEL~1.EXE")
    reprova("um nome curto 8.3 terminado em ponto", disco_base(), "short", r"C:\PROGRA~1.\Ritmelli")
    reprova("um nome curto 8.3 terminado em espaco", disco_base(), "short", RAIZ + "\\RITMEL~1 ")
    d = disco_base()
    d.muda(DESTINO + r"\ritmelli.exe", dacl=acl_arquivo() + [(0, IO, M, US)])
    confere("uma ACE so de heranca num arquivo nao conta (nao vale nem tem filho)", avalia(d) is True,
            repr(avalia(d)))
    for longo in ("Ritmelli~Estudio", "Ritmelli~2026", "ABC\U0001F600DE~1"):
        d = disco_base()
        d.poe(RAIZ + "\\" + longo)
        confere(f"um ~ num nome longo de verdade ({longo!a}) nao e nome curto",
                avalia(d, RAIZ + "\\" + longo) is True, ascii(avalia(d, RAIZ + "\\" + longo)))
    r = avalia(disco_base(), r"C:\Ritmelli")
    confere("a recusa e falsa e diz o motivo", not r and "outside" in str(r) and isinstance(r, pastas.Reprovada))


# ---------- no disco ----------

def icacls(*args):
    r = subprocess.run(["icacls", *map(str, args)], capture_output=True, text=True, encoding="oem", errors="replace")
    if r.returncode:
        raise RuntimeError(f"icacls {' '.join(map(str, args))}: {r.stdout.strip()} {r.stderr.strip()}")


def juncao(link, alvo):
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(alvo)], capture_output=True, text=True,
                       encoding="oem", errors="replace")
    if r.returncode:
        raise RuntimeError(f"mklink /J {link}: {r.stdout.strip()} {r.stderr.strip()}")


def no_disco():
    print("--- no disco")
    if sys.platform != "win32" or not ctypes.windll.shell32.IsUserAnAdmin():
        print("--disco needs an elevated administrator (it creates a folder in Program Files)")
        return False
    raiz = Path(pastas.raiz_protegida())
    base = raiz / f"RitmelliTeste-{uuid.uuid4().hex[:8]}"
    juncoes = []

    def passa(nome, pasta=base):
        r = pastas.pasta_protegida(pasta)
        confere(f"passa: {nome}", r is True, repr(r))

    def reprova_disco(nome, pasta=base):
        r = pastas.pasta_protegida(pasta)
        confere(f"reprova: {nome}", not r and r is not True, repr(r))

    try:
        base.mkdir()
        (base / "ritmelli.exe").write_bytes(b"x")
        (base / "_internal").mkdir()
        (base / "_internal" / "python312.dll").write_bytes(b"x")
        log = base / "microfone" / "log"
        log.mkdir(parents=True)
        icacls(log, "/grant", "*S-1-5-19:(OI)(CI)M")
        (log / "micfx.log").write_bytes(b"x")
        # o log que o audiodg.exe cria depois da rotacao: dono LocalService, com o controle total do CREATOR OWNER
        rot = log / "micfx.log.1"
        rot.write_bytes(b"x")
        icacls(rot, "/setowner", "*S-1-5-19")
        icacls(rot, "/grant", "*S-1-5-19:F")
        passa("a pasta nova em Program Files, como o setup cria, com o LocalService na microfone\\log")

        icacls(base, "/grant", "*S-1-5-32-545:(OI)(CI)M")
        reprova_disco("a escrita de *S-1-5-32-545 na pasta")
        icacls(base, "/remove:g", "*S-1-5-32-545")
        passa("de novo protegida, sem a escrita de Usuarios")

        (base / "atualizacao").mkdir()
        icacls(base / "atualizacao", "/grant", "*S-1-5-32-545:(OI)(CI)M")
        reprova_disco("uma atualizacao\\ gravavel por Usuarios")
        shutil.rmtree(base / "atualizacao")

        icacls(base / "_internal", "/grant", "*S-1-5-19:(OI)(CI)M")
        reprova_disco("a escrita do LocalService fora da microfone\\log")
        icacls(base / "_internal", "/remove:g", "*S-1-5-19")

        caminho = raiz / f"{base.name}-j"
        juncao(caminho, base)
        juncoes.append(caminho)
        reprova_disco("uma juncao no caminho", caminho)
        for dentro in (base / "_internal" / "j", log / "j"):
            juncao(dentro, base / "microfone")
            juncoes.append(dentro)
            reprova_disco(f"uma juncao em {dentro.relative_to(base)}")
            os.rmdir(dentro)
            juncoes.remove(dentro)
        passa("sem as juncoes de dentro")

        eu = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
        icacls(base, "/setowner", eu)
        reprova_disco("o dono trocado para quem roda o teste (icacls /setowner)")
        icacls(base, "/setowner", "*S-1-5-32-544")

        pai = base / "pai"
        (pai / "app").mkdir(parents=True)
        icacls(pai, "/grant", "*S-1-5-32-545:(DC)")
        reprova_disco("a pasta do app protegida num pai que da FILE_DELETE_CHILD a Usuarios", pai / "app")

        grav = base / "gravavel"
        grav.mkdir()
        icacls(grav, "/grant", "*S-1-5-32-545:(OI)(CI)M")
        reprova_disco("um destino que ainda nao existe dentro de um pai gravavel por Usuarios", grav / "novo")
    except RuntimeError as e:
        confere("o preparo no disco", False, str(e))
    finally:
        for j in juncoes:
            try:
                os.rmdir(j)
            except OSError:
                pass
        subprocess.run(["icacls", str(base), "/setowner", "*S-1-5-32-544", "/t", "/c", "/q"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)
        confere("a pasta do teste saiu", not base.exists(), str(base))
    return True


if __name__ == "__main__":
    if "--disco" in sys.argv[1:]:
        if not no_disco():
            sys.exit(1)
    else:
        em_memoria()
    print("tudo certo" if not falhas else f"FALHAS: {', '.join(falhas)}")
    sys.exit(1 if falhas else 0)
