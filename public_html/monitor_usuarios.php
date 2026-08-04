<?php
// Função para buscar e mesclar os dados de monitoramento
function getMonitorData() {
    $dataUsuarios = null;
    $candidatosUsu = [
        '/var/www/status_usuarios.json', // Docker
        __DIR__ . '/../status_usuarios.json', // Local (Root)
        __DIR__ . '/status_usuarios.json' // Legado
    ];
    foreach ($candidatosUsu as $path) {
        if (file_exists($path)) {
            $content = file_get_contents($path);
            if (strncmp($content, "\xEF\xBB\xBF", 3) === 0) $content = substr($content, 3);
            $dataUsuarios = json_decode($content, true);
            if ($dataUsuarios) break;
        }
    }
    if (!$dataUsuarios) $dataUsuarios = ['Maquinas' => [], 'MaquinasOnline' => 0, 'TotalMaquinas' => 0, 'UsuariosAtivos' => 0];

    // Carrega maquinas escaneadas da rede (Scanner de Rede)
    $dataRede = null;
    $candidatosRede = [
        '/var/www/status_maquinas.json',
        __DIR__ . '/../status_maquinas.json',
        __DIR__ . '/status_maquinas.json'
    ];
    foreach ($candidatosRede as $path) {
        if (file_exists($path)) {
            $content = file_get_contents($path);
            if (strncmp($content, "\xEF\xBB\xBF", 3) === 0) $content = substr($content, 3);
            $dataRede = json_decode($content, true);
            if ($dataRede) break;
        }
    }

    // Mescla as máquinas da rede que não possuem o agente instalado
    if ($dataRede && isset($dataRede['Maquinas'])) {
        $existentes = [];
        foreach ($dataUsuarios['Maquinas'] as $m) {
            $nome = strtoupper(trim($m['Nome'] ?? ''));
            if ($nome) $existentes[$nome] = true;
        }

        foreach ($dataRede['Maquinas'] as $ip => $m) {
            $nome = strtoupper(trim($m['Nome'] ?? ''));
            if (!$nome || isset($existentes[$nome]) || $nome === 'OFFLINE' || $nome === 'SEM-NOME') continue;

            $status = $m['Status'] ?? 'Offline';
            
            // Se for nova, adiciona com array de usuários vazio (renderiza como Livre)
            $dataUsuarios['Maquinas'][] = [
                'Nome' => $m['Nome'],
                'IP' => $ip,
                'Status' => $status,
                'HoraVerificacao' => $m['Timestamp'] ?? '',
                'Usuarios' => []
            ];
            
            $dataUsuarios['TotalMaquinas']++;
            if ($status === 'Online') {
                $dataUsuarios['MaquinasOnline']++;
            }
        }
    }

    return $dataUsuarios;
}

// Resposta AJAX para o Polling - NÃO REQUER AUTENTICAÇÃO
if (isset($_GET['format']) && $_GET['format'] === 'json') {
    header('Content-Type: application/json');
    $data = getMonitorData();
    echo json_encode([
        'success' => !!$data,
        'status' => $data,
        'mensagem' => $data ? '' : 'Aguardando dados...'
    ]);
    exit;
}

// A partir daqui requer autenticação
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

$pageTitle = 'Monitor de Rede | ' . APP_NAME;
require_once 'includes/header.php';
?>

