<?php
require_once '../auth.php';
require_once '../db.php';

// Apenas administradores podem fazer backup total
if (!isAdmin()) {
    http_response_code(403);
    die("Acesso Negado");
}

header('Content-Type: application/sql');
header('Content-Disposition: attachment; filename="backup_printdash_'.date('Y-m-d_H-i').'.sql"');

$dbHost = getenv('DB_HOST') ?: 'db';
$dbName = getenv('DB_NAME') ?: 'sistema_impressao';
$dbUser = getenv('DB_USER') ?: 'root';
$dbPass = getenv('DB_PASS') ?: 'root';

putenv("PGPASSWORD=" . $dbPass);
$command = sprintf(
    'pg_dump -h %s -U %s %s',
    escapeshellarg($dbHost),
    escapeshellarg($dbUser),
    escapeshellarg($dbName)
);

passthru($command);
exit;
