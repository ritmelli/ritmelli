# O setup novo por cima da ultima versao publicada, como no PC de quem ja tem o app e recebe a atualizacao: instala o
# setup completo daquela versao (o do ritmelli-releases, conferido pelo hash do manifesto dela), deixa dados de quem usa
# e um microfone salvo no registro, roda o setup novo em silencio e confere o que muda de versao para versao. Por cima
# de uma versao de antes da troca de nome (#58: a 0.4.1 e as anteriores, com o vitrola.exe em Program Files\Vitrola),
# confere tambem a troca: a pasta nova, a de antes apagada, as tarefas, o registro, os atalhos, o firewall, a entrada de
# desinstalacao e, ao abrir, os dados de quem usa na pasta nova. No fim, o desinstalador tem de levar tudo.
#
# The other scenarios (-Scenario) prove the protected folder rule of the setup (instalador/protegida.ps1) when the app
# has to change folders, starting from the 0.6.0, the last version whose setup took any /DIR=:
# - outside-program-files: the 0.6.0 installed with /DIR=C:\Ritmelli, then the new setup in silence (as the update task
#   runs it): the app ends up in Program Files\Ritmelli, with the tasks, the shortcut, the firewall rule and the
#   uninstall entry there, and the old ritmelli.exe renamed to ritmelli.exe.antigo;
# - dir-refused: the new setup with /DIR=C:\Ritmelli on a clean machine exits with 7 and installs nothing;
# - writable-folder: the 0.6.0 in Program Files\Ritmelli, made writable by Users, then the new setup: the app ends up in
#   Program Files\Ritmelli-2, and the old ritmelli.exe is renamed as above.
# Precisa de administrador e de uma maquina sem o app. Roda no job testa-migracao da esteira e numa maquina de teste.
# Uso: testa-migracao.ps1 -Setup <Ritmelli-X.Y.Z-setup.exe> -Versao <X.Y.Z> [-Scenario <name>] [-Vozes <vozes.json>]
param([Parameter(Mandatory = $true)][string]$Setup, [Parameter(Mandatory = $true)][string]$Versao,
      [ValidateSet('update', 'outside-program-files', 'dir-refused', 'writable-folder')][string]$Scenario = 'update',
      [string]$Vozes = (Join-Path $PSScriptRoot '..\vozes.json'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Setup = (Resolve-Path $Setup).Path
$app = "$env:ProgramFiles\Ritmelli"
$appAntes = "$env:ProgramFiles\Vitrola"
$temp = Join-Path $env:TEMP 'testa-migracao'
$id = '{320EB2BD-48BC-420D-8F52-C22F644E47D4}_is1'
$menu = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs"
New-Item -ItemType Directory -Force $temp | Out-Null
if ((Test-Path "$app\ritmelli.exe") -or (Test-Path "$appAntes\vitrola.exe")) { throw 'ja tem o app nesta maquina: rode numa maquina sem ele' }

# com prazo, e nao com o -Wait: um setup parado numa pergunta (ninguem ve a tela) falha em 10 min, com o log. Returns
# the exit code; the log is $temp\<nome>.log
function RunSetup($exe, $nome, $extra = @()) {
  $log = Join-Path $temp "$nome.log"
  $p = Start-Process $exe -ArgumentList (@('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$log") + $extra) -PassThru
  if (-not $p.WaitForExit(600000)) { Stop-Process $p -Force; Get-Content $log -Tail 40; throw "o $nome nao terminou em 10 min" }
  $p.ExitCode
}
function Roda($exe, $nome, $extra = @()) {
  $codigo = RunSetup $exe $nome $extra
  if ($codigo -ne 0) { Get-Content (Join-Path $temp "$nome.log") -Tail 40; throw "o $nome saiu com $codigo" }
}
$erros = New-Object System.Collections.Generic.List[string]
function Confere($ok, $msg) { if ($ok) { "ok   $msg" } else { "FALHA $msg"; $erros.Add($msg) } }
function Tarefa($caminho, $nome) { [bool](Get-ScheduledTask -TaskPath $caminho -TaskName $nome -ErrorAction SilentlyContinue) }
function PastaDeTarefas($nome) {
  $s = New-Object -ComObject Schedule.Service
  $s.Connect()
  try { $s.GetFolder("\$nome") | Out-Null; $true } catch { $false }
}
function Regra($nome) { netsh advfirewall firewall show rule name=$nome verbose 2>$null | Out-String }

# --- the scenarios where the app changes folders (see the top); each one ends the script
function TaskExe($caminho, $nome) {
  $t = Get-ScheduledTask -TaskPath $caminho -TaskName $nome -ErrorAction SilentlyContinue
  if ($t) { ($t.Actions | Select-Object -First 1).Execute }
}
function ShortcutTarget($lnk) { if (Test-Path $lnk) { (New-Object -ComObject WScript.Shell).CreateShortcut($lnk).TargetPath } }
function Uninstall { Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$id" -ErrorAction SilentlyContinue }
if ($Scenario -eq 'dir-refused') {
  $codigo = RunSetup $Setup "setup-$Versao-dir" @('/DIR=C:\Ritmelli')
  Confere ($codigo -eq 7) "the setup with /DIR=C:\Ritmelli exits with 7 ($codigo)"
  Confere (Select-String (Join-Path $temp "setup-$Versao-dir.log") -Pattern 'is outside' -SimpleMatch -Quiet) 'its log says the folder is outside Program Files'
  Confere (-not (Test-Path 'C:\Ritmelli') -and -not (Test-Path $app)) "neither C:\Ritmelli nor $app was created"
  Confere (-not (Uninstall)) 'there is no uninstall entry'
  Confere (-not (Test-Path "$menu\Ritmelli.lnk")) 'there is no Start menu shortcut'
  Confere (-not ((Regra 'Ritmelli') -match 'Ritmelli')) 'there is no Ritmelli firewall rule'
  Confere (-not (Tarefa '\' 'Ritmelli Atualiza') -and -not (Tarefa '\Ritmelli\' 'Microfone')) 'there is no task'
}
if ($Scenario -eq 'outside-program-files' -or $Scenario -eq 'writable-folder') {
  if ($Scenario -eq 'outside-program-files') { $velha = 'C:\Ritmelli'; $nova = $app } else { $velha = $app; $nova = "$app-2" }
  if ((Test-Path $velha) -or (Test-Path $nova)) { throw "$velha or $nova already exists: run on a clean machine" }
  # the 0.6.0 from ritmelli-releases, checked against the hash in its manifest
  $m6 = Invoke-RestMethod 'https://github.com/ritmelli/ritmelli-releases/releases/download/v0.6.0/manifest.json'
  $setup6 = Join-Path $temp 'setup-0.6.0.exe'
  Invoke-WebRequest $m6.instalador.url -OutFile $setup6 -UseBasicParsing
  if ((Get-FileHash $setup6 -Algorithm SHA256).Hash.ToLower() -ne $m6.instalador.sha256) { throw "the 0.6.0 setup doesn't match its manifest" }
  $extra6 = @('/metricas=0')
  if ($Scenario -eq 'outside-program-files') { $extra6 += "/DIR=$velha" }
  Roda $setup6 'setup-0.6.0' $extra6
  if (-not (Test-Path "$velha\ritmelli.exe")) { throw "the 0.6.0 is not in $velha" }
  if ($Scenario -eq 'writable-folder') {
    icacls $velha /grant '*S-1-5-32-545:(OI)(CI)M' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls couldn't make $velha writable by Users" }
  }
  "the 0.6.0 is installed in $velha"
  $voiceList = Get-Content $Vozes -Raw -Encoding UTF8 | ConvertFrom-Json
  $expected = @(foreach ($r in @($voiceList.engine) + @($voiceList.vozes)) { foreach ($a in $r.arquivos) { [pscustomobject]@{ Path = "$($r.tag)\$($a.nome)"; Sha = $a.sha256 } } })
  $copiable = @($expected | Where-Object { (Test-Path "$velha\vozes\$($_.Path)") -and (Get-FileHash "$velha\vozes\$($_.Path)" -Algorithm SHA256).Hash -eq $_.Sha } | ForEach-Object { $_.Path })
  $changed = $null
  if ($Scenario -eq 'writable-folder') {
    $changed = $copiable | Sort-Object { $_ -notlike '*\voz.json' } | Select-Object -First 1
    Add-Content "$velha\vozes\$changed" ' ' -Encoding ascii
  }
  $locked = $copiable | Where-Object { $_ -ne $changed } | Sort-Object | Select-Object -Last 1
  $toCopy = @($copiable | Where-Object { $_ -ne $changed -and $_ -ne $locked })
  if (-not $locked -or -not $toCopy.Count) { throw "$($copiable.Count) voice files of the current vozes.json are in $velha\vozes: the test needs one to lock and one to copy" }
  $toDownload = @($expected | ForEach-Object { $_.Path } | Where-Object { $toCopy -notcontains $_ })
  $lock = [IO.File]::Open("$velha\vozes\$locked", 'Open', 'Read', 'None')
  try { Roda $Setup "setup-$Versao" } finally { $lock.Dispose() }
  $log = Get-Content (Join-Path $temp "setup-$Versao.log")
  $copied = @($log | Select-String -Pattern 'vozes: copied (\S+) from' | ForEach-Object { $_.Matches[0].Groups[1].Value })
  $downloaded = @($log | Select-String -Pattern 'vozes: downloading (\S+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value })
  Confere ((($toCopy | Sort-Object) -join '|') -eq (($copied | Sort-Object) -join '|')) "the setup copied the $($toCopy.Count) matching voice files from $velha with their sha256 checked ($($copied.Count) copied)"
  Confere ((($toDownload | Sort-Object) -join '|') -eq (($downloaded | Sort-Object) -join '|')) "the setup downloaded only the $($toDownload.Count) voice files it couldn't copy ($($downloaded -join ', '))"
  Confere ($log | Select-String -Pattern "vozes: could not copy $([regex]::Escape("$velha\vozes\$locked")), downloading it" -Quiet) "the $locked it couldn't read was logged and downloaded"
  if ($changed) {
    Confere ($log | Select-String -Pattern "$([regex]::Escape("$velha\vozes\$changed")) does not match its sha256" -Quiet) "the changed $changed was refused"
  }
  $wrong = @($expected | Where-Object { -not (Test-Path "$nova\vozes\$($_.Path)") -or (Get-FileHash "$nova\vozes\$($_.Path)" -Algorithm SHA256).Hash -ne $_.Sha })
  Confere ($wrong.Count -eq 0) "every voice file in $nova\vozes has its sha256 ($($wrong.Path -join ', '))"
  $exe = "$nova\ritmelli.exe"
  Confere ((Test-Path $exe) -and (Get-Item $exe).VersionInfo.ProductVersion -eq $Versao) "the ritmelli.exe in $nova is the $Versao"
  $u = Uninstall
  Confere ($u -and $u.InstallLocation.TrimEnd('\') -eq $nova -and $u.UninstallString -eq "`"$nova\unins000.exe`"" -and (Test-Path "$nova\unins000.exe")) "the uninstall entry points to $nova ($($u.InstallLocation), $($u.UninstallString))"
  $atualiza = TaskExe '\' 'Ritmelli Atualiza'
  Confere ($atualiza -eq $exe) "the Ritmelli Atualiza task runs $exe ($atualiza)"
  $microfone = TaskExe '\Ritmelli\' 'Microfone'
  Confere ($microfone -eq $exe) "the \Ritmelli\Microfone task runs $exe ($microfone)"
  $atalho = ShortcutTarget "$menu\Ritmelli.lnk"
  Confere ($atalho -eq $exe) "the Start menu shortcut opens $exe ($atalho)"
  $regra = Regra 'Ritmelli'
  Confere (($regra -match [regex]::Escape($exe)) -and -not ($regra -match [regex]::Escape("$velha\ritmelli.exe"))) "the Ritmelli firewall rule allows $exe, and none allows $velha\ritmelli.exe"
  Confere ((Test-Path "$velha\ritmelli.exe.antigo") -and -not (Test-Path "$velha\ritmelli.exe")) "the ritmelli.exe left in $velha is now ritmelli.exe.antigo"
}
if ($Scenario -ne 'update') {
  if ($erros.Count) { throw "$($erros.Count) checks failed: $($erros -join '; ')" }
  "scenario ${Scenario}: every check passed"
  exit 0
}

# --- a ultima versao publicada, com a escolha dos dados de uso desligada (/metricas=0)
$base = 'https://github.com/ritmelli/ritmelli-releases/releases/latest/download'
$ma = Invoke-RestMethod "$base/manifest.json"
$de = $ma.versao
$setupAntes = Join-Path $temp 'anterior-setup.exe'
Invoke-WebRequest $ma.instalador.url -OutFile $setupAntes -UseBasicParsing
if ((Get-FileHash $setupAntes -Algorithm SHA256).Hash.ToLower() -ne $ma.instalador.sha256) { throw "o setup da $de nao bate com o manifesto dela" }
Roda $setupAntes "setup-$de" @('/metricas=0')
$antesDoNome = Test-Path "$appAntes\vitrola.exe"
if ($antesDoNome) { $dadosAntes = "$env:LOCALAPPDATA\Vitrola"; $regAntes = 'HKLM:\SOFTWARE\Vitrola' } else { $dadosAntes = "$env:LOCALAPPDATA\Ritmelli"; $regAntes = 'HKLM:\SOFTWARE\Ritmelli' }
"a $de instalada ($(if ($antesDoNome) { 'de antes da troca de nome' } else { 'ja com o nome Ritmelli' }))"

# o que quem usa tem: a biblioteca e o original de um microfone (o que o desinstalador devolve)
New-Item -ItemType Directory -Force "$dadosAntes\library" | Out-Null
Set-Content "$dadosAntes\library\marca-migracao.txt" 'a biblioteca de quem usa' -Encoding utf8
$mic = "$regAntes\Microfone\{teste-migracao}"
New-Item -Force $mic | Out-Null
New-ItemProperty $mic -Name 'original' -Value 'efeito-de-fabrica' -PropertyType String -Force | Out-Null

# --- o setup novo por cima, em silencio, como a atualizacao automatica
Roda $Setup "setup-$Versao"
Confere (Test-Path "$app\ritmelli.exe") "o ritmelli.exe esta em $app"
Confere ((Get-Item "$app\ritmelli.exe").VersionInfo.ProductVersion -eq $Versao) "o ritmelli.exe e a $Versao"
$desinstalar = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$id"
Confere ($desinstalar.DisplayName -eq 'Ritmelli' -and $desinstalar.InstallLocation.TrimEnd('\') -eq $app) "Programas e Recursos: Ritmelli, em $app ($($desinstalar.DisplayName), $($desinstalar.InstallLocation))"
Confere (Tarefa '\' 'Ritmelli Atualiza') 'a tarefa Ritmelli Atualiza existe'
Confere (Tarefa '\Ritmelli\' 'Microfone') 'a tarefa \Ritmelli\Microfone existe'
Confere ((Get-ItemProperty 'HKLM:\SOFTWARE\Ritmelli' -Name Metricas -ErrorAction SilentlyContinue).Metricas -eq 0) 'a escolha dos dados de uso (0) veio para o HKLM\SOFTWARE\Ritmelli'
Confere ((Get-ItemProperty 'HKLM:\SOFTWARE\Ritmelli\Microfone\{teste-migracao}' -ErrorAction SilentlyContinue).original -eq 'efeito-de-fabrica') 'o original do microfone veio para o HKLM\SOFTWARE\Ritmelli\Microfone'
Confere (Test-Path "$menu\Ritmelli.lnk") 'o atalho Ritmelli no menu Iniciar'
Confere ((Regra 'Ritmelli') -match [regex]::Escape("$app\ritmelli.exe")) 'a regra Ritmelli do firewall libera o ritmelli.exe novo'
if ($antesDoNome) {
  Confere (-not (Test-Path $appAntes)) "a pasta de antes ($appAntes) saiu"
  Confere (-not (Tarefa '\' 'Vitrola Atualiza')) 'a tarefa Vitrola Atualiza saiu'
  Confere (-not (Tarefa '\Vitrola\' 'Microfone')) 'a tarefa \Vitrola\Microfone saiu'
  Confere (-not (PastaDeTarefas 'Vitrola')) 'a pasta \Vitrola do Agendador de Tarefas saiu'
  Confere (-not (Test-Path 'HKLM:\SOFTWARE\Vitrola')) 'o HKLM\SOFTWARE\Vitrola saiu'
  Confere (-not (Test-Path "$menu\Vitrola.lnk")) 'o atalho Vitrola do menu Iniciar saiu'
  Confere (-not ((Regra 'Vitrola') -match 'Vitrola')) 'a regra Vitrola do firewall saiu'
}

# --- o app abre na versao nova, com os dados de quem usa na pasta nova e a escolha dos dados de uso de antes
$vit = Start-Process "$app\ritmelli.exe" -ArgumentList '--no-browser' -PassThru
$estado = $null
for ($i = 0; $i -lt 90 -and -not $vit.HasExited -and -not $estado; $i++) {
  try { $estado = Invoke-RestMethod 'http://127.0.0.1:8799/api/state' -TimeoutSec 2 } catch { Start-Sleep 1 }
}
if (-not $estado) {
  Get-Content "$env:LOCALAPPDATA\Ritmelli\logs\server.log", "$env:LOCALAPPDATA\Ritmelli\logs\server.err" -ErrorAction SilentlyContinue
  throw 'o Ritmelli nao respondeu em 90 s'
}
Confere ($estado.versao -eq $Versao) "o Ritmelli respondeu a versao $($estado.versao)"
Confere (Test-Path "$env:LOCALAPPDATA\Ritmelli\library\marca-migracao.txt") 'a biblioteca de quem usa esta na pasta nova'
if ($antesDoNome) { Confere (-not (Test-Path "$env:LOCALAPPDATA\Vitrola")) 'a pasta de dados de antes saiu' }
$met = Invoke-RestMethod 'http://127.0.0.1:8799/api/metricas' -TimeoutSec 5
Confere ($met.situacao -eq 'desligada') "os dados de uso seguem desligados, como a pessoa escolheu antes ($($met.situacao))"
# desligada nao ve o aviso de novo, com qualquer versao do texto: a escolha que vale segue a do instalador de antes
Confere ($met.texto -ge 1 -and $met.texto_atual -ge $met.texto) "a versao do texto vem da escolha do instalador de antes ($($met.texto) de $($met.texto_atual))"
Invoke-RestMethod 'http://127.0.0.1:8799/api/shutdown' -Method Post -ContentType 'application/json' -Body '{}' | Out-Null
if (-not $vit.WaitForExit(30000)) { throw 'o Ritmelli nao saiu em 30 s depois do Desligar' }

# --- o desinstalador leva tudo (ele se copia para a pasta temporaria e roda de la: o fim se confere pelo que apaga)
Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
for ($i = 0; $i -lt 120 -and (Test-Path "$app\ritmelli.exe"); $i++) { Start-Sleep 1 }
Start-Sleep 3
Confere (-not (Test-Path "$app\ritmelli.exe")) 'o desinstalador tirou o ritmelli.exe'
Confere (-not (Tarefa '\' 'Ritmelli Atualiza') -and -not (Tarefa '\Ritmelli\' 'Microfone')) 'o desinstalador tirou as tarefas'
Confere (-not ((Regra 'Ritmelli') -match 'Ritmelli')) 'o desinstalador tirou a regra do firewall'
Remove-Item 'HKLM:\SOFTWARE\Ritmelli\Microfone\{teste-migracao}' -Force -ErrorAction SilentlyContinue

if ($erros.Count) { throw "$($erros.Count) conferencias falharam: $($erros -join '; ')" }
"a $Versao entrou por cima da $de, os dados e as escolhas vieram junto e o desinstalador levou tudo"
exit 0
