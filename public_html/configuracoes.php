<?php
require_once 'auth.php';
require_once 'db.php';

if (!isAdmin()) {
    header('Location: index.php');
    exit;
}

$message = ''; $tipo_msg = '';
$configFile = __DIR__ . '/includes/config.json';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!validateCsrfToken($_POST['csrf_token'] ?? '')) { die('Erro de segurança.'); }

    $nome = $_POST['app_name'] ?? 'PrintDash';
    $tagline = $_POST['app_tagline'] ?? '';
    $logo = $_POST['app_logo_url'] ?? '';
    $color = $_POST['app_color'] ?? '#6366f1';
    $price_bw_str = str_replace(',', '.', $_POST['app_price_bw'] ?? '0.50');
    $price_bw = floatval($price_bw_str);
    
    $price_color_str = str_replace(',', '.', $_POST['app_price_color'] ?? '1.00');
    $price_color = floatval($price_color_str);
    $guia_url = $_POST['guia_suporte_url'] ?? '';
    $url_atend = $_POST['url_atendimento'] ?? '';

    $uploadDir = __DIR__ . '/uploads/';
    if (!is_dir($uploadDir)) mkdir($uploadDir, 0755, true);

    if (isset($_FILES['app_logo_upload']) && $_FILES['app_logo_upload']['error'] === UPLOAD_ERR_OK) {
        $ext = strtolower(pathinfo($_FILES['app_logo_upload']['name'], PATHINFO_EXTENSION));
        if (in_array($ext, ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'])) {
            $newFileName = 'logo_customizada.' . $ext;
            if (move_uploaded_file($_FILES['app_logo_upload']['tmp_name'], $uploadDir . $newFileName)) {
                $logo = 'uploads/' . $newFileName . '?v=' . time();
            }
        }
    }

    if (isset($_FILES['guia_suporte_upload']) && $_FILES['guia_suporte_upload']['error'] === UPLOAD_ERR_OK) {
        $ext = strtolower(pathinfo($_FILES['guia_suporte_upload']['name'], PATHINFO_EXTENSION));
        if (in_array($ext, ['pdf', 'doc', 'docx', 'txt', 'jpg', 'png'])) {
            $newFileName = 'guia_suporte_usuario.' . $ext;
            if (move_uploaded_file($_FILES['guia_suporte_upload']['tmp_name'], $uploadDir . $newFileName)) {
                $guia_url = 'uploads/' . $newFileName;
            }
        }
    }

    $newConfig = [
        'APP_NAME' => $nome,
        'APP_TAGLINE' => $tagline,
        'APP_LOGO_URL' => $logo,
        'APP_COLOR' => $color,
        'APP_PRICE_BW' => $price_bw,
        'APP_PRICE_COLOR' => $price_color,
        'MODULO_IMPRESSAO' => isset($_POST['mod_impressao']),
        'MODULO_SUPORTE' => isset($_POST['mod_suporte']),
        'MODULO_ATENDIMENTO' => isset($_POST['mod_atendimento']),
        'URL_ATENDIMENTO' => $url_atend,
        'GUIA_SUPORTE_URL' => $guia_url
    ];

    if (file_put_contents($configFile, json_encode($newConfig, JSON_PRETTY_PRINT))) {
        $message = "Configurações atualizadas!"; $tipo_msg = "success";
    } else {
        $message = "Erro ao salvar."; $tipo_msg = "error";
    }
}

$configData = file_exists($configFile) ? json_decode(file_get_contents($configFile), true) : [];
require_once 'includes/config.php';
$pageTitle = 'Configurações | ' . APP_NAME;
$hideChartJs = true;
require_once 'includes/header.php';
?>

<div class="mb-6">
    <h2 class="text-3xl font-black text-white mb-1 uppercase tracking-tighter italic">Configurações do Sistema</h2>
    <p class="text-slate-500 font-bold uppercase tracking-[0.3em] text-[10px]">Personalização e Segurança</p>
