# =============================================================
# INSTALAÇÃO REMOTA DO AGENTE DE IMPRESSÃO
# Este script é baixado e executado automaticamente via rede.
# =============================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " INSTALANDO AGENTE DE IMPRESSÃO - CLIENTE " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$serverIP = "192.168.1.230:3001"
$pastaDestino = "C:\AgentImpressao"

# 1. Cria a pasta local
if (-not (Test-Path $pastaDestino)) {
    New-Item -ItemType Directory -Path $pastaDestino -Force | Out-Null
}

# 2. Faz o download dos scripts mais recentes direto do seu servidor
Write-Host "-> Baixando scripts do servidor..." -ForegroundColor Yellow
$urlMonitor = "http://$serverIP/agent/monitor_impressao.ps1"
$urlDiag    = "http://$serverIP/agent/agente_diagnostico.ps1"

Invoke-WebRequest -Uri $urlMonitor -OutFile "$pastaDestino\monitor_impressao.ps1" -UseBasicParsing
Invoke-WebRequest -Uri $urlDiag -OutFile "$pastaDestino\agente_diagnostico.ps1" -UseBasicParsing

# 3. Habilita o Log de Impressão do Windows
Write-Host "-> Habilitando rastreamento de impressao no Windows..." -ForegroundColor Yellow
wevtutil sl "Microsoft-Windows-PrintService/Operational" /e:true 2>&1 | Out-Null

# 4. Remove tarefa agendada antiga se existir
$taskName = "MonitorImpressao"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 5. Descobrir usuario atual para rodar a tarefa nele
$usuarioLogado = (Get-CimInstance -ClassName Win32_ComputerSystem).UserName
if (-not $usuarioLogado) { $usuarioLogado = "$env:USERDOMAIN\$env:USERNAME" }

# 6. Cria nova tarefa agendada
Write-Host "-> Criando processo de monitoramento para o usuario $usuarioLogado..." -ForegroundColor Yellow
$action   = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$pastaDestino\monitor_impressao.ps1`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $usuarioLogado
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName  $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -User $usuarioLogado -Force | Out-Null

# 7. Inicia o monitor agora mesmo
Start-ScheduledTask -TaskName $taskName
Write-Host ""
Write-Host "[OK] Tudo configurado e agente rodando em segundo plano!" -ForegroundColor Green
Write-Host "Voce ja pode fazer uma impressao de teste!" -ForegroundColor Green
Write-Host ""
