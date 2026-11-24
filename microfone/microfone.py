"""O filtro de microfone do Ritmelli nos microfones do Windows: pendura, tira e diz o estado.

    python microfone.py estado                          os microfones e em quais o filtro esta
    python microfone.py instala-todos [--tarefa]        (admin) pendura em todo microfone que nao tem, e com --tarefa
                                                        cria a tarefa do Windows que faz o mesmo sem pedir nada
    python microfone.py instala --microfone "IN 2"      (admin) so nesse microfone
    python microfone.py remove [--microfone "IN 2"]     (admin) devolve o efeito original (todos, sem --microfone) e
                                                        apaga a tarefa
    python microfone.py confere [--aparelho "IN 1-2 (BEHRINGER UMC 404HD 192k)" ...]
                                                        os aparelhos que abrem e nao entregam som, em JSON

No app: ritmelli.exe --microfone <a mesma linha>. O instalador roda o instala-todos --tarefa (ele ja e administrador)
e, ao desinstalar, o remove: o Ritmelli nunca pede o UAC. O filtro fica em todos os microfones e so age no que o app
escolheu (o alvo do anel, ver apo/anel.h). Microfone que aparece depois (um fone USB novo): o app roda a tarefa
(pede_tarefa), que roda como SYSTEM o instala-todos; quem usa o PC so pode rodar a tarefa, nao mudar. --dll e, sem
ele, a DLL que vem com o app (dll_padrao); --saida grava o resultado em JSON, com os aparelhos que ficaram mudos
depois do reinicio do audio (confere_aparelhos), que o instalador mostra na ultima pagina (instalador/mudos.iss).

O instala copia a DLL pra uma pasta que o audiodg.exe (LocalService) consegue ler, registra o COM e o APO
(regsvr32), pendura o nosso nas vagas de efeito do microfone e guarda o original em
HKLM\\SOFTWARE\\Ritmelli\\Microfone\\{id do microfone}. Depois reinicia o AudioEndpointBuilder e o servico de
audio, que e quando o Windows rele os efeitos (o som de todo o PC some por um instante; so quando algo mudou), e
confere se todo aparelho voltou a entregar som (confere_aparelhos). O log do filtro fica em log\\micfx.log, na
pasta da DLL.

O filtro vai em DUAS vagas e o Windows usa uma so (lido no audiosrv.dll do 26200, 13/11):
- EFX composto ({d04e05a6...},15, lista): o efeito de endpoint, uma instancia por microfone, que roda pra TODO stream,
  inclusive o raw (o Discord com "Contornar processamento do sistema" ou no perfil Estudio abre raw, e raw pula o
  SFX). O EFX que o fabricante ja tinha fica na lista, antes do nosso. Modos DEFAULT e RAW em {d3993a3f...},7.
- LFX ({d04e05a6...},1): driver velho, que nao declara modos de processamento (o VB-Cable 1.0.3.5 de 2014, os da
  Steam de 2017), fica com o conector "sem modos" e o audiosrv so monta o caminho legado LFX/GFX
  (CEndpointCharacteristics::DiscoverConnectorCapabilities, EffectPack::DeriveEffectiveConnectorAndEffectPackCapabilities).
Microfone com efeito de modo (MFX) do fabricante que cobre o modo RAW (o do notebook da Fortemedia: cancelamento de eco
e redutor de ruido, que apagava a musica como ruido) troca o ultimo MFX do fabricante pelo hospedeiro (HOSPEDES), na
lista composta {d04e05a6...},14. O Windows so aceita a peca de cancelamento de eco como a ultima da lista de MFX, entao
nada nosso pode vir depois dela: o hospedeiro carrega o APO do fabricante por dentro e soma a musica no que sai dele, e
o EFX desse microfone fica so com a voz (o micfx.dll ve o hospedeiro na lista). Por isso so com o RAW no MFX: o raw
pula o MFX onde o fabricante nao o declara, e ficaria sem musica. A vaga do hospedeiro que carrega cada fabricante vai
em HKLM\\SOFTWARE\\Ritmelli\\Microfone, valor _hospede<n>, e o registro de APO do fabricante e copiado para o dele.
O SFX do fabricante nao se mexe (a versao anterior trocava o SFX pelo nosso; instalar de novo devolve o original).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg

CLSID = "{C17A1D48-D473-40D9-9ED3-D024AA46EBE2}"  # EFX e LFX
# o hospedeiro do MFX do fabricante, uma vaga por fabricante (os CLSID_Hospede do micfx.cpp)
HOSPEDES = ("{D6EB08E6-2DDA-44F3-88C8-2D0EA00C6C8E}", "{9FEF5C33-9ED4-4CC6-8624-4F017BB71678}",
            "{ED59B560-1ECA-4491-9179-EC121791159D}", "{1663A464-C189-435F-89BD-9C9E9BAF1C23}")
NOSSOS = (CLSID,) + HOSPEDES
APOS = r"SOFTWARE\Classes\AudioEngine\AudioProcessingObjects"  # o registro de APO (o RegisterAPO grava aqui)
CAPTURA = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
SALVO = r"SOFTWARE\Ritmelli\Microfone"
PASTA = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Ritmelli", "microfone")
# a DLL de antes da troca de nome (#58), que o audiodg.exe pode estar segurando: com ela, a troca tambem para o audio
DLL_VELHA = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Vitrola", "microfone", "micfx.dll")
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
MFX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6"  # MFX simples do fabricante: vira o primeiro da lista composta
MFX_LISTA = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},14"  # MFX composto: CLSIDs em ordem
MODOS_MFX = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},6"
MODO_PADRAO = "{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}"  # AUDIO_SIGNALPROCESSINGMODE_DEFAULT
MODO_RAW = "{9E90EA20-B493-4FD1-A1A8-7E1361A956CF}"  # AUDIO_SIGNALPROCESSINGMODE_RAW
GUARDADOS = (ASSOCIACAO, LFX, "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},2", SFX, MFX, EFX, EFX_LISTA, MFX_LISTA,
             MODOS_SFX, MODOS_MFX, MODOS_EFX)
# Os que a gente pode criar: o remove apaga os que estao em _ausentes (o que nao existia antes)
CRIADOS = (ASSOCIACAO, LFX, SFX, MODOS_SFX, EFX_LISTA, MODOS_EFX, MFX_LISTA)
# 3 = guarda tambem a lista de MFX; 2 = o EFX; salvo sem _versao veio da versao que trocava o SFX
VERSAO_SALVO = 3


def _lista(fx, k):
    """Os CLSIDs de uma lista composta (REG_MULTI_SZ), em maiusculo; vazia sem o valor."""
    return [c.upper() for c in (le(fx, k) or ([],))[0]]


def nosso(fx):
    """O filtro esta pendurado nesse microfone (em qualquer vaga)?"""
    for k in (LFX, SFX, EFX):
        if (le(fx, k) or ("",))[0].upper() == CLSID:
            return True
    return any(c in NOSSOS for c in _lista(fx, EFX_LISTA) + _lista(fx, MFX_LISTA))


def no_mfx(fx):
    """O hospedeiro esta na lista de MFX (a musica entra depois do efeito do fabricante)?"""
    return any(c in HOSPEDES for c in _lista(fx, MFX_LISTA))


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


def microfones(todos=False):
    """[(id, nome, aparelho)] dos microfones ativos (DeviceState 1); com todos, tambem os desligados e desconectados
    (o filtro ja fica neles quando voltarem)."""
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
                    if not todos and (le(k, "DeviceState") or (0,))[0] != 1:
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
    saida = {}

    def le():  # numa thread so dela, em MTA: o comtypes quebra numa thread STA (a principal, depois do sounddevice)
        try:
            import ctypes  # noqa: PLC0415
            ctypes.windll.ole32.CoInitializeEx(None, 0)
            import winvol  # noqa: PLC0415 - o modulo do app, ao lado do microfone/
            saida.update({d.GetId().rsplit(".", 1)[-1].lower(): n for n, d in winvol.microfones()})
        except Exception:  # noqa: BLE001, S110 - sem o Core Audio, fica o nome do registro
            pass

    th = threading.Thread(target=le, daemon=True)
    th.start()
    th.join(10)
    return saida


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
        sys.exit(f"'{filtro}' must match 1 active microphone, matched {len(achados)}: {lista}")
    return achados[0]


def estado():
    for ep, nome, apar in microfones():
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\FxProperties") as fx:
            sfx = (le(fx, SFX) or ("",))[0]
            e_nosso, mfx = nosso(fx), no_mfx(fx)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{ep}\Properties") as p:
            sem = (le(p, SEM_MELHORIAS) or (0,))[0]
        marca = ("RITMELLI" + (" (+ maker's MFX)" if mfx else "")) if e_nosso else \
            ("other: " + sfx if sfx else "no SFX")
        print(f"{nome} ({apar}) {ep}: {marca}{'  [enhancements disabled]' if sem else ''}")
    print("dll:", os.path.join(PASTA, "micfx.dll"), "exists" if os.path.exists(os.path.join(PASTA, "micfx.dll"))
          else "missing")


def audio_rodando():
    """O servico de audio do Windows esta rodando (num servidor sem som, como a maquina da esteira, fica parado)."""
    estado = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Service audiosrv).Status"],
                            capture_output=True, text=True, encoding="oem", errors="replace",
                            creationflags=NO_WINDOW).stdout.strip()
    return estado == "Running"


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
        sys.exit(f"the audio service was '{estado}' after the {acao} (expected {esperado})")


def reinicia_audio(so_servico=False):
    """Depois de mexer nas chaves de efeito: o AudioEndpointBuilder guarda as propriedades dos aparelhos e so as
    rele quando reinicia (o audiosrv cai junto e volta pelo servico_audio). Com so_servico (#136: so a DLL do filtro
    mudou, e nenhum microfone ganhou o filtro), so o audiosrv: o audiodg.exe novo ja carrega a DLL nova, e o
    AudioEndpointBuilder, que desmonta e monta todos os aparelhos, fica como esta."""
    if so_servico:
        servico_audio("Restart" if audio_rodando() else "Start")  # a troca da DLL ja parou o audio para solta-la
        return
    subprocess.run(["powershell", "-NoProfile", "-Command", "Restart-Service AudioEndpointBuilder -Force"],
                   check=False, capture_output=True, text=True, encoding="oem", errors="replace",
                   creationflags=NO_WINDOW)
    servico_audio("Start")


# O aparelho mudo (#136): depois de mexer no audio, uma interface USB (a UMC 404HD da Behringer, com o driver
# TUSBAUDIO da Thesycon, o de muitas interfaces) abria sem erro e nao entregava quadro nenhum, em nenhuma entrada nem
# saida, nem no modo exclusivo, ate tirar o cabo. A causa ficou em aberto: depois de todo reinicio do audio, cada
# aparelho ativo e aberto e os quadros contados. O que nao entregou nada fica no registro (MUDOS, em SALVO), de onde o
# app confere de novo ao abrir e avisa quem usa (engine.py), e vai no --saida, que o instalador mostra na ultima pagina
MUDOS = "_mudos"
RAIZ_MUDOS = winreg.HKEY_LOCAL_MACHINE  # o instalador e a tarefa gravam (administrador e SYSTEM); qualquer usuario le
CONFERE_S = 2.0  # quanto cada aparelho tem para entregar o primeiro quadro
CONFERE_MAX_S = 30.0  # a conferencia inteira, no instalador: um driver que trava nao segura a instalacao


def aparelho_de(nome):
    """O aparelho de um nome do Windows, o que se tira do cabo: "IN 1-2 (BEHRINGER UMC 404HD 192k)" da "BEHRINGER UMC
    404HD 192k". Sem o parentese, o proprio nome."""
    i = nome.find(" (")
    return nome[i + 2:-1] if i > 0 and nome.endswith(")") else nome


