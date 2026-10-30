# =============================================================
# instalar_agente.ps1 — EXECUTE COMO ADMINISTRADOR
# =============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  INSTALAÇÃO DO AGENTE DE IMPRESSÃO" -ForegroundColor Cyan
Write-Host "  Máquina: $env:COMPUTERNAME" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptMonitor = "$PSScriptRoot\monitor_impressao.ps1"

if (-not (Test-Path $scriptMonitor)) {
    Write-Host "[ERRO] Arquivo não encontrado: $scriptMonitor" -ForegroundColor Red
    Write-Host "Certifique-se de que monitor_impressao.ps1 está na mesma pasta." -ForegroundColor Yellow
    Read-Host "Pressione Enter para sair"
    exit 1
}

# 1. Habilitar Log de Impressão
Write-Host "Passo 1: Habilitando Log de Impressão do Windows..." -ForegroundColor Cyan
wevtutil sl "Microsoft-Windows-PrintService/Operational" /e:true 2>&1 | Out-Null
Write-Host "  [OK] Log habilitado." -ForegroundColor Green

# 2. Remover tarefa antiga e matar processo
$taskName = "MonitorImpressao"
Write-Host "Passo 2: Removendo tarefa anterior e encerrando processo antigo..." -ForegroundColor Cyan

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Matar processos rodando o script antigo
Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -match "monitor_impressao.ps1" } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "  [OK] Feito." -ForegroundColor Green

# 3. Descobrir o usuário logado atual (não SYSTEM)
Write-Host "Passo 3: Detectando usuário logado..." -ForegroundColor Cyan
$usuarioLogado = (Get-CimInstance -ClassName Win32_ComputerSystem).UserName
if (-not $usuarioLogado) {
    # Fallback: usar variável de ambiente
    $usuarioLogado = "$env:USERDOMAIN\$env:USERNAME"
}
Write-Host "  [OK] Usuário: $usuarioLogado" -ForegroundColor Green

# 4. Criar tarefa agendada rodando como o USUÁRIO (não SYSTEM)
#    Isso é essencial para ler os eventos de impressão corretamente
Write-Host "Passo 4: Criando tarefa agendada para o usuário '$usuarioLogado'..." -ForegroundColor Cyan

$action   = New-ScheduledTaskAction -Execute 'powershell.exe' `
                -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptMonitor`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $usuarioLogado
$settings = New-ScheduledTaskSettingsSet `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -StartWhenAvailable `
                -RestartCount 5 `
                -RestartInterval (New-TimeSpan -Minutes 1)

# Registrar tarefa para rodar como o usuário logado (com privilégios mais altos)
Register-ScheduledTask `
    -TaskName  $taskName `
    -Action    $action `
    -Trigger   $trigger `
    -Settings  $settings `
    -RunLevel  Highest `
    -User      $usuarioLogado `
    -Force | Out-Null

Write-Host "  [OK] Tarefa '$taskName' criada para o usuário '$usuarioLogado'." -ForegroundColor Green

# 5. Iniciar o monitor AGORA (sem esperar reinício)
Write-Host "Passo 5: Iniciando monitor agora..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2

# Verificar se iniciou
$taskInfo = Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo
if ($taskInfo.LastTaskResult -eq 0 -or $taskInfo.NumberOfMissedRuns -eq 0) {
    Write-Host "  [OK] Monitor iniciado em segundo plano!" -ForegroundColor Green
} else {
    Write-Host "  [AVISO] Pode ser necessário reiniciar o Windows para ativar." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  INSTALAÇÃO CONCLUÍDA!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "PROXIMOS PASSOS:" -ForegroundColor Yellow
Write-Host "  1. Faca uma impressao de teste nesta maquina."
Write-Host "  2. Aguarde 10 segundos e verifique o dashboard."
Write-Host "  3. Se nao aparecer, execute: agente_diagnostico.ps1"
Write-Host ""
