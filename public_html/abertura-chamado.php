<?php
require_once 'db.php';
require_once 'includes/config.php';

$message = '';
$tipo_msg = '';
$successState = false;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $nome_solicitante = trim($_POST['nome_solicitante'] ?? '');
    $maquina = trim($_POST['maquina'] ?? '');
    $titulo = trim($_POST['titulo'] ?? '');
    $descricao = trim($_POST['descricao'] ?? '');

    if ($nome_solicitante && $titulo && $descricao) {
        // Concatenando Máquina ao início da descrição para referência da TI
        $descricao_final = $maquina ? "[Máquina: $maquina]\n\n" . $descricao : $descricao;
        
        $stmt = $pdo->prepare("INSERT INTO chamados (usuario, titulo, descricao) VALUES (?, ?, ?)");
        if ($stmt->execute([$nome_solicitante, $titulo, $descricao_final])) {
            $message = "Chamado registrado com sucesso! A TI resolve as ocorrências por ordem de chegada.";
            $tipo_msg = "success";
            $successState = true;
        } else {
            $message = "Ocorreu um erro técnico. Tente novamente.";
            $tipo_msg = "error";
        }
    } else {
        $message = "Por favor, preencha todos os campos obrigatórios.";
        $tipo_msg = "error";
    }
}

$pageTitle = 'Abertura de Chamado | Suporte TI';
$hideNav = true; // Esconde menus e barra administrativa
$hideChartJs = true;
require_once 'includes/header.php';
?>

<div class="min-h-screen flex items-center justify-center p-4 relative z-10 w-full overflow-hidden">
    
    <div class="w-full max-w-lg">
        <div class="text-center mb-10">
            <!-- Renderiza Logo da Empresa Centralizado -->
            <?php if (!empty(APP_LOGO_URL)): ?>
                <img src="<?= htmlspecialchars(APP_LOGO_URL) ?>" alt="Logo da Empresa" class="h-20 w-auto object-contain mx-auto drop-shadow-xl mb-4" />
            <?php else: ?>
                <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-fuchsia-600 flex items-center justify-center mx-auto shadow-2xl shadow-indigo-500/50 mb-6">
                    <svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </div>
            <?php endif; ?>
            
            <h1 class="text-4xl font-bold tracking-tight bg-gradient-to-r from-white to-slate-400 gradient-text inline-block filter drop-shadow-lg">Abertura de Chamado</h1>
            <p class="text-slate-400 mt-2 font-medium">Relate problemas com equipamentos ou falta de suprimentos de rede.</p>
        </div>

        <div class="glass-panel p-8 sm:p-10 rounded-3xl relative overflow-hidden group shadow-2xl border border-slate-700/50">
            <!-- Glow effect background -->
            <div class="absolute -right-20 -top-20 w-60 h-60 bg-fuchsia-500/20 rounded-full blur-3xl transition-all duration-700"></div>
            <div class="absolute -left-20 -bottom-20 w-60 h-60 bg-indigo-500/20 rounded-full blur-3xl transition-all duration-700"></div>

            <?php if ($message): ?>
                <div class="mb-8 p-4 text-sm font-medium rounded-xl border relative z-20 backdrop-blur-md
                    <?= $tipo_msg === 'success' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 shadow-[0_0_20px_rgba(16,185,129,0.15)]' : 'bg-rose-500/10 text-rose-400 border-rose-500/30' ?>">
                    <div class="flex items-center gap-3">
                        <?php if($tipo_msg === 'success'): ?>
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        <?php else: ?>
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        <?php endif; ?>
                        <?= htmlspecialchars($message) ?>
                    </div>
                </div>
            <?php endif; ?>

            <?php if (!$successState): ?>
                <form action="abertura-chamado.php" method="POST" class="space-y-6 relative z-10 w-full">
                    <div>
                        <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5 flex items-center gap-2">
                            Seu Nome ou Setor
                            <span class="text-rose-500">*</span>
                        </label>
                        <input type="text" name="nome_solicitante" required placeholder="Ex: João - Financeiro" class="glass-input w-full px-5 py-3.5 rounded-xl text-white transition-all">
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5 flex items-center gap-2">
                            Aparelho Físico Analisado
                            <span class="text-slate-500 text-[10px] font-normal lowercase tracking-normal">(Opcional)</span>
                        </label>
                        <input type="text" name="maquina" placeholder="Nome da impressora na etiqueta" class="glass-input w-full px-5 py-3.5 rounded-xl text-white transition-all">
                    </div>
                    
                    <div class="border-t border-slate-700/50 pt-6 mt-2">
                        <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5 flex items-center gap-2">
                            Assunto Principal
                            <span class="text-rose-500">*</span>
                        </label>
                        <input type="text" name="titulo" required placeholder="Ex: Impressora Epson com erro E-01" class="glass-input w-full px-5 py-3.5 rounded-xl text-white transition-all">
                    </div>

                    <div>
                        <label class="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5 flex items-center gap-2">
                            Detalhes Completos da Ocorrência
                            <span class="text-rose-500">*</span>
                        </label>
                        <textarea name="descricao" required rows="4" placeholder="Descreva os barulhos, erros de tela e tentativas de contorno já feitas ao equipamento..." class="glass-input w-full px-5 py-3.5 rounded-xl text-white resize-none transition-all"></textarea>
                    </div>

                    <div class="pt-4">
                        <button type="submit" class="w-full bg-gradient-to-r from-fuchsia-600 to-indigo-600 text-white font-bold py-4 rounded-xl hover:from-fuchsia-500 hover:to-indigo-500 transition-all shadow-[0_4px_20px_0_rgba(217,70,239,0.35)] active:scale-[0.98]">
                            Enviar Solicitação ao Setor Técnico
                        </button>
                    </div>
                </form>
            <?php else: ?>
                <div class="flex flex-col items-center justify-center text-center py-6 relative z-10 w-full space-y-6">
                    <div class="w-20 h-20 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mb-2 shadow-[0_0_30px_rgba(16,185,129,0.3)]">
                        <svg class="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <p class="text-slate-300 text-sm leading-relaxed max-w-sm">
                        Muito obrigado. Nossa equipe recebeu sua notificação. Fique de olho, em breve ajudaremos com o problema no equipamento!
                    </p>
                    <a href="abertura-chamado.php" class="inline-block mt-4 text-indigo-400 font-bold hover:text-indigo-300 transition-all border-b border-indigo-500 hover:border-indigo-400 pb-0.5">Abrir outa ocorrência</a>
                </div>
            <?php endif; ?>
        </div>
        
        <div class="text-center mt-10">
            <p class="text-slate-500 text-xs font-medium tracking-wide">&copy; <?= date('Y') ?> Central de Ti | <span class="text-slate-600"><?= htmlspecialchars(APP_NAME) ?></span></p>
        </div>
    </div>
</div>

<?php require_once 'includes/footer.php'; ?>
