# Monta o instalador da Vitrola: congela o app (o vitrola.spec da raiz deste repo), baixa o Deno na versao fixa abaixo
# (conferindo o hash), junta o ffmpeg so de audio de ffmpeg\bin (o ffmpeg\compila.ps1 gera, e ele vai no git) e compila
# o vitrola.iss pelo Inno Setup. Sai em saida\.
# Uso: monta.ps1 [-Vitrola <pasta do app>] [-SoCongela | -SemCongelar] [-Anterior <manifest.json>]
#   -Vitrola e a raiz deste repo, onde mora o app: so muda para montar outra copia dele
#   -SoCongela para depois de congelar o app (dist\vitrola), sem montar o setup: na esteira, o vitrola.exe e assinado
#   entre as duas chamadas
#   -SemCongelar usa o dist\vitrola que ja existe: na esteira, e a segunda chamada, com o vitrola.exe ja assinado; no
#   PC, serve para testar o instalador sem congelar de novo
#   -Anterior monta tambem a atualizacao parcial (Vitrola-<versao>-parcial.exe), so com o que mudou desde a versao
#   desse manifesto (o manifest.json.sig ao lado dele), e grava ao lado o PARCIAL-<versao>.json do parcial.py
param([string]$Vitrola = (Join-Path $PSScriptRoot '..'), [switch]$SoCongela, [switch]$SemCongelar, [string]$Anterior)
$ErrorActionPreference = 'Stop'
if ($SoCongela -and $SemCongelar) { throw 'o -SoCongela e o -SemCongelar nao vao juntos' }
$ProgressPreference = 'SilentlyContinue'  # sem a barra, o Invoke-WebRequest do PowerShell 5 baixa muito mais rapido
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# o Deno da bin\ do app. Para trocar de versao: a URL, o hash (o publicado, ou Get-FileHash) e a pasta de dentro
$DENO = @{ Url = 'https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip'
           Sha = 'cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf'
           Bin = '' }

$Vitrola = (Resolve-Path $Vitrola).Path
$vendor = Join-Path $PSScriptRoot 'vendor'
$saida = Join-Path $PSScriptRoot 'saida'

# o PowerShell 5 transforma cada linha do stderr de um programa em erro, e com o Stop o primeiro aviso do
# PyInstaller derrubava o script: dos programas de fora, vale so o codigo de saida
function Roda($nome, [scriptblock]$cmd) {
  $antes = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $cmd 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $antes }
  if ($LASTEXITCODE -ne 0) { throw "$nome saiu com $LASTEXITCODE" }
}

