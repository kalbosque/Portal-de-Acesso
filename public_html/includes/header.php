<?php
require_once __DIR__ . '/config.php';
$pageTitle = $pageTitle ?? APP_NAME . ' Premium';
?>
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <script>
        // Init theme immediately to avoid flash 
        if(localStorage.getItem('theme') === 'light') { document.documentElement.classList.add('light-mode'); }
    </script>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= htmlspecialchars($pageTitle) ?></title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        indigo: {
                            400: 'color-mix(in srgb, var(--app-color) 80%, white)',
                            500: 'var(--app-color)',
                            600: 'color-mix(in srgb, var(--app-color) 80%, black)',
                            900: 'color-mix(in srgb, var(--app-color) 40%, black)'
                        }
                    }
                }
            }
        }
    </script>
    
    <?php if(!isset($hideChartJs)): ?>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <?php endif; ?>
    <script src="js/agent_handshake.js"></script>

    <style>
        :root { --app-color: <?= APP_COLOR ?>; }
        body { font-family: 'Inter', sans-serif; background-color: #0f172a; color: #f8fafc; transition: background-color 0.3s, color 0.3s; letter-spacing: -0.01em; }
        h1, h2, h3, h4, .font-premium { font-family: 'Outfit', sans-serif; }
        .glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.05); }
        .glass-input { background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255,255,255,0.1); color: #f8fafc; outline: none; transition: all 0.3s ease;}
        .glass-input:focus { border-color: rgba(99, 102, 241, 0.5); box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2); }
        .gradient-text { background-clip: text; -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .hover-card:hover { transform: translateY(-4px); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.4), 0 10px 10px -5px rgba(0, 0, 0, 0.2); }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #1e293b; }
        ::-webkit-scrollbar-thumb { background: #475569; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #64748b; }
        .glass-modal { background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(16px); }

        /* High Contrast Light Mode (Harmonized 2.0) */
        html.light-mode body { background-color: #f1f5f9; color: #0f172a; }
        html.light-mode .glass-panel { background: #ffffff !important; border: 1px solid #e2e8f0 !important; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -2px rgba(0,0,0,0.05); backdrop-filter: none !important; }
        html.light-mode .text-white, html.light-mode .font-bold, html.light-mode .font-black { color: #000000 !important; }
        html.light-mode .text-slate-400, html.light-mode .text-slate-300, html.light-mode .text-slate-500 { color: #475569 !important; font-weight: 500 !important; }
        html.light-mode .text-slate-600 { color: #334155 !important; font-weight: 600 !important; }
        html.light-mode .gradient-text { background: transparent; -webkit-text-fill-color: #000000; }
        html.light-mode .bg-slate-800, html.light-mode .bg-slate-800\/50, html.light-mode .bg-slate-800\/30, html.light-mode .bg-slate-800\/20, html.light-mode .bg-slate-800\/10 { background-color: #f8fafc !important; border: 1px solid #e2e8f0 !important; color: #0f172a !important; }
        html.light-mode .bg-slate-900\/60, html.light-mode .bg-slate-900\/50, html.light-mode .bg-slate-900\/40 { background-color: #ffffff !important; border: 1px solid #e2e8f0 !important; color: #0f172a !important; }
        html.light-mode .border-slate-700\/50, html.light-mode .border-slate-700\/30, html.light-mode .border-slate-700, html.light-mode .border-white\/5, html.light-mode .border-white\/10 { border-color: #e2e8f0 !important; }
        html.light-mode .glass-input { background: #ffffff !important; border: 1.5px solid #cbd5e1 !important; color: #000000 !important; }
        html.light-mode .glass-input:focus { border-color: #6366f1 !important; box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1) !important; }
        html.light-mode .bg-white\/20, html.light-mode .bg-white\/10, html.light-mode .bg-white\/5 { background-color: #f1f5f9 !important; border: 1px solid #e2e8f0 !important; }
        html.light-mode ::-webkit-scrollbar-track { background: #f8fafc; }
        html.light-mode ::-webkit-scrollbar-thumb { background: #cbd5e1; }
        html.light-mode .glass-modal { background: #ffffff !important; border: 1px solid #e2e8f0 !important; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.15); }
        .nav-shell { border-bottom: 1px solid rgba(255,255,255,0.08); backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 18px 40px rgba(15, 23, 42, 0.28); }
        .nav-pill { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.06); border-radius: 1.25rem; padding: 0.35rem; }
        .nav-link { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.65rem 0.9rem; border-radius: 0.95rem; color: #94a3b8; font-size: 0.72rem; font-weight: 900; text-transform: uppercase; letter-spacing: 0.16em; transition: all 0.2s ease; white-space: nowrap; }
        .nav-link:hover { color: #ffffff; background: rgba(255,255,255,0.06); }
        .nav-link.is-active { background: var(--app-color); color: #ffffff; box-shadow: 0 10px 18px color-mix(in srgb, var(--app-color) 32%, transparent); }
        html.light-mode .nav-shell { border-bottom-color: rgba(226,232,240,0.9); box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08); }
        html.light-mode .nav-pill { background: #f8fafc; border-color: #e2e8f0; }
        html.light-mode .nav-link { color: #64748b; }
        html.light-mode .nav-link:hover { color: #0f172a; background: #e2e8f0; }
        html.light-mode .nav-link.is-active { color: #ffffff; }

        /* Animações do Avatar do Usuário (Contador) */
        .contador-head { animation: head-bob 3s ease-in-out infinite; transform-origin: 65px 92px; }
        .contador-arm-l { animation: arm-swing-l 3s ease-in-out infinite; transform-origin: 43px 90px; }
        .contador-arm-r { animation: arm-swing-r 3s ease-in-out infinite; transform-origin: 87px 90px; }
        .contador-leg-l { animation: leg-swing-l 3s ease-in-out infinite; transform-origin: 55px 118px; }
        .contador-leg-r { animation: leg-swing-r 3s ease-in-out infinite; transform-origin: 75px 118px; }

        @keyframes head-bob {
            0%, 100% { transform: rotate(0deg) translateY(0); }
            50% { transform: rotate(4deg) translateY(-3px); }
        }
        @keyframes arm-swing-l {
            0%, 100% { transform: rotate(0deg); }
            50% { transform: rotate(-20deg); }
        }
        @keyframes arm-swing-r {
            0%, 100% { transform: rotate(0deg); }
            50% { transform: rotate(20deg); }
        }
        @keyframes leg-swing-l {
            0%, 100% { transform: rotate(0deg); }
            50% { transform: rotate(15deg); }
        }
        @keyframes leg-swing-r {
            0%, 100% { transform: rotate(0deg); }
            50% { transform: rotate(-15deg); }
        }
    </style>
</head>
<body class="min-h-screen flex flex-col relative overflow-x-hidden">
    <!-- Ambient Background effects -->
    <div class="fixed top-0 left-0 w-full h-full overflow-hidden -z-10 pointer-events-none">
        <div class="absolute -top-[20%] -left-[10%] w-[50%] h-[50%] rounded-full bg-indigo-600/10 blur-[120px]"></div>
        <div class="absolute bottom-[10%] -right-[10%] w-[40%] h-[40%] rounded-full bg-fuchsia-600/10 blur-[120px]"></div>
    </div>

    <?php if (!isset($hideNav)): ?>
    <!-- Navigation -->
    <nav class="glass-panel nav-shell sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
            
            <!-- Esquerda: Logo e Nome -->
            <div class="flex items-center gap-4 flex-shrink-0">
                <?php 
                $homeUrl = (isset($_SESSION['user_role']) && $_SESSION['user_role'] === 'admin') ? 'index.php' : 'chamados.php';
                ?>
                <a href="<?= $homeUrl ?>" class="flex items-center gap-3 group hover:opacity-90 transition-opacity">
                    <?php if (!empty(APP_LOGO_URL)): ?>
                        <img src="<?= htmlspecialchars(APP_LOGO_URL) ?>" alt="Logo" class="h-10 w-auto object-contain rounded-xl shadow-lg border border-white/5" />
                    <?php else: ?>
                        <div class="w-10 h-10 rounded-2xl bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center shadow-lg border border-white/10">
                            <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"></path></svg>
                        </div>
                    <?php endif; ?>
                    <div class="hidden sm:flex flex-col leading-tight">
                        <h1 class="text-lg font-black tracking-tighter text-white html-light:text-black"><?= htmlspecialchars(APP_NAME) ?></h1>
                        <span class="text-[8px] text-slate-500 font-bold uppercase tracking-widest italic"><?= htmlspecialchars(APP_TAGLINE) ?></span>
                    </div>
                </a>
            </div>

            <!-- Centro: Menu Desktop -->
            <div class="hidden lg:flex items-center gap-1 nav-pill flex-1 justify-center max-w-3xl mx-8">
                <?php
                $current_page = basename($_SERVER['PHP_SELF']);
                $menus = [];
                if (function_exists('hasPermission')) {
                    if (hasPermission('dashboard')) $menus['index.php'] = 'Painel';
                    if (hasPermission('equipamentos')) $menus['impressoras.php'] = 'Equipamentos';
                    if (hasPermission('relatorios')) $menus['relatorios.php'] = 'Relatórios';
                    if (hasPermission('chamados')) $menus['chamados.php'] = 'Suporte TI';
                    if (MODULO_ATENDIMENTO && (isAdmin() || hasPermission('modulo_tickets'))) $menus[URL_ATENDIMENTO] = 'Tickets';
                }
                if (function_exists('isAdmin') && isAdmin()) {
                    $menus['monitor_usuarios.php'] = 'Monitor';
                    $menus['usuarios.php'] = 'Usuários';
                    $menus['cofre_senhas.php'] = 'Cofre';
                    $menus['configuracoes.php'] = 'Configurações';
                }

                foreach ($menus as $file => $label) {
                    $isActive = ($current_page === $file);
                    $textColor = $isActive ? "nav-link is-active" : "nav-link";
                    $isExternal = (strpos($file, 'http') === 0);
                    ?>
                    <a href="<?= $file ?>" <?= $isExternal ? 'target="_blank"' : '' ?> class="<?= $textColor ?>">
                        <?= $label ?>
                    </a>
                <?php } ?>
            </div>

            <!-- Direita: Ações e Sair -->
            <div class="flex items-center gap-3 ml-auto flex-shrink-0">
                <!-- Relógio -->
                <div class="hidden xl:flex flex-col items-end leading-none mr-2">
                    <span id="live-date" class="text-[8px] text-slate-500 font-bold uppercase mb-0.5">00/00/0000</span>
                    <span id="live-clock" class="text-xs font-black font-mono" style="color: var(--app-color);">00:00:00</span>
                </div>

                <button onclick="toggleTheme()" class="w-9 h-9 inline-flex items-center justify-center rounded-xl bg-white/5 border border-white/5 text-slate-400 hover:text-white hover:bg-white/10 transition-all">
                    <svg id="icon-sun" class="w-5 h-5 hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                    <svg id="icon-moon" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
                </button>

                <!-- Perfil com Nome -->
                <button onclick="document.getElementById('profileModal').classList.remove('hidden')" class="hidden sm:flex items-center gap-3 px-3 py-1.5 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10 transition-all group">
                    <div class="text-right hidden sm:block">
                        <span class="block text-slate-200 text-xs font-black leading-none group-hover:text-indigo-400 transition-colors"><?= htmlspecialchars($_SESSION['user_name'] ?? 'Usuário') ?></span>
                        <span class="text-[8px] text-slate-500 font-bold uppercase tracking-widest">Colaborador</span>
                    </div>
                    <div class="w-10 h-10 rounded-full flex items-center justify-center shadow-lg border-2 border-indigo-400 bg-slate-900 group-hover:scale-110 transition-transform">
                        <svg class="w-6 h-6 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                        </svg>
                    </div>
                </button>

                <!-- SAIR -->
                <a href="logout.php" class="flex items-center gap-2 px-4 py-2 rounded-xl bg-rose-600 text-white hover:bg-rose-500 transition-all text-[10px] font-black uppercase tracking-widest shadow-lg shadow-rose-900/20 flex-shrink-0" title="Sair do Sistema">
                    <span>SAIR</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path></svg>
                </a>

                <!-- Mobile Button -->
                <button onclick="toggleMobileMenu()" class="lg:hidden p-2 text-slate-400 hover:text-white">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16m-7 6h7"></path></svg>
                </button>
            </div>
        </div>
    </nav>

    <!-- Modal Perfil (Movido para fora do <nav> para evitar bug de stacking context) -->
    <div id="profileModal" class="hidden fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 backdrop-blur-sm p-4">
        <div class="glass-panel w-full max-w-md p-8 rounded-3xl border border-white/10 shadow-2xl relative animate-[fadeIn_0.2s_ease-out]">
            <button onclick="document.getElementById('profileModal').classList.add('hidden')" class="absolute top-6 right-6 text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
            <h3 class="text-xl font-bold text-white mb-2 html-light:text-black">Segurança da Conta</h3>
            <p class="text-slate-400 text-sm mb-6">Mantenha sua senha atualizada para garantir a integridade dos dados.</p>
            
            <form id="changePassForm" class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Senha Atual</label>
                    <input type="password" name="current_password" required class="glass-input w-full px-4 py-3 rounded-xl">
                </div>
                <div>
                    <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">Nova Senha</label>
                    <input type="password" name="new_password" required class="glass-input w-full px-4 py-3 rounded-xl">
                </div>
                <div id="profileMsg" class="text-xs font-bold hidden p-3 rounded-xl border"></div>
                <button type="submit" class="w-full bg-gradient-to-r from-indigo-500 to-indigo-600 text-white font-bold py-3.5 rounded-xl hover:shadow-lg hover:shadow-indigo-500/25 transition-all">Atualizar Acesso</button>
            </form>
        </div>
    </div>
    <!-- Mobile Navigation Drawer -->
    <div id="mobileDrawer" class="fixed inset-0 z-[100] hidden lg:hidden">
        <div class="absolute inset-0 bg-slate-950/80 backdrop-blur-md" onclick="toggleMobileMenu()"></div>
        <div class="absolute right-0 top-0 bottom-0 w-80 bg-slate-900 border-l border-white/10 p-8 shadow-2xl transition-transform duration-300 translate-x-full" id="drawerContent">
            <div class="flex justify-between items-center mb-10">
                <h2 class="text-xl font-bold text-white uppercase tracking-widest">Menu</h2>
                <button onclick="toggleMobileMenu()" class="p-2 text-slate-400 hover:text-white"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
            </div>
            <div class="space-y-4">
                <?php foreach ($menus as $file => $label): ?>
                    <a href="<?= $file ?>" class="block px-6 py-4 rounded-2xl text-lg font-bold <?= basename($_SERVER['PHP_SELF']) === $file ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30' : 'text-slate-400 hover:text-white hover:bg-white/5' ?>">
                        <?= $label ?>
                    </a>
                <?php endforeach; ?>
                <div class="pt-8 border-t border-white/5 mt-8 space-y-4">
                    <button onclick="toggleTheme()" class="w-full text-left px-6 py-4 rounded-2xl text-slate-400 hover:text-white hover:bg-white/5 font-bold flex items-center justify-between">
                        Alternar Tema
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
                    </button>
                    <a href="logout.php" class="block px-6 py-4 rounded-2xl text-rose-400 hover:bg-rose-500/10 font-bold">
                        Sair da Conta
                    </a>
                </div>
            </div>
        </div>
    </div>
    <main id="app-container" class="flex-grow max-w-7xl w-full mx-auto px-4 pt-4 pb-12 relative space-y-10">
    <?php endif; ?>

    <script>
        function toggleTheme() {
            const html = document.documentElement;
            html.classList.toggle('light-mode');
            const isLight = html.classList.contains('light-mode');
            localStorage.setItem('theme', isLight ? 'light' : 'dark');
            updateThemeIcons(isLight);
        }
        function updateThemeIcons(isLight) {
            const sun = document.getElementById('icon-sun');
            const moon = document.getElementById('icon-moon');
            if(sun && moon) {
                if(isLight) { sun.classList.remove('hidden'); moon.classList.add('hidden'); }
                else { sun.classList.add('hidden'); moon.classList.remove('hidden'); }
            }
        }
        document.addEventListener('DOMContentLoaded', () => {
            updateThemeIcons(document.documentElement.classList.contains('light-mode'));
            
            // Relógio e Data em tempo real
            function updateClock() {
                const now = new Date();
                const clock = document.getElementById('live-clock');
                const dateEl = document.getElementById('live-date');
                if(clock) {
                    clock.textContent = now.toLocaleTimeString('pt-BR', { hour12: false });
                }
                if(dateEl) {
                    dateEl.textContent = now.toLocaleDateString('pt-BR');
                }
            }
            setInterval(updateClock, 1000);
            updateClock();

            // Profile logic as before...
            const cpForm = document.getElementById('changePassForm');
            if(cpForm) {
                cpForm.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const msg = document.getElementById('profileMsg');
                    const btn = cpForm.querySelector('button');
                    btn.disabled = true;
                    btn.textContent = 'Processando...';
                    
                    try {
                        const formData = new FormData(cpForm);
                        const data = Object.fromEntries(formData.entries());
                        const res = await fetch('api/profile.php', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(data)
                        }).then(r => r.json());

                        msg.classList.remove('hidden');
                        if(res.success) {
                            msg.className = 'text-xs font-bold p-3 rounded-xl border bg-emerald-500/10 text-emerald-400 border-emerald-500/20 mb-4';
                            msg.textContent = 'Senha atualizada com sucesso!';
                            cpForm.reset();
                            setTimeout(() => { document.getElementById('profileModal').classList.add('hidden'); msg.classList.add('hidden'); }, 2000);
                        } else {
                            msg.className = 'text-xs font-bold p-3 rounded-xl border bg-rose-500/10 text-rose-400 border-rose-500/20 mb-4';
                            msg.textContent = res.error || 'Erro ao mudar senha.';
                        }
                    } catch(err) { console.error(err); }
                    btn.disabled = false;
                    btn.textContent = 'Atualizar Acesso';
                });
            }
        });

        // Mobile Menu Logic
        function toggleMobileMenu() {
            const drawer = document.getElementById('mobileDrawer');
            const content = document.getElementById('drawerContent');
            if (drawer.classList.contains('hidden')) {
                drawer.classList.remove('hidden');
                setTimeout(() => content.classList.remove('translate-x-full'), 10);
            } else {
                content.classList.add('translate-x-full');
                setTimeout(() => drawer.classList.add('hidden'), 300);
            }
        }
    </script>
