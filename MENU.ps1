#=============================================================
# MENU PRINCIPAL - Monitor de Usuarios da Rede
#=============================================================

param(
    [switch]$VerSomente
)

$PSDefaultParameterValues['Out-GridView:OutputMode'] = 'None'

# Cores
$corTitulo = "Cyan"
$corSucesso = "Green"
$corAviso = "Yellow"
$corErro = "Red"

function Show-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $corTitulo
    Write-Host "║                                                            ║" -ForegroundColor $corTitulo
    Write-Host "║          🖥️  MONITOR DE USUÁRIOS - MENU PRINCIPAL        ║" -ForegroundColor $corTitulo
    Write-Host "║                                                            ║" -ForegroundColor $corTitulo
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $corTitulo
    Write-Host ""
}

function Varrer-Maquinas {
    Write-Host "🔍 VARRENDO MÁQUINAS DA REDE..." -ForegroundColor $corAviso
    Write-Host ""
    
    $listaMaquinas = "$PSScriptRoot\lista_maquinas.txt"
    
    if (-not (Test-Path $listaMaquinas)) {
        Write-Host "❌ Erro: lista_maquinas.txt não encontrado!" -ForegroundColor $corErro
        return $null
    }
    
    $linhas = Get-Content $listaMaquinas | Where-Object { $_ -notmatch '^\s*#' -and $_.Trim() -ne '' }
    $maquinas = @()
    $online = 0
    $offline = 0
    $total = 0
    
    foreach ($linha in $linhas) {
        $maq = ($linha -split '#')[0].Trim()
        if (-not $maq) { continue }
        
        $total++
        Write-Host "  Testando $maq..." -ForegroundColor Gray -NoNewline
        
        $ping = Test-Connection -ComputerName $maq -Count 1 -Quiet -ErrorAction SilentlyContinue -TimeoutSeconds 2
        
        if ($ping) {
            Write-Host " ✓ Online" -ForegroundColor $corSucesso
            $online++
            $status = "Online"
        } else {
            Write-Host " ✗ Offline" -ForegroundColor $corErro
            $offline++
            $status = "Offline"
        }
        
        $maquinas += @{
            Nome = $maq
            Status = $status
        }
    }
    
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
    Write-Host "RESULTADO DA VARREDURA:" -ForegroundColor $corTitulo
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
    Write-Host "  Total de máquinas: $total" -ForegroundColor White
    Write-Host "  ✓ Online: $online" -ForegroundColor $corSucesso
    Write-Host "  ✗ Offline: $offline" -ForegroundColor $corErro
    Write-Host ""
    
    return @{
        Maquinas = $maquinas
        Total = $total
        Online = $online
        Offline = $offline
    }
}

function Show-Menu {
    Write-Host "ESCOLHA UMA OPÇÃO:" -ForegroundColor $corTitulo
    Write-Host ""
    Write-Host "  [1] Iniciar Monitor (coleta dados das máquinas)" -ForegroundColor White
    Write-Host "  [2] Ver Dashboard (dashboard em tempo real)" -ForegroundColor White
    Write-Host "  [3] Ver Status (dados atuais)" -ForegroundColor White
    Write-Host "  [4] Exportar Dados (formato JSON)" -ForegroundColor White
    Write-Host "  [5] Varrear Máquinas Novamente" -ForegroundColor White
    Write-Host "  [0] Sair" -ForegroundColor $corAviso
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
    Write-Host ""
    
    $opcao = Read-Host "Digite a opção (0-5)"
    return $opcao
}

function Iniciar-Monitor {
    Write-Host ""
    Write-Host "Iniciando monitor..." -ForegroundColor $corAviso
    Write-Host "Pressione CTRL+C para parar" -ForegroundColor $corAviso
    Write-Host ""
    
    & ".\monitor_usuarios.ps1" -Acao monitorar -Intervalo 5
}

function Ver-Dashboard {
    Write-Host ""
    Write-Host "Abrindo dashboard..." -ForegroundColor $corAviso
    Write-Host "Pressione CTRL+C para sair" -ForegroundColor $corAviso
    Write-Host ""
    
    & ".\monitor_usuarios.ps1" -Acao dashboard
}

