@echo off
setlocal DisableDelayedExpansion
title Myrinbot
chcp 65001 >nul
set "STARBRIDGE_SELF=%~f0"
set "STARBRIDGE_ACTION=%~1"
set "STARBRIDGE_QUIET=%~2"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "try { $source = [IO.File]::ReadAllText($env:STARBRIDGE_SELF, [Text.Encoding]::UTF8); $parts = $source -split '(?m)^# STARBRIDGE_POWERSHELL\r?$', 2; if ($parts.Count -ne 2) { throw 'Invalid installer file.' }; & ([ScriptBlock]::Create($parts[1])) } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
set "STARBRIDGE_EXIT=%ERRORLEVEL%"
if "%STARBRIDGE_EXIT%"=="0" goto done
if /i "%STARBRIDGE_QUIET%"=="quiet" goto done
echo.
pause
:done
exit /b %STARBRIDGE_EXIT%
# STARBRIDGE_POWERSHELL
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$entrypoint = Split-Path -Leaf $env:STARBRIDGE_SELF
try {
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

function Test-StarBridgePython {
    param([string]$Executable, [string[]]$Prefix = @())
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & $Executable @Prefix -I -c 'import sys, json; assert sys.version_info >= (3, 11); import venv, ssl, sqlite3; print(json.dumps(sys.executable, ensure_ascii=True))' 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) { return (([string](@($result)[-1])).Trim() | ConvertFrom-Json) }
    } catch {} finally { $ErrorActionPreference = $previousPreference }
    return $null
}

function Find-StarBridgePython {
    param([string]$Root, [string]$Requested = '')
    if ($Requested) {
        $found = Test-StarBridgePython -Executable $Requested
        if (-not $found) { throw '指定的 Python 无法运行，或版本低于 3.11。' }
        return $found
    }
    foreach ($path in @((Join-Path $Root '.venv\Scripts\python.exe'), (Join-Path $Root '.runtime\python\python.exe'))) {
        if (Test-Path -LiteralPath $path) {
            $found = Test-StarBridgePython -Executable $path
            if ($found) { return $found }
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.13', '-3.14', '-3.12', '-3.11', '-3')) {
            $found = Test-StarBridgePython -Executable $launcher.Source -Prefix @($version)
            if ($found) { return $found }
        }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
            $found = Test-StarBridgePython -Executable $command.Source
            if ($found) { return $found }
        }
    }
    foreach ($registryRoot in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        if (-not (Test-Path -LiteralPath $registryRoot)) { continue }
        foreach ($key in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
            $installKey = Get-Item -LiteralPath (Join-Path $key.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if ($installKey) {
                $path = $installKey.GetValue('ExecutablePath')
                if (-not $path) { $path = Join-Path $installKey.GetValue('') 'python.exe' }
                $found = Test-StarBridgePython -Executable $path
                if ($found) { return $found }
            }
        }
    }
    return $null
}

