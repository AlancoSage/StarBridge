$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '请先安装 Python 3.11 或更高版本。' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络。' }
if (-not (Test-Path -LiteralPath 'config.toml')) {
    & '.\.venv\Scripts\python.exe' -m starbridge init
    if ($LASTEXITCODE -ne 0) { throw '初始配置生成失败。' }
    Write-Host '请使用 config.toml 中的 app.admin_token 登录面板，其余设置可在面板内调整。'
}
& '.\.venv\Scripts\python.exe' -m starbridge run
