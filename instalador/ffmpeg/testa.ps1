# Confere o ffmpeg compilado (bin\) contra o completo de antes, o que o monta.ps1 baixava (fica no vendor\ de quem ja
# montou o instalador): ver o testa.py. Usa o python do venv do build, que o monta.ps1 cria.
# Uso: testa.ps1
$ErrorActionPreference = 'Stop'
$py = Join-Path $env:LOCALAPPDATA 'vitrola-build\Scripts\python.exe'
$velho = Join-Path $PSScriptRoot '..\vendor\ffmpeg-8d31e162\ffmpeg-9.0.2-full_build-shared\bin'
if (-not (Test-Path "$velho\ffmpeg.exe")) { throw "nao achei o ffmpeg de antes em $velho" }
& $py -X utf8 (Join-Path $PSScriptRoot 'testa.py') (Join-Path $PSScriptRoot 'bin') (Resolve-Path $velho).Path
exit $LASTEXITCODE
