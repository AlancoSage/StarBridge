param([string]$JavaHome = 'C:\Program Files\Java\jdk-17')
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'target'
$classes = Join-Path $target 'login-folia-main-classes'
$tests = Join-Path $target 'login-folia-test-classes'
$gson = Join-Path $target 'gson-2.13.2.jar'
$api = Join-Path $target 'spigot-api-1.20.4-shaded.jar'
if (-not (Test-Path -LiteralPath $api)) { throw 'Run bridge/test.ps1 first to prepare verified Bukkit dependencies.' }
New-Item -ItemType Directory -Force -Path $tests | Out-Null
New-Item -ItemType Directory -Force -Path $classes | Out-Null
$legacyApi = Join-Path $target 'spigot-api-1.8.8.jar'
$production = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\main\java\cn\starbridge') -Filter '*.java' | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -cp "$gson;$legacyApi" -d $classes @production
if ($LASTEXITCODE -ne 0) { throw 'Isolated production compilation for Folia login checks failed' }
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\login-folia-test\java') -Recurse -Filter '*.java' | ForEach-Object FullName)
$sources += @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\scheduler-test\java\io') -Recurse -Filter '*.java' | ForEach-Object FullName)
$sources += Join-Path $PSScriptRoot 'src\scheduler-test\folia\java\io\papermc\paper\threadedregions\RegionizedServer.java'
$sources += Join-Path $PSScriptRoot 'src\login-test\java\org\spigotmc\SpigotConfig.java'
& "$JavaHome\bin\javac.exe" --release 17 -encoding UTF-8 -cp "$gson;$api;$classes" -d $tests @sources
if ($LASTEXITCODE -ne 0) { throw 'Folia login fixture compilation failed' }
& "$JavaHome\bin\java.exe" -ea -cp "$tests;$classes;$gson;$api" cn.starbridge.GameLoginFoliaCheck
if ($LASTEXITCODE -ne 0) { throw 'Folia game login checks failed' }
