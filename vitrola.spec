# A receita do executavel: .venv-build\Scripts\pyinstaller vitrola.spec (ver o README). Sai em dist\vitrola\: o
# vitrola.exe e a _internal\ com o Python, as bibliotecas e os arquivos do app. Pasta, e nao arquivo unico: o
# arquivo unico se desempacota numa pasta temporaria a cada abertura (lento, e mais marcado por antivirus), e o
# instalador instala uma pasta de qualquer jeito. O ffmpeg, o ffprobe e o deno vao na bin\ ao lado do exe
# (pastas.py), fora daqui.
import os
import re

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
                                                 VarStruct, VSVersionInfo)

datas = [
    ("themes", "themes"),  # o server.py e o compasso.py acham pelo __file__, que no exe e a _internal\
    ("gallery.html", "."),
    ("modelos/compasso.onnx", "modelos"),
    ("modelos/LICENSE-beat_this.txt", "modelos"),  # o modelo e MIT: a licenca vai junto com ele
    # o icone da aba do navegador e o do celular (server.py); o setup tambem pega o .ico daqui
    ("icone/vitrola.ico", "icone"),
    ("icone/toque.png", "icone"),
]
datas += collect_data_files("ytmusicapi")  # os idiomas (locales\): sem hook pronto

a = Analysis(
    ["vitrola.py"],
    datas=datas,
    # o yt-dlp acha o resolvedor do desafio do YouTube (os .js, que o hook dele ja leva) sem import direto
    hiddenimports=collect_submodules("yt_dlp_ejs"),
    excludes=["tkinter"],
)
# a informacao de versao do exe (Propriedades > Detalhes, e o nome no Gerenciador de Tarefas): sem ela, tudo em branco
with open(os.path.join(SPECPATH, "versao.py"), encoding="utf-8") as f:
    VERSAO = re.search(r'^VERSAO = "(.+)"', f.read(), re.M).group(1)
numeros = (*map(int, VERSAO.split(".")), 0)
versao = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numeros, prodvers=numeros),
    kids=[
        StringFileInfo([StringTable("041604B0", [  # portugues do Brasil, Unicode
            StringStruct("CompanyName", "Behling Informática Ltda"),
            StringStruct("FileDescription", "Vitrola"),
            StringStruct("FileVersion", VERSAO),
            StringStruct("InternalName", "vitrola"),
            StringStruct("LegalCopyright", "Software livre sob a GPLv3"),
            StringStruct("OriginalFilename", "vitrola.exe"),
            StringStruct("ProductName", "Vitrola"),
            StringStruct("ProductVersion", VERSAO),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
    ])

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vitrola", console=False, version=versao,
          icon=os.path.join(SPECPATH, "icone", "vitrola.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="vitrola")
