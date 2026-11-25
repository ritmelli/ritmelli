"""Os comandos de musica do servidor: tocar, enfileirar, pular, voltar, pausar, retomar, alternar, parar, ir para um
ponto do disco, tirar, mover e limpar a fila e o volume da musica. A regra de cada um mora aqui, e nao na rota: a
rota do server.py le o corpo, chama o comando e monta a resposta, e quem nao e rota (os vigias do App) chama o
mesmo comando. Cada funcao recebe o App do server.py (A); a fila, o historico e a fila_lock sao dele.

O avanco da fila e uma operacao so (avanca): o Proxima (/api/next), o fim do disco (_volta_fila), a virada da
passagem (_volta_passagem), o stream da parecida que nao abriu (_abre_stream), a parecida que chegou com o prato
parado (_volta_auto) e o enfileirar com o prato parado passam por ela, com uma reserva so por deck e linha do prato
(Reserva).

As travas, sempre nesta ordem e nunca ao contrario: a fila_lock do App, depois o _lock do motor (um RLock), depois o
_qlock do motor. Com o _qlock na mao nao se chama metodo do motor que pegue o _lock, e a thread do audio (o _mixa)
nunca pega a fila_lock nem o _lock. Sob a fila_lock nao se grava arquivo."""
import sys
import threading

import engine as eng
import i18n
import pastas

# o por_cima que nao veio no corpo do /api/play: o som curto (buzina, bordao) decide sozinho
CURTO = object()
# quanto o pausar espera o motor confirmar a pausa: o bloco em curso leva 10 ms, e so um _mixa parado passa disso
PAUSA_ESPERA_S = 1.0
# quanto o avanco que achou outra reserva em curso na mesma linha espera o resultado dela
AVANCO_ESPERA_S = 5.0
# o avanco que cedeu a vez: outra reserva de avanco ja corre na mesma linha do prato, ou o prato ja mudou
CEDEU = object()


class Reserva:
    """A reserva de avanco da fila numa linha do prato: o deck e a linha do prato e a entrada (x) que vai tocar. Ha uma
    so em curso por deck e linha (App.reserva, que muda sob a fila_lock e o _qlock). A confirmacao, o erro e a
    invalidacao a resolvem (App._solta_reserva) e liberam quem espera."""

    def __init__(self, deck, linha, x):
        self.deck, self.linha, self.x = deck, linha, x
        self.entrada = None
        self.feita = threading.Event()

    def vale(self, E):
        """Com o _qlock do motor E: o prato ainda e o deck e a linha da reserva."""
        return E._deck is self.deck and E._deck.linha == self.linha

    def espera(self, prazo=None):
        """O resultado, sem trava nenhuma: a entrada que tocou, ou None (erro, invalidacao, prazo estourado)."""
        self.feita.wait(AVANCO_ESPERA_S if prazo is None else prazo)
        return self.entrada


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
    """A entrada do corpo b no A seguir (o POST /api/queue): o poe_na_fila e depois o toca_se_parado. Volta (entrada,
    job, tocou); CorpoRecusado e a recusa do corpo."""
    x, j = poe_na_fila(A, b, remoto=remoto)
    return x, j, toca_se_parado(A, x)


def poe_na_fila(A, b, remoto=False):
    """A entrada do corpo b no A seguir, sem tocar (a regra de cada campo e o App.enfileirar). A rota chama no laco do
    servidor, como o tocar e a prateleira: a procura do download do mesmo video e a criacao de um novo nao correm com
    outro pedido. Volta (entrada, job); CorpoRecusado e a recusa do corpo."""
    try:
        return A.enfileirar(b, remoto=remoto)
    except ValueError as ex:
        raise CorpoRecusado(str(ex)) from ex


def toca_se_parado(A, x):
    """Com nada no prato (parado, ou o disco ja acabou), a entrada x que acabou de entrar toca na hora, sem esperar a
    vez; pausado ainda e disco no prato, e a fila so guarda. Tocar na hora e um avanco reservado na linha do prato: se
    o fim do disco (o vigia) ja reservou o avanco dela, este espera o resultado, e tocou so se foi esta entrada; se
    ela nao tocou nada (a entrada quebrada) e o prato segue na mesma linha, a vez e desta. O prato que mudou de linha
    no meio (o Parar, outro disco) fica como esta. Volta se tocou."""
    cap = A.engine.captura()
    if cap.status not in ("idle", "ended"):
        return False
    for _ in range(3):  # a reserva de outro que nao tocou nesta linha devolve None: de novo, na mesma linha
        y = avanca(A, visto=cap, entrada=x)
        if y is not None:
            return y is x  # a entrada que tocou, ou CEDEU (o prato ja e outra linha)
    return False


