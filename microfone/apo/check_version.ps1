param([Parameter(Mandatory = $true)][string]$Folder)
$ErrorActionPreference = 'Stop'
$Version = (Select-String -Path (Join-Path $PSScriptRoot '..\..\versao.py') -Pattern '^VERSAO = "(.+)"').Matches[0].Groups[1].Value
foreach ($dll in 'micfx.dll', 'voz.dll') {
  $v = (Get-Item (Join-Path $Folder $dll)).VersionInfo
  $numbers = "$($v.FileMajorPart).$($v.FileMinorPart).$($v.FileBuildPart)"
  "${dll}: ProductName=$($v.ProductName) ProductVersion=$($v.ProductVersion) FileVersion=$($v.FileVersion) ($numbers) FileDescription=$($v.FileDescription) OriginalFilename=$($v.OriginalFilename)"
  if ($v.ProductName -ne 'Ritmelli' -or $v.ProductVersion -ne $Version -or $v.FileVersion -ne $Version -or
      $numbers -ne $Version -or $v.OriginalFilename -ne $dll) {
    throw "$dll has no version resource of Ritmelli $Version"
  }
}
