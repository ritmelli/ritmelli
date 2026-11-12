# Compila o ffmpeg so de audio que vai na bin\ do app, com so o que a Vitrola usa: tocar a biblioteca e o stream do
# YouTube, ler a duracao pelo ffprobe e os consertos de container do yt-dlp. Sem os codificadores de video (x264 e x265,
# com patente) e sem biblioteca de fora alem do zlib: o resultado e LGPL. Sai em bin\ (ffmpeg.exe, ffprobe.exe, a
# licenca e a FONTE.txt), que vai no git; o monta.ps1 so copia. O testa.ps1 confere o resultado contra o ffmpeg de antes.
# O compilador vem do MSYS2, numa pasta propria (o msys2.ps1): nada se instala no Windows e nada pede administrador.
# Uso: compila.ps1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # sem a barra, o Invoke-WebRequest do PowerShell 5 baixa muito mais rapido
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

. (Join-Path $PSScriptRoot '..\msys2.ps1')

# versao fixa, conferindo o hash. Para trocar de versao: a URL e o hash (o publicado, ou Get-FileHash)
$FONTE = @{ Url = 'https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz'
            Sha = '8C3850283EB25FA026482078A04051E0BE17347B09EF81A0849BEC15A96E002E' }
$PACOTES = 'make diffutils mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-nasm mingw-w64-ucrt-x86_64-pkgconf mingw-w64-ucrt-x86_64-zlib'

$saida = Join-Path $PSScriptRoot 'bin'
PreparaMsys2 $PACOTES

$env:VITROLA_FONTE = Baixa $FONTE
$env:VITROLA_SAIDA = $saida
'compilando o ffmpeg...'
# o caminho ja no formato do MSYS2 (/c/...): o PowerShell 5 tira as aspas de dentro do que passa para outro programa, e o
# bash recebia o $(cygpath ...) quebrado
$sh = Join-Path $PSScriptRoot 'compila.sh'
Bash 'compila.sh' ('bash /' + $sh.Substring(0, 1).ToLower() + $sh.Substring(2).Replace('\', '/'))

foreach ($exe in 'ffmpeg.exe', 'ffprobe.exe') {
  $f = Get-Item (Join-Path $saida $exe)
  '{0}: {1:N1} MB' -f $f.Name, ($f.Length / 1MB)
}
& (Join-Path $saida 'ffmpeg.exe') -hide_banner -version | Select-Object -First 1
