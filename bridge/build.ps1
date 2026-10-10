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
$api = Join-Path $target 'spigot-api-1.8.8.jar'
$gson = Join-Path $target 'gson-2.13.2.jar'
$asm = Join-Path $target 'asm-9.8.jar'
$asmCommons = Join-Path $target 'asm-commons-9.8.jar'
function Get-VerifiedDependency {
    param([string]$Path, [string]$Url, [string]$Sha256)
    if ((Test-Path -LiteralPath $Path) -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Sha256) { return }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile "$Path.download"
    if ((Get-FileHash -LiteralPath "$Path.download" -Algorithm SHA256).Hash -ne $Sha256) { throw 'Dependency checksum mismatch' }
    Move-Item -LiteralPath "$Path.download" -Destination $Path -Force
}
Get-VerifiedDependency -Path $api -Url 'https://hub.spigotmc.org/nexus/content/repositories/snapshots/org/spigotmc/spigot-api/1.8.8-R0.1-SNAPSHOT/spigot-api-1.8.8-R0.1-20160221.082514-43.jar' -Sha256 'bc50bbc4d8226d75d0d75460828567b4580841d5987cae5c1d89b321f8ffc071'
Get-VerifiedDependency -Path $gson -Url 'https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.13.2/gson-2.13.2.jar' -Sha256 'dd0ce1b55a3ed2080cb70f9c655850cda86c206862310009dcb5e5c95265a5e0'
Get-VerifiedDependency -Path $asm -Url 'https://repo.maven.apache.org/maven2/org/ow2/asm/asm/9.8/asm-9.8.jar' -Sha256 '876eab6a83daecad5ca67eb9fcabb063c97b5aeb8cf1fca7a989ecde17522051'
Get-VerifiedDependency -Path $asmCommons -Url 'https://repo.maven.apache.org/maven2/org/ow2/asm/asm-commons/9.8/asm-commons-9.8.jar' -Sha256 '3301a1c1cb4c59fcc5292648dac1d7c5aed4c0f067dfbe88873b8cdfe77404f4'
$sources = @(Get-ChildItem -LiteralPath (Join-Path $project 'src\main\java\cn\starbridge') -Filter '*.java' | ForEach-Object FullName)
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -cp "$api;$gson" -d $classes @sources
if ($LASTEXITCODE -ne 0) { throw 'Java 编译失败' }
$jar = Join-Path $target 'StarBridge-0.5.2.jar'
$toolClasses = Join-Path $target 'build-tools'
New-Item -ItemType Directory -Force -Path $toolClasses | Out-Null
& "$JavaHome\bin\javac.exe" --release 8 -encoding UTF-8 -cp "$asm;$asmCommons" -d $toolClasses (Join-Path $project 'tools\ShadeJar.java')
if ($LASTEXITCODE -ne 0) { throw 'Dependency relocation tool compilation failed' }
& "$JavaHome\bin\java.exe" -cp "$toolClasses;$asm;$asmCommons" ShadeJar $classes (Join-Path $project 'src\main\resources') $gson $jar (Split-Path $project -Parent)
if ($LASTEXITCODE -ne 0) { throw 'JAR 打包失败' }
Write-Output "插件已生成：$jar"
