$ErrorActionPreference = 'Stop'

$desktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $desktopRoot
$configPath = Join-Path $desktopRoot 'src-tauri\tauri.conf.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

Push-Location $desktopRoot
try {
    npm.cmd run build
} finally {
    Pop-Location
}

$version = [string]$config.version
$source = Join-Path $desktopRoot "src-tauri\target\release\bundle\nsis\Central de Atendimento Operador_${version}_x64-setup.exe"
$downloads = Join-Path $projectRoot 'backend\static\downloads'
$latest = Join-Path $downloads 'Central-de-Atendimento-Operador-latest.exe'

if (-not (Test-Path -LiteralPath $source)) {
    throw "Instalador não encontrado: $source"
}

New-Item -ItemType Directory -Force -Path $downloads | Out-Null
Copy-Item -LiteralPath $source -Destination $latest -Force
Write-Host "Instalador publicado na página: $latest"