<link rel="stylesheet" href="css/monitor.css">
<style>
    /* Força clareza máxima ignorando cache */
    .light-mode body, .light-mode .max-w-7xl { background-color: #f1f5f9 !important; background-image: none !important; }
    .light-mode .glass-card { background: #ffffff !important; border-color: #cbd5e1 !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important; }
    .light-mode .text-\[var\(--text-primary\)\] { color: #000000 !important; }
    .light-mode .text-\[var\(--text-bold\)\] { color: #000000 !important; }
    .light-mode table thead tr { background: #f1f5f9 !important; }
    .light-mode th { color: #475569 !important; }
</style>

<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-0 pb-8 animate-fade-in">
    <!-- Cabeçalho Principal -->
    <div class="flex flex-col md:flex-row justify-between items-center gap-6 mb-4">
        <div class="flex items-center gap-4">
            <div class="p-3 bg-indigo-500/10 rounded-2xl border border-indigo-500/20">
                <svg class="w-8 h-8 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2-0 01-2-2z"></path></svg>
            </div>
            <div>
                <h1 class="text-3xl font-black text-[var(--text-primary)] tracking-tight uppercase">Status da Rede</h1>
                <p class="text-[var(--text-secondary)] font-medium">Monitoramento em tempo real de máquinas e usuários.</p>
            </div>
        </div>

        <div class="flex items-center gap-4">
            <div class="relative group">
                <select id="filtro-usuario-sistema" class="glass-input pl-10 pr-4 py-2.5 rounded-xl text-sm w-full sm:w-64">
                    <option value="">Todos os usuários do sistema</option>
                    <!-- Opções preenchidas via JS -->
                </select>
                <svg class="w-4 h-4 text-[var(--text-muted)] absolute left-3 top-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
            </div>
            <div class="relative group">
                <input type="text" id="filtro-maquina" placeholder="Filtrar computador ou usuário..." 
                       class="glass-input pl-10 pr-4 py-2.5 rounded-xl text-sm w-full sm:w-80">
                <svg class="w-4 h-4 text-[var(--text-muted)] absolute left-3 top-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
            </div>
            <button id="btn-atualizar" class="p-2.5 rounded-xl bg-indigo-500 text-white shadow-lg shadow-indigo-500/20 hover:scale-105 active:scale-95 transition-all group">
                <svg class="w-6 h-6 group-hover:rotate-180 transition-transform duration-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
            </button>
        </div>
    </div>

    <!-- KPIs em Círculos -->
    <div class="flex flex-wrap justify-center gap-12 mb-12">
        <div class="flex flex-col items-center gap-3">
            <div class="w-28 h-28 rounded-full border-2 border-[var(--card-border)] flex items-center justify-center bg-[var(--card-bg)] shadow-sm">
                <span id="total-maquinas" class="text-4xl font-black text-[var(--text-primary)]">0</span>
            </div>
            <span class="text-[10px] font-bold uppercase tracking-widest text-[var(--text-secondary)]">Máquinas Totais</span>
        </div>
        <div class="flex flex-col items-center gap-3">
            <div class="w-28 h-28 rounded-full border-2 border-emerald-500/30 flex items-center justify-center bg-[var(--card-bg)] shadow-sm">
                <span id="maquinas-online" class="text-4xl font-black text-emerald-500">0</span>
            </div>
            <span class="text-[10px] font-bold uppercase tracking-widest text-emerald-500">Online Agora</span>
        </div>
        <div class="flex flex-col items-center gap-3">
            <div class="w-28 h-28 rounded-full border-2 border-red-500/30 flex items-center justify-center bg-[var(--card-bg)] shadow-sm">
                <span id="maquinas-offline" class="text-4xl font-black text-red-500">0</span>
            </div>
            <span class="text-[10px] font-bold uppercase tracking-widest text-red-500">Offline</span>
        </div>
        <div class="flex flex-col items-center gap-3">
            <div class="w-28 h-28 rounded-full border-2 border-amber-500/30 flex items-center justify-center bg-[var(--card-bg)] shadow-sm">
                <span id="usuarios-ativos" class="text-4xl font-black text-amber-500">0</span>
            </div>
            <span class="text-[10px] font-bold uppercase tracking-widest text-amber-500">Usuários Ativos</span>
        </div>
    </div>

    <!-- Alertas e Notificações -->
    <div id="alerts-container" class="mb-6 hidden">
        <div class="glass-card p-4 rounded-xl border-l-4 border-amber-500 bg-amber-500/10">
            <div class="flex items-center gap-3">
                <svg class="w-6 h-6 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"></path>
                </svg>
                <div>
                    <h4 class="font-bold text-amber-700 dark:text-amber-300">Alertas do Sistema</h4>
                    <ul id="alerts-list" class="text-sm text-amber-600 dark:text-amber-200 mt-1"></ul>
                </div>
                <button id="btn-dismiss-alerts" class="ml-auto text-amber-500 hover:text-amber-700">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
        </div>
    </div>
    <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div class="flex items-center gap-4">
            <div class="flex items-center gap-2">
                <input type="checkbox" id="auto-refresh" checked class="w-4 h-4 text-indigo-600 bg-gray-100 border-gray-300 rounded focus:ring-indigo-500">
                <label for="auto-refresh" class="text-sm text-[var(--text-secondary)]">Atualização automática</label>
            </div>
            <div class="flex items-center gap-2">
                <label for="refresh-interval" class="text-sm text-[var(--text-secondary)]">Intervalo:</label>
                <select id="refresh-interval" class="glass-input px-3 py-1 rounded-lg text-sm">
                    <option value="2000">2s</option>
                    <option value="5000" selected>5s</option>
                    <option value="10000">10s</option>
                    <option value="30000">30s</option>
                </select>
            </div>
        </div>
        
        <div class="flex items-center gap-2">
            <button id="btn-export" class="px-4 py-2 bg-green-600 text-white text-sm font-bold rounded-lg hover:bg-green-500 transition-all flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                Exportar CSV
            </button>
            <button id="btn-fullscreen" class="p-2 bg-slate-600 text-white rounded-lg hover:bg-slate-500 transition-all">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 3a1 1 0 011 1v16a1 1 0 01-1 1H3a1 1 0 01-1-1V4a1 1 0 011-1h18zM9 9l6 6m0-6l-6 6"></path></svg>
            </button>
        </div>
    </div>
    <div class="glass-card rounded-3xl overflow-hidden shadow-2xl border border-[var(--card-border)]">
        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr style="background: var(--table-header-bg)">
                        <th class="px-6 py-4 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">Computador / Host</th>
                        <th class="px-6 py-4 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider">Usuário Logado</th>
                        <th class="px-6 py-4 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider text-center">Status Rede</th>
                        <th class="px-6 py-4 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider text-center">Tempo Online</th>
                        <th class="px-6 py-4 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider text-center">Última Atividade</th>
                        <th class="px-6 py-4 text-xs font-bold text-[var(--text-secondary)] uppercase tracking-wider text-right">Info Técnica</th>
                    </tr>
                </thead>
                <tbody id="tabela-usuarios" class="divide-y divide-[var(--card-border)]">
                    <tr><td colspan="4" class="px-8 py-16 text-center text-slate-500 font-medium italic">Sincronizando com a rede...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    let searchFilter = '';
    let userFilter = '';
    let systemUsers = [];

    function getUserDisplayName(username) {
        if (!username || username === 'Disponível') return username;
        const user = systemUsers.find(u => u.username === username);
        return user && user.nome ? user.nome : username;
    }

    async function fetchSystemUsers() {
        try {
            const res = await fetch('api_usuarios.php?action=list');
            const data = await res.json();
            console.log('Usuários do sistema carregados:', data);
            if (data.success && data.usuarios) {
                systemUsers = data.usuarios;
                const select = document.getElementById('filtro-usuario-sistema');
                data.usuarios.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.username;
                    option.textContent = `${user.nome || user.username} (${user.username})`;
                    select.appendChild(option);
                });
                console.log('Select preenchido com', data.usuarios.length, 'usuários');
            } else {
                console.error('Erro ao carregar usuários:', data.error);
            }
        } catch (e) {
            console.error("Erro ao carregar usuários do sistema:", e);
        }
    }

    async function fetchData() {
        try {
            const res = await fetch('?format=json');
            const data = await res.json();
            if (data.success && data.status) {
                updateUI(data.status);
            }
        } catch (e) {
            console.error("Erro na atualização:", e);
        }
    }

    function updateUI(s) {
        document.getElementById('total-maquinas').textContent = s.TotalMaquinas || 0;
        document.getElementById('maquinas-online').textContent = s.MaquinasOnline || 0;
        document.getElementById('maquinas-offline').textContent = (s.TotalMaquinas || 0) - (s.MaquinasOnline || 0);

        // Contar usuários ativos
        let activeUsers = 0;
        if (s.Maquinas) {
            s.Maquinas.forEach(m => {
                if (m.Status === 'Online' && m.Usuarios) {
                    activeUsers += m.Usuarios.filter(u => u.Usuario !== 'Disponível').length;
                }
            });
        }
        document.getElementById('usuarios-ativos').textContent = activeUsers;

        // Verificar alertas
        checkAlerts(s);

        const tbody = document.getElementById('tabela-usuarios');
        let html = '';
        
        if (!s.Maquinas || s.Maquinas.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="px-8 py-16 text-center text-red-400 font-bold">Nenhum computador encontrado.</td></tr>';
            return;
        }

        s.Maquinas.forEach(m => {
            const users = m.Usuarios || [];
            const searchStr = (m.Nome + ' ' + (users.map(u => u.Usuario).join(' '))).toLowerCase();
            const hasFilteredUser = !userFilter || users.some(u => u.Usuario === userFilter);
            
            if (searchFilter && !searchStr.includes(searchFilter)) return;
            if (!hasFilteredUser) return;

            const isOnline = m.Status === 'Online';
            
            if (users.length === 0) {
                html += renderRow(m, { Usuario: 'Disponível', Status: 'Livre', TempoOcioso: '--' }, isOnline);
            } else {
                users.forEach(u => {
                    html += renderRow(m, u, isOnline);
                });
            }
        });
        
        tbody.innerHTML = html;
        verifyOfflineMachines();
    }

    function checkAlerts(s) {
        const alerts = [];
        const alertsContainer = document.getElementById('alerts-container');
        const alertsList = document.getElementById('alerts-list');

        // Verificar máquinas offline há muito tempo
        if (s.Maquinas) {
            s.Maquinas.forEach(m => {
                if (m.Status === 'Offline' && m.UltimaVerificacao) {
                    const lastCheck = new Date(m.UltimaVerificacao);
                    const now = new Date();
                    const diffHours = (now - lastCheck) / (1000 * 60 * 60);
                    
                    if (diffHours > 2) {
                        alerts.push(`Máquina ${m.Nome} offline há ${Math.floor(diffHours)} horas`);
                    }
                }
            });
        }

        // Verificar máquinas com alta latência
        if (s.Maquinas) {
            s.Maquinas.forEach(m => {
                if (m.Status === 'Online' && m.Latencia > 100) {
                    alerts.push(`Máquina ${m.Nome} com alta latência (${m.Latencia}ms)`);
                }
            });
        }

        // Verificar usuários ociosos há muito tempo
        if (s.Maquinas) {
            s.Maquinas.forEach(m => {
                if (m.Status === 'Online' && m.Usuarios) {
                    m.Usuarios.forEach(u => {
                        if (u.TempoOcioso && u.TempoOcioso !== '--') {
                            const idleMinutes = parseInt(u.TempoOcioso);
                            if (idleMinutes > 120) { // Mais de 2 horas
                                alerts.push(`Usuário ${u.Usuario} ocioso há ${Math.floor(idleMinutes/60)}h em ${m.Nome}`);
                            }
                        }
                    });
                }
            });
        }

        if (alerts.length > 0) {
            alertsList.innerHTML = alerts.map(alert => `<li>• ${alert}</li>`).join('');
            alertsContainer.classList.remove('hidden');
        } else {
            alertsContainer.classList.add('hidden');
        }
    }

    function formatTimeAgo(timestamp) {
        if (!timestamp || timestamp === '--') return '--';
        
        try {
            const date = new Date(timestamp);
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMins / 60);
            const diffDays = Math.floor(diffHours / 24);

            if (diffMins < 1) return 'Agora';
            if (diffMins < 60) return `${diffMins}min atrás`;
            if (diffHours < 24) return `${diffHours}h atrás`;
            return `${diffDays}d atrás`;
        } catch (e) {
            return timestamp;
        }
    }

    function exportToCSV() {
        const rows = Array.from(document.querySelectorAll('#tabela-usuarios tr'));
        if (rows.length === 0) {
            alert('Nenhum dado para exportar');
            return;
        }

        let csv = 'Computador,IP,Usuário,Status,Tempo Online,Última Atividade,Ping,Ocioso\n';
        
        rows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length >= 6) {
                const computer = cells[0].textContent.replace(/Computador:/, '').trim().split('\n')[0];
                const ip = cells[0].textContent.split('\n').pop().trim();
                const user = cells[1].textContent.replace(/Usuário:/, '').trim().split('\n')[0];
                const status = cells[2].textContent.trim();
                const onlineTime = cells[3].textContent.trim();
                const lastActivity = cells[4].textContent.trim();
                const ping = cells[5].textContent.split('Ping:')[1]?.split('ms')[0]?.trim() || '0';
                const idle = cells[5].textContent.split('Ocioso:')[1]?.trim() || '--';
                
                csv += `"${computer}","${ip}","${user}","${status}","${onlineTime}","${lastActivity}","${ping}ms","${idle}"\n`;
            }
        });

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `monitoramento_usuarios_${new Date().toISOString().split('T')[0]}.csv`;
        link.click();
    }

    function toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen();
        } else {
            document.exitFullscreen();
        }
    }

    function renderRow(m, u, isOnline) {
        const statusBadge = isOnline 
            ? `<span class="status-badge px-3 py-1 rounded-full text-[10px] font-black uppercase border bg-emerald-500/10 text-emerald-500 border-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.2)]">ONLINE</span>`
            : `<span class="status-badge px-3 py-1 rounded-full text-[10px] font-black uppercase border bg-red-500/10 text-red-500 border-red-500/20">OFFLINE</span>`;

        // Calcular tempo online aproximado
        const onlineTime = m.TempoOnline || 'Desconhecido';
        
        // Última atividade
        const lastActivity = u.UltimaAtividade || m.HoraVerificacao || '--';
        const activityTime = lastActivity !== '--' ? formatTimeAgo(lastActivity) : '--';

        return `
            <tr data-ip="${m.IP || ''}" class="hover:bg-[var(--table-row-hover)] transition-all duration-300 group">
                <td class="px-6 py-4">
                    <div class="flex items-center gap-3">
                        <div class="relative">
                            <div class="w-3 h-3 rounded-full ${isOnline ? 'bg-emerald-500' : 'bg-red-500'}"></div>
                            ${isOnline ? '<div class="absolute inset-0 w-3 h-3 rounded-full bg-emerald-500 animate-ping opacity-75"></div>' : ''}
                        </div>
                        <div>
                            <span class="text-[10px] text-indigo-400 font-black uppercase tracking-widest block opacity-80 mb-0.5">Computador:</span>
                            <span class="font-black text-[var(--text-bold)] text-xl block group-hover:text-indigo-400 transition-colors tracking-tighter leading-none">${m.Nome}</span>
                            <span class="text-[10px] text-[var(--text-muted)] font-mono tracking-widest uppercase opacity-70 mt-1 block">${m.IP || 'Sem IP'}</span>
                        </div>
                    </div>
                </td>
                <td class="px-6 py-4">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-base font-black text-indigo-500 border border-indigo-500/20 uppercase shadow-sm">
                            ${(getUserDisplayName(u.Usuario) || '?').charAt(0)}
                        </div>
                        <div>
                            <span class="text-[10px] text-indigo-400 font-black uppercase tracking-widest block opacity-80 mb-0.5">Usuário:</span>
                            <span class="font-black text-[var(--text-bold)] text-lg block leading-none">${getUserDisplayName(u.Usuario)}</span>
                            <span class="text-[10px] text-[var(--text-muted)] uppercase tracking-widest mt-1 block font-bold">${u.Status || 'SISTEMA'}</span>
                        </div>
                    </div>
                </td>
                <td class="px-6 py-4 text-center">
                    ${statusBadge}
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="text-sm font-bold text-[var(--text-secondary)]">${onlineTime}</span>
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="text-sm font-mono text-[var(--text-muted)]">${activityTime}</span>
                </td>
                <td class="px-6 py-4 text-right font-mono text-[11px] text-[var(--text-muted)] leading-relaxed">
                    <div class="flex flex-col items-end gap-1">
                        <span class="flex items-center gap-1.5">
                            <span class="w-1 h-1 rounded-full bg-indigo-500"></span>
                            Ping: <span class="${isOnline ? 'text-[var(--text-bold)] font-bold' : ''}">${m.Latencia || 0}ms</span>
                        </span>
                        <span class="flex items-center gap-1.5">
                            <span class="w-1 h-1 rounded-full ${u.TempoOcioso !== 'nenhum' && u.TempoOcioso !== '--' ? 'bg-amber-500' : 'bg-slate-600'}"></span>
                            Ocioso: <span class="${u.TempoOcioso !== 'nenhum' && u.TempoOcioso !== '--' ? 'text-amber-500 font-bold' : ''}">${u.TempoOcioso}</span>
                        </span>
                    </div>
                </td>
            </tr>
        `;
    }

    async function verifyOfflineMachines() {
        const rows = Array.from(document.querySelectorAll('#tabela-usuarios tr[data-ip]'));
        const offlineRows = rows.filter(row => {
            const badge = row.querySelector('.status-badge');
            return badge && badge.textContent.trim() === 'OFFLINE';
        });

        for (const row of offlineRows) {
            const ip = row.dataset.ip;
            if (!ip) continue;

            try {
                const res = await fetch(`api_impressoras.php?action=scan_ip&ip=${encodeURIComponent(ip)}`, { cache: 'no-cache' });
                if (!res.ok) continue;
                const data = await res.json();
                if (data.success && data.online) {
                    const badge = row.querySelector('.status-badge');
                    if (badge) {
                        badge.outerHTML = `<span class="status-badge px-3 py-1 rounded-full text-[10px] font-black uppercase border bg-emerald-500/10 text-emerald-500 border-emerald-500/20 shadow-[0_0_15px_rgba(16,185,129,0.2)]">ONLINE</span>`;
                    }
                }
            } catch (err) {
                console.error('Erro ao verificar máquina offline:', err);
            }
        }
    }

    let autoRefreshInterval = null;

    function startAutoRefresh() {
        stopAutoRefresh();
        const interval = parseInt(document.getElementById('refresh-interval').value);
        autoRefreshInterval = setInterval(fetchData, interval);
    }

    function stopAutoRefresh() {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
    }

    document.getElementById('filtro-maquina').addEventListener('input', e => {
        searchFilter = e.target.value.toLowerCase();
        fetchData();
    });

    document.getElementById('filtro-usuario-sistema').addEventListener('change', e => {
        userFilter = e.target.value;
        fetchData();
    });

    document.getElementById('btn-atualizar').addEventListener('click', fetchData);

    document.getElementById('auto-refresh').addEventListener('change', e => {
        if (e.target.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });

    document.getElementById('refresh-interval').addEventListener('change', e => {
        if (document.getElementById('auto-refresh').checked) {
            startAutoRefresh();
        }
    });

    document.getElementById('btn-export').addEventListener('click', exportToCSV);
    document.getElementById('btn-fullscreen').addEventListener('click', toggleFullscreen);
    document.getElementById('btn-dismiss-alerts').addEventListener('click', () => {
        document.getElementById('alerts-container').classList.add('hidden');
    });

    fetchSystemUsers();
    fetchData();
    startAutoRefresh(); // Inicia atualização automática 
</script>

<?php require_once 'includes/footer.php'; ?>