def _mede(sd, alvos, espera_s):
    """Abre os alvos (indice, aparelho do PortAudio, "in" ou "out", canais) juntos e espera ate espera_s pelo primeiro
    quadro de cada. (os nomes que abriram e nao entregaram nada, os que nem abriram)."""
    quadros, abertos, falhas = {}, [], []
    for i, d, tipo, canais in alvos:
        chave = (i, tipo)
        quadros[chave] = 0

        def conta(dados, n, *_, chave=chave, saida=tipo == "out"):
            if saida:
                dados.fill(0)  # silencio: a saida conferida nao toca nada
            quadros[chave] += n
        try:
            s = (sd.InputStream if tipo == "in" else sd.OutputStream)(
                device=i, channels=canais, samplerate=d["default_samplerate"], dtype="float32",
                extra_settings=sd.WasapiSettings(auto_convert=True), callback=conta)
            s.start()
            abertos.append((chave, d["name"], s))
        except Exception:  # noqa: BLE001 - em uso exclusivo por outro programa, por exemplo: nao e mudo
            falhas.append(d["name"])
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim and any(quadros[k] == 0 for k, _, _ in abertos):
        time.sleep(0.02)
    for _, _, s in abertos:
        try:
            s.close()
        except Exception:  # noqa: BLE001, S110 - fechando
            pass
    return sorted({nome for k, nome, _ in abertos if quadros[k] == 0}), falhas


