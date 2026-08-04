<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT * FROM impressoes WHERE impressora_id IS NULL LIMIT 5");
while($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
    echo "ID: " . $row['id'] . " | Printer Name: " . $row['impressora'] . " | Maquina: " . $row['maquina'] . "\n";
}
