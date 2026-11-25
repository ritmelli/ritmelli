import os
import subprocess
import sys
import tempfile
from pathlib import Path

RELEASES = "https://github.com/ritmelli/ritmelli-releases/releases/download"
OUTPUT = Path("instalador", "saida")
APP = Path("dist", "ritmelli")
FFMPEG = Path("instalador", "ffmpeg", "bin")
VENDOR = Path("instalador", "vendor")


def notes_options(folder):
    options = []
    for variable, option in (("NOTAS", "--notas"), ("NOTAS_EN", "--notas-en")):
        lines = [n.strip() for n in (os.environ.get(variable) or "").split("|") if n.strip()]
        if lines:
            path = Path(folder, f"{variable.lower()}.txt")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
            options += [option, path]
    return options


def publica_arguments(version, notes_folder):
    deno = sorted(d for d in VENDOR.glob("deno-*") if d.is_dir())
    if not deno:
        sys.exit(f"no deno-* folder in {VENDOR}")
    setup = OUTPUT / f"Ritmelli-{version}-setup.exe"
    arguments = ["--setup", setup, "--url", f"{RELEASES}/v{version}/{setup.name}", "--app", APP,
                 "--bin", FFMPEG, "--bin", deno[0], "--saida", OUTPUT, *notes_options(notes_folder)]
    partial = OUTPUT / f"Ritmelli-{version}-parcial.exe"
    if partial.exists():
        arguments += ["--parcial", partial, "--parcial-info", OUTPUT / f"PARCIAL-{version}.json"]
    return [str(a) for a in arguments]


def main():
    publica = Path(__file__).resolve().with_name("publica.py")
    with tempfile.TemporaryDirectory() as notes_folder:
        result = subprocess.run([sys.executable, str(publica), *publica_arguments(os.environ["VERSAO"], notes_folder)])
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