def confere_aparelhos(nomes=None, espera_s=CONFERE_S, sd=None):
    """Abre cada microfone e cada saida ativos do Windows (pelo WASAPI, como o app) e espera o primeiro quadro de cada
    por ate espera_s, todos ao mesmo tempo. O que ficou sem nada tem mais uma chance, com o dobro do tempo, um segundo
    depois (logo depois do reinicio do audio, um aparelho pode demorar a acordar). Com nomes, so esses.
    {"conferidos": [os nomes que abriram], "mudos": [os que abriram e nao entregaram nada], "falhas": [os que nem
    abriram: nao contam como mudos]}, ou None sem o sounddevice (o microfone.py rodando sozinho, fora do app). Usa a
    lista que o PortAudio leu ao subir: o app confere num processo a parte (engine._confere_fora), que le a de agora."""
    if sd is None:
        try:
            import sounddevice as sd  # noqa: PLC0415
        except Exception:  # noqa: BLE001 - sem as bibliotecas do app
            return None
    w = next((i for i, h in enumerate(sd.query_hostapis()) if "WASAPI" in h["name"]), None)
    alvos = []
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] != w or "[Loopback]" in d["name"] or (nomes is not None and d["name"] not in nomes):
            continue
        alvos += [(i, d, tipo, c) for tipo, c in (("in", d["max_input_channels"]), ("out", d["max_output_channels"]))
                  if c > 0]
    mudos, falhas = _mede(sd, alvos, espera_s)
    if mudos:  # mais tempo na segunda: um fone Bluetooth demora a montar o canal de voz quando o microfone abre
        time.sleep(1.0)
        mudos, _ = _mede(sd, [a for a in alvos if a[1]["name"] in mudos], espera_s * 2)
    conferidos = sorted({a[1]["name"] for a in alvos} - set(falhas))
    return {"conferidos": conferidos, "mudos": mudos, "falhas": sorted(set(falhas))}