function Ver-Status {
    Write-Host ""
    
    $arquivoStatus = "$PSScriptRoot\status_usuarios.json"
    
    if (-not (Test-Path $arquivoStatus)) {
        Write-Host "❌ Nenhum dado disponível ainda" -ForegroundColor $corErro
        Write-Host "Execute: Iniciar Monitor (opção 1)" -ForegroundColor $corAviso
        Read-Host ""
        return
    }
    
    try {
        $dados = Get-Content $arquivoStatus -Raw | ConvertFrom-Json
        
        Write-Host "📊 STATUS ATUAL" -ForegroundColor $corTitulo
        Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
        Write-Host "Última atualização: $($dados.DataCaptura)" -ForegroundColor Gray
        Write-Host ""
        Write-Host "Resumo:" -ForegroundColor White
        Write-Host "  Total de máquinas: $($dados.TotalMaquinas)" -ForegroundColor White
        Write-Host "  ✓ Online: $($dados.MaquinasOnline)" -ForegroundColor $corSucesso
        Write-Host "  ✗ Offline: $($dados.TotalMaquinas - $dados.MaquinasOnline)" -ForegroundColor $corErro
        Write-Host "  👤 Usuários Ativos: $($dados.UsuariosAtivos)" -ForegroundColor $corAviso
        Write-Host ""
        
        if ($dados.Maquinas -and $dados.Maquinas.Count -gt 0) {
            Write-Host "Máquinas:" -ForegroundColor White
            foreach ($maq in $dados.Maquinas) {
                $corMaq = if ($maq.Status -eq "Online") { $corSucesso } else { $corErro }
                Write-Host "  [$($maq.Status.PadRight(8))] $($maq.Nome.PadRight(20)) - $($maq.TotalUsuarios) usuário(s)" -ForegroundColor $corMaq
                
                if ($maq.Usuarios -and $maq.Usuarios.Count -gt 0) {
                    foreach ($u in $maq.Usuarios) {
                        $corUser = if ($u.Status -eq "Ativo") { $corSucesso } else { $corAviso }
                        Write-Host "           $($u.Usuario.PadRight(15)) [$($u.Status)]" -ForegroundColor $corUser
                    }
                }
            }
        }
        
        Write-Host ""
        Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
        
    } catch {
        Write-Host "❌ Erro ao ler dados: $_" -ForegroundColor $corErro
    }
    
    Read-Host "Pressione ENTER para continuar"
}

function Exportar-Dados {
    Write-Host ""
    
    $arquivoStatus = "$PSScriptRoot\status_usuarios.json"
    
    if (-not (Test-Path $arquivoStatus)) {
        Write-Host "❌ Nenhum dado disponível" -ForegroundColor $corErro
        Read-Host "Pressione ENTER para continuar"
        return
    }
    
    Write-Host "📄 DADOS EXPORTADOS (JSON)" -ForegroundColor $corTitulo
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
    Write-Host ""
    
    $conteudo = Get-Content $arquivoStatus -Raw
    Write-Host $conteudo -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor $corTitulo
    
    # Oferece opção de salvar em arquivo
    $salvar = Read-Host "Deseja salvar em arquivo? (s/n)"
    if ($salvar -eq 's' -or $salvar -eq 'S') {
        $nomeArquivo = "dados_usuarios_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').json"
        $conteudo | Out-File -FilePath $nomeArquivo -Encoding UTF8
        Write-Host "✓ Salvo em: $nomeArquivo" -ForegroundColor $corSucesso
    }
    
    Read-Host "Pressione ENTER para continuar"
}

# PROGRAMA PRINCIPAL
Set-Location $PSScriptRoot

while ($true) {
    Show-Banner
    
    # Faz varredura inicial
    $resultadoVarredura = Varrer-Maquinas
    
    if ($VerSomente) {
        exit
    }
    
    # Menu
    $opcao = Show-Menu
    
    switch ($opcao) {
        "1" {
            Iniciar-Monitor
            # Volta ao menu após parar
        }
        "2" {
            Ver-Dashboard
            # Volta ao menu após parar
        }
        "3" {
            Ver-Status
        }
        "4" {
            Exportar-Dados
        }
        "5" {
            # Volta ao início (nova varredura)
            continue
        }
        "0" {
            Write-Host ""
            Write-Host "Encerrando..." -ForegroundColor $corAviso
            Write-Host ""
            exit
        }
        default {
            Write-Host "❌ Opção inválida!" -ForegroundColor $corErro
            Read-Host "Pressione ENTER para continuar"
        }
    }
}
