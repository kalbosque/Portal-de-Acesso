<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT * FROM impressoes ORDER BY data_hora DESC LIMIT 5");
$results = $stmt->fetchAll(PDO::FETCH_ASSOC);
echo json_encode($results, JSON_PRETTY_PRINT);
