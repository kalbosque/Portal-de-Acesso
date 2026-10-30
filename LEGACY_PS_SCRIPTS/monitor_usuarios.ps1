#=============================================================
# monitor_usuarios.ps1 - Monitora usuarios ativos/inativos (v3.0)
#=============================================================

param(
    [string]$Acao = "monitorar",
    [int]$Intervalo = 5,
    [int]$MaxThreads = 10
)

$listaMaquinas = "$PSScriptRoot\lista_maquinas.txt"
$arquivoStatus = "$PSScriptRoot\status_usuarios.json"
$arquivoStatusAnterior = "$PSScriptRoot\status_usuarios_anterior.json"
$arquivoHistorico = "$PSScriptRoot\status_usuarios_historico.json"
$logFile = "$PSScriptRoot\monitor_usuarios_log.txt"

function Write-Log {
    param([string]$msg, [string]$cor = "White")
    $linha = "$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') | $msg"
    Write-Host $linha -ForegroundColor $cor
    Add-Content -Path $logFile -Value $linha -ErrorAction SilentlyContinue
}

# Bloco de código para execução paralela
$MonitorWorker = {
    param($Computador, $NomeMaq, $IP, $StatusAnterior)
    
    $resultado = @{
        Nome = $NomeMaq
        IP = $IP
        Status = "Offline"
        TotalUsuarios = 0
        Usuarios = @()
        DataVerificacao = (Get-Date -Format "dd/MM/yyyy")
        HoraVerificacaoDetalhe = (Get-Date -Format "HH:mm:ss")
        HoraVerificacao = (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
    }

    # Teste de conexão rápido e captura de latência
    $online = $false
    try {
        $ping = Test-Connection -ComputerName $Computador -Count 1 -ErrorAction SilentlyContinue
        if ($ping) {
            $online = $true
            $resultado.Latencia = $ping.ResponseTime
            
            # Auto-descoberta de IP se estiver vazio ou se resolveu um hostname
            if ($ping.IPV4Address -or $ping.Address) {
                $resolvedIp = if ($ping.IPV4Address) { $ping.IPV4Address.IPAddressToString } else { $ping.Address }
                if ($resolvedIp -and $resolvedIp -ne $Computador) {
                    $resultado.IP = $resolvedIp
                } elseif ($resolvedIp) {
                    $resultado.IP = $resolvedIp
                }
            }
        }
    } catch {}

    if ($online) {
        $resultado.Status = "Online"
        
        # Tenta obter descrição da máquina
        try {
            $os = Get-CimInstance -ComputerName $Computador -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue -OperationTimeoutSec 2
            if ($os.Description) { $resultado.Nome += " ($($os.Description))" }
        } catch {}

        # --- Coleta de Usuários ---
        $usuarios = @()
        
        # Método 1: Win32_ComputerSystem (Mais confiável para usuário local/console)
        try {
            $cs = Get-CimInstance -ComputerName $Computador -ClassName Win32_ComputerSystem -ErrorAction SilentlyContinue -OperationTimeoutSec 4
            if ($cs.UserName) {
                $userLimpo = $cs.UserName -split '\\' | Select-Object -Last 1
                
                # Tenta buscar o nome completo para esse usuário
                $nomeReal = ""
                try {
                    $userInfo = Get-CimInstance -ComputerName $Computador -ClassName Win32_UserAccount -Filter "Name='$userLimpo'" -ErrorAction SilentlyContinue -OperationTimeoutSec 2
                    $nomeReal = $userInfo.FullName
                } catch {}

                $usuarios += @{
                    Usuario = $userLimpo
                    NomeReal = $nomeReal
                    Sessao = "Console"
                    Status = "Ativo"
                    TempoOcioso = "0m"
                    DataHoraCaptura = (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
                }
            }
        } catch {}

        # Método 2: Fallback QUSER (Se o primeiro falhar ou para multiplas sessões)
        if ($usuarios.Count -eq 0) {
            try {
                $quserOutput = quser /server:$Computador 2>&1
                if ($quserOutput -match "USERNAME|USUÁRIO|USUARIO") {
                    foreach ($linha in $quserOutput) {
                        if ($linha -match '^\s*(>?)(?<user>\S+)\s+(?<sessao>\S+)?\s+(?<id>\d+)\s+(?<estado>\S+)\s+(?<ocioso>\S+)\s+(?<logon>.+)$') {
                            $user = $Matches['user'].Trim()
                            if ($user -match "USERNAME|USUÁRIO|USUARIO") { continue }
                            $usuarios += @{
                                Usuario = $user
                                NomeReal = ""
                                Sessao = "RDP/Other"
                                Status = "Ativo"
                                TempoOcioso = $Matches['ocioso'].Trim()
                                DataHoraCaptura = (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
                            }
                        }
                    }
                }
            } catch {}
        }

        $resultado.Usuarios = $usuarios
        $resultado.TotalUsuarios = $usuarios.Count
    }

    return $resultado
}

function Atualizar-Historico {
    param([object]$StatusAtual, [object]$StatusAnterior)
    
    $historicoAtual = @()
    if (Test-Path $arquivoHistorico) {
        try {
            $historicoAtual = Get-Content $arquivoHistorico -Raw | ConvertFrom-Json
        } catch { $historicoAtual = @() }
    }
    if ($null -eq $historicoAtual) { $historicoAtual = @() }

    $atuais = @{}
    foreach ($m in $StatusAtual.Maquinas) {
        foreach ($u in $m.Usuarios) { $atuais["$($m.Nome)|$($u.Usuario)"] = $u }
    }

    $anteriores = @{}
    if ($StatusAnterior) {
        foreach ($m in $StatusAnterior.Maquinas) {
            foreach ($u in $m.Usuarios) { $anteriores["$($m.Nome)|$($u.Usuario)"] = $u }
        }
    }

    # Logins
    foreach ($k in $atuais.Keys) {
        if (-not $anteriores.ContainsKey($k)) {
            $p = $k -split '\|'
            $historicoAtual += @{ timestamp = (Get-Date -Format "o"); tipo = "login"; usuario = $p[1]; maquina = $p[0] }
            Write-Log "HISTORICO: $($p[1]) entrou em $($p[0])" "Green"
        }
    }

    # Logouts
    foreach ($k in $anteriores.Keys) {
        if (-not $atuais.ContainsKey($k)) {
            $p = $k -split '\|'
            $historicoAtual += @{ timestamp = (Get-Date -Format "o"); tipo = "logout"; usuario = $p[1]; maquina = $p[0] }
            Write-Log "HISTORICO: $($p[1]) saiu de $($p[0])" "Red"
        }
    }

    $json = $historicoAtual | Select-Object -Last 50 | ConvertTo-Json -Depth 5
    Set-Content -Path $arquivoHistorico -Value $json -ErrorAction SilentlyContinue
}

function Get-MaquinasLista {
    if (-not (Test-Path $listaMaquinas)) { return @() }
    $linhas = Get-Content $listaMaquinas | Where-Object { $_ -notmatch '^\s*#' -and $_.Trim() -ne '' }
    $lista = @()
    foreach ($l in $linhas) {
        $partes = $l -split '#'
        $idOriginal = $partes[0].Trim()
        $comentario = if ($partes.Count -gt 1) { $partes[1].Trim() } else { "" }
        
        $ip = if ($idOriginal -match '^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$') { $idOriginal } 
              elseif ($l -match 'IP:\s*(?<ip>[0-9\.]+)') { $Matches['ip'] } 
              else { $null }

        # Se o ID for um IP, tenta usar o comentário como nome amigável
        $nome = $idOriginal
        if ($idOriginal -match '^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$' -and $comentario -ne "") {
            $nome = $comentario -split 'IP:' | Select-Object -First 1
            $nome = $nome.Trim()
        }

        $alvo = if ($ip) { $ip } else { $idOriginal }
        $lista += [PSCustomObject]@{ Nome = $nome; Alvo = $alvo; IP = $ip }
    }
    return $lista
}

function Executar-ScanParalelo {
    $maquinas = Get-MaquinasLista
    if ($maquinas.Count -eq 0) { return $null }

    Write-Log "Iniciando scan de $($maquinas.Count) maquinas (Max Threads: $MaxThreads)..." "Yellow"
    
    $rsPool = [runspacefactory]::CreateRunspacePool(1, $MaxThreads)
    $rsPool.Open()
    $jobs = @()

    foreach ($m in $maquinas) {
        $powershell = [powershell]::Create().AddScript($MonitorWorker).AddArgument($m.Alvo).AddArgument($m.Nome).AddArgument($m.IP)
        $powershell.RunspacePool = $rsPool
        $jobs += [PSCustomObject]@{
            Instance = $powershell
            Handle   = $powershell.BeginInvoke()
            Nome     = $m.Nome
        }
    }

    $timeoutSeconds = 60
    $startTime = Get-Date
    while ($jobs.Handle.IsCompleted -contains $false) { 
        if (((Get-Date) - $startTime).TotalSeconds -gt $timeoutSeconds) {
            Write-Log "⚠ Tempo limite de scan atingido ($timeoutSeconds s). Finalizando jobs pendentes..." "Red"
            break
        }
        Start-Sleep -Milliseconds 200 
    }

    $resultados = @()
    foreach ($j in $jobs) {
        if ($j.Handle.IsCompleted) {
            try {
                Write-Log "   - Coletando resultado de $($j.Nome)..." "Gray"
                $resultados += $j.Instance.EndInvoke($j.Handle)
            } catch {
                Write-Log "⚠ Erro ao obter resultado de $($j.Nome): $($_.Exception.Message)" "Red"
            }
        } else {
            Write-Log "⚠ Máquina $($j.Nome) ultrapassou o tempo e foi pulada." "Yellow"
            try { $j.Instance.Stop() } catch {}
        }
        $j.Instance.Dispose()
    }
    
    try {
        $rsPool.Close()
        $rsPool.Dispose()
    } catch {}

    return $resultados
}

function Monitor-UsuariosArquivo {
    Write-Log "Monitor de Usuarios v3.0 iniciado (Modo Paralelo)" "Cyan"
    
    while ($true) {
        $inicio = Get-Date
        
        # Carrega o status anterior para não perder informações de usuários
        $statusAnterior = if (Test-Path $arquivoStatus) { Get-Content $arquivoStatus -Raw | ConvertFrom-Json } else { $null }
        
        $resultados = Executar-ScanParalelo
        
        if ($resultados) {
            # Se a máquina está online mas o scan falhou em pegar o usuário, mantém o anterior (Persistência)
            if ($statusAnterior) {
                foreach ($res in $resultados) {
                    if ($res.Status -eq "Online" -and ($null -eq $res.Usuarios -or $res.Usuarios.Count -eq 0)) {
                        $oldMaq = $statusAnterior.Maquinas | Where-Object { $_.Nome -eq $res.Nome }
                        if ($oldMaq -and $oldMaq.TotalUsuarios -gt 0) {
                            $res.Usuarios = $oldMaq.Usuarios
                            $res.TotalUsuarios = $oldMaq.TotalUsuarios
                        }
                    }
                }
            }

            $totalAtivos = 0
            foreach ($m in $resultados) { $totalAtivos += $m.TotalUsuarios }

            $dados = @{
                DataCaptura = (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
                DataAtualizacao = (Get-Date -Format "dd/MM/yyyy")
                HoraAtualizacao = (Get-Date -Format "HH:mm:ss")
                TotalMaquinas = $resultados.Count
                MaquinasOnline = ($resultados | Where-Object { $_.Status -eq "Online" }).Count
                UsuariosAtivos = $totalAtivos
                Maquinas = $resultados
            }

            $json = $dados | ConvertTo-Json -Depth 10
            Set-Content -Path $arquivoStatus -Value $json -Encoding UTF8
            
            $ant = if (Test-Path $arquivoStatusAnterior) { Get-Content $arquivoStatusAnterior -Raw | ConvertFrom-Json } else { $null }
            Atualizar-Historico -StatusAtual $dados -StatusAnterior $ant
            Set-Content -Path $arquivoStatusAnterior -Value $json -Encoding UTF8 -ErrorAction SilentlyContinue
            
            $fim = Get-Date
            $duracao = ($fim - $inicio).TotalSeconds
            Write-Log "Scan concluido em $($duracao.ToString('F2'))s. Online: $($dados.MaquinasOnline)/$($dados.TotalMaquinas)" "Green"
        }

        Start-Sleep -Seconds $Intervalo
    }
}

function Show-Dashboard {
    Clear-Host
    if (-not (Test-Path $arquivoStatus)) { Write-Host "Aguardando primeira captura..." -ForegroundColor Yellow; return }
    $dados = Get-Content $arquivoStatus -Raw | ConvertFrom-Json
    
    Write-Host "`n MONITOR DE USUARIOS - DASHBOARD REALTIME" -ForegroundColor Cyan
    Write-Host " Atualizado em: $($dados.DataCaptura)" -ForegroundColor Yellow
    Write-Host " Maquinas: $($dados.TotalMaquinas) | Online: $($dados.MaquinasOnline) | Usuarios: $($dados.UsuariosAtivos)" -ForegroundColor White
    Write-Host ("-" * 60) -ForegroundColor DarkGray
    
    foreach ($m in $dados.Maquinas) {
        $cor = if ($m.Status -eq "Online") { "Green" } else { "Red" }
        Write-Host "[$($m.Status.PadRight(7))] $($m.Nome.PadRight(15)) ($($m.TotalUsuarios) users)" -ForegroundColor $cor
        foreach ($u in $m.Usuarios) {
            Write-Host "          > $($u.Usuario.PadRight(15)) [$($u.Status)]" -ForegroundColor Gray
        }
    }
    Write-Host ("-" * 60) -ForegroundColor DarkGray
    Write-Host " Pressione CTRL+C para sair. Atualizando..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 5
    Show-Dashboard
}

switch ($Acao.ToLower()) {
    "monitorar" { Monitor-UsuariosArquivo }
    "dashboard" { Show-Dashboard }
    "capturar"  { 
        $res = Executar-ScanParalelo
        $dados = @{
            DataCaptura = (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
            DataAtualizacao = (Get-Date -Format "dd/MM/yyyy")
            HoraAtualizacao = (Get-Date -Format "HH:mm:ss")
            TotalMaquinas = $res.Count
            MaquinasOnline = ($res | Where-Object { $_.Status -eq "Online" }).Count
            UsuariosAtivos = ($res.Usuarios | Measure-Object).Count
            Maquinas = $res
        }
        $dados | ConvertTo-Json -Depth 10 | Set-Content $arquivoStatus 
    }
    "json"      { if (Test-Path $arquivoStatus) { Get-Content $arquivoStatus } }
    default     { Write-Host "Uso: monitor_usuarios.ps1 -Acao [monitorar|dashboard|capturar|json]" -ForegroundColor Yellow }
}
