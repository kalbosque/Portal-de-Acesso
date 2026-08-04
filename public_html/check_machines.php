<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT maquina, ip_maquina, ultima_acao, versao FROM maquinas ORDER BY ultima_acao DESC LIMIT 10");
while($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
    echo $row['maquina'] . " | " . $row['ip_maquina'] . " | " . $row['ultima_acao'] . " | " . $row['versao'] . "\n";
}