</div>

<?php if ($message): ?>
    <div class="mb-6 p-4 rounded-xl text-xs font-black uppercase tracking-widest border <?= $tipo_msg === 'success' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20' ?>">
        <?= htmlspecialchars($message) ?>
    </div>
<?php endif; ?>

<form method="POST" enctype="multipart/form-data" class="grid grid-cols-1 lg:grid-cols-2 gap-8 pb-12">
    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">

    <!-- Coluna 1: Marca e Módulos -->
    <div class="space-y-8">
        <div class="glass-panel p-8 rounded-[2.5rem] border border-white/5">
            <h3 class="text-lg font-black text-white mb-6 uppercase tracking-tight flex items-center gap-2 italic">Identidade Visual</h3>
            <div class="space-y-4">
                <div>
                    <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5">Nome da Empresa</label>
                    <input type="text" name="app_name" value="<?= htmlspecialchars($configData['APP_NAME'] ?? 'PrintDash') ?>" class="glass-input w-full px-5 py-3 rounded-xl text-white font-bold">
                </div>
                <div>
                    <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5">Slogan / Tagline</label>
                    <input type="text" name="app_tagline" value="<?= htmlspecialchars($configData['APP_TAGLINE'] ?? '') ?>" class="glass-input w-full px-5 py-3 rounded-xl text-white">
                </div>
                <div class="grid grid-cols-3 gap-4">
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5">Cor Principal</label>
                        <input type="color" name="app_color" value="<?= htmlspecialchars($configData['APP_COLOR'] ?? '#6366f1') ?>" class="h-12 w-full bg-transparent cursor-pointer rounded-xl border-0 p-0">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5">Preço P&B</label>
                        <input type="number" step="0.01" name="app_price_bw" value="<?= $configData['APP_PRICE_BW'] ?? 0.50 ?>" class="glass-input w-full px-4 py-3 rounded-xl text-white font-bold">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5">Preço Cor</label>
                        <input type="number" step="0.01" name="app_price_color" value="<?= $configData['APP_PRICE_COLOR'] ?? 1.00 ?>" class="glass-input w-full px-4 py-3 rounded-xl text-white font-bold">
                    </div>
                </div>
            </div>
        </div>

        <div class="glass-panel p-8 rounded-[2.5rem] border border-white/5">
            <h3 class="text-lg font-black text-white mb-6 uppercase tracking-tight flex items-center gap-2 italic">Ativação de Módulos</h3>
            <div class="space-y-3">
                <label class="flex items-center gap-4 p-4 rounded-2xl bg-white/5 border border-white/5 cursor-pointer hover:bg-white/10 transition-all">
                    <input type="checkbox" name="mod_impressao" <?= ($configData['MODULO_IMPRESSAO'] ?? true) ? 'checked' : '' ?> class="w-6 h-6 rounded-lg bg-slate-800 border-white/10 text-indigo-500 focus:ring-0">
                    <div class="flex flex-col">
                        <span class="text-xs font-black text-white uppercase tracking-wider">Gestão de Impressão</span>
                        <span class="text-[10px] text-slate-500 uppercase tracking-widest">Equipamentos e Toner</span>
                    </div>
                </label>
                <label class="flex items-center gap-4 p-4 rounded-2xl bg-white/5 border border-white/5 cursor-pointer hover:bg-white/10 transition-all">
                    <input type="checkbox" name="mod_suporte" <?= ($configData['MODULO_SUPORTE'] ?? true) ? 'checked' : '' ?> class="w-6 h-6 rounded-lg bg-slate-800 border-white/10 text-blue-500 focus:ring-0">
                    <div class="flex flex-col">
                        <span class="text-xs font-black text-white uppercase tracking-wider">Suporte TI</span>
                        <span class="text-[10px] text-slate-500 uppercase tracking-widest">Abertura de Chamados</span>
                    </div>
                </label>
                <label class="flex items-center gap-4 p-4 rounded-2xl bg-white/5 border border-white/5 cursor-pointer hover:bg-white/10 transition-all">
                    <input type="checkbox" name="mod_atendimento" <?= ($configData['MODULO_ATENDIMENTO'] ?? false) ? 'checked' : '' ?> class="w-6 h-6 rounded-lg bg-slate-800 border-white/10 text-emerald-500 focus:ring-0">
                    <div class="flex flex-col">
                        <span class="text-xs font-black text-white uppercase tracking-wider">Atendimento Externo</span>
                        <span class="text-[10px] text-slate-500 uppercase tracking-widest">WhatsApp / Iframe</span>
                    </div>
                </label>
            </div>
            <div class="mt-4">
                <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5">URL Atendimento</label>
                <input type="text" name="url_atendimento" value="<?= htmlspecialchars($configData['URL_ATENDIMENTO'] ?? '') ?>" placeholder="http://..." class="glass-input w-full px-4 py-2 rounded-xl text-white font-mono text-xs">
            </div>
        </div>

        <button type="submit" class="w-full py-5 bg-gradient-to-r from-indigo-600 to-fuchsia-600 text-white font-black text-xs uppercase tracking-[0.3em] rounded-[2rem] shadow-2xl hover:scale-[1.02] active:scale-[0.98] transition-all">
            Salvar Configurações
        </button>
    </div>

    <!-- Coluna 2: Backup e Arquivos -->
    <div class="space-y-8">
        <div class="glass-panel p-8 rounded-[2.5rem] border border-white/5">
            <h3 class="text-lg font-black text-white mb-6 uppercase tracking-tight italic">Arquivos e Manuais</h3>
            <div class="space-y-6">
                <div>
                    <label class="block text-[10px] font-black text-emerald-400 uppercase tracking-widest mb-3">Logomarca (Upload)</label>
                    <input type="file" name="app_logo_upload" class="w-full text-xs text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-emerald-500/10 file:text-emerald-400 cursor-pointer">
                    <input type="hidden" name="app_logo_url" value="<?= htmlspecialchars(explode('?', $configData['APP_LOGO_URL'] ?? '')[0]) ?>">
                </div>
                <div class="pt-6 border-t border-white/5">
                    <label class="block text-[10px] font-black text-blue-400 uppercase tracking-widest mb-3">Guia de Utilização (Upload)</label>
                    <input type="file" name="guia_suporte_upload" class="w-full text-xs text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-500/10 file:text-blue-400 cursor-pointer">
                    <input type="hidden" name="guia_suporte_url" value="<?= htmlspecialchars($configData['GUIA_SUPORTE_URL'] ?? '') ?>">
                </div>
            </div>
        </div>

        <!-- O BACKUP 100% FUNCIONAL VOLTOU AQUI -->
        <div class="glass-panel p-8 rounded-[2.5rem] border border-emerald-500/20 relative overflow-hidden group">
            <h3 class="text-xl font-black text-white mb-4 flex items-center gap-2 uppercase tracking-tighter italic">
                <svg class="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path></svg>
                Backup & Restauração
            </h3>
            
            <button type="button" onclick="generateBackup()" id="btn-backup" class="w-full py-4 bg-emerald-600 hover:bg-emerald-500 text-white font-black text-[10px] uppercase tracking-widest rounded-2xl shadow-lg transition-all flex items-center justify-center gap-2 mb-4">
                Gerar Backup Completo (ZIP)
            </button>

            <div class="p-4 rounded-2xl bg-indigo-500/5 border border-indigo-500/10">
                <label class="block text-[9px] font-black text-indigo-400 uppercase tracking-widest mb-3 text-center">Importar Backup Externo</label>
                <input type="file" id="import-file" accept=".zip,.sql" class="hidden" onchange="uploadAndRestore(this)">
                <button type="button" onclick="document.getElementById('import-file').click()" class="w-full py-2.5 bg-indigo-600/20 hover:bg-indigo-600/40 text-indigo-400 font-bold text-[10px] uppercase tracking-wider rounded-xl border border-indigo-500/30 transition-all flex items-center justify-center gap-2">
                    Selecionar Arquivo ZIP
                </button>
            </div>

            <div class="mt-6 border-t border-white/5 pt-6">
                <h4 class="text-[9px] font-black text-slate-500 uppercase tracking-[0.2em] mb-4">Lista de Backups Disponíveis</h4>
                <div id="backup-list" class="space-y-2 max-h-[250px] overflow-y-auto pr-1 custom-scrollbar">
                    <p class="text-[10px] text-slate-600 italic">Carregando backups...</p>
                </div>
            </div>
        </div>
    </div>
