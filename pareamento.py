"""O pareamento do celular. O PC (quem fala pelo 127.0.0.1) mexe em tudo; um aparelho da rede de casa so mexe
depois de provar que alguem viu a tela do PC: o botao Celular mostra um codigo de 6 numeros e um QR com o link que ja
leva o codigo. O codigo vale CODIGO_S e uma vez so, e morre com ERROS_MAX tentativas erradas (ai so o PC gera outro: sem
isso, quem estivesse na rede podia tentar ate acertar). Pareado, o aparelho ganha uma chave num cookie e fica ate ser
desconectado no PC. O celulares.json guarda so o hash da chave. Tudo aqui roda no loop do aiohttp (as rotas sao
async), entao nao ha trava."""
import functools
import hashlib
import json
import secrets
import sys
import time
from datetime import datetime

import segno

from pastas import save_json

COOKIE = "vitrola_celular"
COOKIE_S = 400 * 86400  # o Chrome nao guarda cookie por mais que isso: cada abertura do tema renova
CODIGO_S = 300
ERROS_MAX = 5
VISTO_SALVA_S = 300  # o "usado por ultimo" vai para o disco no maximo a cada isso
CAMPOS = ("id", "hash", "nome", "desde", "visto")
SO = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Mac OS", "Mac"),
      ("Linux", "Linux"))  # o iPhone antes do Mac: o dele diz "like Mac OS X"
NAVEGADOR = (("SamsungBrowser", "Samsung Internet"), ("EdgA", "Edge"), ("Edg/", "Edge"), ("OPR", "Opera"),
             ("FxiOS", "Firefox"), ("Firefox", "Firefox"), ("CriOS", "Chrome"), ("Chrome", "Chrome"),
             ("Safari", "Safari"))  # o Chrome antes do Safari, e cada um dos outros antes do Chrome: todos dizem Safari


def nome_do_aparelho(ua):
    """O nome do aparelho na tela do PC ("Android · Chrome", "iPhone · Safari"): o bastante para saber qual e qual
    (o Chrome do Android nao diz mais o modelo)."""
    so = next((n for m, n in SO if m in ua), "Aparelho")
    nav = next((n for m, n in NAVEGADOR if m in ua), None)
    return f"{so} · {nav}" if nav else so


@functools.lru_cache(maxsize=4)
def qr(texto):
    """As linhas do QR de texto, de cima para baixo, com "1" no modulo escuro; sem a margem, que o tema desenha."""
    q = segno.make(texto, error="m", micro=False)
    return ["".join("1" if m else "0" for m in linha) for linha in q.matrix_iter(border=0)]


def _hash(chave):
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()


def _agora():
    return datetime.now().isoformat(timespec="seconds")


class Pareamento:
    def __init__(self, path):
        self.path = path
        self.aparelhos = self._le()
        self.por_hash = {a["hash"]: a for a in self.aparelhos}
        # os prazos pelo relogio monotonic: o Windows acertando a hora (ao acordar o PC) nao vence nem estica o codigo
        self.codigo, self.vale_ate, self.erros = None, 0.0, 0
        self.queimado = False  # morreu de tanta tentativa errada: so o outro_codigo traz um novo
        self.salvo_em = float("-inf")  # o primeiro "usado agora" ja vai para o disco

    def _le(self):
        """Os pareados do disco. O arquivo estragado (editado a mao, disco com problema) nao impede o app de abrir:
        a lista comeca vazia, e cada celular pareia de novo, coisa de segundos."""
        if not self.path.exists():
            return []
        try:
            lista = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(lista, list) and all(isinstance(a, dict) and set(CAMPOS) <= a.keys() for a in lista):
                return lista
        except (OSError, ValueError):  # o ValueError cobre o JSON quebrado e o texto fora do UTF-8
            pass
        print(f"celular: {self.path.name} ilegivel; os celulares pareiam de novo", file=sys.stderr, flush=True)
        return []

    def _salva(self):
        save_json(self.path, self.aparelhos)
        self.salvo_em = time.monotonic()

    def _novo(self):
        self.codigo = f"{secrets.randbelow(10 ** 6):06d}"
        self.vale_ate, self.erros, self.queimado = time.monotonic() + CODIGO_S, 0, False

    def codigo_atual(self):
        """(codigo, segundos que ainda vale) para a tela do PC. O vencido e o usado dao lugar a outro sozinhos;
        o queimado, nao: (None, 0)."""
        if self.queimado:
            return None, 0
        if self.codigo is None or time.monotonic() >= self.vale_ate:
            self._novo()
        return self.codigo, round(self.vale_ate - time.monotonic())

    def outro_codigo(self):
        self._novo()

    def parear(self, codigo, nome):
        """(chave, None) se o codigo confere, e o codigo deixa de valer; (None, "errado" ou "queimado") se nao."""
        if self.queimado:
            return None, "queimado"
        if self.codigo is None or time.monotonic() >= self.vale_ate:
            return None, "errado"
        if not secrets.compare_digest(codigo, self.codigo):
            self.erros += 1
            if self.erros >= ERROS_MAX:
                self.codigo, self.queimado = None, True
                return None, "queimado"
            return None, "errado"
        self.codigo = None
        chave = secrets.token_urlsafe(32)
        a = {"id": secrets.token_hex(4), "hash": _hash(chave), "nome": nome, "desde": _agora(), "visto": _agora()}
        self.aparelhos.append(a)
        self.por_hash[a["hash"]] = a
        self._salva()
        return chave, None

    def vale(self, chave):
        """A chave e de um aparelho pareado. Chamado a cada tick do SSE: so olha, nao grava."""
        return bool(chave) and _hash(chave) in self.por_hash

    def confere(self, chave):
        """Como o vale, e marca o aparelho como usado agora."""
        a = self.por_hash.get(_hash(chave)) if chave else None
        if a is None:
            return False
        a["visto"] = _agora()
        if time.monotonic() - self.salvo_em > VISTO_SALVA_S:
            self._salva()
        return True

    def desconecta(self, aid):
        a = next((x for x in self.aparelhos if x["id"] == aid), None)
        if a is None:
            return False
        self.aparelhos.remove(a)
        del self.por_hash[a["hash"]]
        self._salva()
        return True

    def publico(self):
        return [{k: a[k] for k in CAMPOS if k != "hash"} for a in self.aparelhos]
