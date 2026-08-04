<?php
require_once '../auth.php';
require_once '../db.php';

header('Content-Type: application/json');

if (!isset($_SESSION['user_id'])) {
    http_response_code(403);
    echo json_encode(['error' => 'Não autorizado']);
    exit;
}

try {
    // Totais Gerais
    $stmt = $pdo->query("SELECT SUM(paginas) as total_paginas, SUM(valor_total) as receita_total FROM impressoes");
    $totais = $stmt->fetch();
    
    // Status Impressoras
    $stmt = $pdo->query("SELECT COUNT(*) as total, SUM(CASE WHEN status='Online' THEN 1 ELSE 0 END) as online FROM impressoras");
    $status_imp = $stmt->fetch();

    // Chamados Abertos
    $stmt = $pdo->query("SELECT COUNT(*) FROM chamados WHERE status = 'Aberto'");
    $chamados_abertos = $stmt->fetchColumn();

    echo json_encode([
        'total_paginas' => number_format($totais['total_paginas'] ?? 0, 0, ',', '.'),
        'receita_total' => 'R$ ' . number_format($totais['receita_total'] ?? 0, 2, ',', '.'),
        'impressoras_online' => ($status_imp['online'] ?? 0),
        'impressoras_total' => ($status_imp['total'] ?? 0),
        'chamados_abertos' => (int)$chamados_abertos
    ]);

} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => $e->getMessage()]);
}
