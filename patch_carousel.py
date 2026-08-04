#!/usr/bin/env python3
# -*- coding: utf-8 -*-

HTML_FILE = 'c:/sistema-impressao/backend/templates/chamados.html'

NEW_BLOCK = """<!-- CARROSSEL DE AVISOS (DINAMICO) -->
<div class="mb-8">
    <div class="glass-panel p-6 rounded-[2.5rem] border border-white/10 shadow-2xl bg-slate-900/60 relative overflow-hidden">
        <div class="absolute -right-10 -top-10 w-40 h-40 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none"></div>
        <div class="flex items-center justify-between mb-5 relative z-10">
            <div class="flex items-center gap-3">
                <span class="p-2 bg-indigo-500/20 rounded-xl text-indigo-400">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </span>
                <h3 class="text-[12px] font-black text-indigo-400 uppercase tracking-widest">Painel de Avisos &amp; Dicas</h3>
            </div>
            {% if is_admin %}
            <button onclick="openAvisosModal()" id="btn-gerenciar-avisos" class="flex items-center gap-2 px-4 py-2 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 rounded-xl text-indigo-400 text-[9px] font-black uppercase tracking-widest transition-all group">
                <svg class="w-4 h-4 group-hover:rotate-12 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
                Gerenciar Avisos
            </button>
            {% endif %}
        </div>
        <div class="relative h-28 z-10" id="tips-carousel">
            <div class="carousel-item absolute inset-0 flex flex-col justify-center">
                <h4 class="text-slate-500 font-bold text-base mb-1">Carregando avisos...</h4>
            </div>
        </div>
        <div class="flex gap-2 justify-center mt-3 relative z-10" id="carousel-dots-container"></div>
    </div>
</div>

{% if is_admin %}
<div id="avisosModal" class="hidden fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/90 backdrop-blur-xl p-4">
    <div class="glass-panel w-full max-w-2xl p-10 rounded-[3rem] border border-white/10 shadow-2xl relative overflow-y-auto" style="max-height: 90vh">
        <button onclick="closeAvisosModal()" class="absolute top-8 right-8 text-slate-500 hover:text-white hover:rotate-90 transition-all">
            <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
        <div class="mb-8">
            <h3 class="text-3xl font-black text-white mb-1 uppercase italic">Gerenciar Avisos</h3>
            <p class="text-slate-500 text-[10px] font-black uppercase tracking-[0.2em]">Conteudo exibido no painel de avisos para todos os usuarios</p>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
                <h4 class="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-4">Avisos Ativos</h4>
                <div id="avisos-list" class="space-y-3 max-h-[350px] overflow-y-auto pr-2">
                    <div class="text-slate-600 text-xs text-center py-8">Carregando...</div>
                </div>
            </div>
            <div class="space-y-4">
                <h4 class="text-[10px] font-black text-indigo-400 uppercase tracking-widest">Novo Aviso</h4>
                <div id="aviso-preview" class="p-4 rounded-[1.5rem] border border-indigo-500/20 bg-indigo-500/5">
                    <h4 id="preview-titulo" class="text-white font-bold text-base mb-1">Titulo do Aviso</h4>
                    <p id="preview-mensagem" class="text-slate-400 text-sm">A mensagem aparecera aqui...</p>
                </div>
                <div>
                    <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Icone</label>
                    <div class="grid grid-cols-8 gap-1 p-3 bg-white/5 rounded-2xl mb-2" id="icone-picker-grid">
                        {% for ic in ['\U0001f4e3','\U0001f4a1','\U0001f525','\u26a0\ufe0f','\u2705','\U0001f6e0\ufe0f','\U0001f310','\U0001f4bb','\U0001f5a8\ufe0f','\U0001f4e2','\u2744\ufe0f','\U0001f6a8','\U0001f4cc','\U0001f3af','\u26a1','\U0001f514'] %}
                        <button type="button" class="icone-picker-btn text-xl hover:scale-125 transition-transform p-1 rounded-lg hover:bg-white/10">{{ ic }}</button>
                        {% endfor %}
                    </div>
                    <input type="text" id="aviso-icone" value="\U0001f4e3" class="glass-input w-full p-3 rounded-xl text-center text-2xl" oninput="updateAvisoPreview()">
                </div>
                <div>
                    <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Titulo</label>
                    <input type="text" id="aviso-titulo" placeholder="Ex: Dica Rapida" class="glass-input w-full p-4 rounded-2xl text-sm font-bold" oninput="updateAvisoPreview()">
                </div>
                <div>
                    <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Mensagem</label>
                    <textarea id="aviso-mensagem" rows="3" placeholder="Descreva o aviso ou dica..." class="glass-input w-full p-4 rounded-2xl text-sm resize-none" oninput="updateAvisoPreview()"></textarea>
                </div>
                <div>
                    <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Cor de Destaque</label>
                    <div class="flex gap-2">
                        <button type="button" onclick="setAvisoCor('indigo')" class="cor-btn flex-1 py-2 rounded-xl bg-indigo-500/20 border-2 border-indigo-500 text-indigo-400 text-[9px] font-black uppercase" data-cor="indigo">Azul</button>
                        <button type="button" onclick="setAvisoCor('amber')" class="cor-btn flex-1 py-2 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[9px] font-black uppercase" data-cor="amber">Amber</button>
                        <button type="button" onclick="setAvisoCor('emerald')" class="cor-btn flex-1 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[9px] font-black uppercase" data-cor="emerald">Verde</button>
                        <button type="button" onclick="setAvisoCor('rose')" class="cor-btn flex-1 py-2 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-[9px] font-black uppercase" data-cor="rose">Urgente</button>
                    </div>
                </div>
                <input type="hidden" id="aviso-cor" value="indigo">
                <button onclick="salvarAviso()" class="w-full py-4 bg-gradient-to-br from-indigo-500 to-indigo-700 text-white font-black text-xs uppercase tracking-widest rounded-2xl transition-all hover:shadow-lg flex items-center justify-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    Publicar Aviso
                </button>
            </div>
        </div>
    </div>
</div>
{% endif %}

"""

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

start = content.find('<!-- CARROSSEL DE DICAS')
end = content.find('<!-- Filtros e Busca -->')

if start == -1 or end == -1:
    print("ERROR: markers not found", start, end)
else:
    new_content = content[:start] + NEW_BLOCK + content[end:]
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"OK: replaced {end-start} chars with {len(NEW_BLOCK)} chars")
