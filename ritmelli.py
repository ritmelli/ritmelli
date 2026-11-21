"""O ponto de entrada do Ritmelli, o mesmo do executavel (o PyInstaller congela este arquivo). Sem modo, liga o
servidor, com os argumentos do server.py, e abre a janela (janela.py); ja ligado, so traz a janela para a frente. Os processos auxiliares que o servidor abre
vem por aqui tambem: no app congelado nao ha python nem .py para abrir, so o proprio executavel (ver auxiliar no
server.py).

    python ritmelli.py [--port 8799 ...]   o servidor
    python ritmelli.py --yt                o YouTube num processo a parte (yt_fora.py)
    python ritmelli.py --andamento         a medida de andamento (andamento.py)
    python ritmelli.py --microfone ...     o filtro de microfone (microfone/microfone.py): quem chama e o instalador e
                                           a tarefa do Windows que ele cria, nunca o servidor pelo UAC
    python ritmelli.py --atualizador ...   a atualizacao automatica (atualizador.py): a tarefa do Windows que o
                                           instalador cria roda como SYSTEM; o instalador cria e o desinstalador apaga
    python ritmelli.py --migra ...         a troca de nome de Vitrola para Ritmelli no PC (migra.py): o instalador
                                           chama, como administrador"""
import sys

# os argumentos com que o servidor nao liga de verdade: a versao e a ajuda so imprimem, e o --mock trabalha numa copia
# dos dados. Com eles a pasta de antes da troca de nome (%LOCALAPPDATA%\Vitrola) fica como esta (#123)
SEM_MIGRAR = ("--version", "--help", "-h", "--mock")


def migra_agora(argv):
    """O servidor vai ligar de verdade com estes argumentos: e hora de passar os dados para a pasta nova."""
    return not any(a in SEM_MIGRAR for a in argv)


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
    """Outro Ritmelli ja esta ligado ou ligando nesta porta (o atalho clicado de novo). Se ja atende, traz a janela
    dele para a frente (janela.py), ou abre a pagina dele no navegador, quando ele nao tem janela; se ainda esta
    ligando, sai quieto, porque a janela abre quando ele termina. Sem isto, o segundo abria o audio e caia na porta
    ocupada com o erro do Python na tela (29/10). Vem antes do sem_console, que zeraria os logs do que esta ligado."""
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
    # a trava do Windows vem primeiro: o que esta ligando so atende a porta uns 4 s depois (sem nada na tela, e quem
    # nao ve nada clica de novo), e perguntar a porta sem ninguem nela leva 2 s. Fica com o processo ate ele sair, e o
    # Windows solta se ele cair
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, f"Local\\Ritmelli-{a.port}")
    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS: e o unico
        return False
    c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=2)  # sem urllib: um proxy do Windows nao entra
    try:
        c.request("GET", "/api/state")
        atende = c.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        atende = False
    finally:
        c.close()
    if atende and not a.no_browser and not traz_a_janela(a.port):
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{a.port}{pastas.PAGINA}")
    return True


def traz_a_janela(porta):
    """Pede a janela do Ritmelli ligada para a frente (/api/janela/foco). Quem acabou de ser aberto pelo clique e quem
    pode passar a frente: o AllowSetForegroundWindow passa esse direito a ele. False se ele nao tem janela (o
    navegador, ou uma versao de antes da janela)."""
    import ctypes
    import http.client
    ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    try:
        c.request("POST", "/api/janela/foco", body=b"{}", headers={"Content-Type": "application/json"})
        return c.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        c.close()


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
    elif modo == "--atualizador":
        import atualizador
        sys.exit(atualizador.main(sys.argv[2:]))
    elif modo == "--migra":
        import migra
        sys.exit(migra.main(sys.argv[2:]))
    else:
        # os dados da pasta de antes da troca de nome (%LOCALAPPDATA%\Vitrola) vem para a nova antes de qualquer modulo
        # do servidor calcular os caminhos dele (pastas.migra); a versao, a ajuda e o --mock nao mexem nela
        import pastas
        if migra_agora(sys.argv[1:]):
            pastas.migra()
        if not atualizando() and not ja_ligado():
            sem_console()
            import server
            server.main()
            ao_sair()


def atualizando():
    """O Ritmelli foi aberto no meio da atualizacao automatica (o instalador da tarefa trocando os arquivos): sai logo,
    para nao segurar o que ele troca, e abre de novo quando ele terminar (atualizador.reabre)."""
    if not getattr(sys, "frozen", False):
        return False
    import atualizador
    if not atualizador.instalando_agora():
        return False
    atualizador.reabre()
    return True


def ao_sair():
    """O Ritmelli desligou (o X, o Desligar da pagina ou o Instalar agora): com a versao nova ja baixada pela tarefa do
    Windows, e agora que ela entra (atualizador.ao_sair)."""
    if not getattr(sys, "frozen", False):
        return
    import atualizacao
    import atualizador
    try:
        if atualizador.automatica():
            atualizador.ao_sair(reabrir=atualizacao.REABRIR)
    except OSError as e:
        print(f"update: {e}", flush=True)


if __name__ == "__main__":
    main()
