<?php
require_once '../auth.php';
require_once '../db.php';

header('Content-Type: application/json');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    exit;
}

$data = json_decode(file_get_contents('php://input'), true);
$current_pass = $data['current_password'] ?? '';
$new_pass = $data['new_password'] ?? '';
$user_id = $_SESSION['user_id'];

if (!$current_pass || !$new_pass) {
    echo json_encode(['success' => false, 'error' => 'Preencha todos os campos.']);
    exit;
}

try {
    $stmt = $pdo->prepare("SELECT password_hash FROM usuarios WHERE id = ?");
    $stmt->execute([$user_id]);
    $user = $stmt->fetch();

    if ($user && password_verify($current_pass, $user['password_hash'])) {
        $new_hash = password_hash($new_pass, PASSWORD_DEFAULT);
        $stmt = $pdo->prepare("UPDATE usuarios SET password_hash = ? WHERE id = ?");
        $stmt->execute([$new_hash, $user_id]);
        echo json_encode(['success' => true]);
    } else {
        echo json_encode(['success' => false, 'error' => 'Senha atual incorreta.']);
    }
} catch (Exception $e) {
    echo json_encode(['success' => false, 'error' => 'Erro no servidor: ' . $e->getMessage()]);
}
