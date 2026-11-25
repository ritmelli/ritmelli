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
# o handle prende o processo (o pid nao volta a outro enquanto ele esta aberto): o caminho e conferido de novo por esse
# handle, e o fim usa o mesmo handle. Um pid que saiu e voltou em outro programa fica. Os direitos sao os do
# Stop-Process (encerrar) e o de ler o caminho
$codigo = @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public static class RitmelliEncerra {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr OpenProcess(uint acesso, bool herda, int pid);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool QueryFullProcessImageNameW(IntPtr h, uint flags, StringBuilder b, ref uint n);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool TerminateProcess(IntPtr h, uint codigo);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr h);

    public static string Encerra(int pid, IEnumerable<string> alvos) {
        IntPtr h = OpenProcess(0x0001 | 0x1000, false, pid);  // PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION
        if (h == IntPtr.Zero) return "couldn't open " + pid + " (" + new Win32Exception(Marshal.GetLastWin32Error()).Message + ")";
        try {
            StringBuilder b = new StringBuilder(1024);
            uint n = (uint)b.Capacity;
            if (!QueryFullProcessImageNameW(h, 0, b, ref n))
                return "couldn't read the path of " + pid + " (" + new Win32Exception(Marshal.GetLastWin32Error()).Message + ")";
            string caminho = b.ToString();
            string normal = Path.GetFullPath(caminho).ToLowerInvariant();
            foreach (string a in alvos) {
                if (a == normal) {
                    if (!TerminateProcess(h, 1))
                        return "couldn't close " + pid + " " + caminho + " (" + new Win32Exception(Marshal.GetLastWin32Error()).Message + ")";
                    return "closed " + pid + " " + caminho;
                }
            }
            return "left " + pid + ": it is now " + caminho;
        } finally {
            CloseHandle(h);
        }
    }
}
'@
try {
  Add-Type -TypeDefinition $codigo -Language CSharp
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
        $linhas.Add([RitmelliEncerra]::Encerra([int]$p.ProcessId, [string[]]$alvos))
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
