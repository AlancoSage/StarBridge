param(
    [string]$JavaHome = 'C:\Program Files\Java\jdk-17',
    [string]$RuntimeJavaHome = $JavaHome,
    [string[]]$ApiJars = @()
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build.ps1') -JavaHome $JavaHome
$target = Join-Path $PSScriptRoot 'target'
$classes = Join-Path $target 'classes'
$tests = Join-Path $target 'compat-test-classes'
$api = Join-Path $target 'spigot-api-1.8.8-shaded.jar'
$gson = Join-Path $target 'gson-2.13.2.jar'
$asm = Join-Path $target 'asm-9.8.jar'
$jar = Join-Path $target 'VexBot-0.5.6.jar'
$legacyJar = Join-Path $target 'StarBridge-0.5.6.jar'
if ((Get-FileHash -LiteralPath $jar -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $legacyJar -Algorithm SHA256).Hash) {
    throw 'Legacy updater artifact must match the primary JAR'
}
$expected = '2e192832b9ddb70d89b376559282969371d9b062110d5b93aa698ae9784f8608'
if (-not (Test-Path -LiteralPath $api) -or (Get-FileHash -LiteralPath $api -Algorithm SHA256).Hash -ne $expected) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri 'https://hub.spigotmc.org/nexus/content/repositories/snapshots/org/spigotmc/spigot-api/1.8.8-R0.1-SNAPSHOT/spigot-api-1.8.8-R0.1-20160221.082514-43-shaded.jar' -OutFile "$api.download"
    if ((Get-FileHash -LiteralPath "$api.download" -Algorithm SHA256).Hash -ne $expected) { throw 'Test dependency checksum mismatch' }
    Move-Item -LiteralPath "$api.download" -Destination $api -Force
}
New-Item -ItemType Directory -Force -Path $tests | Out-Null
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\compat-test\java') -Filter '*.java' -Recurse | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -cp "$gson;$api;$classes" -d $tests @sources
if ($LASTEXITCODE -ne 0) { throw 'Compatibility test compilation failed' }
foreach ($check in @('BridgeHttpCheck', 'BukkitCompatibilityCheck')) {
    & "$RuntimeJavaHome\bin\java.exe" -ea -cp "$tests;$classes;$gson;$api" "cn.starbridge.$check"
    if ($LASTEXITCODE -ne 0) { throw "$check failed" }
}
& "$RuntimeJavaHome\bin\java.exe" -ea -cp "$tests;$jar;$api" cn.starbridge.PackagedJarCheck
if ($LASTEXITCODE -ne 0) { throw 'Packaged JAR checks failed' }
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -cp $asm -d $tests (Join-Path $PSScriptRoot 'tools\ApiLinkageCheck.java')
if ($LASTEXITCODE -ne 0) { throw 'API linkage checker compilation failed' }
if ($ApiJars.Count -eq 0) { $ApiJars = @($api) }
& "$RuntimeJavaHome\bin\java.exe" -cp "$tests;$asm" ApiLinkageCheck $jar @ApiJars
if ($LASTEXITCODE -ne 0) { throw 'API linkage checks failed' }
