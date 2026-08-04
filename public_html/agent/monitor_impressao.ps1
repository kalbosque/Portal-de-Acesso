# =============================================================
# monitor_impressao.ps1 - Agente de captura de impressoes
# Execute como Administrador. Nao feche a janela.
# =============================================================

# --- CONFIGURACAO ---
$SERVIDOR_URL = "http://192.168.1.230:3001/api/capture.php"
$AGENT_TOKEN  = ""
# --------------------

$logName = "Microsoft-Windows-PrintService/Operational"
$logFile = "$PSScriptRoot\monitor_log.txt"

function Write-Log {
    param([string]$msg, [string]$cor = "White")
    $linha = "$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') | $msg"
    Write-Host $linha -ForegroundColor $cor
    Add-Content -Path $logFile -Value $linha -ErrorAction SilentlyContinue
}

function Get-AgentHeaders {
    if ([string]::IsNullOrWhiteSpace($AGENT_TOKEN)) {
        return @{}
    }

    return @{ "X-Agent-Token" = $AGENT_TOKEN }
}

Write-Log "========================================" "Cyan"
Write-Log "  AGENTE DE IMPRESSAO INICIADO" "Cyan"
Write-Log "  Servidor: $SERVIDOR_URL" "Cyan"
Write-Log "  Maquina : $env:COMPUTERNAME" "Cyan"
Write-Log "========================================" "Cyan"

$logStatus = Get-WinEvent -ListLog $logName -ErrorAction SilentlyContinue
if (-not $logStatus -or -not $logStatus.IsEnabled) {
    Write-Log "[ERRO] Log de impressao desativado. Execute como Admin:" "Red"
    Write-Log "  wevtutil sl '$logName' /e:true" "Yellow"
    Write-Log "  Depois reinicie este script." "Yellow"
    exit 1
}
Write-Log "[OK] Log de impressao esta ativo." "Green"

$headers = Get-AgentHeaders

Write-Log "Testando conexao com o servidor..." "Cyan"
try {
    $statusUrl = $SERVIDOR_URL -replace "/capture.php", "/status.php"
    $teste = Invoke-WebRequest -Uri $statusUrl -Method Get -Headers $headers -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    Write-Log "[OK] Servidor respondeu (HTTP $($teste.StatusCode))." "Green"
} catch {
    Write-Log "[AVISO] Nao foi possivel alcancar o servidor. Verifique rede, Docker ou token." "Yellow"
}

Write-Log "Monitorando... Nao feche esta janela." "Green"

$lastCheck = (Get-Date).AddSeconds(-10)

while ($true) {
    try {
        $eventos = Get-WinEvent -LogName $logName -FilterXPath "*[System[(EventID=307)]]" -MaxEvents 20 -ErrorAction SilentlyContinue |
            Where-Object { $_.TimeCreated -gt $lastCheck }

        if ($null -ne $eventos) {
            foreach ($evt in $eventos) {
                $xml = [xml]$evt.ToXml()
                $params = $xml.Event.UserData.DocumentPrinted

                $documento = [string]$params.Param2
                $usuario = [string]$params.Param3
                $maquinaCliente = [string]$params.Param4
                $nomeImpressora = [string]$params.Param5
                $porta = [string]$params.Param6
                $paginasStr = [string]$params.Param8

                if (-not $maquinaCliente) { $maquinaCliente = $env:COMPUTERNAME }

                # Se o nome for generico, tenta recuperar de forma ultra-robusta
                if ($documento -match "Documento" -or $documento -match "Impressão" -or [string]::IsNullOrWhiteSpace($documento) -or $documento -eq "Sem Titulo") {
                    try {
                        Write-Log "  -> Tentando recuperar nome real (Fila de Impressão)..." "Cyan"
                        # Tenta pegar da fila de impressão (mais preciso para alguns drivers)
                        $job = Get-PrintJob -PrinterName $nomeImpressora | Where-Object { $_.UserName -eq $usuario } | Select-Object -First 1
                        if ($job -and $job.DocumentName -and $job.DocumentName -notmatch "Documento") {
                            $documento = $job.DocumentName
                        } else {
                            # Se falhar na fila, tenta pelo titulo da janela
                            Write-Log "  -> Tentando via Janela Ativa..." "Cyan"
                            $activeWindow = Get-Process | Where-Object {$_.MainWindowTitle -and $_.MainWindowTitle -notmatch "PowerShell"} | Select-Object -First 1
                            if ($activeWindow.MainWindowTitle) {
                                $documento = "($($activeWindow.ProcessName)) " + $activeWindow.MainWindowTitle
                            }
                        }
                    } catch {}
                }

                $paginas = 0
                if (-not [int]::TryParse($paginasStr, [ref]$paginas) -or $paginas -lt 1) {
                    $paginas = 1
                }

                $ipImpressora = ""
                if ($porta -match "^IP_(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})") {
                    $ipImpressora = $Matches[1]
                }

                Write-Log "Capturado: [$usuario] imprimiu '$documento' ($paginas pags) em '$nomeImpressora'" "Yellow"

                $payload = @{
                    maquina = $maquinaCliente
                    usuario = $usuario
                    documento = $documento
                    paginas = $paginas
                    ip_impressora = $ipImpressora
                    nome_impressora = $nomeImpressora
                    tipo = "Preto e Branco"
                }

                $json = $payload | ConvertTo-Json -Compress

                try {
                    $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
                    $resp = Invoke-RestMethod -Uri $SERVIDOR_URL -Method Post -Headers $headers -Body $utf8Bytes -ContentType "application/json; charset=utf-8" -TimeoutSec 10 -ErrorAction Stop
                    if ($resp.success) {
                        Write-Log "  -> ENVIADO com sucesso" "Green"
                    } else {
                        Write-Log "  -> ERRO do servidor" "Red"
                    }
                } catch {
                    $msg = $_.Exception.Message
                    if ($_.ErrorDetails) { $msg += " - " + $_.ErrorDetails.Message }
                    Write-Log "  -> FALHA AO ENVIAR: $msg" "Red"
                }
            }
        }
    } catch {
        # Mantem o loop vivo mesmo com falhas pontuais no parse.
    }

    $lastCheck = Get-Date
    Start-Sleep -Seconds 5
}
