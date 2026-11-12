# A atualizacao parcial como no PC de quem ja tem a versao anterior. Numa maquina sem a Vitrola, confere que a parcial
# recusa sozinha; depois instala o setup completo da versao de onde ela compara (o do ritmelli-releases, conferido pelo
# hash do manifesto daquela versao), roda a parcial em silencio, como o app roda, e confere que a pasta do app ficou
# igual a lista de arquivos do manifesto novo: cada arquivo pelo hash, e nada sobrando na _internal\ nem na bin\. No
# fim, a Vitrola tem de abrir na versao nova, e o desinstalador tem de levar tudo, inclusive o que a parcial trouxe.
# Precisa de administrador e de uma maquina sem a Vitrola. Roda no job testa-parcial da esteira e numa maquina de teste.
# Uso: testa-parcial.ps1 -Manifesto <manifest.json> -Parcial <Vitrola-X.Y.Z-parcial.exe>
param([Parameter(Mandatory = $true)][string]$Manifesto, [Parameter(Mandatory = $true)][string]$Parcial)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$m = Get-Content $Manifesto -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $m.parcial) { throw "o $Manifesto nao tem a parcial" }
$Parcial = (Resolve-Path $Parcial).Path
$de = $m.parcial.de
$app = "$env:ProgramFiles\Vitrola"
$temp = Join-Path $env:TEMP 'testa-parcial'
New-Item -ItemType Directory -Force $temp | Out-Null
if (Test-Path "$app\vitrola.exe") { throw "ja tem uma Vitrola em $app`: rode numa maquina sem ela" }

# com prazo, e nao com o -Wait: um setup parado numa pergunta (ninguem ve a tela) falha em 10 min, com o log
function Roda($exe, $nome, $espera = 0) {
  $log = Join-Path $temp "$nome.log"
  $p = Start-Process $exe -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$log" -PassThru
  if (-not $p.WaitForExit(600000)) { Stop-Process $p -Force; Get-Content $log -Tail 40; throw "o $nome nao terminou em 10 min" }
  if ($p.ExitCode -ne $espera) { Get-Content $log -Tail 40; throw "o $nome saiu com $($p.ExitCode), e nao $espera" }
}
function Versao { (Get-Item "$app\vitrola.exe").VersionInfo.ProductVersion }

# 7: o PrepareToInstall do vitrola.iss recusou
Roda $Parcial 'parcial-sem-app' 7
if (Test-Path "$app\vitrola.exe") { throw 'a parcial recusou, mas deixou um vitrola.exe' }
'sem a Vitrola instalada, a parcial recusa'

$base = "https://github.com/ritmelli/ritmelli-releases/releases/download/v$de"
$ma = Invoke-RestMethod "$base/manifest.json"
$setup = Join-Path $temp "Vitrola-$de-setup.exe"
Invoke-WebRequest $ma.instalador.url -OutFile $setup -UseBasicParsing
if ((Get-FileHash $setup -Algorithm SHA256).Hash.ToLower() -ne $ma.instalador.sha256) { throw "o setup da $de nao bate com o manifesto dela" }
Roda $setup "setup-$de"
if ((Versao) -ne $de) { throw "o setup da $de instalou a $(Versao)" }
"a $de instalada"

Roda $Parcial 'parcial'
$erros = New-Object System.Collections.Generic.List[string]
$lista = @{}
foreach ($f in $m.arquivos) {
  $lista[$f.caminho.ToLower()] = $true
  $arq = Join-Path $app ($f.caminho -replace '/', '\')
  if (-not (Test-Path -LiteralPath $arq)) { $erros.Add("falta $($f.caminho)"); continue }
  if ((Get-FileHash -LiteralPath $arq -Algorithm SHA256).Hash.ToLower() -ne $f.sha256) { $erros.Add("diferente: $($f.caminho)") }
}
foreach ($raiz in '_internal', 'bin') {
  Get-ChildItem -LiteralPath (Join-Path $app $raiz) -Recurse -File | ForEach-Object {
    $c = $_.FullName.Substring($app.Length + 1).Replace('\', '/')
    if (-not $lista.ContainsKey($c.ToLower())) { $erros.Add("sobrou $c") }
  }
}
if ($erros.Count) { $erros | Select-Object -First 30; throw "a pasta do app nao ficou igual a do manifesto da $($m.versao): $($erros.Count) diferencas" }
if ((Versao) -ne $m.versao) { throw "depois da parcial, o vitrola.exe diz $(Versao), e nao $($m.versao)" }
"depois da parcial: os $(@($m.arquivos).Count) arquivos iguais aos do manifesto da $($m.versao), e nada sobrando"

$vit = Start-Process "$app\vitrola.exe" -ArgumentList '--no-browser' -PassThru
$estado = $null
for ($i = 0; $i -lt 90 -and -not $vit.HasExited -and -not $estado; $i++) {
  try { $estado = Invoke-RestMethod 'http://127.0.0.1:8799/api/state' -TimeoutSec 2 } catch { Start-Sleep 1 }
}
if (-not $estado) {
  Get-Content "$env:LOCALAPPDATA\Vitrola\logs\server.log", "$env:LOCALAPPDATA\Vitrola\logs\server.err" -ErrorAction SilentlyContinue
  throw 'a Vitrola nao respondeu em 90 s'
}
if ($estado.versao -ne $m.versao) { throw "a Vitrola respondeu a versao $($estado.versao), e nao a $($m.versao)" }
"a Vitrola abriu e respondeu a $($estado.versao)"

# o desinstalador se copia para a pasta temporaria e roda de la: o fim se confere pelo que ele apaga. A _internal\
# inteira tem de sair: o log de desinstalacao da parcial soma ao do setup completo
Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
for ($i = 0; $i -lt 120 -and ((Test-Path "$app\vitrola.exe") -or (Test-Path "$app\_internal")); $i++) { Start-Sleep 1 }
if ((Test-Path "$app\vitrola.exe") -or (Test-Path "$app\_internal")) {
  Get-ChildItem $app -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 20 -ExpandProperty FullName
  throw 'o desinstalador nao tirou tudo em 2 min'
}
'a parcial recusou sem a Vitrola, atualizou por cima da anterior, abriu e saiu inteira no desinstalador'
