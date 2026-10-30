# =============================================================
# scanner_rede.ps1 - Escaneia a rede e descobre maquinas (v2.0)
# Execute como Administrador no servidor
# =============================================================

# --- CONFIGURACAO ---
$prefixoRede = "192.168.1"
$inicioIP    = 1
$fimIP       = 254
$timeoutMs   = 500
$outputFile  = "$PSScriptRoot\lista_maquinas.txt"
$statusFile  = "$PSScriptRoot\status_maquinas.json"
$intervaloCheck = 300  # 5 minutos em segundos
$modoMonitoramento = $true  # Se $true, executa como daemon com health check contínuo
# --------------------

# Dispositivos que claramente NAO sao PCs Windows (serao marcados para excluir)
$naoWindows = @("OPNSENSE","SWITCH","ROUTER","FIREWALL","PRINTER","AP-","CAMERA","CAM-","NAS-","DLINK","TPLINK","MIKROTIK")

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SCANNER DE REDE - $prefixoRede.x" -ForegroundColor Cyan
Write-Host "  Escaneando IPs de .$inicioIP ate .$fimIP" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Pingando em paralelo... aguarde ate 60 segundos." -ForegroundColor Yellow
Write-Host ""

# Escanear com runspaces paralelos
$runspacePool = [RunspaceFactory]::CreateRunspacePool(1, 80)
$runspacePool.Open()

$scriptBlock = {
    param($ip, $timeout)
    $ping = New-Object System.Net.NetworkInformation.Ping
    try {
        $result = $ping.Send($ip, $timeout)
        if ($result.Status -eq 'Success') {
            $nome = "SEM-NOME"
            try {
                $dns  = [System.Net.Dns]::GetHostEntry($ip)
                $nome = $dns.HostName.Split('.')[0].ToUpper()
            } catch {}
            return [PSCustomObject]@{ IP = $ip; Nome = $nome }
        }
    } catch {}
    return $null
}

$handles = @()
$inicioIP..$fimIP | ForEach-Object {
    $ip = "$prefixoRede.$_"
    $ps = [PowerShell]::Create()
    $ps.RunspacePool = $runspacePool
    $ps.AddScript($scriptBlock).AddArgument($ip).AddArgument($timeoutMs) | Out-Null
    $handles += [PSCustomObject]@{ PS = $ps; Handle = $ps.BeginInvoke() }
}

$resultados = @()
foreach ($h in $handles) {
    try {
        $r = $h.PS.EndInvoke($h.Handle)
        if ($r) { $resultados += $r }
    } catch {}
    $h.PS.Dispose()
}
$runspacePool.Close()

# Ordenar por IP
$resultados = $resultados | Sort-Object { [int]($_.IP.Split('.')[-1]) }

Write-Host "============================================" -ForegroundColor Green
Write-Host "  DISPOSITIVOS ENCONTRADOS: $($resultados.Count)" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

$provavelWindows = @()
$provavelOutro   = @()

foreach ($r in $resultados) {
    $eOutro = $false
    foreach ($nw in $naoWindows) {
        if ($r.Nome -like "*$nw*") { $eOutro = $true; break }
    }
    if ($r.Nome -eq "SEM-NOME") { $eOutro = $true }

    if ($eOutro) {
        $provavelOutro   += $r
    } else {
        $provavelWindows += $r
    }
}

Write-Host "  [PCS WINDOWS - serao monitorados]" -ForegroundColor Green
foreach ($r in $provavelWindows) {
    Write-Host ("    {0,-16}  {1}" -f $r.IP, $r.Nome) -ForegroundColor Green
}