def grava_mudos(nomes):
    """Os aparelhos mudos da ultima conferencia no registro. Lista vazia apaga o valor, sem criar a chave (o
    desinstalador passa por aqui e nao deixa nada para tras)."""
    try:
        if nomes:
            with winreg.CreateKeyEx(RAIZ_MUDOS, SALVO, 0, winreg.KEY_ALL_ACCESS) as k:
                winreg.SetValueEx(k, MUDOS, 0, winreg.REG_MULTI_SZ, list(nomes))
        else:
            with winreg.OpenKey(RAIZ_MUDOS, SALVO, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, MUDOS)
    except FileNotFoundError:  # sem a chave ou sem o valor: nada a apagar
        pass
    except OSError as ex:
        print(f"devices: couldn't record the silent ones ({ex})")


def le_mudos():
    """Os nomes que a ultima conferencia achou mudos, ou []."""
    try:
        with winreg.OpenKey(RAIZ_MUDOS, SALVO) as k:
            return list((le(k, MUDOS) or ([],))[0])
    except OSError:
        return []


def _depois_do_reinicio(espera_s=2.0, grava=True):
    """A conferencia depois de reiniciar o audio (o instalador, a tarefa e o desinstalador passam por aqui): o resultado
    vai para a saida (o log), para o --saida (a ultima pagina do instalador) e, com grava, para o registro (o app, ao
    abrir). Sem nenhum aparelho conferido (sem o sounddevice, ou nenhum abriu, como numa sessao sem audio), o registro
    fica como estava: o resultado de antes nao se perde por uma conferencia que nao aconteceu. A conferencia que
    quebra ou passa de CONFERE_MAX_S (um driver que trava ao abrir) conta como nao feita: a instalacao segue."""
    time.sleep(espera_s)  # os aparelhos se enumeram de novo logo depois do reinicio
    caixa = []

    def roda():
        try:
            caixa.append(confere_aparelhos())
        except Exception as ex:  # noqa: BLE001 - qualquer erro de um driver: sem conferencia
            caixa.append(ex)
    th = threading.Thread(target=roda, daemon=True)
    th.start()
    th.join(CONFERE_MAX_S)
    r = caixa[0] if caixa else TimeoutError(f"still running after {CONFERE_MAX_S:.0f} s")
    if r is None or isinstance(r, Exception):
        print(f"devices: not checked ({'no sounddevice' if r is None else r})")
        return None
    print(f"devices: {len(r['conferidos'])} checked"
          + (f"; silent: {'; '.join(r['mudos'])}" if r["mudos"] else "")
          + (f"; couldn't open: {'; '.join(r['falhas'])}" if r["falhas"] else ""))
    if r["conferidos"] and grava:
        grava_mudos(r["mudos"])
    return r


# O log do filtro (micfx.dll grava em log\ ao lado dela): dentro da pasta de programas, onde so administrador cria
# pasta, e com escrita so pro LocalService (S-1-5-19), que roda o audiodg.exe; o usuario le pela heranca. Pasta de
# log gravavel pelo usuario deixaria ele trocar o arquivo por um link e o audiodg escrever onde ele quisesse.
LOGS = os.path.join(PASTA, "log")


def atualiza_salvo_velho(fx, salvo):
    """Microfone pendurado por versao anterior: completa o salvo com o que aquela versao nao guardava. O que ela
    nunca escrevia (ASSOCIACAO antes de existir, LFX antes de existir, a familia EFX, a lista de MFX) ainda esta no
    valor original."""
    if (le(salvo, "_versao") or (0,))[0] >= VERSAO_SALVO:
        return
    ausentes = list((le(salvo, "_ausentes") or ([],))[0])
    if le(salvo, "_ausentes") is None:  # versao sem _ausentes
        if le(fx, ASSOCIACAO) is None:
            ausentes.append(ASSOCIACAO)
        if not (le(salvo, "_tinha_sfx") or (0,))[0]:
            ausentes += [k for k in (SFX, MODOS_SFX) if le(salvo, k) is None]
    nunca_escritos = [EFX, EFX_LISTA, MODOS_EFX, MFX_LISTA]
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


