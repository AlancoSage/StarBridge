param([string]$JavaHome = $env:JAVA_HOME)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
if (-not $JavaHome) {
    $candidate = 'C:\Program Files\Java\jdk-17'
    if (Test-Path -LiteralPath "$candidate\bin\javac.exe") { $JavaHome = $candidate }
    else { throw '请设置 JAVA_HOME，或使用 -JavaHome 指定 JDK 17+ 路径。' }
}
$target = Join-Path $project 'target'
$classes = Join-Path $target 'classes'
New-Item -ItemType Directory -Force -Path $classes | Out-Null
$api = Join-Path $target 'spigot-api-1.20.4-shaded.jar'
$url = 'https://hub.spigotmc.org/nexus/content/repositories/snapshots/org/spigotmc/spigot-api/1.20.4-R0.1-SNAPSHOT/spigot-api-1.20.4-R0.1-20240423.152506-123-shaded.jar'
if (-not (Test-Path -LiteralPath $api)) { Invoke-WebRequest -Uri $url -OutFile $api }
$sources = @(Get-ChildItem -LiteralPath (Join-Path $project 'src\main\java\cn\starbridge') -Filter '*.java' | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 17 -encoding UTF-8 -cp $api -d $classes @sources
if ($LASTEXITCODE -ne 0) { throw 'Java 编译失败' }
$jar = Join-Path $target 'StarBridge-0.5.0.jar'
& "$JavaHome\bin\jar.exe" --create --file $jar -C $classes . -C (Join-Path $project 'src\main\resources') .
if ($LASTEXITCODE -ne 0) { throw 'JAR 打包失败' }
Write-Output "插件已生成：$jar"
