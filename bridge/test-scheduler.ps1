param([string]$JavaHome = 'C:\Program Files\Java\jdk-17', [string]$RuntimeJavaHome = $JavaHome)
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'target\scheduler-tests'
$common = Join-Path $target 'common'
$folia = Join-Path $target 'folia'
New-Item -ItemType Directory -Force -Path $common, $folia | Out-Null
$sources = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src\scheduler-test\java') -Filter '*.java' -Recurse | ForEach-Object FullName)
$sources += Join-Path $PSScriptRoot 'src\main\java\cn\starbridge\BridgeScheduler.java'
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -d $common @sources
if ($LASTEXITCODE -ne 0) { throw 'Scheduler test compilation failed' }
$marker = Join-Path $PSScriptRoot 'src\scheduler-test\folia\java\io\papermc\paper\threadedregions\RegionizedServer.java'
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -d $folia $marker
if ($LASTEXITCODE -ne 0) { throw 'Folia marker compilation failed' }
& "$RuntimeJavaHome\bin\java.exe" -ea -cp "$common" cn.starbridge.BridgeSchedulerCheck false
if ($LASTEXITCODE -ne 0) { throw 'Legacy scheduler checks failed' }
& "$RuntimeJavaHome\bin\java.exe" -ea -cp "$folia;$common" cn.starbridge.BridgeSchedulerCheck true
if ($LASTEXITCODE -ne 0) { throw 'Folia scheduler checks failed' }
