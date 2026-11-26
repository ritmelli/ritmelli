"""Os comandos de musica do servidor: tocar, enfileirar, pular, voltar, pausar, retomar, alternar, parar, ir para um
ponto do disco, tirar, mover e limpar a fila e o volume da musica. A regra de cada um mora aqui, e nao na rota: a
rota do server.py le o corpo, chama o comando e monta a resposta, e quem nao e rota (os vigias do App) chama o
mesmo comando. Cada funcao recebe o App do server.py (A); a fila, o historico e a fila_lock sao dele.

O avanco da fila e uma operacao so (avanca): o Proxima (/api/next), o fim do disco (_volta_fila), a virada da
passagem (_volta_passagem), o stream da parecida que nao abriu (_abre_stream), a parecida que chegou com o prato
parado (auto_round) e o enfileirar com o prato parado passam por ela, com uma reserva so por deck e linha do prato
(Reserva).

Lock order, always this way and never the other: the App's fila_lock, then the engine's _lock (an RLock), then the
engine's _qlock. Two more come right before the _qlock and are never held with the fila_lock nor the _lock: the
App's proximo_lock (the overlapping Proximos, pular) and the shelf's lock (Library.lock: App.remember_pos takes it,
then the _qlock, and writes the file with the _qlock released). With the _qlock held, no engine method that takes the
_lock is called, and the audio thread (the _mixa) never takes the fila_lock nor the _lock. No file is written under
the fila_lock.

The platter's line is read and checked through the engine's interface (Engine.line, Engine.on_line, with the deck
and line a Captura already carries), the switch the engine made on its own is reconciled in one loop (concilia), and
every queue change goes through App.change_queue."""
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
# concilia: take the pending switch out of the engine, close it and go round again
FECHA = object()
# the advance that carries on past the reconcile loop (avanca)
_CONTINUE_ADVANCE = object()
# how many times an advance is tried on the same platter when another reservation resolved without playing (the
# enqueue on a stopped platter, the similar track whose stream did not open)
ADVANCE_TRIES = 3


class Reserva:
    """A reserva de avanco da fila numa linha do prato: o deck e a linha do prato e a entrada (x) que vai tocar. Ha uma
    so em curso por deck e linha (App.reserva, que muda sob a fila_lock e o _qlock). A confirmacao, o erro e a
    invalidacao a resolvem (App.release_reservation) e liberam quem espera."""

    def __init__(self, deck, linha, x):
        self.deck, self.linha, self.x = deck, linha, x
        self.entrada = None
        self.feita = threading.Event()
        self.tocando = False  # a troca dela ja publicou o disco no prato (numa linha nova), e falta confirmar
        self.publicada = None  # o (deck, linha) que a troca dela publicou, anotado sob o _lock da troca
        # os Proximos (comandos.Proximo) que esperam por ela; resolvem com ela (App.release_reservation)
        self.grupos = []

    def vale(self, E):
        """Com o _qlock do motor E: o prato ainda e o deck e a linha da reserva."""
        return E.on_line(self)

    def toca(self, E):
        """Com o _qlock do motor E: o pode da troca dela. Ainda vale, e o prato passa a ser o dela ali mesmo
        (tocando): quem chega ate ela resolver espera por ela, mesmo com a linha nova."""
        if not self.vale(E):
            return False
        self.tocando = True
        return True

    def viva(self, E):
        """Com o _qlock do motor E: em curso, e ainda desta linha ou ja trocando o prato."""
        return not self.feita.is_set() and (self.tocando or self.vale(E))

    def espera(self, prazo=None):
        """O resultado, sem trava nenhuma: a entrada que tocou, ou None (erro, invalidacao, prazo estourado)."""
        self.feita.wait(AVANCO_ESPERA_S if prazo is None else prazo)
        return self.entrada


