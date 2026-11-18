# A atualizacao automatica (atualizador.py) numa maquina limpa, de ponta a ponta. O setup instala e cria a tarefa
# "Vitrola Atualiza" (SYSTEM, que quem usa o PC roda e nao muda); um manifesto de teste anuncia uma versao a mais, com o
# mesmo setup num servidor local e uma chave de teste no HKLM\SOFTWARE\Vitrola\Atualizador; com a Vitrola aberta, a
# tarefa baixa, confere e nao instala; o Instalar agora fecha a Vitrola, a tarefa instala em silencio e a Vitrola abre
# de novo sozinha, como quem usa o PC (e nao como SYSTEM). No fim, o desinstalador apaga a tarefa e a pasta da
# atualizacao. O setup e o da versao instalada, entao a versao nao muda: o que se confere e o caminho inteiro.
# Precisa de administrador, do Python com o pycryptodomex (o manifesto de teste) e de uma maquina sem a Vitrola. Roda no
# job testa-atualizador da esteira.
# Uso: testa-atualizador.ps1 -Setup <Vitrola-X.Y.Z-setup.exe> -Manifesto <manifest.json do build>
param([Parameter(Mandatory = $true)][string]$Setup, [Parameter(Mandatory = $true)][string]$Manifesto)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Setup = (Resolve-Path $Setup).Path
$Manifesto = (Resolve-Path $Manifesto).Path
$app = "$env:ProgramFiles\Vitrola"
$pasta = "$app\atualizacao"
$tarefa = 'Vitrola Atualiza'
$reg = 'HKLM:\SOFTWARE\Vitrola\Atualizador'
$api = 'http://127.0.0.1:8799/api'
$temp = Join-Path $env:TEMP 'testa-atualizador'
$www = Join-Path $temp 'www'
New-Item -ItemType Directory -Force $www | Out-Null
if (Test-Path "$app\vitrola.exe") { throw "ja tem uma Vitrola em $app`: rode numa maquina sem ela" }

# o que explica uma falha: o log da tarefa, o estado dela e os logs da Vitrola
function Falha($msg) {
  foreach ($f in "$pasta\atualizador.log", "$pasta\estado.json", "$env:LOCALAPPDATA\Vitrola\logs\server.log",
                 "$env:LOCALAPPDATA\Vitrola\logs\server.err") {
    if (Test-Path $f) { "--- $f"; Get-Content $f -Tail 40 }
  }
  throw $msg
}
function Estado { try { Get-Content "$pasta\estado.json" -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $null } }
function Responde { try { Invoke-RestMethod "$api/state" -TimeoutSec 2 } catch { $null } }
# roda o bloco de segundo em segundo ate ele dar algo, ou ate o prazo (e ai da $null)
function Espera($segundos, [scriptblock]$cond) {
  $fim = (Get-Date).AddSeconds($segundos)
  while ((Get-Date) -lt $fim) {
    $r = & $cond
    if ($r) { return $r }
    Start-Sleep 1
  }
  return $null
}
# o codigo de saida de cada vitrola.exe que o setup rodou (o [Run] do vitrola.iss), do log dele
function Saidas($log) {
  $saidas = [ordered]@{}
  $param = $null
  foreach ($l in Get-Content $log) {
    if ($l -match 'Parameters: (.*)$') { $param = $Matches[1] }
    elseif ($l -match 'Process exit code: (\d+)' -and $param) { $saidas[$param] = [int]$Matches[1]; $param = $null }
  }
  return $saidas
}

# --- o setup, como quem instala
$log1 = Join-Path $temp 'setup.log'
$p = Start-Process $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$log1" -PassThru
if (-not $p.WaitForExit(600000)) { Stop-Process $p -Force; Get-Content $log1 -Tail 40; throw 'o setup nao terminou em 10 min' }
if ($p.ExitCode -ne 0) { Get-Content $log1 -Tail 40; throw "o setup saiu com $($p.ExitCode)" }
$versao = (Get-Item "$app\vitrola.exe").VersionInfo.ProductVersion
"a $versao instalada"

