param([string]$PythonPath = '', [switch]$NoStart, [switch]$NoBrowser)
& (Join-Path $PSScriptRoot 'install.ps1') -PythonPath $PythonPath -NoStart:$NoStart -NoBrowser:$NoBrowser
exit $LASTEXITCODE