function Install-StarBridgePython {
    param([string]$Root)
    $version = '3.13.16'
    $architecture = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
    switch ($architecture) {
        'AMD64' { $suffix = '-amd64'; $expectedHash = 'fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b' }
        'ARM64' { $suffix = '-arm64'; $expectedHash = '696e2226062c6ec3622c13f143d28336a856968518e49cb4f4c62513215a4f5d' }
        'x86' { $suffix = ''; $expectedHash = '394ca84150ea428db952cb617c1163c49fbc30e47ec53048c26e6ae44265df07' }
        default { throw "不支持的 Windows 架构：$architecture" }
    }
    $runtime = Join-Path $Root '.runtime'
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $installer = Join-Path $runtime "python-$version$suffix.exe"
    $url = "https://www.python.org/ftp/python/$version/python-$version$suffix.exe"
    if (-not (Test-Path -LiteralPath $installer) -or (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) {
        Write-Host '[1/4] 正在从 Python 官网下载运行环境……'
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $partial = "$installer.download"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $partial -TimeoutSec 180
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Python 安装包校验失败，未运行下载文件。请重新双击安装。' }
        Move-Item -LiteralPath $partial -Destination $installer -Force
    }
    Write-Host '[1/4] 正在安装项目专用 Python，无需修改系统 PATH……'
    $target = Join-Path $runtime 'python'
    $arguments = @('/quiet', '/norestart', 'InstallAllUsers=0', "TargetDir=`"$target`"", 'PrependPath=0', 'Include_launcher=0', 'InstallLauncherAllUsers=0', 'AssociateFiles=0', 'Shortcuts=0', 'Include_test=0', 'Include_doc=0', 'Include_tcltk=0', 'Include_pip=1')
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 3010)) { throw "Python 安装失败（退出码 $($process.ExitCode)）。检查目录写入权限后重试。" }
    $python = Test-StarBridgePython -Executable (Join-Path $target 'python.exe')
    if (-not $python) { throw 'Python 安装后无法运行。如系统提示需要重启，请重启 Windows 后再双击安装。' }
    return $python
}

function Test-StarBridgeProcess {
    param([string]$Python, [string]$PidFile)
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $serviceId = 0
    if (-not [int]::TryParse((Get-Content -Raw -LiteralPath $PidFile).Trim(), [ref]$serviceId) -or $serviceId -le 0) { return $null }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId" -ErrorAction SilentlyContinue
    if ($process -and $process.ExecutablePath -eq $Python -and $process.CommandLine -match '(?:^|\s)-m\s+starbridge\s+run(?:\s|$)') { return $process }
    return $null
}

function Start-StarBridgeWindows {
    param([string]$Root, [string]$RequestedPython = '', [switch]$InstallOnly, [switch]$WithoutBrowser)
    Set-Location -LiteralPath $Root
    foreach ($name in @('config.example.toml', 'requirements.lock.txt', 'starbridge\__main__.py', 'scripts\windows_runtime.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $name))) { throw "安装文件不完整。请先完整解压 Myrinbot 部署包，再双击 $entrypoint。" }
    }
    $data = Join-Path $Root 'data'
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    $lock = $null
    try {
        try { $lock = [IO.File]::Open((Join-Path $data 'install.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw '另一个安装窗口正在处理此目录，或目录不可写。请等待安装结束后再试。' }
        $python = Find-StarBridgePython -Root $Root -Requested $RequestedPython
        if (-not $python) { $python = Install-StarBridgePython -Root $Root }
        $venv = Join-Path $Root '.venv\Scripts\python.exe'
        $existing = Test-StarBridgeProcess -Python $venv -PidFile (Join-Path $data 'server.pid')
        if (-not (Test-StarBridgePython -Executable $venv)) {
            if (Test-Path -LiteralPath (Join-Path $Root '.venv')) { throw '现有虚拟环境不可用。请将 .venv 文件夹改名保留后重试；config.toml 和 data 无需修改。' }
            Write-Host '[2/4] 正在创建项目虚拟环境……'
            & $python -m venv (Join-Path $Root '.venv')
            if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败，请检查目录权限和可用磁盘空间。' }
        }
        & $venv scripts\windows_runtime.py dependencies-ready
        $dependenciesReady = $LASTEXITCODE -eq 0
        if (-not $dependenciesReady) {
            if ($existing) { throw "Bot 正在运行，依赖需要更新。请在 $entrypoint 菜单中停止 Bot，再重新安装，避免修改运行中的环境。" }
            Write-Host '[2/4] 正在安装锁定版本的依赖，首次安装需要联网……'
            & $venv -m ensurepip --upgrade
            if ($LASTEXITCODE -ne 0) { throw 'pip 初始化失败。' }
            & $venv -m pip install --disable-pip-version-check --retries 3 --timeout 30 --only-binary=:all: -r requirements.lock.txt
            if ($LASTEXITCODE -ne 0) { throw '依赖下载或安装失败。请检查网络后重新双击；配置和数据已保留。' }
            & $venv -m pip check
            if ($LASTEXITCODE -ne 0) { throw '依赖版本检查失败。' }
            & $venv scripts\windows_runtime.py dependencies-ready
            if ($LASTEXITCODE -ne 0) { throw '依赖安装不完整。请检查网络后重新双击。' }
        } else { Write-Host '[2/4] Python 和依赖已就绪，跳过重复安装。' }
        $config = Join-Path $Root 'config.toml'
        if (-not (Test-Path -LiteralPath $config)) {
            Write-Host '[3/4] 正在生成带随机令牌的初始配置……'
            & $venv -m starbridge init --config $config
            if ($LASTEXITCODE -ne 0) { throw '初始配置生成失败。' }
        } else { Write-Host '[3/4] 保留现有配置和玩家数据。' }
        $infoJson = & $venv scripts\windows_runtime.py info
        if ($LASTEXITCODE -ne 0) { throw '配置校验失败，请按上方提示检查 config.toml。' }
        $info = $infoJson | ConvertFrom-Json
        Write-Host "管理面板：$($info.panel_url)"
        Write-Host '面板使用用户名和密码登录；首次无服主账号时，点击“创建服主账号”，使用 config.toml 的 app.admin_token 完成首次授权并设置账号。'
        if ($InstallOnly) { Write-Host "[4/4] 部署完成，尚未启动。双击 $entrypoint 可运行。"; return }
        if (-not $existing) {
            & $venv scripts\windows_runtime.py check-port
            if ($LASTEXITCODE -ne 0) { throw '监听地址或端口不可用。请关闭占用端口的程序，或在 config.toml 修改 app.port 后重试。' }
            Write-Host '[4/4] 正在后台启动 Bot……'
            $arguments = @('-u', '-m', 'starbridge', 'run', '--config', "`"$config`"")
            $service = Start-Process -FilePath $venv -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $data 'server.log') -RedirectStandardError (Join-Path $data 'server-error.log')
            [IO.File]::WriteAllText((Join-Path $data 'server.pid'), [string]$service.Id)
        } else {
            Write-Host '[4/4] 本目录的 Bot 已经运行，正在检查管理面板……'
            $service = Get-Process -Id $existing.ProcessId
        }
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            $service.Refresh()
            if ($service.HasExited) { break }
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri $info.panel_url -TimeoutSec 2
                if ($response.StatusCode -eq 200 -and $response.Content -match 'id="panel-username"') { $ready = $true; break }
            } catch {}
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) {
            if (-not $existing -and -not $service.HasExited) {
                & "$env:SystemRoot\System32\taskkill.exe" /PID $service.Id /T /F | Out-Null
            }
            throw 'Bot 没有正常就绪。请查看 data\server-error.log；已有配置和数据未被覆盖。'
        }
        Write-Host "部署完成！Bot 在后台运行，可以关闭此窗口。停止可在此窗口菜单中选择，或重新打开 $entrypoint。" -ForegroundColor Green
        if (-not $WithoutBrowser) {
            try { Start-Process -FilePath $info.panel_url }
            catch { Write-Host '无法自动打开浏览器，请复制上方管理面板地址访问。' }
        }
    } finally { if ($lock) { $lock.Dispose() } }
}


