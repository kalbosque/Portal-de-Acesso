<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT impressora_id, COUNT(*) as total FROM impressoes GROUP BY impressora_id");
while($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
    echo "ID: " . $row['impressora_id'] . " | Total: " . $row['total'] . "\n";
}
