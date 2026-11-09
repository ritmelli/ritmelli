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


# O processo vivo dos enderecos (09/11): o servidor manda os pedidos de stream, um por linha, a um processo que fica
# aberto, e aqui o YoutubeDL e o mesmo de um pedido ao outro. E ele que guarda o player do YouTube ja lido: no
# notebook, com 9 musicas, o endereco saiu em 1,48 s com um YoutubeDL novo a cada pedido no mesmo processo e em
# 0,80 s com o mesmo (o primeiro paga os 1,5 s de sempre)
VIVO = False
_YDLS = {}


def _ydl(opts):
    """O YoutubeDL das opts no processo vivo: o mesmo a cada pedido (as opts mudam so na tentativa com outro formato)."""
    k = json.dumps(opts, sort_keys=True)
    if k not in _YDLS:
        _YDLS[k] = yt_dlp.YoutubeDL(opts)
    return _YDLS[k]


# O endereco rapido (09/11): com o YoutubeDL quente, 0,68 s dos 0,89 s do endereco eram a pagina do video; sem ela o
# yt-dlp pede o initial data (0,5 a 0,7 s) e o cliente web com o JS do player. So o cliente visionos (o que da o
# audio 251 sem o desafio de JS), sem a pagina, o initial data, os configs e o JS, com o visitor data do cliente do
# YouTube Music (sem ele o YouTube pede "Sign in to confirm you're not a bot"): no PC, 6 videos em 0,14 a 0,21 s, todos
# tocando no ffmpeg. Falhou, vai o de sempre no mesmo processo (faz)
RAPIDO_ARGS = {"player_client": ["visionos"], "player_skip": ["webpage", "configs", "initial_data", "js"],
               "skip": ["hls"]}
# o disjuntor do rapido (revisao da r01): falhou isso de vezes seguidas (ou uma com "not a bot"), o processo para de
# tentar o rapido ate ser renovado, sem dobrar os pedidos de player no IP de casa
RAPIDO_FALHAS_MAX = 2
_rapido_falhas = 0


def opts_rapido(opts):
    """As opts do endereco rapido (ver RAPIDO_ARGS), com o visitor id do cliente do YouTube Music."""
    vid = ytm().headers.get("X-Goog-Visitor-Id")
    if not vid:
        raise RuntimeError("sem o visitor id do YouTube Music")
    ea = dict(opts.get("extractor_args") or {})
    ea["youtube"] = {**(ea.get("youtube") or {}), **RAPIDO_ARGS, "visitor_data": [vid]}
    return {**opts, "extractor_args": ea}


def canal_do(yid):
    """O nome do canal de um video pelo cliente do YouTube Music: o rapido pula o initial data, de onde o yt-dlp tira o
    canal (revisao da r01); so quando quem pediu nao tem o canal (link colado, a passagem sem ele). None se falhou."""
    if not yid:
        return None
    try:
        return ((ytm().get_song(yid) or {}).get("videoDetails") or {}).get("author") or None
    except Exception:  # noqa: BLE001 - fica sem o canal, como antes de ter o rapido
        return None


def stream_yt(alvo, opts):
    """O info do yt-dlp com o endereco direto do audio no YouTube e os cabecalhos HTTP dele, em texto para o ffmpeg."""
    if VIVO:
        info = _ydl(opts).extract_info(alvo, download=False)
    else:
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
# numa thread enquanto espera. O endereco rapido (opts_rapido) usa o visitor id dele e espera o aquecimento: num
# processo recem-aberto isso entra no primeiro endereco
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
    """O cliente do YouTube Music: o aquecido (esperando o aquecimento terminar) ou, se ele falhou, um novo, que fica
    para os pedidos seguintes deste processo quando consegue o visitor id (sem isso o processo vivo pagaria o GET do
    YouTube Music em todo endereco rapido; revisao da r01)."""
    global _YTM, _AQUECE_ERRO
    from ytmusicapi import YTMusic
    if _AQUECE is not None:
        _AQUECE.join()
    if _YTM is not None:
        return _YTM
    if _AQUECE_ERRO:
        print(f"YouTube Music: o aquecimento falhou ({_AQUECE_ERRO}): cliente novo", file=sys.stderr)
        _AQUECE_ERRO = None
    yt = YTMusic()
    try:
        yt.headers  # noqa: B018 - o visitor id
        _YTM = yt
    except Exception:  # noqa: BLE001 - sem rede: o pedido segue e o proximo tenta de novo
        pass
    return yt


# a sugestao da caixa de busca (09/11, a latencia do pedido falado): o YouTube Music sugere musicas enquanto se digita,
# em 0,11 s de mediana contra 0,71 s da busca (14 pedidos, cliente quente), e a primeira costuma ser a faixa oficial
# ("Murder In My Mind" do Kordhell em vez do Slowed + Reverb). Mas em metade dos pedidos falados de verdade (20 de 40,
# os longos e os tortos) nao vem musica nenhuma, e as vezes vem outra ("Uma Rapariga e Bom Demais" -> "Raparigas").
# Vale so a primeira do tipo Song (o audio oficial; o Video pode ser remix) com todas as palavras do pedido no titulo
# ou no artista (a regra do so_artista); senao, a busca de sempre. False = so a busca
SUGESTAO = True


