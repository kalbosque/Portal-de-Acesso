<?php
require_once 'auth.php';
require_once 'db.php';

requireAdmin(); // Somente administradores acessam Equipamentos

// List available printers
$stmt = $pdo->query("SELECT * FROM impressoras ORDER BY nome ASC");
$printers = $stmt->fetchAll();

// Guess network prefix
$stmt = $pdo->query("SELECT ip FROM impressoras ORDER BY id DESC LIMIT 1");
$last_ip = $stmt->fetchColumn();

if ($last_ip) {
    $ip_parts = explode('.', $last_ip);
    array_pop($ip_parts);
    $guessed_prefix = implode('.', $ip_parts) . '.';
} else {
    $user_ip = $_SERVER['REMOTE_ADDR'];
    if (strpos($user_ip, '172.') === 0 || $user_ip === '::1' || $user_ip === '127.0.0.1') {
        $guessed_prefix = '192.168.1.';
    } else {
        $ip_parts = explode('.', $user_ip);
        if (count($ip_parts) === 4) {
            array_pop($ip_parts);
            $guessed_prefix = implode('.', $ip_parts) . '.';
        } else {
            $guessed_prefix = '192.168.1.';
        }
    }
}

require_once 'includes/config.php';
$pageTitle = 'Impressoras | ' . APP_NAME;
$hideChartJs = true;
require_once 'includes/header.php';
?>

<div class="mb-8 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
    <div class="flex items-center gap-4">
        <div class="p-3 bg-cyan-500/10 rounded-2xl border border-cyan-500/20 shadow-inner hidden sm:block">
            <svg class="w-8 h-8 text-cyan-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"></path></svg>
        </div>
        <div>
            <h2 class="text-3xl font-black text-[var(--text-primary)] mb-1 uppercase tracking-tighter">Gerenciar Impressoras</h2>
            <p class="text-[var(--text-secondary)] font-bold uppercase tracking-[0.3em] text-[10px] opacity-70">Escaneie a rede local ou adicione os equipamentos.</p>
        </div>
    </div>
</div>
<button id="btnAddManual" class="text-xs bg-indigo-600/20 hover:bg-indigo-600 border border-indigo-500/30 text-indigo-200 font-bold px-4 py-2 rounded-lg transition-all flex items-center gap-2" onclick="document.getElementById('formAdd').scrollIntoView({behavior:'smooth'});">Adicionar Impressora Manual</button>

