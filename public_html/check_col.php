<?php
require 'db.php';
$stmt = $pdo->query("SELECT column_name FROM information_schema.columns WHERE table_name = 'impressoes' AND column_name = 'ip_maquina'");
$exists = $stmt->fetch();
if ($exists) {
    echo "COLUNA_EXISTE\n";
} else {
    echo "COLUNA_NAO_EXISTE\n";
}