</form>

<script>
    async function loadBackups() {
        try {
            const res = await fetch('admin_backup.php?action=list');
            const backups = await res.json();
            const container = document.getElementById('backup-list');
            if (!backups || backups.length === 0) {
                container.innerHTML = '<p class="text-[10px] text-slate-600 italic text-center">Nenhum backup encontrado.</p>';
                return;
            }
            container.innerHTML = backups.map(b => `
                <div class="flex items-center justify-between p-3 bg-white/5 rounded-xl border border-white/5 hover:border-emerald-500/30 transition-all">
                    <div class="flex flex-col">
                        <span class="text-[10px] font-black text-slate-300 uppercase tracking-tighter">${b.name}</span>
                        <span class="text-[8px] text-slate-500 font-bold">${b.date} • ${b.size}</span>
                    </div>
                    <div class="flex gap-1">
                        <button type="button" onclick="restoreBackup('${b.name}')" class="p-2 text-slate-500 hover:text-indigo-400" title="Restaurar"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg></button>
                        <a href="backups/${b.name}" download class="p-2 text-slate-500 hover:text-emerald-400"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a2 2 0 002 2h12a2 2 0 002-2v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg></a>
                        <button type="button" onclick="deleteBackup('${b.name}')" class="p-2 text-slate-500 hover:text-rose-400"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
                    </div>
                </div>
            `).join('');
        } catch(e) { console.error(e); }
    }

    async function generateBackup() {
        const btn = document.getElementById('btn-backup');
        const old = btn.innerHTML;
        btn.disabled = true; btn.innerHTML = 'Gerando...';
        try {
            const res = await fetch('admin_backup.php?action=generate');
            const data = await res.json();
            if (data.success) { alert('Backup gerado!'); loadBackups(); }
            else { alert('Erro: ' + data.message); }
        } catch (e) { alert('Falha ao gerar backup.'); }
        finally { btn.disabled = false; btn.innerHTML = old; }
    }

    async function restoreBackup(name) {
        if (!confirm('Restaurar este backup?')) return;
        try {
            const res = await fetch('admin_backup.php?action=restore&file=' + name);
            const data = await res.json();
            if (data.success) { alert('✅ Sistema restaurado!'); window.location.reload(); }
            else { alert('Erro: ' + data.message); }
        } catch (e) { alert('Erro na restauração.'); }
    }

    async function uploadAndRestore(input) {
        if (!input.files[0]) return;
        const formData = new FormData();
        formData.append('backup_file', input.files[0]);
        try {
            const res = await fetch('admin_backup.php?action=upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) { alert('✅ Importado com sucesso!'); window.location.reload(); }
            else { alert('Erro: ' + data.message); }
        } catch (e) { alert('Erro no envio.'); }
    }

    async function deleteBackup(name) {
        if (!confirm('Excluir?')) return;
        try {
            const res = await fetch('admin_backup.php?action=delete&file=' + name);
            const data = await res.json();
            if (data.success) loadBackups();
        } catch (e) { console.error(e); }
    }

    loadBackups();
</script>

<?php require_once 'includes/footer.php'; ?>
