"""Confere o ffmpeg so de audio (bin\\) contra o ffmpeg completo de antes: os mesmos comandos do motor da Vitrola nos
discos da biblioteca, a duracao pelo ffprobe, um stream https, os consertos de container do yt-dlp e o que o yt-dlp acha
dele. Sai 1 se alguma coisa nao bate.

    python testa.py <bin novo> <bin de antes> [pasta da biblioteca]
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

NOVO, VELHO = Path(sys.argv[1]), Path(sys.argv[2])
LIB = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(os.environ["LOCALAPPDATA"]) / "Vitrola" / "library"
SR = 48000   # o do engine.py
DIF_MAX = 1e-4   # a mesma fonte com outro compilador: a conta em ponto flutuante pode mudar na ultima casa
STREAM = "https://upload.wikimedia.org/wikipedia/commons/c/c8/Example.ogg"
falhas = []


def pcm(pasta, *args):
    """Como o motor le: ffmpeg [-ss] -i <fonte> [-t] -f f32le -ac 2 -ar 48000 -"""
    r = subprocess.run([str(pasta / "ffmpeg.exe"), "-v", "error", "-nostdin", *args, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                       capture_output=True, timeout=300)
    return np.frombuffer(r.stdout[: len(r.stdout) // 4 * 4], np.float32), r.returncode, r.stderr.decode(errors="replace").strip()


def duracao(pasta, arq):
    r = subprocess.run([str(pasta / "ffprobe.exe"), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(arq)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def confere(nome, args):
    a, ra, ea = pcm(NOVO, *args)
    b, rb, eb = pcm(VELHO, *args)
    if ra != rb or (ra and not ea == eb):
        falhas.append(f"{nome}: saida {ra} contra {rb} ({ea[:120] or eb[:120]})")
        return f"FALHOU, saida {ra} contra {rb}"
    if len(a) != len(b):
        falhas.append(f"{nome}: {len(a)} amostras contra {len(b)}")
        return f"FALHOU, {len(a)} amostras contra {len(b)}"
    d = float(np.abs(a - b).max()) if len(a) else 0.0
    if d > DIF_MAX:
        falhas.append(f"{nome}: diferenca {d:.2e}")
        return f"FALHOU, diferenca {d:.2e}"
    return f"ok, {len(a) // 2 / SR:.1f} s, diferenca {d:.1e}"


print("--- o que ele tem")
for opcao, precisa in (("-protocols", ("https", "tls", "http")), ("-bsfs", ("setts", "aac_adtstoasc")), ("-muxers", ("mp4", "f32le"))):
    saida = subprocess.run([str(NOVO / "ffmpeg.exe"), "-hide_banner", opcao], capture_output=True, text=True).stdout
    nomes = set(saida.split())
    falta = [p for p in precisa if p not in nomes]
    print(f"{opcao}: {'ok' if not falta else 'FALTA ' + ', '.join(falta)}")
    if falta:
        falhas.append(f"{opcao} sem {', '.join(falta)}")

print("--- os discos da biblioteca, com os comandos do motor")
discos = sorted(p for p in LIB.iterdir() if p.suffix.lower() in (".webm", ".m4a", ".mp4", ".mp3", ".opus", ".ogg", ".wav", ".flac"))
for arq in discos:
    dn, dv = duracao(NOVO, arq), duracao(VELHO, arq)
    if dn is None or dv is None or abs(dn - dv) > 0.001:
        falhas.append(f"{arq.name}: duracao {dn} contra {dv}")
    meio = max(0.0, min(60.0, (dv or 0) / 2))
    inicio = confere(f"{arq.name} do comeco", ["-i", str(arq), "-t", "20"])
    pulo = confere(f"{arq.name} de {meio:.0f} s", ["-ss", f"{meio:.3f}", "-i", str(arq), "-t", "10"])
    print(f"{arq.name}: duracao {dn} | comeco {inicio} | de {meio:.0f} s {pulo}")

print("--- stream https")
print(f"{STREAM}: {confere('stream https', ['-user_agent', 'Vitrola-teste-do-ffmpeg', '-i', STREAM, '-t', '3'])}")

print("--- consertos de container do yt-dlp (copiar para mp4 sem recodificar)")
with tempfile.TemporaryDirectory() as tmp:
    for arq in [p for p in discos if p.suffix.lower() in (".mp4", ".m4a")][:3]:
        for nome, extra in (("FixupM4a", []), ("FixupM3u8", ["-bsf:a", "aac_adtstoasc"])):
            saida = Path(tmp) / f"{arq.stem}-{nome}.mp4"
            r = subprocess.run([str(NOVO / "ffmpeg.exe"), "-y", "-v", "error", "-nostdin", "-i", str(arq), "-map", "0", "-dn", "-ignore_unknown",
                                "-c", "copy", *extra, "-f", "mp4", str(saida)], capture_output=True, text=True)
            d = duracao(NOVO, saida) if r.returncode == 0 else None
            ok = r.returncode == 0 and d is not None and abs(d - (duracao(VELHO, arq) or 0)) < 0.1
            print(f"{arq.name} {nome}: {'ok' if ok else 'FALHOU ' + r.stderr.strip()[:160]}")
            if not ok:
                falhas.append(f"{arq.name} {nome}")

print("--- o que o yt-dlp acha dele")
from yt_dlp import YoutubeDL  # noqa: E402
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor  # noqa: E402

with YoutubeDL({"ffmpeg_location": str(NOVO), "quiet": True}) as ydl:
    pp = FFmpegPostProcessor(ydl)
    print(f"disponivel: {pp.available} | ffprobe: {pp.probe_available} | versao: {pp._versions.get('ffmpeg')} | setts: {pp._features.get('setts')}")
    if not (pp.available and pp.probe_available and pp._features.get("setts")):
        falhas.append("o yt-dlp nao aceita o ffmpeg novo")

tam = sum(f.stat().st_size for f in NOVO.glob("*.exe")), sum(f.stat().st_size for f in VELHO.iterdir() if f.is_file())
print(f"--- tamanho: {tam[0] / 2**20:.1f} MB, contra {tam[1] / 2**20:.1f} MB")
print("FALHAS:" if falhas else "tudo confere", *falhas, sep="\n  ")
sys.exit(1 if falhas else 0)
