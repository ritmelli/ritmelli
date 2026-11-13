"""Pendura (e despendura) o filtro de microfone da Vitrola num microfone do Windows. Roda como administrador.

    python microfone.py estado                          os microfones ativos e em quais o filtro esta
    python microfone.py instala --microfone "IN 2" --dll apo/saida/micfx.dll
    python microfone.py remove [--microfone "IN 2"]     devolve o efeito original (todos, sem --microfone)

O instala copia a DLL pra uma pasta que o audiodg.exe (LocalService) consegue ler, registra o COM e o APO
(regsvr32), pendura o nosso nas vagas de efeito do microfone e guarda o original em
HKLM\\SOFTWARE\\Vitrola\\Microfone\\{id do microfone}. Depois reinicia o AudioEndpointBuilder e o servico de
audio, que e quando o Windows relê os efeitos (o som de todo o PC some por um instante).

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


def le(chave, nome):
    try:
        return winreg.QueryValueEx(chave, nome)
    except OSError:
        return None


def microfones():
    """[(id, nome, aparelho, chave)] dos microfones ativos (DeviceState 1)."""
    saida = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CAPTURA) as raiz:
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


def acha(filtro):
    """O microfone ativo que casa com o filtro. Logo depois de reiniciar o AudioEndpointBuilder a lista some por uns
    segundos (os aparelhos se enumeram de novo): espera ate 15 s antes de desistir."""
    for _ in range(30):
        achados = [m for m in microfones() if filtro.lower() in f"{m[1]} ({m[2]})".lower()]
        if achados:
            break
        time.sleep(0.5)
    if len(achados) != 1:
        nomes = "; ".join(f"{m[1]} ({m[2]})" for m in (achados or microfones()))
        sys.exit(f"'{filtro}' precisa achar 1 microfone ativo, achou {len(achados)}: {nomes}")
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
                   capture_output=True, text=True, encoding="oem", errors="replace")
    estado = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Service audiosrv).Status"],
                            capture_output=True, text=True, encoding="oem", errors="replace").stdout.strip()
    esperado = "Stopped" if acao == "Stop" else "Running"
    if estado != esperado:
        sys.exit(f"o servico de audio ficou '{estado}' depois do {acao} (esperado {esperado})")


def reinicia_audio():
    """Depois de mexer nas chaves de efeito: o AudioEndpointBuilder guarda as propriedades dos aparelhos e so as
    rele quando reinicia (o audiosrv cai junto e volta pelo servico_audio)."""
    subprocess.run(["powershell", "-NoProfile", "-Command", "Restart-Service AudioEndpointBuilder -Force"],
                   check=False, capture_output=True, text=True, encoding="oem", errors="replace")
    servico_audio("Start")


LOGS = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Vitrola")


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
    os.makedirs(PASTA, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)  # o log do filtro: LocalService (S-1-5-19) e Usuarios (S-1-5-32-545) escrevem
    subprocess.run(["icacls", LOGS, "/grant", "*S-1-5-19:(OI)(CI)M", "*S-1-5-32-545:(OI)(CI)M"],
                   capture_output=True)
    destino = os.path.join(PASTA, "micfx.dll")
    servico_audio("Stop")  # o audiodg.exe solta a DLL velha
    shutil.copy2(dll, destino)
    r = subprocess.run(["regsvr32", "/s", destino], capture_output=True, text=True, encoding="oem",
                       errors="replace")
    if r.returncode:
        sys.exit(f"regsvr32 falhou ({r.returncode})")
    base = rf"{CAPTURA}\{ep}"
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
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\Properties", 0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as p:
        if (le(p, SEM_MELHORIAS) or (0,))[0]:
            winreg.SetValueEx(p, SEM_MELHORIAS, 0, winreg.REG_DWORD, 0)
            print("as melhorias de audio desse microfone estavam desativadas: ligadas (senao o filtro nao carrega)")
    reinicia_audio()
    print(f"pendurado em {nome} ({apar}) {ep}")


def remove(filtro=None):
    alvos = [acha(filtro)] if filtro else microfones()
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
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, rf"{SALVO}\{ep}")
        print(f"devolvido o original em {nome} ({apar}) {ep}")
    sobrou = [m for m in microfones()
              if nosso(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{m[0]}\FxProperties"))]
    if not sobrou:
        destino = os.path.join(PASTA, "micfx.dll")
        if os.path.exists(destino):
            subprocess.run(["regsvr32", "/s", "/u", destino], capture_output=True)
    reinicia_audio()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=("estado", "instala", "remove"))
    ap.add_argument("--microfone")
    ap.add_argument("--dll")
    a = ap.parse_args()
    if a.acao == "estado":
        estado()
    elif a.acao == "instala":
        if not a.microfone or not a.dll:
            sys.exit("instala precisa de --microfone e --dll")
        instala(a.microfone, a.dll)
    else:
        remove(a.microfone)