Write-Host ""
Write-Host "  [OUTROS - NAO serao incluidos na lista]" -ForegroundColor DarkGray
foreach ($r in $provavelOutro) {
    Write-Host ("    {0,-16}  {1}" -f $r.IP, $r.Nome) -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  PCs Windows identificados : $($provavelWindows.Count)" -ForegroundColor Green
Write-Host "  Outros dispositivos       : $($provavelOutro.Count)" -ForegroundColor DarkGray
Write-Host ""

if ($provavelWindows.Count -gt 0) {
    $resposta = Read-Host "Salvar lista de PCs em lista_maquinas.txt? (S/N)"
    if ($resposta -match '^[Ss]') {
        $linhas = @()
        $linhas += "# Lista gerada em $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"
        $linhas += "# $($provavelWindows.Count) PCs encontrados"
        $linhas += "# REMOVA as linhas das maquinas que NAO quer monitorar"
        $linhas += ""
        foreach ($m in $provavelWindows) {
            if ($m.Nome -ne "SEM-NOME") {
                $linhas += "$($m.Nome)   # IP: $($m.IP)"
            } else {
                $linhas += "$($m.IP)"
            }
        }
        $linhas | Set-Content -Path $outputFile -Encoding UTF8
        Write-Host ""
        Write-Host "  [OK] Lista salva: $outputFile" -ForegroundColor Green
        Write-Host "  Revise o arquivo e depois execute: deploy_todos.ps1" -ForegroundColor Yellow
    }
} else {
    Write-Host "Nenhum PC encontrado. Verifique o prefixo: $prefixoRede" -ForegroundColor Red
}

Write-Host ""

# --- FUNCAO PARA OBTER USUARIOS ATIVOS ---
function Get-UsuariosAtivos {
    param([string]$Computador)
    
    $usuarios = @()
    try {
        $quserOutput = quser /server:$Computador 2>&1
        
        if ($LASTEXITCODE -eq 0 -and $quserOutput) {
            foreach ($linha in $quserOutput) {
                if ($linha -match '^\s*(.+?)\s+(\S+)\s+(\d+)\s+(\S+)\s+(.*)') {
                    $usuario = $Matches[1].Trim()
                    $sessao = $Matches[2].Trim()
                    $idSessao = $Matches[3]
                    $estado = $Matches[4]
                    $resto = $Matches[5]
                    
                    if ($usuario -eq "USERNAME") { continue }
                    
                    $tempoOcioso = "0"
                    if ($resto -match "(\d+)\+(\d{2}):(\d{2})") {
                        $tempoOcioso = "$($Matches[1])d $($Matches[2])h"
                    } elseif ($resto -match "(\d{2}):(\d{2})") {
                        $tempoOcioso = "$($Matches[1])h $($Matches[2])m"
                    }
                    
                    $usuarios += @{
                        Usuario = $usuario
                        Sessao = $sessao
                        Estado = $estado
                        Status = if ($estado -eq "Disc") { "Inativo" } else { "Ativo" }
                    }
                }
            }
        }
    } catch {}
    
    return $usuarios
}

# --- MODO MONITORAMENTO CONTINUO ---
if ($modoMonitoramento) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  MODO MONITORAMENTO CONTINUO ATIVADO" -ForegroundColor Cyan
    Write-Host "  Intervalo: $intervaloCheck segundos" -ForegroundColor Cyan
    Write-Host "  (Incluindo monitoramento de usuários)" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Deixe esta janela aberta. Pressione CTRL+C para parar." -ForegroundColor Yellow
    Write-Host ""

    $maquinasAnterior = @{}
    
    while ($true) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Executando health check..." -ForegroundColor Cyan
        
        $maquinasAtuais = @{}
        
        # Re-escanear de forma otimizada (apenas as conhecidas)
        $runspacePool = [RunspaceFactory]::CreateRunspacePool(1, 80)
        $runspacePool.Open()

        $scriptBlock = {
            param($ip, $timeout)
            $ping = New-Object System.Net.NetworkInformation.Ping
            try {
                $result = $ping.Send($ip, $timeout)
                if ($result.Status -eq 'Success') {
                    $nome = "SEM-NOME"
                    try {
                        $dns = [System.Net.Dns]::GetHostEntry($ip)
                        $nome = $dns.HostName.Split('.')[0].ToUpper()
                    } catch {}
                    return [PSCustomObject]@{ IP = $ip; Nome = $nome; Status = "Online"; Timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss' }
                }
            } catch {}
            return [PSCustomObject]@{ IP = $ip; Nome = "OFFLINE"; Status = "Offline"; Timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss' }
        }

        $handles = @()
        $inicioIP..$fimIP | ForEach-Object {
            $ip = "$prefixoRede.$_"
            $ps = [PowerShell]::Create()
            $ps.RunspacePool = $runspacePool
            $ps.AddScript($scriptBlock).AddArgument($ip).AddArgument($timeoutMs) | Out-Null
            $handles += [PSCustomObject]@{ PS = $ps; Handle = $ps.BeginInvoke() }
        }

        $resultados = @()
        foreach ($h in $handles) {
            try {
                $r = $h.PS.EndInvoke($h.Handle)
                if ($r) { $resultados += $r }
            } catch {}
            $h.PS.Dispose()
        }
        $runspacePool.Close()

        # Processar resultados
        foreach ($r in $resultados) {
            $key = $r.IP
            
            # Obter usuários ativos se máquina estiver online
            $usuarios = @()
            if ($r.Status -eq "Online") {
                $usuarios = Get-UsuariosAtivos -Computador $r.IP
            }
            
            $maquinasAtuais[$key] = @{
                Nome = $r.Nome
                Status = $r.Status
                Timestamp = $r.Timestamp
                Usuarios = $usuarios
                TotalUsuarios = $usuarios.Count
            }
            }
        }

        # Detectar mudanças de status
        foreach ($key in $maquinasAtuais.Keys) {
            if (-not $maquinasAnterior.ContainsKey($key)) {
                Write-Host "  [NOVO] $key - $($maquinasAtuais[$key].Nome) - Online" -ForegroundColor Green
            } elseif ($maquinasAnterior[$key].Status -ne $maquinasAtuais[$key].Status) {
                if ($maquinasAtuais[$key].Status -eq "Online") {
                    Write-Host "  [ONLINE] $key - $($maquinasAtuais[$key].Nome)" -ForegroundColor Green
                } else {
                    Write-Host "  [OFFLINE] $key - $($maquinasAnterior[$key].Nome)" -ForegroundColor Red
                }
            }
        }

        foreach ($key in $maquinasAnterior.Keys) {
            if (-not $maquinasAtuais.ContainsKey($key)) {
                Write-Host "  [REMOTO] $key - Desapareceu" -ForegroundColor DarkRed
            }
        }

        # Salvar status em JSON (formato limpo para PHP)
        try {
            $statusData = @{
                UltimaAtualizacao = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
                Maquinas = $maquinasAtuais
                Total = $maquinasAtuais.Count
            }
            # Usar -Depth para garantir serialização completa do JSON
            # Salvar como UTF8 para compatibilidade com PHP
            $json | Set-Content -Path $statusFile -Encoding UTF8
        } catch {
            Write-Host "  [ERRO] Falha ao salvar status em JSON: $_" -ForegroundColor DarkRed
        }

        $maquinasAnterior = $maquinasAtuais

        Write-Host "  Próximo check em $intervaloCheck segundos..." -ForegroundColor DarkGray
        Start-Sleep -Seconds $intervaloCheck
    }
} else {
    Read-Host "Pressione Enter para fechar"
}