# --- a tarefa: SYSTEM, o vitrola.exe do app, e quem usa o PC so le e roda
$t = Get-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue
if (-not $t) { throw "o setup nao criou a tarefa $tarefa" }
if ($t.Principal.UserId -notin 'SYSTEM', 'S-1-5-18') { throw "a tarefa roda como $($t.Principal.UserId), e nao como SYSTEM" }
$acao = $t.Actions | Select-Object -First 1
if ($acao.Execute -ne "$app\vitrola.exe" -or $acao.Arguments -ne '--atualizador') { throw "a tarefa roda $($acao.Execute) $($acao.Arguments)" }
$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$sddl = $svc.GetFolder('\').GetTask($tarefa).GetSecurityDescriptor(4)
$sd = New-Object System.Security.AccessControl.RawSecurityDescriptor -ArgumentList $sddl
# gravar, apagar e mudar a permissao, nas formas especifica e generica
$escreve = 0x2 -bor 0x4 -bor 0x10 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x10000000 -bor 0x40000000
$usuarios = 'S-1-5-11', 'S-1-5-32-545', 'S-1-1-0', 'S-1-5-4'  # Authenticated Users, Users, Everyone, Interactive
$roda = $false
foreach ($ace in $sd.DiscretionaryAcl) {
  if ($ace.AceType -ne 'AccessAllowed' -or $ace.SecurityIdentifier.Value -notin $usuarios) { continue }
  if ($ace.AccessMask -band $escreve) { throw "quem usa o PC pode mudar a tarefa: $sddl" }
  if ($ace.AccessMask -band (0x20000000 -bor 0x20)) { $roda = $true }  # GENERIC_EXECUTE ou FILE_EXECUTE
}
if (-not $roda) { throw "quem usa o PC nao pode rodar a tarefa (a Vitrola nao dispara a atualizacao): $sddl" }
"a tarefa roda como SYSTEM o $($acao.Execute) $($acao.Arguments), e quem usa o PC so le e roda: $sddl"

# --- uma versao a mais, assinada por uma chave de teste, com o mesmo setup num servidor local
$n = $versao.Split('.')
$nova = "$($n[0]).$($n[1]).$([int]$n[2] + 1)"
$porta = 8765
Copy-Item $Setup "$www\setup.exe"
$chave = python -I "$PSScriptRoot\atualizacao\manifesto_de_teste.py" --manifesto $Manifesto --versao $nova `
  --url "http://127.0.0.1:$porta/setup.exe" --saida $www
if ($LASTEXITCODE -ne 0) { throw "o manifesto de teste saiu com $LASTEXITCODE" }
$srv = Start-Process python -ArgumentList '-I', '-m', 'http.server', $porta, '--bind', '127.0.0.1', '--directory', "`"$www`"" `
  -PassThru -WindowStyle Hidden
if (-not (Espera 30 { try { Invoke-WebRequest "http://127.0.0.1:$porta/manifest.json" -UseBasicParsing -TimeoutSec 2 } catch { $null } })) {
  throw 'o servidor do manifesto de teste nao subiu'
}
New-Item -Path $reg -Force | Out-Null
New-ItemProperty -Path $reg -Name Manifesto -Value "http://127.0.0.1:$porta/manifest.json" -PropertyType String -Force | Out-Null
New-ItemProperty -Path $reg -Name Chave -Value "$chave".Trim() -PropertyType String -Force | Out-Null
New-ItemProperty -Path $reg -Name SoHttps -Value 0 -PropertyType DWord -Force | Out-Null
"a $nova anunciada em http://127.0.0.1:$porta, com a chave de teste no HKLM"

try {
  # --- com a Vitrola aberta, a tarefa baixa e confere, e nao instala
  $vit = Start-Process "$app\vitrola.exe" -ArgumentList '--no-browser' -PassThru
  if (-not (Espera 90 { Responde })) { Falha 'a Vitrola nao respondeu em 90 s' }
  if (-not (Espera 30 { (Invoke-RestMethod "$api/atualizacao").automatica })) {
    Falha 'a Vitrola nao viu a tarefa: a atualizacao dela nao ficou automatica'
  }
  schtasks /run /tn $tarefa | Out-Null
  if ($LASTEXITCODE -ne 0) { Falha "o schtasks /run saiu com $LASTEXITCODE" }
  if (-not (Espera 300 { $s = Estado; if ($s -and $s.estado -eq 'pronta') { $s } })) {
    Falha 'a tarefa nao deixou a versao nova pronta em 5 min'
  }
  if (-not (Espera 90 { Select-String "$pasta\atualizador.log" -Pattern 'Vitrola is open' -Quiet -ErrorAction SilentlyContinue })) {
    Falha 'a tarefa nao esperou a Vitrola fechar'
  }
  if (-not (Test-Path "$pasta\Vitrola-$nova-setup.exe")) { Falha "a tarefa nao deixou o Vitrola-$nova-setup.exe na $pasta" }
  if ((Estado).estado -ne 'pronta' -or $vit.HasExited -or -not (Responde)) { Falha 'a tarefa mexeu na Vitrola aberta' }
  $at = Invoke-RestMethod "$api/atualizacao"
  if ($at.estado -ne 'pronta' -or $at.nova.versao -ne $nova) { Falha "a tela nao ve a $nova pronta: $($at | ConvertTo-Json -Compress -Depth 4)" }
  "com a Vitrola aberta, a tarefa baixou e conferiu a $nova, e a tela mostra ela pronta"

  # --- o Instalar agora: a Vitrola fecha, a tarefa instala em silencio e a Vitrola abre de novo
  try {
    Invoke-RestMethod "$api/atualizacao/instalar" -Method Post -ContentType 'application/json' -Body '{}' | Out-Null
  } catch {
    "o Instalar agora respondeu: $($_.Exception.Message) $($_.ErrorDetails.Message)"  # a Vitrola fechando no meio
  }
  if (-not $vit.WaitForExit(60000)) { Falha 'a Vitrola nao fechou em 60 s depois do Instalar agora' }
  $s = Espera 120 { $e = Estado; if ($e -and $e.estado -eq 'instalando') { $e } }
  if (-not $s) { Falha 'a tarefa nao comecou a instalar em 2 min depois de a Vitrola fechar' }
  if (-not (Espera 600 { -not (Get-Process -Id $s.pid -ErrorAction SilentlyContinue) })) { Falha 'o instalador nao terminou em 10 min' }
  $log2 = "$pasta\$($s.log)"
  if (-not (Select-String $log2 -Pattern 'Installation process succeeded' -Quiet)) { Get-Content $log2 -Tail 40; Falha 'o instalador da tarefa nao terminou bem' }
  # como SYSTEM, cada vitrola.exe do [Run] tem de sair como saiu na instalacao de quem usa o PC
  $antes, $depois = (Saidas $log1), (Saidas $log2)
  foreach ($k in $depois.Keys) {
    "  $k -> $($depois[$k]) (na instalacao comum, $($antes[$k]))"
    if ($depois[$k] -ne 0 -and $antes[$k] -eq 0) { Falha "como SYSTEM, o vitrola.exe $k saiu com $($depois[$k])" }
  }
  "a tarefa instalou em silencio: $($s.log)"
  if (-not (Espera 180 { Responde })) { Falha 'a Vitrola nao abriu de novo em 3 min depois de instalar' }
  $dono = (Get-Process -Id (Get-NetTCPConnection -LocalPort 8799 -State Listen | Select-Object -First 1).OwningProcess `
    -IncludeUserName).UserName
  if ($dono -notlike "*\$env:USERNAME") { Falha "a Vitrola abriu de novo como $dono, e nao como $env:USERNAME" }
  "a Vitrola abriu de novo sozinha, como $dono"
} finally {
  Stop-Process $srv -Force -ErrorAction SilentlyContinue
  Remove-Item $reg -Force -ErrorAction SilentlyContinue
}

# --- o desinstalador leva a tarefa e a pasta da atualizacao. Ele se copia para a pasta temporaria e roda de la: o fim se
# confere pelo que ele apaga
Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
if (-not (Espera 120 { -not (Test-Path "$app\vitrola.exe") -and -not (Test-Path $pasta) })) {
  Get-ChildItem $app -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 20 -ExpandProperty FullName
  throw 'o desinstalador nao tirou o app e a pasta da atualizacao em 2 min'
}
if (Get-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue) { throw 'o desinstalador deixou a tarefa' }
'a tarefa baixou com a Vitrola aberta, instalou quando ela fechou, a Vitrola abriu de novo sozinha e o desinstalador levou tudo'
