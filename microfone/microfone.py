"""Pendura (e despendura) o filtro de microfone da Vitrola num microfone do Windows. Roda como administrador.

    python microfone.py estado                          os microfones ativos e em quais o filtro esta
    python microfone.py instala --microfone "IN 2" --dll apo/saida/micfx.dll
    python microfone.py remove [--microfone "IN 2"]     devolve o efeito original (todos, sem --microfone)
    python microfone.py atualiza                        troca a DLL ja pendurada pela do app, se mudou (instalador)

No app: vitrola.exe --microfone <a mesma linha> (o servidor pede pelo UAC: pede_admin); --dll e, sem ele, a DLL que
vem com o app (dll_padrao); --saida grava o resultado em JSON, que o processo elevado nao tem console.

O instala copia a DLL pra uma pasta que o audiodg.exe (LocalService) consegue ler, registra o COM e o APO
(regsvr32), pendura o nosso nas vagas de efeito do microfone e guarda o original em
HKLM\\SOFTWARE\\Vitrola\\Microfone\\{id do microfone}. Depois reinicia o AudioEndpointBuilder e o servico de
audio, que e quando o Windows relê os efeitos (o som de todo o PC some por um instante). O log do filtro fica em
log\\micfx.log, na pasta da DLL.

O filtro vai em DUAS vagas e o Windows usa uma so (lido no audiosrv.dll do 26200, 13/11):
- EFX composto ({d04e05a6...},15, lista): o efeito de endpoint, uma instancia por microfone, que roda pra TODO stream,
  inclusive o raw (o Discord com "Contornar processamento do sistema" ou no perfil Estudio abre raw, e raw pula o
  SFX). O EFX que o fabricante ja tinha fica na lista, antes do nosso. Modos DEFAULT e RAW em {d3993a3f...},7.
- LFX ({d04e05a6...},1): driver velho, que nao declara modos de processamento (o VB-Cable 1.0.3.5 de 2014, os da
  Steam de 2017), fica com o conector "sem modos" e o audiosrv so monta o caminho legado LFX/GFX
  (CEndpointCharacteristics::DiscoverConnectorCapabilities, EffectPack::DeriveEffectiveConnectorAndEffectPackCapabilities).
O SFX do fabricante nao se mexe (a versao anterior trocava o SFX pelo nosso; instalar de novo devolve o original).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import winreg

CLSID = "{C17A1D48-D473-40D9-9ED3-D024AA46EBE2}"
CAPTURA = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
SALVO = r"SOFTWARE\Vitrola\Microfone"
PASTA = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Vitrola", "microfone")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no executavel sem console, nada de janela piscando

NOME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
APARELHO = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
SEM_MELHORIAS = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"  # 1 = "desativar melhorias": nenhum efeito carrega
SFX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5"
LFX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},1"  # a vaga legada: driver sem modos de processamento so le esta
# PKEY_FX_Association: o no do driver em que os efeitos entram. Microfone que nunca teve efeito (cabo virtual,
# o Conector AUX da Steam) nao tem: sem ela o Windows nem olha o SFX (13/11). KSNODETYPE_ANY = qualquer no.
ASSOCIACAO = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},0"
KSNODETYPE_ANY = "{00000000-0000-0000-0000-000000000000}"
MODOS_SFX = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},5"
EFX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},7"  # EFX simples do fabricante: vira o primeiro da lista composta
EFX_LISTA = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},15"  # EFX composto (Windows 10 1803+): CLSIDs em ordem
MODOS_EFX = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},7"
MODO_PADRAO = "{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}"  # AUDIO_SIGNALPROCESSINGMODE_DEFAULT
MODO_RAW = "{9E90EA20-B493-4FD1-A1A8-7E1361A956CF}"  # AUDIO_SIGNALPROCESSINGMODE_RAW
GUARDADOS = (ASSOCIACAO, LFX, "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},2", SFX,
             "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6", EFX, EFX_LISTA, MODOS_SFX,
             "{d3993a3f-99c2-4402-b5ec-a92a0367664b},6", MODOS_EFX)
# Os que a gente pode criar: o remove apaga os que estao em _ausentes (o que nao existia antes)
CRIADOS = (ASSOCIACAO, LFX, SFX, MODOS_SFX, EFX_LISTA, MODOS_EFX)
VERSAO_SALVO = 2  # 2 = guarda tambem o EFX; salvo sem _versao veio da versao que trocava o SFX


def nosso(fx):
    """O filtro esta pendurado nesse microfone (em qualquer vaga)?"""
    for k in (LFX, SFX, EFX):
        if (le(fx, k) or ("",))[0].upper() == CLSID:
            return True
    return CLSID in [c.upper() for c in (le(fx, EFX_LISTA) or ([],))[0]]


def tem_filtro(ep):
    """O microfone com essa chave do registro tem o filtro (False sem as propriedades de efeito)?"""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\FxProperties") as fx:
            return nosso(fx)
    except OSError:
        return False


def le(chave, nome):
    try:
        return winreg.QueryValueEx(chave, nome)
    except OSError:
        return None


def microfones():
    """[(id, nome, aparelho, chave)] dos microfones ativos (DeviceState 1)."""
    saida = []
    try:
        raiz = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CAPTURA)
    except OSError:  # Windows sem aparelho de audio nenhum (a maquina da esteira)
        return saida
    with raiz:
        i = 0
        while True:
            try:
                ep = winreg.EnumKey(raiz, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(raiz, ep) as k:
                    if (le(k, "DeviceState") or (0,))[0] != 1:
                        continue
                with winreg.OpenKey(raiz, ep + r"\Properties") as p:
                    nome, apar = (le(p, NOME) or ("?",))[0], (le(p, APARELHO) or ("?",))[0]
                saida.append((ep, nome, apar))
            except OSError:
                continue
    return saida


def nomes_windows():
    """{chave do microfone no registro: o nome que o Windows da a ele agora}, pelo Core Audio (winvol.py, do app). E o
    nome do sounddevice e da tela: o montado do registro ("IN 2 (BEHRINGER ...)") perde o "2- " que o Windows poe
    quando ha dois aparelhos com o mesmo nome ("IN 2 (2- BEHRINGER ...)", 13/11). Vazio sem o winvol (o microfone.py
    rodando sozinho, fora do app): fica o do registro."""
    try:
        import ctypes  # noqa: PLC0415
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # MTA, como no motor; S_FALSE/RPC_E_CHANGED_MODE servem
        import winvol  # noqa: PLC0415 - o modulo do app, ao lado do microfone/
        return {d.GetId().rsplit(".", 1)[-1].lower(): n for n, d in winvol.microfones()}
    except Exception:  # noqa: BLE001 - sem o Core Audio, o nome do registro
        return {}


def nome_de(m, nomes):
    """O nome do microfone (ep, nome, aparelho) de microfones(): o do Windows, ou o montado do registro."""
    return nomes.get(m[0].lower()) or f"{m[1]} ({m[2]})"


def acha(filtro):
    """O microfone ativo com esse nome (o do Windows, igual, sem caixa) ou, sem nenhum igual, o unico que contem o
    texto (na linha de comando: "IN 2"). Logo depois de reiniciar o AudioEndpointBuilder a lista some por uns
    segundos (os aparelhos se enumeram de novo): espera ate 15 s antes de desistir."""
    f = filtro.lower()
    for _ in range(30):
        nomes = nomes_windows()
        todos = [(m, nome_de(m, nomes)) for m in microfones()]
        achados = [m for m, n in todos if n.lower() == f] or [
            m for m, n in todos if f in n.lower() or f in f"{m[1]} ({m[2]})".lower()]
        if achados:
            break
        time.sleep(0.5)
    if len(achados) != 1:
        lista = "; ".join(n for m, n in todos if not achados or m in achados)
        sys.exit(f"'{filtro}' precisa achar 1 microfone ativo, achou {len(achados)}: {lista}")
    return achados[0]


def estado():
    for ep, nome, apar in microfones():
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\FxProperties") as fx:
            sfx = (le(fx, SFX) or ("",))[0]
            e_nosso = nosso(fx)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\Properties") as p:
            sem = (le(p, SEM_MELHORIAS) or (0,))[0]
        marca = "VITROLA" if e_nosso else ("outro: " + sfx if sfx else "sem SFX")
        print(f"{nome} ({apar}) {ep}: {marca}{'  [melhorias desativadas]' if sem else ''}")
    print("dll:", os.path.join(PASTA, "micfx.dll"), "existe" if os.path.exists(os.path.join(PASTA, "micfx.dll"))
          else "nao existe")


def servico_audio(acao):
    """Stop, Start ou Restart do servico de audio (o audiodg.exe segura a DLL enquanto ele roda). O Start-Service
    nao tem -Force (com ele o comando falha calado e o PC fica sem som: 13/11). Confere o estado no fim."""
    forca = " -Force" if acao in ("Stop", "Restart") else ""
    subprocess.run(["powershell", "-NoProfile", "-Command", f"{acao}-Service audiosrv{forca}"], check=False,
                   capture_output=True, text=True, encoding="oem", errors="replace", creationflags=NO_WINDOW)
    estado = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Service audiosrv).Status"],
                            capture_output=True, text=True, encoding="oem", errors="replace",
                            creationflags=NO_WINDOW).stdout.strip()
    esperado = "Stopped" if acao == "Stop" else "Running"
    if estado != esperado:
        sys.exit(f"o servico de audio ficou '{estado}' depois do {acao} (esperado {esperado})")


def reinicia_audio():
    """Depois de mexer nas chaves de efeito: o AudioEndpointBuilder guarda as propriedades dos aparelhos e so as
    rele quando reinicia (o audiosrv cai junto e volta pelo servico_audio)."""
    subprocess.run(["powershell", "-NoProfile", "-Command", "Restart-Service AudioEndpointBuilder -Force"],
                   check=False, capture_output=True, text=True, encoding="oem", errors="replace",
                   creationflags=NO_WINDOW)
    servico_audio("Start")


# O log do filtro (micfx.dll grava em log\ ao lado dela): dentro da pasta de programas, onde so administrador cria
# pasta, e com escrita so pro LocalService (S-1-5-19), que roda o audiodg.exe; o usuario le pela heranca. Pasta de
# log gravavel pelo usuario deixaria ele trocar o arquivo por um link e o audiodg escrever onde ele quisesse.
LOGS = os.path.join(PASTA, "log")


def atualiza_salvo_velho(fx, salvo):
    """Microfone pendurado por versao anterior: completa o salvo com o que aquela versao nao guardava. O que ela
    nunca escrevia (ASSOCIACAO antes de existir, LFX antes de existir, a familia EFX) ainda esta no valor original."""
    if (le(salvo, "_versao") or (0,))[0] >= VERSAO_SALVO:
        return
    ausentes = list((le(salvo, "_ausentes") or ([],))[0])
    if le(salvo, "_ausentes") is None:  # versao sem _ausentes
        if le(fx, ASSOCIACAO) is None:
            ausentes.append(ASSOCIACAO)
        if not (le(salvo, "_tinha_sfx") or (0,))[0]:
            ausentes += [k for k in (SFX, MODOS_SFX) if le(salvo, k) is None]
    nunca_escritos = [EFX, EFX_LISTA, MODOS_EFX]
    if (le(fx, LFX) or ("",))[0].upper() != CLSID:
        nunca_escritos.append(LFX)
    for k in nunca_escritos:
        v = le(fx, k)
        if le(salvo, k) is not None or k in ausentes:
            continue
        if v is not None:
            winreg.SetValueEx(salvo, k, 0, v[1], v[0])
        elif k in CRIADOS:
            ausentes.append(k)
    winreg.SetValueEx(salvo, "_ausentes", 0, winreg.REG_MULTI_SZ, ausentes)


def instala(filtro, dll):
    ep, nome, apar = acha(filtro)
    os.makedirs(LOGS, exist_ok=True)
    r = subprocess.run(["icacls", LOGS, "/grant", "*S-1-5-19:(OI)(CI)M"], capture_output=True, text=True,
                       encoding="oem", errors="replace", creationflags=NO_WINDOW)
    if r.returncode:
        sys.exit(f"icacls na pasta do log falhou ({r.returncode}): {r.stdout.strip()} {r.stderr.strip()}")
    base = rf"{CAPTURA}\{ep}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\Properties") as p:
        sem_melhorias = (le(p, SEM_MELHORIAS) or (0,))[0]
    destino = os.path.join(PASTA, "micfx.dll")
    servico_audio("Stop")  # o audiodg.exe solta a DLL velha
    if os.path.normcase(os.path.abspath(dll)) != os.path.normcase(destino):  # instalar de novo a ja instalada
        shutil.copy2(dll, destino)
    r = subprocess.run(["regsvr32", "/s", destino], capture_output=True, text=True, encoding="oem",
                       errors="replace", creationflags=NO_WINDOW)
    if r.returncode:
        sys.exit(f"regsvr32 falhou ({r.returncode})")
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\FxProperties", 0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as fx, \
            winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, rf"{SALVO}\{ep}", 0, winreg.KEY_ALL_ACCESS) as salvo:
        if not nosso(fx):  # guarda so o original (instalar de novo nao apaga ele)
            for k in GUARDADOS:
                v = le(fx, k)
                if v is not None:
                    winreg.SetValueEx(salvo, k, 0, v[1], v[0])
                else:
                    try:
                        winreg.DeleteValue(salvo, k)
                    except OSError:
                        pass
            winreg.SetValueEx(salvo, "_tinha_sfx", 0, winreg.REG_DWORD, 1 if le(fx, SFX) else 0)
            # "desativar melhorias" fica fora do FxProperties: guardado a parte pro remove desligar de novo
            winreg.SetValueEx(salvo, "_sem_melhorias", 0, winreg.REG_DWORD, 1 if sem_melhorias else 0)
            winreg.SetValueEx(salvo, "_ausentes", 0, winreg.REG_MULTI_SZ, [k for k in CRIADOS if le(fx, k) is None])
        else:
            atualiza_salvo_velho(fx, salvo)
        winreg.SetValueEx(salvo, "_versao", 0, winreg.REG_DWORD, VERSAO_SALVO)
        # a versao anterior trocava o SFX: o do fabricante volta (ou some, se nao havia)
        if (le(fx, SFX) or ("",))[0].upper() == CLSID:
            v = le(salvo, SFX)
            if v is not None:
                winreg.SetValueEx(fx, SFX, 0, v[1], v[0])
            else:
                winreg.DeleteValue(fx, SFX)
        winreg.SetValueEx(fx, LFX, 0, winreg.REG_SZ, CLSID)
        lista = [c for c in (le(fx, EFX_LISTA) or ([],))[0] if c.upper() != CLSID]
        simples = (le(fx, EFX) or ("",))[0]
        if simples and simples.upper() != CLSID:  # o EFX simples do fabricante entra na lista, na frente
            if simples.upper() not in [c.upper() for c in lista]:
                lista.insert(0, simples)
        if simples:
            winreg.DeleteValue(fx, EFX)
        winreg.SetValueEx(fx, EFX_LISTA, 0, winreg.REG_MULTI_SZ, lista + [CLSID])
        modos = list((le(fx, MODOS_EFX) or ([],))[0])
        for m in (MODO_PADRAO, MODO_RAW):
            if m.upper() not in [x.upper() for x in modos]:
                modos.append(m)
        winreg.SetValueEx(fx, MODOS_EFX, 0, winreg.REG_MULTI_SZ, modos)
        if le(fx, ASSOCIACAO) is None:
            winreg.SetValueEx(fx, ASSOCIACAO, 0, winreg.REG_SZ, KSNODETYPE_ANY)
    if sem_melhorias:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\Properties", 0, winreg.KEY_SET_VALUE) as p:
            winreg.SetValueEx(p, SEM_MELHORIAS, 0, winreg.REG_DWORD, 0)
        print("as melhorias de audio desse microfone estavam desativadas: ligadas (senao o filtro nao carrega; o "
              "remove desativa de novo)")
    reinicia_audio()
    print(f"pendurado em {nome} ({apar}) {ep}")


def remove(filtro=None):
    """Devolve o original dos microfones (o do filtro, ou todos) e, sem nenhum com o filtro, tira a DLL. O audio do PC
    so reinicia se algum microfone mudou (o desinstalador chama sempre)."""
    alvos = [acha(filtro)] if filtro else microfones()
    mexeu = False
    for ep, nome, apar in alvos:
        try:
            salvo = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{SALVO}\{ep}")
        except OSError:
            continue
        with salvo, winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\FxProperties", 0,
                                   winreg.KEY_READ | winreg.KEY_SET_VALUE) as fx:
            ausentes = (le(salvo, "_ausentes") or ([SFX],))[0]  # sem _ausentes (versao velha): so o SFX
            for k in GUARDADOS:
                v = le(salvo, k)
                if v is not None:
                    winreg.SetValueEx(fx, k, 0, v[1], v[0])
                elif k in ausentes:
                    try:
                        winreg.DeleteValue(fx, k)
                    except OSError:
                        pass
            sem_melhorias = (le(salvo, "_sem_melhorias") or (0,))[0]  # instalado antes de guardar: nao mexe
        if sem_melhorias:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\Properties", 0,
                                winreg.KEY_SET_VALUE) as p:
                winreg.SetValueEx(p, SEM_MELHORIAS, 0, winreg.REG_DWORD, 1)
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, rf"{SALVO}\{ep}")
        mexeu = True
        print(f"devolvido o original em {nome} ({apar}) {ep}")
    sobrou = [m for m in microfones() if tem_filtro(m[0])]
    destino = os.path.join(PASTA, "micfx.dll")
    if not sobrou and os.path.exists(destino):
        subprocess.run(["regsvr32", "/s", "/u", destino], capture_output=True, creationflags=NO_WINDOW)
    if mexeu:
        reinicia_audio()
    if not sobrou:  # o audiodg ja soltou a DLL: sai a pasta (a DLL e o log)
        shutil.rmtree(PASTA, ignore_errors=True)


def dll_padrao():
    """A micfx.dll que vem com o app: no executavel, a da _internal\\microfone (vitrola.spec); no fonte, a que o
    apo\\compila.bat gera."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "microfone", "micfx.dll")  # noqa: SLF001 - o PyInstaller poe aqui
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "apo", "saida", "micfx.dll")


