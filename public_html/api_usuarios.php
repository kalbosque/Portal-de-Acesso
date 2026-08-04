<?php
require_once 'db.php';

header('Content-Type: application/json');

$action = $_GET['action'] ?? '';

if ($action === 'list') {
    try {
        $stmt = $pdo->query("SELECT id, nome, username, email FROM usuarios ORDER BY nome");
        $usuarios = $stmt->fetchAll(PDO::FETCH_ASSOC);
        echo json_encode(['success' => true, 'usuarios' => $usuarios]);
    } catch (Exception $e) {
        echo json_encode(['success' => false, 'error' => $e->getMessage()]);
    }
    exit;
}

echo json_encode(['success' => false, 'error' => 'Ação inválida']);