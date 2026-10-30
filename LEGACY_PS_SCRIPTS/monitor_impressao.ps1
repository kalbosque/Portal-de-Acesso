# =============================================================
# monitor_impressao.ps1 - Agente de captura de impressoes (v3.0)
# NOVIDADE v3.0: Detecta tipo de documento (PDF, Word, Excel,
#                TXT, Imagem, Web, Remota) diretamente na maquina.
# Execute como Administrador. Nao feche a janela.
# =============================================================

# --- CONFIGURACAO ---
$SERVIDOR_URL = "http://192.168.1.230:3001/api/capture.php"
$AGENT_TOKEN  = ""
$MAX_RETRIES  = 5          # Máximo de tentativas de envio
$RETRY_DELAY_SEC = 2       # Delay inicial entre tentativas (segundos)
$HEALTH_CHECK_INTERVAL = 60 # Interval para health check (segundos)
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

# ---------------------------------------------------------------
# DETECCAO DE TIPO DE DOCUMENTO (roda na maquina cliente)
# Analisa o nome do trabalho de impressao e retorna o tipo.
# ---------------------------------------------------------------
function Get-TipoDocumento {
    param([string]$nomeDoc)

    $docLower = $nomeDoc.ToLower()

    # 1. Impressao remota via AnyDesk
    if ($docLower -match 'anydesk') {
        return 'Remota'
    }

    # 2. Limpa prefixos de aplicativos para expor a extensao real
    $nomeLimpo = $nomeDoc `
        -replace '^Microsoft Word\s*[-–]\s*', '' `
        -replace '^Microsoft Excel\s*[-–]\s*', '' `
        -replace '^Microsoft PowerPoint\s*[-–]\s*', '' `
        -replace '^Adobe Acrobat\s*(Reader)?\s*[A-Z0-9\s]*\s*[-–]\s*', '' `
        -replace '^Google Chrome\s*[-–]\s*', '' `
        -replace '^Mozilla Firefox\s*[-–]\s*', '' `
        -replace '\s*[-–]\s*Microsoft Word$', '' `
        -replace '\s*[-–]\s*Microsoft Excel$', '' `
        -replace '\s*[-–]\s*Microsoft PowerPoint$', '' `
        -replace '\s*[-–]\s*Bloco de Notas$', '' `
        -replace '^Bloco de Notas\s*[-–]\s*', '' `
        -replace '\s*[-–]\s*Notepad$', '' `
        -replace '^Notepad\s*[-–]\s*', '' `
        -replace '\s*[-–]\s*WordPad$', ''

    # 3. Extrai extensao do nome limpo
    $ext = [System.IO.Path]::GetExtension($nomeLimpo).ToLower().TrimStart('.')

    $extMap = @{
        # PDF
        'pdf'  = 'PDF'
        # Word
        'doc'  = 'Word'; 'docx' = 'Word'; 'rtf' = 'Word'; 'odt' = 'Word'; 'wps' = 'Word'
        # Excel
        'xls'  = 'Excel'; 'xlsx' = 'Excel'; 'csv' = 'Excel'; 'ods' = 'Excel'
        # PowerPoint
        'ppt'  = 'PPT'; 'pptx' = 'PPT'; 'pps' = 'PPT'; 'ppsx' = 'PPT'; 'odp' = 'PPT'
        # Texto
        'txt'  = 'Texto'; 'log' = 'Texto'; 'ini' = 'Texto'; 'md' = 'Texto'; 'cfg' = 'Texto'; 'bat' = 'Texto'
        # Imagem
        'jpg'  = 'Imagem'; 'jpeg' = 'Imagem'; 'png' = 'Imagem'; 'gif' = 'Imagem'
        'bmp'  = 'Imagem'; 'tiff' = 'Imagem'; 'tif' = 'Imagem'; 'svg' = 'Imagem'; 'webp' = 'Imagem'
        # Web
        'html' = 'Web'; 'htm' = 'Web'; 'php' = 'Web'; 'asp' = 'Web'; 'aspx' = 'Web'
    }

    if ($ext -and $extMap.ContainsKey($ext)) {
        return $extMap[$ext]
    }

    # 4. Fallback por palavras-chave no nome original (sem extensao conhecida)
    $docLowerLimpo = $nomeLimpo.ToLower()
    if     ($docLowerLimpo -match '\.pdf|pdf')                              { return 'PDF' }
    elseif ($docLowerLimpo -match '\.docx?|word')                           { return 'Word' }
    elseif ($docLowerLimpo -match '\.xlsx?|excel|planilha|tabela')          { return 'Excel' }
    elseif ($docLowerLimpo -match '\.pptx?|powerpoint|apresenta')           { return 'PPT' }
    elseif ($docLowerLimpo -match '\.txt|bloco de notas|notepad')           { return 'Texto' }
    elseif ($docLowerLimpo -match '\.jpe?g|\.png|\.bmp|imagem|foto')        { return 'Imagem' }
    elseif ($docLowerLimpo -match 'chrome|edge|firefox|http|www\.')         { return 'Web' }
    elseif ($docLowerLimpo -match 'outlook|thunderbird|e-mail|email|gmail') { return 'E-mail' }

    # 5. Nao foi possivel identificar
    return 'Sistema'
}

