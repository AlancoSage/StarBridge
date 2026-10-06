param(
    [int]$Port = 8089,
    [string]$BindAddress = '127.0.0.1',
    [string]$ApiBase = ''
)
$ErrorActionPreference = 'Stop'
$scriptFile = Join-Path $PSScriptRoot 'serve.py'
$websiteArguments = @($scriptFile, '--host', $BindAddress, '--port', [string]$Port)
if ($ApiBase) { $websiteArguments += @('--api-base', $ApiBase) }
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @websiteArguments
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @websiteArguments
} else {
    throw 'Install Python 3.11 or later, or deploy these static files with Nginx.'
}
exit $LASTEXITCODE
