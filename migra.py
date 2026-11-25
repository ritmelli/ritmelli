r"""A troca de nome de Vitrola para Ritmelli (#58) no PC de quem ja tinha o app (ate a 0.4.1): o instalador chama, como
administrador. Os dados de quem usa (%LOCALAPPDATA%) mudam de pasta no proprio app, ao ligar (pastas.migra).

    ritmelli.exe --migra maquina
        antes do filtro de microfone: copia o HKLM\SOFTWARE\Vitrola para o HKLM\SOFTWARE\Ritmelli (a escolha dos
        dados de uso, o original de cada microfone e as vagas do hospedeiro, sem trocar o que ja esta no novo) e apaga
        as tarefas do Windows de antes. O app de antes aberto, o setup ja fechou, pelo caminho do executavel (o
        PrepareToInstall do ritmelli.iss)
    ritmelli.exe --migra limpa
        no fim, com o filtro novo no lugar (o audio reinicia e o audiodg.exe solta a DLL de antes): apaga o
        HKLM\SOFTWARE\Vitrola e a pasta padrao de antes (Program Files\Vitrola); o que estiver preso sai no proximo
        reinicio

A copia do registro vem antes de tudo porque o microfone.py guarda o efeito original de cada microfone so quando nao
acha o de antes: sem ela, ele guardaria o nosso filtro como original, e desinstalar nao devolveria o do fabricante. O
app que estava na pasta padrao (Program Files\Vitrola) passa para a Program Files\Ritmelli; o que estava numa pasta
escolhida a mao fica nela (o ritmelli.iss decide), e dela o setup so apaga o vitrola.exe. A limpeza da pasta de
antes so mexe numa pasta protegida (pastas.pasta_protegida): ela roda como administrador, e tambem em toda rodada da
tarefa de atualizacao, como SYSTEM."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pastas

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REG_VELHO = r"SOFTWARE\Vitrola"
REG_NOVO = r"SOFTWARE\Ritmelli"
TAREFAS_VELHAS = ("Vitrola Atualiza", r"\Vitrola\Microfone")
PASTA_TAREFAS_VELHA = "Vitrola"
PASTA_VELHA = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Vitrola"
# so se apaga numa pasta protegida (os testes trocam por uma que aceita a pasta temporaria)
PROTEGIDA = pastas.pasta_protegida
# o que o instalador de antes punha na pasta do app, e o que o app criava nela
DO_APP_VELHO = ("vitrola.exe", "_internal", "bin", "microfone", "atualizacao", "LICENSE.txt", "TERCEIROS.txt")


def log(texto):
    print(f"migra: {texto}", flush=True)


# ---------- o registro ----------

def _copia_chave(winreg, de, para):
    """Copia a chave de (aberta) para a chave para (aberta), com as subchaves, sem trocar valor que ja existe no
    destino. Quantos valores copiou."""
    n, i = 0, 0
    while True:
        try:
            nome, valor, tipo = winreg.EnumValue(de, i)
        except OSError:
            break
        i += 1
        try:
            winreg.QueryValueEx(para, nome)
        except OSError:
            winreg.SetValueEx(para, nome, 0, tipo, valor)
            n += 1
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(de, i)
        except OSError:
            break
        i += 1
        with winreg.OpenKey(de, sub, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as d, \
                winreg.CreateKeyEx(para, sub, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as p:
            n += _copia_chave(winreg, d, p)
    return n


def registro(raiz=None, de=REG_VELHO, para=REG_NOVO):
    r"""O HKLM\SOFTWARE\Vitrola copiado para o HKLM\SOFTWARE\Ritmelli, sem trocar o que o novo ja tem. Sem a chave de
    antes, nada a fazer. O microfone.py tambem chama, antes de mexer em qualquer microfone. Quantos valores copiou (os
    testes passam outra raiz e outras chaves)."""
    if sys.platform != "win32":
        return 0
    import winreg
    raiz = winreg.HKEY_LOCAL_MACHINE if raiz is None else raiz
    try:
        velho = winreg.OpenKey(raiz, de, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return 0
    with velho, winreg.CreateKeyEx(raiz, para, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as novo:
        n = _copia_chave(winreg, velho, novo)
    if n:
        log(f"{n} registry values copied from {de} to {para}")
    return n


def _apaga_chave(winreg, raiz, caminho):
    """Apaga a chave com as subchaves (o DeleteKey so apaga chave vazia)."""
    with winreg.OpenKey(raiz, caminho, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as k:
        while True:
            try:
                sub = winreg.EnumKey(k, 0)
            except OSError:
                break
            _apaga_chave(winreg, raiz, caminho + "\\" + sub)
    winreg.DeleteKeyEx(raiz, caminho, winreg.KEY_WOW64_64KEY, 0)


def apaga_registro_velho(raiz=None, chave=REG_VELHO):
    if sys.platform != "win32":
        return
    import winreg
    raiz = winreg.HKEY_LOCAL_MACHINE if raiz is None else raiz
    try:
        _apaga_chave(winreg, raiz, chave)
        log(f"{chave} removed")
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"couldn't remove {chave}: {e}")


# ---------- as tarefas e o app de antes ----------

def tarefas():
    """Apaga as tarefas do Windows de antes (as novas o instalador cria) e a pasta delas no Agendador de Tarefas."""
    for t in TAREFAS_VELHAS:
        for args in (["/end"], ["/delete", "/f"]):
            subprocess.run(["schtasks", *args, "/tn", t], capture_output=True, creationflags=NO_WINDOW)
    ps = ("$s=New-Object -ComObject Schedule.Service;$s.Connect();"
          f"try{{$s.GetFolder('\\').DeleteFolder('{PASTA_TAREFAS_VELHA}',0)}}catch{{}}")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                   creationflags=NO_WINDOW)


# ---------- a pasta do app de antes ----------

def _apaga_no_reinicio(caminho):
    """O que o Windows nao deixou apagar agora (a DLL presa num processo) sai no proximo reinicio."""
    import ctypes
    ctypes.windll.kernel32.MoveFileExW(str(caminho), None, 4)  # MOVEFILE_DELAY_UNTIL_REBOOT


def pasta_velha(pasta=PASTA_VELHA):
    """Apaga da pasta padrao do app de antes o que era dele, e a pasta, se ficar vazia (outra coisa que alguem tenha
    posto nela fica). Nunca a pasta do app que esta rodando, e nada numa pasta fora da regra da pasta protegida (uma
    juncao no caminho ou dentro dela levaria o rmtree, como administrador ou SYSTEM, para onde ela aponta): ali so o
    motivo vai para o log. Quantos itens ficaram para o reinicio."""
    pasta = Path(pasta)
    protegida = PROTEGIDA(pasta)  # antes de seguir o caminho (o is_dir e o resolve seguem uma juncao)
    if not protegida:
        log(f"{pasta} was left as it is, the folder isn't protected: {protegida}")
        return 0
    if not pasta.is_dir() or pasta.resolve() == pastas.APP.resolve():
        return 0
    presos = []

    def anota(_func, caminho, _exc):
        presos.append(Path(caminho))

    for nome in DO_APP_VELHO:
        p = pasta / nome
        if p.is_dir():
            shutil.rmtree(p, onexc=anota)
        elif p.exists():
            try:
                p.unlink()
            except OSError:
                presos.append(p)
    for p in pasta.glob("unins*.*"):  # o desinstalador de antes (o novo mora na pasta nova)
        try:
            p.unlink()
        except OSError:
            presos.append(p)
    for p in presos:
        _apaga_no_reinicio(p)
    try:
        pasta.rmdir()
    except OSError:
        if presos:
            _apaga_no_reinicio(pasta)
    if presos:
        log(f"{len(presos)} items of {pasta} will be removed on the next restart")
    else:
        log(f"{pasta}: the old app was removed" + (" (other files kept)" if pasta.exists() else ""))
    return len(presos)


def main(args):
    modo = args[0] if args else ""
    if modo == "maquina":
        registro()
        tarefas()
        return 0
    if modo == "limpa":
        apaga_registro_velho()
        pasta_velha()
        return 0
    print("usage: --migra maquina|limpa")
    return 2