# ---------------------------------------------------------------

Write-Log "========================================" "Cyan"
Write-Log "  AGENTE DE IMPRESSAO v3.0 INICIADO" "Cyan"
Write-Log "  Servidor: $SERVIDOR_URL" "Cyan"
Write-Log "  Maquina : $env:COMPUTERNAME" "Cyan"
Write-Log "  Deteccao de tipo de documento: ATIVA" "Cyan"
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

function Send-Heartbeat {
    try {
        $heartbeatUrl = $SERVIDOR_URL -replace "/capture.php", "/heartbeat.php"
        $usuarioAtual = $env:USERNAME
        if (-not $usuarioAtual) { $usuarioAtual = "Nenhum" }

        $payload = @{
            maquina = $env:COMPUTERNAME
            usuario = $usuarioAtual
        }
        $json = $payload | ConvertTo-Json -Compress
        $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        
        $headers = Get-AgentHeaders
        Invoke-RestMethod -Uri $heartbeatUrl -Method Post -Headers $headers -Body $utf8Bytes -ContentType "application/json; charset=utf-8" -TimeoutSec 5 -ErrorAction SilentlyContinue
        Write-Log "  -> Sinal de vida enviado (Usuario: $usuarioAtual)" "DarkCyan"
    } catch {
        # Falha silenciosa para não atrapalhar a monitoria de impressão
    }
}

$lastCheck = (Get-Date).AddSeconds(-10)
$lastHeartbeat = (Get-Date).AddSeconds(-($HEALTH_CHECK_INTERVAL + 1))