# baixa o .zip (se ainda nao esta aqui com o hash certo), confere e extrai numa pasta so dele
function Prepara($nome, $p) {
  $zip = Join-Path $vendor (Split-Path $p.Url -Leaf)
  $zip = $zip -replace '\.zip$', "-$($p.Sha.Substring(0, 8)).zip"
  if (-not (Test-Path $zip) -or (Get-FileHash $zip -Algorithm SHA256).Hash -ne $p.Sha) {
    # Write-Host, e nao a saida da funcao: o que ela solta vai junto com o caminho que ela devolve
    Write-Host "baixando $nome..."
    Invoke-WebRequest $p.Url -OutFile $zip -UseBasicParsing
    $h = (Get-FileHash $zip -Algorithm SHA256).Hash
    if ($h -ne $p.Sha) { Remove-Item $zip; throw "$nome veio com hash $h, e nao $($p.Sha)" }
  }
  $pasta = Join-Path $vendor "$nome-$($p.Sha.Substring(0, 8))"
  if (-not (Test-Path $pasta)) {
    # extrai ao lado e so no fim renomeia: uma extracao interrompida nao fica parecendo pronta no build seguinte
    $meio = "$pasta.extraindo"
    if (Test-Path $meio) { Remove-Item $meio -Recurse -Force }
    Expand-Archive $zip -DestinationPath $meio
    Rename-Item $meio (Split-Path $pasta -Leaf)
  }
  return (Join-Path $pasta $p.Bin).TrimEnd('\')
}

$versao = (Select-String -Path (Join-Path $Vitrola 'versao.py') -Pattern '^VERSAO = "(.+)"').Matches[0].Groups[1].Value
"Vitrola $versao"

# o venv fica numa pasta curta, fora do repo: num caminho longo, o pip passa dos 260 caracteres do Windows
# (WinError 206 no numpy)
$raiz = Join-Path $env:LOCALAPPDATA 'vitrola-build'
$venv = Join-Path $raiz 'Scripts'
if (-not $SemCongelar) {
  if (-not (Test-Path "$venv\python.exe")) {
    "criando o venv em $raiz..."
    Roda 'venv' { python -m venv $raiz }
  }
  # a cada build: as versoes de travas.txt (o PC e o GitHub montam com as mesmas, e elas so mudam de proposito), o que
  # entrou no requirements.txt e ainda nao esta na trava, e o yt-dlp sempre o mais novo (o YouTube quebra o velho, e o
  # update do app e o unico jeito de o novo chegar a quem usa)
  Roda 'pip' { & "$venv\python.exe" -m pip install -q -r (Join-Path $Vitrola 'requirements.txt') -r (Join-Path $PSScriptRoot 'travas.txt') }
  # o PyInstaller da versao fixa, instalado da fonte com o bootloader compilado aqui (bootloader\compila.ps1) no lugar
  # do pronto. So reinstala quando o bootloader do venv nao e o nosso; a fonte se abre na pasta curta do venv
  $PYI = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'bootloader\pyinstaller.psd1')
  $nosso = Join-Path $PSScriptRoot 'bootloader\bin'
  $doVenv = Join-Path $raiz 'Lib\site-packages\PyInstaller\bootloader\Windows-64bit-intel\runw.exe'
  $hash = (Get-FileHash "$nosso\runw.exe" -Algorithm SHA256).Hash
  if (-not (Test-Path $doVenv) -or (Get-FileHash $doVenv -Algorithm SHA256).Hash -ne $hash) {
    New-Item -ItemType Directory -Force $vendor | Out-Null
    $tar = Join-Path $vendor (Split-Path $PYI.Url -Leaf)
    if (-not (Test-Path $tar) -or (Get-FileHash $tar -Algorithm SHA256).Hash -ne $PYI.Sha) {
      'baixando a fonte do PyInstaller...'
      Invoke-WebRequest $PYI.Url -OutFile $tar -UseBasicParsing
      $h = (Get-FileHash $tar -Algorithm SHA256).Hash
      if ($h -ne $PYI.Sha) { Remove-Item $tar; throw "a fonte do PyInstaller veio com hash $h, e nao $($PYI.Sha)" }
    }
    # pelo tarfile, e nao pelo tar do Windows, que nao cria os links simbolicos do sdist (o tarfile copia o arquivo)
    $fonte = Join-Path $raiz "pyinstaller-$($PYI.Versao)"
    if (Test-Path $fonte) { Remove-Item $fonte -Recurse -Force }
    Roda 'tarfile' { & "$venv\python.exe" -c "import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='data')" $tar $raiz }
    Copy-Item "$nosso\*.exe" (Join-Path $fonte 'PyInstaller\bootloader\Windows-64bit-intel') -Force
    "instalando o PyInstaller $($PYI.Versao) com o bootloader de bootloader\bin..."
    # o da mesma versao, vindo do PyPI, contaria como ja instalado
    Roda 'pip' { & "$venv\python.exe" -m pip uninstall -q -y pyinstaller }
    Roda 'pip' { & "$venv\python.exe" -m pip install -q $fonte }
    Remove-Item $fonte -Recurse -Force
  }
  if ((Get-FileHash $doVenv -Algorithm SHA256).Hash -ne $hash) { throw 'o PyInstaller do venv ficou com outro bootloader' }
  Roda 'yt-dlp' { & "$venv\python.exe" -m pip install -q -U 'yt-dlp[default]' }
  "yt-dlp $(& "$venv\python.exe" -m yt_dlp --version)"
  # o filtro de microfone (a musica no microfone do jogo): a DLL vai dentro do app (vitrola.spec). Precisa do Visual Studio 2022 com
  # C++ (no GitHub, o do windows-latest)
  'compilando o filtro de microfone...'
  Roda 'micfx' { cmd /c (Join-Path $Vitrola 'microfone\apo\compila.bat') }
  'congelando o app...'
  Push-Location $Vitrola
  try { Roda 'pyinstaller' { & "$venv\pyinstaller.exe" --noconfirm --log-level ERROR vitrola.spec } } finally { Pop-Location }
}
$app = Join-Path $Vitrola 'dist\vitrola'
if (-not (Test-Path "$app\vitrola.exe")) { throw "nao achei $app\vitrola.exe (rode sem -SemCongelar)" }
if ($SoCongela) { "congelado: $app"; return }

