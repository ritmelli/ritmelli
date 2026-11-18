"""Onde moram as coisas. Os dados de quem usa ficam fora da pasta do app, porque instalado em Program Files
ela nao aceita escrita: audio baixado, biblioteca e escolhas em library/; os logs do servidor em logs/. Os logs
das ferramentas de dev/ (logs/efeitos/) seguem na pasta do codigo. O ffmpeg, o ffprobe e o deno vem na bin/ do
app (o instalador poe); sem ela, saem do PATH, como no codigo. A porta do servidor e a pagina que o app abre moram
aqui tambem: o ritmelli.py precisa delas antes de carregar o servidor. E o jeito de gravar os .json dos dados
(save_json), o mesmo para o servidor e para o pareamento."""
import json
import os
import sys
from pathlib import Path

_BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home())
DADOS_NOVA = _BASE / "Ritmelli"
# a pasta de antes da troca de nome (#58; ate a 0.4.1 o app se chamava Vitrola): enquanto o migra() nao a renomeia,
# os dados seguem nela, e nenhum processo grava em duas pastas
DADOS_VELHA = _BASE / "Vitrola"
DADOS = DADOS_VELHA if DADOS_VELHA.is_dir() and not DADOS_NOVA.exists() else DADOS_NOVA
LIB = DADOS / "library"
LOGS = DADOS / "logs"
# a pasta do executavel no app congelado (PyInstaller), a do codigo fora dele
APP = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BIN = APP / "bin"
PORTA = 8799  # a do servidor: o PC abre em 127.0.0.1, o celular no IP da rede de casa
# o tema, e nao a galeria de temas (que segue em /): quem acabou de instalar cai direto no toca-discos
PAGINA = "/t/vitrola/"  # o tema se chama Vitrola (o aparelho de som que ele desenha); o app e o Ritmelli


def migra():
    """Os dados da pasta de antes da troca de nome (%LOCALAPPDATA%\\Vitrola) passam para a %LOCALAPPDATA%\\Ritmelli,
    com a biblioteca, as escolhas, o codigo dos dados de uso e o que a janela guarda: so o servidor chama, ao ligar,
    antes de carregar os modulos que gravam nela. Renomear e instantaneo (mesmo disco); se a pasta velha estiver
    presa (o Explorer aberto nela, um arquivo em uso), os dados seguem nela nesta abertura e a troca tenta de novo na
    proxima. True se os dados estao na pasta nova."""
    global DADOS, LIB, LOGS
    if DADOS == DADOS_NOVA:
        return True
    try:
        DADOS_VELHA.rename(DADOS_NOVA)
    except OSError as e:
        print(f"data folder: couldn't move {DADOS_VELHA} to {DADOS_NOVA} ({e}); using the old one for now", flush=True)
        return False
    DADOS, LIB, LOGS = DADOS_NOVA, DADOS_NOVA / "library", DADOS_NOVA / "logs"
    return True


def ferramenta(nome):
    """O caminho de nome.exe na BIN, ou None (ai vale o do PATH)."""
    p = BIN / f"{nome}.exe"
    return str(p) if p.exists() else None


def save_json(path, data):
    """Grava num .tmp e troca de uma vez: o app caindo no meio nunca deixa o arquivo pela metade."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
