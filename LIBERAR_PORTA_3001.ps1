param(
    [int]$Port = 3001
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host "Este script precisa ser executado como Administrador." -ForegroundColor Red
    Write-Host "Abra o PowerShell como admin e rode novamente: .\LIBERAR_PORTA_3001.ps1" -ForegroundColor Yellow
    exit 1
}

$ruleName = "PrintDash TCP $Port"

Write-Host "Verificando regra de firewall para a porta $Port..." -ForegroundColor Cyan

$existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null
if ($LASTEXITCODE -eq 0 -and $existing -match [regex]::Escape($ruleName)) {
    Write-Host "A regra '$ruleName' já existe." -ForegroundColor Green
    exit 0
}

Write-Host "Criando regra de entrada para TCP/$Port..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$Port profile=any | Out-Null

if ($LASTEXITCODE -eq 0) {
    Write-Host "Porta $Port liberada com sucesso." -ForegroundColor Green
    Write-Host "Teste novamente em: http://192.168.1.230:$Port" -ForegroundColor Green
} else {
    Write-Host "Não foi possível criar a regra automaticamente." -ForegroundColor Red
    exit 1
}
