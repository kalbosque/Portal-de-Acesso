<?php
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

if (!isAdmin()) { header('Location: index.php'); exit; }

$message = ''; $err = ''; $tipo_msg = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // SEGURANÇA: Validar Token CSRF
    if (!validateCsrfToken($_POST['csrf_token'] ?? '')) {
        die('Erro de segurança: Token inválido.');
    }
}

// Criar usuário
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'create') {
    $nome     = trim($_POST['nome'] ?? '');
    $email    = trim($_POST['email'] ?? '');
    $user     = trim($_POST['username'] ?? '');
    $pass     = $_POST['password'] ?? '';
    $role     = $_POST['role'] ?? 'operator';
    $perms    = json_encode($_POST['perms'] ?? []);

    if (!$nome || !$email || !$user || !$pass) {
        $err = 'Preencha todos os campos obrigatórios.'; $tipo_msg = 'error';
    } elseif (strlen($pass) < 6 || strlen($pass) > 8) {
        $err = 'A senha deve ter entre 6 e 8 caracteres.'; $tipo_msg = 'error';
    } elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $err = 'E-mail inválido.'; $tipo_msg = 'error';
    } else {
        // Verificar e-mail duplicado
        $checkEmail = $pdo->prepare("SELECT id FROM usuarios WHERE email = ?");
        $checkEmail->execute([$email]);
        if ($checkEmail->fetch()) {
            $err = 'Este e-mail já está cadastrado no sistema.'; $tipo_msg = 'error';
        } else {
            // Verificar username duplicado
            $checkUser = $pdo->prepare("SELECT id FROM usuarios WHERE username = ?");
            $checkUser->execute([$user]);
            if ($checkUser->fetch()) {
                $err = 'Este nome de usuário já está em uso.'; $tipo_msg = 'error';
            } else {
                try {
                    $hash = password_hash($pass, PASSWORD_DEFAULT);
                    $pdo->prepare("INSERT INTO usuarios (nome, email, username, password_hash, role, status_conta, permissoes) VALUES (?,?,?,?,?,'ativo',?)")
                        ->execute([$nome, $email, $user, $hash, $role, $perms]);
                    $message = "Usuário '$user' criado com sucesso!"; $tipo_msg = 'success';
                    header('Location: usuarios.php?msg=criado');
                    exit;
                } catch (Exception $e) { $err = 'Erro ao criar usuário.'; $tipo_msg = 'error'; }
            }
        }
    }
}

// Alterar senha
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'edit_pass') {
    $uid = intval($_POST['user_id']); $np = $_POST['new_password'] ?? '';
    if ($uid && $np) {
        $pdo->prepare("UPDATE usuarios SET password_hash=? WHERE id=?")->execute([password_hash($np, PASSWORD_DEFAULT), $uid]);
        header('Location: usuarios.php?msg=senha');
        exit;
    }
}

// Atualizar permissões + nome + email
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'edit_perms') {
    $uid   = intval($_POST['user_id']);
    $nome  = trim($_POST['nome'] ?? '');
    $email = trim($_POST['email'] ?? '');
    $perms = json_encode($_POST['perms'] ?? []);
    $role  = $_POST['role'] ?? 'operator';
    if ($uid) {
        $pdo->prepare("UPDATE usuarios SET nome=?, email=?, role=?, permissoes=? WHERE id=?")->execute([$nome, $email, $role, $perms, $uid]);
        header('Location: usuarios.php?msg=atualizado');
        exit;
    }
}

// Alterar status (aprovar/bloquear/ativar)
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'set_status') {
    $uid = intval($_POST['user_id']); $status = $_POST['status'] ?? 'ativo';
    if ($uid && $uid !== $_SESSION['user_id']) {
        $pdo->prepare("UPDATE usuarios SET status_conta=? WHERE id=?")->execute([$status, $uid]);
        header('Location: usuarios.php?msg=status');
        exit;
    }
}