class Proximo(Reserva):
    """Os Proximos sobrepostos de uma linha do prato (App.proximo): o primeiro avanca, e os outros esperam o resultado
    dele. r: a reserva que ele fez ou espera."""

    def __init__(self, deck, linha):
        super().__init__(deck, linha, None)
        self.r = None
        self.virada = None  # a virada pendente que ele viu: o avanco dele e ela, e nenhuma reserva o liga

    def resolve(self, entrada):
        """Com o _qlock: o resultado do grupo, uma vez so; os que esperam por ele voltam."""
        if not self.feita.is_set():
            self.entrada = entrada
            self.feita.set()

    def liga(self, r):
        """Com o _qlock: r e o avanco deste grupo. Ele resolve quando r resolver (ou agora, se r ja resolveu), sem
        esperar o resto do Proximo que o abriu (a gravacao da posicao)."""
        self.r = r
        r.grupos.append(self)
        if r.feita.is_set():
            self.resolve(r.entrada)

    def junta(self, E):
        """Com o _qlock do motor E: quem chega agora divide este avanco (o prato ainda na linha dele, ou na linha que a
        reserva dele publicou, ou com ela publicando agora); depois de um Parar ou de outro disco, nao. O grupo ja
        resolvido, com o primeiro Proximo ainda por voltar (gravando a posicao), aceita quem chega se tocou e o prato
        segue na linha que ele publicou: o resultado volta na hora."""
        r = self.r
        if self.feita.is_set():
            return self.entrada is not None and r is not None and E.on_line(r.publicada)
        return self.vale(E) or (r is not None and ((r.tocando and not r.feita.is_set()) or E.on_line(r.publicada)))


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


def play_shelf_record(A, it):
    """The shelf record it, the one the route already picked, on the platter from the start (the POST /api/library with
    play of a record already on the shelf): a short sound too, never on top, and never from its last_pos. Returns
    whether it swapped."""
    return A.play_item(it, 0.0)


def play_downloading(A, j, alvo, meta):
    """The video alvo, not on the shelf yet, on the platter right away over the stream while job j downloads it (the
    POST /api/library with play): when the file arrives, the engine moves to it without cutting. meta: the youtube_id,
    title, channel, thumb and duration the body brought. Returns whether it swapped."""
    A.job_update(j, play=True)
    return A.tocar_remoto(j, alvo, meta)


def update_record(A, iid, **fields):
    """The shelf record iid gets fields (the PATCH /api/library/{iid}: the title, the "rapido"), and the platter's
    track too when it is that record, so the state shows the new name right away (Engine.update_track, under the
    engine's _qlock). Returns the record, or None if it is not on the shelf."""
    it = A.lib.update(iid, **fields)
    if it:
        A.engine.update_track(it["id"], **fields)
    return it


def enfileirar(A, b, remoto=False):
    """A entrada do corpo b no A seguir (o POST /api/queue): o poe_na_fila e depois o toca_se_parado. Volta (entrada,
    job, tocou); CorpoRecusado e a recusa do corpo."""
    x, j = poe_na_fila(A, b, remoto=remoto)
    return x, j, toca_se_parado(A, x, A.engine.captura())


def poe_na_fila(A, b, remoto=False):
    """A entrada do corpo b no A seguir, sem tocar (a regra de cada campo e o App.enfileirar). A rota chama no laco do
    servidor, como o tocar e a prateleira: a procura do download do mesmo video e a criacao de um novo nao correm com
    outro pedido. Volta (entrada, job); CorpoRecusado e a recusa do corpo."""
    try:
        return A.enfileirar(b, remoto=remoto)
    except ValueError as ex:
        raise CorpoRecusado(str(ex)) from ex


def toca_se_parado(A, x, cap):
    """Com nada no prato (parado, ou o disco ja acabou), a entrada x que acabou de entrar toca na hora, sem esperar a
    vez; pausado ainda e disco no prato, e a fila so guarda. Tocar na hora e um avanco reservado na linha do prato: se
    o fim do disco (o vigia) ja reservou o avanco dela, este espera o resultado, e tocou so se foi esta entrada; se
    ela nao tocou nada (a entrada quebrada) e o prato segue na mesma linha, a vez e desta. cap: o prato logo depois de x
    entrar na fila (a rota captura no laco, antes do executor); o que mudou de linha depois (o Parar, outro disco) fica
    como esta. Volta se tocou."""
    if cap.status not in ("idle", "ended"):
        return False
    for _ in range(ADVANCE_TRIES):  # a reserva de outro que nao tocou nesta linha devolve None: de novo, na mesma linha
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
            A.remove_if_queued(x)  # a entrada quebrada sai da fila, como antes
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


def concilia(A, under, closed=None):
    """With the fila_lock: the one loop that reconciles the switch the engine already made on its own (the DJ
    transition) with the queue. Each round runs under(v) under the engine's _qlock, with v the pending switch (None
    without one): under returns FECHA (only with a v) to take v out of the engine in that same stretch and close it
    (fecha_virada, with the _qlock released and the fila_lock still held), or anything else, which concilia returns.
    closed(x), with the entry of the switch just closed (None if it had already left the queue), returns FECHA to go
    round again, or the result. Since the switch leaves the engine under the fila_lock, only one caller reconciles each
    one, and the state read (App.leitura) sees the switch and its entry together, or neither."""
    E = A.engine
    while True:
        with E.state_section():
            v = E.virou
            r = under(v)
            if r is not FECHA or v is None:
                return r
            E.take_switch(v)
        x = fecha_virada(A, v)
        if closed is not None:
            r = closed(x)
            if r is not FECHA:
                return r


