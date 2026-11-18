"""Um manifesto de teste para a atualizacao automatica (o testa-atualizador.ps1): o manifesto do build com outra versao
e o setup num endereco local, assinado por uma chave de teste gerada na hora. Grava o manifest.json e o .sig na --saida e
imprime a chave publica em base64, que o teste poe no HKLM\\SOFTWARE\\Vitrola\\Atualizador (o atualizador.py so le de
la). Sem a parcial: o teste e o do setup completo.

    python manifesto_de_teste.py --manifesto <manifest.json do build> --versao <X.Y.Z> --url <http://...> --saida <pasta>
"""
import argparse
import base64
import json
from pathlib import Path

from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifesto", type=Path, required=True)
    ap.add_argument("--versao", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--saida", type=Path, required=True)
    a = ap.parse_args()
    m = json.loads(a.manifesto.read_text(encoding="utf-8"))
    m["versao"] = a.versao
    m["instalador"]["url"] = a.url
    m.pop("parcial", None)
    dados = (json.dumps(m, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    k = ECC.generate(curve="Ed25519")
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "manifest.json").write_bytes(dados)
    sig = base64.b64encode(eddsa.new(k, "rfc8032").sign(dados)).decode()
    (a.saida / "manifest.json.sig").write_text(json.dumps({"chave": 1, "assinatura": sig}) + "\n", encoding="ascii")
    print(base64.b64encode(k.public_key().export_key(format="raw")).decode())


if __name__ == "__main__":
    main()
