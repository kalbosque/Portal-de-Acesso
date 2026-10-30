# =============================================================
# deploy_todos.ps1 - Deploy do Agente em TODAS as Maquinas
# Execute como Administrador NO SERVIDOR
# Requer: Compartilhamento de rede e acesso administrativo
# =============================================================

# --- CONFIGURACAO ---
$pastaLocal     = $PSScriptRoot
$pastaDestino   = "AgentImpressao"
$listaMaquinas  = "$PSScriptRoot\lista_maquinas.txt"
$adminUser      = ""   # Deixe vazio para usar credenciais atuais
$logDeploy      = "$PSScriptRoot\deploy_log.txt"
# --------------------

$arquivos = @(
    "monitor_impressao.ps1",
    "instalar_agente.ps1",
    "agente_diagnostico.ps1"
)

function Write-Log {
    param([string]$msg, [string]$cor = "White")
    $linha = "$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') | $msg"
    Write-Host $linha -ForegroundColor $cor
    Add-Content -Path $logDeploy -Value $linha -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  DEPLOY EM MASSA - AGENTE DE IMPRESSAO" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $listaMaquinas)) {
    Write-Host "[ERRO] Arquivo lista_maquinas.txt nao encontrado em: $listaMaquinas" -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}

$linhasBrutas = Get-Content $listaMaquinas | Where-Object { $_ -notmatch '^\s*#' -and $_.Trim() -ne '' }
$maquinas = @()

foreach ($linha in $linhasBrutas) {
    # Remove qualquer coisa depois do '#' para limpar os comentarios do IP na mesma linha
    $maqLimpa = ($linha -split '#')[0].Trim()
    if ($maqLimpa) {
        $maquinas += $maqLimpa
    }
}

if ($maquinas.Count -eq 0) {
    Write-Host "[ERRO] Lista de maquinas esta vazia! Edite lista_maquinas.txt" -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}

Write-Host "Maquinas na lista: $($maquinas.Count)" -ForegroundColor Yellow
Write-Host ""

$sucesso = 0
$falha   = 0
$offline = 0
$resultados = @()

foreach ($maquina in $maquinas) {
    Write-Host "----------------------------------------" -ForegroundColor DarkGray
    Write-Host "[$($sucesso+$falha+$offline+1)/$($maquinas.Count)] Processando: $maquina" -ForegroundColor Cyan

    $ping = Test-Connection -ComputerName $maquina -Count 1 -Quiet -ErrorAction SilentlyContinue
    if (-not $ping) {
        Write-Log "[$maquina] OFFLINE ou inacessivel - pulando." "Yellow"
        $offline++
        $resultados += [PSCustomObject]@{ Maquina=$maquina; Status="OFFLINE" }
        continue
    }
    Write-Host "  [OK] Maquina online." -ForegroundColor Green

    $destUNC = "\\$maquina\C$\$pastaDestino"
    try {
        if (-not (Test-Path $destUNC)) {
            New-Item -ItemType Directory -Path $destUNC -Force | Out-Null
        }

        foreach ($arq in $arquivos) {
            $origem = "$pastaLocal\$arq"
            if (Test-Path $origem) {
                Copy-Item -Path $origem -Destination $destUNC -Force
            }
        }
        Write-Host "  [OK] Arquivos copiados." -ForegroundColor Green
    } catch {
        Write-Log "[$maquina] ERRO ao copiar arquivos: $($_.Exception.Message)" "Red"
        $falha++
        $resultados += [PSCustomObject]@{ Maquina=$maquina; Status="ERRO_COPIA" }
        continue
    }

    try {
        Invoke-Command -ComputerName $maquina -ScriptBlock {
            wevtutil sl "Microsoft-Windows-PrintService/Operational" /e:true 2>&1 | Out-Null
        } -ErrorAction Stop
        Write-Host "  [OK] Log de impressao habilitado remotamente." -ForegroundColor Green
    } catch {
        Write-Log "  [AVISO] Nao habilitou o log via remoto: $($_.Exception.Message)" "Yellow"
    }

    try {
        $taskName  = "MonitorImpressao"
        $psArgs    = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"C:\$pastaDestino\monitor_impressao.ps1`""
        
        $delCmd = "schtasks /delete /tn `"$taskName`" /f /s $maquina"
        Invoke-Expression $delCmd 2>&1 | Out-Null

        $createCmd = "schtasks /create /s $maquina /tn `"$taskName`" /tr `"powershell.exe $psArgs`" /sc ONLOGON /rl HIGHEST /f /ru INTERACTIVE"
        $result = Invoke-Expression $createCmd 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Tarefa agendada criada com SUCESSO." -ForegroundColor Green
            $sucesso++
            $resultados += [PSCustomObject]@{ Maquina=$maquina; Status="SUCESSO" }
        } else {
            throw $result
        }
    } catch {
        Write-Log "[$maquina] ERRO ao criar tarefa: $($_.Exception.Message)" "Red"
        $falha++
        $resultados += [PSCustomObject]@{ Maquina=$maquina; Status="ERRO_TAREFA" }
    }

    # --- INICIA O AGENTE IMEDIATAMENTE (sem esperar reinicio) ---
    try {
        Invoke-Command -ComputerName $maquina -ScriptBlock {
            param($destino, $psArgs)
            # Mata processos antigos do agente
            Get-Process powershell -ErrorAction SilentlyContinue | Where-Object {
                $_.MainWindowTitle -match 'monitor' -or
                (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine -match 'monitor_impressao'
            } | Stop-Process -Force -ErrorAction SilentlyContinue

            # Inicia o novo agente em background (sem janela)
            Start-Process powershell.exe -ArgumentList $psArgs -WindowStyle Hidden
        } -ArgumentList "C:\$pastaDestino", $psArgs -ErrorAction Stop

        Write-Host "  [OK] Agente v3.0 iniciado em SEGUNDO PLANO na maquina remota!" -ForegroundColor Green
    } catch {
        Write-Host "  [AVISO] Nao foi possivel iniciar remotamente (sera ativo no proximo login): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  RELATORIO FINAL DO DEPLOY" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Total             : $($maquinas.Count)" -ForegroundColor White
Write-Host "  [SUCESSO]         : $sucesso" -ForegroundColor Green
Write-Host "  [ERRO]            : $falha" -ForegroundColor Red
Write-Host "  [OFFLINE]         : $offline" -ForegroundColor Yellow
Write-Host ""

$problemas = $resultados | Where-Object { $_.Status -notlike "SUCESSO*" }
if ($problemas.Count -gt 0) {
    Write-Host "Problemas encontrados:" -ForegroundColor Yellow
    foreach ($p in $problemas) {
        Write-Host "  $($p.Maquina) - $($p.Status)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Log salvo em: $logDeploy" -ForegroundColor DarkGray
Write-Host "NOTA: As maquinas que deram SUCESSO iniciarao o monitoramento" -ForegroundColor Yellow
Write-Host "      automaticamente quando o sistema for reiniciado ou login for feito." -ForegroundColor Yellow
Write-Host ""
Read-Host "Pressione Enter para fechar"