// Excluir
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'delete') {
    $uid = intval($_POST['user_id']);
    $myId = intval($_SESSION['user_id']);
    
    if (!$uid) {
        $err = 'ID inválido.'; $tipo_msg = 'error';
    } elseif ($uid == $myId) {
        $err = 'Não é permitido auto-exclusão.'; $tipo_msg = 'error';
    } else {
        // Verificar se o alvo é admin (NUNCA excluir admin por acidente)
        $target = $pdo->prepare("SELECT role FROM usuarios WHERE id = ?");
        $target->execute([$uid]);
        $targetUser = $target->fetch();
        
        if ($targetUser && $targetUser['role'] === 'admin') {
            $err = 'Não é permitido excluir um Administrador.'; $tipo_msg = 'error';
        } else {
            $pdo->prepare("DELETE FROM usuarios WHERE id = ? AND role != 'admin'")->execute([$uid]);
            header('Location: usuarios.php?msg=removido');
            exit;
        }
    }
}

// Capturar mensagem de redirecionamento
if (isset($_GET['msg'])) {
    $msgs = ['removido'=>'Usuário removido.','criado'=>'Usuário criado!','atualizado'=>'Dados atualizados.','senha'=>'Senha alterada.','status'=>'Status atualizado.'];
    $message = $msgs[$_GET['msg']] ?? '';
    $tipo_msg = 'success';
}

$users = $pdo->query("SELECT id, nome, email, username, role, status_conta, permissoes, created_at FROM usuarios ORDER BY created_at DESC")->fetchAll();

$pageTitle = 'Usuários | ' . APP_NAME;
$hideChartJs = true;
require_once 'includes/header.php';
?>

