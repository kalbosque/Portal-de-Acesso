<?php
require_once 'auth.php';
require_once 'db.php';

header('Content-Type: application/json');

if (!isset($_SESSION['user_id'])) {
    echo json_encode(['error' => 'Não autenticado']);
    exit;
}

$currentUser = $_SESSION['user_name'];

// Contagem global de abertos (para admins)
$abertos = $pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Aberto'")->fetchColumn();

// Contagem de resolvidos do usuário logado (para usuários comuns)
$stmt = $pdo->prepare("SELECT COUNT(*) FROM chamados WHERE usuario = ? AND status = 'Resolvido'");
$stmt->execute([$currentUser]);
$meus_resolvidos = $stmt->fetchColumn();

// Buscar o ID da última mensagem e o ID do chamado correspondente
if ($isAdmin) {
    $row = $pdo->query("SELECT id, chamado_id FROM chamados_interacoes ORDER BY id DESC LIMIT 1")->fetch(PDO::FETCH_ASSOC);
    // Para o admin, buscar todos os chamados que tenham mensagens não lidas para o admin
    $unread_list = $pdo->query("SELECT id, unread_admin FROM chamados WHERE unread_admin > 0")->fetchAll(PDO::FETCH_KEY_PAIR);
} else {
    $stmt = $pdo->prepare("SELECT i.id, i.chamado_id FROM chamados_interacoes i JOIN chamados c ON i.chamado_id = c.id WHERE c.usuario = ? ORDER BY i.id DESC LIMIT 1");
    $stmt->execute([$currentUser]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    // Para o usuário, buscar seus chamados que tenham mensagens não lidas para o usuário
    $stmtU = $pdo->prepare("SELECT id, unread_user FROM chamados WHERE usuario = ? AND unread_user > 0");
    $stmtU->execute([$currentUser]);
    $unread_list = $stmtU->fetchAll(PDO::FETCH_KEY_PAIR);
}

$latest_msg_id = $row['id'] ?? 0;
$latest_chamado_id = $row['chamado_id'] ?? 0;

echo json_encode([
    'abertos' => (int)$abertos,
    'meus_resolvidos' => (int)$meus_resolvidos,
    'latest_msg_id' => (int)$latest_msg_id,
    'latest_chamado_id' => (int)$latest_chamado_id,
    'unread_list' => $unread_list // Ex: [15 => 2, 18 => 1]
]);
