<?php
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

// Força o navegador a sempre buscar a versão nova (sem cache)
header("Cache-Control: no-store, no-cache, must-revalidate, max-age=0");
header("Pragma: no-cache");
header("Expires: Thu, 01 Jan 1970 00:00:00 GMT");

if (!hasPermission('chamados')) {
    die('<div style="background:#0f172a; height:100vh; display:flex; align-items:center; justify-content:center; color:white; font-family:sans-serif;"><h1>Acesso Bloqueado. Voce nao tem permissao para visualizar o Suporte/TI.</h1></div>');
}

// Mensagens de Sucesso via URL (para evitar duplicidade no F5)
$message = "";
$tipo_msg = "";
if (isset($_GET['success'])) {
    $message = "Protocolo registrado com sucesso! A equipe de suporte analisará a solicitação.";
    $tipo_msg = "success";
} elseif (isset($_GET['resolved'])) {
    $message = "Chamado encerrado com nota técnica registrada!";
    $tipo_msg = "success";
}

$message = '';
$tipo_msg = '';

$currentUser = $_SESSION['user_name'] ?? 'Desconhecido';
$isAdmin = isAdmin();

/**
 * Função Auxiliar para Envio de E-mail
 */
function enviarEmailChamado($pdo, $chamado_id, $tipo = 'novo') {
    try {
        // Buscar dados do chamado e do usuário
        $stmt = $pdo->prepare("SELECT c.*, u.email as user_email FROM chamados c LEFT JOIN usuarios u ON c.usuario = u.username WHERE c.id = ?");
        $stmt->execute([$chamado_id]);
        $c = $stmt->fetch();
        if (!$c) return false;

        $app_name = APP_NAME ?? 'Sistema IT';
        $headers = "MIME-Version: 1.0" . "\r\n";
        $headers .= "Content-type:text/html;charset=UTF-8" . "\r\n";
        $headers .= "From: Suporte $app_name <nao-responder@sistema.com>" . "\r\n";

        if ($tipo === 'novo') {
            // Notificar Admin/Equipe
            $to = "admin@empresa.com"; // AJUSTE PARA SEU E-MAIL DE SUPORTE
            $subject = "🆕 Novo Chamado: #{$c['id']} - {$c['titulo']}";
            $body = "<h2>Um novo chamado foi aberto!</h2>
                     <p><b>Usuário:</b> {$c['usuario']}</p>
                     <p><b>Assunto:</b> {$c['titulo']}</p>
                     <p><b>Prioridade:</b> {$c['prioridade']}</p>
                     <hr><p>{$c['descricao']}</p>";
        } else {
            // Notificar Usuário (Finalizado)
            $to = $c['user_email'];
            if (!$to) return false;
            $subject = "✅ Chamado Finalizado: #{$c['id']}";
            $body = "<h2>Seu chamado foi concluído!</h2>
                     <p>Olá <b>{$c['usuario']}</b>, o seu chamado foi finalizado pela equipe técnica.</p>
                     <div style='background:#f8fafc; padding:15px; border-radius:10px; border:1px solid #e2e8f0;'>
                        <b>Histórico/Nota Técnica:</b><br>
                        " . nl2br($c['nota_tecnica']) . "
                     </div>
                     <p>Agradecemos o contato.</p>";
        }

        return @mail($to, $subject, $body, $headers);
    } catch (Exception $e) { return false; }
}

// Carregar lista de impressoras para o seletor
$stmtImp = $pdo->query("SELECT id, nome, ip FROM impressoras ORDER BY nome");
$listaImpressoras = $stmtImp->fetchAll();

// Carregar Atalhos de Problemas Dinâmicos
$stmtProb = $pdo->query("SELECT * FROM tipos_problemas ORDER BY id ASC");
$atalhosProblemas = $stmtProb->fetchAll();

// KPIs de Suporte Detalhados (Unificado)
if ($isAdmin) {
    $stats = [
        'abertos' => (int)$pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Aberto'")->fetchColumn(),
        'atendimento' => (int)$pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Em Atendimento'")->fetchColumn(),
        'resolvidos' => (int)$pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Resolvido'")->fetchColumn(),
        'resolvidos_hoje' => (int)$pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Resolvido' AND DATE(data_resolucao) = CURRENT_DATE")->fetchColumn(),
        'urgentes' => (int)$pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Aberto' AND data_abertura < NOW() - INTERVAL '4 hours'")->fetchColumn()
    ];
} else {
    $stmtStats = $pdo->prepare("
        SELECT 
            SUM(CASE WHEN status = 'Aberto' THEN 1 ELSE 0 END) as abertos,
            SUM(CASE WHEN status = 'Em Atendimento' THEN 1 ELSE 0 END) as atendimento,
            SUM(CASE WHEN status = 'Resolvido' THEN 1 ELSE 0 END) as resolvidos,
            SUM(CASE WHEN status = 'Resolvido' AND DATE(data_resolucao) = CURRENT_DATE THEN 1 ELSE 0 END) as resolvidos_hoje,
            SUM(CASE WHEN status = 'Aberto' AND data_abertura < NOW() - INTERVAL '4 hours' THEN 1 ELSE 0 END) as urgentes
        FROM chamados WHERE usuario = ?
    ");
    $stmtStats->execute([$currentUser]);
    $rowStats = $stmtStats->fetch(PDO::FETCH_ASSOC);
    $stats = [
        'abertos' => (int)($rowStats['abertos'] ?? 0),
        'atendimento' => (int)($rowStats['atendimento'] ?? 0),
        'resolvidos' => (int)($rowStats['resolvidos'] ?? 0),
        'resolvidos_hoje' => (int)($rowStats['resolvidos_hoje'] ?? 0),
        'urgentes' => (int)($rowStats['urgentes'] ?? 0)
    ];
}
$totalChamados = $stats['abertos'] + $stats['atendimento'] + $stats['resolvidos'];

// Alias para compatibilidade com os cards de admin
$statsSuporte = [
    'total' => $totalChamados,
    'abertos' => $stats['abertos'],
    'atendimento' => $stats['atendimento'],
    'resolvidos_hoje' => $stats['resolvidos_hoje'],
    'urgentes' => $stats['urgentes']
];

// Processamento de Dados via POST
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // SEGURANÇA: Validar Token CSRF
    if (!validateCsrfToken($_POST['csrf_token'] ?? '')) {
        die('Erro de segurança: Token inválido ou expirado.');
    }

    // Ação: Gerenciar Atalhos (Admin ou Permissão Especial)
    if (isset($_POST['action']) && $_POST['action'] === 'add_atalho' && hasPermission('config_suporte')) {
        $icone = trim($_POST['icone'] ?? '🛠️');
        $label = trim($_POST['label'] ?? '');
        $titulo_p = trim($_POST['titulo_padrao'] ?? '');
        $cat = trim($_POST['categoria'] ?? 'Outros');
        $pri = trim($_POST['prioridade'] ?? 'Media');
        
        if ($label) {
            $stmt = $pdo->prepare("INSERT INTO tipos_problemas (icone, label, titulo_padrao, categoria, prioridade_padrao) VALUES (?, ?, ?, ?, ?)");
            $stmt->execute([$icone, $label, $titulo_p, $cat, $pri]);
            header("Location: chamados.php?manage_atalhos=1"); exit;
        }
    }
    // Ação: Deletar Atalho
    if (isset($_POST['action']) && $_POST['action'] === 'del_atalho' && hasPermission('config_suporte')) {
        $id_del = $_POST['id'] ?? 0;
        $pdo->prepare("DELETE FROM tipos_problemas WHERE id = ?")->execute([$id_del]);
        header("Location: chamados.php?manage_atalhos=1"); exit;
    }
    // Ação: Editar Atalho
    if (isset($_POST['action']) && $_POST['action'] === 'edit_atalho' && hasPermission('config_suporte')) {
        $id = $_POST['id'] ?? 0;
        $icone = trim($_POST['icone'] ?? '🛠️');
        $label = trim($_POST['label'] ?? '');
        $titulo_p = trim($_POST['titulo_padrao'] ?? '');
        $cat = trim($_POST['categoria'] ?? 'Outros');
        $pri = trim($_POST['prioridade'] ?? 'Media');
        if ($id && $label) {
            $pdo->prepare("UPDATE tipos_problemas SET icone=?, label=?, titulo_padrao=?, categoria=?, prioridade_padrao=? WHERE id=?")
                ->execute([$icone, $label, $titulo_p, $cat, $pri, $id]);
            header("Location: chamados.php?manage_atalhos=1"); exit;
        }
    }

    if (isset($_POST['action']) && $_POST['action'] === 'abrir') {
        $titulo = trim($_POST['titulo'] ?? '');
        $titulo_custom = trim($_POST['titulo_custom'] ?? '');
        if ($titulo === 'Outro Problema' && $titulo_custom) {
            $titulo = $titulo_custom;
        }

        $descricao = trim($_POST['descricao'] ?? '');
        $prioridade = $_POST['prioridade'] ?? 'Media';
        $categoria = $_POST['categoria'] ?? 'Outros';
        $eq_id = $_POST['equipamento_id'] ?? null;
        $anexo_url = null;

        // Processar Anexo
        if (isset($_FILES['anexo']) && $_FILES['anexo']['error'] === UPLOAD_ERR_OK) {
            $uploadDir = __DIR__ . '/uploads/tickets/';
            $ext = strtolower(pathinfo($_FILES['anexo']['name'], PATHINFO_EXTENSION));
            if (in_array($ext, ['jpg', 'jpeg', 'png', 'webp', 'gif'])) {
                $fileName = time() . '_' . uniqid() . '.' . $ext;
                if (move_uploaded_file($_FILES['anexo']['tmp_name'], $uploadDir . $fileName)) {
                    $anexo_url = 'uploads/tickets/' . $fileName;
                }
            }
        }

        if ($titulo && $descricao) {
            // ANTI-DUPLICIDADE: Verificar se ja existe um chamado identico do mesmo usuario nos ultimos 10 segundos
            $stmtCheck = $pdo->prepare("SELECT id FROM chamados WHERE usuario = ? AND titulo = ? AND data_abertura > NOW() - INTERVAL '10 seconds'");
            $stmtCheck->execute([$currentUser, $titulo]);
            if ($stmtCheck->rowCount() > 0) {
                $message = "Ja recebemos sua solicitacao. Aguarde um momento.";
                $tipo_msg = "warning";
            } else {
                $stmt = $pdo->prepare("INSERT INTO chamados (usuario, titulo, categoria, equipamento_id, descricao, anexo_url, prioridade, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'Aberto')");
                $stmt->execute([$currentUser, $titulo, $categoria, $eq_id, $descricao, $anexo_url, $prioridade]);
                $lastId = $pdo->lastInsertId();
                
                // Enviar E-mail de Alerta (Novo)
                enviarEmailChamado($pdo, $lastId, 'novo');

                // Redirecionar para evitar reenvio ao atualizar (F5)
                header("Location: chamados.php?success=1");
                exit;
            }
        } else {
            $message = "E obrigatorio descrever o problema encontrado.";
            $tipo_msg = "error";
        }
    } elseif (isset($_POST['action']) && $_POST['action'] === 'atender' && $isAdmin) {
        $chamado_id = $_POST['chamado_id'] ?? 0;
        if ($chamado_id) {
            $stmt = $pdo->prepare("UPDATE chamados SET status = 'Em Atendimento' WHERE id = ?");
            $stmt->execute([$chamado_id]);
            $message = "Atendimento iniciado! O usuario sera notificado do progresso.";
            $tipo_msg = "success";
        }
    } elseif (isset($_POST['action']) && $_POST['action'] === 'resolver' && $isAdmin) {
        $chamado_id = $_POST['chamado_id'] ?? 0;
        $nota = trim($_POST['nota_tecnica'] ?? '');
        if ($chamado_id) {
            $stmt = $pdo->prepare("UPDATE chamados SET status = 'Resolvido', nota_tecnica = ?, data_resolucao = CURRENT_TIMESTAMP WHERE id = ?");
            $stmt->execute([$nota, $chamado_id]);
            
            // Enviar E-mail de Alerta (Finalizado)
            enviarEmailChamado($pdo, $chamado_id, 'finalizado');

            header("Location: chamados.php?resolved=1");
            exit;
        }
    } elseif (isset($_POST['action']) && $_POST['action'] === 'interagir') {
        $chamado_id = $_POST['chamado_id'] ?? 0;
        $txt = trim($_POST['mensagem'] ?? '');
        
        // Seguranca: verificar se o chamado pertence ao usuario ou se e ADMIN
        $stmtCheck = $pdo->prepare("SELECT usuario FROM chamados WHERE id = ?");
        $stmtCheck->execute([$chamado_id]);
        $owner = $stmtCheck->fetchColumn();

        if ($chamado_id && $txt && ($isAdmin || $owner === $currentUser)) {
            $stmt = $pdo->prepare("INSERT INTO chamados_interacoes (chamado_id, usuario, mensagem) VALUES (?, ?, ?)");
            $stmt->execute([$chamado_id, $currentUser, $txt]);
            $message = "Mensagem enviada para o mural!";
            $tipo_msg = "success";
        } else {
            $message = "Erro de permissao: voce nao pode interagir neste chamado.";
            $tipo_msg = "error";
        }
    }
}