<div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
    
    <!-- Coluna de Cadastro / Scan -->
    <div class="lg:col-span-1 space-y-6">
        
        <!-- Cadastro Manual -->
        <div class="glass-panel p-6 rounded-2xl relative overflow-hidden group">
            <div class="absolute -right-6 -top-6 w-24 h-24 bg-fuchsia-500/20 rounded-full blur-2xl group-hover:bg-fuchsia-500/30 transition duration-500"></div>
            
            <h2 class="text-lg font-bold text-slate-200 mb-4 flex items-center gap-2">
                <svg class="w-5 h-5 text-fuchsia-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                Cadastro Manual
            </h2>
            <form id="formAdd" class="space-y-4 relative z-10">
                <input type="hidden" id="csrf_token" name="csrf_token" value="<?= htmlspecialchars(getCsrfToken()) ?>">
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">Nome Identificador</label>
                    <input type="text" id="nome" name="nome" placeholder="Ex: Recepção principal" class="glass-input w-full px-4 py-2.5 rounded-xl text-white" required>
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">Endereço IP (Se for rede)</label>
                    <input type="text" id="ip" name="ip" placeholder="Ex: 192.168.1.50" class="glass-input w-full px-4 py-2.5 rounded-xl text-white" required>
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">Modelo do Equipamento</label>
                    <input type="text" id="modelo" name="modelo" placeholder="Ex: Lexmark MS415, HP LaserJet" class="glass-input w-full px-4 py-2.5 rounded-xl text-white">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">Setor / Localização Física</label>
                    <input type="text" id="localizacao" name="localizacao" placeholder="Ex: Bloco A, Sala 3" class="glass-input w-full px-4 py-2.5 rounded-xl text-white">
                </div>
                <button type="submit" class="w-full bg-gradient-to-r from-fuchsia-600 to-indigo-600 text-white font-bold py-3 rounded-xl hover:from-fuchsia-500 hover:to-indigo-500 transition-all shadow-lg shadow-fuchsia-500/25">Adicionar Impressora</button>
            </form>
        </div>

        <!-- Escaneamento de Rede -->
        <div class="glass-panel p-6 rounded-2xl relative overflow-hidden group">
            <div class="absolute -left-6 -bottom-6 w-32 h-32 bg-indigo-500/20 rounded-full blur-2xl group-hover:bg-indigo-500/30 transition duration-500"></div>
            
            <h2 class="text-lg font-bold text-slate-200 mb-2 flex items-center gap-2">
                <svg class="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                Escanear Rede
            </h2>
            <p class="text-xs text-slate-400 mb-4 leading-relaxed">Busque impressoras e computadores na rede local.</p>
            
            <div class="space-y-3 relative z-10">
                <div class="flex gap-2">
                    <input type="text" id="prefixo" value="<?= htmlspecialchars($guessed_prefix) ?>" placeholder="192.168.1." class="glass-input flex-grow px-3 py-2 rounded-xl text-center font-mono text-white tracking-widest">
                    <button id="btnScan" class="bg-indigo-600 text-white font-bold px-4 py-2 rounded-xl hover:bg-indigo-500 transition-all shadow-lg shadow-indigo-500/25">Escanear</button>
                </div>
                
                <button type="button" id="btnScanPCs" class="w-full bg-cyan-600 text-white font-bold py-2.5 rounded-xl hover:bg-cyan-500 transition-all shadow-lg shadow-cyan-500/25 flex items-center justify-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 002 2h2a2 2 0 002-2m0 0V5m0 10a2 2 0 00-2 2H9a2 2 0 00-2-2m0 0V5m0 10h12m0 0v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6m12 0V3a2 2 0 00-2-2H7a2 2 0 00-2 2v10"></path></svg>
                    Buscar PCs na Rede
                </button>
            </div>
            
            <div id="scanStatus" class="mt-5 hidden relative z-10">
                <div class="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                    <div id="scanProgress" class="h-full bg-indigo-500 transition-all duration-300 relative" style="width: 0%">
                        <div class="absolute top-0 left-0 w-full h-full bg-white/20 animate-pulse"></div>
                    </div>
                </div>
                <p id="currentIP" class="text-center text-[10px] text-indigo-300 mt-2 uppercase font-bold tracking-widest"></p>
            </div>
        </div>

    </div>

    <!-- Coluna de Lista -->
    <div class="lg:col-span-2 space-y-6">
        
            <div class="px-6 py-5 border-b border-slate-700/50 bg-slate-800/30 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                <div class="flex flex-col gap-1">
                    <h2 class="text-lg font-bold text-white flex items-center gap-2">
                        <svg class="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16"></path></svg>
                        Impressoras Cadastradas
                    </h2>
                    <input type="text" id="filtroImpressoras" placeholder="Buscar por nome, IP, setor..." class="glass-input text-xs px-3 py-1.5 rounded-lg text-white w-64 mt-1 border border-slate-600 focus:border-indigo-500 transition-all" oninput="filtrarTabelaImpressoras()">
                </div>
                <div class="flex gap-2">
                    <button id="btnSyncPrinters" class="text-xs bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-500/30 text-emerald-200 font-bold px-4 py-2 rounded-lg transition-all flex items-center gap-2" title="Importar impressoras detectadas no scan de rede">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                        Sincronizar Rede
                    </button>
                    <button id="btnRefreshAll" class="text-xs bg-indigo-600/20 hover:bg-indigo-600/40 border border-indigo-500/30 text-indigo-200 font-bold px-4 py-2 rounded-lg transition-all flex items-center gap-2">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                        Atualizar Status
                    </button>
                </div>
            </div>
            
            <div class="overflow-x-auto w-full flex-grow">
                <table class="w-full text-left border-collapse min-w-full" id="tabelaImpressoras">
                    <thead>
                        <tr class="bg-slate-800/50 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700/50">
                            <th class="px-6 py-4 font-semibold whitespace-nowrap">Nome</th>
                            <th class="px-6 py-4 font-semibold whitespace-nowrap">IP de Rede</th>
                            <th class="px-6 py-4 font-semibold whitespace-nowrap">Modelo</th>
                            <th class="px-6 py-4 font-semibold whitespace-nowrap">Localização / Setor</th>
                            <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Status</th>
                            <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Fonte</th>
                            <th class="px-6 py-4 font-semibold whitespace-nowrap w-[200px]">Toner</th>
                            <th class="px-6 py-4 font-semibold text-center whitespace-nowrap min-w-[140px]">Ações</th>
                        </tr>
                    </thead>
                    <tbody class="text-slate-300 text-sm">
                        <?php if (count($printers) > 0): ?>
                            <?php foreach ($printers as $p): ?>
                            <tr class="border-b border-slate-700/30 hover:bg-slate-800/40 transition duration-200 group printer-row" data-id="<?= $p['id'] ?>">
                                <td class="px-6 py-4">
                                    <!-- Modo visualização -->
                                    <span class="nome-view font-medium text-white group-hover:text-indigo-200 transition"><?= htmlspecialchars($p['nome']) ?></span>
                                    <!-- Modo edição -->
                                    <input type="text" class="nome-edit hidden glass-input px-3 py-1.5 rounded-lg text-sm w-full" value="<?= htmlspecialchars($p['nome']) ?>">
                                </td>
                                <td class="px-6 py-4 font-mono text-slate-400"><?= htmlspecialchars($p['ip']) ?: '-' ?></td>
                                <td class="px-6 py-4">
                                    <!-- Modo visualização -->
                                    <span class="modelo-view text-slate-300"><?= htmlspecialchars($p['modelo'] ?? 'Não informado') ?></span>
                                    <!-- Modo edição -->
                                    <input type="text" class="modelo-edit hidden glass-input px-3 py-1.5 rounded-lg text-sm w-full" value="<?= htmlspecialchars($p['modelo'] ?? '') ?>">
                                </td>
                                <td class="px-6 py-4">
                                    <!-- Modo visualização -->
                                    <span class="localizacao-view text-slate-300"><?= htmlspecialchars($p['localizacao'] ?? 'Não informado') ?></span>
                                    <!-- Modo edição -->
                                    <input type="text" class="localizacao-edit hidden glass-input px-3 py-1.5 rounded-lg text-sm w-full" value="<?= htmlspecialchars($p['localizacao'] ?? '') ?>">
                                </td>
                                <td class="px-6 py-4 text-center">
                                    <?php
                                        if ($p['status'] === 'Online') {
                                            $badgeClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
                                        } elseif ($p['status'] === 'Offline') {
                                            $badgeClass = 'bg-rose-500/10 text-rose-400 border-rose-500/20';
                                        } else {
                                            $badgeClass = 'bg-slate-700/50 text-slate-400 border-slate-600/50';
                                        }
                                    ?>
                                    <span class="px-3 py-1 rounded-full text-xs font-bold tracking-wide border inline-block <?= $badgeClass ?>">
                                        <?= $p['status'] ?>
                                    </span>
                                </td>
                                <td class="px-6 py-4 text-center">
                                    <span class="inline-block px-2 py-1 rounded-full text-[10px] font-black uppercase tracking-widest bg-slate-700/40 text-slate-200 border border-slate-600">
                                        <?= htmlspecialchars($p['fonte_status'] ?? 'Manual') ?>
                                    </span>
                                </td>
                                <td class="px-6 py-4 toner-cell text-center" style="width: 180px; min-width: 180px;" data-ip="<?= htmlspecialchars($p['ip']) ?>">
                                    <div class="h-2 w-full bg-slate-800/50 rounded-full overflow-hidden flex items-center relative border border-slate-700/30">
                                        <div class="toner-bar h-full bg-slate-500 w-0 transition-all duration-1000 relative">
                                            <div class="absolute inset-0 bg-white/20 animate-[pulse_2s_ease-in-out_infinite]"></div>
                                        </div>
                                    </div>
                                    <p class="toner-text text-[9px] text-slate-500 mt-1.5 font-black uppercase tracking-widest leading-none">CARREGANDO...</p>
                                </td>
                                <td class="px-6 py-4 text-center">
                                    <!-- Botões modo normal -->
                                    <div class="acoes-normal flex items-center justify-center gap-4">
                                        <button class="text-slate-400 hover:text-indigo-400 transition transform hover:scale-110" title="Editar nome" onclick="startEdit(this.closest('tr'))">
                                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                                        </button>
                                        <button class="text-slate-400 hover:text-rose-400 transition transform hover:scale-110" title="Excluir equipamento" onclick="removePrinter(<?= $p['id'] ?>)">
                                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                        </button>
                                    </div>
                                    <!-- Botões modo edição -->
                                    <div class="acoes-edit hidden flex items-center justify-center gap-2">
                                        <button class="bg-indigo-600 text-white text-xs font-bold px-3 py-1.5 rounded-md hover:bg-indigo-500 transition" onclick="saveName(this.closest('tr'), <?= $p['id'] ?>)">Salvar</button>
                                        <button class="bg-slate-700 text-slate-300 text-xs font-bold px-3 py-1.5 rounded-md hover:bg-slate-600 transition" onclick="cancelEdit(this.closest('tr'))">Cancelar</button>
                                    </div>
                                </td>
                            </tr>
                            <?php endforeach; ?>
                        <?php else: ?>
                            <tr>
                                <td colspan="8" class="px-6 py-12 text-center">
                                    <div class="flex flex-col items-center justify-center text-slate-500">
                                        <svg class="w-12 h-12 mb-3 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"></path></svg>
                                        <p>Nenhuma impressora monitorada ainda.</p>
                                    </div>
                                </td>
                            </tr>
                        <?php endif; ?>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Resultados do Scan -->
        <div id="scanResults" class="hidden">
            <h3 class="text-sm font-bold text-slate-400 uppercase tracking-widest mb-3 pl-2 border-l-2 border-indigo-500">Descobertos na Rede</h3>
            <div id="scanList" class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <!-- Itens injetados via JS -->
            </div>
        </div>

    </div>