New-Item -ItemType Directory -Force $vendor | Out-Null
$ffmpeg = Join-Path $PSScriptRoot 'ffmpeg\bin'
if (-not (Test-Path "$ffmpeg\ffmpeg.exe")) { throw "nao achei $ffmpeg\ffmpeg.exe (rode o ffmpeg\compila.ps1)" }
$deno = Prepara 'deno' $DENO

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'falta o Inno Setup 6: winget install -e --id JRSoftware.InnoSetup' }
# os avisos de terceiros, pelo venv que congelou o app: sai ao lado do setup, para conferir, e vai na pasta do app
if (-not (Test-Path "$venv\python.exe")) { throw "nao achei o venv do build em $raiz (rode sem -SemCongelar)" }
$terceiros = Join-Path $saida "TERCEIROS-$versao.txt"
Roda 'terceiros.py' { & "$venv\python.exe" (Join-Path $PSScriptRoot 'terceiros.py') --app $app --vitrola $Vitrola --ffmpeg $ffmpeg --deno $deno --saida $terceiros }
# a versao de cada biblioteca do venv que congelou o app, tambem ao lado do setup: de onde saiu cada build
$versoes = Join-Path $saida "VERSOES-$versao.txt"
Roda 'pip freeze' { & "$venv\python.exe" -m pip freeze --all | Set-Content -Path $versoes -Encoding ascii }
"$versoes"
'compilando o instalador...'
Roda 'ISCC' { & $iscc /Q "/DVersao=$versao" "/DApp=$app" "/DFfmpeg=$ffmpeg" "/DDeno=$deno" "/DLicenca=$(Join-Path $Vitrola 'LICENSE')" "/DTerceiros=$terceiros" "/O$saida" (Join-Path $PSScriptRoot 'vitrola.iss') }
$setup = Get-Item (Join-Path $saida "Vitrola-$versao-setup.exe")
'pronto: {0} ({1:N0} MB)' -f $setup.FullName, ($setup.Length / 1MB)

if ($Anterior) {
  # a parcial separa o que mudou numa pasta fora da saida\ (a saida\ inteira vira artefato na esteira) e monta o mesmo
  # vitrola.iss so com isso. Sem nada mudado, o parcial.py nao grava o parcial.json, e fica so o setup completo
  $pasta = Join-Path $raiz 'parcial'
  $info = Join-Path $saida "PARCIAL-$versao.json"
  Remove-Item $info, (Join-Path $saida "Vitrola-$versao-parcial.exe") -ErrorAction SilentlyContinue
  Roda 'parcial.py' { & "$venv\python.exe" (Join-Path $PSScriptRoot 'atualizacao\parcial.py') --anterior $Anterior --app-py (Join-Path $Vitrola 'atualizacao.py') --app $app --bin $ffmpeg --bin $deno --saida $pasta }
  if (Test-Path "$pasta\parcial.json") {
    'compilando a atualizacao parcial...'
    Roda 'ISCC parcial' { & $iscc /Q "/DVersao=$versao" "/DApp=$app" "/DFfmpeg=$ffmpeg" "/DDeno=$deno" "/DLicenca=$(Join-Path $Vitrola 'LICENSE')" "/DTerceiros=$terceiros" "/DParcial=$pasta\arquivos" "/DApaga=$pasta\apaga.iss" "/O$saida" (Join-Path $PSScriptRoot 'vitrola.iss') }
    Copy-Item "$pasta\parcial.json" $info
    $p = Get-Item (Join-Path $saida "Vitrola-$versao-parcial.exe")
    'pronto: {0} ({1:N1} MB)' -f $p.FullName, ($p.Length / 1MB)
  }
}
