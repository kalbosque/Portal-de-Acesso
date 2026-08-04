<?php
require_once 'auth.php';
require_once 'db.php';

$pageTitle = 'Diagnóstico - Máquinas';
require_once 'includes/header.php';
?>

<div class="mb-6 text-center sm:text-left">
    <h2 class="text-3xl font-bold text-white mb-2">🔍 Diagnóstico: Monitoramento de Máquinas</h2>
    <p class="text-slate-400">Verifique o status da API e dos dados no banco de dados</p>
</div>

<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <!-- Status Geral -->
    <div class="glass-panel p-6 rounded-2xl">
        <h3 class="text-lg font-bold text-white mb-4">📊 Status Geral</h3>
        
        <div class="space-y-3">
            <div class="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg">
                <span class="text-slate-300">Usuário Logado:</span>
                <span class="font-bold text-cyan-400"><?= htmlspecialchars($_SESSION['username'] ?? 'Desconhecido') ?></span>
            </div>
            
            <div class="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg">
                <span class="text-slate-300">User ID:</span>
                <span class="font-bold text-cyan-400"><?= htmlspecialchars($_SESSION['user_id'] ?? 'N/A') ?></span>
            </div>
            
            <div class="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg">
                <span class="text-slate-300">Session Active:</span>
                <span class="font-bold text-emerald-400">✓ Sim</span>
            </div>
            
            <?php
                // Contar máquinas no banco
                $stmt = $pdo->query("SELECT COUNT(DISTINCT CONCAT(maquina, usuario)) as total FROM impressoes WHERE maquina IS NOT NULL");
                $totalMachines = $stmt->fetchColumn();
            ?>
            
            <div class="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg">
                <span class="text-slate-300">Máquinas no Banco:</span>
                <span class="font-bold text-cyan-400"><?= intval($totalMachines) ?></span>
            </div>
        </div>
    </div>

    <!-- Teste da API -->
    <div class="glass-panel p-6 rounded-2xl">
        <h3 class="text-lg font-bold text-white mb-4">🔌 Teste da API</h3>
        
        <div class="space-y-3">
            <button id="btnTestApi" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2 px-4 rounded-lg transition">
                Testar API: get_machines
            </button>
            
            <div id="apiResult" class="hidden p-4 bg-slate-800/50 rounded-lg">
                <div id="apiStatus" class="text-sm font-mono text-slate-300"></div>
            </div>
        </div>
    </div>

    <!-- Dados Brutos -->
    <div class="glass-panel p-6 rounded-2xl lg:col-span-2">
        <h3 class="text-lg font-bold text-white mb-4">📋 Dados Brutos do Banco</h3>
        
        <div class="overflow-x-auto">
            <table class="w-full text-xs text-slate-300">
                <thead>
                    <tr class="bg-slate-800/50 text-slate-400 uppercase">
                        <th class="px-4 py-2 text-left">Máquina</th>
                        <th class="px-4 py-2 text-left">Usuário</th>
                        <th class="px-4 py-2 text-left">Última Ação</th>
                        <th class="px-4 py-2 text-center">Impressões</th>
                    </tr>
                </thead>
                <tbody>
                    <?php
                        $stmt = $pdo->query("
                            SELECT 
                                maquina,
                                usuario,
                                MAX(data_hora) as ultima_acao,
                                COUNT(*) as total_impressoes
                            FROM impressoes
                            WHERE maquina IS NOT NULL AND maquina != ''
                            GROUP BY maquina, usuario
                            ORDER BY MAX(data_hora) DESC
                            LIMIT 10
                        ");
                        $machines = $stmt->fetchAll();
                        
                        if (count($machines) > 0) {
                            foreach ($machines as $m) {
                                echo "<tr class='border-b border-slate-700/30'>";
                                echo "<td class='px-4 py-2'>" . htmlspecialchars($m['maquina']) . "</td>";
                                echo "<td class='px-4 py-2'>" . htmlspecialchars($m['usuario']) . "</td>";
                                echo "<td class='px-4 py-2'>" . htmlspecialchars($m['ultima_acao']) . "</td>";
                                echo "<td class='px-4 py-2 text-center'>" . intval($m['total_impressoes']) . "</td>";
                                echo "</tr>";
                            }
                        } else {
                            echo "<tr><td colspan='4' class='px-4 py-3 text-center text-slate-500'>Nenhum dado encontrado</td></tr>";
                        }
                    ?>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    document.getElementById('btnTestApi').addEventListener('click', async function() {
        const btn = this;
        const resultDiv = document.getElementById('apiResult');
        const statusDiv = document.getElementById('apiStatus');
        
        btn.disabled = true;
        btn.textContent = 'Testando...';
        statusDiv.textContent = 'Carregando...';
        resultDiv.classList.remove('hidden');
        
        try {
            console.log('[Test] Iniciando teste da API...');
            const response = await fetch('api_impressoras.php?action=get_machines', {
                credentials: 'same-origin'
            });
            
            console.log('[Test] Status:', response.status);
            const text = await response.text();
            console.log('[Test] Resposta (primeiros 200 chars):', text.substring(0, 200));
            
            const json = JSON.parse(text);
            
            if (json.success && json.machines) {
                const onlineCount = json.machines.filter(m => m.status === 'Online').length;
                const offlineCount = json.machines.filter(m => m.status === 'Offline').length;
                
                statusDiv.innerHTML = `
                    <div style="color: #10b981;">✓ API respondeu com sucesso</div>
                    <div>Total de máquinas: <strong>${json.machines.length}</strong></div>
                    <div>Online: <strong style="color: #10b981;">${onlineCount}</strong></div>
                    <div>Offline: <strong style="color: #ef4444;">${offlineCount}</strong></div>
                    <div style="margin-top: 10px; color: #94a3b8;">Resposta JSON válida!</div>
                `;
            } else {
                statusDiv.innerHTML = `
                    <div style="color: #ef4444;">✗ Erro na API</div>
                    <div>${json.error || 'Erro desconhecido'}</div>
                `;
            }
        } catch (e) {
            statusDiv.innerHTML = `
                <div style="color: #ef4444;">✗ Erro ao chamar API</div>
                <div>${e.message}</div>
            `;
            console.error('[Test] Erro:', e);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Testar API: get_machines';
        }
    });
</script>

<?php require_once 'includes/footer.php'; ?>
