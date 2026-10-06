param([string]$JavaHome = 'C:\Program Files\Java\jdk-17')
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build.ps1') -JavaHome $JavaHome
$target = Join-Path $PSScriptRoot 'target'
$testClasses = Join-Path $target 'test-classes'
New-Item -ItemType Directory -Force -Path $testClasses | Out-Null
$api = Join-Path $target 'spigot-api-1.20.4-shaded.jar'
$classes = Join-Path $target 'classes'
$testSources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\test\java') -Recurse -Filter '*.java' | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 17 -encoding UTF-8 -cp "$api;$classes" -d $testClasses @testSources
if ($LASTEXITCODE -ne 0) { throw 'Java test compilation failed' }
& "$JavaHome\bin\java.exe" -ea -cp "$testClasses;$classes;$api" cn.starbridge.GameLoginCheck
if ($LASTEXITCODE -ne 0) { throw 'Java game login checks failed' }
