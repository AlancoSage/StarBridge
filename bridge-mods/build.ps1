param([string]$JavaHome = $env:JAVA_HOME, [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
& $Python (Join-Path $PSScriptRoot 'build.py') --java-home $JavaHome
if ($LASTEXITCODE -ne 0) { throw 'Java 8 Forge bridge build failed.' }
