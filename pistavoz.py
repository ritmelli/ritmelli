"""O pedal de troca de voz (#129): o modulo do contrato do API.md ("Pedal de troca de voz"). Com o pedal ligado, sobe
o processo da troca de voz (pista.py, pelo ritmelli.py --pistavoz), que le a voz crua do anel do filtro, converte e
escreve na pista da voz; desligado, derruba o processo e a voz do microfone volta.

As vozes sao as do ritmelli-voices, nas releases que o vozes.json (ao lado deste arquivo) fixa, com o sha256 de cada
arquivo: o instalador baixa os arquivos para a pasta vozes\\ do app (MODELOS), e quem roda pelo codigo baixa com o
python dev/vozes.py baixa. Sem placa de video, ou sem os modelos, o pedal nao aparece (impedimento()). O que e de quem
usa (a voz escolhida e o tom de cada voz, em semitons) fica no pedal_voz.json da pasta de dados que o servidor passa
em dados() (no --mock, a temporaria dele)."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pastas

with open(Path(__file__).resolve().parent / "vozes.json", encoding="utf-8") as _f:
    MANIFESTO = json.load(_f)
VOZES = [v["id"] for v in MANIFESTO["vozes"]]  # da mais grave para a mais aguda
ENGINE = MANIFESTO["engine"]["tag"]
RELEASES = {v["id"]: v["tag"] for v in MANIFESTO["vozes"]}
MODELOS = pastas.APP / "vozes"  # a pasta do app: no instalado, a que o instalador encheu
SAIR_S = 5  # o processo tem isso para sair sozinho com o "sair" antes de ser derrubado

_trava = threading.RLock()
_arq = None          # o pedal_voz.json
_cfg = None          # o que ele guarda: {"voz": id, "tom": {id: semitons}}
_estado = {"voz": VOZES[0], "visor": None, "progresso": None}
_proc = None
_ligado = False


def placas():
    """O nome de cada placa de video do PC, pelo DXGI (o que o DirectML enxerga), sem o adaptador de software do
    Windows (o Microsoft Basic Render Driver, que roda no processador)."""
    if os.name != "nt":
        return []
    import ctypes

    class Guid(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

    class Desc1(ctypes.Structure):  # DXGI_ADAPTER_DESC1
        _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                    ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                    ("LuidBaixo", ctypes.c_ulong), ("LuidAlto", ctypes.c_long), ("Flags", ctypes.c_uint)]

    def metodo(obj, i, *args):  # o metodo i da tabela do objeto COM
        tabela = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *args)(tabela[i])

    iid = Guid(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    fab = ctypes.c_void_p()
    dxgi = ctypes.WinDLL("dxgi")
    dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long
    if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(fab)) != 0:
        return []
    nomes = []
    try:
        enum = metodo(fab, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))  # IDXGIFactory1::EnumAdapters1
        i = 0
        while True:
            ad = ctypes.c_void_p()
            if enum(fab, i, ctypes.byref(ad)) != 0:  # DXGI_ERROR_NOT_FOUND: acabou
                break
            d = Desc1()
            ok = metodo(ad, 10, ctypes.POINTER(Desc1))(ad, ctypes.byref(d)) == 0  # IDXGIAdapter1::GetDesc1
            metodo(ad, 2)(ad)  # Release
            if ok and not d.Flags & 2:  # DXGI_ADAPTER_FLAG_SOFTWARE
                nomes.append(d.Description)
            i += 1
    finally:
        metodo(fab, 2)(fab)
    return nomes


def impedimento():
    """None com o pedal pronto para aparecer; senao o motivo, que o fx.py poe no log, e o pedal fica de fora (o
    Alienigena volta): sem placa de video, ou sem os modelos baixados inteiros na MODELOS."""
    if not placas():
        return "no graphics card for DirectML (only the software adapter)"
    faltam = [f"{r['tag']}/{a['nome']}" for r in [MANIFESTO["engine"], *MANIFESTO["vozes"]] for a in r["arquivos"]
              if not ((MODELOS / r["tag"] / a["nome"]).is_file()
                      and (MODELOS / r["tag"] / a["nome"]).stat().st_size == a["tamanho"])]
    if faltam:
        return (f"{len(faltam)} voice files missing or incomplete in {MODELOS} ({faltam[0]}...; the installer downloads "
                f"them, and from the code: python dev/vozes.py baixa)")
    return None


def dados(pasta):
    """A pasta de dados do app (a do library.json; no --mock, a temporaria): o pedal_voz.json fica nela. O servidor
    chama ao subir."""
    global _arq, _cfg
    with _trava:
        _arq, _cfg = Path(pasta) / "pedal_voz.json", None
        _carrega()  # o estado() ja sai com a voz escolhida, sem ler o disco


def _carrega():
    global _cfg
    if _cfg is None:
        try:
            with open(_arq or pastas.LIB / "pedal_voz.json", encoding="utf-8") as f:
                _cfg = json.load(f)
        except (OSError, ValueError):
            _cfg = {}
        if not isinstance(_cfg, dict) or _cfg.get("voz") not in VOZES:
            _cfg = {"voz": VOZES[0], "tom": (_cfg.get("tom") if isinstance(_cfg, dict) else None)}
        if not isinstance(_cfg.get("tom"), dict):
            _cfg["tom"] = {}
        _estado["voz"] = _cfg["voz"]
    return _cfg


def _salva():
    arq = _arq or pastas.LIB / "pedal_voz.json"
    arq.parent.mkdir(parents=True, exist_ok=True)
    pastas.save_json(arq, _cfg)


def estado():
    """{"voz", "visor", "progresso"} na hora, sem disco nem rede (o servidor chama a cada tick do SSE)."""
    return dict(_estado)


def escolhe(voz):
    """Troca a voz; com o pedal ligado, o processo sobe de novo com a voz nova."""
    if voz not in VOZES:
        raise ValueError(f"unknown voice {voz!r}")
    with _trava:
        cfg = _carrega()
        if cfg["voz"] == voz:
            return
        cfg["voz"] = _estado["voz"] = voz
        _salva()
        if _ligado:
            _para()
            _sobe()


def liga(ligado):
    """True ao entrar no efeito do pedal, False ao sair dele e quando o app fecha (pode repetir o mesmo valor)."""
    global _ligado
    with _trava:
        _carrega()
        _ligado = bool(ligado)
        if _ligado and _proc is None:
            _sobe()
        elif not _ligado:
            _para()


def pastas_da_voz(voz):
    """(a pasta da engine, a pasta da voz) com os modelos baixados."""
    return MODELOS / ENGINE, MODELOS / RELEASES[voz]


def _comando():
    if getattr(sys, "frozen", False):  # o app congelado: o proprio executavel
        return [sys.executable, "--pistavoz"]
    return [sys.executable, str(Path(__file__).resolve().parent / "ritmelli.py"), "--pistavoz"]


def _sobe():
    global _proc
    voz = _cfg["voz"]
    engine, pasta = pastas_da_voz(voz)
    if not (engine.is_dir() and pasta.is_dir()):
        print(f"pedal_voz: the {voz} voice isn't downloaded ({pasta})", file=sys.stderr, flush=True)
        return
    arg = json.dumps({"engine": str(engine), "voz": str(pasta), "tom": float(_cfg["tom"].get(voz, 0.0)),
                      "provedor": os.environ.get("RITMELLI_PISTAVOZ_PROVEDOR", "dml")})
    pastas.LOGS.mkdir(parents=True, exist_ok=True)
    log = open(pastas.LOGS / "pistavoz.log", "w", encoding="utf-8")
    p = subprocess.Popen(_comando() + [arg], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True,
                         encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log.close()
    _proc = p
    threading.Thread(target=_ouve, args=(p,), daemon=True, name="pistavoz_ouve").start()


def _ouve(p):
    """O que o processo diz: "pronto" e "erro: ..." vao para o log do app."""
    global _proc
    for linha in p.stdout:
        linha = linha.strip()
        if linha:
            print(f"pedal_voz: {linha}", file=sys.stderr, flush=True)
    with _trava:
        if _proc is p:
            _proc = None


def _para():
    global _proc
    p, _proc = _proc, None
    if p is None:
        return
    try:
        p.stdin.write("sair\n")
        p.stdin.flush()
        p.stdin.close()
    except OSError:
        pass
    try:
        p.wait(timeout=SAIR_S)
    except subprocess.TimeoutExpired:
        p.kill()
