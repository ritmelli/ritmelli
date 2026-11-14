"""O ponto de entrada da Vitrola, o mesmo do executavel (o PyInstaller congela este arquivo). Sem modo, liga o
servidor, com os argumentos do server.py (ja ligado, so abre a pagina). Os processos auxiliares que o servidor abre
vem por aqui tambem: no app congelado nao ha python nem .py para abrir, so o proprio executavel (ver auxiliar no
server.py).

    python vitrola.py [--port 8799 ...]   o servidor
    python vitrola.py --yt                o YouTube num processo a parte (yt_fora.py)
    python vitrola.py --andamento         a medida de andamento (andamento.py)
    python vitrola.py --microfone ...     o filtro de microfone (microfone/microfone.py): quem chama e o instalador e
                                          a tarefa do Windows que ele cria, nunca o servidor pelo UAC"""
import sys


def sem_console():
    """Sem console (o executavel, ou o pythonw), a saida e os erros, ate os de carregar o servidor, vao para os
    mesmos arquivos que o soundboard.ps1 grava. Os da vez anterior ficam ao lado (server.anterior.log): quem reabre o
    app depois de ele cair nao perde o motivo."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    import pastas
    pastas.LOGS.mkdir(parents=True, exist_ok=True)
    for nome, cano in (("server.log", "stdout"), ("server.err", "stderr")):
        if getattr(sys, cano) is None:
            p = pastas.LOGS / nome
            try:
                p.replace(p.with_name(f"{p.stem}.anterior{p.suffix}"))
            except OSError:
                pass  # a primeira vez, sem log anterior
            setattr(sys, cano, open(p, "w", encoding="utf-8", buffering=1))


def ja_ligado():
    """Outra Vitrola ja esta ligada ou ligando nesta porta (o atalho clicado de novo). Se ja atende, so abre a pagina
    dela; se ainda esta ligando, sai quieta, porque a pagina abre quando ela termina. Sem isto, a segunda abria o
    audio e caia na porta ocupada com o erro do Python na tela (29/10). Vem antes do sem_console, que zeraria os
    logs da que esta ligada."""
    if sys.platform != "win32":
        return False
    import argparse
    import ctypes
    import http.client

    import pastas
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--port", type=int, default=pastas.PORTA)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--version", action="store_true")
    a, _ = ap.parse_known_args()
    if a.version:
        return False
    # a trava do Windows vem primeiro: a que esta ligando so atende a porta uns 4 s depois (sem nada na tela, e quem
    # nao ve nada clica de novo), e perguntar a porta sem ninguem nela leva 2 s. Fica com o processo ate ele sair, e o
    # Windows solta se ele cair
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, f"Local\\Vitrola-{a.port}")
    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS: e a unica
        return False
    c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=2)  # sem urllib: um proxy do Windows nao entra
    try:
        c.request("GET", "/api/state")
        atende = c.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        atende = False
    finally:
        c.close()
    if atende and not a.no_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{a.port}{pastas.PAGINA}")
    return True


def main():
    # o auxiliar carrega so o modulo dele, sem o servidor
    modo = sys.argv[1] if len(sys.argv) > 1 else None
    if modo == "--yt":
        import yt_fora
        yt_fora.main()
    elif modo == "--andamento":
        import andamento
        andamento.main()
    elif modo == "--microfone":
        from microfone import microfone as filtro
        sys.exit(filtro.main(sys.argv[2:]))
    elif not ja_ligado():
        sem_console()
        import server
        server.main()


if __name__ == "__main__":
    main()
