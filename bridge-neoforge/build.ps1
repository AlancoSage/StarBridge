param([string]$JavaHome = $env:JAVA_HOME)
$ErrorActionPreference = 'Stop'
if ($JavaHome) { $env:JAVA_HOME = $JavaHome }
$sourceRoot = $PSScriptRoot
$stagingRoot = $null
# Java 17 on Windows reads launcher argument files using the system code page.
# Gradle writes them in UTF-8; staging in ASCII avoids broken test classpaths.
if ($sourceRoot -match '[^\x00-\x7F]') {
    $stagingRoot = Join-Path $env:TEMP ('VexBot-NeoForge-' + [guid]::NewGuid().ToString('N'))
    if ($stagingRoot -match '[^\x00-\x7F]') { throw 'Please build from an ASCII path and set TEMP to an ASCII directory.' }
    New-Item -ItemType Directory -Path $stagingRoot | Out-Null
    foreach ($name in @('src', 'gradle', 'gradlew', 'gradlew.bat', 'build.gradle', 'settings.gradle', 'gradle.properties')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination $stagingRoot -Recurse
    }
    $previousGradleHome = $env:GRADLE_USER_HOME
    if ($env:GRADLE_USER_HOME -match '[^\x00-\x7F]') { $env:GRADLE_USER_HOME = Join-Path $env:TEMP 'StarBridge-NeoForge-Gradle' }
}
Push-Location $(if ($stagingRoot) { $stagingRoot } else { $sourceRoot })
try {
    $task = if ($stagingRoot) { 'build' } else { 'copyBridge' }
    & ./gradlew.bat $task --console=plain "-PstarbridgeLicenseRoot=$(Split-Path $sourceRoot -Parent)"
    if ($LASTEXITCODE -ne 0) { throw 'Forge build failed' }
    if ($stagingRoot) {
        $output = Join-Path (Split-Path $sourceRoot -Parent) 'bridge/target'
        New-Item -ItemType Directory -Force $output | Out-Null
        foreach ($built in Get-ChildItem -Path (Join-Path $stagingRoot 'build/libs/VexBot-NeoForge-1.21.1-*.jar')) {
            Copy-Item -LiteralPath $built.FullName -Destination (Join-Path $output $built.Name) -Force
            Copy-Item -LiteralPath $built.FullName -Destination (Join-Path $output ($built.Name -replace '^VexBot-', 'Myrinbot-')) -Force
            Copy-Item -LiteralPath $built.FullName -Destination (Join-Path $output ($built.Name -replace '^VexBot-', 'StarBridge-')) -Force
        }
    }
} finally {
    Pop-Location
    if ($stagingRoot) { $env:GRADLE_USER_HOME = $previousGradleHome }
}
