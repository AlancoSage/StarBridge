param([string]$JavaHome = $env:JAVA_HOME)
$ErrorActionPreference = 'Stop'
if ($JavaHome) { python (Join-Path $PSScriptRoot 'build.py') --java-home $JavaHome }
else { python (Join-Path $PSScriptRoot 'build.py') }
if ($LASTEXITCODE -ne 0) { throw 'Velocity bridge build failed' }
