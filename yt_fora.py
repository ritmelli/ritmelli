"""O YouTube (yt-dlp e ytmusicapi) num processo a parte, nunca no do servidor (num notebook o audio
estalava bastante): o yt-dlp segurava o interpretador do servidor em rajadas de 30 a 45 ms a cada endereco de
stream, e o callback do audio e de 10 ms. O servidor deixa um processo destes ja aberto, com as bibliotecas
carregadas, esperando o pedido (Fora); cada pedido usa um e ja abre o proximo.

    python vitrola.py --yt   (o pedido em JSON na entrada: {"op": ..., ...}; no app, vitrola.exe --yt)

A saida e uma linha JSON por evento: {"progresso": f} no download e, no fim, {"r": resultado} ou {"erro": motivo}.
Do yt-dlp volta so o que o servidor le (enxuto): o info inteiro nao e JSON e e grande."""
import difflib
import json
import re
import sys
import threading
import unicodedata
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


# palavras que nao contam na comparacao do pedido com o nome do artista
VAZIAS = {"mc", "dj", "e", "do", "da", "de", "dos", "das", "o", "a", "os", "as", "the", "musica", "musicas", "uma", "um"}


def palavras(texto):
    """As palavras que contam: minusculo, sem acento, as iniciais com ponto juntas ("M.C." -> "mc", "N.W.A." ->
    "nwa"), sem as VAZIAS."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\b(?:[a-z0-9]\.){2,}", lambda m: m.group(0).replace(".", ""), t)
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", t).split() if w not in VAZIAS]


def so_artista(pedido, artista):
    """O pedido e so o nome do artista que o YouTube Music achou: cada palavra dele bate com uma do nome (a escrita
    pode errar um pouco: "the weekend" e The Weeknd, "rei da cimbinha" e Rei da Cacimbinha). Sobrou palavra = o nome
    da musica veio junto. O nome de um integrante ("Chorão Charlie Brown Jr") sobra e vai como musica."""
    nomes, ped = palavras(artista), palavras(pedido)
    return bool(ped) and bool(nomes) and all(
        any(difflib.SequenceMatcher(None, w, x).ratio() >= 0.8 for x in nomes) for w in ped)


def _item(x, artista=None):
    """Um resultado do YouTube Music no formato do /api/search (o que o /api/queue recebe)."""
    yid = x.get("videoId")
    if not yid:
        return None
    nomes = ", ".join(a["name"] for a in x.get("artists") or [] if a.get("name")) or artista
    it = {"youtube_id": yid, "title": x.get("title")}
    if nomes:
        it["channel"] = nomes
    if x.get("duration_seconds"):
        it["duration"] = x["duration_seconds"]
    return it


# O cliente do YouTube Music aquecido na espera (09/11): o primeiro pedido de um cliente novo busca antes o visitor id
# (abre a pagina inicial do YouTube Music), 0,53 a 0,60 s medidos no PC com a ytmusicapi 1.12.3, e todo pedido e um
# processo novo, entao toda busca pagava isso (1,3 s contra 0,7 com o cliente ja usado). O processo de reserva faz isso
# numa thread enquanto espera; o pedido que nao e do YouTube Music (o endereco de stream, logo depois da busca) nao
# espera por ela
_YTM = None
_AQUECE = None
_AQUECE_ERRO = None


def aquece_ytm():
    global _YTM, _AQUECE_ERRO
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        yt.headers  # noqa: B018 - o visitor id vem no primeiro acesso aos cabecalhos
        _YTM = yt
    except Exception as ex:  # noqa: BLE001 - sem o aquecido, o pedido abre um cliente novo
        _AQUECE_ERRO = str(ex)[:120] or type(ex).__name__


def ytm():
    """O cliente do YouTube Music: o aquecido (esperando o aquecimento terminar) ou, se ele falhou, um novo."""
    from ytmusicapi import YTMusic
    if _AQUECE is not None:
        _AQUECE.join()
    if _YTM is not None:
        return _YTM
    if _AQUECE_ERRO:
        print(f"YouTube Music: o aquecimento falhou ({_AQUECE_ERRO}): cliente novo", file=sys.stderr)
    return YTMusic()


def musica(q, n, yt=None):
    """A busca de musica do YouTube Music, como o app dele busca (09/11, o pedido falado da mina): a busca do YouTube
    devolvia o que nao e musica ("Toca Raul" achou um video de financas; nos 90 pedidos falados das sessoes, ~7 assim),
    e a do YouTube Music devolveu musica nos 90, em 0,74 s de mediana contra 1,41. O melhor resultado sendo um artista
    e o pedido so o nome dele: as mais tocadas da pagina dele ("Raul" -> Metamorfose Ambulante, "Radiohead" -> Creep);
    com o nome da musica junto, as musicas e videos da busca ("Luan Santana Chuva de Arroz" -> Chuva de Arroz). Volta
    a lista no formato do /api/search, vazia se nada achou."""
    if yt is None:
        yt = ytm()
    res = yt.search(q, limit=10) or []
    topo = res[0] if res else {}
    if topo.get("resultType") == "artist":
        dono = (topo.get("artists") or [{}])[0] or {}
        bid = topo.get("browseId") or dono.get("id")
        nome = dono.get("name") or topo.get("artist")
        if bid and (nome is None or so_artista(q, nome)):
            pag = yt.get_artist(bid) or {}
            nome = pag.get("name") or nome
            if so_artista(q, nome or ""):
                itens = [i for i in (_item(x, nome) for x in ((pag.get("songs") or {}).get("results") or [])) if i]
                if itens:
                    print(f"busca: {q!r} é o artista {nome}: a mais tocada, {itens[0]['title']}", file=sys.stderr)
                    return itens[:n]
    itens = [i for i in (_item(x) for x in res if x.get("resultType") in ("song", "video")) if i]
    if itens:
        print(f"busca: {q!r} no YouTube Music: {itens[0]['title']} ({itens[0].get('channel') or '?'})", file=sys.stderr)
    return itens[:n]


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
        return ytm().get_watch_playlist(videoId=p["yid"], radio=True, limit=p["n"]).get("tracks") or []
    if op == "musica":
        return musica(p["q"], p.get("n", 3))
    if op == "musicas":
        return ytm().search(p["q"], filter="songs", limit=3)[:3]
    raise ValueError(f"pedido desconhecido: {op}")


def main():
    global _AQUECE
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # o servidor le o cano em utf-8
    try:
        import ytmusicapi  # noqa: F401 - carregada ja na espera, como o yt-dlp
    except ImportError:
        pass  # sem ela, o radio e a versao de audio voltam erro e o servidor segue com o Mix do YouTube
    else:
        _AQUECE = threading.Thread(target=aquece_ytm, daemon=True)
        _AQUECE.start()
    pedido = sys.stdin.read()
    if not pedido.strip():
        sys.exit(0)  # o servidor fechou sem pedir (saiu, ou este era o de reserva)
    try:
        print(json.dumps({"r": faz(json.loads(pedido))}), flush=True)
    except Exception as ex:  # noqa: BLE001 - o servidor poe o motivo no log e na tela
        print(json.dumps({"erro": str(ex) or type(ex).__name__}), flush=True)


if __name__ == "__main__":
    main()
