"""Os textos da interface em cada lingua (o plano esta no I18N.md do ritmelli-server). Cada tema que tem a pasta i18n/
guarda la um i18n_<lingua>.properties por lingua; o servidor le os da lingua de quem abre a pagina e os do ingles (a
reserva) e poe os dois na pagina, no lugar do MARCA, antes de qualquer script do tema. O tema le em I18N_DADOS. O
servidor nao escreve frase para quem usa: manda a mensagem (msg), com a chave que o tema traduz.

O formato do .properties: uma linha por texto, chave=valor (separados pelo primeiro =, sem o espaco em volta); # ou !
no comeco da linha e comentario; UTF-8 com a acentuacao direto no arquivo; \\n e quebra de linha, \\\\ e a barra e
\\ (barra e espaco) e um espaco que conta, para o valor que comeca ou termina com espaco."""
import json
import re
import sys
from pathlib import Path

LINGUAS = ("en", "pt_BR")
RESERVA = "en"
# ate o PR 7 do I18N.md a lingua do navegador nao conta: todo mundo ve portugues, fora o ?lang= dos testes. Assim uma
# versao publicada no meio da traducao nunca mostra metade da tela em ingles
DETECTA = False
PADRAO = "pt_BR"
MARCA = "<!-- i18n -->"


def ler(caminho):
    """As chaves e os valores de um .properties, na ordem do arquivo. Linha sem = ou chave repetida e erro: o arquivo
    quebrado aparece no dev/testa_i18n.py, e nao como texto sumido na tela."""
    textos = {}
    # utf-8-sig: o BOM que um editor do Windows ponha no comeco nao vira parte da primeira chave
    for n, linha in enumerate(Path(caminho).read_text(encoding="utf-8-sig").splitlines(), 1):
        s = linha.lstrip()
        if not s.strip() or s[0] in "#!":
            continue
        chave, sep, valor = s.partition("=")
        chave = chave.strip()
        if not sep or not chave:
            raise ValueError(f"{caminho}:{n}: expected key=value")
        if chave in textos:
            raise ValueError(f"{caminho}:{n}: duplicate key {chave!r}")
        # o espaco de fora nao conta, menos o escapado (\ ), que o desescape vira espaco
        valor = re.sub(r"(?<!\\)\s+$", "", valor.lstrip())
        textos[chave] = re.sub(r"\\(.)", lambda m: "\n" if m[1] == "n" else m[1], valor)
    return textos


def lingua_de(codigo):
    """A lingua que temos para um codigo do navegador ou do ?lang= (pt-BR, pt_PT, en-US...), ou None."""
    c = (codigo or "").strip().lower()
    if c.startswith("pt"):
        return "pt_BR"
    if c.startswith("en"):
        return "en"
    return None


def preferidas(accept_language):
    """Os codigos do cabecalho Accept-Language na ordem de preferencia (o q mais alto primeiro; empate, a ordem dele)."""
    itens = []
    for i, parte in enumerate((accept_language or "").split(",")):
        codigo, _, params = parte.strip().partition(";")
        q = 1.0
        if (m := re.search(r"q\s*=\s*([0-9.]+)", params)):
            try:
                q = float(m[1])
            except ValueError:
                q = 0.0
        if codigo.strip() and q > 0:
            itens.append((-q, i, codigo.strip()))
    return [c for _, _, c in sorted(itens)]


def escolher(pedida=None, accept_language=""):
    """A lingua da pagina: a do ?lang=, se for uma que temos; senao (com o DETECTA) a primeira que temos na
    preferencia do navegador, ou o ingles; sem o DETECTA, o PADRAO."""
    if (lingua := lingua_de(pedida)):
        return lingua
    if not DETECTA:
        return PADRAO
    for codigo in preferidas(accept_language):
        if (lingua := lingua_de(codigo)):
            return lingua
    return RESERVA


def arquivo(pasta, lingua):
    return Path(pasta) / f"i18n_{lingua}.properties"


def dados(pasta, lingua):
    """O que vai para a pagina: a lingua, os textos dela e os do ingles, que o tema usa quando falta uma chave."""
    reserva = ler(arquivo(pasta, RESERVA))
    textos = reserva if lingua == RESERVA else ler(arquivo(pasta, lingua))
    return {"lingua": lingua, "textos": textos, "reserva": reserva}


def injeta(html, pasta, lingua):
    """O html do tema com os textos no lugar do MARCA. Tema sem o MARCA ou sem a pasta i18n/ sai como veio. Arquivo
    quebrado nao derruba a pagina: vai sem textos (o tema mostra as chaves) e o erro sai no log."""
    if MARCA not in html or not Path(pasta).is_dir():
        return html
    try:
        d = dados(pasta, lingua)
    except (OSError, ValueError) as ex:
        print(f"i18n: could not read the texts in {pasta} ({ex})", file=sys.stderr, flush=True)
        d = {"lingua": lingua, "textos": {}, "reserva": {}}
    # o < escapado: um texto com </script> nao fecha o script da pagina
    js = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return html.replace(MARCA, f"<script>window.I18N_DADOS = {js};</script>", 1)


def versao(pasta):
    """Um carimbo dos arquivos de texto de um tema, para o ETag da pagina mudar quando um deles muda."""
    try:
        return "-".join(str(arquivo(pasta, x).stat().st_mtime_ns) for x in LINGUAS)
    except OSError:
        return "0"


# --- as mensagens do servidor (o formato no API.md, "Mensagem")

def msg(chave, texto, **params):
    """Uma mensagem que a tela pode mostrar: a chave e os params, que o tema traduz pelos arquivos dele, e o texto em
    ingles, para o log e para quem chama a API sem tema. O texto e um modelo com os {param} da chave. Um param pode ser
    outra mensagem (o motivo que e uma Recusa): o tema traduz as duas. O dev/testa_i18n.py confere que todo tema com
    i18n/ tem cada chave server.* daqui, com os mesmos params, e que cada chamada passa os params do texto."""
    return {"key": chave, "params": params,
            "text": texto.format(**{k: v["text"] if isinstance(v, dict) else v for k, v in params.items()})}


def so_texto(texto):
    """A mensagem que nenhuma tela mostra (o pedido feito errado, a rota que so outro programa chama): so o texto, em
    ingles."""
    return {"text": texto}


class Recusa(ValueError):
    """Um erro com a mensagem pronta para a tela (msg), para quem chama mostrar como veio. str() e o texto em ingles."""

    def __init__(self, chave, texto, **params):
        self.msg = msg(chave, texto, **params)
        super().__init__(self.msg["text"])


def motivo(ex, n=160):
    """O motivo de um erro para ir num param: a mensagem dele, se e uma Recusa (o tema traduz), senao o texto dele."""
    return ex.msg if isinstance(ex, Recusa) else str(ex)[:n]
