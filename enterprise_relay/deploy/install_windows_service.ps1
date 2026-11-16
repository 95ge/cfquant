param(
    [string]$PythonPath = "$PSScriptRoot\..\..\.venv\Scripts\python.exe",
    [string]$DataDir = "$env:ProgramData\CFQuant\Relay",
    [string]$ServiceName = "CFQuantEnterpriseRelay"
)

$ErrorActionPreference = "Stop"
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$data = [System.IO.Path]::GetFullPath($DataDir)
New-Item -ItemType Directory -Force -Path $data | Out-Null

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 1
}

$binPath = '"{0}" -m enterprise_relay.server --data-dir "{1}"' -f $python, $data
New-Service -Name $ServiceName -BinaryPathName $binPath -DisplayName "CFQuant Enterprise Relay" `
    -Description "CFQuant Enterprise Relay Server" -StartupType Automatic
Write-Host "Installed $ServiceName. Configure CFQUANT_RELAY_ACTIVATION_CODE for first activation, then start the service."
