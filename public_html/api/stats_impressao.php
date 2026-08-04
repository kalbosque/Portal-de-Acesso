<?php
date_default_timezone_set('America/Porto_Velho');
header('Content-Type: application/json');
require_once '../includes/config.php';
require_once '../db.php';

try {
    // 1. Estatísticas por Impressora (Top 5) - Corrigido com JOIN
    $stmt1 = $pdo->query("
        SELECT COALESCE(imp.nome, 'Impressora Local') as nome, SUM(i.paginas) as total 
        FROM impressoes i 
        LEFT JOIN impressoras imp ON i.impressora_id = imp.id 
        GROUP BY imp.nome, i.impressora_id 
        ORDER BY total DESC 
        LIMIT 5
    ");
    $porImpressora = $stmt1->fetchAll(PDO::FETCH_ASSOC);

    // 2. Estatísticas por Usuário (Top 5)
    $stmt2 = $pdo->query("
        SELECT usuario as nome, SUM(paginas) as total 
        FROM impressoes 
        GROUP BY usuario 
        ORDER BY total DESC 
        LIMIT 5
    ");
    $porUsuario = $stmt2->fetchAll(PDO::FETCH_ASSOC);

    echo json_encode([
        'success' => true,
        'stats' => [
            'impressoras' => $porImpressora,
            'usuarios' => $porUsuario
        ]
    ]);

} catch (PDOException $e) {
    echo json_encode(['success' => false, 'error' => $e->getMessage()]);
}
