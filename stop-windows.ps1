$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$pidFile = Join-Path $root '.codemuse-server.pid'
$outLog = Join-Path $root '.server-8765.out.log'
$errLog = Join-Path $root '.server-8765.err.log'
$port = 8765

$serverPid = $null
if (Test-Path -LiteralPath $pidFile) {
    $serverPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not [string]::IsNullOrWhiteSpace($serverPid)) {
    try {
        Stop-Process -Id [int]$serverPid -Force -ErrorAction Stop
        Write-Host "已停止 CodeMuse，PID=$serverPid"
    }
    catch {
        Write-Host "未能停止进程，可能已退出：PID=$serverPid"
    }
}
else {
    Write-Host '未找到有效的 CodeMuse PID 记录。'
}

$portOwner = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($portOwner) {
    try {
        Stop-Process -Id $portOwner.OwningProcess -Force -ErrorAction Stop
        Write-Host "已停止占用 8765 端口的进程，PID=$($portOwner.OwningProcess)"
    }
    catch {
        Write-Host "未能停止 8765 端口进程，PID=$($portOwner.OwningProcess)"
    }
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $outLog, $errLog -Force -ErrorAction SilentlyContinue
