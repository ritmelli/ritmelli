"""Quem pode chamar cada rota do servidor: a tabela (metodo, rota canonica) -> papeis, que o guard do server.py confere
em todo pedido, depois do Host e da Origin. So da biblioteca padrao: o dev/testa_mock.py le a tabela antes de a esteira
instalar as bibliotecas do app.

Os papeis de quem pede:
- "pc": quem conecta pelo 127.0.0.1 (ou ::1) sem o cabecalho do remoto. Pode tudo, inclusive rota fora da tabela;
- "celular": da rede de casa, com a chave do pareamento (pareamento.py) no cookie;
- "publico": da rede de casa, sem chave que valha. So o tema, os arquivos dele e o pareamento;
- "remoto": quem conecta pelo 127.0.0.1 (so o IPv4) com o cabecalho REMOTO e um token de sessao que vale (Remotos). So os
  comandos da lista REMOTO. Cabecalho com token que nao vale (errado, vencido, ou vindo de fora do 127.0.0.1) e 401,
  mesmo do 127.0.0.1: quem manda o cabecalho nunca cai no papel do PC.

A rota e a canonica do aiohttp (/api/library/{iid}, sem o id); o HEAD vale como o GET da mesma rota. Rota fora da
tabela e so do PC: rota nova nasce fechada, e abrir para o celular ou para o remoto e uma linha aqui."""
import secrets
import threading

PAPEIS = ("pc", "celular", "remoto", "publico")
REMOTO = "X-Ritmelli-Remoto"  # o cabecalho do token da sessao remota

PC = frozenset({"pc"})
CELULAR = frozenset({"pc", "celular"})
LIVRE = frozenset({"pc", "celular", "publico"})        # o tema e o pareamento: antes de parear
TAMBEM_REMOTO = frozenset({"pc", "celular", "remoto"})  # os comandos do vocabulario remoto que o tema ja usa
SO_REMOTO = frozenset({"pc", "remoto"})  # os do remoto que o tema nao usa: fechados para o celular

# The routes only the optional module from outside the repo calls. It runs on the PC and connects through 127.0.0.1, so
# it has the "pc" role: the theme never uses these, and they stay closed to the phone and to the remote session. The
# count is held by dev/testa_ganchos.py: a new route for that module goes through the ones already here.
OUT_OF_REPO = (
    ("GET", "/api/tocadas"),   # what has played since the server started
    ("GET", "/api/musica"),    # the YouTube Music search of a spoken request
    ("POST", "/api/aquece"),   # someone started talking: warm up the YouTube connections
)

