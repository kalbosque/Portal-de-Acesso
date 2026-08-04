<?php
require_once 'auth.php';
require_once 'db.php';

header('Content-Type: application/json');

$currentUser = $_SESSION['user_name'] ?? null;
$isAdmin     = isAdmin();

if (!$currentUser) {
    echo json_encode(['ok' => false, 'error' => 'Não autenticado']);
    exit;
}

$action     = $_GET['action'] ?? $_POST['action'] ?? '';
$chamado_id = (int)($_GET['chamado_id'] ?? $_POST['chamado_id'] ?? 0);

// SEGURANÇA: Validar Token CSRF apenas em ações de modificação (POST)
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !in_array($action, ['typing', 'stop_typing'])) {
    if (!validateCsrfToken($_POST['csrf_token'] ?? '')) {
        echo json_encode(['ok' => false, 'error' => 'Token CSRF invalido']);
        exit;
    }
}

// ── Verificar se o usuário tem acesso ao chamado ─────────────────
function verificarAcesso($pdo, $chamado_id, $currentUser, $isAdmin): bool {
    if ($isAdmin) return true;
    $stmt = $pdo->prepare("SELECT usuario FROM chamados WHERE id = ?");
    $stmt->execute([$chamado_id]);
    $owner = $stmt->fetchColumn();
    return $owner === $currentUser;
}

switch ($action) {

    // ── Enviar mensagem ──────────────────────────────────────────────
    case 'send':
        if (!$chamado_id) { echo json_encode(['ok' => false, 'error' => 'ID inválido']); exit; }
        if (!verificarAcesso($pdo, $chamado_id, $currentUser, $isAdmin)) {
            echo json_encode(['ok' => false, 'error' => 'Sem permissão']); exit;
        }
        $msg = trim($_POST['mensagem'] ?? '');
        if (!$msg) { echo json_encode(['ok' => false, 'error' => 'Mensagem vazia']); exit; }

        $stmt = $pdo->prepare("INSERT INTO chamados_interacoes (chamado_id, usuario, mensagem) VALUES (?, ?, ?)");
        $stmt->execute([$chamado_id, $currentUser, $msg]);
        $newId = $pdo->lastInsertId();

        // Incrementar o contador de mensagens não lidas
        if ($isAdmin) {
            $pdo->prepare("UPDATE chamados SET unread_user = unread_user + 1 WHERE id = ?")->execute([$chamado_id]);
        } else {
            $pdo->prepare("UPDATE chamados SET unread_admin = unread_admin + 1 WHERE id = ?")->execute([$chamado_id]);
        }

        // Remover status de digitação ao enviar
        $pdo->prepare("DELETE FROM chat_typing WHERE chamado_id = ? AND usuario = ?")->execute([$chamado_id, $currentUser]);

        // Retornar a mensagem recém criada
        $stmt2 = $pdo->prepare("SELECT * FROM chamados_interacoes WHERE id = ?");
        $stmt2->execute([$newId]);
        $row = $stmt2->fetch();

        echo json_encode(['ok' => true, 'message' => $row]);
        break;

    // ── Buscar mensagens (polling) ───────────────────────────────────
    case 'get_messages':
        if (!$chamado_id) { echo json_encode(['ok' => false, 'error' => 'ID inválido']); exit; }
        if (!verificarAcesso($pdo, $chamado_id, $currentUser, $isAdmin)) {
            echo json_encode(['ok' => false, 'error' => 'Sem permissão']); exit;
        }
        $since_id = (int)($_GET['since_id'] ?? 0);

        $stmt = $pdo->prepare("SELECT * FROM chamados_interacoes WHERE chamado_id = ? AND id > ? ORDER BY data_hora ASC");
        $stmt->execute([$chamado_id, $since_id]);
        $messages = $stmt->fetchAll();

        // Zerar o contador de mensagens não lidas ao abrir/sincronizar o chat
        if ($isAdmin) {
            $pdo->prepare("UPDATE chamados SET unread_admin = 0 WHERE id = ?")->execute([$chamado_id]);
        } else {
            $pdo->prepare("UPDATE chamados SET unread_user = 0 WHERE id = ?")->execute([$chamado_id]);
        }

        echo json_encode(['ok' => true, 'messages' => $messages]);
        break;

    // ── Atualizar status de digitação ────────────────────────────────
    case 'typing':
        if (!$chamado_id) { echo json_encode(['ok' => false]); exit; }
        $pdo->prepare("INSERT INTO chat_typing (chamado_id, usuario, ultima_atividade) VALUES (?, ?, NOW())
                       ON CONFLICT (chamado_id, usuario) DO UPDATE SET ultima_atividade = NOW()")
            ->execute([$chamado_id, $currentUser]);
        echo json_encode(['ok' => true]);
        break;

    // ── Parar de digitar ─────────────────────────────────────────────
    case 'stop_typing':
        if (!$chamado_id) { echo json_encode(['ok' => false]); exit; }
        $pdo->prepare("DELETE FROM chat_typing WHERE chamado_id = ? AND usuario = ?")
            ->execute([$chamado_id, $currentUser]);
        echo json_encode(['ok' => true]);
        break;

    // ── Buscar quem está digitando ───────────────────────────────────
    case 'get_typing':
        if (!$chamado_id) { echo json_encode(['ok' => false, 'typing' => []]); exit; }
        // Retorna apenas quem digitou nos últimos 5 segundos (exceto eu mesmo)
        $stmt = $pdo->prepare("SELECT usuario FROM chat_typing WHERE chamado_id = ? AND usuario != ? AND ultima_atividade >= NOW() - INTERVAL '5 seconds'");
        $stmt->execute([$chamado_id, $currentUser]);
        $typing = $stmt->fetchAll(PDO::FETCH_COLUMN);
        echo json_encode(['ok' => true, 'typing' => $typing]);
        break;

    default:
        echo json_encode(['ok' => false, 'error' => 'Ação desconhecida']);
}
?>
