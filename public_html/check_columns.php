<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'impressoes'");
$results = $stmt->fetchAll(PDO::FETCH_ASSOC);
echo json_encode($results, JSON_PRETTY_PRINT);