</div>

<!-- Seção de Máquinas/Computadores da Rede -->
<div class="mt-12">
    <div class="mb-4 text-center sm:text-left">
        <h2 class="text-3xl font-bold text-white mb-1">Monitoramento de Máquinas da Rede</h2>
        <p class="text-slate-400">Visualize todos os computadores conectados e os usuários ativos.</p>
    </div>

    <div class="glass-panel rounded-2xl overflow-hidden flex flex-col">
        <div class="px-6 py-5 border-b border-slate-700/50 bg-slate-800/30 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
            <div>
                <h2 class="text-lg font-bold text-white flex items-center gap-2">
                    <svg class="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 002 2h2a2 2 0 002-2m0 0V5m0 10a2 2 0 00-2 2H9a2 2 0 00-2-2m0 0V5m0 10h12m0 0v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6m12 0V3a2 2 0 00-2-2H7a2 2 0 00-2 2v10"></path></svg>
                    Máquinas da Rede
                </h2>
                <p class="text-xs text-slate-400 mt-1">Online e Offline - Atualiza a cada 5 segundos</p>
            </div>
            <div class="flex items-center gap-2">
                <div id="staleWarning" class="hidden text-xs bg-amber-500/10 border border-amber-500/30 text-amber-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5">
                    <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"></path></svg>
                    <span id="staleWarningText">Dados desatualizados</span>
                </div>
                <button id="btnRefreshMachines" class="text-xs bg-cyan-600/20 hover:bg-cyan-600/40 border border-cyan-500/30 text-cyan-200 font-bold px-4 py-2 rounded-lg transition-all flex items-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                    Atualizar
                </button>
            </div>
        </div>
        
        <div class="overflow-x-auto w-full flex-grow">
            <table class="w-full text-left border-collapse min-w-full">
                <thead>
                    <tr class="bg-slate-800/50 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700/50">
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Máquina</th>
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">IP</th>
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Usuário</th>
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Status</th>
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Fonte</th>
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Última Ação</th>
                        <th class="px-6 py-4 font-semibold whitespace-nowrap text-center">Impressões</th>
                    </tr>
                </thead>
                <tbody class="text-slate-300 text-sm" id="machinesTableBody">
                    <tr>
                        <td colspan="6" class="px-6 py-12 text-center text-slate-500">
                            <div class="flex flex-col items-center justify-center">
                                <svg class="w-12 h-12 mb-3 text-slate-600 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                <p>Carregando máquinas...</p>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    // Cadastro manual
    document.getElementById('formAdd').addEventListener('submit', function(e) {
        e.preventDefault();
        const nome = document.getElementById('nome').value;
        const ip = document.getElementById('ip').value;
        const modelo = document.getElementById('modelo').value;
        const localizacao = document.getElementById('localizacao').value;
        const csrf_token = document.getElementById('csrf_token').value;

        if (!nome || !ip) return alert('Preecha tudo!');

        fetch('api_impressoras.php?action=add_printer', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({nome, ip, modelo, localizacao, csrf_token})
        }).then(r => r.json()).then(res => {
            if(res.success) location.reload();
            else alert('Erro: ' + res.error);
        });
    });

    // Atualizar todos os status
    document.getElementById('btnRefreshAll').addEventListener('click', function() {
        const btn = this;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="animate-pulse">Verificando...</span>';
        btn.disabled = true;
        fetch('api_impressoras.php?action=check_all')
            .then(r => r.json())
            .then(res => {
                if(res.success) location.reload();
                else { alert('Erro no check'); btn.disabled = false; btn.innerHTML = originalText; }
            });
    });

    // Sincronizar impressoras da rede
    document.getElementById('btnSyncPrinters').addEventListener('click', function() {
        const btn = this;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="animate-pulse">Sincronizando...</span>';
        btn.disabled = true;
        
        const csrf = document.getElementById('csrf_token').value;
        fetch(`api_impressoras.php?action=sync_network_printers&csrf_token=${encodeURIComponent(csrf)}`)
            .then(r => r.json())
            .then(res => {
                if(res.success) {
                    alert(res.added + ' impressoras sincronizadas!');
                    location.reload();
                } else { 
                    alert('Erro: ' + res.error); 
                    btn.disabled = false; 
                    btn.innerHTML = originalText; 
                }
            }).catch(e => {
                alert('Erro de conexao');
                btn.disabled = false;
                btn.innerHTML = originalText;
            });
    });

    // Scanner de Rede
    document.getElementById('btnScan').addEventListener('click', async function() {
        const prefix = document.getElementById('prefixo').value;
        if (!prefix) return;
        
        const btn = this;
        btn.disabled = true;
        document.getElementById('scanStatus').classList.remove('hidden');
        document.getElementById('scanList').innerHTML = '';
        document.getElementById('scanResults').classList.add('hidden');

        const bar = document.getElementById('scanProgress');
        const currentLabel = document.getElementById('currentIP');

        for (let i = 1; i <= 254; i++) {
            const ip = `${prefix}.${i}`;
            currentLabel.innerText = `Pingando: ${ip}`;
            bar.style.width = `${(i/254)*100}%`;

            try {
                const res = await fetch(`api_impressoras.php?action=scan_ip&ip=${ip}`).then(r=>r.json());
                if (res.online) {
                    document.getElementById('scanResults').classList.remove('hidden');
                    addScanResult(res);
                }
            } catch(e) {}
        }

        btn.disabled = false;
        currentLabel.innerText = 'Varredura ConcluÃƒÂ­da!';
        setTimeout(() => { document.getElementById('scanStatus').classList.add('hidden'); }, 3000);
    });

    // Buscar PCs na Rede
    document.getElementById('btnScanPCs').addEventListener('click', async function() {
        const prefix = document.getElementById('prefixo').value;
        if (!prefix) {
            alert('Digite o prefixo da rede (ex: 192.168.1.)');
            return;
        }
        
        const btn = this;
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<div class="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></div> Buscando...';
        
        document.getElementById('scanStatus').classList.remove('hidden');
        document.getElementById('scanList').innerHTML = '';
        document.getElementById('scanResults').classList.add('hidden');

        const bar = document.getElementById('scanProgress');
        const currentLabel = document.getElementById('currentIP');

        try {
            currentLabel.innerText = 'Buscando PCs na rede...';
            bar.style.width = '10%';

            // Chama API para escanear PCs
            const res = await fetch(`api_impressoras.php?action=scan_pcs&prefix=${encodeURIComponent(prefix)}`).then(r => r.json());
            
            bar.style.width = '50%';
            currentLabel.innerText = 'Processando resultados...';

            if (res.success && res.devices && res.devices.length > 0) {
                document.getElementById('scanResults').classList.remove('hidden');
                
                res.devices.forEach(device => {
                    addPCResult(device);
                });
                
                bar.style.width = '100%';
                currentLabel.innerText = `${res.devices.length} PCs encontrados!`;
            } else {
                document.getElementById('scanResults').classList.remove('hidden');
                document.getElementById('scanList').innerHTML = `
                    <div class="glass-panel p-6 rounded-xl text-center text-slate-300">
                        Nenhum dispositivo encontrado no prefixo <strong>${prefix}</strong>.
                        Verifique se as mÃƒÂ¡quinas estÃƒÂ£o na mesma sub-rede e se respondem a ping.
                    </div>
                `;
                bar.style.width = '100%';
                currentLabel.innerText = 'Nenhum PC encontrado na rede';
            }
        } catch(e) {
            console.error('Erro ao buscar PCs:', e);
            document.getElementById('scanResults').classList.remove('hidden');
            document.getElementById('scanList').innerHTML = `
                <div class="glass-panel p-6 rounded-xl text-center text-slate-300">
                    Ocorreu um erro ao buscar PCs na rede.<br>
                    Verifique o prefixo e tente novamente.
                </div>
            `;
            currentLabel.innerText = 'Erro na busca';
        }

        btn.disabled = false;
        btn.innerHTML = originalText;
        setTimeout(() => { 
            document.getElementById('scanStatus').classList.add('hidden'); 
        }, 3000);
    });

    function addScanResult(device) {
        const list = document.getElementById('scanList');
        const div = document.createElement('div');
        div.className = 'glass-panel p-4 rounded-xl flex justify-between items-center transition hover:border-indigo-500/50 group';
        div.innerHTML = `
            <div>
                <h4 class="font-bold text-white text-sm group-hover:text-indigo-300 transition">${device.device_name}</h4>
                <div class="flex items-center gap-2 mt-1">
                    <span class="w-2 h-2 rounded-full ${device.is_printer ? 'bg-emerald-400' : 'bg-slate-500'}"></span>
                    <p class="text-xs font-mono text-slate-400">${device.ip} ${device.is_printer ? '(Impressora Detectada)' : ''}</p>
                </div>
            </div>
            <button onclick="quickAdd('${device.device_name}', '${device.ip}')" class="bg-indigo-600/20 hover:bg-indigo-600 border border-indigo-500/30 text-indigo-200 hover:text-white text-[10px] uppercase font-bold py-1.5 px-3 rounded-lg transition">Monitorar</button>
        `;
        list.appendChild(div);
    }

    function addMachine(nome, ip) {
        // Preenche o formulÃƒÂ¡rio de cadastro com os dados do PC
        document.getElementById('nome').value = nome;
        document.getElementById('ip').value = ip;
        
        // Scroll para o formulÃƒÂ¡rio
        document.getElementById('formAdd').scrollIntoView({behavior: 'smooth', block: 'center'});
        
        // Destaque visual
        const formDiv = document.getElementById('formAdd').parentElement;
        formDiv.classList.add('border-cyan-500');
        setTimeout(() => formDiv.classList.remove('border-cyan-500'), 1500);
        
        // Feedback visual
        alert(`PC "${nome}" adicionado ao formulÃƒÂ¡rio. Clique em "Adicionar Impressora" para cadastrar.`);
    }

    function addPCResult(device) {
        const list = document.getElementById('scanList');
        const div = document.createElement('div');
        div.className = 'glass-panel p-4 rounded-xl flex justify-between items-center transition hover:border-cyan-500/50 group';
        div.innerHTML = `
            <div>
                <h4 class="font-bold text-white text-sm group-hover:text-cyan-300 transition">${device.hostname || device.ip}</h4>
                <div class="flex items-center gap-2 mt-1">
                    <span class="w-2 h-2 rounded-full bg-cyan-400"></span>
                    <p class="text-xs font-mono text-slate-400">${device.ip} (Computador)</p>
                </div>
                ${device.mac ? `<p class="text-xs text-slate-500 mt-1">MAC: ${device.mac}</p>` : ''}
            </div>
            <button onclick="addMachine('${device.hostname || device.ip}', '${device.ip}')" class="bg-cyan-600/20 hover:bg-cyan-600 border border-cyan-500/30 text-cyan-200 hover:text-white text-[10px] uppercase font-bold py-1.5 px-3 rounded-lg transition">Monitorar PC</button>
        `;
        list.appendChild(div);
    }

    function quickAdd(nome, ip) {
        document.getElementById('nome').value = nome;
        document.getElementById('ip').value = ip;
        // visual scroll to form
        document.getElementById('formAdd').scrollIntoView({behavior: 'smooth', block: 'center'});
        // pulse form highlight
        const formDiv = document.getElementById('formAdd').parentElement;
        formDiv.classList.add('border-indigo-500');
        setTimeout(()=> formDiv.classList.remove('border-indigo-500'), 1500);
    }

    // TESTE: Carregar dados hardcoded primeiro - VERSÃƒÆ’O SIMPLIFICADA
    function loadMachinesHardcoded() {
        console.log('[Machine Monitor] Ã°Å¸â€Â§ Carregando dados hardcoded...');

        const tbody = document.getElementById('machinesTableBody');
        if (!tbody) {
            console.error('[Machine Monitor] âÂÅ’ tbody nÃƒÂ£o encontrado');
            return;
        }

        // Dados simples para teste
        const machines = [
            { nome_maquina: 'SERVIDOR-XML', usuario: 'TESTE', status: 'Online', ultima_acao: 'Agora', total_impressoes: 5 },
            { nome_maquina: 'SERVER-EMAIL', usuario: 'ADMIN', status: 'Online', ultima_acao: '5 min', total_impressoes: 3 }
        ];

        console.log('[Machine Monitor] âÅ“â€œ Renderizando', machines.length, 'mÃƒÂ¡quinas');

        tbody.innerHTML = '';

        machines.forEach(machine => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td class="px-6 py-4 text-white">${machine.nome_maquina}</td>
                <td class="px-6 py-4">${machine.usuario}</td>
                <td class="px-6 py-4 text-center"><span class="text-green-400">${machine.status}</span></td>
                <td class="px-6 py-4 text-slate-400">${machine.ultima_acao}</td>
                <td class="px-6 py-4 text-center">${machine.total_impressoes}</td>
            `;
            tbody.appendChild(row);
        });

        console.log('[Machine Monitor] âÅ“â€œ Dados hardcoded carregados com sucesso!');
    }

    async function loadMachines() {
        console.log('[Machine Monitor] âÂÂ³ Tentando carregar da API...');

        try {
            const response = await fetch('api_impressoras.php?action=get_machines', {
                method: 'GET',
                cache: 'no-cache',
                headers: {
                    'Cache-Control': 'no-cache'
                }
            });

            console.log('[Machine Monitor] Status HTTP:', response.status);

            if (!response.ok) {
                console.log('[Machine Monitor] âÅ¡Â Ã¯Â¸Â HTTP erro, mantendo dados atuais');
                return;
            }

            const text = await response.text();
            console.log('[Machine Monitor] Resposta recebida, tamanho:', text.length);

            if (text.includes('<html>') || text.includes('<body>')) {
                console.log('[Machine Monitor] âÅ¡Â Ã¯Â¸Â Resposta ÃƒÂ© HTML, mantendo dados atuais');
                return;
            }

            const data = JSON.parse(text);
            console.log('[Machine Monitor] âÅ“â€œ JSON parseado:', data);

            if (data.success && data.machines && data.machines.length > 0) {
                console.log('[Machine Monitor] âÅ“â€œ API funcionou! Carregando dados reais...');
                renderMachinesTable(data.machines);
            } else {
                console.log('[Machine Monitor] âÅ¡Â Ã¯Â¸Â API retornou dados vazios');
            }
        } catch (e) {
            console.log('[Machine Monitor] âÅ¡Â Ã¯Â¸Â Erro na API:', e.message);
        }
    }
    
    function showApiError(message) {
        let errorDiv = document.getElementById('machineApiError');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.id = 'machineApiError';
            const tbody = document.getElementById('machinesTableBody');
            tbody.parentElement.insertBefore(errorDiv, tbody);
        }
        errorDiv.className = 'px-6 py-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-300 text-sm';
        errorDiv.textContent = 'âÅ¡Â Ã¯Â¸Â ' + message;
    }
    
    function clearApiError() {
        const errorDiv = document.getElementById('machineApiError');
        if (errorDiv) errorDiv.remove();
    }

    // Funções de Renderização unificadas (Versão 6 colunas)

    function startEditUser(td) {
        window.isEditingUser = true;
        td.querySelector('.user-view').classList.add('hidden');
        td.querySelector('.user-edit').classList.remove('hidden');
        td.querySelector('input').focus();
    }

    function cancelEditUser(td) {
        window.isEditingUser = false;
        td.querySelector('.user-view').classList.remove('hidden');
        td.querySelector('.user-edit').classList.add('hidden');
        // revert input
        td.querySelector('input').value = td.querySelector('.user-view span').textContent.trim();
    }

    async function saveUserAlias(td, maquinaNome) {
        const novoUsuario = td.querySelector('input').value.trim();
        
        td.style.opacity = '0.5';
        try {
            const res = await fetch('api_impressoras.php?action=set_machine_alias', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ maquina: maquinaNome, usuario: novoUsuario })
            }).then(r => r.json());
            
            td.style.opacity = '1';
            window.isEditingUser = false;
            
            if (res.success) {
                // Refresh table completely to show new data
                loadMachines();
            } else {
                alert('Erro ao salvar usuário: ' + (res.error || 'Erro desconhecido'));
                cancelEditUser(td);
            }
        } catch (e) {
            td.style.opacity = '1';
            window.isEditingUser = false;
            alert('Erro de conexão ao salvar usuário.');
            cancelEditUser(td);
        }
    }

    function renderEmptyMachines() {
        const tbody = document.getElementById('machinesTableBody');
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="px-6 py-12 text-center">
                    <div class="flex flex-col items-center justify-center text-slate-500">
                        <svg class="w-12 h-12 mb-3 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 17V7m0 10a2 2 0 002 2h2a2 2 0 002-2m0 0V5m0 10a2 2 0 00-2 2H9a2 2 0 00-2-2m0 0V5m0 10h12m0 0v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6m12 0V3a2 2 0 00-2-2H7a2 2 0 00-2 2v10"></path></svg>
                        <p>Nenhuma máquina monitorada ainda.</p>
                        <p class="text-xs mt-2">Máquinas aparecerão aqui quando começarem a imprimir.</p>
                        <p class="text-xs mt-1 text-slate-600">Máquinas offline continuam visíveis na lista para referência.</p>
                    </div>
                </td>
            </tr>
        `;
    }

    function getRelativeTime(minutes) {
        minutes = parseInt(minutes, 10) || 0;
        if (isNaN(minutes) || minutes < 0) return 'Desconhecido';
        if (minutes === 0) return 'Agora';
        if (minutes < 60) return `${minutes}m atras`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h atras`;
        const days = Math.floor(hours / 24);
        if (days < 365) return `${days}d atras`;
        const years = Math.floor(days / 365);
        return `${years}a atras`;
    }

    function escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }

    // BotÃƒÂ£o para atualizar mÃƒÂ¡quinas
    document.getElementById('btnRefreshMachines').addEventListener('click', function() {
        const btn = this;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="animate-pulse">Atualizando...</span>';
        
        setTimeout(() => {
            loadMachines();
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }, 1000);
    });

    async function removePrinter(id) {
        if(!confirm('Deseja excluir permanentemente este equipamento e parar o monitoramento?')) return;
        try {
            const csrf = document.getElementById('csrf_token').value;
            const res = await fetch(`api_impressoras.php?action=delete_printer&id=${id}&csrf_token=${encodeURIComponent(csrf)}`).then(r=>r.json());
            if (res.success) {
                const tr = document.querySelector(`tr[data-id="${id}"]`);
                tr.style.opacity = '0';
                tr.style.transform = 'translateX(20px)';
                setTimeout(() => location.reload(), 300);
            } else {
                alert('Erro ao excluir: ' + (res.error || 'Erro desconhecido'));
            }
        } catch (e) {
            alert('Erro de conexão com o servidor.');
        }
    }

    function startEdit(row) {
        row.querySelector('.nome-view').classList.add('hidden');
        row.querySelector('.nome-edit').classList.remove('hidden');
        row.querySelector('.modelo-view').classList.add('hidden');
        row.querySelector('.modelo-edit').classList.remove('hidden');
        row.querySelector('.localizacao-view').classList.add('hidden');
        row.querySelector('.localizacao-edit').classList.remove('hidden');
        row.querySelector('.nome-edit').focus();
        row.querySelector('.acoes-normal').classList.add('hidden');
        row.querySelector('.acoes-edit').classList.remove('hidden');
    }

    function cancelEdit(row) {
        row.querySelector('.nome-view').classList.remove('hidden');
        row.querySelector('.nome-edit').classList.add('hidden');
        row.querySelector('.nome-edit').value = row.querySelector('.nome-view').textContent.trim();
        row.querySelector('.modelo-view').classList.remove('hidden');
        row.querySelector('.modelo-edit').classList.add('hidden');
        row.querySelector('.modelo-edit').value = row.querySelector('.modelo-view').textContent.trim() === 'Não informado' ? '' : row.querySelector('.modelo-view').textContent.trim();
        row.querySelector('.localizacao-view').classList.remove('hidden');
        row.querySelector('.localizacao-edit').classList.add('hidden');
        row.querySelector('.localizacao-edit').value = row.querySelector('.localizacao-view').textContent.trim() === 'Não informado' ? '' : row.querySelector('.localizacao-view').textContent.trim();
        row.querySelector('.acoes-normal').classList.remove('hidden');
        row.querySelector('.acoes-edit').classList.add('hidden');
    }

    async function saveName(row, id) {
        const novoNome = row.querySelector('.nome-edit').value.trim();
        const novoModelo = row.querySelector('.modelo-edit').value.trim();
        const novaLocalizacao = row.querySelector('.localizacao-edit').value.trim();
        const csrf_token = document.getElementById('csrf_token').value;
        if (!novoNome) return alert('O nome não pode ficar em branco.');
        
        row.style.opacity='0.5';
        try {
            const res = await fetch('api_impressoras.php?action=update_name', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id, nome: novoNome, modelo: novoModelo, localizacao: novaLocalizacao, csrf_token})
            }).then(r => r.json());
            
            row.style.opacity='1';
            if (res.success) {
                row.querySelector('.nome-view').textContent = novoNome;
                row.querySelector('.modelo-view').textContent = novoModelo || 'Não informado';
                row.querySelector('.localizacao-view').textContent = novaLocalizacao || 'Não informado';
                cancelEdit(row);
            } else {
                alert('Erro ao salvar: ' + (res.error || 'Erro desconhecido'));
            }
        } catch (e) {
            row.style.opacity='1';
            alert('Erro de conexão com o servidor.');
        }
    }

    // --- Monitoramento de Toner SNMP ---
    function loadTonerLevels() {
        const cells = document.querySelectorAll('.toner-cell');
        cells.forEach(cell => {
            const ip = cell.getAttribute('data-ip');
            if (!ip || ip === '' || ip === '-') {
                updateTonerUI(cell, null, 'N/A');
                return;
            }

            fetch(`api_impressoras.php?action=get_toner_level&ip=${ip}`)
                .then(r => r.json())
                .then(res => {
                    if (res.success && res.toner !== null) {
                        updateTonerUI(cell, res.toner, res.toner + '%');
                    } else {
                        const reason = res.reason || 'N/A';
                        updateTonerUI(cell, null, reason);
                        if (res.reason) console.warn(`Toner IP ${ip}: ${res.reason}`);
                    }
                })
                .catch(err => {
                    updateTonerUI(cell, null, 'ERRO');
                    console.error(`Falha ao buscar toner ${ip}:`, err);
                });
        });
    }

    function updateTonerUI(cell, percentage, text) {
        const bar = cell.querySelector('.toner-bar');
        const p = cell.querySelector('.toner-text');
        
        // Remove animation element if it exists
        const pulse = bar.querySelector('div');
        if(pulse) pulse.remove();

        p.textContent = text;
        
        if (percentage === null) {
            bar.style.width = '100%';
            bar.className = 'toner-bar h-full bg-slate-600 transition-all duration-1000';
            p.className = 'toner-text text-[10px] text-slate-500 mt-1.5 font-bold tracking-widest text-center';
        } else if (percentage === 'OK') {
            bar.style.width = '100%';
            bar.className = 'toner-bar h-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)] transition-all duration-1000';
            p.className = 'toner-text text-[10px] text-emerald-400 mt-1.5 font-black tracking-widest text-center';
            p.textContent = 'TONER OK';
        } else {
            bar.style.width = percentage + '%';
            if (percentage <= 20) {
                bar.className = 'toner-bar h-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.5)] transition-all duration-1000';
                p.className = 'toner-text text-[10px] text-rose-400 mt-1.5 font-black tracking-widest text-center';
            } else {
                bar.className = 'toner-bar h-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)] transition-all duration-1000';
                p.className = 'toner-text text-[10px] text-emerald-400 mt-1.5 font-black tracking-widest text-center';
            }
        }
    }

    document.addEventListener('DOMContentLoaded', loadTonerLevels);

    // --- Fim Monitoramento Toner ---

    function loadMachinesHardcoded() {
        return;
    }

    async function loadMachines() {
        try {
            const response = await fetch('api_impressoras.php?action=get_machines', {
                method: 'GET',
                cache: 'no-cache',
                headers: {
                    'Cache-Control': 'no-cache'
                }
            });

            if (!response.ok) {
                showApiError('Nao foi possivel consultar o status atual dos PCs.');
                return false;
            }

            const data = await response.json();
            if (!data.success) {
                showApiError(data.error || 'A API nao retornou dados validos.');
                return false;
            }

            clearApiError();

            // Aviso de dados desatualizados
            const staleWarning = document.getElementById('staleWarning');
            const staleText = document.getElementById('staleWarningText');
            if (data.data_stale && staleWarning) {
                const age = data.stale_age_min ? `há ${data.stale_age_min} min` : '';
                staleText.textContent = `Monitor de rede parado ${age} — verificando via ping`;
                staleWarning.classList.remove('hidden');
            } else if (staleWarning) {
                staleWarning.classList.add('hidden');
            }

            if (Array.isArray(data.machines) && data.machines.length > 0) {
                if (!window.isEditingUser) {
                    renderMachinesTable(data.machines);
                }
            } else {
                if (!window.isEditingUser) {
                    renderEmptyMachines();
                }
            }

            return !!data.data_stale;
        } catch (e) {
            showApiError('Erro ao atualizar monitor em tempo real: ' + e.message);
            return false;
        }
    }

    function getRelativeTime(minutes) {
        minutes = parseInt(minutes, 10);
        if (Number.isNaN(minutes) || minutes < 0) return 'Desconhecido';
        if (minutes === 0) return 'Agora';
        if (minutes < 60) return `${minutes}m atras`;
        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours}h atras`;
        const days = Math.floor(hours / 24);
        if (days < 365) return `${days}d atras`;
        const years = Math.floor(days / 365);
        return `${years}a atras`;
    }

    function getMachineTimeText(machine) {
        if (machine.minutos_ago !== null && machine.minutos_ago !== undefined) {
            return getRelativeTime(machine.minutos_ago);
        }
        if (machine.ultima_verificacao) {
            return `Verificado ${machine.ultima_verificacao}`;
        }
        if (machine.ultima_acao) {
            return machine.ultima_acao;
        }
        return 'Sem dados';
    }

    function escapeHtml(text) {
        text = String(text ?? '');
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }

    function renderMachinesTable(machines) {
        const tbody = document.getElementById('machinesTableBody');
        if (!tbody) return;
        tbody.innerHTML = '';

        const online = machines.filter(m => m.status === 'Online');
        const offline = machines.filter(m => m.status === 'Offline');
        const unknown = machines.filter(m => !['Online', 'Offline'].includes(m.status));
        const sorted = [...online, ...unknown, ...offline];

        if (sorted.length === 0) {
            renderEmptyMachines();
            return;
        }

        sorted.forEach((machine, index) => {
            if (index === online.length && online.length > 0 && (unknown.length > 0 || offline.length > 0)) {
                const sep = document.createElement('tr');
                sep.className = 'bg-slate-800/20';
                sep.innerHTML = `<td colspan="7" class="px-6 py-3"><div class="text-[10px] text-slate-500 font-black uppercase tracking-widest">--- MÁQUINAS OFFLINE / OUTROS ---</div></td>`;
                tbody.appendChild(sep);
            }

            const row = document.createElement('tr');
            row.className = 'border-b border-slate-700/30 hover:bg-slate-800/40 transition duration-200 group';
            if (machine.status === 'Offline') row.classList.add('opacity-75');

            const statusClass = machine.status === 'Online'
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : machine.status === 'Offline'
                    ? 'bg-slate-500/10 text-slate-400 border-slate-500/20'
                    : 'bg-amber-500/10 text-amber-300 border-amber-500/20';

            const statusIcon = machine.status === 'Online'
                ? '<span class="inline-block w-2 h-2 rounded-full bg-emerald-400 mr-2 animate-pulse"></span>'
                : '<span class="inline-block w-2 h-2 rounded-full bg-slate-500 mr-2"></span>';

            const timeText = getMachineTimeText(machine);
            const timeTitle = machine.ultima_acao || machine.ultima_verificacao || 'Sem dados';

            row.innerHTML = `
                <td class="px-6 py-4 font-bold text-white text-center">${escapeHtml(machine.nome_maquina)}</td>
                <td class="px-6 py-4 font-mono text-xs text-slate-400 text-center">${escapeHtml(machine.ip || '-')}</td>
                <td class="px-6 py-4 group/user text-center">
                    <div class="user-view flex items-center justify-center gap-2">
                        <span class="inline-block px-3 py-1 rounded-full text-xs font-semibold ${machine.has_alias ? 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30' : 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30'} border">
                            ${escapeHtml(machine.usuario || 'N/A')}
                        </span>
                        <button onclick="startEditUser(this.closest('td'))" class="text-slate-500 hover:text-indigo-400 opacity-0 group-hover/user:opacity-100 transition" title="Alterar Usuário">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                        </button>
                    </div>
                    <div class="user-edit hidden flex items-center justify-center gap-1">
                        <input type="text" class="glass-input px-2 py-1 rounded text-xs w-24 text-white" value="${escapeHtml(machine.usuario || '')}">
                        <button onclick="saveUserAlias(this.closest('td'), '${escapeHtml(machine.nome_maquina)}')" class="text-emerald-400 hover:text-emerald-300 p-1">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                        </button>
                        <button onclick="cancelEditUser(this.closest('td'))" class="text-rose-400 hover:text-rose-300 p-1">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    </div>
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border inline-flex items-center ${statusClass}">
                        ${statusIcon} ${machine.status || 'Offline'}
                    </span>
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="inline-block px-2 py-1 rounded-full text-[10px] font-black uppercase tracking-widest bg-slate-700/40 text-slate-200 border border-slate-600">
                        ${escapeHtml(machine.fonte_status || 'n/a')}
                    </span>
                </td>
                <td class="px-6 py-4 text-xs text-slate-400 italic text-center">
                    <span title="${escapeHtml(timeTitle)}">${escapeHtml(timeText)}</span>
                </td>
                <td class="px-6 py-4 text-center">
                    <span class="inline-block px-2 py-1 rounded bg-slate-700/50 text-indigo-400 font-black text-sm">${machine.total_impressoes || 0}</span>
                </td>
            `;
            tbody.appendChild(row);
        });
    }

    window.isEditingUser = false;

    // Função de filtragem de impressoras em tempo real
    function filtrarTabelaImpressoras() {
        const termo = document.getElementById('filtroImpressoras').value.toLowerCase();
        const linhas = document.querySelectorAll('.printer-row');
        linhas.forEach(linha => {
            const texto = linha.textContent.toLowerCase();
            if (texto.includes(termo)) {
                linha.style.display = '';
            } else {
                linha.style.display = 'none';
            }
        });
    }

    // Polling adaptativo: 5s quando monitor está ativo, 60s quando usando live_ping
    let _pollTimer = null;
    function schedulePoll(stale) {
        if (_pollTimer) clearTimeout(_pollTimer);
        const delay = stale ? 60000 : 5000;
        _pollTimer = setTimeout(pollMachines, delay);
    }
    async function pollMachines() {
        const stale = await loadMachines();
        schedulePoll(stale);
    }

    pollMachines();
</script>

<?php require_once 'includes/footer.php'; ?>

