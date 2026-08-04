<?php
ob_start();
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

// Redireciona se já estiver logado
if (isset($_SESSION['user_id'])) {
    $redirect = ($_SESSION['user_role'] === 'admin') ? 'index.php' : 'chamados.php';
    header('Location: ' . $redirect);
    exit;
}

$error = '';
$success = '';
$action = $_POST['action'] ?? 'login';

// SEGURANÇA: Validar Token CSRF em todas as ações de POST
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!validateCsrfToken($_POST['csrf_token'] ?? '')) {
        $error = 'Erro de segurança: Token inválido. Tente novamente.';
        $action = 'error'; // Bloqueia a execução
    }
}

if ($action === 'cadastro') {
    $nome     = trim($_POST['nome']     ?? '');
    $email    = trim($_POST['email']    ?? '');
    $username = trim($_POST['username'] ?? '');
    $password  = $_POST['password']  ?? '';
    $password2 = $_POST['password2'] ?? '';

    if (!$nome || !$email || !$username || !$password) {
        $error = 'Preencha todos os campos.';
    } elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $error = 'Informe um e-mail válido.';
    } elseif (strlen($password) < 6 || strlen($password) > 8) {
        $error = 'A senha precisa ter entre 6 e 8 caracteres.';
    } elseif ($password !== $password2) {
        $error = 'As senhas não coincidem.';
    } else {
        // Verifica username e email duplicados
        $chk = $pdo->prepare("SELECT id FROM usuarios WHERE username = ? OR email = ?");
        $chk->execute([$username, $email]);
        if ($chk->fetch()) {
            $error = 'Este nome de usuário ou e-mail já está em uso.';
        } else {
            $hash = password_hash($password, PASSWORD_BCRYPT);
            $stmt = $pdo->prepare(
                "INSERT INTO usuarios (nome, email, username, password_hash, role, status_conta, permissoes)
                 VALUES (?, ?, ?, ?, 'operator', 'ativo', '[\"dashboard\", \"chamados\", \"modulo_tickets\"]')"
            );
            $stmt->execute([$nome, $email, $username, $hash]);
            $success = 'Cadastro realizado com sucesso! Você já pode fazer login e acessar o sistema.';
            $action = 'login';
        }
    }

} elseif ($action === 'reset_senha') {
    $login_id = trim($_POST['login_id'] ?? '');

    if (!$login_id) {
        $error = 'Informe seu e-mail ou nome de usuário.';
    } else {
        // Busca por email ou username (Insensível a maiúsculas/minúsculas)
        $stmt = $pdo->prepare("SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?) LIMIT 1");
        $stmt->execute([$login_id, $login_id]);
        $user = $stmt->fetch();

        if (!$user) {
            // Mensagem neutra para evitar descoberta de e-mails existentes
            $success = 'Se o usuário existir, uma senha temporária foi gerada. Verifique com o suporte.';
        } else {
            $temp = strtoupper(substr(md5(uniqid()), 0, 8));
            $hash = password_hash($temp, PASSWORD_BCRYPT);
            $pdo->prepare("UPDATE usuarios SET senha_temp = ? WHERE id = ?")->execute([$hash, $user['id']]);
            $success = "Senha temporária gerada: <strong class='text-white text-lg tracking-widest font-mono'>{$temp}</strong><br><span class='text-xs'>Anote esta senha e use-a para entrar. Troque-a logo após o acesso.</span>";
        }
    }

} elseif ($action === 'login' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $login_id = trim($_POST['login_id'] ?? '');
    $password  = $_POST['password'] ?? '';
    $intent    = $_POST['intent'] ?? 'suporte';

    if ($login_id && $password) {
        // Aceita login por e-mail OU username (Insensível a maiúsculas/minúsculas)
        $stmt = $pdo->prepare("SELECT * FROM usuarios WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?) LIMIT 1");
        $stmt->execute([$login_id, $login_id]);
        $user = $stmt->fetch();

        if ($user) {
            $status = $user['status_conta'] ?? 'ativo';

            if ($status === 'pendente') {
                $error = 'Sua conta está aguardando aprovação do administrador.';
            } elseif ($status === 'bloqueado') {
                $error = 'Sua conta foi bloqueada. Entre em contato com o administrador.';
            } elseif (
                password_verify($password, $user['password_hash']) ||
                (!empty($user['senha_temp']) && password_verify($password, $user['senha_temp']))
            ) {
                if (!empty($user['senha_temp']) && password_verify($password, $user['senha_temp'])) {
                    $pdo->prepare("UPDATE usuarios SET senha_temp = NULL WHERE id = ?")->execute([$user['id']]);
                }

                // SEGURANÇA: Regenerar ID da sessão após o login
                session_regenerate_id(true);

                $_SESSION['user_id']   = $user['id'];
                $_SESSION['user_name'] = $user['nome'] ?: $user['username'];
                $_SESSION['username']  = $user['username'];
                $_SESSION['user_role'] = $user['role'];
                $_SESSION['maquina_vinculada'] = $user['maquina_vinculada'] ?? null;

                $permsRaw = isset($user['permissoes']) && !is_null($user['permissoes']) ? $user['permissoes'] : '[]';
                $_SESSION['user_perms'] = json_decode((string) $permsRaw, true) ?: [];

                try {
                    $realIp = getRealIp();
                    $pdo->prepare("INSERT INTO historico_acessos (usuario_id, usuario_nome, ip, acao) VALUES (?, ?, ?, ?)")
                        ->execute([$user['id'], $_SESSION['user_name'], $realIp, "Login ($intent)"]);
                } catch (Exception $e) {}

                // Operador tentando acessar o portal de Gestão → bloqueia com mensagem
                if ($user['role'] !== 'admin' && $intent === 'gestao') {
                    // Destrói a sessão criada pois acesso não é permitido neste portal
                    session_unset();
                    session_destroy();
                    $error = '🔒 Este portal é exclusivo para Administradores. Use o portal de Suporte TI para acessar o sistema.';
                } else {
                    $redirectPage = ($user['role'] === 'admin')
                        ? (($intent === 'suporte') ? 'chamados.php' : 'index.php')
                        : 'chamados.php';

                    header('Location: ' . $redirectPage);
                    exit;
                }
            } else {
                $error = 'E-mail/usuário ou senha incorretos.';
            }
        } else {
            $error = 'E-mail/usuário ou senha incorretos.';
        }
    } else {
        $error = 'Por favor, preencha todos os campos.';
    }
}

