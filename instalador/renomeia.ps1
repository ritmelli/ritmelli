# Na migracao para outra pasta (o ssPostInstall do ritmelli.iss), renomeia o ritmelli.exe da instalacao anterior para
# ritmelli.exe.antigo: a pasta anterior fica onde esta, mas o reabre() da versao antiga (o atualizador dela, que espera
# o setup terminar) nao abre mais a versao velha. So o ritmelli.exe, e com cuidado, porque o setup roda como
# administrador ou SYSTEM numa pasta que pode nao ser protegida:
# - o caminho e resolvido por componentes, e nenhum deles pode ser ponto de reanalise;
# - o arquivo e aberto sem seguir ponto de reanalise e sem deixar outro processo gravar nele ou troca-lo, o caminho final
#   do que foi aberto tem de ser o pedido, e o recurso de versao dele tem de dizer Ritmelli (lido de uma copia dos bytes
#   abertos);
# - a renomeacao e feita sobre esse mesmo arquivo aberto, e nunca sobrescreve um ritmelli.exe.antigo que ja exista.
# Qualquer outro caso so vai para o log.
#
# O setup roda este arquivo como texto (um scriptblock), sem depender da politica de execucao de scripts:
#   & ([scriptblock]::Create([IO.File]::ReadAllText('renomeia.ps1'))) -Exe <...\ritmelli.exe> -Saida <arquivo>
# Grava no -Saida o que fez (so ASCII, para o log do Inno). -Produto existe para os testes (outro exe no lugar).
param([Parameter(Mandatory = $true)][string]$Exe, [Parameter(Mandatory = $true)][string]$Saida,
      [string]$Produto = 'Ritmelli')

$codigo = @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class RitmelliRenomeia {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateFileW(string nome, uint acesso, uint compartilha, IntPtr sa, uint disposicao,
                                             uint flags, IntPtr modelo);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandle(SafeFileHandle h, out Info info);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetFinalPathNameByHandleW(SafeFileHandle h, StringBuilder b, uint n, uint flags);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetFileInformationByHandle(SafeFileHandle h, int classe, IntPtr info, uint tamanho);

    [StructLayout(LayoutKind.Sequential)]
    struct Info {
        public uint Atributos;
        public uint C1, C2, A1, A2, E1, E2;
        public uint Serie, TamanhoAlto, TamanhoBaixo, Links, IndiceAlto, IndiceBaixo;
    }

    const uint DELETE = 0x10000, GENERIC_READ = 0x80000000, FILE_SHARE_READ = 1, OPEN_EXISTING = 3;
    const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    const int FileRenameInfo = 3;

    // o caminho final do arquivo aberto (com o \\?\ da frente)
    static string Final(SafeFileHandle h) {
        StringBuilder b = new StringBuilder(1024);
        uint n = GetFinalPathNameByHandleW(h, b, (uint)b.Capacity, 0);
        if (n == 0 || n >= b.Capacity) throw new Win32Exception(Marshal.GetLastWin32Error());
        return b.ToString();
    }

    static string SemPrefixo(string s) {
        return s.StartsWith(@"\\?\") ? s.Substring(4) : s;
    }

    public static string Renomeia(string exe, string copia, string produto) {
        string cheio = Path.GetFullPath(exe);
        string raiz = Path.GetPathRoot(cheio);
        string c = raiz;
        foreach (string parte in cheio.Substring(raiz.Length).Split(new char[] { '\\' },
                                                                     StringSplitOptions.RemoveEmptyEntries)) {
            c = Path.Combine(c, parte);
            if ((File.GetAttributes(c) & FileAttributes.ReparsePoint) != 0)
                return "not renamed: " + c + " is a reparse point";
        }
        using (SafeFileHandle h = CreateFileW(cheio, DELETE | GENERIC_READ, FILE_SHARE_READ, IntPtr.Zero,
                                              OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, IntPtr.Zero)) {
            if (h.IsInvalid) return "not renamed: couldn't open " + cheio + " (" +
                                    new Win32Exception(Marshal.GetLastWin32Error()).Message + ")";
            Info info;
            if (!GetFileInformationByHandle(h, out info)) throw new Win32Exception(Marshal.GetLastWin32Error());
            if ((info.Atributos & (uint)(FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0)
                return "not renamed: " + cheio + " is not a regular file";
            string final = Final(h);
            if (!string.Equals(SemPrefixo(final), cheio, StringComparison.OrdinalIgnoreCase))
                return "not renamed: " + cheio + " resolves to " + SemPrefixo(final);
            // o FileStream usa o mesmo handle (e o fecha no fim): a renomeacao vem antes disso
            FileStream f = new FileStream(h, FileAccess.Read, 1 << 16, false);
            try {
                // o recurso de versao, de uma copia dos bytes que estao abertos (ninguem grava nem troca o arquivo)
                using (FileStream d = File.Create(copia)) {
                    f.CopyTo(d);
                }
                string nome = System.Diagnostics.FileVersionInfo.GetVersionInfo(copia).ProductName;
                File.Delete(copia);
                if (!string.Equals(nome, produto, StringComparison.Ordinal))
                    return "not renamed: " + cheio + " is '" + nome + "', not " + produto;
                // FILE_RENAME_INFO: ReplaceIfExists (4 bytes, com o alinhamento), RootDirectory, FileNameLength e
                // FileName. O nome novo vai com o caminho final da pasta do arquivo aberto (um nome solto o Windows
                // resolveria pela pasta atual do processo); a pasta de um arquivo aberto nao muda de nome enquanto ele
                // esta aberto
                string novo = Path.GetFileName(cheio) + ".antigo";
                byte[] bytes = Encoding.Unicode.GetBytes(final.Substring(0, final.LastIndexOf('\\') + 1) + novo);
                int base_ = IntPtr.Size == 8 ? 20 : 12;
                int tamanho = base_ + bytes.Length + 2;
                IntPtr p = Marshal.AllocHGlobal(tamanho);
                try {
                    for (int i = 0; i < tamanho; i++) Marshal.WriteByte(p, i, 0);  // ReplaceIfExists = 0: nunca sobrescreve
                    Marshal.WriteInt32(p, IntPtr.Size == 8 ? 16 : 8, bytes.Length);
                    Marshal.Copy(bytes, 0, IntPtr.Add(p, base_), bytes.Length);
                    if (!SetFileInformationByHandle(h, FileRenameInfo, p, (uint)tamanho))
                        return "not renamed: " + cheio + " (" +
                               new Win32Exception(Marshal.GetLastWin32Error()).Message + ")";
                } finally {
                    Marshal.FreeHGlobal(p);
                }
                return "renamed " + cheio + " to " + novo;
            } finally {
                f.Dispose();
            }
        }
    }
}
'@

try {
  Add-Type -TypeDefinition $codigo -Language CSharp
  $copia = Join-Path ([IO.Path]::GetDirectoryName($Saida)) ("renomeia-" + [guid]::NewGuid().ToString('N') + '.exe')
  $texto = [RitmelliRenomeia]::Renomeia($Exe, $copia, $Produto)
} catch {
  $texto = "not renamed: $($_.Exception.Message)"
}
$ascii = -join ($texto.ToCharArray() | ForEach-Object { if ([int]$_ -lt 128) { $_ } else { '?' } })
[IO.File]::WriteAllText($Saida, $ascii)
