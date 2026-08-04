<?php
date_default_timezone_set('America/Porto_Velho');
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

if (!MODULO_IMPRESSAO) {
    header('Location: chamados.php');
    exit;
}



requireAdmin(); // Somente administradores acessam a Gestão de Impressão

// Carregamento de dados
try {
    $stmt = $pdo->query("SELECT SUM(paginas) as total_paginas, SUM(valor_total) as receita_total FROM impressoes");
    $totais = $stmt->fetch();

    $stmt = $pdo->query("SELECT COUNT(*) as total, SUM(CASE WHEN status='Online' THEN 1 ELSE 0 END) as online FROM impressoras");
    $statusImp = $stmt->fetch();

    $stmt = $pdo->query("SELECT SUM(paginas) as paginas_hoje FROM impressoes WHERE DATE(data_hora) = CURRENT_DATE");
    $hoje = $stmt->fetch();

    // Chamados Pendentes Detalhado
    $stmt = $pdo->query("SELECT 
        COUNT(*) as total, 
        SUM(CASE WHEN status='Aberto' THEN 1 ELSE 0 END) as abertos,
        SUM(CASE WHEN status='Em Atendimento' THEN 1 ELSE 0 END) as curso,
        SUM(CASE WHEN status='Resolvido' THEN 1 ELSE 0 END) as resolvidos
    FROM chamados");
    $chamadosStats = $stmt->fetch();

    $stmt = $pdo->query("SELECT titulo, usuario, data_abertura FROM chamados WHERE status != 'Resolvido' ORDER BY data_abertura DESC LIMIT 1");
    $ultimoChamado = $stmt->fetch();

    // Dados da Rede - Busca em múltiplos locais (Docker / Local)
    $jsonRede = null;
    $candidatosRede = [
        '/var/www/status_usuarios.json', // Docker
        __DIR__ . '/../status_usuarios.json', // Local (Root)
        __DIR__ . '/status_usuarios.json' // Legado
    ];
    
    foreach ($candidatosRede as $path) {
        if (file_exists($path)) {
            $jsonRede = $path;
            break;
        }
    }

    $rede = ['TotalMaquinas' => 0, 'MaquinasOnline' => 0];
    if ($jsonRede) {
        $content = file_get_contents($jsonRede);
        // Remove o UTF-8 BOM se existir para evitar erro no json_decode
        if (strncmp($content, "\xEF\xBB\xBF", 3) === 0) {
            $content = substr($content, 3);
        }
        $redeData = json_decode($content, true);
        if ($redeData) {
            $rede['TotalMaquinas'] = $redeData['TotalMaquinas'] ?? 0;
            $rede['MaquinasOnline'] = $redeData['MaquinasOnline'] ?? 0;
        }
    }
} catch (PDOException $e) {
    die('Erro: ' . $e->getMessage());
}

$pageTitle = 'Dashboard Executivo | ' . APP_NAME;
require_once 'includes/header.php';
?>

<link rel="stylesheet" href="css/monitor.css">
<style>
    .light-mode body, .light-mode .max-w-7xl { background-color: #f1f5f9 !important; background-image: none !important; }
    .light-mode .glass-card { background: #ffffff !important; border-color: #cbd5e1 !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important; }
    .light-mode .text-\[var\(--text-primary\)\] { color: #000000 !important; }
    .light-mode .text-\[var\(--text-bold\)\] { color: #000000 !important; }
    .light-mode table thead tr { background: #f1f5f9 !important; }
    .light-mode th { color: #475569 !important; }
    
    .badge-pb    { background:rgba(148,163,184,.1); color:#94a3b8; border:1px solid rgba(148,163,184,.2); }
    .badge-color { background:rgba(236,72,153,.1);  color:#ec4899; border:1px solid rgba(236,72,153,.2); }
    /* Badges de tipo de documento */
    .badge-pdf   { background:rgba(239,68,68,.12);  color:#ef4444; border:1px solid rgba(239,68,68,.25); }
    .badge-word  { background:rgba(59,130,246,.12); color:#3b82f6; border:1px solid rgba(59,130,246,.25); }
    .badge-excel { background:rgba(34,197,94,.12);  color:#22c55e; border:1px solid rgba(34,197,94,.25); }
    .badge-ppt   { background:rgba(249,115,22,.12); color:#f97316; border:1px solid rgba(249,115,22,.25); }
    .badge-txt   { background:rgba(148,163,184,.1); color:#94a3b8; border:1px solid rgba(148,163,184,.2); }
    .badge-img   { background:rgba(168,85,247,.12); color:#a855f7; border:1px solid rgba(168,85,247,.25); }
    .badge-sys   { background:rgba(100,116,139,.1); color:#64748b; border:1px solid rgba(100,116,139,.2); }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-0 pb-8 animate-fade-in">
    
    <!-- Header -->
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-4">
        <div class="flex items-center gap-4">
            <div class="p-3 bg-emerald-500/10 rounded-2xl border border-emerald-500/20 shadow-inner hidden sm:block">
                <svg class="w-8 h-8 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"></path></svg>
            </div>
            <div>
                <h1 class="text-3xl font-black text-[var(--text-primary)] tracking-tighter mb-1 uppercase">Dashboard</h1>
                <div class="flex items-center gap-2 text-[var(--text-secondary)] font-bold uppercase text-[10px] tracking-[0.3em]">
                    <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_#10b981]"></span>
                    Operação em Tempo Real
                </div>
            </div>
        </div>
        <div class="flex flex-wrap gap-3">
            <a href="monitor_usuarios.php" class="px-5 py-3 rounded-2xl bg-white/5 text-slate-300 border border-white/10 font-black text-[10px] uppercase tracking-widest hover:bg-white/10 hover:text-white transition-all flex items-center gap-2 shadow-inner html-light:bg-slate-100 html-light:text-slate-600 html-light:border-slate-200 html-light:hover:bg-slate-200 html-light:hover:text-slate-800">
                <svg class="w-4 h-4 text-indigo-400 html-light:text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2-0 01-2-2z"></path></svg>
                Monitor de Rede
            </a>
            <button onclick="window.location.reload()" class="px-5 py-3 rounded-2xl bg-indigo-600 text-white font-black text-[10px] uppercase tracking-widest shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/40 hover:-translate-y-0.5 transition-all flex items-center gap-2 group border border-indigo-500">
                <svg class="w-4 h-4 group-hover:rotate-180 transition-transform duration-700 ease-in-out" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                Sincronizar
            </button>
        </div>
    </div>

    <!-- KPIs -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
        <div class="glass-card rounded-3xl p-6 border-l-4 border-indigo-500">
            <p class="text-indigo-500 text-[10px] font-black uppercase tracking-widest mb-3">Rede Online</p>
            <h3 class="text-4xl font-black text-indigo-500"><?= $rede['MaquinasOnline'] ?> <span class="text-sm opacity-50">/ <?= $rede['TotalMaquinas'] ?></span></h3>
        </div>
        <div class="glass-card rounded-3xl p-6 border-l-4 border-cyan-500">
            <p class="text-cyan-500 text-[10px] font-black uppercase tracking-widest mb-3">Impressoras</p>
            <h3 class="text-4xl font-black text-cyan-500"><?= $statusImp['online'] ?> <span class="text-sm opacity-50">/ <?= $statusImp['total'] ?></span></h3>
                    </div>
            <button id="btnAddManualIdx" class="text-xs bg-indigo-600/20 hover:bg-indigo-600 border border-indigo-500/30 text-indigo-200 font-bold px-4 py-2 rounded-lg transition-all mt-2" onclick="window.location.href='impressoras.php#formAdd'">Adicionar Impressora Manual</button>
        <div class="glass-card rounded-3xl p-6 border-l-4 border-fuchsia-500">
            <p class="text-fuchsia-500 text-[10px] font-black uppercase tracking-widest mb-3">Total Páginas</p>
            <h3 class="text-4xl font-black text-fuchsia-500"><?= number_format($totais['total_paginas'] ?? 0, 0, ',', '.') ?></h3>
        </div>
        <div class="glass-card rounded-3xl p-6 border-l-4 border-emerald-500">
            <p class="text-emerald-500 text-[10px] font-black uppercase tracking-widest mb-3">Faturamento</p>
            <h3 class="text-4xl font-black text-emerald-500">R$ <?= number_format($totais['receita_total'] ?? 0, 2, ',', '.') ?></h3>
        </div>
        <div class="glass-card rounded-3xl p-6 border-l-4 border-indigo-500 bg-indigo-500/5 group hover:bg-indigo-500/10 transition-all cursor-pointer relative overflow-hidden" onclick="window.location.href='chamados.php'">
            <div class="flex justify-between items-start mb-4 relative z-10">
                <div>
                    <p class="text-indigo-400 text-[10px] font-black uppercase tracking-widest mb-1">Suporte TI</p>
                    <h3 class="text-3xl font-black text-white"><?= $chamadosStats['total'] ?> <span class="text-[10px] text-slate-500 uppercase tracking-widest ml-1">Total</span></h3>
                </div>
                <div class="flex flex-col items-end gap-1.5">
                    <span class="px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-500 text-[8px] font-black uppercase tracking-widest border border-rose-500/20"><?= $chamadosStats['abertos'] ?> Novos</span>
                    <span class="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-500 text-[8px] font-black uppercase tracking-widest border border-amber-500/20"><?= $chamadosStats['curso'] ?> Em Curso</span>
                    <span class="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-500 text-[8px] font-black uppercase tracking-widest border border-emerald-500/20"><?= $chamadosStats['resolvidos'] ?> Finalizados</span>
                </div>
            </div>
            
            <?php if($ultimoChamado): ?>
                <div class="mt-4 pt-4 border-t border-white/5 relative z-10">
                    <p class="text-[8px] text-slate-500 font-black uppercase tracking-widest mb-1 italic">Última Solicitação:</p>
                    <p class="text-[11px] text-white font-bold truncate tracking-tight"><?= htmlspecialchars($ultimoChamado['titulo']) ?></p>
                    <p class="text-[9px] text-indigo-400 font-medium mt-1 uppercase tracking-widest opacity-70"><?= $ultimoChamado['usuario'] ?></p>
                </div>
            <?php else: ?>
                <div class="mt-4 pt-4 border-t border-white/5 text-center relative z-10">
                    <p class="text-[9px] text-slate-600 font-black uppercase tracking-widest italic">Tudo resolvido por aqui! ✅</p>
                </div>
            <?php endif; ?>

            <!-- Efeito de Fundo -->
            <div class="absolute -right-4 -bottom-4 w-24 h-24 bg-indigo-500/10 rounded-full blur-3xl group-hover:bg-indigo-500/20 transition-all"></div>
        </div>
    </div>

    <!-- Gráficos -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
        <div class="glass-card rounded-[2.5rem] p-8 h-[380px] flex flex-col">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em] mb-8 text-center">Status da Rede</h3>
            <div class="flex-1 relative"><canvas id="chart-rede"></canvas></div>
        </div>
        <div class="glass-card rounded-[2.5rem] p-8 h-[380px] flex flex-col border-t-4 border-t-cyan-500">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em] mb-8 text-center">Uso por Equipamento</h3>
            <div class="flex-1 relative"><canvas id="chart-impressoras"></canvas></div>
        </div>
        <div class="glass-card rounded-[2.5rem] p-8 h-[380px] flex flex-col border-t-4 border-t-fuchsia-500">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em] mb-8 text-center">Top Usuários</h3>
            <div class="flex-1 relative"><canvas id="chart-usuarios"></canvas></div>
        </div>
    </div>

    <!-- Atividade Recente -->
    <div class="glass-card rounded-[2.5rem] overflow-hidden">
        <div class="p-8 border-b border-[var(--card-border)] bg-[var(--table-header-bg)]/30">
            <h2 class="text-2xl font-black text-[var(--text-primary)] tracking-tighter uppercase">Atividade Recente</h2>
            <p class="text-xs text-[var(--text-secondary)] font-bold tracking-widest uppercase opacity-60">Log de Impressões (Horário de Rondônia)</p>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-[var(--table-header-bg)]">
                        <th class="px-8 py-5 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">Data/Hora</th>
                        <th class="px-8 py-5 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">Documento / Tipo</th>
                        <th class="px-8 py-5 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">Colaborador</th>
                        <th class="px-8 py-5 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-[0.2em] text-center">Volume</th>
                        <th class="px-8 py-5 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-[0.2em] text-right">Custo</th>
                    </tr>
                </thead>
                <tbody id="tabela-atividades" class="divide-y divide-[var(--card-border)]">
                    <tr><td colspan="5" class="px-8 py-16 text-center text-slate-500 font-bold italic">Sincronizando atividades...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    const centerTextPlugin = {
        id: 'centerText',
        beforeDraw: function(chart) {
            // Protege contra gráficos sem texto central ou sem área definida
            if (!chart.config.options.elements || !chart.config.options.elements.center) return;
            if (!chart.chartArea) return;
            const ctx = chart.ctx;
            const txt = chart.config.options.elements.center.text;
            if (!txt) return;
            const color = getComputedStyle(document.body).getPropertyValue('--text-primary').trim() || '#f8fafc';
            ctx.save();
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const centerX = (chart.chartArea.left + chart.chartArea.right) / 2;
            const centerY = (chart.chartArea.top + chart.chartArea.bottom) / 2;
            // Ajusta fonte dinamicamente para nomes longos
            const fontSize = txt.length > 10 ? '13px' : txt.length > 6 ? '16px' : '28px';
            ctx.font = "900 " + fontSize + " 'Inter', sans-serif";
            ctx.fillStyle = color;
            ctx.fillText(txt, centerX, centerY);
            ctx.restore();
        }
    };

    let charts = {};

    function initCharts() {
        const baseOptions = { 
            responsive: true, 
            maintainAspectRatio: false, 
            cutout: '80%', 
            plugins: { 
                legend: { 
                    position: 'bottom', 
                    labels: { color: '#94a3b8', font: { size: 9, weight: 'bold' }, usePointStyle: true, padding: 16 } 
                } 
            }
        };

        // Gráfico Rede - com texto fixo do PHP
        charts.rede = new Chart(document.getElementById('chart-rede'), { 
            type: 'doughnut', 
            data: { 
                labels: ['Online', 'Offline'], 
                datasets: [{ 
                    data: [<?= (int)$rede['MaquinasOnline'] ?>, <?= (int)($rede['TotalMaquinas'] - $rede['MaquinasOnline']) ?>], 
                    backgroundColor: ['#10b981', '#ef4444'], 
                    borderWidth: 0 
                }] 
            }, 
            options: { 
                ...baseOptions, 
                elements: { center: { text: '<?= (int)$rede['MaquinasOnline'] ?>/<?= (int)$rede['TotalMaquinas'] ?>' } } 
            }, 
            plugins: [centerTextPlugin] 
        });

        // Gráfico Impressoras - texto será preenchido via AJAX
        charts.impressoras = new Chart(document.getElementById('chart-impressoras'), { 
            type: 'doughnut', 
            data: { labels: [], datasets: [{ data: [], backgroundColor: ['#06b6d4', '#3b82f6', '#6366f1', '#8b5cf6'], borderWidth: 0 }] }, 
            options: { ...baseOptions, elements: { center: null } },
            plugins: [centerTextPlugin] 
        });

        // Gráfico Usuários - texto será preenchido via AJAX
        charts.usuarios = new Chart(document.getElementById('chart-usuarios'), { 
            type: 'doughnut', 
            data: { labels: [], datasets: [{ data: [], backgroundColor: ['#f59e0b', '#f97316', '#ef4444', '#ec4899'], borderWidth: 0 }] }, 
            options: { ...baseOptions, elements: { center: null } },
            plugins: [centerTextPlugin]
        });
        
        // Carrega dados APÓS criar os gráficos
        loadStats();
        loadRecentActivity();
    }

    async function loadStats() {
        try {
            const res = await fetch('api/stats_impressao.php');
            const data = await res.json();
            if (!data.success) return;

            // Impressoras - coloca o nome campeão no centro
            charts.impressoras.data.labels = data.stats.impressoras.map(i => i.nome);
            charts.impressoras.data.datasets[0].data = data.stats.impressoras.map(i => i.total);
            if (data.stats.impressoras && data.stats.impressoras.length > 0) {
                charts.impressoras.options.elements.center = { text: data.stats.impressoras[0].nome };
            } else {
                charts.impressoras.options.elements.center = { text: 'Nenhum Dado' };
            }
            charts.impressoras.update();

            // Usuários - coloca o nome campeão no centro
            charts.usuarios.data.labels = data.stats.usuarios.map(u => u.nome);
            charts.usuarios.data.datasets[0].data = data.stats.usuarios.map(u => u.total);
            if (data.stats.usuarios && data.stats.usuarios.length > 0) {
                charts.usuarios.options.elements.center = { text: data.stats.usuarios[0].nome };
            } else {
                charts.usuarios.options.elements.center = { text: 'Nenhum Dado' };
            }
            charts.usuarios.update();

        } catch (e) { console.error("Erro stats:", e); }
    }

    // Detecta estilo visual baseado no tipo salvo no banco ou extensão
    function getDocBadge(tipo, nome) {
        const tipos = {
            'PDF':    { label: 'PDF',    css: 'badge-pdf',   icon: '📕' },
            'Word':   { label: 'Word',   css: 'badge-word',  icon: '📘' },
            'Excel':  { label: 'Excel',  css: 'badge-excel', icon: '📗' },
            'PPT':    { label: 'PPT',    css: 'badge-ppt',   icon: '📙' },
            'Texto':  { label: 'Texto',  css: 'badge-txt',   icon: '📄' },
            'Imagem': { label: 'Imagem', css: 'badge-img',   icon: '🖼️' },
            'Web':    { label: 'Web',    css: 'badge-word',  icon: '🌐' },
            'E-mail': { label: 'E-mail', css: 'badge-ppt',   icon: '📧' },
            'Sistema':{ label: 'Sistema',css: 'badge-sys',   icon: '🖨️' }
        };

        if (tipo && tipos[tipo]) return tipos[tipo];

        // Fallback para adivinhação se o tipo for genérico
        const nomeLower = (nome || '').toLowerCase();
        if (nomeLower.includes('.pdf')) return tipos['PDF'];
        if (nomeLower.includes('.doc')) return tipos['Word'];
        if (nomeLower.includes('.xls') || nomeLower.includes('.csv')) return tipos['Excel'];
        if (nomeLower.includes('.ppt')) return tipos['PPT'];
        
        return tipos['Sistema'];
    }

    async function loadRecentActivity() {
        try {
            const res = await fetch('api/recent_activity.php');
            const data = await res.json();
            if (!data.success) return;

            const tbody = document.getElementById('tabela-atividades');
            if (!tbody) return;

            if (data.atividades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="px-8 py-16 text-center text-slate-500 font-bold italic">Nenhuma impressão registrada ainda.</td></tr>';
                return;
            }

            let html = '';
            data.atividades.forEach(imp => {
                const initials = (imp.usuario || '??').substring(0, 2);
                const isColor = imp.tipo_impressao === 'Colorida';
                const badgeClass = isColor ? 'badge-color' : 'badge-pb';
                const typeLabel = isColor ? 'Colorida' : 'P&B';
                const docBadge = getDocBadge(imp.tipo_documento, imp.documento);

                const nomeDoc = imp.documento || 'Desconhecido';

                html += `
                    <tr class="hover:bg-[var(--table-row-hover)] transition-all duration-300 group border-b border-[var(--card-border)]">

                        <!-- Data / Hora -->
                        <td class="px-8 py-6 whitespace-nowrap">
                            <div class="flex flex-col gap-1">
                                <span class="text-sm font-black text-[var(--text-bold)]">${imp.data_formatada}</span>
                                <span class="text-[11px] font-bold text-indigo-400 font-mono tracking-wider">${imp.hora_formatada}</span>
                            </div>
                        </td>

                        <!-- Documento -->
                        <td class="px-8 py-6">
                            <div class="flex flex-col gap-2">
                                <!-- Badges de tipo -->
                                <div class="flex items-center gap-2 flex-wrap">
                                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest ${docBadge.css}">${docBadge.icon} ${docBadge.label}</span>
                                    <span class="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest ${badgeClass}">${typeLabel}</span>
                                </div>
                                <!-- Nome do documento -->
                                <span class="text-sm font-bold text-[var(--text-bold)] group-hover:text-indigo-400 transition-colors truncate max-w-[380px] tracking-tight leading-snug">${nomeDoc}</span>
                                <!-- Impressora e Máquina -->
                                <div class="flex items-center gap-3 mt-0.5">
                                    <span class="flex items-center gap-1 text-[9px] font-bold text-cyan-500 uppercase tracking-widest">
                                        <span class="w-1.5 h-1.5 rounded-full bg-cyan-500 shadow-[0_0_5px_#06b6d4]"></span>
                                        ${imp.nome_impressora || 'Local'}
                                    </span>
                                    <span class="text-[9px] text-[var(--text-muted)] font-medium opacity-60">• ${imp.maquina}</span>
                                </div>
                            </div>
                        </td>

                        <!-- Colaborador -->
                        <td class="px-8 py-6 whitespace-nowrap">
                            <div class="flex items-center gap-3">
                                <div class="w-9 h-9 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-500 font-black text-xs border border-indigo-500/20 uppercase shrink-0">
                                    ${initials}
                                </div>
                                <div class="flex flex-col">
                                    <span class="text-[9px] text-[var(--text-muted)] font-bold uppercase tracking-widest opacity-60">Colaborador</span>
                                    <span class="text-sm font-bold text-[var(--text-bold)] uppercase tracking-tight">${imp.usuario}</span>
                                </div>
                            </div>
                        </td>

                        <!-- Volume -->
                        <td class="px-8 py-6 text-center whitespace-nowrap">
                            <div class="inline-flex flex-col items-center gap-1">
                                <span class="text-2xl font-black text-[var(--text-primary)] leading-none">${imp.paginas}</span>
                                <span class="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-widest">Páginas</span>
                            </div>
                        </td>

                        <!-- Custo -->
                        <td class="px-8 py-6 text-right whitespace-nowrap">
                            <div class="flex flex-col items-end gap-0.5">
                                <span class="text-[9px] text-[var(--text-muted)] font-bold uppercase tracking-widest opacity-60">Custo</span>
                                <span class="text-lg font-black text-emerald-500 tracking-tighter leading-none">
                                    <span class="text-[10px] opacity-60">R$</span> ${parseFloat(imp.valor_total).toLocaleString('pt-BR', {minimumFractionDigits: 2})}
                                </span>
                            </div>
                        </td>

                    </tr>
                `;
            });
            tbody.innerHTML = html;

        } catch (e) { console.error("Erro atividade:", e); }
    }

    // Initialize charts and start periodic updates
    initCharts();
    // First load
    loadRecentActivity();
    loadStats();
    // Async loop for subsequent updates
    (async function scheduleUpdates() {
        while (true) {
            await new Promise(r => setTimeout(r, 5000)); // activity interval
            try { await loadRecentActivity(); } catch(e) { console.error('Erro ao atualizar atividades', e); }
            await new Promise(r => setTimeout(r, 10000)); // stats interval
            try { await loadStats(); } catch(e) { console.error('Erro ao atualizar stats', e); }
        }
    })();
</script>

<?php require_once 'includes/footer.php'; ?>
