# Encerra, pelo caminho completo do executavel, os processos que seguram a instalacao que o setup substitui (o
# PrepareToInstall do ritmelli.iss, depois de conferir o destino). So os caminhos pedidos: nunca um processo com o
# mesmo nome de outra pasta, nunca o que roda da atualizacao\ (o setup baixado pelo atualizador mora la), e nunca o
# proprio setup nem quem o lancou (a cadeia de pais deste PowerShell: a rodada da tarefa de atualizacao espera o pid
# do setup).
#
# O setup roda este arquivo como texto (um scriptblock), sem depender da politica de execucao de scripts:
#   & ([scriptblock]::Create([IO.File]::ReadAllText('encerra.ps1'))) -Caminhos 'C:\a\x.exe|C:\b\y.exe' -Saida <arquivo>
# Grava no -Saida o que encerrou (so ASCII, para o log do Inno).
param([Parameter(Mandatory = $true)][string]$Caminhos, [Parameter(Mandatory = $true)][string]$Saida)

$linhas = New-Object System.Collections.Generic.List[string]
try {
  $alvos = @($Caminhos -split '\|' | Where-Object { $_ } | ForEach-Object { [IO.Path]::GetFullPath($_).ToLowerInvariant() })
  $processos = @(Get-CimInstance Win32_Process)
  $pai = @{}
  foreach ($p in $processos) { $pai[[int]$p.ProcessId] = [int]$p.ParentProcessId }
  $meus = @{}
  $id = $PID
  while ($id -and -not $meus.ContainsKey($id)) { $meus[$id] = $true; $id = $pai[$id] }
  foreach ($p in $processos) {
    if (-not $p.ExecutablePath -or $meus.ContainsKey([int]$p.ProcessId)) { continue }
    if ($alvos -contains $p.ExecutablePath.ToLowerInvariant()) {
      try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        $linhas.Add("closed $($p.ProcessId) $($p.ExecutablePath)")
      } catch {
        $linhas.Add("couldn't close $($p.ProcessId) $($p.ExecutablePath): $($_.Exception.Message)")
      }
    }
  }
  if (-not $linhas.Count) { $linhas.Add('nothing to close') }
} catch {
  $linhas.Add("couldn't list the processes: $($_.Exception.Message)")
}
$texto = $linhas -join '; '
$ascii = -join ($texto.ToCharArray() | ForEach-Object { if ([int]$_ -lt 128) { $_ } else { '?' } })
[IO.File]::WriteAllText($Saida, $ascii)
