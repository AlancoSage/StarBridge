param([string]$JavaHome = 'C:\Program Files\Java\jdk-17')
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build.ps1') -JavaHome $JavaHome
$target = Join-Path $PSScriptRoot 'target'
$testClasses = Join-Path $target 'test-classes'
New-Item -ItemType Directory -Force -Path $testClasses | Out-Null
$api = Join-Path $target 'spigot-api-1.20.4-shaded.jar'
$classes = Join-Path $target 'classes'
$gson = Join-Path $target 'gson-2.13.2.jar'
$expectedApi = '60307fe037d748e4f371ee6755647841a999b7aa27d66079b2c53d6a7375867a'
if (-not (Test-Path -LiteralPath $api) -or (Get-FileHash -LiteralPath $api -Algorithm SHA256).Hash -ne $expectedApi) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $url = 'https://hub.spigotmc.org/nexus/content/repositories/snapshots/org/spigotmc/spigot-api/1.20.4-R0.1-SNAPSHOT/spigot-api-1.20.4-R0.1-20240423.152506-123-shaded.jar'
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile "$api.download"
    if ((Get-FileHash -LiteralPath "$api.download" -Algorithm SHA256).Hash -ne $expectedApi) { throw 'Login test API checksum mismatch' }
    Move-Item -LiteralPath "$api.download" -Destination $api -Force
}
$testSources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\login-test\java') -Recurse -Filter '*.java' | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 17 -encoding UTF-8 -cp "$gson;$api;$classes" -d $testClasses @testSources
if ($LASTEXITCODE -ne 0) { throw 'Java test compilation failed' }
foreach ($check in @('GameLoginCheck', 'BindingGateCheck')) {
    & "$JavaHome\bin\java.exe" -ea -cp "$testClasses;$classes;$gson;$api" "cn.starbridge.$check"
    if ($LASTEXITCODE -ne 0) { throw "Java $check checks failed" }
}
