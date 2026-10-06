$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'data\server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host '没有记录后台进程；前台运行时请按 Ctrl+C。'; exit }
$serviceId = [int](Get-Content -LiteralPath $pidFile)
$service = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId"
$expectedExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not $service) { Write-Host '后台服务已经停止。'; exit }
if ($service.ExecutablePath -ne $expectedExe -or $service.CommandLine -notmatch '(?:^|\s)-m\s+starbridge\s+run(?:\s|$)') {
    throw 'PID 对应的进程与本项目不符，未停止任何进程。'
}
Stop-Process -Id $serviceId
Write-Host '星桥后台服务已停止。'
