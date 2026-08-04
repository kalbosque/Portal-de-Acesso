<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT id, nome, ip FROM impressoras");
while($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
    echo $row['id'] . ' | ' . $row['nome'] . ' | ' . $row['ip'] . "\n";
}
