# O MSYS2 dos compiladores (o ffmpeg\compila.ps1 e o bootloader\compila.ps1), numa pasta propria
# (%LOCALAPPDATA%\vitrola-msys2): nada se instala no Windows e nada pede administrador. Para tirar, e so apagar a pasta.
# Uso, no comeco de outro script: . (Join-Path $PSScriptRoot '..\msys2.ps1'); PreparaMsys2 '<pacotes do pacman>'
# Deixa $raiz (a pasta, onde o Baixa grava), $bash e $ucrt64 (a bin\ do gcc que gera exe do Windows).

# versao fixa, conferindo o hash. Para trocar de versao: a URL e o hash (o publicado, ou Get-FileHash)
$MSYS2 = @{ Url = 'https://github.com/msys2/msys2-installer/releases/download/2026-09-27/msys2-base-x86_64-20260927.sfx.exe'
            Sha = 'AD336CCCFDA47758B5E15CDA993FBBA421115CB0B126697DAEF1EE4DFE37209F' }

$raiz = Join-Path $env:LOCALAPPDATA 'vitrola-msys2'
$bash = Join-Path $raiz 'msys64\usr\bin\bash.exe'
$ucrt64 = Join-Path $raiz 'msys64\ucrt64\bin'

# baixa (se ainda nao esta aqui com o hash certo) e confere
function Baixa($p) {
  $arq = Join-Path $raiz (Split-Path $p.Url -Leaf)
  if (-not (Test-Path $arq) -or (Get-FileHash $arq -Algorithm SHA256).Hash -ne $p.Sha) {
    Write-Host "baixando $(Split-Path $arq -Leaf)..."
    Invoke-WebRequest $p.Url -OutFile $arq -UseBasicParsing
    $h = (Get-FileHash $arq -Algorithm SHA256).Hash
    if ($h -ne $p.Sha) { Remove-Item $arq; throw "$(Split-Path $arq -Leaf) veio com hash $h, e nao $($p.Sha)" }
  }
  return $arq
}

# o bash do MSYS2 no ambiente UCRT64, o do gcc que gera exe do Windows. Como no monta.ps1: dos programas de fora, vale
# so o codigo de saida
function Bash($nome, $cmd) {
  $antes = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $env:MSYSTEM = 'UCRT64'; $env:CHERE_INVOKING = '1'
  try { & $bash -lc $cmd 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $antes }
  if ($LASTEXITCODE -ne 0) { throw "$nome saiu com $LASTEXITCODE" }
}

# extrai o MSYS2 na primeira vez, atualiza e instala os pacotes que faltam
function PreparaMsys2($pacotes) {
  New-Item -ItemType Directory -Force $raiz | Out-Null
  if (-not (Test-Path $bash)) {
    $sfx = Baixa $MSYS2
    'extraindo o MSYS2...'
    & $sfx -y "-o$raiz" | Out-Null
    Bash 'msys2' 'true'   # a primeira vez cria as chaves do pacman
  }
  # a primeira atualizacao troca o proprio pacman e o runtime do MSYS2, e fecha o bash no meio, com erro: a segunda
  # volta termina o resto
  'atualizando o MSYS2...'
  try { Bash 'pacman' 'pacman -Syuu --noconfirm' } catch { 'o MSYS2 trocou o proprio nucleo e fechou; mais uma volta' }
  Bash 'pacman' 'pacman -Syuu --noconfirm'
  Bash 'pacman' "pacman -S --needed --noconfirm $pacotes"
}
