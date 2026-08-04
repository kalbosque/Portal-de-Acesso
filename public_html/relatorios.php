<?php
date_default_timezone_set('America/Porto_Velho');

// Detecta estilo visual baseado no label do banco
if (!function_exists('getVisualInfo')) {
    function getVisualInfo(string $label): array {
        return match($label) {
            'PDF'    => ['icon' => '📕', 'css' => 'badge-pdf'],
            'Word'   => ['icon' => '📘', 'css' => 'badge-word'],
            'Excel'  => ['icon' => '📗', 'css' => 'badge-excel'],
            'PPT'    => ['icon' => '📙', 'css' => 'badge-ppt'],
            'Texto'  => ['icon' => '📄', 'css' => 'badge-txt'],
            'Imagem' => ['icon' => '🖼️', 'css' => 'badge-img'],
            'Web'    => ['icon' => '🌐', 'css' => 'badge-word'], // Reuso de cor para web
            'E-mail' => ['icon' => '📧', 'css' => 'badge-ppt'],
            'Remota' => ['icon' => '🖥️', 'css' => 'badge-remote'],
            default  => ['icon' => '🖨️', 'css' => 'badge-sys'],
        };
    }
}
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

requireAdmin();

$mes = $_GET['mes'] ?? date('m');
$ano = $_GET['ano'] ?? date('Y');

// Otimização: Calcular range de datas para usar o índice idx_impressoes_data
$startDate = "$ano-$mes-01 00:00:00";
$endDate = date('Y-m-t 23:59:59', strtotime($startDate));

