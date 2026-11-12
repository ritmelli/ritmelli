"""A atualizacao parcial de um build: so os arquivos que mudaram desde a versao anterior publicada, para o vitrola.iss
montar um setup pequeno (o caminho B do atualizador, pelo proprio Inno).

    python parcial.py --anterior <manifest.json da versao anterior> --app-py <atualizacao.py do app>
                      --app <dist\\vitrola do build> --bin <pasta> [--bin <pasta> ...] --saida <pasta>

Confere a assinatura do manifesto anterior (o manifest.json.sig ao lado dele) com o CHAVES do app e compara, arquivo por
arquivo, o hash dele com o do build, pela mesma lista do manifesto (o fontes do publica.py). A --saida e refeita, com:

- arquivos\\: cada arquivo novo ou mudado, no caminho dele na pasta do app (o vitrola.iss copia tudo para o {app});
- apaga.iss: o [InstallDelete] dos arquivos que a versao anterior tinha e este build nao tem;
- parcial.json: a versao anterior ("de"), os caminhos que a parcial traz ("arquivos") e os que ela apaga ("apaga"),
  para o publica.py por no manifesto.

Sem nada mudado, nao grava o parcial.json, e o monta.ps1 so monta o setup completo. O app so usa a parcial se o que esta
instalado bater com o manifesto novo em tudo que ela nao traz (o atualizacao.py, no repo vitrola): por isso ela serve
tambem a quem esta algumas versoes atras, desde que as bibliotecas nao tenham mudado no meio. Senao, vai o completo.
"""
import argparse
import base64
import json
import shutil
import sys
from pathlib import Path

from Cryptodome.Signature import eddsa

from publica import chaves_do_app, fontes, sha


def confere_anterior(manifesto, chaves):
    """O manifesto anterior como dict, se a assinatura ao lado dele for de uma chave que o app conhece."""
    dados = manifesto.read_bytes()
    try:
        s = json.loads(manifesto.with_name(manifesto.name + ".sig").read_text(encoding="ascii"))
        pub = eddsa.import_public_key(base64.b64decode(chaves[s["chave"]], validate=True))
        eddsa.new(pub, "rfc8032").verify(dados, base64.b64decode(s["assinatura"], validate=True))
    except (OSError, KeyError, TypeError, ValueError) as e:
        sys.exit(f"a assinatura do manifesto anterior ({manifesto}) nao confere: {e}")
    return json.loads(dados)


def inno(caminho):
    """O caminho do app como o Inno quer: barras do Windows, e a chave dobrada (a { abre uma constante)."""
    return "{app}\\" + caminho.replace("/", "\\").replace("{", "{{")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anterior", type=Path, required=True)
    ap.add_argument("--app-py", type=Path, required=True)
    ap.add_argument("--app", type=Path, required=True)
    ap.add_argument("--bin", type=Path, action="append", default=[])
    ap.add_argument("--saida", type=Path, required=True)
    a = ap.parse_args()
    anterior = confere_anterior(a.anterior, chaves_do_app(a.app_py))
    antes = {f["caminho"]: f["sha256"] for f in anterior["arquivos"]}
    agora = fontes(a.app, a.bin)
    traz = [c for c, f in agora.items() if antes.get(c) != sha(f)]
    apaga = sorted(c for c in antes if c not in agora)

    if a.saida.exists():
        shutil.rmtree(a.saida)
    a.saida.mkdir(parents=True)
    if not traz:
        print(f"nada mudou desde a {anterior['versao']}: sem a parcial")
        return
    for c in traz:
        destino = a.saida / "arquivos" / c
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(agora[c], destino)
    linhas = [f"; o parcial.py gera: o que a {anterior['versao']} tinha e este build nao tem"]
    linhas += [f'Type: files; Name: "{inno(c)}"' for c in apaga]
    (a.saida / "apaga.iss").write_text("\n".join(linhas) + "\n", encoding="utf-8-sig")
    (a.saida / "parcial.json").write_text(
        json.dumps({"de": anterior["versao"], "arquivos": traz, "apaga": apaga}, indent=1) + "\n", encoding="utf-8")
    tamanho = sum(agora[c].stat().st_size for c in traz)
    print(f"parcial desde a {anterior['versao']}: {len(traz)} de {len(agora)} arquivos ({tamanho / 2**20:.1f} MB) "
          f"e {len(apaga)} apagados, em {a.saida}")


if __name__ == "__main__":
    main()
