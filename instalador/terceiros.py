"""Os avisos de terceiros do instalador (o TERCEIROS.txt da pasta do app): tudo o que vai junto com a Vitrola, cada um
com o texto da licenca dele. O monta.ps1 roda depois de congelar, com o python do venv do build:

    python terceiros.py --app <dist\\vitrola> --vitrola <repo vitrola> --ffmpeg <pasta> --deno <pasta> --saida <arquivo>

- as bibliotecas Python que o PyInstaller levou: os modulos do PYZ do exe e o que esta na _internal\\, ligados ao pacote
  do pip pelos arquivos que cada pacote instalou no venv. O texto sai dos arquivos de licenca do pacote;
- o Python (o LICENSE.txt da instalacao, que ja traz o OpenSSL, o libffi, o zlib e os outros que vem com ele) e o
  PyInstaller (o bootloader e o comeco do vitrola.exe);
- os modelos e as fontes da _internal\\, com a licenca que esta na mesma pasta;
- o ffmpeg e o Deno da bin\\. A licenca do Deno nao vem no .zip dele: esta em licencas\\.

Um modulo que nao e de nenhum pacote, um pacote sem arquivo de licenca ou um modelo sem licenca ao lado derruba o build:
e para olhar e acrescentar, e nao para sair um instalador faltando aviso.
"""
import argparse
import importlib.metadata as md
import re
import subprocess
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

LICENCAS = Path(__file__).parent / "licencas"
NOME_LICENCA = re.compile(r"(LICEN[CS]E|LICENCA|COPYING|NOTICE|COPYRIGHT|OFL)", re.I)
DADOS_COM_LICENCA = {".onnx", ".woff", ".woff2", ".ttf", ".otf"}


def le(arq):
    return Path(arq).read_text(encoding="utf-8", errors="replace").strip()


def modulos(app):
    """Os nomes de cima de tudo o que o PyInstaller levou: os modulos do PYZ e as pastas e .pyd da _internal\\."""
    pyz = CArchiveReader(str(app / "vitrola.exe")).open_embedded_archive("PYZ.pyz")
    nomes = {n.split(".")[0] for n in pyz.toc}
    for p in (app / "_internal").iterdir():
        if p.is_dir() and not p.name.endswith(".dist-info"):
            nomes.add(p.name)
        elif p.suffix == ".pyd":
            nomes.add(p.name.split(".")[0])
    return nomes


def dono_de_cada_nome():
    """nome de cima (pasta, modulo ou .pyd) -> pacotes do venv que instalaram arquivos nele."""
    donos = {}
    for d in md.distributions():
        for f in d.files or []:
            topo = f.parts[0]
            if topo.endswith((".dist-info", ".data")) or topo in ("..", "__pycache__"):
                continue
            donos.setdefault(topo.split(".")[0] if f.suffix in (".py", ".pyd") and len(f.parts) == 1 else topo,
                             set()).add(d.metadata["Name"])
    return donos