// Lógica de Exportação CSV
if (isset($_GET['action']) && $_GET['action'] === 'export') {
    $stmt = $pdo->prepare("SELECT i.data_hora, i.usuario, i.documento, i.tipo_documento, i.tipo_impressao, i.paginas, i.valor_total, imp.nome as impressora 
                           FROM impressoes i 
                           LEFT JOIN impressoras imp ON i.impressora_id = imp.id 
                           WHERE i.data_hora BETWEEN ? AND ?
                           ORDER BY i.data_hora DESC");
    $stmt->execute([$startDate, $endDate]);
    $dados = $stmt->fetchAll(PDO::FETCH_ASSOC);

    header('Content-Type: text/csv; charset=utf-8');
    header('Content-Disposition: attachment; filename=Relatorio_Impressao_'.$mes.'_'.$ano.'.csv');
    $output = fopen('php://output', 'w');
    fprintf($output, chr(0xEF).chr(0xBB).chr(0xBF)); // UTF-8 BOM para Excel
    fputcsv($output, ['Data e Hora (Rondônia)', 'Usuário', 'Documento', 'Formato', 'Tipo Impressão', 'Páginas', 'Valor (R$)', 'Impressora'], ';');
    foreach ($dados as $linha) {
        $dt = new DateTime($linha['data_hora']);
        fputcsv($output, [
            $dt->format('d/m/Y H:i:s'),
            $linha['usuario'],
            $linha['documento'],
            $linha['tipo_documento'] ?? 'Sistema',
            $linha['tipo_impressao'],
            $linha['paginas'],
            $linha['valor_total'],
            $linha['impressora']
        ], ';');
    }
    fclose($output);
    exit;
}

// Resumo por usuário - USANDO RANGE PARA PERFORMANCE
$stmt = $pdo->prepare("SELECT usuario, COUNT(*) as total_trabalhos, SUM(paginas) as total_paginas, SUM(valor_total) as total_valor 
                       FROM impressoes 
                       WHERE data_hora BETWEEN ? AND ?
                       GROUP BY usuario 
                       ORDER BY total_valor DESC");
$stmt->execute([$startDate, $endDate]);
$resumo_usuarios = $stmt->fetchAll();

// Resumo por impressora
$stmt = $pdo->prepare("SELECT COALESCE(imp.nome, 'Local / USB') as nome_impressora, COUNT(i.id) as total_trabalhos, SUM(i.paginas) as total_paginas, SUM(i.valor_total) as total_valor 
                       FROM impressoes i 
                       LEFT JOIN impressoras imp ON i.impressora_id = imp.id 
                       WHERE i.data_hora BETWEEN ? AND ?
                       GROUP BY i.impressora_id, imp.nome 
                       ORDER BY total_valor DESC");
$stmt->execute([$startDate, $endDate]);
$resumo_impressoras = $stmt->fetchAll();

// Evolução diária
$num_dias = date('t', strtotime($startDate));
$evolucao_diaria = [];
for ($i = 1; $i <= $num_dias; $i++) {
    $evolucao_diaria[$i] = ['dia' => $i, 'paginas' => 0];
}

$stmt = $pdo->prepare("SELECT EXTRACT(DAY FROM data_hora) as dia, SUM(paginas) as paginas 
                       FROM impressoes 
                       WHERE data_hora BETWEEN ? AND ?
                       GROUP BY EXTRACT(DAY FROM data_hora) 
                       ORDER BY dia ASC");
$stmt->execute([$startDate, $endDate]);
$dados_evolucao = $stmt->fetchAll();

foreach ($dados_evolucao as $d) {
    $dia = (int)$d['dia'];
    if (isset($evolucao_diaria[$dia])) {
        $evolucao_diaria[$dia]['paginas'] = (int)$d['paginas'];
    }
}
$evolucao_diaria = array_values($evolucao_diaria);

// Histórico detalhado
$stmt = $pdo->prepare("SELECT i.data_hora, i.usuario, i.documento, i.tipo_documento, i.tipo_impressao, i.paginas, i.valor_total, i.maquina, i.ip_maquina, imp.nome as impressora_nome 
                       FROM impressoes i 
                       LEFT JOIN impressoras imp ON i.impressora_id = imp.id 
                       WHERE i.data_hora BETWEEN ? AND ?
                       ORDER BY i.data_hora DESC LIMIT 200");
$stmt->execute([$startDate, $endDate]);
$historico_raw = $stmt->fetchAll();

$historico_detalhado = [];
foreach ($historico_raw as $row) {
    $dt = new DateTime($row['data_hora']);
    $row['data_formatada'] = $dt->format('d/m/Y');
    $row['hora_formatada'] = $dt->format('H:i');
    $historico_detalhado[] = $row;
}

$meses = [
    '01' => 'Janeiro', '02' => 'Fevereiro', '03' => 'Março', '04' => 'Abril',
    '05' => 'Maio', '06' => 'Junho', '07' => 'Julho', '08' => 'Agosto',
    '09' => 'Setembro', '10' => 'Outubro', '11' => 'Novembro', '12' => 'Dezembro'
];

$pageTitle = 'Relatórios | ' . APP_NAME;
require_once 'includes/header.php';
?>

<link rel="stylesheet" href="css/monitor.css">
<style>
    .light-mode body, .light-mode .max-w-7xl { background-color: #f1f5f9 !important; background-image: none !important; }
    .light-mode .glass-card { background: #ffffff !important; border-color: #cbd5e1 !important; }
    .light-mode .text-\[var\(--text-primary\)\] { color: #000000 !important; }
    .light-mode table thead tr { background: #f1f5f9 !important; }
    .light-mode th { color: #475569 !important; }
    .badge-pb    { background:rgba(148,163,184,.1); color:#94a3b8; border:1px solid rgba(148,163,184,.2); }
    .badge-cor   { background:rgba(236,72,153,.1);  color:#ec4899; border:1px solid rgba(236,72,153,.2); }
    /* Badges de tipo de documento */
    .badge-pdf   { background:rgba(239,68,68,.12);  color:#ef4444; border:1px solid rgba(239,68,68,.25); }
    .badge-word  { background:rgba(59,130,246,.12); color:#3b82f6; border:1px solid rgba(59,130,246,.25); }
    .badge-excel { background:rgba(34,197,94,.12);  color:#22c55e; border:1px solid rgba(34,197,94,.25); }
    .badge-ppt   { background:rgba(249,115,22,.12); color:#f97316; border:1px solid rgba(249,115,22,.25); }
    .badge-txt   { background:rgba(148,163,184,.1); color:#94a3b8; border:1px solid rgba(148,163,184,.2); }
    .badge-img   { background:rgba(168,85,247,.12); color:#a855f7; border:1px solid rgba(168,85,247,.25); }
    .badge-sys   { background:rgba(100,116,139,.1); color:#64748b; border:1px solid rgba(100,116,139,.2); }
    .badge-remote{ background:rgba(20,184,166,.12); color:#14b8a6; border:1px solid rgba(20,184,166,.25); }

    /* Correção para Select e Options (evita texto branco no fundo branco) */
    select option {
        background-color: #0f172a; /* Fundo escuro para modo dark */
        color: #f8fafc;
    }
    .light-mode select option {
        background-color: #ffffff; /* Fundo branco para modo light */
        color: #000000;
    }
    select:focus {
        outline: none;
        border-color: #6366f1 !important;
        box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
    }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-0 pb-8 animate-fade-in">

    <!-- Header -->
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-4">
        <div class="flex items-center gap-4">
            <div class="p-3 bg-amber-500/10 rounded-2xl border border-amber-500/20 shadow-inner hidden sm:block">
                <svg class="w-8 h-8 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
            </div>
            <div>
                <h1 class="text-3xl font-black text-[var(--text-primary)] tracking-tighter mb-1 uppercase">Relatórios</h1>
                <p class="text-xs text-[var(--text-secondary)] font-bold uppercase tracking-[0.3em] opacity-70">
                    Análise de Consumo · <?= $meses[$mes] ?> <?= $ano ?>
                </p>
            </div>
        </div>
        <div class="flex gap-3 print:hidden">
            <a href="relatorios.php?action=export&mes=<?= $mes ?>&ano=<?= $ano ?>" 
               class="px-5 py-3 rounded-2xl bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 font-black text-xs uppercase tracking-widest hover:bg-emerald-500/20 transition-all flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                Exportar CSV
            </a>
            <button onclick="window.print()" 
                    class="px-5 py-3 rounded-2xl bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 font-black text-xs uppercase tracking-widest hover:bg-indigo-500/20 transition-all flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"></path></svg>
                Imprimir
            </button>
        </div>
    </div>

    <!-- Filtro -->
    <div class="glass-card rounded-3xl p-6 mb-10 print:hidden">
        <form action="relatorios.php" method="GET" class="flex flex-wrap gap-4 items-end">
            <div class="flex-grow sm:flex-grow-0 min-w-[180px]">
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-2">Mês de Referência</label>
                <select name="mes" class="w-full px-4 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--card-border)] text-[var(--text-primary)] font-bold appearance-none">
                    <?php foreach($meses as $num => $nome): ?>
                        <option value="<?= $num ?>" <?= $mes == $num ? 'selected' : '' ?>><?= $nome ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div class="flex-grow sm:flex-grow-0 min-w-[100px]">
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-2">Ano</label>
                <select name="ano" class="w-full px-4 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--card-border)] text-[var(--text-primary)] font-bold appearance-none">
                    <option value="2026" <?= $ano == '2026' ? 'selected' : '' ?>>2026</option>
                    <option value="2025" <?= $ano == '2025' ? 'selected' : '' ?>>2025</option>
                </select>
            </div>
            <button type="submit" class="px-8 py-2.5 rounded-2xl bg-indigo-600 text-white font-black text-xs uppercase tracking-widest shadow-lg hover:bg-indigo-500 transition-all">
                Buscar
            </button>
        </form>
    </div>

    <!-- Gráfico + Impressoras -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
        <!-- Gráfico de Evolução -->
        <div class="glass-card rounded-3xl p-8">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em] mb-6">📈 Consumo Diário no Mês</h3>
            <div class="w-full h-64"><canvas id="evolucaoChart"></canvas></div>
        </div>

        <!-- Resumo por Impressora -->
        <div class="glass-card rounded-3xl overflow-hidden">
            <div class="px-8 py-5 border-b border-[var(--card-border)]">
                <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">🖨️ Uso por Equipamento</h3>
            </div>
            <table class="w-full text-left text-sm">
                <thead>
                    <tr class="bg-[var(--table-header-bg)]">
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Equipamento</th>
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Págs</th>
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-right">Custo</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-[var(--card-border)]">
                    <?php foreach($resumo_impressoras as $ri): ?>
                    <tr class="hover:bg-[var(--table-row-hover)] transition-colors">
                        <td class="px-8 py-4 font-bold text-[var(--text-bold)] flex items-center gap-2">
                            <span class="w-2 h-2 rounded-full bg-cyan-500 shadow-[0_0_6px_#06b6d4]"></span>
                            <?= htmlspecialchars($ri['nome_impressora']) ?>
                        </td>
                        <td class="px-8 py-4 text-center font-black text-[var(--text-primary)]"><?= number_format($ri['total_paginas'], 0, ',', '.') ?></td>
                        <td class="px-8 py-4 text-right font-black text-emerald-500">R$ <?= number_format($ri['total_valor'], 2, ',', '.') ?></td>
                    </tr>
                    <?php endforeach; ?>
                    <?php if(empty($resumo_impressoras)): ?>
                        <tr><td colspan="3" class="px-8 py-10 text-center text-[var(--text-muted)] italic">Sem registros neste período.</td></tr>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Consumo por Usuário -->
    <div class="glass-card rounded-3xl overflow-hidden mb-10">
        <div class="px-8 py-6 border-b border-[var(--card-border)]">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">👥 Consumo Acumulado por Colaborador</h3>
        </div>
        <table class="w-full text-left text-sm">
            <thead>
                <tr class="bg-[var(--table-header-bg)]">
                    <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Colaborador</th>
                    <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Trabalhos</th>
                    <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Páginas</th>
                    <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-right">Total</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-[var(--card-border)]">
                <?php foreach($resumo_usuarios as $ru): ?>
                <tr class="hover:bg-[var(--table-row-hover)] transition-colors group">
                    <td class="px-8 py-4">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-500 font-black text-[10px] uppercase">
                                <?= substr($ru['usuario'] ?? '?', 0, 2) ?>
                            </div>
                            <span class="font-black text-[var(--text-bold)] uppercase tracking-tight group-hover:text-indigo-400 transition-colors">
                                <?= htmlspecialchars($ru['usuario'] ?? 'N/A') ?>
                            </span>
                        </div>
                    </td>
                    <td class="px-8 py-4 text-center text-[var(--text-secondary)] font-bold"><?= $ru['total_trabalhos'] ?></td>
                    <td class="px-8 py-4 text-center font-black text-[var(--text-primary)] text-lg"><?= number_format($ru['total_paginas'], 0, ',', '.') ?></td>
                    <td class="px-8 py-4 text-right font-black text-emerald-500 text-base">R$ <?= number_format($ru['total_valor'], 2, ',', '.') ?></td>
                </tr>
                <?php endforeach; ?>
                <?php if(empty($resumo_usuarios)): ?>
                    <tr><td colspan="4" class="px-8 py-10 text-center text-[var(--text-muted)] italic">Nenhum consumo registrado neste período.</td></tr>
                <?php endif; ?>
            </tbody>
        </table>
    </div>

    <!-- Auditoria Detalhada -->
    <div class="glass-card rounded-3xl overflow-hidden mb-10">
        <div class="px-8 py-6 border-b border-[var(--card-border)]">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">📋 Auditoria Detalhada (Últimos 200 Registros)</h3>
            <p class="text-[10px] text-[var(--text-muted)] mt-1">Horários no fuso de Rondônia (UTC-4)</p>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-left text-sm border-collapse">
                <thead>
                    <tr class="bg-[var(--table-header-bg)]">
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Data</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Hora</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Tipo Doc</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Documento</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Colaborador</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Origem (Máquina/IP)</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Impressora</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Impressão</th>
                        <th class="px-6 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Págs</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-[var(--card-border)]">
                    <?php foreach($historico_detalhado as $hist): ?>
                    <tr class="hover:bg-[var(--table-row-hover)] transition-colors group">
                        <td class="px-6 py-4 font-black text-[var(--text-bold)] text-xs whitespace-nowrap"><?= $hist['data_formatada'] ?></td>
                        <td class="px-6 py-4 font-bold text-indigo-400 font-mono text-xs whitespace-nowrap"><?= $hist['hora_formatada'] ?></td>
                        <td class="px-6 py-4">
                            <?php $vis = getVisualInfo($hist['tipo_documento'] ?? 'Sistema'); ?>
                            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest <?= $vis['css'] ?>">
                                <?= $vis['icon'] ?> <?= htmlspecialchars($hist['tipo_documento'] ?? 'Sistema') ?>
                            </span>
                        </td>
                        <td class="px-6 py-4 text-[var(--text-bold)] font-bold break-words min-w-[200px]" title="<?= htmlspecialchars($hist['documento'] ?? '') ?>">
                            <?= htmlspecialchars($hist['documento'] ?? 'Sem Nome') ?>
                        </td>
                        <td class="px-6 py-4 font-bold text-[var(--text-secondary)] group-hover:text-indigo-400 transition-colors uppercase text-xs">
                            <?= htmlspecialchars($hist['usuario'] ?? 'N/A') ?>
                        </td>
                        <td class="px-6 py-4">
                            <div class="flex flex-col">
                                <span class="text-xs font-bold text-[var(--text-bold)]"><?= htmlspecialchars($hist['maquina'] ?? 'N/A') ?></span>
                                <span class="text-[9px] text-[var(--text-muted)] font-mono"><?= htmlspecialchars($hist['ip_maquina'] ?? '0.0.0.0') ?></span>
                            </div>
                        </td>
                        <td class="px-6 py-4 text-[var(--text-secondary)] text-xs">
                            <?= htmlspecialchars($hist['impressora_nome'] ?? 'Local / USB') ?>
                        </td>
                        <td class="px-6 py-4 text-center">
                            <span class="px-2 py-0.5 rounded text-[7px] font-black uppercase tracking-widest <?= $hist['tipo_impressao'] === 'Colorida' ? 'badge-cor' : 'badge-pb' ?>">
                                <?= $hist['tipo_impressao'] === 'Colorida' ? 'Cor' : 'P&B' ?>
                            </span>
                        </td>
                        <td class="px-6 py-4 text-center font-black text-[var(--text-primary)]"><?= $hist['paginas'] ?></td>
                    </tr>
                    <?php endforeach; ?>
                    <?php if(empty($historico_detalhado)): ?>
                        <tr><td colspan="7" class="px-8 py-10 text-center text-[var(--text-muted)] italic">Nenhum histórico encontrado para este período.</td></tr>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    const ctx = document.getElementById('evolucaoChart').getContext('2d');
    const evolucaoData = <?= json_encode($evolucao_diaria) ?>;
    
    const isDark = !document.documentElement.classList.contains('light-mode');
    const lineColor = '#6366f1';
    const textColor = isDark ? '#94a3b8' : '#475569';
    const gridColor = isDark ? 'rgba(51,65,85,0.4)' : 'rgba(203,213,225,0.6)';

    const gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, 'rgba(99, 102, 241, 0.35)');
    gradient.addColorStop(1, 'rgba(99, 102, 241, 0.0)');

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: evolucaoData.map(d => 'Dia ' + d.dia),
            datasets: [{
                label: 'Páginas Impressas',
                data: evolucaoData.map(d => d.paginas),
                borderColor: lineColor,
                backgroundColor: gradient,
                borderWidth: 3,
                pointBackgroundColor: lineColor,
                pointBorderColor: lineColor,
                pointRadius: 4,
                pointHoverRadius: 7,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: textColor } },
                x: { grid: { display: false }, ticks: { color: textColor } }
            }
        }
    });
</script>

<?php require_once 'includes/footer.php'; ?>
