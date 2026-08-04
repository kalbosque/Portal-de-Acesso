<?php
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

if (!isAdmin()) {
    header('Location: index.php');
    exit;
}

$pageTitle = 'Cofre de Senhas | ' . APP_NAME;
require_once 'includes/header.php';
?>

<style>
    /* === Cofre de Senhas — Premium Glassmorphism === */
    .cofre-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(370px, 1fr)); gap: 1.25rem; }
    .cofre-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 1.25rem;
        padding: 1.5rem;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .cofre-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--app-color), #a855f7);
        opacity: 0;
        transition: opacity 0.3s;
    }
    .cofre-card:hover { transform: translateY(-3px); border-color: rgba(255,255,255,0.12); }
    .cofre-card:hover::before { opacity: 1; }

    .cat-badge {
        display: inline-flex; align-items: center; gap: 0.35rem;
        padding: 0.3rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.65rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .cat-email   { background: rgba(59,130,246,0.12); color: #60a5fa; border: 1px solid rgba(59,130,246,0.2); }
    .cat-app     { background: rgba(168,85,247,0.12); color: #c084fc; border: 1px solid rgba(168,85,247,0.2); }
    .cat-web     { background: rgba(34,197,94,0.12);  color: #4ade80; border: 1px solid rgba(34,197,94,0.2); }
    .cat-rede    { background: rgba(249,115,22,0.12); color: #fb923c; border: 1px solid rgba(249,115,22,0.2); }
    .cat-sistema { background: rgba(236,72,153,0.12); color: #f472b6; border: 1px solid rgba(236,72,153,0.2); }
    .cat-outro   { background: rgba(148,163,184,0.1); color: #94a3b8; border: 1px solid rgba(148,163,184,0.2); }

    .senha-field {
        display: flex; align-items: center; gap: 0.5rem;
        background: rgba(15, 23, 42, 0.5);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 0.75rem;
        padding: 0.6rem 0.85rem;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        color: #94a3b8;
        letter-spacing: 0.15em;
    }
    .senha-field .senha-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .btn-icon {
        display: inline-flex; align-items: center; justify-content: center;
        width: 2rem; height: 2rem;
        border-radius: 0.65rem;
        border: 1px solid rgba(255,255,255,0.06);
        background: rgba(255,255,255,0.04);
        color: #94a3b8;
        cursor: pointer;
        transition: all 0.2s;
        flex-shrink: 0;
    }
    .btn-icon:hover { background: rgba(255,255,255,0.1); color: #f8fafc; }
    .btn-icon.copied { background: rgba(34,197,94,0.15); color: #4ade80; border-color: rgba(34,197,94,0.3); }

    .cofre-stat {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        background: rgba(30, 41, 59, 0.5); border: 1px solid rgba(255,255,255,0.06);
        border-radius: 1rem; padding: 1.25rem 1.5rem;
        min-width: 140px;
    }
    .cofre-stat .stat-num { font-size: 2rem; font-weight: 900; font-family: 'Outfit', sans-serif; }
    .cofre-stat .stat-label { font-size: 0.6rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.12em; color: #64748b; margin-top: 0.25rem; }

    .cofre-empty {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        padding: 4rem 2rem;
        text-align: center;
        color: #64748b;
    }
    .cofre-empty svg { width: 4rem; height: 4rem; margin-bottom: 1rem; opacity: 0.3; }

    /* Toast */
    .cofre-toast {
        position: fixed; bottom: 2rem; right: 2rem; z-index: 200;
        background: rgba(30, 41, 59, 0.95); backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.1);
        padding: 1rem 1.5rem; border-radius: 1rem;
        font-size: 0.85rem; font-weight: 600; color: #f8fafc;
        box-shadow: 0 20px 40px rgba(0,0,0,0.4);
        transform: translateY(120%); opacity: 0;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .cofre-toast.show { transform: translateY(0); opacity: 1; }

    /* Light mode overrides */
    html.light-mode .cofre-card { background: #ffffff !important; border-color: #e2e8f0 !important; }
    html.light-mode .cofre-card:hover { border-color: #cbd5e1 !important; box-shadow: 0 10px 25px rgba(0,0,0,0.08) !important; }
    html.light-mode .senha-field { background: #f8fafc !important; border-color: #e2e8f0 !important; color: #334155 !important; }
    html.light-mode .cofre-stat { background: #ffffff !important; border-color: #e2e8f0 !important; }
    html.light-mode .cofre-toast { background: #ffffff !important; border-color: #e2e8f0 !important; color: #0f172a !important; }
    html.light-mode .btn-icon { border-color: #e2e8f0 !important; background: #f8fafc !important; color: #64748b !important; }
    html.light-mode .btn-icon:hover { background: #e2e8f0 !important; color: #0f172a !important; }

    @keyframes fadeSlideUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
    .animate-card { animation: fadeSlideUp 0.4s ease forwards; }
</style>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">

<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-0 pb-8 animate-fade-in">

    <!-- Header -->
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
            <h1 class="text-2xl md:text-3xl font-black text-white tracking-tight" style="font-family: 'Outfit', sans-serif;">
                🔐 Cofre de Senhas (V2)
            </h1>
            <p class="text-slate-400 text-sm mt-1">Gerencie credenciais de e-mail e aplicativos do escritório com segurança</p>
        </div>
        <button onclick="openCreateModal()" class="flex items-center gap-2 px-5 py-3 rounded-xl text-white font-bold text-sm transition-all hover:shadow-lg hover:shadow-indigo-500/25 hover:-translate-y-0.5" style="background: var(--app-color);">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
            Nova Credencial
        </button>
    </div>

    <!-- Stats -->
    <div id="cofreStats" class="flex flex-wrap gap-4 mb-6"></div>

    <!-- Search & Filters -->
    <div class="flex flex-col sm:flex-row gap-3 mb-6">
        <div class="flex-1 relative">
            <svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
            <input id="searchInput" type="text" placeholder="Buscar por título, e-mail, categoria ou setor..." class="glass-input w-full pl-10 pr-4 py-3 rounded-xl text-sm" oninput="filterCards()">
        </div>
        <select id="filterSetor" onchange="filterCards()" class="glass-input px-4 py-3 rounded-xl text-sm cursor-pointer min-w-[150px]">
            <option value="">Todos os Setores</option>
            <option value="Contábil">📊 Contábil</option>
            <option value="Fiscal">📄 Fiscal</option>
            <option value="Legalização">⚖️ Legalização</option>
            <option value="RH/DP">👥 RH/DP</option>
            <option value="TI">💻 TI</option>
            <option value="Financeiro">💰 Financeiro</option>
        </select>
        <select id="filterCategoria" onchange="filterCards()" class="glass-input px-4 py-3 rounded-xl text-sm cursor-pointer min-w-[160px]">
            <option value="">Todas Categorias</option>
            <option value="E-mail">📧 E-mail</option>
            <option value="App">📱 App</option>
            <option value="Web">🌐 Web</option>
            <option value="Rede">🔌 Rede</option>
            <option value="Sistema">💻 Sistema</option>
            <option value="Outro">📎 Outro</option>
        </select>
    </div>

    <!-- Grid de Credenciais -->
    <div id="cofreGrid" class="cofre-grid"></div>

    <!-- Empty State -->
    <div id="cofreEmpty" class="cofre-empty hidden">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
        <p class="text-lg font-bold">Nenhuma credencial salva</p>
        <p class="text-sm mt-1">Clique em "Nova Credencial" para começar</p>
    </div>
</div>

<!-- Modal Criar/Editar -->
<div id="cofreModal" class="hidden fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 backdrop-blur-sm p-4">
    <div class="glass-panel w-full max-w-lg p-8 rounded-3xl border border-white/10 shadow-2xl relative animate-[fadeSlideUp_0.3s_ease-out]">
        <button onclick="closeModal('cofreModal')" class="absolute top-6 right-6 text-slate-400 hover:text-white transition-colors">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>

        <h3 id="modalTitle" class="text-xl font-bold text-white mb-1" style="font-family: 'Outfit', sans-serif;">Nova Credencial</h3>
        <p class="text-slate-400 text-sm mb-6">Preencha os dados da credencial para salvar no cofre.</p>

        <form id="cofreForm" class="space-y-4" onsubmit="submitForm(event)">
            <input type="hidden" id="editId" value="">

            <div>
                <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">Título *</label>
                <input type="text" id="fTitulo" required placeholder="Ex: Outlook RH" class="glass-input w-full px-4 py-3 rounded-xl text-sm">
            </div>

            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">Categoria</label>
                    <select id="fCategoria" class="glass-input w-full px-4 py-3 rounded-xl text-sm cursor-pointer">
                        <option value="E-mail">📧 E-mail</option>
                        <option value="App">📱 App</option>
                        <option value="Web">🌐 Web</option>
                        <option value="Rede">🔌 Rede</option>
                        <option value="Sistema">💻 Sistema</option>
                        <option value="Outro">📎 Outro</option>
                    </select>
                </div>
                <div>
                    <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">Setor</label>
                    <select id="fSetor" class="glass-input w-full px-4 py-3 rounded-xl text-sm cursor-pointer">
                        <option value="Contábil">📊 Contábil</option>
                        <option value="Fiscal">📄 Fiscal</option>
                        <option value="Legalização">⚖️ Legalização</option>
                        <option value="RH/DP">👥 RH/DP</option>
                        <option value="TI">💻 TI</option>
                        <option value="Financeiro">💰 Financeiro</option>
                    </select>
                </div>
            </div>

            <div>
                <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">E-mail / Login *</label>
                <input type="text" id="fLogin" required placeholder="usuario@empresa.com.br" class="glass-input w-full px-4 py-3 rounded-xl text-sm">
            </div>

            <div>
                <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">
                    Senha *
                    <span id="senhaHint" class="text-slate-600 normal-case tracking-normal hidden">(deixe vazio para manter a atual)</span>
                </label>
                <div class="relative">
                    <input type="password" id="fSenha" placeholder="●●●●●●●●" class="glass-input w-full px-4 py-3 pr-12 rounded-xl text-sm">
                    <button type="button" onclick="toggleFormPassword()" class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors">
                        <svg id="formEyeIcon" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                    </button>
                </div>
            </div>

            <div>
                <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">URL (opcional)</label>
                <input type="text" id="fUrl" placeholder="https://outlook.office.com" class="glass-input w-full px-4 py-3 rounded-xl text-sm">
            </div>

            <div>
                <label class="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">Observações (opcional)</label>
                <textarea id="fObs" rows="2" placeholder="Anotações adicionais..." class="glass-input w-full px-4 py-3 rounded-xl text-sm resize-none"></textarea>
            </div>

            <div id="formMsg" class="text-xs font-bold hidden p-3 rounded-xl border"></div>

            <button type="submit" id="btnSubmit" class="w-full text-white font-bold py-3.5 rounded-xl hover:shadow-lg transition-all text-sm" style="background: var(--app-color);">
                💾 Salvar Credencial
            </button>
        </form>
    </div>
</div>

<!-- Modal Confirmação de Exclusão -->
<div id="deleteModal" class="hidden fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/60 backdrop-blur-sm p-4">
    <div class="glass-panel w-full max-w-sm p-8 rounded-3xl border border-white/10 shadow-2xl text-center animate-[fadeSlideUp_0.3s_ease-out]">
        <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
            <svg class="w-8 h-8 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
        </div>
        <h3 class="text-lg font-bold text-white mb-2">Excluir credencial?</h3>
        <p id="deleteItemName" class="text-slate-400 text-sm mb-6">Esta ação não pode ser desfeita.</p>
        <div class="flex gap-3">
            <button onclick="closeDeleteModal()" class="flex-1 py-3 rounded-xl font-bold text-sm border border-white/10 text-slate-300 hover:bg-white/5 transition-all">Cancelar</button>
            <button id="btnConfirmDelete" onclick="confirmDelete()" class="flex-1 py-3 rounded-xl font-bold text-sm bg-rose-600 text-white hover:bg-rose-500 transition-all">Excluir</button>
        </div>
    </div>
</div>

<!-- Toast -->
<div id="cofreToast" class="cofre-toast"></div>

<script>
const API_BASE = window.location.port === '3001' ? '' : 'http://' + window.location.hostname + ':3001';
const API = API_BASE + '/api/cofre';
let allCredentials = [];
let deleteTargetId = null;
let isInitialLoad = true;

const catIcons = {
    'E-mail': '📧', 'App': '📱', 'Web': '🌐',
    'Rede': '🔌', 'Sistema': '💻', 'Outro': '📎'
};

const catClasses = {
    'E-mail': 'cat-email', 'App': 'cat-app', 'Web': 'cat-web',
    'Rede': 'cat-rede', 'Sistema': 'cat-sistema', 'Outro': 'cat-outro'
};

// ====================
// Load & Render
// ====================
async function loadCredentials() {
    try {
        const res = await fetch(`${API}/list`, { credentials: 'include' });
        const data = await res.json();
        if (data.success) {
            allCredentials = data.credenciais;
            renderStats();
            filterCards();
            isInitialLoad = false;
        }
    } catch (e) { console.error('Erro ao carregar credenciais:', e); }
}

function renderStats() {
    const cats = {};
    allCredentials.forEach(c => { cats[c.categoria] = (cats[c.categoria] || 0) + 1; });
    const el = document.getElementById('cofreStats');
    let html = `
        <div class="cofre-stat">
            <span class="stat-num" style="color: var(--app-color);">${allCredentials.length}</span>
            <span class="stat-label">Total</span>
        </div>`;
    Object.entries(cats).sort((a,b) => b[1]-a[1]).forEach(([cat, count]) => {
        html += `
        <div class="cofre-stat">
            <span class="stat-num text-white">${count}</span>
            <span class="stat-label">${catIcons[cat] || '📎'} ${cat}</span>
        </div>`;
    });
    el.innerHTML = html;
}

function renderCards(items) {
    const grid = document.getElementById('cofreGrid');
    const empty = document.getElementById('cofreEmpty');

    if (items.length === 0) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        return;
    }
    empty.classList.add('hidden');

    grid.innerHTML = items.map((c, i) => `
        <div class="cofre-card ${isInitialLoad ? 'animate-card' : ''}" ${isInitialLoad ? `style="animation-delay: ${i * 0.05}s"` : ''}>
            <div class="flex items-start justify-between mb-3">
                <div>
                    <h3 class="text-white font-bold text-base">${esc(c.titulo)}</h3>
                    <div class="flex flex-wrap gap-1.5 mt-1">
                        <span class="cat-badge ${catClasses[c.categoria] || 'cat-outro'}">${catIcons[c.categoria] || '📎'} ${esc(c.categoria)}</span>
                        <span class="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest bg-slate-800 text-slate-400 border border-white/5 html-light:bg-slate-100 html-light:text-slate-700 html-light:border-slate-200">${esc(c.setor || 'TI')}</span>
                    </div>
                </div>
                <div class="flex gap-1.5">
                    <button onclick="openEditModal(${c.id})" class="btn-icon" title="Editar">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
                    </button>
                    <button onclick="openDeleteModal(${c.id}, '${esc(c.titulo)}')" class="btn-icon" title="Excluir" style="color: #f87171;">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                    </button>
                </div>
            </div>

            <div class="space-y-2 text-sm">
                <div class="flex items-center gap-2 text-slate-400">
                    <svg class="w-4 h-4 flex-shrink-0 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                    <span class="truncate">${esc(c.login_email)}</span>
                </div>

                <div class="senha-field">
                    <svg class="w-4 h-4 flex-shrink-0 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
                    <span class="senha-text" id="senha-${c.id}">●●●●●●●●</span>
                    <button type="button" onclick="toggleReveal(${c.id})" class="btn-icon" id="eye-${c.id}" title="Mostrar senha">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                    </button>
                    <button type="button" onclick="copyPassword(${c.id})" class="btn-icon" id="copy-${c.id}" title="Copiar senha">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
                    </button>
                </div>

                ${c.url ? `
                <div class="flex items-center gap-2 text-slate-500 text-xs">
                    <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path></svg>
                    <a href="${esc(c.url)}" target="_blank" class="truncate hover:text-indigo-400 transition-colors">${esc(c.url)}</a>
                </div>` : ''}

                ${c.observacoes ? `
                <div class="flex items-start gap-2 text-slate-500 text-xs mt-1">
                    <svg class="w-3.5 h-3.5 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"></path></svg>
                    <span>${esc(c.observacoes)}</span>
                </div>` : ''}
            </div>
        </div>
    `).join('');
}

function filterCards() {
    const q = document.getElementById('searchInput').value.toLowerCase();
    const cat = document.getElementById('filterCategoria').value;
    const setor = document.getElementById('filterSetor').value;
    const filtered = allCredentials.filter(c => {
        const matchQ = !q || c.titulo.toLowerCase().includes(q) || c.login_email.toLowerCase().includes(q) || c.categoria.toLowerCase().includes(q) || (c.setor && c.setor.toLowerCase().includes(q));
        const matchCat = !cat || c.categoria === cat;
        const matchSetor = !setor || (c.setor && c.setor === setor);
        return matchQ && matchCat && matchSetor;
    });
    renderCards(filtered);
}

// ====================
// Reveal / Copy
// ====================
const revealCache = {};

async function toggleReveal(id) {
    const el = document.getElementById(`senha-${id}`);
    if (el.dataset.revealed === 'true') {
        el.textContent = '●●●●●●●●';
        el.dataset.revealed = 'false';
        el.style.color = '';
        el.style.letterSpacing = '0.15em';
        return;
    }
    try {
        let senha = revealCache[id];
        if (!senha) {
            const res = await fetch(`${API}/reveal/${id}`, { credentials: 'include' });
            const data = await res.json();
            if (!data.success) throw new Error();
            senha = data.senha;
            revealCache[id] = senha;
        }
        el.textContent = senha;
        el.dataset.revealed = 'true';
        el.style.color = '#f8fafc';
        el.style.letterSpacing = '0.02em';
    } catch (e) { showToast('Erro ao revelar senha', 'error'); }
}

async function copyPassword(id) {
    try {
        let senha = revealCache[id];
        if (!senha) {
            const res = await fetch(`${API}/reveal/${id}`, { credentials: 'include' });
            const data = await res.json();
            if (!data.success) throw new Error();
            senha = data.senha;
            revealCache[id] = senha;
        }
        await navigator.clipboard.writeText(senha);
        const btn = document.getElementById(`copy-${id}`);
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 1500);
        showToast('✅ Senha copiada!', 'success');
    } catch (e) { showToast('Erro ao copiar', 'error'); }
}

// ====================
// Modal Create/Edit
// ====================
function openCreateModal() {
    document.getElementById('editId').value = '';
    document.getElementById('modalTitle').textContent = 'Nova Credencial';
    document.getElementById('fTitulo').value = '';
    document.getElementById('fCategoria').value = 'E-mail';
    document.getElementById('fSetor').value = 'TI';
    document.getElementById('fLogin').value = '';
    document.getElementById('fSenha').value = '';
    document.getElementById('fSenha').required = true;
    document.getElementById('fUrl').value = '';
    document.getElementById('fObs').value = '';
    document.getElementById('senhaHint').classList.add('hidden');
    document.getElementById('formMsg').classList.add('hidden');
    document.getElementById('btnSubmit').textContent = '💾 Salvar Credencial';
    document.getElementById('cofreModal').classList.remove('hidden');
}

function openEditModal(id) {
    const item = allCredentials.find(c => c.id === id);
    if (!item) return;
    document.getElementById('editId').value = id;
    document.getElementById('modalTitle').textContent = 'Editar Credencial';
    document.getElementById('fTitulo').value = item.titulo;
    document.getElementById('fCategoria').value = item.categoria;
    document.getElementById('fSetor').value = item.setor || 'TI';
    document.getElementById('fLogin').value = item.login_email;
    document.getElementById('fSenha').value = '';
    document.getElementById('fSenha').required = false;
    document.getElementById('fUrl').value = item.url || '';
    document.getElementById('fObs').value = item.observacoes || '';
    document.getElementById('senhaHint').classList.remove('hidden');
    document.getElementById('formMsg').classList.add('hidden');
    document.getElementById('btnSubmit').textContent = '💾 Atualizar Credencial';
    document.getElementById('cofreModal').classList.remove('hidden');
}

async function submitForm(e) {
    e.preventDefault();
    const editId = document.getElementById('editId').value;
    const isEdit = !!editId;
    const endpoint = isEdit ? `${API}/edit` : `${API}/create`;

    const fd = new FormData();
    if (isEdit) fd.append('id', editId);
    fd.append('titulo', document.getElementById('fTitulo').value);
    fd.append('categoria', document.getElementById('fCategoria').value);
    fd.append('setor', document.getElementById('fSetor').value);
    fd.append('login_email', document.getElementById('fLogin').value);
    fd.append('senha', document.getElementById('fSenha').value);
    fd.append('url', document.getElementById('fUrl').value);
    fd.append('observacoes', document.getElementById('fObs').value);

    // Validação: senha obrigatória para criação
    if (!isEdit && !document.getElementById('fSenha').value.trim()) {
        showFormMsg('Preencha a senha.', 'error');
        return;
    }

    try {
        const res = await fetch(endpoint, { method: 'POST', body: fd, credentials: 'include' });
        const data = await res.json();
        if (data.success) {
            closeModal();
            showToast(data.message || 'Salvo!', 'success');
            // Limpar cache de senhas reveladas se editou
            if (isEdit) delete revealCache[editId];
            await loadCredentials();
        } else {
            showFormMsg(data.detail || 'Erro ao salvar', 'error');
        }
    } catch (e) { showFormMsg('Erro de conexão', 'error'); }
}

function showFormMsg(msg, type) {
    const el = document.getElementById('formMsg');
    el.classList.remove('hidden');
    el.textContent = msg;
    el.className = `text-xs font-bold p-3 rounded-xl border ${type === 'error' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'}`;
}

function toggleFormPassword() {
    const inp = document.getElementById('fSenha');
    inp.type = inp.type === 'password' ? 'text' : 'password';
}

// ====================
// Delete
// ====================
function openDeleteModal(id, titulo) {
    deleteTargetId = id;
    document.getElementById('deleteItemName').textContent = `"${titulo}" será removida permanentemente.`;
    document.getElementById('deleteModal').classList.remove('hidden');
}

function closeDeleteModal() {
    document.getElementById('deleteModal').classList.add('hidden');
    deleteTargetId = null;
}

async function confirmDelete() {
    if (!deleteTargetId) return;
    const fd = new FormData();
    fd.append('id', deleteTargetId);
    try {
        const res = await fetch(`${API}/delete`, { method: 'POST', body: fd, credentials: 'include' });
        const data = await res.json();
        if (data.success) {
            closeDeleteModal();
            showToast('🗑️ Credencial removida', 'success');
            delete revealCache[deleteTargetId];
            await loadCredentials();
        } else { showToast(data.detail || 'Erro', 'error'); }
    } catch (e) { showToast('Erro de conexão', 'error'); }
}

// ====================
// Toast
// ====================
function showToast(msg, type = 'info') {
    const el = document.getElementById('cofreToast');
    el.textContent = msg;
    el.style.borderLeft = `4px solid ${type === 'success' ? '#22c55e' : type === 'error' ? '#ef4444' : '#6366f1'}`;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 3000);
}

// ====================
// Helpers
// ====================
function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Init
loadCredentials();
</script>

<?php require_once 'includes/footer.php'; ?>
