# Compila o bootloader do PyInstaller (o comeco do vitrola.exe, que acha e abre o Python da _internal\) da fonte da
# versao de pyinstaller.psd1, com o gcc do MSYS2 (UCRT64). O bootloader pronto que vem no pip e o mesmo de milhares de
# executaveis, e parte deles e malware: o antivirus que reconhece pelo comeco do arquivo marca a Vitrola junto.
# Compilado aqui, o comeco e so nosso. Sai em bin\ (run.exe, runw.exe e os _d, de depuracao, com a FONTE.txt), que vai
# no git; o monta.ps1 instala o PyInstaller com eles no lugar dos prontos. Rodar de novo so ao trocar a versao.
# Uso: compila.ps1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # sem a barra, o Invoke-WebRequest do PowerShell 5 baixa muito mais rapido
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

. (Join-Path $PSScriptRoot '..\msys2.ps1')
$PYI = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'pyinstaller.psd1')
$saida = Join-Path $PSScriptRoot 'bin'
$EXES = 'run.exe', 'runw.exe', 'run_d.exe', 'runw_d.exe'

# como no monta.ps1: dos programas de fora, vale so o codigo de saida
function Roda($nome, [scriptblock]$cmd) {
  $antes = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $cmd 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $antes }
  if ($LASTEXITCODE -ne 0) { throw "$nome saiu com $LASTEXITCODE" }
}

PreparaMsys2 'mingw-w64-ucrt-x86_64-gcc'
$tar = Baixa $PYI
# a fonte limpa a cada vez: o waf grava o resultado dentro dela, por cima dos bootloaders prontos. Pelo tarfile do
# Python, e nao pelo tar do Windows, que nao cria os links simbolicos do sdist (o tarfile copia o arquivo)
$fonte = Join-Path $raiz "pyinstaller-$($PYI.Versao)"
if (Test-Path $fonte) { Remove-Item $fonte -Recurse -Force }
Roda 'tarfile' { python -c "import sys, tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2], filter='data')" $tar $raiz }

# o waf pelo python do Windows, com o gcc do UCRT64 na frente do PATH (--gcc: sem ele, o waf procura o MSVC)
"compilando o bootloader do PyInstaller $($PYI.Versao)..."
$env:PATH = "$ucrt64;$env:PATH"
Push-Location (Join-Path $fonte 'bootloader')
try { Roda 'waf' { python ./waf configure all --gcc } } finally { Pop-Location }

New-Item -ItemType Directory -Force $saida | Out-Null
$feitos = Join-Path $fonte 'PyInstaller\bootloader\Windows-64bit-intel'
foreach ($e in $EXES) { Copy-Item (Join-Path $feitos $e) $saida -Force }
$gcc = (& (Join-Path $ucrt64 'gcc.exe') --version | Select-Object -First 1)
$hashes = foreach ($e in $EXES) { '{0}  {1}' -f (Get-FileHash (Join-Path $saida $e) -Algorithm SHA256).Hash.ToLower(), $e }
@(
  "Bootloader do PyInstaller $($PYI.Versao) ($($EXES -join ', ')), para a Vitrola."
  'Licenca: GPL 2 ou posterior, com a excecao do bootloader (o programa gerado pode ter qualquer licenca). O texto e o'
  'COPYING.txt do PyInstaller, que vai no TERCEIROS.txt do app.'
  "Fonte: $(Split-Path $PYI.Url -Leaf), sem mudancas, do PyPI (sha256 $($PYI.Sha.ToLower()))."
  "Compilado no MSYS2 UCRT64 com $gcc, pelo compila.ps1: python ./waf configure all --gcc"
  ''
  $hashes
) | Set-Content (Join-Path $saida 'FONTE.txt') -Encoding ASCII

foreach ($e in $EXES) { '{0}: {1:N0} KB' -f $e, ((Get-Item (Join-Path $saida $e)).Length / 1KB) }