def tipo(d):
    """O nome curto da licenca pelos metadados (License-Expression, License de uma linha ou o classificador)."""
    m = d.metadata
    if m.get("License-Expression"):
        return m["License-Expression"]
    lic = (m.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 80:
        return lic
    cl = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(cl) or "ver o texto"


def textos(d):
    """Os arquivos de licenca que o pacote instalou: os do .dist-info (e da licenses\\ dele) e os do alto da pasta do
    pacote (o onnxruntime guarda o LICENSE e o ThirdPartyNotices.txt so ali)."""
    out = []
    for f in d.files or []:
        no_dist_info = f.parts[0].endswith(".dist-info") and (NOME_LICENCA.search(f.name) or "licenses" in f.parts[1:-1])
        no_pacote = len(f.parts) == 2 and f.parts[0] != ".." and NOME_LICENCA.search(f.name)
        if no_dist_info or no_pacote:
            out.append((f.as_posix(), le(d.locate_file(f))))
    lic = (d.metadata.get("License") or "").strip()
    if not out and "\n" in lic:  # quem poe o texto inteiro no campo License
        out.append(("License (metadados)", lic))
    return out


def roda(exe, *args):
    return subprocess.run([str(exe), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=60).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    for a in ("--app", "--vitrola", "--ffmpeg", "--deno", "--saida"):
        ap.add_argument(a, type=Path, required=True)
    a = ap.parse_args()
    # do app: os modulos dele e as pastas que o vitrola.spec copia do repo
    nosso = {p.stem for p in a.vitrola.glob("*.py")} | {"themes", "modelos", "icone"}
    donos = dono_de_cada_nome()
    pacotes, sem_dono = set(), []
    for n in sorted(modulos(a.app)):
        if n in sys.stdlib_module_names or n in nosso or n.startswith(("pyimod", "pyi_", "_pyi")):
            continue
        if n in donos:
            pacotes |= donos[n]
        else:
            sem_dono.append(n)
    if sem_dono:
        sys.exit(f"modulos que nao sao de nenhum pacote do venv (de onde vem a licenca?): {', '.join(sem_dono)}")
    pacotes.add("pyinstaller")  # o bootloader vai no vitrola.exe; o PyInstaller em si nao entra no PYZ

    secoes, lista, faltando = [], [], []

    def secao(titulo, licenca, corpo):
        lista.append(f"  {titulo:<40} {licenca}")
        secoes.append(f"{'=' * 100}\n{titulo} ({licenca})\n{'=' * 100}\n\n{corpo.strip()}\n")

    py = Path(sys.base_prefix) / "LICENSE.txt"
    secao(f"Python {sys.version.split()[0]}", "PSF-2.0 e as dos componentes dele", le(py))

    for nome in sorted(pacotes, key=str.lower):
        d = md.distribution(nome)
        tx = textos(d)
        if not tx:
            faltando.append(nome)
            continue
        extra = ("O bootloader do PyInstaller e o comeco do vitrola.exe; a excecao da licenca dele permite distribuir o "
                 "programa gerado sob outra licenca.\n\n" if nome == "pyinstaller" else "")
        lic = "GPL-2.0-or-later WITH Bootloader-exception" if nome == "pyinstaller" else tipo(d)
        secao(f"{d.metadata['Name']} {d.version}", lic, extra + "\n\n".join(f"--- {c}\n\n{t}" for c, t in tx))
    if faltando:
        sys.exit(f"pacotes sem arquivo de licenca no venv: {', '.join(faltando)} (acrescente o texto em licencas\\)")

    interno = a.app / "_internal"
    pastas = sorted({f.parent for f in interno.rglob("*") if f.suffix.lower() in DADOS_COM_LICENCA})
    for p in pastas:
        lic = sorted(f for f in p.iterdir() if f.is_file() and NOME_LICENCA.search(f.name))
        if not lic:
            sys.exit(f"{p.relative_to(interno)} tem modelo ou fonte sem licenca na mesma pasta")
        corpo = "\n\n".join(f"--- {f.relative_to(interno).as_posix()}\n\n{le(f)}" for f in lic)
        secao(f"_internal\\{p.relative_to(interno)}", "ver o texto", corpo)

    ff = a.ffmpeg / "ffmpeg.exe"
    ver = roda(ff, "-hide_banner", "-version").splitlines()
    num = re.search(r"version n?(\d+(?:\.\d+)+)", ver[0])
    corpo = [ver[0], next((x for x in ver if x.startswith("configuration:")), ""), "", roda(ff, "-hide_banner", "-L")]
    if num:
        corpo.append(f"\nA fonte: https://ffmpeg.org/releases/ffmpeg-{num.group(1)}.tar.xz")
    for pasta in (a.ffmpeg, a.ffmpeg.parent):
        for f in sorted(pasta.iterdir()):
            if f.is_file() and (NOME_LICENCA.search(f.name) or f.name == "FONTE.txt"):
                corpo.append(f"\n--- {f.name}\n\n{le(f)}")
    secao("ffmpeg e ffprobe (bin\\)", "ver o texto", "\n".join(corpo))

    deno = roda(a.deno / "deno.exe", "--version").splitlines()[0]
    num = re.search(r"deno (\d+(?:\.\d+)+)", deno).group(1)
    secao(f"Deno {num} (bin\\)", "MIT", f"A fonte: https://github.com/denoland/deno/tree/v{num}\n\n"
                                      f"{le(LICENCAS / 'deno-LICENSE.md')}")

    versao = re.search(r'^VERSAO = "(.+)"', (a.vitrola / "versao.py").read_text(encoding="utf-8"), re.M).group(1)
    topo = (f"Vitrola {versao}: avisos de terceiros\n\n"
            "A Vitrola é software livre sob a GPL versão 3 (LICENSE.txt, nesta pasta). Ela leva junto programas e "
            "bibliotecas\nde outros projetos, cada um sob a própria licença: a lista vem primeiro e, depois dela, o "
            "texto de cada licença.\n\n")
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    # com o BOM: o Bloco de Notas antigo le sem ele como ANSI
    a.saida.write_text(topo + "\n".join(lista) + "\n\n\n" + "\n\n".join(secoes), encoding="utf-8-sig")
    print(f"{a.saida}: {len(lista)} componentes, {a.saida.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
