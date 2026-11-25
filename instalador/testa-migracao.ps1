# O setup novo por cima da ultima versao publicada, como no PC de quem ja tem o app e recebe a atualizacao: instala o
# setup completo daquela versao (o do ritmelli-releases, conferido pelo hash do manifesto dela), deixa dados de quem usa
# e um microfone salvo no registro, roda o setup novo em silencio e confere o que muda de versao para versao. Por cima
# de uma versao de antes da troca de nome (#58: a 0.4.1 e as anteriores, com o vitrola.exe em Program Files\Vitrola),
# confere tambem a troca: a pasta nova, a de antes apagada, as tarefas, o registro, os atalhos, o firewall, a entrada de
# desinstalacao e, ao abrir, os dados de quem usa na pasta nova. No fim, o desinstalador tem de levar tudo.
# Precisa de administrador e de uma maquina sem o app. Roda no job testa-migracao da esteira e numa maquina de teste.
# Uso: testa-migracao.ps1 -Setup <Ritmelli-X.Y.Z-setup.exe> -Versao <X.Y.Z>
param([Parameter(Mandatory = $true)][string]$Setup, [Parameter(Mandatory = $true)][string]$Versao)
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

# com prazo, e nao com o -Wait: um setup parado numa pergunta (ninguem ve a tela) falha em 10 min, com o log
function Roda($exe, $nome, $extra = @()) {
  $log = Join-Path $temp "$nome.log"
  $p = Start-Process $exe -ArgumentList (@('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$log") + $extra) -PassThru
  if (-not $p.WaitForExit(600000)) { Stop-Process $p -Force; Get-Content $log -Tail 40; throw "o $nome nao terminou em 10 min" }
  if ($p.ExitCode -ne 0) { Get-Content $log -Tail 40; throw "o $nome saiu com $($p.ExitCode)" }
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
