<?php
require_once 'db.php';
header('Content-Type: application/json');

$stmt = $pdo->query('SELECT id, nome, ip, status, ultima_verificacao FROM impressoras');
$rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
echo json_encode(['printers' => $rows, 'count' => count($rows)], JSON_PRETTY_PRINT);