$pageTitle = 'Portal de Acesso | ' . APP_NAME;
$hideNav = true;
$hideChartJs = true;
require_once 'includes/header.php';
?>

<style>
    .portal-card {
        transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
        cursor: pointer;
    }

    .portal-card:hover {
        transform: translateY(-10px) scale(1.02);
        box-shadow: 0 30px 60px -12px rgba(0, 0, 0, 0.5);
    }

    .login-container {
        display: none;
        opacity: 0;
        transform: translateY(20px);
        transition: all 0.5s ease-out;
    }

    .login-container.show {
        display: block;
        opacity: 1;
        transform: translateY(0);
    }

    .tab-btn {
        transition: all 0.3s ease;
    }

    .tab-btn.active {
        color: white;
    }

    .tab-indicator {
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
</style>

<div class="flex items-center justify-center min-h-[90vh] px-4 relative">
    <div id="portalSelection" class="w-full max-w-7xl transition-all duration-700">
        <div class="text-center mb-16 animate-[slideIn_0.8s_ease-out] flex flex-col items-center">
            <?php if (!empty(APP_LOGO_URL)): ?>
                <div class="mb-8 p-3 bg-white rounded-3xl shadow-2xl border border-white/20 html-light:bg-transparent html-light:shadow-none">
                    <img src="<?= htmlspecialchars(APP_LOGO_URL) ?>" alt="Logo" class="max-w-full h-[80px] md:h-[100px] object-contain drop-shadow-2xl" />
                </div>
            <?php else: ?>
                <div class="w-20 h-20 rounded-[2rem] bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-lg shadow-indigo-500/30 mb-8 border border-white/10">
                    <svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"></path></svg>
                </div>
            <?php endif; ?>

            <h1 class="text-5xl font-black text-white mb-4 tracking-tighter uppercase html-light:text-black">
                Portal de Acesso <span class="text-indigo-500"></span>
            </h1>
            <p class="text-slate-500 font-bold uppercase tracking-[0.4em] text-xs html-light:text-slate-700">
                Escolha o seu ponto de entrada
            </p>
        </div>

        <div class="flex flex-wrap justify-center gap-8 items-stretch">
            
            <?php if (MODULO_SUPORTE): ?>
            <div onclick="showLogin('suporte')" class="portal-card glass-panel group p-10 rounded-[3rem] border border-blue-500/20 hover:border-blue-500/50 relative overflow-hidden flex-1 min-w-[320px] max-w-[400px] flex flex-col">
                <div class="absolute -top-6 -right-6 text-blue-500/5 group-hover:text-blue-500/10 transition-all duration-500 pointer-events-none transform group-hover:scale-110 group-hover:-rotate-12">
                    <svg class="w-48 h-48" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z"/></svg>
                </div>
                <div class="relative z-10 flex flex-col items-center text-center h-full">
                    <div class="w-20 h-20 rounded-3xl bg-blue-500/10 flex items-center justify-center text-blue-400 mb-8 border border-blue-500/20 shadow-xl group-hover:bg-blue-500 group-hover:text-white transition-all duration-500">
                        <svg class="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                    </div>
                    <h3 class="text-3xl font-black text-white mb-3 tracking-tight html-light:text-black uppercase">CENTRAL DE SUPORTE</h3>
                    <p class="text-slate-400 font-medium text-sm leading-relaxed max-w-[250px] html-light:text-slate-700">
                        Abertura de chamados tecnicos, notas de solucao e auxilio ao colaborador.
                    </p>
                    
                    <?php if (!empty(GUIA_SUPORTE_URL)): ?>
                    <a href="<?= htmlspecialchars(GUIA_SUPORTE_URL) ?>" target="_blank" onclick="event.stopPropagation();" class="mt-4 flex items-center gap-2 text-[10px] font-black text-blue-400 hover:text-white transition-colors uppercase tracking-widest group/link">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path></svg>
                        <span>Ver Guia de Utilização</span>
                    </a>
                    <?php endif; ?>

                    <div class="mt-auto pt-6">
                        <div class="px-6 py-2 rounded-full border border-blue-500/30 text-blue-400 text-[10px] font-black uppercase tracking-widest group-hover:bg-blue-500 group-hover:text-white transition-all inline-block">
                            Acesso Rapido
                        </div>
                    </div>
                </div>
            </div>
            <?php endif; ?>

            <?php if (MODULO_IMPRESSAO): ?>
            <div onclick="showLogin('gestao')" class="portal-card glass-panel group p-10 rounded-[3rem] border border-indigo-500/20 hover:border-indigo-500/50 relative overflow-hidden flex-1 min-w-[320px] max-w-[400px] flex flex-col">
                <div class="absolute -top-6 -right-6 text-indigo-500/20 group-hover:text-indigo-500/40 transition-all duration-500 pointer-events-none transform group-hover:scale-110 group-hover:rotate-12">
                    <svg class="w-48 h-48" fill="currentColor" viewBox="0 0 24 24"><path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm-1-9H6v4h12V3z"/></svg>
                </div>
                <div class="relative z-10 flex flex-col items-center text-center h-full">
                    <div class="w-20 h-20 rounded-3xl bg-indigo-500/10 flex items-center justify-center text-indigo-300 mb-8 border border-indigo-500/20 shadow-xl group-hover:bg-indigo-500 group-hover:text-white transition-all duration-500">
                        <svg class="w-10 h-10" fill="currentColor" viewBox="0 0 24 24"><path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm-1-9H6v4h12V3z"/></svg>
                    </div>
                    <h3 class="text-3xl font-black text-white mb-3 tracking-tight html-light:text-black uppercase">CONTROLE DE GESTÃO</h3>
                    <p class="text-slate-400 font-medium text-sm leading-relaxed max-w-[250px] html-light:text-slate-700">
                        Monitoramento de impressao, relatorios de custo e administracao do sistema.
                    </p>
                    <div class="mt-auto pt-8">
                        <div class="px-6 py-2 rounded-full border border-indigo-500/30 text-indigo-400 text-[10px] font-black uppercase tracking-widest group-hover:bg-indigo-500 group-hover:text-white transition-all inline-block">
                            Acesso Restrito
                        </div>
                    </div>
                </div>
            </div>
            <?php endif; ?>


            <?php if (MODULO_ATENDIMENTO): ?>
            <a href="<?= htmlspecialchars(URL_ATENDIMENTO) ?>" target="_blank" class="portal-card glass-panel group p-10 rounded-[3rem] border border-emerald-500/20 hover:border-emerald-500/50 relative overflow-hidden block no-underline flex-1 min-w-[320px] max-w-[400px] flex flex-col">
                <div class="absolute -top-6 -right-6 text-emerald-500/5 group-hover:text-emerald-500/10 transition-all duration-500 pointer-events-none transform group-hover:scale-110 group-hover:rotate-12">
                    <svg class="w-48 h-48" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14.5v-9l6 4.5-6 4.5z"/></svg>
                </div>
                <div class="relative z-10 flex flex-col items-center text-center h-full">
                    <div class="w-20 h-20 rounded-3xl bg-emerald-500/10 flex items-center justify-center text-emerald-400 mb-8 border border-emerald-500/20 shadow-xl group-hover:bg-emerald-500 group-hover:text-white transition-all duration-500">
                        <svg class="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"></path></svg>
                    </div>
                    <h3 class="text-3xl font-black text-white mb-3 tracking-tight html-light:text-black uppercase">ATENDIMENTO</h3>
                    <p class="text-slate-400 font-medium text-sm leading-relaxed max-w-[250px] html-light:text-slate-700">
                        Plataforma de gestão de mensagens e atendimento via WhatsApp.
                    </p>
                    <div class="mt-auto pt-8">
                        <div class="px-6 py-2 rounded-full border border-emerald-500/30 text-emerald-400 text-[10px] font-black uppercase tracking-widest group-hover:bg-emerald-500 group-hover:text-white transition-all inline-block">
                            Acesso Externo
                        </div>
                    </div>
                </div>
            </a>
            <?php endif; ?>

        </div>
    </div>

    <div id="loginFormContainer" class="login-container w-full max-w-md">
        <div class="glass-panel p-10 rounded-[3rem] border border-white/10 shadow-[0_50px_100px_-20px_rgba(0,0,0,0.5)] relative overflow-hidden">
            <button onclick="backToPortal()" class="absolute left-8 top-8 text-slate-500 hover:text-white transition-colors flex items-center gap-2 group">
                <svg class="w-5 h-5 group-hover:-translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
            </button>

            <div class="text-center mb-6">
                <div id="loginIcon" class="w-16 h-16 rounded-2xl mx-auto flex items-center justify-center text-white mb-5 shadow-xl border border-white/20"></div>
                <h2 id="loginTitle" class="text-2xl font-black text-white uppercase tracking-tight italic html-light:text-black">Acesso Identificado</h2>
                <p id="loginSubtitle" class="text-slate-500 text-[10px] font-black uppercase tracking-[0.2em] mt-1"></p>
            </div>

            <div class="relative flex bg-white/5 rounded-2xl p-1 mb-6 border border-white/5">
                <div id="tabIndicator" class="tab-indicator absolute top-1 bottom-1 rounded-xl bg-indigo-600 shadow-lg" style="width:33.33%;left:0"></div>
                <button id="tab_login" onclick="switchTab('login')" class="tab-btn active relative z-10 flex-1 py-2 text-[9px] font-black uppercase tracking-widest text-white">Login</button>
                <button id="tab_cadastro" onclick="switchTab('cadastro')" class="tab-btn relative z-10 flex-1 py-2 text-[9px] font-black uppercase tracking-widest text-slate-400">Cadastro</button>
                <button id="tab_reset" onclick="switchTab('reset')" class="tab-btn relative z-10 flex-1 py-2 text-[9px] font-black uppercase tracking-widest text-slate-400">Esqueci</button>
            </div>

            <?php if ($error): ?>
                <div class="mb-5 p-4 bg-rose-500/10 border-l-4 border-rose-500 text-rose-400 text-xs font-bold rounded-r-xl"><?= htmlspecialchars($error) ?></div>
            <?php endif; ?>
            <?php if ($success): ?>
                <div class="mb-5 p-4 bg-emerald-500/10 border-l-4 border-emerald-500 text-emerald-400 text-xs font-bold rounded-r-xl leading-relaxed"><?= $success ?></div>
            <?php endif; ?>

            <div id="form_login">
                <form action="login.php" method="POST" class="space-y-5">
                    <input type="hidden" name="action" value="login">
                    <input type="hidden" name="intent" id="loginIntent" value="suporte">
                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">E-mail ou Usuário</label>
                        <input type="text" name="login_id" required autocomplete="username" class="glass-input w-full px-6 py-4 rounded-2xl text-white font-bold html-light:text-black" placeholder="Digite seu e-mail ou usuário">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">Senha</label>
                        <div class="relative">
                            <input type="password" id="login_pass" name="password" required autocomplete="current-password" class="glass-input w-full px-6 py-4 rounded-2xl text-white font-bold html-light:text-black pr-16" placeholder="********">
                            <button type="button" onclick="togglePass('login_pass', this)" class="absolute right-5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-indigo-400 transition-colors">
                                <svg class="w-5 h-5 eye-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                            </button>
                        </div>
                    </div>
                    <button type="submit" id="submitBtn" class="w-full bg-indigo-600 text-white font-black text-xs uppercase tracking-[0.2em] py-5 rounded-2xl shadow-lg shadow-indigo-500/20 transition-all active:scale-95 border border-white/10 mt-2">
                        Entrar no Sistema
                    </button>
                </form>
            </div>

            <div id="form_cadastro" class="hidden">
                <form action="login.php" method="POST" class="space-y-4">
                    <input type="hidden" name="action" value="cadastro">
                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                    <input type="hidden" name="intent" class="intent-sync" value="suporte">
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">Nome Completo</label>
                        <input type="text" name="nome" required class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold html-light:text-black text-sm" placeholder="Seu nome completo">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">E-mail Corporativo</label>
                        <input type="email" name="email" required autocomplete="email" class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold html-light:text-black text-sm" placeholder="seu@email.com">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">Nome de Usuário</label>
                        <input type="text" name="username" required autocomplete="username" class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold html-light:text-black text-sm" placeholder="Escolha um usuário">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">Senha</label>
                        <input type="password" name="password" required autocomplete="new-password" class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold html-light:text-black text-sm" placeholder="De 6 a 8 caracteres">
                    </div>
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">Confirmar Senha</label>
                        <input type="password" name="password2" required autocomplete="new-password" class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold html-light:text-black text-sm" placeholder="Repita a senha">
                    </div>
                    <div class="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
                        <p class="text-[9px] text-emerald-400 font-black uppercase tracking-widest">Sua conta será ativada instantaneamente</p>
                    </div>
                    <button type="submit" class="w-full bg-emerald-600 text-white font-black text-xs uppercase tracking-[0.2em] py-4 rounded-2xl shadow-lg shadow-emerald-500/20 transition-all active:scale-95 border border-white/10">
                        Finalizar Cadastro
                    </button>
                </form>
            </div>

            <div id="form_reset" class="hidden">
                <div class="text-center mb-5 p-4 bg-indigo-500/10 border border-indigo-500/20 rounded-2xl">
                    <p class="text-[10px] text-indigo-300 font-bold leading-relaxed">Informe seu e-mail ou nome de usuário. O administrador gerará uma senha temporária.</p>
                </div>
                <form action="login.php" method="POST" class="space-y-5">
                    <input type="hidden" name="action" value="reset_senha">
                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                    <input type="hidden" name="intent" class="intent-sync" value="suporte">
                    <div>
                        <label class="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1 ml-1">E-mail ou Usuário</label>
                        <input type="text" name="login_id" required class="glass-input w-full px-6 py-4 rounded-2xl text-white font-bold html-light:text-black" placeholder="seu@email.com ou nome_usuario">
                    </div>
                    <button type="submit" class="w-full bg-amber-600 text-white font-black text-xs uppercase tracking-[0.2em] py-5 rounded-2xl shadow-lg shadow-amber-500/20 transition-all active:scale-95 border border-white/10">
                        Gerar Senha Temporária
                    </button>
                </form>
            </div>
        </div>
    </div>
</div>

<script>
    const tabPositions = { login: '0', cadastro: '33.33%', reset: '66.66%' };

    function switchTab(tab) {
        document.getElementById('tabIndicator').style.left = tabPositions[tab];

        ['login', 'cadastro', 'reset'].forEach((t) => {
            document.getElementById(`tab_${t}`).classList.toggle('active', t === tab);
            document.getElementById(`tab_${t}`).classList.toggle('text-white', t === tab);
            document.getElementById(`tab_${t}`).classList.toggle('text-slate-400', t !== tab);
            document.getElementById(`form_${t}`).classList.toggle('hidden', t !== tab);
        });
    }

    function showLogin(intent) {
        const portal = document.getElementById('portalSelection');
        const login = document.getElementById('loginFormContainer');
        
        // Sincroniza o intent em todos os formulários
        document.getElementById('loginIntent').value = intent;
        document.querySelectorAll('.intent-sync').forEach(el => el.value = intent);

        const isSupport = intent === 'suporte';
        document.getElementById('loginTitle').textContent = isSupport ? 'Central de Suporte' : 'Gestao de Impressao';
        document.getElementById('loginSubtitle').textContent = isSupport ? 'Portal do Colaborador' : 'Acesso Administrativo';

        const icon = document.getElementById('loginIcon');
        icon.className = `w-16 h-16 rounded-2xl mx-auto flex items-center justify-center text-white mb-5 shadow-xl border border-white/20 ${isSupport ? 'bg-blue-600' : 'bg-indigo-600'}`;
        icon.innerHTML = isSupport
            ? '<svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>'
            : '<svg class="w-8 h-8" fill="currentColor" viewBox="0 0 24 24"><path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm-1-9H6v4h12V3z"/></svg>';

        portal.style.opacity = '0';
        portal.style.transform = 'scale(0.9)';

        setTimeout(() => {
            portal.style.display = 'none';
            login.style.display = 'block';
            setTimeout(() => login.classList.add('show'), 50);
        }, 400);
    }

    function togglePass(id, btn) {
        const input = document.getElementById(id);
        const icon = btn.querySelector('.eye-icon');
        if (input.type === 'password') {
            input.type = 'text';
            // Ícone de olho riscado (ocultar)
            icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18"></path>';
        } else {
            input.type = 'password';
            // Ícone de olho aberto (mostrar)
            icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>';
        }
    }

    function backToPortal() {
        const portal = document.getElementById('portalSelection');
        const login = document.getElementById('loginFormContainer');

        login.classList.remove('show');
        setTimeout(() => {
            login.style.display = 'none';
            portal.style.display = 'block';
            setTimeout(() => {
                portal.style.opacity = '1';
                portal.style.transform = 'scale(1)';
            }, 50);
        }, 400);
    }

    <?php if ($error || $success): ?>
    window.onload = () => {
        showLogin('<?= htmlspecialchars($_POST['intent'] ?? 'suporte') ?>');
        <?php
        // Usa a variável $action do PHP (que pode ter sido alterada de 'cadastro' para 'login' em caso de sucesso)
        if ($action === 'cadastro') {
            echo "switchTab('cadastro');";
        } elseif ($action === 'reset_senha') {
            echo "switchTab('reset');";
        } else {
            echo "switchTab('login');";
        }
        ?>
    };
    <?php endif; ?>
</script>

<?php require_once 'includes/footer.php'; ?>
