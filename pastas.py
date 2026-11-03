"""Onde moram as coisas. Os dados de quem usa ficam fora da pasta do app, porque instalado em Program Files
ela nao aceita escrita: audio baixado, biblioteca e escolhas em library/; os logs do servidor em logs/. Os logs
das ferramentas de dev/ (logs/efeitos/) seguem na pasta do codigo. O ffmpeg, o ffprobe e o deno vem na bin/ do
app (o instalador poe); sem ela, saem do PATH, como no codigo. A porta do servidor mora aqui tambem: o vitrola.py
precisa dela antes de carregar o servidor. E o jeito de gravar os .json dos dados (save_json), o mesmo para o
servidor e para o pareamento."""
import json
import os
import sys
from pathlib import Path

DADOS = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Vitrola"
LIB = DADOS / "library"
LOGS = DADOS / "logs"
# a pasta do executavel no app congelado (PyInstaller), a do codigo fora dele
APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BIN = APP / "bin"
PORTA = 8799  # a do servidor: o PC abre em 127.0.0.1, o celular no IP da rede de casa


def ferramenta(nome):
    """O caminho de nome.exe na BIN, ou None (ai vale o do PATH)."""
    p = BIN / f"{nome}.exe"
    return str(p) if p.exists() else None


def save_json(path, data):
    """Grava num .tmp e troca de uma vez: o app caindo no meio nunca deixa o arquivo pela metade."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
