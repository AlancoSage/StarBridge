param([string]$JavaHome = $env:JAVA_HOME, [string]$Python = 'python', [string]$Version = '')
$ErrorActionPreference = 'Stop'
$buildArguments = @((Join-Path $PSScriptRoot 'build.py'), '--java-home', $JavaHome)
if ($Version) { $buildArguments += @('--version', $Version) }
& $Python @buildArguments
if ($LASTEXITCODE -ne 0) { throw 'Fabric bridge build failed.' }
