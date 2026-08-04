<?php
require_once 'db.php';

try {
    $pdo->beginTransaction();

    // 1. Mover histórico da impressora 8 para a 1
    $stmt = $pdo->prepare("UPDATE impressoes SET impressora_id = 1 WHERE impressora_id = 8");
    $stmt->execute();
    $moved = $stmt->rowCount();

    // 2. Deletar a impressora duplicada (8)
    $pdo->exec("DELETE FROM impressoras WHERE id = 8");

    // 3. Renomear a impressora principal (1) para o nome que o agente usa, 
    // garantindo que o IP fique o correto (.170)
    $stmt = $pdo->prepare("UPDATE impressoras SET nome = 'Brother MFC-8480DN Printer', ip = '192.168.1.170' WHERE id = 1");
    $stmt->execute();

    $pdo->commit();
    echo "Sucesso! $moved registros movidos. Impressoras unificadas.\n";
} catch (Exception $e) {
    $pdo->rollBack();
    echo "Erro: " . $e->getMessage() . "\n";
}