TABELA = {
    # o tema, os arquivos dele, a galeria e o pareamento
    ("GET", "/"): LIVRE,
    ("GET", "/favicon.ico"): LIVRE,
    ("GET", "/apple-touch-icon.png"): LIVRE,
    ("GET", "/t/{slug}"): LIVRE,
    ("GET", "/t/{slug}/"): LIVRE,
    ("GET", "/t/{slug}/index.html"): LIVRE,
    ("GET", "/t"): LIVRE,                      # os arquivos dos temas (o static do /t/)
    ("GET", "/t/vitrola{resto}"): LIVRE,      # o endereco de antes da troca de nome (o TEMA_DE_ANTES do server.py)
    ("GET", "/api/themes"): LIVRE,
    ("POST", "/api/parear"): LIVRE,

    # o estado: o remoto le para saber o que pode e o que toca
    ("GET", "/api/state"): TAMBEM_REMOTO,
    ("GET", "/api/events"): TAMBEM_REMOTO,

    # o vocabulario remoto: tocar, enfileirar, pular, pausar, retomar, tirar da fila, mover na fila, volume, abaixar e
    # o sinal de teste
    ("POST", "/api/play"): TAMBEM_REMOTO,
    ("POST", "/api/queue"): TAMBEM_REMOTO,
    ("POST", "/api/queue/play"): TAMBEM_REMOTO,
    ("POST", "/api/next"): TAMBEM_REMOTO,
    ("POST", "/api/pause"): TAMBEM_REMOTO,
    ("POST", "/api/resume"): TAMBEM_REMOTO,
    ("DELETE", "/api/queue/{qid}"): TAMBEM_REMOTO,
    ("POST", "/api/queue/move"): TAMBEM_REMOTO,
    ("POST", "/api/volume"): SO_REMOTO,
    ("POST", "/api/abaixa"): SO_REMOTO,
    ("POST", "/api/sinal"): SO_REMOTO,

    # o celular pareado: o que o tema usa nele
    ("GET", "/api/onda/{iid}"): CELULAR,
    ("GET", "/api/library"): CELULAR,
    ("GET", "/api/jobs"): CELULAR,
    ("GET", "/api/search"): CELULAR,
    ("POST", "/api/library"): CELULAR,
    ("PATCH", "/api/library/{iid}"): CELULAR,
    ("DELETE", "/api/library/{iid}"): CELULAR,
    ("DELETE", "/api/queue"): CELULAR,
    ("POST", "/api/prev"): CELULAR,
    ("POST", "/api/toggle"): CELULAR,
    ("POST", "/api/stop"): CELULAR,
    ("POST", "/api/seek"): CELULAR,
    ("POST", "/api/settings"): CELULAR,
    ("GET", "/api/effects"): CELULAR,
    ("POST", "/api/pedal_voz"): CELULAR,
    ("GET", "/api/devices"): CELULAR,
    ("POST", "/api/devices"): CELULAR,
    ("GET", "/api/boas-vindas"): CELULAR,

    # only the module from outside the repo (OUT_OF_REPO), which is the PC
    **dict.fromkeys(OUT_OF_REPO, PC),

    # so o PC
    ("POST", "/api/shutdown"): PC,  # off, the app can only be turned back on from the PC itself
    ("GET", "/api/lan"): PC,
    ("POST", "/api/effects/reload"): PC,
    ("POST", "/api/boas-vindas"): PC,
    ("POST", "/api/janela/foco"): PC,
    ("GET", "/api/metricas"): PC,
    ("POST", "/api/metricas"): PC,
    ("GET", "/api/atualizacao"): PC,
    ("POST", "/api/atualizacao/consultar"): PC,
    ("POST", "/api/atualizacao/baixar"): PC,
    ("POST", "/api/atualizacao/instalar"): PC,
    ("GET", "/api/pareamento"): PC,
    ("POST", "/api/pareamento/codigo"): PC,
    ("DELETE", "/api/pareamento/{aid}"): PC,
}


def papeis(metodo, rota):
    """Quem pode chamar a rota (a canonica, ou None quando nenhuma casou): fora da tabela, so o PC."""
    return TABELA.get(("GET" if metodo == "HEAD" else metodo, rota), PC)


def caps(papel):
    """O que o papel pode fazer: {"papel", "rotas": ["POST /api/play", ...]}, as rotas da API que ele alcanca, em
    ordem. O tema mostra os controles por aqui, no lugar de olhar o endereco."""
    return {"papel": papel, "rotas": sorted(f"{m} {r}" for (m, r), p in TABELA.items()
                                            if papel in p and r.startswith("/api/"))}


class Remotos:
    """Os tokens das sessoes remotas aceitas: um por sessao (secrets.token_urlsafe(32)), que vale enquanto ela dura.
    So na memoria: com o app aberto de novo, nenhum vale."""

    def __init__(self):
        self._tokens = set()
        self._lock = threading.Lock()

    def abre(self):
        """A sessao foi aceita: o token dela."""
        t = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens.add(t)
        return t

    def fecha(self, token):
        """A sessao acabou: o token deixa de valer (inclusive no SSE aberto com ele)."""
        with self._lock:
            self._tokens.discard(token)

    def vale(self, token):
        if not isinstance(token, str) or not token:
            return False
        with self._lock:
            ativos = list(self._tokens)
        ok = False
        for t in ativos:  # sem parar no primeiro: o tempo nao diz qual token chegou perto
            ok |= secrets.compare_digest(t.encode("utf-8"), token.encode("utf-8", "surrogatepass"))
        return ok