def sugestao(q, yt):
    """A primeira musica (Song) das sugestoes do YouTube Music para q, no formato do /api/search, se ela bate com o
    pedido (ver SUGESTAO); senao None."""
    r = yt._send_request("music/get_search_suggestions", {"input": q})
    for sec in r.get("contents") or []:
        for it in (sec.get("searchSuggestionsSectionRenderer") or {}).get("contents") or []:
            m = it.get("musicResponsiveListItemRenderer")
            if not m:
                continue
            nav = m.get("navigationEndpoint") or {}
            yid = (m.get("playlistItemData") or {}).get("videoId") or (nav.get("watchEndpoint") or {}).get("videoId")
            if not yid:
                continue
            cols = ["".join(x.get("text", "") for x in ((c.get("musicResponsiveListItemFlexColumnRenderer") or {})
                                                          .get("text") or {}).get("runs") or [])
                    for c in m.get("flexColumns") or []]
            partes = (cols[1] if len(cols) > 1 else "").split(" • ")
            if not cols or partes[0] != "Song" or len(partes) < 2:
                return None  # a primeira musica sugerida e video (remix, ao vivo) ou sem artista: vai a busca
            titulo, artista = cols[0], partes[1]
            if not so_artista(q, f"{titulo} {artista}"):
                return None
            return {"youtube_id": yid, "title": titulo, "channel": artista}
    return None


def musica(q, n, yt=None):
    """A busca de musica do YouTube Music, como o app dele busca (09/11, o pedido falado da mina): a busca do YouTube
    devolvia o que nao e musica ("Toca Raul" achou um video de financas; nos 90 pedidos falados das sessoes, ~7 assim),
    e a do YouTube Music devolveu musica nos 90, em 0,74 s de mediana contra 1,41. O melhor resultado sendo um artista
    e o pedido so o nome dele: as mais tocadas da pagina dele ("Raul" -> Metamorfose Ambulante, "Radiohead" -> Creep);
    com o nome da musica junto, as musicas e videos da busca ("Luan Santana Chuva de Arroz" -> Chuva de Arroz). Volta
    a lista no formato do /api/search, vazia se nada achou."""
    if yt is None:
        yt = ytm()
    if SUGESTAO and n <= 3:
        try:
            s = sugestao(q, yt)
        except Exception as ex:  # noqa: BLE001 - a busca de sempre
            s = None
            print(f"busca: a sugestao de {q!r} falhou ({str(ex)[:100]})", file=sys.stderr)
        if s:
            print(f"busca: {q!r} pela sugestao: {s['title']} ({s['channel']})", file=sys.stderr)
            return [s]
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
        global _rapido_falhas
        info = None
        if p.get("rapido") and _rapido_falhas < RAPIDO_FALHAS_MAX:
            try:
                info, hdr = stream_yt(p["alvo"], opts_rapido(p["opts"]))
                _rapido_falhas = 0
            except Exception as ex:  # noqa: BLE001 - o de sempre logo em seguida, no mesmo processo
                _rapido_falhas = RAPIDO_FALHAS_MAX if "not a bot" in str(ex) else _rapido_falhas + 1
                fora = ": desligado neste processo" if _rapido_falhas >= RAPIDO_FALHAS_MAX else ""
                print(f"stream: o rapido falhou em {p['alvo']} ({str(ex)[:120]}): vai pelo de sempre{fora}",
                      file=sys.stderr, flush=True)
        if info is None:
            info, hdr = stream_yt(p["alvo"], p["opts"])
        if p.get("canal") and not info.get("channel"):
            info["channel"] = canal_do(info.get("id"))
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
    # o pedido e uma linha JSON (o servidor de antes escrevia sem a quebra e fechava a entrada: o readline le igual);
    # com "vivo", o processo segue atendendo um pedido por linha ate o servidor fechar a entrada
    linha = sys.stdin.readline()
    if not linha.strip():
        sys.exit(0)  # o servidor fechou sem pedir (saiu, ou este era o de reserva)
    responde(linha)
    while VIVO:
        linha = sys.stdin.readline()
        if not linha.strip():
            break
        responde(linha)


def responde(linha):
    global VIVO
    try:
        p = json.loads(linha)
        VIVO = bool(p.pop("vivo", False)) or VIVO
        print(json.dumps({"r": faz(p)}), flush=True)
    except Exception as ex:  # noqa: BLE001 - o servidor poe o motivo no log e na tela
        print(json.dumps({"erro": str(ex) or type(ex).__name__}), flush=True)


if __name__ == "__main__":
    main()
