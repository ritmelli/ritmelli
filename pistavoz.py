"""O pedal de troca de voz (#129): o modulo do contrato do API.md ("Pedal de troca de voz"). Com o pedal ligado, sobe
o processo da troca de voz (pista.py, pelo ritmelli.py --pistavoz), que le a voz crua do anel do filtro, converte e
escreve na pista da voz; desligado, derruba o processo e a voz do microfone volta.

As vozes sao as do ritmelli-voices (ENGINE e RELEASES: as tags que esta versao do app conhece), numa pasta vozes/
dentro da pasta de dados que o servidor passa em dados() (no --mock, a pasta temporaria dele); o pedal.json ao lado
guarda a voz escolhida e o tom de cada voz (semitons)."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pastas

VOZES = ["mina", "lira"]  # da mais grave para a mais aguda
ENGINE = "engine-v0.1"
RELEASES = {"mina": "mina-v0.2", "lira": "lira-v0.2"}
SAIR_S = 5  # o processo tem isso para sair sozinho com o "sair" antes de ser derrubado

_trava = threading.RLock()
_pasta = None
_cfg = None          # o pedal.json: {"voz": id, "tom": {id: semitons}}
_estado = {"voz": VOZES[0], "visor": None, "progresso": None}
_proc = None
_ligado = False


def dados(pasta):
    """A pasta de dados do app (a do library.json; no --mock, a temporaria): as vozes e o pedal.json ficam em vozes/
    dentro dela. O servidor chama ao subir."""
    global _pasta, _cfg
    with _trava:
        _pasta, _cfg = Path(pasta) / "vozes", None
        _carrega()  # o estado() ja sai com a voz escolhida, sem ler o disco


def _vozes():
    return _pasta if _pasta is not None else pastas.LIB / "vozes"


def _carrega():
    global _cfg
    if _cfg is None:
        try:
            with open(_vozes() / "pedal.json", encoding="utf-8") as f:
                _cfg = json.load(f)
        except (OSError, ValueError):
            _cfg = {}
        if _cfg.get("voz") not in VOZES:
            _cfg["voz"] = VOZES[0]
        _cfg.setdefault("tom", {})
        _estado["voz"] = _cfg["voz"]
    return _cfg


def _salva():
    p = _vozes()
    p.mkdir(parents=True, exist_ok=True)
    pastas.save_json(p / "pedal.json", _cfg)


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
    v = _vozes()
    return v / ENGINE, v / RELEASES[voz]


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
