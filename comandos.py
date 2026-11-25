"""Os comandos de musica do servidor: tocar, enfileirar, pular, voltar, pausar, retomar, alternar, parar, ir para um
ponto do disco, tirar, mover e limpar a fila e o volume da musica. A regra de cada um mora aqui, e nao na rota: a
rota do server.py le o corpo, chama o comando e monta a resposta, e quem nao e rota (os vigias do App) chama o
mesmo comando. Cada funcao recebe o App do server.py (A); a fila, o historico e a fila_lock sao dele.

O avanco da fila e uma operacao so (avanca): o Proxima (/api/next), o fim do disco (_volta_fila), a virada da
passagem (_volta_passagem), o stream da parecida que nao abriu (_abre_stream) e a parecida que chegou com o prato
parado (_volta_auto) passam por ela.

As travas, sempre nesta ordem e nunca ao contrario: a fila_lock do App, depois o _lock do motor (um RLock), depois o
_qlock do motor. Com o _qlock na mao nao se chama metodo do motor que pegue o _lock, e a thread do audio (o _mixa)
nunca pega a fila_lock nem o _lock. Sob a fila_lock nao se grava arquivo."""
import engine as eng
import i18n
import pastas

# o por_cima que nao veio no corpo do /api/play: o som curto (buzina, bordao) decide sozinho
CURTO = object()


class CorpoRecusado(ValueError):
    """O corpo que o enfileirar recusa (a rota responde 400 com o texto). O erro de tocar a entrada na hora nao e uma
    recusa: segue para quem chamou, como antes."""


def tocar(A, iid, start=None, retomar=False, loop=None, por_cima=CURTO):
    """O disco iid da prateleira no prato (o /api/play). Sem o por_cima, o som curto toca por cima da musica em vez de
    trocar, so quando nao vem start nem retomar (continuar de onde parou e a faixa principal); com ele, True ou False
    decide. Volta "por_cima", "prato" ou None (o disco nao esta na prateleira)."""
    it = A.lib.get(iid)
    if not it:
        return None
    curto = (it.get("duration") or 1e9) <= eng.CURTO_MAX_S and start is None and not retomar
    if (curto if por_cima is CURTO else por_cima):
        A.engine.por_cima(dict(it, path=str(pastas.LIB / it["file"])))
        return "por_cima"
    if start is None:
        start = it.get("last_pos", 0) if retomar else 0
    A.play_item(it, float(start), loop)
    return "prato"


def enfileirar(A, b, remoto=False):
    """A entrada do corpo b no A seguir (o POST /api/queue; a regra de cada campo e o App.enfileirar). Com nada no
    prato (parado, ou o disco ja acabou), o que acabou de entrar toca na hora, sem esperar a vez; pausado ainda e
    disco no prato, e a fila so guarda. Volta (entrada, job, tocou); CorpoRecusado e a recusa do corpo."""
    try:
        x, j = A.enfileirar(b, remoto=remoto)
    except ValueError as ex:
        raise CorpoRecusado(str(ex)) from ex
    if A.engine.status() in ("idle", "ended") and A.tirar_da_fila(x["qid"]):
        A.tocar_entrada(x)
        return x, j, True
    return x, j, False


def tocar_da_fila(A, qid):
    """A entrada qid sai da fila e toca agora. Volta a entrada, ou None se ela ja tinha saido."""
    x = A.tirar_da_fila(qid or "")
    if x:
        A.tocar_entrada(x)
    return x


def tirar_da_fila(A, qid):
    """A entrada qid sai da fila; a parecida do Automatico que o usuario tirou nao volta nesta sessao. Volta a
    entrada, ou None se ela ja tinha saido."""
    return A.tirar_da_fila(qid, recusar=True)


def mover_na_fila(A, qid, to):
    """A entrada qid vai para a posicao to da fila. False se ela ja tinha saido."""
    return A.mover_na_fila(qid, to)


def limpar_fila(A):
    A.limpar_fila()


def avanca(A, virada=None, historico=True, na_tela=False):
    """O avanco da fila. Sem virada, a primeira do A seguir sai da fila e toca (historico=False: o disco que sai do
    prato nao entra no Anterior). Com virada, o (o que saiu, o que entrou, a tag) do motor, que ja virou sozinho
    para a entrada da tag na passagem: ela so sai da fila, e o que saiu entra no historico. Volta a entrada (None
    com a fila vazia, ou, na virada, se ela ja tinha saido). na_tela: o erro de tocar vai para a tela (o
    engine.error), e nao para quem chamou (os vigias: entrada quebrada nao trava a fila)."""
    E = A.engine
    if virada is not None:
        sai, entrou, tag = virada
        with A.fila_lock:
            # a virada sai do motor e a entrada dela sai da fila sob a mesma fila_lock: a leitura do estado (App.leitura)
            # ve as duas, ou nenhuma. Quem chega depois (o vigia, ou o avanco abaixo) nao concilia de novo
            with E._qlock:
                if E.virou is not virada:
                    return None
                E.virou = None
            x = next((y for y in A.fila if y["qid"] == tag), None)
            if x:
                A._tirar(x)
            # o que saiu entra no Anterior, e a marca do prato parado sai, ainda sob a mesma fila_lock: o Proxima ou o
            # fim do disco que chegar logo depois espera, guarda o disco da virada depois dele e marca o prato depois
            A._guardar_historico(entrou["id"], tr=sai)
            A.parado_sem_fila = None
        return x
    v = E.virou
    if v is not None:  # a virada que o vigia ainda nao conciliou fecha antes: o Anterior guarda o que saiu nela primeiro
        avanca(A, virada=v)
    x = A.proxima()
    if x is None:
        return None
    try:
        A.tocar_entrada(x, historico=historico)
    except Exception as ex:  # noqa: BLE001 - nos vigias, entrada quebrada nao trava a fila
        if not na_tela:
            raise
        A.engine.error = i18n.msg("server.queue.playFailed", "Couldn't play \"{title}\" from the queue ({reason}).",
                                  title=x.get("title") or "?", reason=i18n.motivo(ex, 120))
    return x


def pular(A):
    """O Proxima: a primeira da fila toca agora. Volta a entrada, ou None com a fila vazia."""
    return avanca(A)


def voltar(A):
    """O Anterior (App.anterior): "inicio", "anterior" ou None (nada tocou antes deste)."""
    return A.anterior()


def pausar(A):
    A.engine.pause()
    A.remember_pos()


def retomar(A):
    A.engine.resume()


def alternar(A):
    """O botao principal (o /api/toggle): tocando ou carregando, pausa; senao, retoma."""
    if A.engine.status() in ("playing", "buffering"):
        pausar(A)
    else:
        retomar(A)


def parar(A):
    """O disco sai do prato, e o Anterior toca ele de novo."""
    A.remember_pos()
    A.guardar_historico()
    A.engine.stop()


def ir_para(A, t):
    """O disco do prato a partir de t segundos."""
    A.engine.seek(t)


def volume(A, v):
    """O volume da musica (de 0 a 1; fora disso, o limite), gravado sozinho: o resto do som fica como esta gravado.
    Volta o do motor."""
    v = max(0.0, min(1.0, float(v)))
    A.engine.vol = v
    A.grava_cfg(vol=v)
    return A.engine.vol
