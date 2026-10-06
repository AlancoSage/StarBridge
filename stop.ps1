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
# Windows venv launches a child Python process; stop the verified process tree.
& "$env:SystemRoot\System32\taskkill.exe" /PID $serviceId /T /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw '停止失败，请查看进程状态后重试。' }
Write-Host '星桥后台服务已停止。'
