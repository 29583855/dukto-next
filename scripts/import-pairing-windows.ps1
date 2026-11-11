# 日期：2026-11-11；将用户选择的单个配对文件复制到仅当前账户可访问的新目录，供现有客户端读取。
[CmdletBinding()]
param(
    [string]$CredentialFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw '此脚本仅适用于 Windows。'
}

if ([string]::IsNullOrWhiteSpace($CredentialFile)) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    try {
        $picker.Title = '选择从服务器复制过来的配对 JSON 文件'
        $picker.Filter = '配对文件 (*.json)|*.json'
        $picker.Multiselect = $false
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            return
        }
        $CredentialFile = $picker.FileName
    }
    finally {
        $picker.Dispose()
    }
}

# 日期：2026-11-11；有界读取并校验格式，凭据正文不输出到控制台或命令行。
$source = Get-Item -LiteralPath $CredentialFile -Force
if ($source -isnot [System.IO.FileInfo] -or
    ($source.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw '请选择实际的普通 JSON 文件。'
}
$inputStream = [System.IO.File]::Open(
    $source.FullName, [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
try {
    if ($inputStream.Length -le 0 -or $inputStream.Length -gt 65536) {
        throw '配对文件大小无效，必须为 1 至 65536 字节。'
    }
    $bytes = New-Object byte[] ([int]$inputStream.Length)
    $offset = 0
    while ($offset -lt $bytes.Length) {
        $count = $inputStream.Read($bytes, $offset, $bytes.Length - $offset)
        if ($count -le 0) {
            throw '配对文件读取不完整。'
        }
        $offset += $count
    }
}
finally {
    $inputStream.Dispose()
}
try {
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $record = ConvertFrom-Json -InputObject $utf8.GetString($bytes)
    if ($record.version -ne 1 -or $record.credential -isnot [string] -or
        $record.credential -cnotmatch '\A[0-9a-f]{64}\z') {
        throw 'invalid'
    }
}
catch {
    throw '文件不是有效的 Dukto Next 配对文件，请从服务器重新颁发。'
}

# 日期：2026-11-11；以当前账户 SID 显式设置所有者及保护 DACL，创建时即禁止继承其他账户权限。
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
try {
    $sid = $identity.User.Value
}
finally {
    $identity.Dispose()
}
$directorySecurity = New-Object System.Security.AccessControl.DirectorySecurity
$directorySecurity.SetSecurityDescriptorSddlForm("O:${sid}D:P(A;OICI;FA;;;${sid})")
$fileSecurity = New-Object System.Security.AccessControl.FileSecurity
$fileSecurity.SetSecurityDescriptorSddlForm("O:${sid}D:P(A;;FA;;;${sid})")
$localDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($localDirectory)) {
    throw '无法确定当前账户的本地应用数据目录。'
}
$destinationDirectory = Join-Path $localDirectory ('DuktoNext-Pairing-' + [guid]::NewGuid().ToString('N'))
$directoryInfo = New-Object System.IO.DirectoryInfo($destinationDirectory)
if ($directoryInfo.Exists) {
    throw '导入目录已存在，请重新运行。'
}
if ($PSVersionTable.PSEdition -eq 'Core') {
    [System.IO.FileSystemAclExtensions]::Create($directoryInfo, $directorySecurity)
}
else {
    $directoryInfo.Create($directorySecurity)
}

# 日期：2026-11-11；目的文件只创建新对象，不覆盖已有文件；秘密写入前已设置当前账户专有权限。
$destination = Join-Path $destinationDirectory 'pairing.json'
if ($PSVersionTable.PSEdition -eq 'Core') {
    $outputStream = [System.IO.FileSystemAclExtensions]::Create(
        [System.IO.FileInfo]::new($destination), [System.IO.FileMode]::CreateNew,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::WriteThrough,
        $fileSecurity)
}
else {
    $outputStream = [System.IO.FileStream]::new(
        $destination, [System.IO.FileMode]::CreateNew,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::WriteThrough,
        $fileSecurity)
}
try {
    $outputStream.Write($bytes, 0, $bytes.Length)
    $outputStream.Flush($true)
}
finally {
    $outputStream.Dispose()
    [Array]::Clear($bytes, 0, $bytes.Length)
}

Write-Host '导入完成。请在 Windows 客户端的“配对文件路径”中选择或粘贴下面的新路径，再点击“配对并保存资料”。'
Write-Output $destination
