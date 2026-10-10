param([string]$JavaHome = 'C:\Program Files\Java\jdk-17')
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'target'
$classes = Join-Path $target 'adapter-main-classes'
$tests = Join-Path $target 'adapter-test-classes'
$gson = Join-Path $target 'gson-2.13.2.jar'
$api = Join-Path $target 'spigot-api-1.20.4-shaded.jar'
$legacyApi = Join-Path $target 'spigot-api-1.8.8.jar'
if (-not (Test-Path -LiteralPath $api)) { throw 'Run bridge/test.ps1 first to prepare verified test dependencies.' }
New-Item -ItemType Directory -Force -Path $tests, $classes | Out-Null
$production = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\main\java\cn\starbridge') -Filter '*.java' | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -cp "$gson;$legacyApi" -d $classes @production
if ($LASTEXITCODE -ne 0) { throw 'Adapter production compilation failed' }
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\login-adapter-test\java') -Recurse -Filter '*.java' | ForEach-Object FullName)
$sources += Join-Path $PSScriptRoot 'src\login-test\java\org\bukkit\entity\Player.java'
$sources += Join-Path $PSScriptRoot 'src\login-test\java\org\bukkit\World.java'
& "$JavaHome\bin\javac.exe" --release 17 -encoding UTF-8 -cp "$gson;$api;$classes" -d $tests @sources
if ($LASTEXITCODE -ne 0) { throw 'Login adapter fixture compilation failed' }
foreach ($fixture in @('NLoginLinkCheck', 'LoginSecurityLinkCheck', 'LibreLoginLinkCheck')) {
    & "$JavaHome\bin\java.exe" -ea -cp "$tests;$classes;$gson;$api" "cn.starbridge.$fixture"
    if ($LASTEXITCODE -ne 0) { throw "$fixture failed" }
}
