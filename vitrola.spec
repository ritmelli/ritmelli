# A receita do executavel: .venv-build\Scripts\pyinstaller vitrola.spec (ver o README). Sai em dist\vitrola\: o
# vitrola.exe e a _internal\ com o Python, as bibliotecas e os arquivos do app. Pasta, e nao arquivo unico: o
# arquivo unico se desempacota numa pasta temporaria a cada abertura (lento, e mais marcado por antivirus), e o
# instalador instala uma pasta de qualquer jeito. O ffmpeg, o ffprobe e o deno vao na bin\ ao lado do exe
# (pastas.py), fora daqui.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("themes", "themes"),  # o server.py e o compasso.py acham pelo __file__, que no exe e a _internal\
    ("gallery.html", "."),
    ("modelos/compasso.onnx", "modelos"),
]
datas += collect_data_files("ytmusicapi")  # os idiomas (locales\): sem hook pronto

a = Analysis(
    ["vitrola.py"],
    datas=datas,
    # o yt-dlp acha o resolvedor do desafio do YouTube (os .js, que o hook dele ja leva) sem import direto
    hiddenimports=collect_submodules("yt_dlp_ejs"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vitrola", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="vitrola")
