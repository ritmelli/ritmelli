# A regra da pasta protegida para o setup (o ritmelli.iss): a mesma do pastas.pasta_protegida do app, pelo PowerShell
# do sistema, antes de o setup usar a pasta do app. As duas tarefas do Windows rodam como SYSTEM o ritmelli.exe dela, e
# a de atualizacao roda dali o setup baixado: so uma pasta que apenas o sistema e os administradores alteram serve.
#
# - o caminho, normalizado, fica dentro da raiz, e nem ele, nem um ancestral, nem nada dentro dele e ponto de reanalise;
# - o dono da pasta e de tudo dentro dela e SYSTEM, Administradores ou TrustedInstaller;
# - nenhuma ACE de permissao da a outro principal escrita (dos dados, dos atributos ou dos atributos estendidos),
#   acrescimo ou criacao, exclusao (inclusive a de filhos), WRITE_DAC ou WRITE_OWNER (das so de heranca, so a do
#   CREATOR OWNER fica de fora); o mesmo vale
#   para cada pasta da raiz (inclusive) ate o pai do destino. DACL nula ou ilegivel reprova, e tambem um nome que o
#   Windows nao abre como esta (terminado em ponto ou espaco);
# - na microfone\log, o LocalService (o audiodg.exe grava o log do filtro) pode escrever, criar e apagar, nunca
#   WRITE_DAC nem WRITE_OWNER na pasta, e ser dono dos arquivos (com controle total sobre os que sao dele), nunca da
#   pasta.
# O destino que ainda nao existe e conferido pelos ancestrais que existem.
#
# O setup roda este arquivo como texto (um scriptblock), sem depender da politica de execucao de scripts:
#   & ([scriptblock]::Create([IO.File]::ReadAllText('protegida.ps1'))) -Pasta <destino> -Raiz <raiz> -Saida <arquivo>
# Grava no -Saida "OK", ou o motivo da recusa (so ASCII, para o log do Inno).
param([Parameter(Mandatory = $true)][string]$Pasta, [Parameter(Mandatory = $true)][string]$Raiz,
      [Parameter(Mandatory = $true)][string]$Saida)

