"""O YouTube (yt-dlp e ytmusicapi) num processo a parte, nunca no do servidor (num notebook o audio
estalava bastante): o yt-dlp segurava o interpretador do servidor em rajadas de 30 a 45 ms a cada endereco de
stream, e o callback do audio e de 10 ms. O servidor deixa um processo destes ja aberto, com as bibliotecas
carregadas, esperando o pedido (Fora); cada pedido usa um e ja abre o proximo.

    python yt_fora.py   (o pedido em JSON na entrada: {"op": ..., ...})

A saida e uma linha JSON por evento: {"progresso": f} no download e, no fim, {"r": resultado} ou {"erro": motivo}.
Do yt-dlp volta so o que o servidor le (enxuto): o info inteiro nao e JSON e e grande."""
import json
import sys
from pathlib import Path

import yt_dlp

CAMPOS = ("id", "title", "duration", "channel", "uploader")
ABAIXO_DO_NORMAL = 0x00004000  # o download cede o processador ao audio, como a medida de andamento


def enxuto(info):
    """Do info do yt-dlp, os CAMPOS e, numa playlist ou busca, os das entradas."""
    out = {k: info.get(k) for k in CAMPOS}
    if info.get("entries") is not None:
        out["entries"] = [enxuto(e) for e in info["entries"] if e]
    return out


def stream_yt(alvo, opts):
    """O info do yt-dlp com o endereco direto do audio no YouTube e os cabecalhos HTTP dele, em texto para o ffmpeg."""
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(alvo, download=False)
    if info.get("entries"):
        info = info["entries"][0]
    if not info.get("url"):
        raise RuntimeError("o YouTube não deu um endereço de áudio")
    return info, "".join(f"{k}: {v}\r\n" for k, v in (info.get("http_headers") or {}).items())


def baixar(alvo, opts):
    """O download para opts["outtmpl"], com o progresso na saida; volta o info enxuto e o nome do arquivo."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), ABAIXO_DO_NORMAL)

    def hook(d):
        tot = d.get("total_bytes") or d.get("total_bytes_estimate")
        if d.get("status") == "downloading" and tot:
            print(json.dumps({"progresso": d.get("downloaded_bytes", 0) / tot}), flush=True)

    with yt_dlp.YoutubeDL({**opts, "progress_hooks": [hook]}) as y:
        info = y.extract_info(alvo, download=True)
        if info.get("entries"):
            info = info["entries"][0]
        return {"info": enxuto(info), "file": Path(y.prepare_filename(info)).name}


def faz(p):
    op = p["op"]
    if "opts" in p:
        p["opts"] = {**p["opts"], "logtostderr": True}  # a saida e so do JSON: o que o yt-dlp diz vai para o log
    if op == "stream":
        info, hdr = stream_yt(p["alvo"], p["opts"])
        return {"info": dict(enxuto(info), url=info["url"]), "hdr": hdr}
    if op == "info":
        with yt_dlp.YoutubeDL(p["opts"]) as y:
            return enxuto(y.extract_info(p["alvo"], download=False))
    if op == "baixar":
        return baixar(p["alvo"], p["opts"])
    if op == "radio":
        from ytmusicapi import YTMusic
        return YTMusic().get_watch_playlist(videoId=p["yid"], radio=True, limit=p["n"]).get("tracks") or []
    if op == "musicas":
        from ytmusicapi import YTMusic
        return YTMusic().search(p["q"], filter="songs", limit=3)[:3]
    raise ValueError(f"pedido desconhecido: {op}")


if __name__ == "__main__":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # o servidor le o cano em utf-8
    try:
        import ytmusicapi  # noqa: F401 - carregada ja na espera, como o yt-dlp
    except ImportError:
        pass  # sem ela, o radio e a versao de audio voltam erro e o servidor segue com o Mix do YouTube
    pedido = sys.stdin.read()
    if not pedido.strip():
        sys.exit(0)  # o servidor fechou sem pedir (saiu, ou este era o de reserva)
    try:
        print(json.dumps({"r": faz(json.loads(pedido))}), flush=True)
    except Exception as ex:  # noqa: BLE001 - o servidor poe o motivo no log e na tela
        print(json.dumps({"erro": str(ex) or type(ex).__name__}), flush=True)