def _prepara_dll(dll):
    """A DLL no lugar e registrada; True se parou o audio para trocar (o reinicia_audio volta)."""
    os.makedirs(LOGS, exist_ok=True)
    r = subprocess.run(["icacls", LOGS, "/grant", "*S-1-5-19:(OI)(CI)M"], capture_output=True, text=True,
                       encoding="oem", errors="replace", creationflags=NO_WINDOW)
    if r.returncode:
        sys.exit(f"icacls on the log folder failed ({r.returncode}): {r.stdout.strip()} {r.stderr.strip()}")
    destino = os.path.join(PASTA, "micfx.dll")
    mesma = os.path.normcase(os.path.abspath(dll)) == os.path.normcase(destino)
    parou = False
    if not mesma and not (os.path.exists(destino) and _sha(dll) == _sha(destino)):
        if os.path.exists(destino):  # a primeira instalacao nao tem DLL presa: o som segue
            servico_audio("Stop")  # o audiodg.exe solta a DLL velha
            parou = True
        elif os.path.exists(DLL_VELHA) and audio_rodando():
            # a DLL de antes da troca de nome mora em outra pasta e nao segura a copia, mas o audiodg.exe so carrega a
            # nova quando o audio reinicia (o reinicia_audio de quem chamou)
            parou = True
        shutil.copy2(dll, destino)
    r = subprocess.run(["regsvr32", "/s", destino], capture_output=True, text=True, encoding="oem",
                       errors="replace", creationflags=NO_WINDOW)
    if r.returncode:
        sys.exit(f"regsvr32 failed ({r.returncode})")
    return parou


def _pendura(ep):
    """Pendura o filtro no microfone (a chave dele no registro), guardando o original; liga as melhorias de audio se
    estavam desativadas (sem elas nenhum efeito carrega; o remove desativa de novo). True se mudou algo."""
    base = rf"{CAPTURA}\{ep}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\Properties") as p:
        sem_melhorias = (le(p, SEM_MELHORIAS) or (0,))[0]
    mudou = False
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, base + r"\FxProperties", 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as fx, \
            winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, rf"{SALVO}\{ep}", 0, winreg.KEY_ALL_ACCESS) as salvo:
        if not nosso(fx):  # guarda so o original (pendurar de novo nao apaga ele)
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
            mudou = True
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
            mudou = True
        if (le(fx, LFX) or ("",))[0].upper() != CLSID:
            winreg.SetValueEx(fx, LFX, 0, winreg.REG_SZ, CLSID)
            mudou = True
        lista = [c for c in (le(fx, EFX_LISTA) or ([],))[0] if c.upper() != CLSID]
        simples = (le(fx, EFX) or ("",))[0]
        if simples and simples.upper() != CLSID:  # o EFX simples do fabricante entra na lista, na frente
            if simples.upper() not in [c.upper() for c in lista]:
                lista.insert(0, simples)
        if simples:
            winreg.DeleteValue(fx, EFX)
        nova = lista + [CLSID]
        if [c.upper() for c in (le(fx, EFX_LISTA) or ([],))[0]] != [c.upper() for c in nova]:
            winreg.SetValueEx(fx, EFX_LISTA, 0, winreg.REG_MULTI_SZ, nova)
            mudou = True
        modos = list((le(fx, MODOS_EFX) or ([],))[0])
        faltam = [m for m in (MODO_PADRAO, MODO_RAW) if m.upper() not in [x.upper() for x in modos]]
        if faltam:
            winreg.SetValueEx(fx, MODOS_EFX, 0, winreg.REG_MULTI_SZ, modos + faltam)
            mudou = True
        mudou |= _pendura_mfx(fx)
        if le(fx, ASSOCIACAO) is None:
            winreg.SetValueEx(fx, ASSOCIACAO, 0, winreg.REG_SZ, KSNODETYPE_ANY)
            mudou = True
    if sem_melhorias:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\Properties", 0, winreg.KEY_SET_VALUE) as p:
            winreg.SetValueEx(p, SEM_MELHORIAS, 0, winreg.REG_DWORD, 0)
        mudou = True
    return mudou