def tocar_da_fila(A, qid):
    """A entrada qid sai da fila e toca agora (a virada pendente fecha antes: a entrada dela ja tocou). Volta a
    entrada, ou None se ela ja tinha saido."""
    with A.fila_lock:
        x = next((y for y in A.fila if y["qid"] == qid), None) if qid else None
    if x is None:
        return None
    try:
        return x if A.tocar_entrada(x, entrada=x) else None
    except Exception:
        with A.fila_lock:
            A._tirar_se(x)  # a entrada quebrada sai da fila, como antes
        raise


def tirar_da_fila(A, qid):
    """A entrada qid sai da fila; a parecida do Automatico que o usuario tirou nao volta nesta sessao. Volta a
    entrada, ou None se ela ja tinha saido."""
    return A.tirar_da_fila(qid, recusar=True)


def mover_na_fila(A, qid, to):
    """A entrada qid vai para a posicao to da fila. False se ela ja tinha saido."""
    return A.mover_na_fila(qid, to)


def limpar_fila(A):
    A.limpar_fila()


def fecha_virada(A, virada):
    """Com a fila_lock, e com a virada ja tirada do motor (o E.virou limpo sob o _qlock): a entrada dela sai da fila, o
    que saiu entra no Anterior e a marca do prato parado sai, sem soltar a trava. O Proxima ou o fim do disco que
    chegar logo depois espera, guarda o disco da virada depois dele e marca o prato depois. Volta a entrada (None se
    ela ja tinha saido)."""
    sai, entrou, tag = virada
    x = next((y for y in A.fila if y["qid"] == tag), None)
    if x:
        A._tirar(x)
    A._guardar_historico(entrou["id"], tr=sai)
    A.parado_sem_fila = None
    return x


def avanca(A, virada=None, historico=True, na_tela=False, visto=None, entrada=None, pular=False, cede=False):
    """O avanco da fila. Com virada, o (o que saiu, o que entrou, a tag) do motor, que ja virou sozinho para a entrada
    da tag na passagem: ela so sai da fila, e o que saiu entra no historico. Volta a entrada (None se ela ja tinha
    saido).

    Sem virada, um avanco reservado na linha do prato. Sob a fila_lock e o _qlock, fecha antes a virada que o motor ja
    confirmou e o vigia ainda nao conciliou (no Proxima, pular=True, essa virada e o avanco dele: volta a entrada que
    acabou de entrar) e reserva a entrada (a primeira da fila, ou entrada) para o deck e a linha do prato, tirando a
    passagem preparada (o motor nao vira para ela no meio). Tocar corre fora das travas, e a troca confere de novo a
    reserva, o deck, a linha e a entrada sob elas (App._troca): so ai a entrada sai da fila e o que saiu entra no
    Anterior (historico=False: nao entra). Com outra reserva em curso na mesma linha, quem chega cede (cede=True, os
    vigias: volta CEDEU) ou espera o resultado dela, sem trava nenhuma (o Proxima, o enfileirar). visto: a Captura do
    prato que pediu o avanco (o fim do disco, o enfileirar com o prato parado); com o prato ja em outro deck ou linha,
    volta CEDEU. Volta a entrada que tocou, None (fila vazia, ou a reserva invalidada no meio) ou CEDEU. na_tela: o
    erro de tocar vai para a tela (o engine.error), e nao para quem chamou (os vigias: entrada quebrada nao trava a
    fila); nos dois casos ela sai da fila."""
    E = A.engine
    if virada is not None:
        with A.fila_lock:
            # a virada sai do motor e a entrada dela sai da fila sob a mesma fila_lock: a leitura do estado
            # (App.leitura) ve as duas, ou nenhuma. Quem chega depois (o vigia, ou outro avanco) nao concilia de novo
            with E._qlock:
                if E.virou is not virada:
                    return None
                E.virou = None
            return fecha_virada(A, virada)
    em_curso = r = None
    if not cede:
        # a reserva de outro ja em curso nesta linha (o vigia trocando o disco, com a fila_lock na mao): quem chega
        # espera o resultado dela, sem disputar a fila_lock e reservar a seguinte depois
        with E._qlock:
            r0 = A.reserva
            vivo = r0 is not None and not r0.feita.is_set() and r0.vale(E)
        if vivo:
            return r0.espera()
    with A.fila_lock:
        while True:
            with E._qlock:
                v, E.virou = E.virou, None
                if v is None:
                    d = E._deck
                    if visto is not None and (visto.deck is not d or visto.linha != d.linha):
                        return CEDEU
                    em_curso = A.reserva
                    if em_curso is not None and (em_curso.feita.is_set() or not em_curso.vale(E)):
                        em_curso = None
                    if em_curso is None:
                        x = entrada if entrada is not None else (A.fila[0] if A.fila else None)
                        if x is None or not any(y is x for y in A.fila):
                            return None
                        r = A.reserva = Reserva(d, d.linha, x)
                        E._cancela_passagem()  # a preparada sai: o motor nao vira para ela no meio do avanco
                    break
            x = fecha_virada(A, v)  # o Anterior guarda primeiro o que saiu nela
            if pular and x is not None:
                return x  # sem a entrada (ja saiu da fila), o Proximo segue para a primeira
    if em_curso is not None:
        return CEDEU if cede else em_curso.espera()
    try:
        tocou = A.tocar_entrada(r.x, historico=historico, entrada=r.x, reserva=r)
    except Exception as ex:  # noqa: BLE001 - nos vigias, entrada quebrada nao trava a fila
        if r.feita.is_set() and r.entrada is r.x:  # tocou: o que falhou veio depois (a gravacao da posicao)
            print(f"queue: {r.x.get('title')!r} played, but then: {ex}", file=sys.stderr, flush=True)
            return r.x
        with A.fila_lock:
            outra = A.reserva
            if outra is None or outra is r or outra.x is not r.x:  # a entrada de outra reserva em curso fica
                A._tirar_se(r.x)
            A._solta_reserva(r, None)
        if not na_tela:
            raise
        E.error = i18n.msg("server.queue.playFailed", "Couldn't play \"{title}\" from the queue ({reason}).",
                           title=r.x.get("title") or "?", reason=i18n.motivo(ex, 120))
        return r.x
    if not tocou:  # a reserva foi invalidada no meio (o prato trocou, ou a entrada saiu da fila)
        with A.fila_lock:
            A._solta_reserva(r, None)
        return CEDEU if cede else None
    return r.x