<link rel="stylesheet" href="css/monitor.css">
<style>
    .modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); backdrop-filter:blur(4px); z-index:999; align-items:center; justify-content:center; }
    .modal-overlay.open { display:flex; }
    .modal-box { background:var(--glass-bg, rgba(15,23,42,.95)); border:1px solid rgba(255,255,255,.1); border-radius:1.5rem; padding:2rem; width:100%; max-width:440px; animation:slideUp .25s ease-out; }
    @keyframes slideUp { from{opacity:0;transform:translateY(20px)} to{opacity:1;transform:translateY(0)} }
    .status-ativo    { background:rgba(16,185,129,.12); color:#10b981; border:1px solid rgba(16,185,129,.25); }
    .status-pendente { background:rgba(245,158,11,.12); color:#f59e0b; border:1px solid rgba(245,158,11,.25); }
    .status-bloqueado{ background:rgba(239,68,68,.12);  color:#ef4444; border:1px solid rgba(239,68,68,.25); }
    .light-mode .glass-card { background:#fff !important; border-color:#cbd5e1 !important; }
    .light-mode .modal-box  { background:#f8fafc !important; }
</style>

<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-0 pb-8 animate-fade-in">

    <!-- Header -->
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-4">
        <div class="flex items-center gap-4">
            <div class="p-3 bg-fuchsia-500/10 rounded-2xl border border-fuchsia-500/20 shadow-inner hidden sm:block">
                <svg class="w-8 h-8 text-fuchsia-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
            </div>
            <div>
                <h1 class="text-3xl font-black text-[var(--text-primary)] tracking-tighter mb-1 uppercase">Usuários</h1>
                <p class="text-xs text-[var(--text-secondary)] font-bold uppercase tracking-[0.3em] opacity-70">Governança de Acessos · <?= count($users) ?> cadastrados</p>
            </div>
        </div>
        <button onclick="openModal('modal-create')" class="px-6 py-3 rounded-2xl bg-indigo-600 text-white font-black text-xs uppercase tracking-widest shadow-xl hover:bg-indigo-500 transition-all flex items-center gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
            Novo Usuário
        </button>
    </div>

    <?php if ($message || $err): ?>
        <div class="mb-6 p-4 rounded-2xl text-sm font-bold <?= $tipo_msg === 'success' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20' ?>">
            <?= htmlspecialchars($message ?: $err) ?>
        </div>
    <?php endif; ?>

    <!-- Tabela -->
    <div class="glass-card rounded-3xl overflow-hidden">
        <div class="px-8 py-6 border-b border-[var(--card-border)]">
            <h3 class="text-xs font-black text-[var(--text-secondary)] uppercase tracking-[0.2em]">👥 Usuários Cadastrados</h3>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-left text-sm border-collapse">
                <thead>
                    <tr class="bg-[var(--table-header-bg)]">
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">Colaborador</th>
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest">E-mail</th>
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Perfil</th>
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-center">Status</th>
                        <th class="px-8 py-4 text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest text-right">Ações</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-[var(--card-border)]">
                    <?php foreach($users as $u):
                        $up = json_decode($u['permissoes'] ?? '[]', true) ?: [];
                        $status = $u['status_conta'] ?? 'ativo';
                        $initials = strtoupper(substr($u['nome'] ?: $u['username'], 0, 2));
                    ?>
                    <tr class="hover:bg-[var(--table-row-hover)] transition-colors group">
                        <td class="px-8 py-5">
                            <div class="flex items-center gap-3">
                                <div class="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 font-black text-xs uppercase shrink-0">
                                    <?= $initials ?>
                                </div>
                                <div class="flex flex-col">
                                    <span class="font-black text-[var(--text-bold)] tracking-tight"><?= htmlspecialchars($u['nome'] ?: $u['username']) ?></span>
                                    <span class="text-[10px] text-[var(--text-muted)] font-mono opacity-60">@<?= htmlspecialchars($u['username']) ?></span>
                                </div>
                            </div>
                        </td>
                        <td class="px-8 py-5 text-[var(--text-secondary)] text-xs font-medium">
                            <?= $u['email'] ? htmlspecialchars($u['email']) : '<span class="opacity-40 italic">Não informado</span>' ?>
                        </td>
                        <td class="px-8 py-5 text-center">
                            <?php if($u['role'] === 'admin'): ?>
                                <span class="px-2 py-1 rounded text-[8px] font-black uppercase tracking-widest bg-fuchsia-500/10 text-fuchsia-400 border border-fuchsia-500/20">Admin</span>
                            <?php else: ?>
                                <span class="px-2 py-1 rounded text-[8px] font-black uppercase tracking-widest bg-slate-500/10 text-slate-400 border border-slate-500/20">Colaborador</span>
                            <?php endif; ?>
                        </td>
                        <td class="px-8 py-5 text-center">
                            <span class="px-2 py-1 rounded text-[8px] font-black uppercase tracking-widest status-<?= $status ?>">
                                <?= ucfirst($status) ?>
                            </span>
                        </td>
                        <td class="px-8 py-5 text-right">
                            <div class="flex items-center justify-end gap-2">
                                <!-- Editar -->
                                <button onclick="openEdit(<?= htmlspecialchars(json_encode($u)) ?>)"
                                    class="px-3 py-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-[9px] font-black uppercase tracking-widest hover:bg-indigo-500/20 transition-colors">
                                    ✏️ Editar
                                </button>
                                <!-- Senha -->
                                <button onclick="openPass(<?= $u['id'] ?>, '<?= htmlspecialchars($u['username']) ?>')"
                                    class="px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-[9px] font-black uppercase tracking-widest hover:bg-cyan-500/20 transition-colors">
                                    🔑 Senha
                                </button>
                                <!-- Status -->
                                <?php if(intval($u['id']) !== intval($_SESSION['user_id'])): ?>
                                <?php if($status === 'pendente'): ?>
                                <form method="POST" class="inline">
                                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                                    <input type="hidden" name="action" value="set_status">
                                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                                    <input type="hidden" name="status" value="ativo">
                                    <button type="submit" class="px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-black uppercase tracking-widest hover:bg-emerald-500/20 transition-colors">✅ Aprovar</button>
                                </form>
                                <?php elseif($status === 'ativo'): ?>
                                <form method="POST" class="inline">
                                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                                    <input type="hidden" name="action" value="set_status">
                                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                                    <input type="hidden" name="status" value="bloqueado">
                                    <button type="submit" class="px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[9px] font-black uppercase tracking-widest hover:bg-amber-500/20 transition-colors">🔒 Bloquear</button>
                                </form>
                                <?php else: ?>
                                <form method="POST" class="inline">
                                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                                    <input type="hidden" name="action" value="set_status">
                                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                                    <input type="hidden" name="status" value="ativo">
                                    <button type="submit" class="px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-black uppercase tracking-widest hover:bg-emerald-500/20 transition-colors">🔓 Ativar</button>
                                </form>
                                <?php endif; // fecha if($status === ...)  ?>
                                <?php endif; // fecha if($u['id'] !== $_SESSION['user_id']) do bloco Status ?>
                                <!-- Excluir (só aparece para outros usuários) -->
                                <?php if(intval($u['id']) !== intval($_SESSION['user_id'])): ?>
                                <form method="POST" class="inline" onsubmit="if(this.dataset.sent) return false; this.dataset.sent='1'; return confirm('Remover @<?= htmlspecialchars($u['username']) ?> permanentemente?');">
                                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                                    <input type="hidden" name="action" value="delete">
                                    <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                                    <button type="submit" class="p-2 rounded-lg text-rose-500 hover:bg-rose-500/10 transition-colors" title="Excluir usuário">
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                                    </button>
                                </form>
                                <?php endif; ?>
                            </div>
                        </td>
                    </tr>
                    <?php endforeach; ?>
                    <?php if(empty($users)): ?>
                        <tr><td colspan="5" class="px-8 py-12 text-center text-[var(--text-muted)] italic">Nenhum usuário cadastrado.</td></tr>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- Modal: Criar Usuário -->
<div id="modal-create" class="modal-overlay" onclick="closeOnBg(event,'modal-create')">
    <div class="modal-box">
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-black text-[var(--text-primary)] uppercase tracking-tight">➕ Novo Usuário</h2>
            <button onclick="closeModal('modal-create')" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
        </div>
        <form method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
            <input type="hidden" name="action" value="create">
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Nome Completo *</label>
                <input type="text" name="nome" required class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm" placeholder="Nome do colaborador">
            </div>
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">E-mail *</label>
                <input type="email" name="email" required class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm" placeholder="email@empresa.com">
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Usuário *</label>
                    <input type="text" name="username" required class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm" placeholder="login">
                </div>
                <div>
                    <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Senha *</label>
                    <input type="password" name="password" required class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm" placeholder="••••••">
                </div>
            </div>
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Perfil</label>
                <select name="role" class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm appearance-none">
                    <option value="operator">Colaborador</option>
                    <option value="admin">Administrador</option>
                </select>
            </div>
            <div class="border-t border-[var(--card-border)] pt-4">
                <label class="block text-[10px] font-black text-indigo-400 uppercase tracking-widest mb-3">🛠️ Módulos Ativos (Licenciamento)</label>
                <div class="grid grid-cols-2 gap-2" id="perms-container-create">
                    <?php foreach([
                        'dashboard'=>'🏠 Tela Inicial',
                        'chamados'=>'🎧 Suporte TI',
                        'equipamentos'=>'🖨️ Equipamentos',
                        'relatorios'=>'📊 Relatórios',
                        'modulo_tickets' => '🎫 Tickets (WhatsApp)',
                        'config_suporte' => '⚙️ Config. Suporte'
                    ] as $val=>$lbl): ?>
                    <label class="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-bold cursor-pointer hover:text-white transition-colors">
                        <input type="checkbox" name="perms[]" value="<?= $val ?>" <?= in_array($val, ['dashboard','chamados','modulo_tickets']) ? 'checked' : '' ?> class="rounded border-white/10 bg-white/5 perms-checkbox"> <?= $lbl ?>
                    </label>
                    <?php endforeach; ?>
                </div>
            </div>
            <button type="submit" class="w-full py-3 rounded-2xl bg-indigo-600 text-white font-black text-xs uppercase tracking-widest hover:bg-indigo-500 transition-all shadow-lg">
                Criar Usuário
            </button>
        </form>
    </div>
</div>

<!-- Modal: Editar Usuário -->
<div id="modal-edit" class="modal-overlay" onclick="closeOnBg(event,'modal-edit')">
    <div class="modal-box">
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-black text-[var(--text-primary)] uppercase tracking-tight">✏️ Editar Usuário</h2>
            <button onclick="closeModal('modal-edit')" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
        </div>
        <form method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
            <input type="hidden" name="action" value="edit_perms">
            <input type="hidden" name="user_id" id="edit_uid">
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Nome</label>
                <input type="text" name="nome" id="edit_nome" class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm">
            </div>
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">E-mail</label>
                <input type="email" name="email" id="edit_email" class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm">
            </div>
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Perfil</label>
                <select name="role" id="edit_role" class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm appearance-none">
                    <option value="operator">Colaborador</option>
                    <option value="admin">Administrador</option>
                </select>
            </div>
            <div class="border-t border-[var(--card-border)] pt-4">
                <label class="block text-[10px] font-black text-indigo-400 uppercase tracking-widest mb-3">🛠️ Módulos Ativos (Licenciamento)</label>
                <div class="grid grid-cols-2 gap-2" id="edit_perms_list">
                    <?php foreach([
                        'dashboard'=>'🏠 Tela Inicial',
                        'chamados'=>'🎧 Suporte TI',
                        'equipamentos'=>'🖨️ Equipamentos',
                        'relatorios'=>'📊 Relatórios',
                        'modulo_tickets' => '🎫 Tickets (WhatsApp)',
                        'config_suporte' => '⚙️ Config. Suporte'
                    ] as $val=>$lbl): ?>
                    <label class="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-bold cursor-pointer hover:text-white transition-colors">
                        <input type="checkbox" name="perms[]" id="eperm_<?= $val ?>" value="<?= $val ?>" class="rounded perms-checkbox-edit"> <?= $lbl ?>
                    </label>
                    <?php endforeach; ?>
                </div>
            </div>
            <button type="submit" class="w-full py-3 rounded-2xl bg-fuchsia-600 text-white font-black text-xs uppercase tracking-widest hover:bg-fuchsia-500 transition-all shadow-lg">
                Salvar Alterações
            </button>
        </form>
    </div>
</div>

<!-- Modal: Alterar Senha -->
<div id="modal-pass" class="modal-overlay" onclick="closeOnBg(event,'modal-pass')">
    <div class="modal-box">
        <div class="flex justify-between items-center mb-6">
            <div>
                <h2 class="text-lg font-black text-[var(--text-primary)] uppercase tracking-tight">🔑 Nova Senha</h2>
                <p id="pass_username" class="text-[10px] text-[var(--text-muted)] font-mono mt-1"></p>
            </div>
            <button onclick="closeModal('modal-pass')" class="text-[var(--text-muted)] hover:text-[var(--text-primary)]">✕</button>
        </div>
        <form method="POST" class="space-y-4">
            <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
            <input type="hidden" name="action" value="edit_pass">
            <input type="hidden" name="user_id" id="pass_uid">
            <div>
                <label class="block text-[10px] font-black text-[var(--text-secondary)] uppercase tracking-widest mb-1">Nova Senha</label>
                <input type="password" name="new_password" required minlength="6" class="glass-input w-full px-4 py-3 rounded-xl text-[var(--text-primary)] font-bold text-sm" placeholder="Mínimo 6 caracteres">
            </div>
            <button type="submit" class="w-full py-3 rounded-2xl bg-cyan-600 text-white font-black text-xs uppercase tracking-widest hover:bg-cyan-500 transition-all shadow-lg">
                Atualizar Senha
            </button>
        </form>
    </div>
</div>

<script>
    function openModal(id) { 
        document.getElementById(id).classList.add('open'); 
        if(id === 'modal-create') {
            updatePermsByRole('operator', 'perms-container-create');
        }
    }
    function closeModal(id) { document.getElementById(id).classList.remove('open'); }
    function closeOnBg(e, id) { if (e.target === e.currentTarget) closeModal(id); }

    function updatePermsByRole(role, containerId) {
        const container = document.getElementById(containerId);
        const checkboxes = container.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => {
            if(role === 'admin') {
                cb.checked = true;
            } else {
                // Padrão para Colaborador: Suporte e Atendimento
                cb.checked = (cb.value === 'dashboard' || cb.value === 'chamados' || cb.value === 'modulo_tickets');
            }
        });
    }

    // Auto-update perms on role change
    document.querySelector('#modal-create select[name="role"]').addEventListener('change', function() {
        updatePermsByRole(this.value, 'perms-container-create');
    });
    document.getElementById('edit_role').addEventListener('change', function() {
        updatePermsByRole(this.value, 'edit_perms_list');
    });

    function openEdit(u) {
        document.getElementById('edit_uid').value   = u.id;
        document.getElementById('edit_nome').value  = u.nome || '';
        document.getElementById('edit_email').value = u.email || '';
        document.getElementById('edit_role').value  = u.role || 'operator';
        
        const perms = JSON.parse(u.permissoes || '[]');
        const container = document.getElementById('edit_perms_list');
        container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.checked = perms.includes(cb.value);
        });
        
        openModal('modal-edit');
    }

    function openPass(uid, username) {
        document.getElementById('pass_uid').value = uid;
        document.getElementById('pass_username').textContent = '@' + username;
        openModal('modal-pass');
    }
</script>

<?php require_once 'includes/footer.php'; ?>