function Stop-StarBridgeWindows {
    param([string]$Root)
    $pidFile = Join-Path $Root 'data\server.pid'
    if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host '没有记录后台进程。'; return }
    $lock = $null
    try {
        try { $lock = [IO.File]::Open((Join-Path $Root 'data\install.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
        catch { throw '另一个窗口正在处理此目录，请稍后重试。' }
        $serviceId = 0
        if (-not [int]::TryParse((Get-Content -Raw -LiteralPath $pidFile).Trim(), [ref]$serviceId) -or $serviceId -le 0) { throw '后台 PID 记录无效，未停止任何进程。' }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId" -ErrorAction SilentlyContinue
        if (-not $process) { Write-Host '后台服务已经停止。'; return }
        $venv = Join-Path $Root '.venv\Scripts\python.exe'
        if (-not (Test-StarBridgeProcess -Python $venv -PidFile $pidFile)) { throw 'PID 对应的进程与本项目不符，未停止任何进程。' }
        # Windows venv launches a child Python process; stop the verified process tree.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $serviceId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '停止失败，请查看进程状态后重试。' }
        Write-Host 'Myrinbot后台服务已停止。' -ForegroundColor Green
    } finally { if ($lock) { $lock.Dispose() } }
}

function Invoke-StarBridgeAction {
    param([string]$Action)
    switch ($Action.ToLowerInvariant()) {
        'start' { Start-StarBridgeWindows -Root $root -RequestedPython $env:STARBRIDGE_PYTHON -WithoutBrowser:$quiet }
        'install' { Start-StarBridgeWindows -Root $root -RequestedPython $env:STARBRIDGE_PYTHON -InstallOnly -WithoutBrowser }
        'stop' { Stop-StarBridgeWindows -Root $root }
        'restart' { Stop-StarBridgeWindows -Root $root; Start-StarBridgeWindows -Root $root -RequestedPython $env:STARBRIDGE_PYTHON -WithoutBrowser:$quiet }
        default { throw "用法：$entrypoint [start|stop|restart|install] [quiet]" }
    }
}

$root = [IO.Path]::GetDirectoryName($env:STARBRIDGE_SELF)
$quiet = $env:STARBRIDGE_QUIET -eq 'quiet'
$action = $env:STARBRIDGE_ACTION
if (-not $action) { $action = 'start' }
try {
    Invoke-StarBridgeAction -Action $action
    if (-not $quiet) {
        while ($true) {
            Write-Host ''
            Write-Host 'Myrinbot  |  1 打开面板  2 启动  3 停止  4 重启  0 关闭窗口'
            $choice = Read-Host '请选择'
            switch ($choice) {
                '0' { exit 0 }
                '1' {
                    $python = Join-Path $root '.venv\Scripts\python.exe'
                    $info = & $python (Join-Path $root 'scripts\windows_runtime.py') info
                    if ($LASTEXITCODE -ne 0) { throw '无法读取面板地址，请检查配置。' }
                    Start-Process -FilePath (($info | ConvertFrom-Json).panel_url)
                }
                '2' { Invoke-StarBridgeAction -Action 'start' }
                '3' { Invoke-StarBridgeAction -Action 'stop' }
                '4' { Invoke-StarBridgeAction -Action 'restart' }
                default { Write-Host '请输入 0 到 4。' }
            }
        }
    }
    exit 0
} catch {
    Write-Host "操作失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
