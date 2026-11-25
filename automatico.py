"""O Automatico: com ele ligado, a fila nunca acaba. O ultimo disco que o usuario escolheu e a semente, e as parecidas
dela (o radio do YouTube Music, pelo mix_do do App) ficam no fim do A seguir, em ordem de andamento (andamento.py). O
vigia das parecidas (_vigia_auto, uma _volta_auto a cada 0,5 s) busca o Mix e monta a fila; o do andamento
(_vigia_andamento) mede cada disco uma vez so e troca a parecida que veio como video pela versao so de audio.

O estado do Automatico mora no App (auto, semente, mix, mix_base, ponte, mix_buscando, mix_falhou, mix_seq, fora,
fora_musica, andamentos, andamentos_versao, versoes), porque a leitura do estado, o save_cfg e o _recusar o leem: o
Automatico o le e o muda pelo app, sob a app.fila_lock, na ordem das travas do comandos.py. O mix_do chega resolvido a
cada chamada (o teste troca o do App). As constantes e as funcoes de musica (chaves_musica, autores, mesma_faixa)
continuam no server.py, lidas pelo modulo do App (srv)."""
import json
import subprocess
import sys
import threading
import time
import uuid

import andamento as an
import comandos as cmd
import engine as eng


class Automatico:
    def __init__(self, app, mix_do):
        self.app = app
        self.mix_do = mix_do
        # o server.py do App: o __main__ quando ele roda direto, e nao uma segunda copia importada daqui
        self.srv = sys.modules[type(app).__module__]

    def ligar_auto(self, on):
        """Desligar tira as parecidas da fila; ligar enche na proxima volta do vigia."""
        A = self.app
        with A.fila_lock:
            A.auto = bool(on)
            if not A.auto:
                for x in [x for x in A.fila if x.get("auto")]:
                    A._tirar(x)

    def _busca_mix(self, base):
        A, S = self.app, self.srv
        try:
            lista = self.mix_do(base)
        except Exception as ex:  # noqa: BLE001 - sem Mix, o Automatico espera e tenta de novo
            print(f"auto: the Mix of {base} failed: {S.yt_msg(ex)}", file=sys.stderr, flush=True)
            lista = None
        with A.fila_lock:
            A.mix_buscando = False
            if lista is None:
                A.mix_falhou = time.time()
            elif base == A.mix_base:  # a semente nao trocou no meio
                for m in lista:
                    A.mix_seq += 1
                    m["ordem"] = A.mix_seq
                    if m["youtube_id"] in A.versoes:  # a versao de audio ja procurada antes
                        self._poe_versao(m, A.versoes[m["youtube_id"]])
                A.mix = lista

    def _janela(self, pool, n):
        """As de pool (na ordem do Mix) que cabem na proxima AUTO_JANELA_S, e pelo menos n."""
        S = self.srv
        out, soma = [], 0.0
        for c in pool:
            if len(out) >= n and soma >= S.AUTO_JANELA_S:
                break
            out.append(c)
            soma += c.get("duration") or 0
        return out

    def _livres(self):
        """Com fila_lock: as do Mix que podem entrar, na ordem do Mix: nem tocaram nesta sessao, nem o usuario tirou,
        nem estao na fila, nem sao a mesma musica de uma dessas ou de uma anterior do Mix."""
        A, S = self.app, self.srv
        vistas = set(A.fora_musica)
        for x in A.fila:
            vistas |= S.chaves_musica(x)
        na_fila = {x.get("youtube_id") for x in A.fila}
        out = []
        for m in sorted(A.mix or [], key=lambda c: c.get("ordem", 0)):
            ks = S.chaves_musica(m)
            if m["youtube_id"] in A.fora or m["youtube_id"] in na_fila or ks & vistas:
                continue
            vistas |= ks
            out.append(m)
        return out

    def _presa(self):
        """Com fila_lock: a primeira da fila nao troca mais (a passagem para ela ja esta sendo preparada, ou falta
        pouco para isso, ou um avanco reservado em curso vai toca-la)."""
        A = self.app
        if not A.fila:
            return False
        e, q = A.engine, A.fila[0]["qid"]
        tr = e.track
        dur = tr.get("duration") if tr else None
        r = A.reserva
        return bool((dur and dur - e.pos <= eng.TRANS_PREP_S + 15) or e.pronto_tag == q
                    or (A.preparando is not None and A.preparando[1] == q)
                    or (r is not None and not r.feita.is_set() and r.x is A.fila[0]))

    def _ordena_auto(self):
        """Com fila_lock: as parecidas do fim do A seguir em ordem de andamento (andamento.ordena: subindo no
        circulo das oitavas a partir do fim do disco antes delas), escolhidas entre as que ja estao la e as do Mix
        ainda nao usadas, so as da proxima AUTO_JANELA_S do Mix (as mais parecidas com a semente), ate AUTO_FILA. A
        que o usuario arrastou fica onde ele pos, e a primeira da fila fica se a passagem para ela ja vai ser preparada.
        A que sai da fila volta para o Mix. Sem medida ainda, fica a ordem do Mix; cada medida que chega ordena de
        novo. Volta quantas entraram."""
        A, S = self.app, self.srv
        k = len(A.fila)
        while k and A.fila[k - 1].get("auto") and not A.fila[k - 1].get("fixa"):
            k -= 1
        if k == 0 and self._presa():
            k = 1
        bloco = A.fila[k:]
        n = S.AUTO_FILA - sum(1 for x in A.fila[:k] if x.get("auto"))
        mix = self._livres()
        janela = self._janela(sorted(bloco + mix, key=lambda c: c.get("ordem", 0)), n)
        # o andamento do fim do disco antes delas: o ultimo da fila que fica, ou o do prato
        antes = list(reversed(A.fila[:k])) + ([A.engine.track] if A.engine.track else [])
        t = A._tempo(antes[0]) if antes else None
        cursor, salto = None, False
        if t:
            salto = t.get("fim") is None  # sem batida firme no fim dele: a passagem para a primeira vai ser de volume
            cursor = t.get("fim") or t.get("ini")
            for y in antes[1:]:  # nem o comeco dele: o circulo segue do ultimo andamento conhecido
                if cursor is not None:
                    break
                ty = A._tempo(y)
                cursor = ty and (ty.get("fim") or ty.get("ini"))
        escolha = an.ordena(cursor, salto, janela, A._tempo, max(0, n), S.autores, S.autores(antes[0]) if antes else frozenset())
        na_bloco = {x["qid"] for x in bloco}
        nova, entrou = [], 0
        for c in escolha:
            if c.get("qid") in na_bloco:
                nova.append(c)
            else:
                nova.append(dict(c, id=None, url=None, job=None, qid=uuid.uuid4().hex[:8],
                                 auto=True, auto_de=A.semente["title"]))
                entrou += 1
        if [x["qid"] for x in nova] == [x["qid"] for x in bloco]:
            return 0
        usadas = {c["youtube_id"] for c in escolha}
        if A.mix is not None:
            A.mix = sorted([m for m in mix if m["youtube_id"] not in usadas]
                           + [x for x in bloco if x["youtube_id"] not in usadas], key=lambda c: c.get("ordem", 0))
        with A.engine._qlock:
            A.fila[k:] = nova
            if A.fila_ordem is not None:
                A.fila_ordem = [x for x in A.fila_ordem if x["qid"] not in na_bloco] + nova
            A._confere_preparo_sob()
        return entrou

    def _vigia_auto(self):
        """Com o Automatico ligado, a fila nunca acaba (como no YouTube Music): o ultimo disco que
        o usuario escolheu (qualquer um que o Automatico nao pos) e a semente, e o radio dela (mix_do)
        mantem AUTO_FILA parecidas no fim do A seguir. Semente nova troca as parecidas; o que ja
        tocou nesta sessao nao volta; quando o Mix da semente acaba, segue do Mix da ultima
        parecida que tocou. As parecidas vao em ordem de andamento (_ordena_auto). Cada volta e o _volta_auto."""
        visto, sinal = None, None
        while True:
            time.sleep(0.5)
            visto, sinal = self._volta_auto(visto, sinal)

    def _volta_auto(self, visto=None, sinal=None):
        """Uma volta do _vigia_auto. visto: o youtube_id do prato na volta de antes; sinal: o que a ordem por
        andamento viu da ultima vez que ordenou. Volta os dois da proxima volta."""
        A, S = self.app, self.srv
        e = A.engine
        tr = e.track
        yid = tr.get("youtube_id") if tr else None
        if yid and yid != visto:
            visto = yid
            with A.fila_lock:
                A.fora.add(yid)
                A.fora_musica |= S.chaves_musica(tr)
                if tr.get("auto"):
                    A.ponte = yid
                else:
                    A.semente = {"youtube_id": yid, "title": tr.get("title")}
                    A.mix, A.mix_base = None, yid
                    for x in [x for x in A.fila if x.get("auto")]:
                        A._tirar(x)
        base, entrou = None, 0
        with A.fila_lock:
            if not A.auto or not A.semente:
                return visto, sinal
            falta = S.AUTO_FILA - sum(1 for x in A.fila if x.get("auto"))
            if falta > 0 and not A.mix_buscando:
                if not A.mix and A.mix is not None and A.ponte and A.ponte != A.mix_base:
                    A.mix, A.mix_base = None, A.ponte  # o Mix da semente acabou
                if A.mix is None and time.time() - A.mix_falhou >= S.AUTO_ESPERA_S:
                    A.mix_buscando, base = True, A.mix_base
            # a ordem por andamento se refaz quando muda a fila, o prato, o Mix ou chega uma medida
            agora = (id(tr), tuple(x["qid"] for x in A.fila), A.andamentos_versao, A.mix_seq,
                     self._presa())
            if agora != sinal and (A.mix or any(x.get("auto") for x in A.fila)):
                entrou = self._ordena_auto()
                sinal = (id(tr), tuple(x["qid"] for x in A.fila), A.andamentos_versao, A.mix_seq,
                         self._presa())
        if base:
            threading.Thread(target=self._busca_mix, args=(base,), daemon=True).start()
        # o disco acabou antes de chegar parecida (o Mix ainda vinha): a primeira toca agora; e tambem a que ja estava
        # la quando a volta de antes cedeu a outro avanco que nao a tocou
        if (entrou or A.fila) and tr is not None and tr is A.parado_sem_fila:
            cap = e.captura()
            if cap.track is tr and cap.status == "ended":
                x = cmd.avanca(A, na_tela=True, visto=cap, cede=True)
                if x is not None and x is not cmd.CEDEU:  # so o avanco que tocou tira a marca do prato parado
                    A.parado_sem_fila = None
        return visto, sinal

    def _poe_versao(self, x, v):
        """A parecida passa a tocar a versao so de audio v (sem versao, fica o video e so a marca de procurada)."""
        S = self.srv
        x["audio"] = True
        if v:
            x.update(v, video=x.get("video") or x["youtube_id"], thumb=S.thumb(v["youtube_id"]), tipo="ATV")

    def versao_audio(self, x):
        """A versao so de audio (a faixa do album no YouTube Music) da parecida que veio como video, pela busca de
        musicas com nome e artista: {"youtube_id", "duration", "title", "channel"} da primeira das 3 que e a mesma
        faixa (mesma_faixa), ou None (musica so do YouTube, ou a busca so traz outras)."""
        S = self.srv
        for r in S.fora.pede("musicas", q=S.busca_de(x)):
            if r.get("videoId") and S.YT_ID.match(r["videoId"]) and S.mesma_faixa(x, r):
                artistas = ", ".join(a["name"] for a in r.get("artists") or [] if a.get("name"))
                return {"youtube_id": r["videoId"],
                        "duration": r.get("duration_seconds") or S.segundos(r.get("duration")),
                        "title": r.get("title") or x.get("title"), "channel": artistas or x.get("channel")}
        return None

    def _troca_audio(self, vid, v):
        """Com fila_lock: a parecida do video vid (no Mix e na fila; a primeira da fila fica se ja esta presa)
        passa para a versao de audio v."""
        A = self.app
        presa = A.fila[0] if A.fila and self._presa() else None
        for x in list(A.mix or []) + [y for y in A.fila if y.get("auto") and y is not presa]:
            if x.get("youtube_id") == vid and not x.get("audio"):
                self._poe_versao(x, v)

    def _a_medir(self):
        """Com fila_lock: o que falta fazer, pela ordem em que faz falta: ("medir", disco) sem andamento ou
        ("audio", parecida) sem a versao de audio procurada; o do prato, o ultimo que o usuario pos antes das parecidas
        e as parecidas da janela (as da fila e as do Mix), na ordem do Mix, cada uma com a versao antes da medida.
        (None, None) sem nada."""
        A, S = self.app, self.srv
        k = len(A.fila)
        while k and A.fila[k - 1].get("auto"):
            k -= 1
        mix = self._livres()
        pool = sorted([x for x in A.fila[k:]] + mix, key=lambda c: c.get("ordem", 0))
        agora = time.time()
        janela = self._janela(pool, S.AUTO_FILA)
        parecidas = {id(c) for c in janela}
        for x in [A.engine.track] + A.fila[k - 1:k] + janela:
            vid = x.get("youtube_id") if id(x) in parecidas else None
            if (vid and not x.get("audio") and vid not in A.versoes
                    and agora - A.andamento_falhou.get(f"audio:{vid}", 0.0) >= S.ANDAMENTO_ESPERA_S):
                return "audio", dict(x)
            c = A.chave_andamento(x)
            if c and c not in A.andamentos and agora - A.andamento_falhou.get(c, 0.0) >= S.ANDAMENTO_ESPERA_S:
                return "medir", dict(x)
        return None, None

    def _mede_andamento(self, x):
        """{"ini", "fim"} do disco pelo andamento.py num processo a parte, com prioridade baixa: da prateleira, o
        arquivo; senao o stream que toca (so os pedacos que a medida le, ~1 MB), com o endereco pedido ao YouTube la
        dentro: o yt-dlp aqui segurava o interpretador do servidor em rajadas e o audio estalava (22/10: 15
        parecidas medidas na primeira musica do radio). None sem como ler."""
        A, S = self.app, self.srv
        it = (A.lib.get(x["id"]) if x.get("id") else None) or \
             (A.lib.by_youtube(x["youtube_id"]) if x.get("youtube_id") else None)
        if it and (S.LIB / it["file"]).exists():
            if not it.get("duration"):
                return None
            pedido = {"fonte": str(S.LIB / it["file"]), "dur": it["duration"]}
        elif x.get("youtube_id") and not A.mock:  # no --mock, so o arquivo: o stream iria a rede sozinho (#128)
            pedido = {"yt": A.alvo_yt(x["youtube_id"]), "opts": A.opts_stream(), "dur": x.get("duration")}
        else:
            return None
        p = subprocess.run(S.auxiliar("--andamento"),
                           input=json.dumps(pedido), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180, cwd=str(S.HERE),
                           creationflags=eng.NO_WINDOW | S.ABAIXO_DO_NORMAL, startupinfo=eng.sem_cursor())
        r = json.loads(p.stdout.strip().splitlines()[-1])
        if r and r.get("erro"):
            raise RuntimeError(r["erro"])
        return {"ini": r.get("ini"), "fim": r.get("fim")} if r else None

    def _vigia_andamento(self):
        """Com o Automatico ligado, mede o andamento (_a_medir, _mede_andamento) um disco de cada vez, uma vez so
        por disco (fica no andamentos.json). So depois de o disco do prato ficar ANDAMENTO_APOS_S tocando (pular
        de disco em disco nao le nada; buscar nao mede nunca) e nunca com a passagem sendo planejada (a rede do
        motor e a da medida juntas). Antes da medida, a parecida que veio como video troca pela versao so de
        audio, quando ha (versao_audio). A medida que chega faz o _vigia_auto ordenar de novo."""
        A, S = self.app, self.srv
        prato, desde = None, 0.0
        while True:
            time.sleep(1.0)
            e = A.engine
            tr = e.track
            if (tr and tr.get("id")) != prato:
                prato, desde = tr and tr.get("id"), time.time()
            if not A.auto or not prato or time.time() - desde < S.ANDAMENTO_APOS_S or e.planejando:
                continue
            with A.fila_lock:
                o_que, x = self._a_medir()
            if x is None:
                continue
            if o_que == "audio":
                vid = x["youtube_id"]
                try:
                    v = self.versao_audio(x)
                except Exception as ex:  # noqa: BLE001 - sem a busca, a parecida toca o video
                    print(f"audio: couldn't look up {x.get('title')!r}: {S.yt_msg(ex)}", file=sys.stderr, flush=True)
                    with A.fila_lock:
                        A.andamento_falhou[f"audio:{vid}"] = time.time()
                    continue
                # grava fora da fila_lock (o disco lento nao segura a fila) e so depois aplica, na ordem de antes: a
                # medida entra na memoria mesmo se a gravacao falha; a troca na fila e o andamentos_versao (a nova
                # ordem do Automatico) so vem com a gravacao feita
                with A.fila_lock:
                    versoes = {**A.versoes, vid: v}
                gravou = False
                try:
                    S.save_json(A.versoes_path, versoes)
                    gravou = True
                finally:
                    with A.fila_lock:
                        A.versoes[vid] = v
                        if gravou:
                            self._troca_audio(vid, v)
                            A.andamentos_versao += 1
                print(f"audio: {x.get('title')!r}: " + (f"the audio version {v['youtube_id']} ({v['duration']} s)"
                                                         if v else "only the video"), file=sys.stderr, flush=True)
                continue
            c = A.chave_andamento(x)
            t0 = time.time()
            try:
                r = self._mede_andamento(x)
            except Exception as ex:  # noqa: BLE001 - sem medida, a parecida fica sem andamento (vai para o salto)
                r = None
                print(f"tempo: couldn't measure {x.get('title')!r}: {S.yt_msg(ex)}", file=sys.stderr, flush=True)
            with A.fila_lock:
                if r is None:
                    A.andamento_falhou[c] = time.time()
                    continue
                andamentos = {**A.andamentos, c: r}
            gravou = False
            try:  # fora da fila_lock e antes de valer, como a versao de audio
                S.save_json(A.andamentos_path, andamentos)
                gravou = True
            finally:
                with A.fila_lock:
                    A.andamentos[c] = r
                    if gravou:
                        A.andamentos_versao += 1
            print(f"tempo: {x.get('title')!r}: start {r['ini']}, end {r['fim']} BPM in {time.time() - t0:.1f} s",
                  file=sys.stderr, flush=True)