def fecha_virada(A, virada):
    """Com a fila_lock, e com a virada ja tirada do motor (o E.virou limpo sob o _qlock): a entrada dela sai da fila, o
    que saiu entra no Anterior e a marca do prato parado sai, sem soltar a trava. O Proxima ou o fim do disco que
    chegar logo depois espera, guarda o disco da virada depois dele e marca o prato depois. Volta a entrada (None se
    ela ja tinha saido)."""
    sai, entrou, tag = virada
    x = next((y for y in A.fila if y["qid"] == tag), None)
    if x:
        A.remove_from_queue(x)
    A.save_history(entrou["id"], tr=sai)
    A.parado_sem_fila = None
    return x


def avanca(A, virada=None, historico=True, na_tela=False, visto=None, entrada=None, pular=False, cede=False,
           grupo=None):
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
    fila); nos dois casos ela sai da fila. grupo: o Proximo (comandos.Proximo) que anota a reserva que fez ou espera.
    Uma reserva continua em curso ate resolver, mesmo depois de a troca dela publicar a linha nova (Reserva.viva)."""
    E = A.engine
    if virada is not None:
        with A.fila_lock:  # only this switch: whoever comes after (the watcher, another advance) won't close it again
            return concilia(A, lambda v: FECHA if v is virada else None, closed=lambda x: x)
    em_curso = r = None
    if not cede:
        # a reserva de outro ja em curso nesta linha (o vigia trocando o disco, com a fila_lock na mao): quem chega
        # espera o resultado dela, sem disputar a fila_lock e reservar a seguinte depois
        with E.state_section():
            if grupo is not None and grupo.r is not None:
                r0, vivo = grupo.r, True  # o avanco que ja e deste grupo (mesmo resolvido): ele nao troca de avanco
            else:
                r0 = A.reserva
                vivo = (r0 is not None and r0.viva(E)
                        and (visto is None or (visto.deck is r0.deck and visto.linha == r0.linha)))
                if vivo and grupo is not None:
                    grupo.liga(r0)
        if vivo:
            return r0.espera()

    def reserve(v):  # under the _qlock, with the pending switch v (concilia)
        nonlocal em_curso, r
        if grupo is not None and grupo.r is not None:
            em_curso = grupo.r  # o avanco que outro fez para este Proximo enquanto ele chegava (antes da virada)
            return _CONTINUE_ADVANCE
        if v is not None:
            if pular and grupo is not None:
                grupo.deck, grupo.linha = E.line()  # quem chega agora junta neste, que concilia
                if any(y["qid"] == v[2] for y in A.fila):
                    grupo.virada = v  # e o avanco dele e a virada: outra reserva nesta linha nao o liga
            return FECHA  # o Anterior guarda primeiro o que saiu nela
        if visto is not None and not E.on_line(visto):
            return CEDEU
        em_curso = A.reserva
        if em_curso is not None and not em_curso.viva(E):
            em_curso = None
        if em_curso is None:
            x = entrada if entrada is not None else (A.fila[0] if A.fila else None)
            if x is None or not any(y is x for y in A.fila):
                if grupo is not None:
                    grupo.resolve(None)  # o Proximo que nao tem o que tocar ja decidiu: ninguem o liga
                return None
            r = A.reserva = Reserva(*E.line(), x)
            E.drop_prepared()  # a preparada sai: o motor nao vira para ela no meio do avanco
            p = A.proximo  # o Proximo que chegou nesta linha e ainda nao reservou: este avanco e o dele
            if (p is not None and p is not grupo and p.r is None and p.virada is None
                    and not p.feita.is_set() and E.on_line(p)):
                p.liga(r)
        if grupo is not None:
            grupo.liga(em_curso or r)
        return _CONTINUE_ADVANCE
    with A.fila_lock:
        # sem a entrada (ja saiu da fila), o Proximo segue para a primeira
        res = concilia(A, reserve, closed=lambda x: x if pular and x is not None else FECHA)
        if res is not _CONTINUE_ADVANCE:
            return res
    if em_curso is not None:
        return CEDEU if cede else em_curso.espera()
    try:
        tocou = A.tocar_entrada(r.x, historico=historico, entrada=r.x, reserva=r)
    except Exception as ex:  # nos vigias, entrada quebrada nao trava a fila
        if r.feita.is_set() and r.entrada is r.x:  # tocou: o que falhou veio depois (a gravacao da posicao)
            print(f"queue: {r.x.get('title')!r} played, but then: {ex}", file=sys.stderr, flush=True)
            return r.x
        with A.fila_lock:
            outra = A.reserva
            if outra is None or outra is r or outra.x is not r.x:  # a entrada de outra reserva em curso fica
                A.remove_if_queued(r.x)
            A.release_reservation(r, None)
        if not na_tela:
            raise
        E.set_error(i18n.msg("server.queue.playFailed", "Couldn't play \"{title}\" from the queue ({reason}).",
                             title=r.x.get("title") or "?", reason=i18n.motivo(ex, 120)))
        return r.x
    if not tocou:  # a reserva foi invalidada no meio (o prato trocou, ou a entrada saiu da fila)
        with A.fila_lock:
            A.release_reservation(r, None)
        return CEDEU if cede else None
    return r.x


def pular(A):
    """O Proxima: a primeira da fila toca agora; logo depois de uma virada da passagem ainda nao conciliada, a virada e
    o avanco, e volta a entrada que acabou de entrar. Os Proximos sobrepostos (o segundo chega antes de o primeiro
    voltar, mesmo preso na fila_lock enquanto o primeiro troca o disco) dividem o mesmo avanco, se o prato ainda e a
    linha dele (ou a que a reserva dele publicou): um so toca, e os outros esperam o resultado dele, sem trava nenhuma.
    O avanco ja em curso que o Proximo encontra (o do fim do disco) e a virada pendente que ele ve sao o avanco dele; o
    prato que muda de linha antes de ele reservar fica como esta se trocou de disco (o Parar), e com o mesmo disco (um
    seek) o Proximo segue. Volta a entrada, ou None com a fila vazia (ou o avanco que nao tocou)."""
    E = A.engine
    v = vx = faixa = None
    with A.proximo_lock, E.state_section():
        p = A.proximo
        junta = p is not None and p.junta(E)
        if not junta:  # o primeiro desta linha (o de outra linha, de antes de um Parar, segue sozinho)
            p = A.proximo = Proximo(*E.line())
            faixa = E.track
            r0 = A.reserva
            if r0 is not None and r0.viva(E):
                p.liga(r0)  # o avanco de outro ja em curso nesta linha (o fim do disco): este Proximo e o dele
            elif E.virou is not None:  # a virada que este Proximo viu e o avanco dele, mesmo se o vigia conciliar antes
                vx = next((y for y in A.fila if y["qid"] == E.virou[2]), None)
                if vx is not None:  # sem a entrada dela na fila, o avanco dele e o da primeira, como sem virada
                    v = p.virada = E.virou
    if junta:
        return p.espera()
    x = None
    try:
        if p.r is not None:
            x = p.r.espera()
        elif vx is not None:
            x = avanca(A, virada=v) or vx
        else:
            x = avanca(A, pular=True, grupo=p, visto=p)  # o prato que mudou de linha no meio (o Parar) fica
            if x is CEDEU:
                with A.proximo_lock, E.state_section():  # o mesmo disco no mesmo deck numa linha nova (um seek): o Proximo
                    agora = E.line()
                    de_novo = faixa is not None and E.track is faixa and agora.deck is p.deck  # ainda vale
                    if de_novo:
                        p.linha = agora.linha  # e o grupo passa para a linha do seek (quem chega agora junta)
                x = avanca(A, pular=True, visto=p, grupo=p) if de_novo else None
                if x is CEDEU:
                    x = None
        return x
    finally:
        with A.proximo_lock, E.state_section():
            if A.proximo is p:
                A.proximo = None
            p.resolve(x)


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
        A.close_switches()
        cap = A.engine.stop()
        if A.reserva is not None:
            A.release_reservation(A.reserva, None)  # quem esperava o avanco desta linha nao espera mais
        if cap.track is not None:
            A.save_history(tr=cap.track)
        return cap
    A.remember_pos(A.with_engine(para))  # a fila_lock e o _lock do motor, sem prender a leitura do estado


def ir_para(A, t):
    """O disco do prato a partir de t segundos."""
    A.engine.seek(t)


def volume(A, v, save=True):
    """O volume da musica (de 0 a 1; fora disso, o limite), gravado sozinho: o resto do som fica como esta gravado.
    save=False: whoever calls writes it (the /api/settings saves the whole sound config right after). Volta o do
    motor."""
    v = max(0.0, min(1.0, float(v)))
    A.engine.vol = v
    if save:
        A.grava_cfg(vol=v)
    return A.engine.vol
