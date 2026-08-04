# =============================================================
# agente_diagnostico.ps1 - Diagnostico do agente de impressao
# Execute como Administrador em qualquer maquina cliente.
# Este script nao faz loop. Apenas diagnostica e sai.
# =============================================================

$SERVIDOR_URL = "http://192.168.1.230:3001/api/capture.php"
$STATUS_URL   = "http://192.168.1.230:3001/api/status.php"
$AGENT_TOKEN  = ""
$logName      = "Microsoft-Windows-PrintService/Operational"

function Titulo { param($t) Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function OK     { param($m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function ERRO   { param($m) Write-Host "  [ERRO]  $m" -ForegroundColor Red }
function AVISO  { param($m) Write-Host "  [AVISO] $m" -ForegroundColor Yellow }
function INFO   { param($m) Write-Host "  [INFO]  $m" -ForegroundColor White }

function Get-AgentHeaders {
    if ([string]::IsNullOrWhiteSpace($AGENT_TOKEN)) {
        return @{}
    }

    return @{ "X-Agent-Token" = $AGENT_TOKEN }
}

$headers = Get-AgentHeaders

Write-Host "############################################" -ForegroundColor Magenta
Write-Host "  DIAGNOSTICO DO AGENTE DE IMPRESSAO" -ForegroundColor Magenta
$dataStr = Get-Date -Format 'dd/MM/yyyy HH:mm:ss'
Write-Host "  Maquina: $env:COMPUTERNAME | $dataStr" -ForegroundColor Magenta
Write-Host "############################################" -ForegroundColor Magenta

Titulo "1. Log de impressao do Windows"
try {
    $logStatus = Get-WinEvent -ListLog $logName -ErrorAction Stop
    if ($logStatus.IsEnabled) {
        OK "Log '$logName' esta ativo."
        INFO "Registros no log: $($logStatus.RecordCount)"
    } else {
        ERRO "Log de impressao esta desativado."
        AVISO "Para habilitar, execute como Administrador:"
        Write-Host "    wevtutil sl `"$logName`" /e:true" -ForegroundColor Yellow
    }
} catch {
    ERRO "Nao foi possivel verificar o log: $($_.Exception.Message)"
}

Titulo "2. Conectividade com o servidor ($STATUS_URL)"
try {
    $resp = Invoke-WebRequest -Uri $STATUS_URL -Method Get -Headers $headers -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    $json = $resp.Content | ConvertFrom-Json
    OK "Servidor respondeu. Status: $($json.status)"
    INFO "Hora do servidor : $($json.hora)"
    INFO "Impressoras no BD: $($json.impressoras)"
} catch {
    ERRO "Nao foi possivel alcancar o servidor."
    AVISO "Verifique IP, Docker, firewall ou token do agente."
    INFO "Erro: $($_.Exception.Message)"
}

Titulo "3. Impressoras instaladas nesta maquina"
$impressoras = Get-Printer
if ($impressoras.Count -eq 0) {
    AVISO "Nenhuma impressora encontrada."
} else {
    foreach ($imp in $impressoras) {
        $tipo = if ($imp.PortName -match "^IP_") { "REDE" } elseif ($imp.PortName -match "^USB") { "USB" } else { "LOCAL/$($imp.PortName)" }
        INFO "  $($imp.Name) | Porta: $($imp.PortName) | Tipo: $tipo"
    }
}

Titulo "4. Ultimos 5 trabalhos de impressao (Event ID 307)"
try {
    $eventos = Get-WinEvent -LogName $logName `
                            -FilterXPath "*[System[(EventID=307)]]" `
                            -MaxEvents 5 `
                            -ErrorAction Stop

    if ($eventos.Count -eq 0) {
        AVISO "Nenhum evento de impressao encontrado. Faca uma impressao de teste."
    } else {
        OK "Encontrados $($eventos.Count) evento(s)."
        foreach ($evt in $eventos) {
            $xml = [xml]$evt.ToXml()
            $params = $xml.Event.UserData.DocumentPrinted
            Write-Host ""
            Write-Host "  ---- [$($evt.TimeCreated)] ----" -ForegroundColor DarkCyan
            Write-Host "  Param1 (Job ID)     : $($params.Param1)"
            Write-Host "  Param2 (Documento)  : $($params.Param2)" -ForegroundColor White
            Write-Host "  Param3 (Usuario)    : $($params.Param3)" -ForegroundColor Green
            Write-Host "  Param4 (Maquina)    : $($params.Param4)"
            Write-Host "  Param5 (Impressora) : $($params.Param5)" -ForegroundColor Yellow
            Write-Host "  Param6 (Porta)      : $($params.Param6)" -ForegroundColor Yellow
            Write-Host "  Param7              : $($params.Param7)" -ForegroundColor Cyan
            Write-Host "  Param8              : $($params.Param8)"

            if ($params.Param6 -match "^IP_(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})") {
                Write-Host "  IP extraido da porta: $($Matches[1])" -ForegroundColor Green
            } elseif ($params.Param6 -match "^USB") {
                Write-Host "  Tipo de porta       : USB/Local" -ForegroundColor Magenta
            }
        }
    }
} catch {
    ERRO "Erro ao ler eventos: $($_.Exception.Message)"
    AVISO "Verifique se o log esta habilitado."
}

Titulo "5. Teste de envio para o servidor"
$payload = @{
    maquina = $env:COMPUTERNAME
    usuario = $env:USERNAME
    documento = "TESTE_DIAGNOSTICO.pdf"
    paginas = 1
    ip_impressora = ""
    nome_impressora = "Impressora Teste"
    tipo = "Preto e Branco"
} | ConvertTo-Json -Compress

try {
    $resp = Invoke-RestMethod -Uri $SERVIDOR_URL -Method Post -Headers $headers -Body $payload -ContentType "application/json" -TimeoutSec 10 -ErrorAction Stop
    if ($resp.success) {
        OK "Registro de teste enviado com sucesso. ID no banco: $($resp.id)"
        AVISO "Lembre de apagar esse registro de teste no sistema."
    } else {
        ERRO "Servidor recusou o envio: $($resp.error)"
    }
} catch {
    ERRO "Falha de conexao ao enviar: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "############################################" -ForegroundColor Magenta
Write-Host "  DIAGNOSTICO CONCLUIDO" -ForegroundColor Magenta
Write-Host "############################################" -ForegroundColor Magenta
Write-Host ""
Read-Host "Pressione Enter para fechar"
