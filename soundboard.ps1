# Liga, desliga e mostra o soundboard do VRChat (vitrola.py, o mesmo ponto de entrada do executavel) fora do terminal:
# processo destacado e escondido, log em %LOCALAPPDATA%\Vitrola\logs. Uso: soundboard.ps1 [start|stop|status|open] [-Port 8799] [-NoBrowser]
param([ValidateSet('start', 'stop', 'status', 'open')][string]$Cmd = 'start', [int]$Port = 8799, [switch]$NoBrowser)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = "http://127.0.0.1:$Port"

function Get-State { try { Invoke-RestMethod "$base/api/state" -TimeoutSec 2 } catch { $null } }
function Get-Celular { try { (Invoke-RestMethod "$base/api/lan" -TimeoutSec 2).url } catch { $null } }

switch ($Cmd) {
  'start' {
    if (Get-State) { "ja esta ligado em $base/"; if (-not $NoBrowser) { Start-Process "$base/" }; break }
    $logs = Join-Path $env:LOCALAPPDATA 'Vitrola\logs'  # o mesmo pastas.LOGS
    New-Item -ItemType Directory -Force $logs | Out-Null
    Start-Process python -ArgumentList '-u', "`"$here\vitrola.py`"", '--port', $Port, '--no-browser' `
      -WorkingDirectory $here -WindowStyle Hidden `
      -RedirectStandardOutput "$logs\server.log" -RedirectStandardError "$logs\server.err"
    foreach ($i in 1..40) { Start-Sleep -Milliseconds 250; if ($s = Get-State) { break } }
    if (-not $s) { "nao subiu; veja $logs\server.err"; Get-Content "$logs\server.err" -Tail 15; exit 1 }
    "ligado em $base/ | mic: $($s.active_devices.mic) | fone: $($s.active_devices.monitor)"
    "no VRChat o microfone precisa ser CABLE Output (VB-Audio Virtual Cable)"
    if ($c = Get-Celular) { "celular (mesmo Wi-Fi): $c" }
    if (-not $NoBrowser) { Start-Process "$base/" }
  }
  'stop' {
    if (Get-State) {
      try { Invoke-RestMethod -Method Post "$base/api/shutdown" -TimeoutSec 3 | Out-Null } catch { }
      Start-Sleep -Milliseconds 800
    }
    if (Get-State) {
      # o python desta Vitrola (vitrola.py, ou o server.py rodado direto), pela linha de comando (nunca por nome:
      # pode ter outro python aberto)
      Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine.Contains("$here\vitrola.py") -or $_.CommandLine.Contains("$here\server.py")) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
    if (Get-State) { 'continua de pe'; exit 1 } else { 'desligado (a voz parou de passar pelo cabo)' }
  }
  'status' {
    $s = Get-State
    if (-not $s) { 'desligado'; break }
    $t = if ($s.track) { $s.track.title } else { '-' }
    "ligado em $base/ | $($s.status) | $t | mic: $($s.active_devices.mic) | fone: $($s.active_devices.monitor)"
    if ($c = Get-Celular) { "celular (mesmo Wi-Fi): $c" }
  }
  'open' { Start-Process "$base/" }
}