def _hospedado(vaga):
    """O CLSID do MFX do fabricante que a vaga do hospedeiro carrega, ou None."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SALVO) as raiz:
            return (le(raiz, f"_hospede{vaga}") or (None,))[0]
    except OSError:
        return None


def _vaga_hospede(fabricante):
    """A vaga do hospedeiro que carrega esse MFX do fabricante: a que ja o carrega, ou a primeira livre (gravada em
    HKLM\\SOFTWARE\\Ritmelli\\Microfone, _hospede<n>). O registro de APO do fabricante vai para o do hospedeiro (o
    regsvr32 grava o padrao a cada instalacao). None sem vaga livre."""
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, SALVO, 0, winreg.KEY_ALL_ACCESS) as raiz:
        livre = None
        for n in range(len(HOSPEDES)):
            v = (le(raiz, f"_hospede{n}") or (None,))[0]
            if v and v.upper() == fabricante.upper():
                livre = n
                break
            if v is None and livre is None:
                livre = n
        else:
            if livre is None:
                return None
            winreg.SetValueEx(raiz, f"_hospede{livre}", 0, winreg.REG_SZ, fabricante)
    _copia_registro_apo(fabricante, HOSPEDES[livre])
    return livre


def _copia_registro_apo(de, para):
    """Os valores do registro de APO do fabricante (flags, conexoes, interfaces) no do hospedeiro, com o nome nosso: o
    motor ve no hospedeiro o mesmo que veria no fabricante."""
    try:
        origem = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{APOS}\{de}")
    except OSError:  # fabricante sem registro de APO: fica o que o regsvr32 gravou
        return
    with origem, winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, rf"{APOS}\{para}", 0, winreg.KEY_ALL_ACCESS) as dest:
        i = 0
        while True:
            try:
                nome, valor, tipo = winreg.EnumValue(origem, i)
            except OSError:
                break
            i += 1
            if nome.lower() not in ("friendlyname", "copyright"):
                winreg.SetValueEx(dest, nome, 0, tipo, valor)


def _pendura_mfx(fx):
    """Com MFX do fabricante que cobre DEFAULT e RAW, o ultimo dele sai da lista e o hospedeiro que o carrega entra no
    lugar; sem MFX do fabricante (um driver novo tirou), sem RAW nele, ou sem vaga de hospedeiro, a lista fica a do
    fabricante. Os modos do MFX nao se mexem. True se mudou algo."""
    lista = list((le(fx, MFX_LISTA) or ([],))[0])
    fabricante = []
    for c in lista:  # o que um hospedeiro ja carrega volta a ser o do fabricante, para decidir de novo
        if c.upper() in HOSPEDES:
            c = _hospedado(HOSPEDES.index(c.upper()))
        if c and c.upper() not in NOSSOS:
            fabricante.append(c)
    simples = (le(fx, MFX) or ("",))[0]
    modos = [m.upper() for m in (le(fx, MODOS_MFX) or ([],))[0]]
    cobre = MODO_PADRAO.upper() in modos and MODO_RAW.upper() in modos
    usa = cobre and (fabricante or (simples and simples.upper() not in NOSSOS))
    mudou = False
    if usa and simples and simples.upper() not in NOSSOS:  # o MFX simples do fabricante entra na lista, na frente
        if simples.upper() not in [c.upper() for c in fabricante]:
            fabricante.insert(0, simples)
        winreg.DeleteValue(fx, MFX)
        mudou = True
    vaga = _vaga_hospede(fabricante[-1]) if usa else None
    nova = fabricante[:-1] + [HOSPEDES[vaga]] if vaga is not None else fabricante
    if [c.upper() for c in nova] != [c.upper() for c in lista]:
        if nova:
            winreg.SetValueEx(fx, MFX_LISTA, 0, winreg.REG_MULTI_SZ, nova)
        else:
            winreg.DeleteValue(fx, MFX_LISTA)
        mudou = True
    return mudou


def instala(filtro, dll):
    """So num microfone (desenvolvimento): o app usa o instala_todos. A conferencia dos aparelhos, se o audio
    reiniciou (confere_aparelhos), ou None."""
    ep, nome, apar = acha(filtro)
    parou = _prepara_dll(dll)
    novo = _pendura(ep)
    if novo or parou:
        reinicia_audio(so_servico=not novo)
    print(f"installed on {nome} ({apar}) {ep}")
    return _depois_do_reinicio() if novo or parou else None


def instala_todos(dll):
    """Pendura em todo microfone do Windows (ativo, desligado ou desconectado) que nao tem o filtro, e troca a DLL se
    a do app mudou. O audio do PC so reinicia se algo mudou: rodar de novo sem nada novo nao mexe no som, e so a DLL
    nova reinicia so o servico de audio. A conferencia dos aparelhos, se o audio reiniciou (confere_aparelhos), ou
    None."""
    parou = _prepara_dll(dll)
    novos = []
    for m in microfones(todos=True):
        try:
            if _pendura(m[0]):
                novos.append(m)
        except OSError:  # aparelho velho sem as propriedades no registro: fica sem, como estava
            continue
    if novos or parou:
        reinicia_audio(so_servico=not novos)
    print(f"filter on {len(microfones(todos=True))} microphones; now: {len(novos)}"
          f"{'; DLL replaced' if parou else ''}")
    return _depois_do_reinicio() if novos or parou else None


def _devolve(ep):
    """Devolve o original guardado de um microfone (as vagas de efeito e as melhorias) e apaga o guardado; False se
    nao havia nada guardado."""
    try:
        salvo = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{SALVO}\{ep}")
    except OSError:
        return False
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
    return True


def remove(filtro=None):
    """Devolve o original dos microfones (o do filtro, ou todos) e, sem nenhum com o filtro, tira a DLL. O audio do PC
    so reinicia se algum microfone mudou (o desinstalador chama sempre). A conferencia dos aparelhos, se o audio
    reiniciou (confere_aparelhos), ou None."""
    alvos = [acha(filtro)] if filtro else microfones(todos=True)
    mexeu = False
    for ep, nome, apar in alvos:
        if _devolve(ep):
            mexeu = True
            print(f"restored the original on {nome} ({apar}) {ep}")
    sobrou = [m for m in microfones(todos=True) if tem_filtro(m[0])]
    destino = os.path.join(PASTA, "micfx.dll")
    if not sobrou and os.path.exists(destino):
        subprocess.run(["regsvr32", "/s", "/u", destino], capture_output=True, creationflags=NO_WINDOW)
    r = None
    if mexeu:
        reinicia_audio()
        r = _depois_do_reinicio(grava=bool(sobrou))  # sem filtro nenhum, nao ha app para avisar: so o log
    if not sobrou:  # o audiodg ja soltou a DLL: saem a pasta (a DLL e o log), a tarefa, os hospedeiros e os mudos
        shutil.rmtree(PASTA, ignore_errors=True)
        tarefa_apaga()
        _esquece_hospedes()
        grava_mudos([])
    return r


def _esquece_hospedes():
    """Sem filtro em microfone nenhum, as vagas do hospedeiro (_hospede<n>) saem do registro."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SALVO, 0, winreg.KEY_ALL_ACCESS) as raiz:
            for n in range(len(HOSPEDES)):
                try:
                    winreg.DeleteValue(raiz, f"_hospede{n}")
                except OSError:
                    pass
    except OSError:
        pass