def _sha(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def estado_dados():
    """O estado para a tela, sem administrador: {"microfones": [{"nome": "IN 2 (BEHRINGER ...)", "filtro": bool}],
    "dll_app": a DLL que vem com o app existe, "desatualizado": a pendurada difere dela (None sem uma das duas)}. O nome
    e o mesmo que o sounddevice da ao microfone no WASAPI."""
    mics, nomes = [], nomes_windows()
    for m in microfones():
        mics.append({"nome": nome_de(m, nomes), "filtro": tem_filtro(m[0])})
    fonte, instalada = dll_padrao(), os.path.join(PASTA, "micfx.dll")
    desat = None
    if os.path.exists(fonte) and os.path.exists(instalada):
        try:
            desat = _sha(fonte) != _sha(instalada)
        except OSError:
            pass
    return {"microfones": mics, "dll_app": os.path.exists(fonte), "desatualizado": desat}


def atualiza(dll):
    """A versao nova do app trouxe outra micfx.dll: troca a pendurada (para o audio, copia, volta). Sem microfone com o
    filtro, ou com a mesma DLL, nao faz nada (o instalador chama sempre)."""
    destino = os.path.join(PASTA, "micfx.dll")
    com_filtro = [m for m in estado_dados()["microfones"] if m["filtro"]]
    if not com_filtro or not os.path.exists(dll) or (os.path.exists(destino) and _sha(dll) == _sha(destino)):
        print("nada a atualizar")
        return
    servico_audio("Stop")
    try:
        shutil.copy2(dll, destino)
    finally:
        servico_audio("Start")
    print(f"DLL trocada ({len(com_filtro)} microfone(s) com o filtro)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="microfone")
    ap.add_argument("acao", choices=("estado", "instala", "remove", "atualiza"))
    ap.add_argument("--microfone")
    ap.add_argument("--dll", help="a micfx.dll a pendurar (sem ele, a que vem com o app)")
    ap.add_argument("--saida", help="grava o resultado em JSON ({ok, erro}): o processo elevado nao tem console")
    a = ap.parse_args(argv)
    dll = a.dll or dll_padrao()
    res = {"ok": True}
    try:
        if a.acao == "estado":
            estado()
        elif a.acao == "instala":
            if not a.microfone:
                sys.exit("instala precisa de --microfone")
            if not os.path.exists(dll):
                sys.exit(f"a DLL do filtro nao esta em {dll}")
            instala(a.microfone, dll)
        elif a.acao == "remove":
            remove(a.microfone)
        else:
            atualiza(dll)
    except SystemExit as ex:
        if ex.code not in (None, 0):
            res = {"ok": False, "erro": str(ex.code)}
    except Exception as ex:  # noqa: BLE001 - o app mostra o motivo em vez de ficar sem resposta
        res = {"ok": False, "erro": f"{type(ex).__name__}: {ex}"}
    if a.saida:
        with open(a.saida, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
    if not res["ok"]:
        print(res["erro"], file=sys.stderr)
        return 1
    return 0


def pede_admin(acao, microfone=None, espera_s=120):
    """Roda instala/remove como administrador, com o pedido do UAC do Windows na tela, e devolve {ok, erro}. No
    executavel e o proprio vitrola.exe --microfone; no fonte, o python com o vitrola.py. Recusado o UAC, ok e False
    com o motivo. Bloqueia ate o fim (o instala reinicia o audio do PC: uns 5 a 15 s)."""
    import ctypes  # noqa: PLC0415 - so o servidor chama
    import tempfile  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class Sei(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    fd, saida = tempfile.mkstemp(prefix="vitrola-microfone-", suffix=".json")
    os.close(fd)
    os.remove(saida)  # o elevado cria: arquivo que sobra sem ele escrever nao vira resultado velho
    args = ["--microfone", acao, "--saida", saida] + (["--microfone", microfone] if microfone else [])
    if not getattr(sys, "frozen", False):
        args = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vitrola.py")] + args
    # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI, e SW_HIDE: nenhuma janela alem da do UAC
    sei = Sei(cbSize=ctypes.sizeof(Sei), fMask=0x40 | 0x400, lpVerb="runas", lpFile=sys.executable,
              lpParameters=subprocess.list2cmdline(args), nShow=0)
    sh = ctypes.WinDLL("shell32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sh.ShellExecuteExW.argtypes = (ctypes.POINTER(Sei),)
    k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    if not sh.ShellExecuteExW(ctypes.byref(sei)):
        erro = ctypes.get_last_error()
        if erro == 1223:  # ERROR_CANCELLED: o UAC foi recusado
            return {"ok": False, "erro": "O Windows não recebeu a permissão de administrador (o pedido foi recusado)."}
        return {"ok": False, "erro": f"Não consegui pedir a permissão de administrador (erro {erro})."}
    try:
        if k32.WaitForSingleObject(sei.hProcess, int(espera_s * 1000)) != 0:
            return {"ok": False, "erro": "O ajuste do microfone demorou demais e ficou sem resposta."}
    finally:
        k32.CloseHandle(sei.hProcess)
    try:
        with open(saida, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"ok": False, "erro": "O ajuste do microfone terminou sem dizer o resultado."}
    finally:
        try:
            os.remove(saida)
        except OSError:
            pass


if __name__ == "__main__":
    sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # o winvol.py do app
    sys.exit(main())
