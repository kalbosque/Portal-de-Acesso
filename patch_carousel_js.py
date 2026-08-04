#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# patch_carousel_js.py - substitui o bloco JS do carrossel estatico pelo dinamico

HTML_FILE = 'c:/sistema-impressao/backend/templates/chamados.html'

OLD_JS_MARKER_START = '    // Carrossel Logic\n    let currentCarouselIndex = 0;\n    const carouselItems = document.querySelectorAll(\'.carousel-item\');\n    const carouselDots = document.querySelectorAll(\'.carousel-dot\');\n    let carouselInterval;'
OLD_JS_MARKER_END = '    function scrollToNewestTicket() {\n        focarNovoChamado();\n    }\n</script>'

NEW_JS = '''    // ==========================================
    // CARROSSEL DINAMICO - carrega da API
    // ==========================================
    let currentCarouselIndex = 0;
    let carouselData = [];
    let carouselInterval;
    const COR_MAP = {
        indigo:  { title: 'text-indigo-400',  dot: 'bg-indigo-500' },
        amber:   { title: 'text-amber-400',   dot: 'bg-amber-500'  },
        emerald: { title: 'text-emerald-400', dot: 'bg-emerald-500'},
        rose:    { title: 'text-rose-400',    dot: 'bg-rose-500'   },
    };

    async function loadCarousel() {
        try {
            const res = await fetch('/api/avisos');
            const avisos = await res.json();
            carouselData = avisos;

            const container = document.getElementById('tips-carousel');
            const dotsContainer = document.getElementById('carousel-dots-container');
            container.innerHTML = '';
            dotsContainer.innerHTML = '';

            if (!avisos.length) {
                container.innerHTML = '<div class="absolute inset-0 flex flex-col justify-center"><h4 class="text-slate-600 font-bold text-base">Nenhum aviso cadastrado.</h4></div>';
                return;
            }

            avisos.forEach((av, i) => {
                const cores = COR_MAP[av.cor] || COR_MAP.indigo;
                const slide = document.createElement('div');
                slide.className = 'carousel-item absolute inset-0 transition-opacity duration-700 flex flex-col justify-center ' + (i === 0 ? 'opacity-100' : 'opacity-0 pointer-events-none');
                slide.innerHTML = `<h4 class="font-bold text-lg mb-1 flex items-center gap-2 ${cores.title}">${av.icone} ${av.titulo}</h4><p class="text-slate-400 text-sm font-medium">${av.mensagem}</p>`;
                container.appendChild(slide);

                const dot = document.createElement('button');
                dot.className = 'w-2 h-2 rounded-full transition-all ' + (i === 0 ? (COR_MAP[av.cor] || COR_MAP.indigo).dot : 'bg-white/20');
                dot.onclick = () => showCarouselItem(i);
                dotsContainer.appendChild(dot);
            });

            showCarouselItem(0);
            startCarousel();
        } catch(e) {
            console.error('Erro ao carregar avisos:', e);
        }
    }

    function showCarouselItem(index) {
        const items = document.querySelectorAll('#tips-carousel .carousel-item');
        const dots  = document.querySelectorAll('#carousel-dots-container button');
        if (!items.length) return;

        items.forEach((item, i) => {
            if (i === index) {
                item.classList.remove('opacity-0', 'pointer-events-none');
                item.classList.add('opacity-100');
                if (dots[i]) {
                    const cor = (COR_MAP[carouselData[i]?.cor] || COR_MAP.indigo).dot;
                    dots[i].className = 'w-2 h-2 rounded-full transition-all ' + cor;
                }
            } else {
                item.classList.add('opacity-0', 'pointer-events-none');
                item.classList.remove('opacity-100');
                if (dots[i]) dots[i].className = 'w-2 h-2 rounded-full transition-all bg-white/20';
            }
        });
        currentCarouselIndex = index;
    }

    function nextCarouselItem() {
        const items = document.querySelectorAll('#tips-carousel .carousel-item');
        if (!items.length) return;
        showCarouselItem((currentCarouselIndex + 1) % items.length);
    }

    function startCarousel() {
        if (carouselInterval) clearInterval(carouselInterval);
        carouselInterval = setInterval(nextCarouselItem, 6000);
    }

    // Pausa ao hover
    document.getElementById('tips-carousel')?.addEventListener('mouseenter', () => clearInterval(carouselInterval));
    document.getElementById('tips-carousel')?.addEventListener('mouseleave', startCarousel);

    // ==========================================
    // MODAL DE GERENCIAMENTO DE AVISOS (ADMIN)
    // ==========================================
    function openAvisosModal() {
        document.getElementById('avisosModal').classList.remove('hidden');
        refreshAvisosList();
    }
    function closeAvisosModal() {
        document.getElementById('avisosModal').classList.add('hidden');
    }

    async function refreshAvisosList() {
        const list = document.getElementById('avisos-list');
        list.innerHTML = '<div class="text-slate-600 text-xs text-center py-8">Carregando...</div>';
        const res = await fetch('/api/avisos');
        const avisos = await res.json();
        if (!avisos.length) {
            list.innerHTML = '<div class="text-slate-600 text-xs text-center py-8">Nenhum aviso cadastrado.</div>';
            return;
        }
        list.innerHTML = avisos.map(av => `
            <div class="flex items-center justify-between p-4 bg-white/5 rounded-2xl border border-white/5 group hover:bg-white/10 transition-all">
                <div class="flex items-center gap-3">
                    <span class="text-2xl">${av.icone}</span>
                    <div>
                        <span class="block text-xs font-black text-white">${av.titulo}</span>
                        <span class="block text-[9px] text-slate-500 line-clamp-1 max-w-[160px]">${av.mensagem}</span>
                    </div>
                </div>
                <button onclick="deletarAviso(${av.id})" class="p-2 text-rose-400 hover:bg-rose-500/10 rounded-lg transition-all">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                </button>
            </div>
        `).join('');
    }

    async function salvarAviso() {
        const icone = document.getElementById('aviso-icone').value.trim();
        const titulo = document.getElementById('aviso-titulo').value.trim();
        const mensagem = document.getElementById('aviso-mensagem').value.trim();
        const cor = document.getElementById('aviso-cor').value;

        if (!titulo || !mensagem) {
            showLiveToast('warning', 'Preencha o titulo e a mensagem do aviso.', '⚠️');
            return;
        }

        const form = new FormData();
        form.append('icone', icone || '📣');
        form.append('titulo', titulo);
        form.append('mensagem', mensagem);
        form.append('cor', cor);

        const res = await fetch('/api/avisos', { method: 'POST', body: form });
        if (res.ok) {
            showLiveToast('success', 'Aviso publicado com sucesso!', '✅');
            document.getElementById('aviso-titulo').value = '';
            document.getElementById('aviso-mensagem').value = '';
            document.getElementById('aviso-icone').value = '📣';
            refreshAvisosList();
            loadCarousel();
        } else {
            showLiveToast('error', 'Erro ao publicar aviso.', '❌');
        }
    }

    async function deletarAviso(id) {
        const res = await fetch('/api/avisos/' + id, { method: 'DELETE' });
        if (res.ok) {
            showLiveToast('info', 'Aviso removido.', '🗑️');
            refreshAvisosList();
            loadCarousel();
        }
    }

    function setAvisoIcon(ic) {
        document.getElementById('aviso-icone').value = ic;
        updateAvisoPreview();
    }
    function setAvisoCor(cor) {
        document.getElementById('aviso-cor').value = cor;
        document.querySelectorAll('.cor-btn').forEach(btn => {
            const isActive = btn.dataset.cor === cor;
            btn.style.borderWidth = isActive ? '2px' : '1px';
            btn.style.opacity = isActive ? '1' : '0.5';
        });
    }
    function updateAvisoPreview() {
        const icone = document.getElementById('aviso-icone').value;
        const titulo = document.getElementById('aviso-titulo').value || 'Titulo do Aviso';
        const mensagem = document.getElementById('aviso-mensagem').value || 'A mensagem aparecera aqui...';
        document.getElementById('preview-titulo').textContent = icone + ' ' + titulo;
        document.getElementById('preview-mensagem').textContent = mensagem;
    }

    // Delegacao de evento para os botoes de icone
    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('icone-picker-grid')?.addEventListener('click', e => {
            const btn = e.target.closest('.icone-picker-btn');
            if (btn) setAvisoIcon(btn.textContent.trim());
        });
        loadCarousel();
    });

    function focarNovoChamado() {
        const panel = document.getElementById('wizard_title');
        if (panel) {
            panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
            const formContainer = panel.closest('.glass-panel');
            if (formContainer) {
                formContainer.classList.add('shadow-[0_0_30px_rgba(99,102,241,0.6)]', 'border-indigo-400');
                setTimeout(() => formContainer.classList.remove('shadow-[0_0_30px_rgba(99,102,241,0.6)]', 'border-indigo-400'), 1500);
            }
        } else { window.scrollTo({ top: 0, behavior: 'smooth' }); }
    }
    function scrollToNewestTicket() { focarNovoChamado(); }
</script>'''

with open(HTML_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# Encontrar o bloco JS antigo do carrossel (entre <script> e </script> do primeiro script apos o form)
start = content.find('    // Carrossel Logic')
end = content.find('</script>', start) + len('</script>')

if start == -1:
    print("ERROR: JS marker not found")
else:
    # Pega o script tag que envolve
    script_start = content.rfind('<script>', 0, start)
    new_content = content[:script_start] + NEW_JS + content[end:]
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"OK: replaced JS block ({end-script_start} chars with {len(NEW_JS)} chars)")