def dll_padrao():
    """A micfx.dll que vem com o app: no executavel, a da _internal\\microfone (ritmelli.spec); no fonte, a que o
    apo\\compila.bat gera."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "microfone", "micfx.dll")  # noqa: SLF001 - o PyInstaller poe aqui
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "apo", "saida", "micfx.dll")


def _sha(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def estado_dados():
    """O estado para a tela, sem administrador: {"microfones": [{"nome": o do Windows, "guid": a chave dele no
    registro, "filtro": bool, "melhorias": bool (as melhorias de audio ligadas; sem elas o filtro nao carrega)}],
    "dll_app": a DLL que vem com o app existe, "tarefa": a tarefa do instalador existe}."""
    mics, nomes = [], nomes_windows()
    for m in microfones():
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURA}\{m[0]}\Properties") as p:
                melhorias = not (le(p, SEM_MELHORIAS) or (0,))[0]
        except OSError:
            melhorias = True
        mics.append({"nome": nome_de(m, nomes), "guid": m[0], "filtro": tem_filtro(m[0]), "melhorias": melhorias})
    return {"microfones": mics, "dll_app": os.path.exists(dll_padrao()), "tarefa": tarefa_existe()}


def do_microfone(nome, dados=None):
    """O item do estado_dados desse microfone (pelo nome do Windows, sem caixa), ou None."""
    dados = dados or estado_dados()
    n = (nome or "").lower()
    return next((m for m in dados["microfones"] if m["nome"].lower() == n), None)


# A tarefa do Windows que pendura o filtro como SYSTEM: o instalador cria (ele e administrador), quem usa o PC so pode
# rodar (o descritor da tarefa da leitura e execucao aos usuarios), e o comando e fixo, no ritmelli.exe da pasta de
# programas (que so administrador muda). E por ela que o microfone que aparece depois ganha o filtro sem UAC.
TAREFA = r"\Ritmelli\Microfone"
TAREFA_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Ritmelli: adiciona o filtro de microfone aos microfones que ainda não o têm.</Description>
    <SecurityDescriptor>D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;AU)</SecurityDescriptor>
  </RegistrationInfo>
  <Principals>
    <Principal id="Sistema"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Sistema">
    <Exec><Command>{exe}</Command><Arguments>--microfone instala-todos</Arguments></Exec>
  </Actions>
</Task>
"""