// Estatisticas rapidas ja carregadas no topo do arquivo (Variavel $stats)

// Extrair Base de Dados de Suporte
if ($isAdmin) {
    $stmt = $pdo->query("SELECT * FROM chamados ORDER BY 
        CASE status WHEN 'Em Atendimento' THEN 1 WHEN 'Aberto' THEN 2 WHEN 'Resolvido' THEN 3 ELSE 4 END, 
        CASE prioridade WHEN 'Alta' THEN 1 WHEN 'Media' THEN 2 WHEN 'Baixa' THEN 3 ELSE 4 END, 
        data_abertura DESC");
} else {
    $stmt = $pdo->prepare("SELECT * FROM chamados WHERE usuario = ? ORDER BY 
        CASE status WHEN 'Em Atendimento' THEN 1 WHEN 'Aberto' THEN 2 WHEN 'Resolvido' THEN 3 ELSE 4 END, 
        data_abertura DESC");
    $stmt->execute([$currentUser]);
}
$chamados = $stmt->fetchAll(PDO::FETCH_ASSOC);

// Carregar todas as interacoes para uso no modal (injetado via JS)
$interacoes_stmt = $pdo->query("SELECT chamado_id, usuario, mensagem, data_hora FROM chamados_interacoes ORDER BY data_hora ASC");
$interacoes_por_chamado = $interacoes_stmt->fetchAll(PDO::FETCH_GROUP|PDO::FETCH_ASSOC);

$pageTitle = 'Suporte TI | ' . APP_NAME;
$hideChartJs = false; // Habilitar graficos
require_once 'includes/header.php';
?>

<style>
    .glass-card-magnetic {
        position: relative;
        overflow: hidden;
    }
    .glass-card-magnetic::before {
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background: radial-gradient(400px circle at var(--mouse-x) var(--mouse-y), rgba(99, 102, 241, 0.15), transparent 40%);
        z-index: 0;
        pointer-events: none;
        opacity: 0;
        transition: opacity 0.3s;
    }
    .glass-card-magnetic:hover::before { opacity: 1; }
    
    .kanban-col { min-height: 400px; padding: 10px; border-radius: 20px; background: rgba(255,255,255,0.02); }
    @keyframes slideIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    
    .status-indicator { width: 8px; height: 8px; border-radius: 50%; }

    /* Stepper Progress */
    .stepper-line { height: 2px; flex-grow: 1; background: rgba(255,255,255,0.1); margin: 0 4px; border-radius: 2px; }
    .stepper-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(255,255,255,0.2); }
    .stepper-dot.active { background: currentColor; box-shadow: 0 0 8px currentColor; }
    .stepper-line.active { background: currentColor; }

    /* High Priority Glow */
    .priority-alta-glow { box-shadow: 0 0 20px rgba(244, 63, 94, 0.15); border-color: rgba(244, 63, 94, 0.4) !important; }
    
    /* Search Bar focus */
    .search-focus:focus-within { border-color: #6366f1; box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1); }

    /* Visual Grid Problems */
    .problem-node {
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        cursor: pointer;
        border: 1px solid rgba(255,255,255,0.05);
    }
    .problem-node:hover {
        transform: translateY(-5px);
        background: rgba(99, 102, 241, 0.1);
        border-color: rgba(99, 102, 241, 0.3);
    }
    .problem-node.selected {
        background: #6366f1 !important;
        border-color: #818cf8 !important;
        box-shadow: 0 10px 20px -5px rgba(99, 102, 241, 0.4);
    }
    .problem-node.selected span { color: white !important; }

    /* Wizard Steps */
    .wizard-step { transition: all 0.4s ease; }
    .step-inactive { opacity: 0; pointer-events: none; transform: translateX(20px); position: absolute; width: 100%; }
    .step-active { opacity: 1; pointer-events: auto; transform: translateX(0); position: relative; }

    /* Real-time Notifications Toast */
    #live-toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 10px; pointer-events: none; }
    .live-toast { 
        pointer-events: auto;
        background: rgba(15, 23, 42, 0.9);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 1.25rem;
        padding: 1rem 1.5rem;
        box-shadow: 0 20px 40px -10px rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        gap: 12px;
        min-width: 300px;
        animation: toastSlideIn 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
    }
    @keyframes toastSlideIn { from { opacity:0; transform: translateX(100px); } to { opacity:1; transform: translateX(0); } }
    .toast-exit { animation: toastSlideOut 0.4s ease forwards; }
    @keyframes toastSlideOut { to { opacity:0; transform: translateX(100px); } }

    /* Ajuste de Layout Dinâmico para evitar sobreposição do Chat */
    #app-container { transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1) !important; }
    @media (min-width: 1280px) {
        body.chat-sidebar-open #app-container { 
            margin-right: 400px !important;
            max-width: calc(100% - 420px) !important;
        }
    }

    /* Chat Widget Flutuante (Estilo Moderna SaaS) */
    .side-panel {
        position: fixed !important;
        top: 100px !important;
        right: 20px !important;
        bottom: 20px !important;
        width: calc(100% - 40px) !important;
        max-width: 380px !important;
        z-index: 9000 !important;
        background: rgba(15, 23, 42, 0.9) !important;
        backdrop-filter: blur(30px) !important;
        -webkit-backdrop-filter: blur(30px) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 2.5rem !important;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5) !important;
        display: flex !important;
        flex-direction: column !important;
        transform: translateX(calc(100% + 40px)) !important;
        transition: transform 0.6s cubic-bezier(0.16, 1, 0.3, 1) !important;
        overflow: hidden;
    }
    .side-panel.open { transform: translateX(0) !important; }

    /* Adaptação para Modo Claro */
    html.light-mode .side-panel {
        background: rgba(255, 255, 255, 0.95) !important;
        border: 1px solid #e2e8f0 !important;
        box-shadow: 0 20px 40px rgba(0,0,0,0.1) !important;
    }
    html.light-mode .side-panel .text-white { color: #0f172a !important; }
    html.light-mode .side-panel .bg-slate-900\/60 { background: #f8fafc !important; border-bottom: 1px solid #e2e8f0 !important; border-top: 1px solid #e2e8f0 !important; }
    html.light-mode .side-panel .bg-slate-800\/40 { background: #f1f5f9 !important; border: 1px solid #e2e8f0 !important; }
    html.light-mode .side-panel .border-white\/5 { border-color: #e2e8f0 !important; }
    html.light-mode .side-panel .text-slate-500 { color: #64748b !important; }
    html.light-mode .side-panel .chat-empty svg { color: #cbd5e1 !important; }
    /* Estilo de ALTO CONTRASTE para o Modo Claro */
    html.light-mode .ticket-card { 
        background: #ffffff !important; 
        border: 2px solid #cbd5e1 !important; 
        box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1) !important; 
    }
    html.light-mode .ticket-card:hover { 
        border-color: #6366f1 !important; 
        box-shadow: 0 20px 30px -10px rgba(99, 102, 241, 0.2) !important; 
    }
    
    html.light-mode .ticket-card h5 { font-family: 'Outfit', sans-serif; font-weight: 900 !important; color: #000000 !important; font-size: 19px !important; }
    html.light-mode .ticket-card p { font-family: 'Inter', sans-serif; font-weight: 600 !important; color: #1e293b !important; line-height: 1.6; font-size: 14px !important; }
    html.light-mode .ticket-card .text-slate-300 { color: #000000 !important; font-weight: 700 !important; }
    html.light-mode .ticket-card .text-indigo-400 { color: #3730a3 !important; font-weight: 800 !important; }
    html.light-mode .ticket-card .text-slate-500 { color: #475569 !important; font-weight: 700 !important; }
    html.light-mode .ticket-card .text-white { color: #000000 !important; }
    html.light-mode .ticket-card .bg-slate-900\/40 { background: #f1f5f9 !important; border: 1px solid #cbd5e1 !important; }

    /* Campos de Busca de Alta Visibilidade */
    html.light-mode .search-focus { 
        background: #ffffff !important; 
        border: 2px solid #6366f1 !important; 
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1) !important;
    }
    html.light-mode .search-focus input { color: #000000 !important; font-weight: 700 !important; }
    html.light-mode .search-focus input::placeholder { color: #64748b !important; }
    
    /* Painéis Superiores Sólidos */
    html.light-mode .glass-panel { background: #ffffff !important; border: 2px solid #e2e8f0 !important; box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important; }
    html.light-mode .glass-panel .text-white { color: #000000 !important; font-weight: 800 !important; }
    html.light-mode .bg-slate-900\/40 { background: #f8fafc !important; border: 1px solid #e2e8f0 !important; }
    html.light-mode .text-slate-500 { color: #334155 !important; font-weight: 700 !important; }

    /* Cores das Bolhas de Chat (Modo Claro) */
    html.light-mode .msg-bubble-me { background: #3730a3 !important; color: #ffffff !important; }
    html.light-mode .msg-bubble-other { background: #e2e8f0 !important; color: #000000 !important; border: 1px solid #cbd5e1 !important; }

    .side-panel.open { transform: translateX(0) !important; }

    /* Overlay Minimalista (Sem embaçar o fundo excessivamente) */
    .side-panel-overlay {
        position: fixed !important;
        inset: 0 !important;
        background: transparent !important; /* Totalmente invisível */
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
        z-index: 8999 !important;
        opacity: 0 !important;
        pointer-events: none !important;
        transition: opacity 0.5s ease !important;
    }
    .side-panel-overlay.open { opacity: 1 !important; pointer-events: auto !important; }

    /* Bloquear Scroll do Body quando aberto */
    body.chat-open { overflow: hidden !important; }

    /* Ajustes Específicos para a Vista do Colaborador (Modo Claro) */
    html.light-mode .glass-panel.rounded-\[2rem\] { 
        background: #ffffff !important; 
        border: 2px solid #e2e8f0 !important; 
    }
    html.light-mode .status-tab { 
        color: #475569 !important; 
        font-weight: 800 !important;
    }
    html.light-mode .status-tab.active-tab { 
        background: #3730a3 !important; 
        color: #ffffff !important; 
    }
    html.light-mode div.bg-slate-950\/40 { 
        background: #f1f5f9 !important; 
        border: 1px solid #cbd5e1 !important; 
    }
    html.light-mode .px-8.py-6.border-b.border-white\/5 { 
        background: #f8fafc !important; 
        border-bottom: 2px solid #e2e8f0 !important; 
    }
    html.light-mode .px-8.py-6.border-b.border-white\/5 h3 { 
        color: #000000 !important; 
        font-weight: 900 !important; 
    }

    /* Floating Message Avatar (Right Side) */
    #msg-fab {
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 1000;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        /* Sem background, sem border-radius pill - o contadorzinho fica solto */
        background: transparent;
        border: none;
        padding: 0;
        transition: transform 0.3s ease;
    }
    #msg-fab:hover { transform: scale(1.08) translateY(-6px); }

    #msg-fab .pulse-ring { display: none; }
    #msg-fab .new-label { display: none; }
    #msg-fab.has-new .pulse-ring { display: block; }
    #msg-fab.has-new .new-label { display: block; }

    #msg-badge {
        position: absolute;
        top: -4px;
        right: -4px;
        background: #ff0000;
        color: white;
        font-size: 11px;
        font-weight: 900;
        padding: 4px 8px;
        border-radius: 20px;
        border: 2px solid #ffffff;
        box-shadow: 0 0 15px rgba(255, 0, 0, 0.6);
        display: none;
        z-index: 1001;
    }
    #msg-fab.has-new #msg-badge { display: block; }

    .fab-avatar-svg {
        width: 160px;
        height: 190px;
        display: block;
        overflow: visible;
        filter: drop-shadow(0 8px 20px rgba(0,0,0,0.6));
    }

    .fab-label {
        background: #4f46e5;
        color: white;
        font-weight: 900;
        font-size: 11px;
        padding: 5px 16px;
        border-radius: 100px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        box-shadow: 0 4px 15px rgba(79,70,229,0.5);
        border: 1px solid rgba(255,255,255,0.2);
    }

    @keyframes pulseAttention { 0% { transform: scale(1); opacity: 0.8; } 100% { transform: scale(1.5); opacity: 0; } }
    @keyframes pulseFade { 0% { transform: scale(1); opacity: 0.5; } 100% { transform: scale(1.3); opacity: 0; } }

    /* Animações do Contadorzinho - definidas aqui para garantir funcionamento */
    .contador-head { animation: cHeadBob 3s ease-in-out infinite; transform-origin: 65px 92px; }
    .contador-arm-l { animation: cArmSwingL 3s ease-in-out infinite; transform-origin: 43px 90px; }
    .contador-arm-r { animation: cArmSwingR 3s ease-in-out infinite; transform-origin: 87px 90px; }
    .contador-leg-l { animation: cLegSwingL 3s ease-in-out infinite; transform-origin: 55px 118px; }
    .contador-leg-r { animation: cLegSwingR 3s ease-in-out infinite; transform-origin: 75px 118px; }

    @keyframes cHeadBob {
        0%, 100% { transform: rotate(0deg) translateY(0); }
        50% { transform: rotate(4deg) translateY(-4px); }
    }
    @keyframes cArmSwingL {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(-25deg); }
    }
    @keyframes cArmSwingR {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(25deg); }
    }
    @keyframes cLegSwingL {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(18deg); }
    }
    @keyframes cLegSwingR {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(-18deg); }
    }
</style>

<!-- Container para Notificações em Tempo Real -->
<div id="live-toast-container"></div>

<!-- Botão Flutuante de Mensagem (Permanente no lado direito) -->
<div id="msg-fab" onclick="resetUnread(); openGlobalChat();">
    <div id="msg-badge">0</div>
    <div class="pulse-ring"></div>
    <div class="flex items-center justify-center bg-indigo-600 hover:bg-indigo-500 transition-colors rounded-full shadow-[0_10px_20px_rgba(79,70,229,0.5)] border-2 border-white/20" style="width: 60px; height: 60px; margin-bottom: 8px;">
        <svg class="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
    </div>
    <span class="fab-label">Chat</span>
</div>

<audio id="notif-sound" src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" preload="auto"></audio>

<div class="mb-8 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-8">
    <div class="flex items-center gap-4 flex-grow">
        <div class="p-3 bg-blue-500/10 rounded-2xl border border-blue-500/20 shadow-inner hidden sm:block">
            <svg class="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
        </div>
        <div>
            <h2 class="text-3xl font-black text-[var(--text-primary)] mb-1 tracking-tighter uppercase italic">Central de Suporte</h2>
            <p class="text-[var(--text-secondary)] font-bold uppercase tracking-[0.3em] text-[10px] opacity-70">Gestao Visual e Inteligencia de Atendimento</p>
        </div>
    </div>
    
    <?php 
    // Cálculo de Eficiência (Saúde)
    $perc = $totalChamados > 0 ? round(($stats['resolvidos'] / $totalChamados) * 100) : 100;
    $color = $perc > 80 ? '#10b981' : ($perc > 50 ? '#f59e0b' : '#ef4444');
    ?>

    <!-- Novo Painel de Inteligência Premium -->
    <div class="flex flex-wrap lg:flex-nowrap gap-4 w-full lg:w-auto">
        <!-- Card: Pendentes -->
        <div class="flex-1 min-w-[140px] glass-panel p-5 rounded-[2rem] border border-blue-500/10 relative overflow-hidden group">
            <div class="absolute -right-4 -top-4 w-16 h-16 bg-blue-500/10 rounded-full blur-xl group-hover:bg-blue-500/20 transition-all"></div>
            <div class="flex items-center gap-4 relative z-10">
                <div class="w-12 h-12 rounded-2xl bg-blue-500/10 flex items-center justify-center text-blue-500 border border-blue-500/20 shadow-lg">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </div>
                <div>
                    <span class="block text-[24px] font-black text-white leading-none mb-1"><?= $stats['abertos'] ?></span>
                    <span class="block text-[8px] text-blue-400 font-black uppercase tracking-[0.2em]">Pendentes</span>
                </div>
            </div>
        </div>

        <!-- Card: Em Atendimento -->
        <div class="flex-1 min-w-[140px] glass-panel p-5 rounded-[2rem] border border-amber-500/10 relative overflow-hidden group">
            <div class="absolute -right-4 -top-4 w-16 h-16 bg-amber-500/10 rounded-full blur-xl group-hover:bg-amber-500/20 transition-all"></div>
            <div class="flex items-center gap-4 relative z-10">
                <div class="w-12 h-12 rounded-2xl bg-amber-500/10 flex items-center justify-center text-amber-500 border border-amber-500/20 shadow-lg">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                </div>
                <div>
                    <span class="block text-[24px] font-black text-white leading-none mb-1"><?= $stats['atendimento'] ?></span>
                    <span class="block text-[8px] text-amber-400 font-black uppercase tracking-[0.2em]">Em Curso</span>
                </div>
            </div>
        </div>

        <!-- Card: Finalizados -->
        <div class="flex-1 min-w-[140px] glass-panel p-5 rounded-[2rem] border border-emerald-500/10 relative overflow-hidden group">
            <div class="absolute -right-4 -top-4 w-16 h-16 bg-emerald-500/10 rounded-full blur-xl group-hover:bg-emerald-500/20 transition-all"></div>
            <div class="flex items-center gap-4 relative z-10">
                <div class="w-12 h-12 rounded-2xl bg-emerald-500/10 flex items-center justify-center text-emerald-500 border border-emerald-500/20 shadow-lg">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </div>
                <div>
                    <span class="block text-[24px] font-black text-white leading-none mb-1"><?= $stats['resolvidos'] ?></span>
                    <span class="block text-[8px] text-emerald-400 font-black uppercase tracking-[0.2em]">Resolvidos</span>
                </div>
            </div>
        </div>

        <!-- Saúde do Sistema -->
        <div class="flex-grow lg:flex-grow-0 min-w-[180px] bg-slate-900/40 p-6 rounded-[2.5rem] border border-white/5 backdrop-blur-md flex flex-col justify-center gap-3">
            <div class="flex justify-between items-center px-1">
                <span class="text-[9px] font-black text-slate-500 uppercase tracking-widest">Taxa de Saúde</span>
                <span class="text-[12px] font-black text-indigo-400"><?= $perc ?>%</span>
            </div>
            <div class="h-1.5 w-full bg-white/5 rounded-full overflow-hidden">
                <div class="h-full transition-all duration-1000 shadow-[0_0_10px_<?= $color ?>]" style="width: <?= $perc ?>%; background: <?= $color ?>;"></div>
            </div>
            <?php if($stats['urgentes'] > 0): ?>
                <div class="flex items-center gap-2 text-rose-500 animate-pulse">
                    <div class="w-1.5 h-1.5 rounded-full bg-rose-500"></div>
                    <span class="text-[8px] font-black uppercase tracking-widest"><?= $stats['urgentes'] ?> Tickets Críticos</span>
                </div>
            <?php endif; ?>
        </div>
    </div>
</div>

<!-- Barra de Busca e Filtros -->
<div class="mb-8 flex flex-col md:flex-row gap-4 items-center justify-between">
    <div class="relative w-full md:max-w-md search-focus bg-slate-900/40 rounded-2xl border border-white/10 p-1 flex items-center transition-all shadow-inner">
        <div class="pl-4 text-slate-500">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
        </div>
        <input type="text" id="ticketSearch" onkeyup="filterTickets()" placeholder="Pesquisar por titulo, usuario ou descricao..." 
               class="w-full bg-transparent border-none focus:ring-0 text-sm font-bold text-white px-4 py-3 placeholder-slate-600">
    </div>
    
    <div class="flex flex-wrap gap-2 justify-center">
        <button onclick="setFilter('Todos')" class="px-4 py-2.5 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-[10px] font-black uppercase tracking-widest hover:bg-indigo-600 hover:text-white transition-all filter-btn active-filter shadow-lg" data-filter="Todos">Todos</button>
        <button onclick="setFilter('Alta')" class="px-4 py-2.5 rounded-xl bg-rose-500/10 text-rose-400 border border-rose-500/20 text-[10px] font-black uppercase tracking-widest hover:bg-rose-600 hover:text-white transition-all filter-btn shadow-lg" data-filter="Alta">Urgente</button>
        <button onclick="setFilter('Impressora')" class="px-4 py-2.5 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-black uppercase tracking-widest hover:bg-blue-600 hover:text-white transition-all filter-btn shadow-lg" data-filter="Impressora">Impressão</button>
        <button onclick="setFilter('Rede/Internet')" class="px-4 py-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-black uppercase tracking-widest hover:bg-emerald-600 hover:text-white transition-all filter-btn shadow-lg" data-filter="Rede/Internet">Rede</button>
    </div>
</div>

<?php if ($message): ?>
    <div class="mb-8 p-5 text-sm font-bold rounded-2xl border relative z-10 backdrop-blur-md shadow-2xl animate-[slideIn_0.3s_ease-out]
        <?= $tipo_msg === 'success' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20' ?>">
        <div class="flex items-center gap-4">
            <div class="w-8 h-8 rounded-full <?= $tipo_msg === 'success' ? 'bg-emerald-500/20' : 'bg-rose-500/20' ?> flex items-center justify-center">
                <svg class="w-5 h-5 font-bold" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <?= htmlspecialchars($message) ?>
        </div>
    </div>
<?php endif; ?>

<div class="grid grid-cols-1 lg:grid-cols-4 gap-8 mb-12">
    <!-- Interface de Abertura Operacional (Visual Wizard) -->
    <div class="lg:col-span-1">
        <div class="glass-panel rounded-[2.5rem] border border-white/10 shadow-2xl sticky top-24 overflow-hidden bg-slate-900/40">
            <!-- Barra de Progresso Wizard -->
            <div class="h-1.5 w-full bg-white/5 flex">
                <div id="wizard_progress" class="h-full bg-indigo-500 transition-all duration-500 shadow-[0_0_10px_#6366f1]" style="width: 33%"></div>
            </div>

            <div class="p-8">
                <div class="flex items-center justify-between mb-8">
                    <h3 id="wizard_title" class="text-xl font-black text-white uppercase tracking-tight italic">O que houve?</h3>
                    <span id="wizard_step_label" class="px-3 py-1 bg-indigo-500/10 text-indigo-400 rounded-full text-[8px] font-black uppercase tracking-widest border border-indigo-500/20">Passo 1/2</span>
                </div>
                
                <form id="formChamado" action="chamados.php" method="POST" enctype="multipart/form-data" onsubmit="return handleDoubleSubmit(this)">
                    <input type="hidden" name="action" value="abrir">
                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                    <input type="hidden" name="prioridade" id="input_prioridade" value="Media">
                    <input type="hidden" name="categoria" id="input_categoria" value="Outros">
                    <input type="hidden" name="titulo" id="input_titulo" value="">

                    <!-- PASSO 1: Seleção de Problema -->
                    <div id="step_1" class="wizard-step step-active space-y-6">
                        <div class="grid grid-cols-2 gap-3">
                            <?php foreach($atalhosProblemas as $ap): ?>
                                <div onclick="selectProblem(this, '<?= addslashes($ap['label']) ?>', '<?= addslashes($ap['descricao_padrao'] ?? '') ?>', '<?= $ap['categoria'] ?>', '<?= $ap['prioridade_padrao'] ?>')" class="problem-node p-5 bg-white/5 rounded-3xl text-center group active:scale-95">
                                    <span class="block text-3xl mb-2"><?= $ap['icone'] ?></span>
                                    <span class="block text-[9px] font-black text-slate-400 uppercase tracking-widest group-hover:text-white"><?= htmlspecialchars($ap['label']) ?></span>
                                </div>
                            <?php endforeach; ?>
                            
                            <div onclick="selectProblem(this, 'Outro Problema', '', 'Outros', 'Media')" class="problem-node col-span-2 p-4 bg-white/5 rounded-3xl text-center flex items-center justify-center gap-3 group active:scale-95">
                                <span class="text-2xl">🛠️</span>
                                <span class="text-[10px] font-black text-slate-400 uppercase tracking-widest group-hover:text-white">Outra Situação</span>
                            </div>
                        </div>
                        <?php if(hasPermission('config_suporte')): ?>
                            <div class="text-center">
                                <button type="button" onclick="openAdminAtalhos()" class="text-[8px] font-black text-indigo-400 hover:text-white uppercase tracking-widest opacity-60">+ Configurar Opções</button>
                            </div>
                        <?php endif; ?>
                    </div>

                    <!-- PASSO 2: Detalhes e Envio -->
                    <div id="step_2" class="wizard-step step-inactive space-y-5">
                        <div id="field_titulo_custom" class="hidden">
                            <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Assunto Específico</label>
                            <input type="text" name="titulo_custom" id="titulo_custom" class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold text-sm" placeholder="Ex: Monitor piscando">
                        </div>
                        
                        <div>
                            <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Descrição do Ocorrido</label>
                            <textarea name="descricao" id="input_descricao" required rows="3" class="glass-input w-full px-5 py-4 rounded-2xl text-white text-sm font-medium resize-none" placeholder="Conte-nos o que houve..."></textarea>
                        </div>

                        <div>
                            <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Selecione o Equipamento</label>
                            <select name="equipamento_id" class="glass-input w-full px-5 py-3.5 rounded-2xl text-white font-bold text-xs appearance-none cursor-pointer">
                                <option value="">Não sei identificar / Outro</option>
                                <?php foreach ($listaImpressoras as $imp): ?>
                                    <option value="<?= $imp['id'] ?>"><?= htmlspecialchars($imp['nome']) ?></option>
                                <?php endforeach; ?>
                            </select>
                        </div>

                        <!-- Anexo Rápido -->
                        <div id="dropzone" class="relative group p-6 bg-white/5 rounded-3xl border-2 border-dashed border-white/5 hover:border-indigo-500/40 transition-all text-center cursor-pointer">
                            <input type="file" name="anexo" id="anexo_file" accept="image/*" class="hidden">
                            <div id="anexo_preview" class="hidden mb-3"><img id="img_preview" class="h-16 mx-auto rounded-xl shadow-2xl border border-white/10"></div>
                            <div id="dropzone_prompt">
                                <svg class="w-7 h-7 text-indigo-400 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                                <span class="block text-[9px] font-black text-slate-400 uppercase tracking-widest group-hover:text-white">Anexar ou Cole (Ctrl+V)</span>
                            </div>
                        </div>

                        <div class="flex gap-3">
                            <button type="button" onclick="prevStep()" class="w-14 h-14 rounded-2xl bg-white/5 flex items-center justify-center text-slate-400 hover:bg-white/10 hover:text-white transition-all">
                                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path></svg>
                            </button>
                            <button type="submit" class="flex-grow bg-gradient-to-br from-indigo-500 to-indigo-700 text-white font-black text-xs uppercase tracking-widest rounded-2xl hover:shadow-[0_15px_30px_-5px_rgba(99,102,241,0.4)] transition-all active:scale-95 border border-white/10 flex items-center justify-center gap-3">
                                <span>Enviar Agora</span>
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
                            </button>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Interface Kanban / Lista -->
    <div class="lg:col-span-3">
        <?php if($isAdmin): ?>
        
        <!-- Visualização Kanban para Administradores -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <!-- COLUNA: PENDENTES -->
            <div class="space-y-4">
                <div class="flex items-center justify-between px-4 py-3 bg-slate-900/40 rounded-2xl border border-white/5 mb-2 shadow-inner">
                    <h4 class="text-[11px] font-black text-rose-400 uppercase tracking-widest">Pendente (<?= $stats['abertos'] ?>)</h4>
                    <div class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></div>
                </div>
                <div class="space-y-4 kanban-col shadow-inner">
                    <?php foreach($chamados as $c): if($c['status'] === 'Aberto'): ?>
                        <?= renderChamadoCard($c, $isAdmin) ?>
                    <?php endif; endforeach; ?>
                </div>
            </div>

            <!-- COLUNA: EM ATENDIMENTO -->
            <div class="space-y-4">
                <div class="flex items-center justify-between px-4 py-3 bg-slate-900/40 rounded-2xl border border-white/5 mb-2 shadow-inner">
                    <h4 class="text-[11px] font-black text-amber-400 uppercase tracking-widest">Em Curso (<?= $stats['atendimento'] ?>)</h4>
                    <div class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-bounce"></div>
                </div>
                <div class="space-y-4 kanban-col shadow-inner">
                    <?php foreach($chamados as $c): if($c['status'] === 'Em Atendimento'): ?>
                        <?= renderChamadoCard($c, $isAdmin) ?>
                    <?php endif; endforeach; ?>
                </div>
            </div>

            <!-- COLUNA: CONCLUÍDOS -->
            <div class="space-y-4">
                <div class="flex items-center justify-between px-4 py-3 bg-slate-900/40 rounded-2xl border border-white/5 mb-2 shadow-inner">
                    <h4 class="text-[11px] font-black text-emerald-400 uppercase tracking-widest">Finalizado (<?= $stats['resolvidos'] ?>)</h4>
                    <div class="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
                </div>
                <div class="space-y-4 kanban-col shadow-inner">
                    <?php foreach($chamados as $c): if($c['status'] === 'Resolvido'): ?>
                        <?= renderChamadoCard($c, $isAdmin) ?>
                    <?php endif; endforeach; ?>
                </div>
            </div>
        </div>
        <?php else: ?>
            <!-- Lista Moderna para Operadores (Com Abas) -->
            <div class="glass-panel rounded-[2rem] overflow-hidden border border-white/10 shadow-2xl bg-slate-900/20">
                <div class="px-8 py-6 border-b border-white/5 bg-slate-800/10 flex flex-col sm:flex-row justify-between items-center gap-4">
                    <h3 class="text-sm font-black text-white uppercase tracking-[0.2em] italic">Meus Chamados</h3>
                    
                    <!-- Abas de Status -->
                    <div class="flex bg-slate-950/40 p-1 rounded-xl border border-white/5 shadow-inner">
                        <button onclick="setStatusFilter('Ativos')" class="status-tab px-4 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-widest transition-all bg-indigo-600 text-white shadow-lg" data-status="Ativos">Ativos</button>
                        <button onclick="setStatusFilter('Resolvido')" class="status-tab px-4 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-widest text-slate-500 hover:text-white transition-all" data-status="Resolvido">Finalizados</button>
                        <button onclick="setStatusFilter('Todos')" class="status-tab px-4 py-1.5 rounded-lg text-[9px] font-black uppercase tracking-widest text-slate-500 hover:text-white transition-all" data-status="Todos">Todos</button>
                    </div>
                </div>

                <div class="p-8">
                    <div id="user-ticket-list" class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <?php foreach($chamados as $c): ?>
                            <div class="user-ticket-item" data-status="<?= $c['status'] ?>">
                                <?= renderChamadoCard($c, $isAdmin) ?>
                            </div>
                        <?php endforeach; ?>
                        
                        <?php if(empty($chamados)): ?>
                            <div class="col-span-full py-20 text-center opacity-50">
                                <div class="text-5xl mb-4">📭</div>
                                <p class="text-xs font-black text-slate-500 uppercase tracking-widest">Nenhum chamado registrado.</p>
                            </div>
                        <?php endif; ?>
                    </div>
                </div>
            </div>
        <?php endif; ?>
    </div>
</div>

<!-- Modal Mural de Interação (Painel Lateral) -->
<div id="muralOverlay" class="side-panel-overlay" onclick="closeMuralModal()"></div>
<div id="muralModal" class="side-panel">
    <!-- Topo do Mural -->
    <div class="p-8 border-b border-white/5 bg-slate-900/60 flex-shrink-0">
        <div class="flex items-center justify-between mb-3">
            <div class="flex flex-col">
                <h3 id="mural_titulo" class="text-xl font-black text-white uppercase tracking-tighter italic leading-none mb-1">Mural de Interação</h3>
                <span id="mural_autor" class="text-[9px] text-slate-500 font-black uppercase tracking-widest">Iniciando conversa...</span>
            </div>
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 rounded-full border border-emerald-500/20">
                    <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                    <span class="text-[8px] text-emerald-400 font-black uppercase tracking-widest">Ao Vivo</span>
                </div>
                <button onclick="closeMuralModal()" class="text-slate-500 hover:text-white transition-all hover:rotate-90 duration-300">
                    <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                </button>
            </div>
        </div>
    </div>

    <div class="flex-grow flex flex-col relative min-h-0">
        <!-- Área das Mensagens -->
        <div id="mural_timeline" class="flex-grow overflow-y-auto p-7 space-y-5" style="min-height:200px">
            <!-- Mensagens injetadas via JS -->
        </div>

        <!-- Indicador de Digitação (painel separado) -->
        <div id="mural_typing_bar" class="hidden px-7 pb-2 flex-shrink-0">
            <div class="flex items-center gap-2 bg-slate-800/40 px-4 py-2.5 rounded-2xl border border-white/5 w-fit">
                <div class="flex gap-1">
                    <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce" style="animation-delay:0ms"></span>
                    <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce" style="animation-delay:150ms"></span>
                    <span class="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-bounce" style="animation-delay:300ms"></span>
                </div>
                <span id="mural_typing_text" class="text-[9px] text-indigo-400 font-black uppercase tracking-widest italic"></span>
            </div>
        </div>


        <!-- Campo de Mensagem -->
        <div class="p-6 border-t border-white/5 bg-slate-900/60 flex-shrink-0 relative">
            <!-- Seletor de Emojis (Glass Popover) -->
            <div id="emoji_picker" class="hidden absolute bottom-24 left-6 z-50 bg-slate-900/95 border border-white/10 rounded-[2rem] p-5 shadow-2xl backdrop-blur-2xl w-[290px] animate-[slideUp_0.2s_ease-out]">
                <div class="flex items-center justify-between mb-3 px-1">
                    <span class="text-[9px] font-black text-slate-500 uppercase tracking-widest italic">Expressões Rápidas</span>
                    <button onclick="toggleEmojiPicker()" class="text-slate-600 hover:text-white">✕</button>
                </div>
                <div id="emoji_grid" class="grid grid-cols-6 gap-2 max-h-[180px] overflow-y-auto pr-1 custom-scrollbar">
                    <!-- Emojis injetados via JS -->
                </div>
            </div>

            <div class="flex gap-3 items-end">
                <textarea id="mural_msg" rows="1" class="glass-input flex-grow px-5 py-4 rounded-2xl text-white font-medium text-sm leading-relaxed shadow-inner resize-none overflow-hidden" placeholder="Escreva algo... (Enter envia)" style="min-height:54px; max-height:150px;"></textarea>
                <button id="mural_send_btn" onclick="chatSendMessage()" class="w-12 h-12 bg-indigo-600 text-white rounded-2xl flex items-center justify-center hover:bg-indigo-500 transition-all shadow-lg hover:shadow-indigo-500/25 active:scale-95 flex-shrink-0 mb-1">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
                </button>
            </div>
        </div>
    </div>
</div>

<!-- Modal Gerenciar Atalhos (Admin) -->
<div id="adminAtalhosModal" class="hidden fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/90 backdrop-blur-xl p-4">
    <div class="glass-panel w-full max-w-2xl p-10 rounded-[3rem] border border-white/10 shadow-2xl relative overflow-y-auto" style="max-height: 90vh">
        <button onclick="closeAdminAtalhos()" class="absolute top-8 right-8 text-slate-500 hover:text-white transition-all hover:rotate-90"><svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
        
        <div class="mb-10">
            <h3 class="text-3xl font-black text-white mb-2 uppercase italic tracking-tight">Gerenciar Atalhos</h3>
            <p class="text-slate-500 text-[10px] font-black uppercase tracking-[0.2em]">Personalize a experiência do usuário final</p>
        </div>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-10">
            <!-- Coluna: Lista Atual -->
            <div class="space-y-4">
                <h4 class="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-4">Atalhos Ativos</h4>
                <div class="space-y-3 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                    <?php foreach($atalhosProblemas as $ap): ?>
                        <div class="flex items-center justify-between p-4 bg-white/5 rounded-2xl border border-white/5 group hover:bg-white/10 transition-all">
                            <div class="flex items-center gap-4">
                                <span class="text-2xl"><?= $ap['icone'] ?></span>
                                <div>
                                    <span class="block text-xs font-black text-white uppercase"><?= htmlspecialchars($ap['label']) ?></span>
                                    <span class="block text-[8px] text-indigo-400 font-bold uppercase tracking-widest"><?= $ap['categoria'] ?></span>
                                </div>
                            </div>
                            <div class="flex items-center gap-1">
                                <button type="button" onclick='editAtalho(<?= json_encode($ap) ?>)' class="w-8 h-8 flex items-center justify-center text-indigo-400 hover:bg-indigo-400/20 rounded-lg transition-all">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                                </button>
                                <form action="chamados.php" method="POST" onsubmit="return confirm('Deseja realmente excluir este atalho?')">
                                    <input type="hidden" name="action" value="del_atalho">
                                    <input type="hidden" name="id" value="<?= $ap['id'] ?>">
                                    <button type="submit" class="w-8 h-8 flex items-center justify-center text-rose-500 hover:bg-rose-500/20 rounded-lg transition-all">
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                    </button>
                                </form>
                            </div>
                        </div>
                    <?php endforeach; ?>
                </div>
            </div>

            <!-- Coluna: Adicionar/Editar -->
            <div class="space-y-6">
                <h4 id="atalho_form_title" class="text-[10px] font-black text-indigo-400 uppercase tracking-widest">Criar Novo Atalho</h4>
                
                <!-- Preview em Tempo Real -->
                <div class="p-6 rounded-[2rem] border border-dashed border-indigo-500/30 bg-indigo-500/5 text-center">
                    <p class="text-[8px] text-indigo-400 font-black uppercase tracking-widest mb-4">Pré-visualização</p>
                    <div id="btn_preview" class="problem-node p-5 bg-white/10 rounded-3xl mx-auto w-32 border border-white/10">
                        <span id="preview_icon" class="block text-3xl mb-2">🛠️</span>
                        <span id="preview_label" class="block text-[9px] font-black text-slate-400 uppercase tracking-widest">Novo Botão</span>
                    </div>
                </div>

                <form method="POST" action="chamados.php" id="form_gerenciar_atalho">
                    <input type="hidden" name="action" id="atalho_action" value="add_atalho">
                    <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                    <input type="hidden" name="id" id="atalho_edit_id" value="">
                    
                    <div>
                        <label class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Escolha ou Cole um Ícone</label>
                        <div class="grid grid-cols-6 gap-2 p-3 bg-white/5 rounded-2xl border border-white/5 mb-3">
                            <?php 
                            $iconesSugeridos = ['🌑','📄','🌐','🐌','💻','🖱️','⌨️','🖥️','🔌','📶','🖨️','🛠️','⚠️','🔥','❄️','📢','📱','🔒','☁️'];
                            foreach($iconesSugeridos as $ic):
                            ?>
                                <button type="button" onclick="setPickerIcon('<?= $ic ?>')" class="text-xl hover:scale-125 transition-transform p-1"><?= $ic ?></button>
                            <?php endforeach; ?>
                        </div>
                        <input type="text" name="icone" id="input_picker_icon" value="🛠️" placeholder="Ou cole um emoji aqui..." class="glass-input w-full p-4 rounded-2xl text-center text-2xl" onkeyup="updatePreview()">
                    </div>

                    <input type="text" name="label" id="input_picker_label" placeholder="Nome no Botão" class="glass-input w-full p-4 rounded-2xl text-sm font-bold" required onkeyup="updatePreview()">
                    <input type="text" name="titulo_padrao" id="input_picker_titulo" placeholder="Assunto automático" class="glass-input w-full p-4 rounded-2xl text-xs font-medium">
                    
                    <div class="grid grid-cols-2 gap-3">
                        <select name="categoria" id="input_picker_cat" class="glass-input p-4 rounded-2xl text-xs font-bold appearance-none">
                            <option value="Impressora">Impressora</option>
                            <option value="Rede/Internet">Rede/Internet</option>
                            <option value="Computador/Hardware">Máquina</option>
                            <option value="Outros">Outros</option>
                        </select>
                        <select name="prioridade" id="input_picker_pri" class="glass-input p-4 rounded-2xl text-xs font-bold appearance-none">
                            <option value="Baixa">Baixa</option>
                            <option value="Media" selected>Média</option>
                            <option value="Alta">Alta</option>
                        </select>
                    </div>
                    
                    <div class="flex gap-2">
                        <button type="submit" id="atalho_submit_btn" class="flex-grow py-5 bg-gradient-to-br from-indigo-500 to-indigo-700 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-indigo-500/20 active:scale-95 transition-all">Salvar Atalho</button>
                        <button type="button" id="cancel_edit_btn" onclick="cancelEditAtalho()" class="hidden w-14 py-5 bg-white/5 text-slate-400 rounded-2xl hover:bg-white/10 hover:text-white transition-all flex items-center justify-center">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- Modal de Resolução Técnica -->
<div id="solutionModal" class="hidden fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/90 backdrop-blur-xl p-4">
    <div class="glass-panel w-full max-w-lg p-10 rounded-[3rem] border border-white/10 shadow-[0_50px_100px_-20px_rgba(0,0,0,0.5)] relative animate-[slideIn_0.2s_ease-out]">
        <button onclick="closeSolutionModal()" class="absolute top-8 right-8 text-slate-500 hover:text-white transition-all hover:rotate-90 duration-300"><svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg></button>
        
        <div class="mb-8">
            <h3 class="text-3xl font-black text-white mb-2 uppercase tracking-tight italic">Relatório de Solução</h3>
            <p class="text-slate-500 text-[10px] font-black uppercase tracking-[0.2em]">O que foi realizado para fechar este Ticket?</p>
        </div>
        
        <form action="chamados.php" method="POST" class="space-y-8">
            <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
            <input type="hidden" name="action" value="resolver">
            <input type="hidden" name="chamado_id" id="modal_chamado_id">
            
            <textarea name="nota_tecnica" required rows="5" class="glass-input w-full px-8 py-6 rounded-[2rem] text-white font-medium text-sm leading-relaxed shadow-inner" placeholder="Ex: Substituição de cilindro e limpeza de roletes efetuada..."></textarea>
            
            <button type="submit" class="w-full bg-gradient-to-br from-emerald-500 to-emerald-800 text-white font-black text-xs uppercase tracking-[0.2em] py-6 rounded-2xl shadow-[0_15px_35px_-10px_rgba(16,185,129,0.4)] active:scale-95 transition-all border border-emerald-400/20">Registrar e Finalizar</button>
        </form>
    </div>
</div>

<?php
function renderChamadoCard($c, $isAdmin) {
    ob_start();
    $isEmAtendimento = $c['status'] === 'Em Atendimento';
    $isResolvido = $c['status'] === 'Resolvido';

    // Cálculo de tempo decorrido (SLA)
    $inicio = new DateTime($c['data_abertura']);
    $agora = new DateTime();
    $diff = $inicio->diff($agora);
    if ($diff->d > 0) $tempoMsg = $diff->d . 'd ' . $diff->h . 'h';
    elseif ($diff->h > 0) $tempoMsg = $diff->h . 'h ' . $diff->i . 'm';
    else $tempoMsg = $diff->i . ' min';

    $priColor = 'text-slate-400';
    $priBorder = 'border-slate-800/50';
    $glowClass = '';
    if($c['prioridade'] === 'Alta') { 
        $priColor = 'text-rose-400'; 
        $priBorder = 'border-rose-500/20 html-light:border-rose-300'; 
        $glowClass = 'priority-alta-glow';
    }
    elseif($c['prioridade'] === 'Media') { $priColor = 'text-amber-400'; $priBorder = 'border-amber-500/20 html-light:border-amber-300'; }
    elseif($c['prioridade'] === 'Baixa') { $priColor = 'text-blue-400'; $priBorder = 'border-blue-500/20 html-light:border-blue-300'; }

    ?>
    <div class="ticket-card glass-card-magnetic glass-panel p-7 rounded-[2rem] border <?= $priBorder ?> <?= $glowClass ?> transition-all duration-500 group relative flex flex-col h-full shadow-lg hover:shadow-indigo-500/10" 
         data-title="<?= strtolower(htmlspecialchars($c['titulo'])) ?>" 
         data-user="<?= strtolower(htmlspecialchars($c['usuario'])) ?>" 
         data-desc="<?= strtolower(htmlspecialchars($c['descricao'])) ?>"
         data-priority="<?= $c['prioridade'] ?>"
         data-category="<?= $c['categoria'] ?>">
        <!-- Barra de Progresso Visual (Stepper) -->
        <div class="flex items-center mb-5 <?= $isResolvido ? 'text-emerald-500' : ($isEmAtendimento ? 'text-amber-500' : 'text-blue-500') ?>">
            <div class="stepper-dot active"></div>
            <div class="stepper-line <?= $isEmAtendimento || $isResolvido ? 'active' : '' ?>"></div>
            <div class="stepper-dot <?= $isEmAtendimento || $isResolvido ? 'active' : '' ?>"></div>
            <div class="stepper-line <?= $isResolvido ? 'active' : '' ?>"></div>
            <div class="stepper-dot <?= $isResolvido ? 'active' : '' ?>"></div>
            <span class="ml-3 text-[8px] font-black uppercase tracking-[0.2em] italic"><?= $c['status'] ?></span>
        </div>

        <div class="flex justify-between items-start mb-4">
            <span class="px-3 py-1 rounded-full text-[8px] font-black uppercase tracking-widest border border-white/10 bg-slate-900/60 <?= $priColor ?> html-light:border-black html-light:bg-slate-100 html-light:text-black">
                <span class="mr-1.5">●</span> <?= $c['prioridade'] ?>
            </span>
            <div class="flex items-center gap-2">
                <?php if($c['anexo_url']): ?>
                    <a href="<?= $c['anexo_url'] ?>" target="_blank" class="w-8 h-8 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center border border-indigo-500/30 hover:bg-indigo-500 hover:text-white transition-all shadow-lg" title="Ver Anexo">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.414a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                    </a>
                <?php endif; ?>
                <?php if(!$isResolvido): ?>
                    <div class="text-[9px] text-slate-500 font-black uppercase tracking-widest bg-white/5 px-2.5 py-1 rounded-lg html-light:bg-slate-200 html-light:text-black flex items-center gap-1.5">
                        <svg class="w-3 h-3 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        Há <?= $tempoMsg ?>
                    </div>
                <?php else: ?>
                    <div class="text-[9px] text-emerald-500 font-black uppercase tracking-widest bg-emerald-500/10 px-2.5 py-1 rounded-lg border border-emerald-500/10">Resolvido</div>
                <?php endif; ?>
            </div>
        </div>
        
        <div class="flex items-center gap-2 mb-3">
            <?php 
            $catIcon = '🛠️';
            if($c['categoria'] === 'Impressora') $catIcon = '🖨️';
            elseif($c['categoria'] === 'Rede/Internet') $catIcon = '🌐';
            elseif($c['categoria'] === 'Computador/Hardware') $catIcon = '💻';
            ?>
            <span class="text-xs"><?= $catIcon ?></span>
            <span class="text-[9px] font-black text-indigo-400 uppercase tracking-[0.2em]"><?= $c['categoria'] ?></span>
            <?php if($c['equipamento_id']): ?>
                <span class="text-[8px] font-black text-slate-500 uppercase tracking-widest border-l border-white/10 pl-2">EQ-<?= $c['equipamento_id'] ?></span>
            <?php endif; ?>
        </div>

        <h5 class="text-white font-bold text-base mb-3 uppercase tracking-tight group-hover:text-indigo-400 transition-colors leading-tight html-light:text-black html-light:font-bold break-words" style="font-size:17px">#<?= $c['id'] ?> - <?= htmlspecialchars($c['titulo']) ?></h5>
        <p class="text-slate-400 text-[13px] leading-relaxed line-clamp-3 mb-4 font-medium flex-grow html-light:text-slate-600 html-light:font-medium break-words whitespace-pre-wrap overflow-hidden"><?= htmlspecialchars($c['descricao']) ?></p>
        
        <?php if($isResolvido && $c['nota_tecnica']): ?>
            <div class="mt-4 p-4 rounded-[1.5rem] bg-indigo-500/5 border border-indigo-500/10 mb-6 group-hover:bg-indigo-500/10 transition-colors html-light:bg-indigo-50 html-light:border-indigo-300">
                <div class="text-[8px] text-indigo-400 font-black uppercase tracking-widest mb-1.5 italic flex items-center gap-2 html-light:text-indigo-800">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    SOLUÇÃO FINAL:
                </div>
                <div class="text-[10px] text-slate-300 font-medium italic leading-relaxed font-sans html-light:text-slate-700 html-light:font-medium"><?= htmlspecialchars($c['nota_tecnica']) ?></div>
            </div>
        <?php endif; ?>

        <div class="flex items-center justify-between pt-5 border-t border-white/5 mt-auto html-light:border-slate-300">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-full bg-gradient-to-br from-slate-800 to-slate-900 flex items-center justify-center text-indigo-400 border border-white/5 shadow-inner text-xs font-black html-light:from-slate-200 html-light:to-slate-300 html-light:text-black html-light:border-slate-400">
                    <?= strtoupper(substr($c['usuario'], 0, 1)) ?>
                </div>
                <div class="flex flex-col">
                    <span class="text-[9px] text-slate-500 font-black uppercase tracking-widest html-light:text-slate-700">Aberto por</span>
                    <span class="text-[10px] text-white font-bold tracking-wide leading-none html-light:text-black html-light:font-black"><?= htmlspecialchars($c['usuario']) ?></span>
                </div>
            </div>
            
            <div class="flex gap-2 items-center">
                <!-- Botão Mural de Interação -->
                <button onclick="openMuralModal(<?= $c['id'] ?>, '<?= addslashes($c['titulo']) ?>', '<?= $c['usuario'] ?>', '<?= $c['anexo_url'] ?>')" class="w-9 h-9 rounded-xl bg-slate-800/40 text-slate-400 hover:bg-slate-700 hover:text-white transition-all flex items-center justify-center border border-white/5 shadow-lg group relative" title="Abrir Chat em Tempo Real">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"></path></svg>
                    <?php 
                    $unread = $isAdmin ? ($c['unread_admin'] ?? 0) : ($c['unread_user'] ?? 0);
                    if($unread > 0): 
                    ?>
                        <span class="absolute -top-2 -right-2 w-5 h-5 bg-rose-500 text-[10px] font-black text-white rounded-full flex items-center justify-center border-2 border-slate-900 animate-pulse shadow-[0_0_10px_rgba(244,63,94,0.5)] unread-badge-<?= $c['id'] ?>"><?= $unread ?></span>
                    <?php endif; ?>
                </button>

                <?php if($isAdmin): ?>
                    <?php if($c['status'] === 'Aberto'): ?>
                        <form method="POST" action="chamados.php">
                            <input type="hidden" name="action" value="atender">
                            <input type="hidden" name="csrf_token" value="<?= getCsrfToken() ?>">
                            <input type="hidden" name="chamado_id" value="<?= $c['id'] ?>">
                            <button type="submit" class="w-9 h-9 rounded-xl bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500 hover:text-white transition-all flex items-center justify-center border border-indigo-500/20 shadow-lg html-light:bg-indigo-600 html-light:text-white html-light:border-indigo-700" title="Assumir Ticket"><svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg></button>
                        </form>
                    <?php endif; ?>
                    <?php if($c['status'] !== 'Resolvido'): ?>
                        <button onclick="openSolutionModal(<?= $c['id'] ?>)" class="w-9 h-9 rounded-xl bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500 hover:text-white transition-all flex items-center justify-center border border-emerald-500/20 shadow-lg html-light:bg-emerald-600 html-light:text-white html-light:border-emerald-700" title="Finalizar e Registrar Solução"><svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg></button>
                    <?php endif; ?>
                <?php endif; ?>
            </div>
        </div>
    </div>
    <?php
    return ob_get_clean();
}
?>

<script>
    // Gráfico de Eficiência Ultra Detalhado
    document.addEventListener('DOMContentLoaded', () => {
        const isLight = document.documentElement.classList.contains('light-mode');
        const ctx = document.getElementById('supportChart').getContext('2d');
        
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Pendentes', 'Em Atendimento', 'Resolvidos'],
                datasets: [{
                    data: [<?= $stats['abertos'] ?>, <?= $stats['atendimento'] ?>, <?= $stats['resolvidos'] ?>],
                    backgroundColor: [
                        isLight ? 'rgba(59, 130, 246, 0.8)' : 'rgba(59, 130, 246, 0.6)', 
                        isLight ? 'rgba(245, 158, 11, 0.8)' : 'rgba(245, 158, 11, 0.6)', 
                        '#10b981'
                    ],
                    borderColor: isLight ? '#ffffff' : 'rgba(255,255,255,0.1)',
                    borderWidth: 2,
                    hoverOffset: 12,
                    hoverBorderWidth: 4,
                }]
            },
            options: {
                cutout: '72%',
                responsive: true,
                maintainAspectRatio: true,
                layout: { padding: 5 },
                plugins: { 
                    legend: { display: false }, 
                    tooltip: { 
                        enabled: true,
                        backgroundColor: isLight ? '#0f172a' : '#1e293b',
                        titleFont: { weight: 'bold', size: 12 },
                        bodyFont: { weight: 'bold', size: 12 },
                        padding: 12,
                        cornerRadius: 12,
                        displayColors: true
                    } 
                },
                animation: { duration: 2500, easing: 'easeOutQuart' }
            }
        });

        initMagneticEffect();
    });

    let currentFilter = 'Todos';

    function setFilter(filter) {
        currentFilter = filter;
        document.querySelectorAll('.filter-btn').forEach(btn => {
            if(btn.dataset.filter === filter) btn.classList.add('active-filter', 'bg-indigo-600', 'text-white');
            else btn.classList.remove('active-filter', 'bg-indigo-600', 'text-white');
        });
        filterTickets();
    }

    function filterTickets() {
        const query = document.getElementById('ticketSearch').value.toLowerCase();
        const cards = document.querySelectorAll('.ticket-card');
        const userItems = document.querySelectorAll('.user-ticket-item');
        
        // Filtro para Admin (Kanban)
        cards.forEach(card => {
            const title = card.dataset.title;
            const user = card.dataset.user;
            const desc = card.dataset.desc;
            const pri = card.dataset.priority;
            const cat = card.dataset.category;

            const matchesSearch = title.includes(query) || user.includes(query) || desc.includes(query);
            const matchesFilter = currentFilter === 'Todos' || pri === currentFilter || cat === currentFilter;

            if(matchesSearch && matchesFilter) {
                card.classList.remove('hidden');
                card.style.animation = 'fadeIn 0.3s ease forwards';
            } else {
                card.classList.add('hidden');
            }
        });

        // Filtro para Usuário (Lista com Abas)
        userItems.forEach(item => {
            const card = item.querySelector('.ticket-card');
            const status = item.dataset.status;
            
            const matchesSearch = card.dataset.title.includes(query) || card.dataset.desc.includes(query);
            let matchesStatus = true;
            if (currentStatusFilter === 'Ativos') matchesStatus = (status === 'Aberto' || status === 'Em Atendimento');
            else if (currentStatusFilter !== 'Todos') matchesStatus = (status === currentStatusFilter);

            if (matchesSearch && matchesStatus) {
                item.classList.remove('hidden');
            } else {
                item.classList.add('hidden');
            }
        });
    }

    let currentStatusFilter = 'Ativos';
    function setStatusFilter(status) {
        currentStatusFilter = status;
        document.querySelectorAll('.status-tab').forEach(tab => {
            if(tab.dataset.status === status) {
                tab.classList.add('active-tab', 'bg-indigo-600', 'text-white', 'shadow-lg');
                tab.classList.remove('text-slate-500');
            } else {
                tab.classList.remove('active-tab', 'bg-indigo-600', 'text-white', 'shadow-lg');
                tab.classList.add('text-slate-500');
            }
        });
        filterTickets();
    }

    // Inicializar filtro de status ao carregar
    document.addEventListener('DOMContentLoaded', () => {
        if (!is_admin_logged) setStatusFilter('Ativos');
    });

    function selectProblem(el, titulo, desc, cat, pri) {
        document.querySelectorAll('.problem-node').forEach(node => node.classList.remove('selected'));
        el.classList.add('selected');
        
        document.getElementById('input_titulo').value = titulo;
        document.getElementById('input_prioridade').value = pri;
        document.getElementById('input_categoria').value = cat;
        document.getElementById('input_descricao').value = desc;

        // Ir para o Passo 2
        nextStep();

        if(titulo === 'Outro Problema') {
            document.getElementById('field_titulo_custom').classList.remove('hidden');
            document.getElementById('titulo_custom').required = true;
            document.getElementById('input_descricao').value = '';
            document.getElementById('wizard_title').textContent = 'O que está ocorrendo?';
        } else {
            document.getElementById('field_titulo_custom').classList.add('hidden');
            document.getElementById('titulo_custom').required = false;
            document.getElementById('wizard_title').textContent = 'Quase lá...';
        }
    }

    function nextStep() {
        document.getElementById('step_1').classList.replace('step-active', 'step-inactive');
        document.getElementById('step_2').classList.replace('step-inactive', 'step-active');
        document.getElementById('wizard_progress').style.width = '100%';
        document.getElementById('wizard_step_label').textContent = 'Passo 2/2';
        document.getElementById('wizard_step_label').classList.replace('bg-indigo-500/10', 'bg-emerald-500/10');
        document.getElementById('wizard_step_label').classList.replace('text-indigo-400', 'text-emerald-400');
    }

    function prevStep() {
        document.getElementById('step_2').classList.replace('step-active', 'step-inactive');
        document.getElementById('step_1').classList.replace('step-inactive', 'step-active');
        document.getElementById('wizard_progress').style.width = '33%';
        document.getElementById('wizard_step_label').textContent = 'Passo 1/2';
        document.getElementById('wizard_step_label').classList.replace('bg-emerald-500/10', 'bg-indigo-500/10');
        document.getElementById('wizard_step_label').classList.replace('text-emerald-400', 'text-indigo-400');
        document.getElementById('wizard_title').textContent = 'O que houve?';
    }

    // Suporte a colar imagem do Clipboard (Ctrl+V)
    document.addEventListener('paste', function (e) {
        if(!document.getElementById('step_2').classList.contains('step-active')) return;
        
        const items = (e.clipboardData || e.originalEvent.clipboardData).items;
        for (let index in items) {
            const item = items[index];
            if (item.kind === 'file' && item.type.includes('image')) {
                const blob = item.getAsFile();
                const fileInput = document.getElementById('anexo_file');
                
                // Criar um DataTransfer para simular o input file
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(blob);
                fileInput.files = dataTransfer.files;

                // Preview
                const reader = new FileReader();
                reader.onload = function(event){
                    document.getElementById('img_preview').src = event.target.result;
                    document.getElementById('anexo_preview').classList.remove('hidden');
                };
                reader.readAsDataURL(blob);
            }
        }
    });

    function initMagneticEffect() {
        document.querySelectorAll('.glass-card-magnetic').forEach(card => {
            card.onmousemove = e => {
                const rect = card.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                card.style.setProperty("--mouse-x", `${x}px`);
                card.style.setProperty("--mouse-y", `${y}px`);
            };
        });
    }

    function openSolutionModal(id) {
        document.getElementById('modal_chamado_id').value = id;
        document.getElementById('solutionModal').classList.remove('hidden');
    }

    function closeSolutionModal() {
        document.getElementById('solutionModal').classList.add('hidden');
    }

    // ── Chat em Tempo Real ─────────────────────────────────────────────
    const currentUser = "<?= $currentUser ?>";
    let chatChamadoId = null;
    let chatAnexo     = null;
    let chatLastId    = 0;
    // --- Sistema de Emojis ---
    const emojis = [
        '😊','😂','😉','😍','🤔','🙄','😎','😴','😭','😱','👍','👎','👌','🤝','👏','🙌','🙏','✅','❌','⚠️','💡','🚀','💻','🖥️','🖨️','📄','🛠️','⚙️','🔌','🌐','⚡','🔥','✨','📦','📅','⏰'
    ];

    function toggleEmojiPicker() {
        const picker = document.getElementById('emoji_picker');
        if (picker.classList.contains('hidden')) {
            populateEmojis();
            picker.classList.remove('hidden');
        } else {
            picker.classList.add('hidden');
        }
    }

    function populateEmojis() {
        const grid = document.getElementById('emoji_grid');
        if (grid.children.length > 0) return; // Ja populado

        emojis.forEach(emoji => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'w-10 h-10 flex items-center justify-center text-xl hover:bg-white/10 rounded-xl transition-all active:scale-90';
            btn.textContent = emoji;
            btn.onclick = () => insertEmoji(emoji);
            grid.appendChild(btn);
        });
    }

    function insertEmoji(emoji) {
        const textarea = document.getElementById('mural_msg');
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const text = textarea.value;
        
        textarea.value = text.substring(0, start) + emoji + text.substring(end);
        
        // Reposicionar cursor
        const newPos = start + emoji.length;
        textarea.setSelectionRange(newPos, newPos);
        textarea.focus();

        // Auto-resize do textarea (chamando o evento input)
        textarea.dispatchEvent(new Event('input'));
        
        // Opcional: fechar ao clicar (vou manter aberto para multiplos emojis)
    }

    // Fechar ao clicar fora
    document.addEventListener('mousedown', (e) => {
        const picker = document.getElementById('emoji_picker');
        if (picker && !picker.contains(e.target) && !e.target.closest('button[onclick="toggleEmojiPicker()"]')) {
            picker.classList.add('hidden');
        }
    });

    let chatPollTimer = null;
    let chatTypingTimer = null;
    let isTyping = false;

    // --- Renderizar uma mensagem na timeline ---
    function renderMsg(m) {
        const timeline = document.getElementById('mural_timeline');
        const emptyNotice = timeline.querySelector('.chat-empty');
        if (emptyNotice) emptyNotice.remove();

        const isMe = m.usuario === currentUser;
        // Formatar hora corretamente
        const d = new Date(m.data_hora.replace(' ', 'T'));
        const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        const data = d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });

        const div = document.createElement('div');
        div.className = `flex flex-col ${isMe ? 'items-end' : 'items-start'}`;
        div.style.animation = 'slideIn 0.25s ease-out';
        
        // SEGURANÇA: Escapar nome de usuário e mensagem para evitar XSS
        const safeUser = m.usuario.replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const safeMsg  = m.mensagem.replace(/</g,'&lt;').replace(/>/g,'&gt;');

        div.innerHTML = `
            <div class="flex items-center gap-2 mb-1">
                <span class="text-[9px] font-black uppercase tracking-widest ${isMe ? 'text-indigo-400' : 'text-slate-400 html-light:text-slate-600'}">${safeUser}</span>
                <span class="text-[8px] text-slate-600 font-bold" title="${data}">${hora}</span>
            </div>
            <div class="max-w-[85%] px-5 py-3 rounded-2xl break-words overflow-hidden ${isMe ? 'msg-bubble-me rounded-tr-none' : 'msg-bubble-other rounded-tl-none'}">
                <p class="text-[13px] leading-relaxed font-medium whitespace-pre-wrap break-all">${safeMsg}</p>
            </div>
        `;
        timeline.appendChild(div);
        timeline.scrollTop = timeline.scrollHeight;
    }

    // --- Atualizar indicador de digitação no painel separado ---
    function updateTypingIndicator(typingUsers) {
        const bar  = document.getElementById('mural_typing_bar');
        const text = document.getElementById('mural_typing_text');
        if (!bar || !text) return;

        if (typingUsers.length > 0) {
            const names = typingUsers.join(', ');
            const label = typingUsers.length === 1 ? ' está digitando...' : ' estão digitando...';
            text.textContent = names + label;
            bar.classList.remove('hidden');
            // Rolar para baixo para mostrar o indicador
            const timeline = document.getElementById('mural_timeline');
            if (timeline) timeline.scrollTop = timeline.scrollHeight;
        } else {
            bar.classList.add('hidden');
        }
    }

    // --- Polling: buscar novas mensagens ---
    let chatIsSending = false; // Flag para evitar race condition

    async function chatPoll() {
        if (!chatChamadoId || chatIsSending) return;
        try {
            const res = await fetch(`api_chat.php?action=get_messages&chamado_id=${chatChamadoId}&since_id=${chatLastId}`);
            const data = await res.json();
            if (data.ok && data.messages.length > 0) {
                data.messages.forEach(m => {
                    if (m.id > chatLastId) {
                        chatLastId = m.id;
                        renderMsg(m);
                    }
                });
            }

            // Indicador de digitação dentro da timeline
            const resT = await fetch(`api_chat.php?action=get_typing&chamado_id=${chatChamadoId}`);
            const dataT = await resT.json();
            updateTypingIndicator(dataT.ok ? dataT.typing : []);
        } catch(e) {}
    }

    // --- Enviar mensagem (sem duplicar: apenas envia e atualiza chatLastId) ---
    async function chatSendMessage() {
        const textarea = document.getElementById('mural_msg');
        const msg = textarea.value.trim();
        if (!msg || !chatChamadoId) return;

        const btn = document.getElementById('mural_send_btn');
        btn.disabled = true;
        btn.classList.add('opacity-50');
        textarea.value = '';
        textarea.style.height = 'auto';

        // Pausar o poll para evitar duplicação
        chatIsSending = true;

        // Para o indicador de digitação
        isTyping = false;
        fetch(`api_chat.php?action=stop_typing&chamado_id=${chatChamadoId}`, { method: 'POST' });

        try {
            const form = new FormData();
            form.append('mensagem', msg);
            form.append('csrf_token', '<?= getCsrfToken() ?>');
            const res = await fetch(`api_chat.php?action=send&chamado_id=${chatChamadoId}`, { method: 'POST', body: form });
            const data = await res.json();
            if (data.ok) {
                chatLastId = Math.max(chatLastId, data.message.id);
                renderMsg(data.message);
            }
        } catch(e) {}

        // Reativar poll
        chatIsSending = false;
        btn.disabled = false;
        btn.classList.remove('opacity-50');
        textarea.focus();
    }

    // --- Abrir o modal ---
    function openMuralModal(id, titulo, autor, anexo = null) {
        chatChamadoId = id;
        chatAnexo = anexo;
        chatLastId = 0;

        // Esconder badge de não lida se houver
        const badge = document.querySelector('.unread-badge-' + id);
        if (badge) badge.remove();

        document.getElementById('mural_titulo').textContent = titulo;
        document.getElementById('mural_autor').textContent = 'Aberto por: ' + autor;
        // Esconder o painel de digitação ao abrir
        const typingBar = document.getElementById('mural_typing_bar');
        if (typingBar) typingBar.classList.add('hidden');

        const timeline = document.getElementById('mural_timeline');
        timeline.innerHTML = '';

        // Exibir anexo se existir
        if (anexo) {
            const anexoDiv = document.createElement('div');
            anexoDiv.className = 'mb-6 p-4 rounded-2xl bg-indigo-500/10 border border-indigo-500/20';
            anexoDiv.innerHTML = `
                <div class="text-[9px] text-indigo-400 font-black uppercase tracking-widest mb-2 flex items-center gap-1.5">
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.414a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                    Anexo do Chamado
                </div>
                <a href="${anexo}" target="_blank" class="block overflow-hidden rounded-xl border border-white/10 hover:border-indigo-400 transition-all">
                    <img src="${anexo}" class="w-full h-auto max-h-52 object-cover hover:scale-105 transition-transform duration-700">
                </a>`;
            timeline.appendChild(anexoDiv);
        }

        // Estado vazio inicial
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'chat-empty py-10 text-center';
        emptyDiv.innerHTML = `
            <div class="w-14 h-14 bg-slate-800/20 rounded-full flex items-center justify-center mx-auto mb-3 border border-white/5">
                <svg class="w-7 h-7 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
            </div>
            <p class="text-slate-500 font-black uppercase tracking-[0.2em] text-[9px] italic">Nenhuma mensagem ainda. Comece a conversa!</p>
        `;
        timeline.appendChild(emptyDiv);

        document.getElementById('muralModal').classList.add('open');
        document.getElementById('muralOverlay').classList.add('open');
        document.body.classList.add('chat-sidebar-open');
        
        // Rolar para o fim após a animação de abertura
        setTimeout(() => {
            const timeline = document.getElementById('mural_timeline');
            if (timeline) timeline.scrollTop = timeline.scrollHeight;
            const input = document.getElementById('mural_msg');
            if (input) input.focus();
        }, 150);

        // Carregar mensagens já existentes e iniciar polling
        chatPoll();
        chatPollTimer = setInterval(chatPoll, 2000);
    }

    let lastMessageChamadoId = null;
    let unreadCount = 0;

    function resetUnread() {
        unreadCount = 0;
        document.getElementById('msg-fab').classList.remove('has-new');
        document.getElementById('msg-badge').textContent = '0';
    }

    function openGlobalChat() {
        // Se temos um ID de chamado que acabou de receber msg, priorizamos ele
        let targetId = lastMessageChamadoId;
        
        // Fallback: se não temos um ID recente, pegamos o primeiro card visível (o mais recente da lista)
        if (!targetId) {
            const firstCard = document.querySelector('.ticket-card');
            if (firstCard) {
                // Tenta extrair o ID do onclick do botão de chat dentro desse card
                const btn = firstCard.querySelector('button[onclick*="openMuralModal"]');
                if (btn) btn.click();
                return;
            }
        }

        if (targetId) {
            const selector = `button[onclick*="openMuralModal(${targetId}"]`;
            const openBtn = document.querySelector(selector);
            
            if (openBtn) {
                openBtn.click();
            } else {
                // Tenta forçar a aba 'Todos' caso o chamado esteja oculto
                const tabAll = document.querySelector('[onclick*="filterStatus(\'all\'"]');
                if (tabAll) {
                    tabAll.click();
                    setTimeout(() => {
                        const retryBtn = document.querySelector(selector);
                        if (retryBtn) retryBtn.click();
                    }, 200);
                } else {
                    showToast('Chat', 'Localizando chamado...', 'info');
                }
            }
        } else {
            showToast('Suporte', 'Nenhuma conversa ativa encontrada.', 'info');
        }
    }

    // --- Fechar o modal ---
    function closeMuralModal() {
        document.getElementById('muralModal').classList.remove('open');
        document.getElementById('muralOverlay').classList.remove('open');
        document.body.classList.remove('chat-sidebar-open');
        chatChamadoId = null;
        if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
        if (chatTypingTimer) { clearTimeout(chatTypingTimer); chatTypingTimer = null; }
        isTyping = false;
    }

    // --- Admin Atalhos ---
    function openAdminAtalhos() { document.getElementById('adminAtalhosModal').classList.remove('hidden'); }
    function closeAdminAtalhos() { document.getElementById('adminAtalhosModal').classList.add('hidden'); }

    function setPickerIcon(emoji) {
        document.getElementById('input_picker_icon').value = emoji;
        updatePreview();
    }

    function editAtalho(data) {
        document.getElementById('atalho_form_title').textContent = 'Editar Atalho';
        document.getElementById('atalho_action').value = 'edit_atalho';
        document.getElementById('atalho_edit_id').value = data.id;
        document.getElementById('input_picker_icon').value = data.icone;
        document.getElementById('input_picker_label').value = data.label;
        document.getElementById('input_picker_titulo').value = data.titulo_padrao;
        document.getElementById('input_picker_cat').value = data.categoria;
        document.getElementById('input_picker_pri').value = data.prioridade_padrao;
        document.getElementById('atalho_submit_btn').textContent = 'Atualizar Atalho';
        document.getElementById('cancel_edit_btn').classList.remove('hidden');
        updatePreview();
    }

    function cancelEditAtalho() {
        document.getElementById('atalho_form_title').textContent = 'Criar Novo Atalho';
        document.getElementById('atalho_action').value = 'add_atalho';
        document.getElementById('atalho_edit_id').value = '';
        document.getElementById('form_gerenciar_atalho').reset();
        document.getElementById('atalho_submit_btn').textContent = 'Salvar Atalho';
        document.getElementById('cancel_edit_btn').classList.add('hidden');
        setPickerIcon('🛠️');
    }

    function updatePreview() {
        const emoji = document.getElementById('input_picker_icon').value || '🛠️';
        const label = document.getElementById('input_picker_label').value || 'Novo Botão';
        
        document.getElementById('preview_icon').textContent = emoji;
        document.getElementById('preview_label').textContent = label;
    }

    // --- Eventos do textarea ---
    document.addEventListener('DOMContentLoaded', () => {
        // Manter modal de atalhos aberto se veio de uma ação de gerenciar
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('manage_atalhos') === '1') {
            openAdminAtalhos();
            // Limpa a URL para não reabrir no refresh manual
            window.history.replaceState({}, document.title, window.location.pathname);
        }

        // --- Eventos do Chat (Mural) ---
        const textarea = document.getElementById('mural_msg');
        if(textarea) {
            // Unificado: Auto-resize, Digitação e Envio
            textarea.addEventListener('input', function() {
                // 1. Auto-resize (Com ajuste fino para nao cortar)
                this.style.height = 'auto';
                const newHeight = Math.min(this.scrollHeight, 150);
                this.style.height = newHeight + 'px';
                
                // Forçar scroll para o final se exceder o limite
                if (this.scrollHeight > 150) this.style.overflowY = 'auto';
                else this.style.overflowY = 'hidden';

                // 2. Notificar Digitação (Tempo Real) - Com Throttle (Evita sobrecarga)
                const now = Date.now();
                if (chatChamadoId && (!window.lastTypingTime || now - window.lastTypingTime > 2000)) {
                    window.lastTypingTime = now;
                    fetch(`api_chat.php?action=typing&chamado_id=${chatChamadoId}`, { method: 'POST' });
                }

                // 3. Parar status após 4 segundos sem digitar
                clearTimeout(chatTypingTimer);
                chatTypingTimer = setTimeout(() => {
                    isTyping = false;
                    window.lastTypingTime = 0;
                    if (chatChamadoId) fetch(`api_chat.php?action=stop_typing&chamado_id=${chatChamadoId}`, { method: 'POST' });
                }, 4000);
            });

            // Enter para enviar, Shift+Enter para nova linha
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    chatSendMessage();
                }
            });
        }
    });

    // --- Sistema de Notificações em Tempo Real ---
    let lastTicketCount = <?= $stats['abertos'] ?>;
    let myLastResolvedCount = <?= $stats['resolvidos'] ?>;
    let lastKnownMsgId = 0; // Será inicializado no primeiro poll
    const is_admin_logged = <?= $isAdmin ? 'true' : 'false' ?>;

    function showToast(title, msg, type = 'info') {
        const container = document.getElementById('live-toast-container');
        if(!container) return;
        const toast = document.createElement('div');
        toast.className = `live-toast border-l-4 ${type === 'success' ? 'border-emerald-500' : (type === 'error' ? 'border-rose-500' : 'border-indigo-500')}`;
        const icon = type === 'success' ? '✅' : (type === 'error' ? '🚨' : '💬');
        
        toast.innerHTML = `
            <div class="text-2xl">${icon}</div>
            <div class="flex-grow">
                <div class="text-[10px] font-black text-slate-500 uppercase tracking-widest">${title}</div>
                <div class="text-xs font-bold text-white">${msg}</div>
            </div>
            <button onclick="this.parentElement.remove()" class="text-slate-500 hover:text-white">✕</button>
        `;
        container.appendChild(toast);
        document.getElementById('notif-sound').play().catch(() => {});
        setTimeout(() => {
            toast.classList.add('toast-exit');
            setTimeout(() => toast.remove(), 400);
        }, 6000);
    }

    async function checkNotifications() {
        try {
            const response = await fetch('api_chamados_status.php');
            const data = await response.json();
            
            // 1. Notificações de Novos Chamados (Admin)
            if (is_admin_logged) {
                if (data.abertos > lastTicketCount) {
                    showToast('Novo Chamado', 'Uma nova solicitação foi aberta agora.', 'info');
                }
                lastTicketCount = data.abertos;
            } else {
                // 2. Notificações de Finalização (Usuário)
                if (data.meus_resolvidos > myLastResolvedCount) {
                    showToast('Chamado Finalizado', 'Seu chamado foi concluído pela equipe técnica!', 'success');
                }
                myLastResolvedCount = data.meus_resolvidos;
            }

            // 3. Notificações de Novas Mensagens no Chat (Geral)
            if (lastKnownMsgId > 0 && data.latest_msg_id > lastKnownMsgId) {
                if (!chatChamadoId) {
                    showToast('Nova Resposta', 'Há uma nova mensagem no Mural de um chamado.', 'indigo');
                    document.getElementById('msg-fab').classList.add('has-new');
                    
                    // Rastrear qual chamado recebeu a msg
                    lastMessageChamadoId = data.latest_chamado_id;

                    // Incrementar o contador de mensagens não lidas
                    unreadCount++;
                    const badge = document.getElementById('msg-badge');
                    badge.textContent = unreadCount;
                }
            }
            lastKnownMsgId = data.latest_msg_id;

            // 4. Atualizar Badges de Não Lidas nos Cards de forma dinâmica
            if (data.unread_list) {
                // Remover badges de chamados que foram lidos ou não têm mais msgs novas
                document.querySelectorAll('[class*="unread-badge-"]').forEach(b => {
                    const match = b.className.match(/unread-badge-(\d+)/);
                    if (match && !data.unread_list[match[1]]) b.remove();
                });

                // Adicionar ou atualizar as badges
                for (const id in data.unread_list) {
                    const count = data.unread_list[id];
                    let badge = document.querySelector('.unread-badge-' + id);
                    
                    if (!badge) {
                        const btn = document.querySelector(`button[onclick*="openMuralModal(${id},"]`);
                        if (btn) {
                            badge = document.createElement('span');
                            badge.className = `absolute -top-2 -right-2 w-5 h-5 bg-rose-500 text-[10px] font-black text-white rounded-full flex items-center justify-center border-2 border-slate-900 animate-pulse shadow-[0_0_10px_rgba(244,63,94,0.5)] unread-badge-${id}`;
                            btn.appendChild(badge);
                        }
                    }
                    if (badge) badge.textContent = count;
                }
            }

        } catch (e) {}
    }
    setInterval(checkNotifications, 10000);

    // --- Prevenir Duplo Clique no Envio ---
    function handleDoubleSubmit(form) {
        const btn = form.querySelector('button[type="submit"]');
        if(btn) {
            btn.disabled = true;
            btn.innerHTML = '<div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div> Enviando...';
            btn.classList.add('opacity-70', 'cursor-not-allowed');
        }
        return true;
    }
</script>

<?php require_once 'includes/footer.php'; ?>
