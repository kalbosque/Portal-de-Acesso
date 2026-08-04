<?php
require_once 'db.php';
$stmt = $pdo->query("SELECT * FROM impressoes LIMIT 1");
$row = $stmt->fetch(PDO::FETCH_ASSOC);
print_r(array_keys($row));
