<?php
date_default_timezone_set('America/Porto_Velho');
require_once '../db.php';

try {
    $stmt = $pdo->query("
        SELECT 
            i.*,
            imp.nome as nome_impressora
        FROM impressoes i 
        LEFT JOIN impressoras imp ON i.impressora_id = imp.id 
        ORDER BY i.data_hora DESC 
        LIMIT 8
    ");
    $atividades = $stmt->fetchAll(PDO::FETCH_ASSOC);

    // Já está no fuso correto pelo banco (db.php)
    foreach ($atividades as &$row) {
        $dt = new DateTime($row['data_hora']);
        $row['data_formatada'] = $dt->format('d/m');
        $row['hora_formatada'] = $dt->format('H:i:s');
    }
    unset($row);

    echo json_encode([
        'success' => true,
        'atividades' => $atividades
    ]);
} catch (PDOException $e) {
    echo json_encode(['success' => false, 'error' => $e->getMessage()]);
}