while ($true) {
    # Envia Heartbeat a cada minuto
    if ((Get-Date) -gt $lastHeartbeat.AddSeconds($HEALTH_CHECK_INTERVAL)) {
        Send-Heartbeat
        $lastHeartbeat = Get-Date
    }

    try {
        $eventos = Get-WinEvent -LogName $logName -FilterXPath "*[System[(EventID=307)]]" -MaxEvents 20 -ErrorAction SilentlyContinue |
            Where-Object { $_.TimeCreated -gt $lastCheck }

        if ($null -ne $eventos) {
            foreach ($evt in $eventos) {
                $xml = [xml]$evt.ToXml()
                $params = $xml.Event.UserData.DocumentPrinted

                $documento      = [string]$params.Param2
                $usuario        = [string]$params.Param3
                $maquinaCliente = [string]$params.Param4
                $nomeImpressora = [string]$params.Param5
                $param6         = [string]$params.Param6   # porta OU caminho do arquivo
                $paginasStr    = [string]$params.Param8

                if (-not $maquinaCliente) { $maquinaCliente = $env:COMPUTERNAME }

                $paginas = 0
                if (-not [int]::TryParse($paginasStr, [ref]$paginas) -or $paginas -lt 1) {
                    $paginas = 1
                }

                # --- EXTRAI IP DA IMPRESSORA (porta IP_x.x.x.x) ---
                $ipImpressora = ""
                if ($param6 -match "^IP_(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})") {
                    $ipImpressora = $Matches[1]
                }

                # --- RECUPERA O NOME REAL DO ARQUIVO via Param6 ---
                # Quando Param2 é genérico ("Documento de Impressão"), o Param6 pode
                # conter o caminho completo do arquivo (ex: C:\Users\...\relatorio.pdf)
                $nomesGenericos = @(
                    "Documento de Impressão", "Documento de impressão",
                    "Print Document", "Document", ""
                )
                if ($nomesGenericos -contains $documento.Trim()) {
                    $nomeRecuperado = $false
                    # Tenta extrair do caminho (Param6)
                    if ($param6 -notmatch "^IP_" -and $param6 -match "\\") {
                        $nomeArquivoReal = [System.IO.Path]::GetFileName($param6)
                        if ($nomeArquivoReal -ne "") {
                            $documento = $nomeArquivoReal
                            $nomeRecuperado = $true
                            Write-Log "  -> Nome recuperado do caminho: $documento" "DarkGreen"
                        }
                    }
                    
                    # Se ainda não conseguiu, tenta pegar o título da Janela Ativa
                    if (-not $nomeRecuperado) {
                        try {
                            Add-Type -TypeDefinition @"
                            using System;
                            using System.Runtime.InteropServices;
                            using System.Text;
                            public class Win32API {
                                [DllImport("user32.dll")]
                                public static extern IntPtr GetForegroundWindow();
                                [DllImport("user32.dll", CharSet = CharSet.Auto)]
                                public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
                            }
"@ -ErrorAction SilentlyContinue
                            
                            $hwnd = [Win32API]::GetForegroundWindow()
                            $sb = New-Object System.Text.StringBuilder 256
                            if ([Win32API]::GetWindowText($hwnd, $sb, 256) -gt 0) {
                                $activeTitle = $sb.ToString()
                                if ([string]::IsNullOrWhiteSpace($activeTitle)) {
                                    $documento = "Documento de Impressão [Titulo Vazio]"
                                } else {
                                    $documento = $activeTitle
                                    Write-Log "  -> Nome recuperado da janela ativa: $documento" "DarkGreen"
                                }
                            } else {
                                $documento = "Documento de Impressão [Sem Janela Ativa]"
                            }
                        } catch {
                            $documento = "Documento de Impressão [Erro API Janela]"
                        }
                    }
                }

                # --- DETECCAO DO TIPO DE DOCUMENTO NA MAQUINA CLIENTE ---
                $tipoDocDetectado = Get-TipoDocumento -nomeDoc $documento

                # Limpa o nome para AnyDesk
                $documentoEnvio = $documento
                if ($tipoDocDetectado -eq 'Remota') {
                    $documentoEnvio = "Impressao Remota (AnyDesk)"
                }

                Write-Log "Capturado: [$usuario] '$documento' -> Tipo: $tipoDocDetectado ($paginas pags) em '$nomeImpressora'" "Yellow"

                $payload = @{
                    maquina         = $maquinaCliente
                    usuario         = $usuario
                    documento       = $documentoEnvio
                    tipo_documento  = $tipoDocDetectado
                    paginas         = $paginas
                    ip_impressora   = $ipImpressora
                    nome_impressora = $nomeImpressora
                    tipo            = "Preto e Branco"
                }

                $json = $payload | ConvertTo-Json -Compress

                try {
                    $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
                    $resp = Invoke-RestMethod -Uri $SERVIDOR_URL -Method Post -Headers $headers -Body $utf8Bytes -ContentType "application/json; charset=utf-8" -TimeoutSec 10 -ErrorAction Stop
                    if ($resp.success) {
                        Write-Log "  -> ENVIADO: tipo='$tipoDocDetectado' doc='$documentoEnvio'" "Green"
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