def tarefa_existe():
    r = subprocess.run(["schtasks", "/query", "/tn", TAREFA], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def tarefa_cria():
    """Cria (ou refaz) a tarefa, so no executavel instalado: no codigo-fonte, a tarefa rodaria como SYSTEM um .py que
    o usuario pode mudar."""
    if not getattr(sys, "frozen", False):
        print("the task is only created by the installed executable (from source, run instala-todos as administrator)")
        return
    import tempfile  # noqa: PLC0415
    from xml.sax.saxutils import escape  # noqa: PLC0415
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
        sys.exit(f"couldn't create the task ({r.returncode}): {r.stdout.strip()} {r.stderr.strip()}")
    print(f"task {TAREFA} created")


def tarefa_apaga():
    subprocess.run(["schtasks", "/delete", "/tn", TAREFA, "/f"], capture_output=True, creationflags=NO_WINDOW)


def pede_tarefa(nome, espera_s=60):
    """Do app, sem administrador: roda a tarefa do instalador e espera o microfone ter o filtro (e as melhorias) e o
    audio do Windows voltar. {ok} ou {ok: False, motivo, detalhe}: o motivo e um codigo (sem_tarefa, tarefa_falhou,
    nao_pronto, audio), e quem chama poe a frase na lingua da tela (o engine.py)."""
    if not tarefa_existe():
        return {"ok": False, "motivo": "sem_tarefa"}
    r = subprocess.run(["schtasks", "/run", "/tn", TAREFA], capture_output=True, text=True, encoding="oem",
                       errors="replace", creationflags=NO_WINDOW)
    if r.returncode:
        return {"ok": False, "motivo": "tarefa_falhou", "detalhe": r.stdout.strip() or r.stderr.strip()}
    fim = time.monotonic() + espera_s
    while time.monotonic() < fim:
        time.sleep(1.0)
        m = do_microfone(nome)
        if m and m["filtro"] and m["melhorias"]:
            break
    else:
        return {"ok": False, "motivo": "nao_pronto"}
    while time.monotonic() < fim:  # o reinicio do audio: o servico volta depois do registro
        st = subprocess.run(["sc", "query", "audiosrv"], capture_output=True, text=True, encoding="oem",
                            errors="replace", creationflags=NO_WINDOW).stdout
        if "RUNNING" in st:
            time.sleep(2.0)  # os aparelhos se enumeram de novo logo depois
            return {"ok": True}
        time.sleep(0.5)
    return {"ok": False, "motivo": "audio"}


def _migra_registro():
    """O registro de antes da troca de nome (HKLM\\SOFTWARE\\Vitrola, migra.py) antes de mexer em qualquer microfone:
    sem o original de cada um, o _pendura guardaria o nosso filtro como original. O instalador ja chamou; aqui e a
    garantia para quem roda a ferramenta de outro jeito."""
    try:
        import migra
    except ImportError:  # rodando este arquivo direto, sem a raiz do app no caminho: o instalador ja migrou
        return
    migra.registro()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="microfone")
    ap.add_argument("acao", choices=("estado", "instala", "instala-todos", "remove", "confere"))
    ap.add_argument("--microfone")
    ap.add_argument("--dll", help="the micfx.dll to install (without it, the one that comes with the app)")
    ap.add_argument("--tarefa", action="store_true", help="instala-todos: also creates the Windows task")
    ap.add_argument("--saida", help="writes the result as JSON ({ok, erro, mudos, aparelhos}, in ASCII)")
    ap.add_argument("--aparelho", action="append", help="confere: only this device (repeatable)")
    a = ap.parse_args(argv)
    if a.acao == "confere":  # sem administrador e sem mexer em nada: o app, num processo a parte (engine._confere_fora)
        print(json.dumps(confere_aparelhos(a.aparelho)))
        return 0
    dll = a.dll or dll_padrao()
    res = {"ok": True}
    r = None
    try:
        if a.acao != "estado":
            _migra_registro()
        if a.acao == "estado":
            estado()
        elif a.acao in ("instala", "instala-todos"):
            if not os.path.exists(dll):
                sys.exit(f"the filter DLL isn't at {dll}")
            if a.acao == "instala":
                if not a.microfone:
                    sys.exit("instala needs --microfone")
                r = instala(a.microfone, dll)
            else:
                if a.tarefa:  # antes: um microfone que falhe nao deixa o PC sem a tarefa (o app nao teria como pedir)
                    tarefa_cria()
                r = instala_todos(dll)
        else:
            r = remove(a.microfone)
    except SystemExit as ex:
        if ex.code not in (None, 0):
            res = {"ok": False, "erro": str(ex.code)}
    except Exception as ex:  # noqa: BLE001 - quem chamou ve o motivo em vez de ficar sem resposta
        res = {"ok": False, "erro": f"{type(ex).__name__}: {ex}"}
    if r is not None:  # os aparelhos que pararam de entregar som depois do reinicio do audio (#136), e um nome por
        # aparelho fisico, o do aviso (a ultima pagina do instalador, instalador/mudos.iss)
        res["mudos"] = r["mudos"]
        res["aparelhos"] = list(dict.fromkeys(aparelho_de(n) for n in r["mudos"]))
    if a.saida:  # em ASCII (a letra com acento vai escapada): o Pascal do instalador le sem saber de UTF-8
        with open(a.saida, "w", encoding="ascii") as f:
            json.dump(res, f)
    if not res["ok"]:
        print(res["erro"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(1, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # o winvol.py do app
    sys.exit(main())
