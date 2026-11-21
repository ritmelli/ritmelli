"""Os avisos de terceiros do instalador (o TERCEIROS.txt da pasta do app): tudo o que vai junto com o Ritmelli, cada um
com o texto da licenca dele. O monta.ps1 roda depois de congelar, com o python do venv do build:

    python terceiros.py --app <dist\\ritmelli> --ritmelli <repo ritmelli> --ffmpeg <pasta> --deno <pasta> --saida <arquivo>

- as bibliotecas Python que o PyInstaller levou: os modulos do PYZ do exe e o que esta na _internal\\, ligados ao pacote
  do pip pelos arquivos que cada pacote instalou no venv. O texto sai dos arquivos de licenca do pacote;
- o Python (o LICENSE.txt da instalacao, que ja traz o OpenSSL, o libffi, o zlib e os outros que vem com ele) e o
  PyInstaller (o bootloader e o comeco do ritmelli.exe);
- os modelos e as fontes da _internal\\, com a licenca que esta na mesma pasta;
- o SDK do WebView2 e a DirectML, que vem dentro de pacotes do pip sem os termos da Microsoft: os textos estao em
  licencas\\ (a DirectML confere a versao da DLL);
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
DIRECTML = "1.15.4"  # a versao dos termos da DirectML em licencas\ (directml-LICENSE.txt e directml-NOTICE.txt)


def le(arq):
    return Path(arq).read_text(encoding="utf-8", errors="replace").strip()


def modulos(app):
    """Os nomes de cima de tudo o que o PyInstaller levou: os modulos do PYZ e as pastas e .pyd da _internal\\."""
    pyz = CArchiveReader(str(app / "ritmelli.exe")).open_embedded_archive("PYZ.pyz")
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
    return ", ".join(cl) or "consulte o texto / see the text"


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


def versao_da_dll(arq):
    """A versao de arquivo de uma DLL (as tres primeiras partes), pelo recurso de versao dela."""
    import ctypes
    v = ctypes.WinDLL("version")
    n = v.GetFileVersionInfoSizeW(str(arq), None)
    buf = ctypes.create_string_buffer(n)
    if not n or not v.GetFileVersionInfoW(str(arq), 0, n, buf):
        sys.exit(f"{arq}: sem informacao de versao")
    p, tam = ctypes.c_void_p(), ctypes.c_uint()
    v.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(tam))
    ms, ls = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32 * 4)).contents[2:4]  # dwFileVersionMS, dwFileVersionLS
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"


def roda(exe, *args):
    return subprocess.run([str(exe), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=60).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    for a in ("--app", "--ritmelli", "--ffmpeg", "--deno", "--saida"):
        ap.add_argument(a, type=Path, required=True)
    a = ap.parse_args()
    # do app: os modulos dele, os pacotes dele (pasta com __init__.py, como o microfone/) e as pastas que o
    # ritmelli.spec copia do repo
    nosso = ({p.stem for p in a.ritmelli.glob("*.py")} | {p.parent.name for p in a.ritmelli.glob("*/__init__.py")}
             | {"themes", "gallery", "modelos", "icone"})
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
    pacotes.add("pyinstaller")  # o bootloader vai no ritmelli.exe; o PyInstaller em si nao entra no PYZ

    secoes, lista, faltando = [], [], []

    def secao(titulo, licenca, corpo):
        lista.append(f"  {titulo:<40} {licenca}")
        secoes.append(f"{'=' * 100}\n{titulo} ({licenca})\n{'=' * 100}\n\n{corpo.strip()}\n")

    py = Path(sys.base_prefix) / "LICENSE.txt"
    secao(f"Python {sys.version.split()[0]}", "PSF-2.0 e as licenças dos seus componentes / PSF-2.0 and the licenses of its components", le(py))

    for nome in sorted(pacotes, key=str.lower):
        d = md.distribution(nome)
        tx = textos(d)
        if not tx:  # o pacote declara a licenca sem trazer o texto: o texto que mora em licencas\ (proxy_tools)
            base = d.metadata["Name"].replace("-", "_").lower()
            tx = [(f"instalador/licencas/{f.name}", le(f)) for f in sorted(LICENCAS.glob("*-LICENSE*"))
                  if f.name.split("-LICENSE")[0].replace("-", "_").lower() == base]
        if not tx:
            faltando.append(nome)
            continue
        extra = ("O bootloader do PyInstaller forma o início do ritmelli.exe; a exceção prevista na licença dele permite "
                 "distribuir o programa gerado sob outra licença.\n\n"
                 "The PyInstaller bootloader forms the beginning of ritmelli.exe; the exception in its license allows "
                 "the generated program to be distributed under another license.\n\n" if nome == "pyinstaller" else "")
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
        secao(f"_internal\\{p.relative_to(interno)}", "consulte o texto / see the text", corpo)

    # as DLLs do SDK do WebView2 (a janela, janela.py) vem dentro do pywebview, sem a licenca da Microsoft: o texto e
    # o aviso do pacote NuGet da mesma versao moram em licencas\
    wv2 = interno / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll"
    if wv2.exists():
        secao("Microsoft Edge WebView2 SDK (_internal\\webview\\lib)", "BSD-3-Clause",
              f"--- LICENSE.txt\n\n{le(LICENCAS / 'webview2-LICENSE.txt')}\n\n"
              f"--- NOTICE.txt\n\n{le(LICENCAS / 'webview2-NOTICE.txt')}")

    # a DirectML.dll (a troca de voz na placa de video, conversor.py) vem dentro do onnxruntime-directml, sem os termos
    # da Microsoft: o texto e os avisos do pacote NuGet Microsoft.AI.DirectML da mesma versao moram em licencas\. Uma
    # DirectML de outra versao derruba o build, para os termos serem conferidos de novo
    for dml in sorted(interno.rglob("DirectML.dll")):
        ver = versao_da_dll(dml)
        if ver != DIRECTML:
            sys.exit(f"a DirectML.dll do app e a {ver}, e os termos em licencas\\ sao os da {DIRECTML}: troque o "
                     f"directml-LICENSE.txt e o directml-NOTICE.txt pelos do pacote NuGet Microsoft.AI.DirectML {ver}")
        secao(f"Microsoft DirectML {ver} (_internal\\{dml.parent.relative_to(interno)})", "Microsoft Software License Terms",
              f"--- LICENSE.txt\n\n{le(LICENCAS / 'directml-LICENSE.txt')}\n\n"
              f"--- ThirdPartyNotices.txt\n\n{le(LICENCAS / 'directml-NOTICE.txt')}")

    ff = a.ffmpeg / "ffmpeg.exe"
    ver = roda(ff, "-hide_banner", "-version").splitlines()
    num = re.search(r"version n?(\d+(?:\.\d+)+)", ver[0])
    corpo = [ver[0], next((x for x in ver if x.startswith("configuration:")), ""), "", roda(ff, "-hide_banner", "-L")]
    if num:
        corpo.append(f"\nCódigo-fonte / source code: https://ffmpeg.org/releases/ffmpeg-{num.group(1)}.tar.xz")
    for pasta in (a.ffmpeg, a.ffmpeg.parent):
        for f in sorted(pasta.iterdir()):
            if f.is_file() and (NOME_LICENCA.search(f.name) or f.name == "FONTE.txt"):
                corpo.append(f"\n--- {f.name}\n\n{le(f)}")
    secao("ffmpeg e ffprobe (bin\\)", "consulte o texto / see the text", "\n".join(corpo))

    deno = roda(a.deno / "deno.exe", "--version").splitlines()[0]
    num = re.search(r"deno (\d+(?:\.\d+)+)", deno).group(1)
    secao(f"Deno {num} (bin\\)", "MIT", f"Código-fonte / source code: https://github.com/denoland/deno/tree/v{num}\n\n"
                                      f"{le(LICENCAS / 'deno-LICENSE.md')}")

    versao = re.search(r'^VERSAO = "(.+)"', (a.ritmelli / "versao.py").read_text(encoding="utf-8"), re.M).group(1)
    topo = (f"Ritmelli {versao}: avisos de terceiros / third-party notices\n\n"
            "O Ritmelli é software livre, distribuído sob a GPLv3 (LICENSE.txt, nesta pasta). Ele inclui "
            "programas e bibliotecas\nde outros projetos, cada um sob a sua própria licença. Este arquivo traz a "
            "lista desses componentes e, em seguida, o texto\nde cada licença.\n\n"
            "Ritmelli is free software, distributed under the GPLv3 (LICENSE.txt, in this folder). It "
            "includes software\nand libraries from other projects, each under its own license. This file lists "
            "those components, followed by\nthe text of each license.\n\n")
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    # com o BOM: o Bloco de Notas antigo le sem ele como ANSI
    a.saida.write_text(topo + "\n".join(lista) + "\n\n\n" + "\n\n".join(secoes), encoding="utf-8-sig")
    print(f"{a.saida}: {len(lista)} componentes, {a.saida.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