$donos = @('S-1-5-18', 'S-1-5-32-544', 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$servico = 'S-1-5-19'
# CREATOR OWNER: so de heranca, vira a ACE de quem cria (o CREATOR GROUP viraria a do grupo primario dele, o None)
$criadores = @('S-1-3-0')
# FILE_WRITE_DATA, FILE_APPEND_DATA, FILE_WRITE_EA, FILE_DELETE_CHILD, FILE_WRITE_ATTRIBUTES (basta para transformar
# uma pasta vazia em juncao), DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_WRITE, GENERIC_ALL
$escrita = 0x2 -bor 0x4 -bor 0x10 -bor 0x40 -bor 0x100 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40000000 -bor 0x10000000
$trocaAcl = 0x40000 -bor 0x80000 -bor 0x10000000
$reparse = [int][IO.FileAttributes]::ReparsePoint
$pastaAttr = [int][IO.FileAttributes]::Directory

# o objeto como a regra le: $null se nao existe; senao os atributos (sem seguir ponto de reanalise) e, quando nao e
# ponto de reanalise, o descritor de seguranca (o dono e a DACL)
function Le($c) {
  try { $a = [int][IO.File]::GetAttributes($c) }
  catch [IO.FileNotFoundException], [IO.DirectoryNotFoundException] { return $null }
  $o = @{ Caminho = $c; Pasta = ($a -band $pastaAttr) -ne 0; Reparse = ($a -band $reparse) -ne 0 }
  if (-not $o.Reparse) {
    $secoes = [Security.AccessControl.AccessControlSections]'Owner, Access'
    $acl = if ($o.Pasta) { [IO.Directory]::GetAccessControl($c, $secoes) } else { [IO.File]::GetAccessControl($c, $secoes) }
    [byte[]]$binario = $acl.GetSecurityDescriptorBinaryForm()
    $o.Sd = [Security.AccessControl.RawSecurityDescriptor]::new($binario, 0)
  }
  $o
}

# o motivo pelo qual o dono ou a DACL reprovam, ou $null
function ConfereObjeto($o, [bool]$noLog) {
  $dono = if ($o.Sd.Owner) { $o.Sd.Owner.Value } else { $null }
  if (-not ($donos -contains $dono) -and -not ($noLog -and -not $o.Pasta -and $dono -eq $servico)) {
    return "$($o.Caminho) is owned by $dono"
  }
  $dacl = $o.Sd.DiscretionaryAcl
  if ($null -eq $dacl) { return "$($o.Caminho) has a null DACL" }
  foreach ($ace in $dacl) {
    # num arquivo, a so de heranca nao vale nem tem para quem passar
    if (-not $o.Pasta -and (([int]$ace.AceFlags -band 0x08) -ne 0)) { continue }
    $tipo = [int]$ace.AceType
    if (@(1, 6, 10, 12) -contains $tipo) { continue }  # negacao: so tira acesso
    if (@(0, 9) -notcontains $tipo) { return "$($o.Caminho) has an ACE of type $tipo" }
    $sid = $ace.SecurityIdentifier.Value
    $mascara = [int]$ace.AccessMask
    if (($donos -contains $sid) -or (($mascara -band $escrita) -eq 0)) { continue }
    if ((([int]$ace.AceFlags -band 0x08) -ne 0) -and ($criadores -contains $sid)) { continue }
    # o controle total so num arquivo de log que e do LocalService (o micfx.log que o audiodg.exe cria na rotacao)
    if ($noLog -and $sid -eq $servico -and ((($mascara -band $trocaAcl) -eq 0) -or (-not $o.Pasta -and $dono -eq $servico))) { continue }
    return "$($o.Caminho) lets $sid write or change it (access 0x$('{0:x8}' -f $mascara))"
  }
  $null
}

# o motivo pelo qual a pasta ou algo dentro dela reprova, ou $null. Nao entra em ponto de reanalise: ele reprova
function ConfereArvore($o) {
  $pilha = New-Object System.Collections.Stack
  $pilha.Push(@($o, ''))
  while ($pilha.Count) {
    $o, $rel = $pilha.Pop()
    if ($o.Reparse) { return "$($o.Caminho) is a reparse point" }
    $partes = @($rel -split '\\' | Where-Object { $_ })
    # a propria microfone\log so como pasta: um arquivo com esse nome nao e o log do filtro. Ordinal, como o lower() do
    # app: o -eq compara pela cultura e acharia 'log' igual a 'log' com um caractere invisivel no fim
    $ord = [StringComparison]::OrdinalIgnoreCase
    $noLog = $partes.Count -ge 2 -and [string]::Equals($partes[0], 'microfone', $ord) -and
             [string]::Equals($partes[1], 'log', $ord) -and ($partes.Count -gt 2 -or $o.Pasta)
    $m = ConfereObjeto $o $noLog
    if ($m) { return $m }
    if ($o.Pasta) {
      foreach ($filho in [IO.Directory]::EnumerateFileSystemEntries($o.Caminho)) {
        # o Windows corta o ponto ou o espaco do fim ao abrir: a leitura acharia outro objeto
        if ($filho -match '[. ]$') { return "$filho has a name Windows can't open" }
        # o MAX_PATH: sem o \\?\, o Windows diria que nao existe, e ele passaria sem conferir
        if ($filho.Length -ge 260) { return "$filho is too long to check" }
        $f = Le $filho
        if ($f) { $pilha.Push(@($f, "$rel\$([IO.Path]::GetFileName($filho))")) }
      }
    }
  }
  $null
}

function Motivo {
  # o GetFullPath do .NET Framework expande o nome curto (C:\PROGRA~1 vira C:\Program Files), e o app, pelo
  # sys.executable, nao expande: a mesma pasta passaria aqui e reprovaria la. Alias e o componente de ate 8 caracteres
  # com um ~ seguido de digito e extensao de ate 3; um nome longo com ~ (Ritmelli~2026) nao e
  foreach ($comp in ($Pasta -split '[\\/]' | Select-Object -Skip 1)) {
    $c = $comp.TrimEnd('. ')  # o Windows corta o ponto e o espaco do fim
    if ($c -match '^[^.]{1,8}(\.[^.]{1,3})?$' -and $c.Split('.')[0] -match '~[0-9]') {
      return "$Pasta has a short (8.3) name"
    }
  }
  $p = [IO.Path]::GetFullPath($Pasta).TrimEnd('\')
  $r = [IO.Path]::GetFullPath($Raiz).TrimEnd('\')
  if (-not $p.StartsWith("$r\", [StringComparison]::OrdinalIgnoreCase)) { return "$p is outside $r" }
  # antes de andar: um pai que ainda nao existe pararia a conta antes do fim
  if ($p.Length -ge 260) { return "$p is too long to check" }
  $raizPartes = @($r.Substring(3) -split '\\' | Where-Object { $_ }).Count
  $partes = @($p.Substring(3) -split '\\' | Where-Object { $_ })
  $c = $p.Substring(0, 3)
  for ($i = 0; $i -le $partes.Count; $i++) {
    if ($i) { $c = Join-Path $c $partes[$i - 1] }
    $o = Le $c
    if (-not $o) {
      # o destino (ou um pai dele) ainda nao existe: valem os ancestrais que existem, a raiz inclusive
      if ($i -le $raizPartes) { return "$r doesn't exist" }
      return $null
    }
    if ($o.Reparse) { return "$c is a reparse point" }
    if (-not $o.Pasta) { return "$c is not a folder" }
    if ($i -eq $partes.Count) { return ConfereArvore $o }
    if ($i -ge $raizPartes) {
      $m = ConfereObjeto $o $false
      if ($m) { return $m }
    }
  }
  $null
}

try {
  if ($Pasta -notmatch '^[A-Za-z]:\\' -or $Raiz -notmatch '^[A-Za-z]:\\') { $texto = "$Pasta is not an absolute path" }
  else { $texto = Motivo }
} catch {
  $texto = "couldn't check ${Pasta}: $($_.Exception.Message)"
}
if (-not $texto) { $texto = 'OK' }
$ascii = -join ($texto.ToCharArray() | ForEach-Object { if ([int]$_ -lt 128) { $_ } else { '?' } })
[IO.File]::WriteAllText($Saida, $ascii)