def pular(A):
    """O Proxima: a primeira da fila toca agora; logo depois de uma virada da passagem ainda nao conciliada, a
    virada e o avanco, e volta a entrada que acabou de entrar. Os Proximos sobrepostos (o segundo chega antes de o
    primeiro voltar, mesmo preso na fila_lock enquanto o primeiro troca o disco) dividem o mesmo avanco: um so toca, e
    os outros esperam o resultado dele, sem trava nenhuma. Volta a entrada, ou None com a fila vazia (ou o avanco que
    nao tocou)."""
    with A.proximo_lock:
        p = A.proximo
        dono = p is None
        if dono:
            p = A.proximo = Reserva(None, None, None)
    if not dono:
        return p.espera()
    x = None
    try:
        x = avanca(A, pular=True)
        return x
    finally:
        with A.proximo_lock:
            A.proximo = None
        p.entrada = x
        p.feita.set()


def voltar(A):
    """O Anterior (App.anterior): "inicio", "anterior" ou None (nada tocou antes deste)."""
    return A.anterior()


def pausar(A):
    """Pausa no limite entre blocos do motor (engine.pause) e grava a posicao que ele confirmou. A espera e sem trava
    nenhuma e tem prazo (PAUSA_ESPERA_S); o pedido substituido no meio (retomar, trocar de disco, ir para outro ponto)
    termina a espera sem gravar nada. Volta se a pausa foi confirmada."""
    p = A.engine.pause()
    if not p.espera(PAUSA_ESPERA_S):
        return False
    A.remember_pos(pausa=p)
    return True


def retomar(A):
    A.engine.resume()


def alternar(A):
    """O botao principal (o /api/toggle): tocando ou carregando, pausa e grava a posicao confirmada; senao, retoma. A
    escolha e no motor (engine.alterna): dois toggles juntos nao pausam os dois, e uma pausa pendente o segundo
    retoma."""
    p = A.engine.alterna()
    if p is not None and p.espera(PAUSA_ESPERA_S):
        A.remember_pos(pausa=p)


def parar(A):
    """O disco sai do prato, e o Anterior toca ele de novo (a virada pendente fecha antes, sob a mesma fila_lock: o
    Anterior guarda primeiro o que saiu nela). A posicao gravada e a do instante em que ele saiu."""
    def para(depois):
        A._fecha_viradas()
        cap = A.engine.stop()
        if A.reserva is not None:
            A._solta_reserva(A.reserva, None)  # quem esperava o avanco desta linha nao espera mais
        if cap.track is not None:
            A._guardar_historico(tr=cap.track)
        return cap
    A.remember_pos(A._com_motor(para))  # a fila_lock e o _lock do motor, sem prender a leitura do estado


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
