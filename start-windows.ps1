$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$pidFile = Join-Path $root '.codemuse-server.pid'
$outLog = Join-Path $root '.server-8765.out.log'
$errLog = Join-Path $root '.server-8765.err.log'
$serverScript = Join-Path $root 'scripts\run_server.py'
$port = 8765

if (-not (Test-Path -LiteralPath $serverScript)) {
    Write-Host '未找到 scripts\run_server.py，请确认在 CodeMuse 项目根目录下执行。'
    exit 1
}

if (Test-Path -LiteralPath $pidFile) {
    $oldPid = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($oldPid) {
        try {
            $existing = Get-Process -Id [int]$oldPid -ErrorAction Stop
            Write-Host "CodeMuse 已在运行，PID=$($existing.Id)"
            exit 0
        }
        catch {
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        }
    }
}

$portOwner = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($portOwner) {
    Set-Content -LiteralPath $pidFile -Value $portOwner.OwningProcess -Encoding ASCII
    Write-Host "CodeMuse 已在运行，PID=$($portOwner.OwningProcess)"
    Write-Host "浏览器地址: http://127.0.0.1:$port/"
    exit 0
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $pythonCmd) {
    throw '未找到 Python，请先安装 Python 3 并加入 PATH。'
}

$proc = Start-Process -FilePath $pythonCmd.Source -ArgumentList @(
    'scripts\\run_server.py',
    '--host', '127.0.0.1',
    '--port', "$port"
) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

Start-Sleep -Milliseconds 800
if ($proc.HasExited) {
    throw "CodeMuse 启动失败，进程已退出。请查看 $errLog"
}

Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
Write-Host "CodeMuse 已启动，PID=$($proc.Id)"
Write-Host "浏览器地址: http://127.0.0.1:$port/"
