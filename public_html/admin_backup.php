<?php
ob_start(); 
require_once 'auth.php';
require_once 'db.php';
require_once 'includes/config.php';

if (!isAdmin()) {
    ob_end_clean();
    header('Content-Type: application/json');
    echo json_encode(['success' => false, 'message' => 'Acesso negado.']);
    exit;
}

set_time_limit(1200); // 20 minutos para sistemas grandes
ini_set('memory_limit', '1024M'); // 1GB de RAM para o ZIP

$action = $_GET['action'] ?? '';

if ($action === 'generate') {
    try {
        $backupDir = __DIR__ . '/backups/';
        if (!is_dir($backupDir)) mkdir($backupDir, 0755, true);
        
        $date = date('Y-m-d_H-i-s');
        $sqlFile = "db_backup_$date.sql";
        $zipFile = "FULL_BACKUP_$date.zip";
        
        // 1. Gerar SQL
        $sqlContent = "-- Backup Total com Sequências - $date\n\n";
        
        // Exportar Sequências (Importante para IDs no PostgreSQL)
        $sequences = $pdo->query("SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public'")->fetchAll(PDO::FETCH_COLUMN);
        foreach ($sequences as $seq) {
            $sqlContent .= "DROP SEQUENCE IF EXISTS \"$seq\" CASCADE;\n";
            $sqlContent .= "CREATE SEQUENCE \"$seq\";\n";
        }
        $sqlContent .= "\n";

        $tables = $pdo->query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")->fetchAll(PDO::FETCH_COLUMN);
        foreach ($tables as $table) {
            $stmt = $pdo->query("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = '$table' ORDER BY ordinal_position");
            $columns = $stmt->fetchAll(PDO::FETCH_ASSOC);
            $sqlContent .= "DROP TABLE IF EXISTS \"$table\" CASCADE;\nCREATE TABLE \"$table\" (\n";
            $colDefs = [];
            foreach ($columns as $col) {
                $def = "\"" . $col['column_name'] . "\" " . $col['data_type'];
                if ($col['is_nullable'] === 'NO') $def .= " NOT NULL";
                if ($col['column_default']) $def .= " DEFAULT " . $col['column_default'];
                $colDefs[] = "  $def";
            }
            $sqlContent .= implode(",\n", $colDefs) . "\n);\n";
            $data = $pdo->query("SELECT * FROM \"$table\"")->fetchAll(PDO::FETCH_ASSOC);
            foreach ($data as $row) {
                $keys = array_keys($row);
                $vals = array_map(function($v) use ($pdo) { return ($v === null) ? 'NULL' : $pdo->quote($v); }, array_values($row));
                $sqlContent .= "INSERT INTO \"$table\" (\"" . implode('", "', $keys) . "\") VALUES (" . implode(", ", $vals) . ");\n";
            }
            
            // Sincronizar Sequência apenas se a coluna 'id' existir na tabela
            $hasId = false;
            foreach ($columns as $col) { if ($col['column_name'] === 'id') { $hasId = true; break; } }
            
            if ($hasId) {
                $sqlContent .= "SELECT setval(pg_get_serial_sequence('\"$table\"', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM \"$table\";\n\n";
            }
        }
        file_put_contents($backupDir . $sqlFile, $sqlContent);

        // 2. Tentar ZIP
        if (class_exists('ZipArchive')) {
            $zip = new ZipArchive();
            if ($zip->open($backupDir . $zipFile, ZipArchive::CREATE) === TRUE) {
                $zip->addFile($backupDir . $sqlFile, $sqlFile);
                
                $rootPath = realpath(__DIR__);
                $files = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($rootPath), RecursiveIteratorIterator::LEAVES_ONLY);

                foreach ($files as $name => $file) {
                    if (!$file->isDir()) {
                        $filePath = $file->getRealPath();
                        $relativePath = substr($filePath, strlen($rootPath) + 1);
                        
                        // IGNORAR pasta de backups e arquivos temporários
                        if (strpos($relativePath, 'backups') === 0 || $relativePath === $sqlFile || strpos($relativePath, '.git') === 0) {
                            continue;
                        }

                        // Tentar adicionar, se falhar (arquivo em uso), apenas pula
                        @$zip->addFile($filePath, $relativePath);
                    }
                }
                $zip->close();
                @unlink($backupDir . $sqlFile);
                ob_end_clean();
                echo json_encode(['success' => true, 'file' => $zipFile]);
                exit;
            }
        }

        // Se chegar aqui, ou não tem ZipArchive ou falhou o ZIP, retornamos o SQL
        ob_end_clean();
        echo json_encode(['success' => true, 'message' => 'Apenas SQL gerado (ZIP falhou)', 'file' => $sqlFile]);

    } catch (Exception $e) {
        ob_end_clean();
        echo json_encode(['success' => false, 'message' => $e->getMessage()]);
    }
    exit;
}

// ... (resto do arquivo: list, delete, restore continuam iguais)
if ($action === 'list') {
    header('Content-Type: application/json');
    $backupDir = __DIR__ . '/backups/';
    $files = array_merge(glob($backupDir . "*.zip") ?: [], glob($backupDir . "*.sql") ?: []);
    $list = [];
    foreach ($files as $file) {
        if (!file_exists($file)) continue;
        $list[] = ['name' => basename($file), 'size' => round(filesize($file) / 1024 / 1024, 2) . ' MB', 'date' => date('d/m/Y H:i', filemtime($file)), 'type' => strtoupper(pathinfo($file, PATHINFO_EXTENSION))];
    }
    usort($list, function($a, $b) use ($backupDir) { return filemtime($backupDir . $b['name']) - filemtime($backupDir . $a['name']); });
    ob_end_clean();
    echo json_encode($list);
    exit;
}

if ($action === 'upload') {
    if (!isset($_FILES['backup_file'])) { ob_end_clean(); echo json_encode(['success' => false, 'message' => 'Nenhum arquivo enviado.']); exit; }
    $file = $_FILES['backup_file'];
    $ext = pathinfo($file['name'], PATHINFO_EXTENSION);
    $newName = 'UPLOAD_'.date('Ymd_His').'.'.$ext;
    if (move_uploaded_file($file['tmp_name'], __DIR__ . '/backups/' . $newName)) {
        $_GET['file'] = $newName;
        $action = 'restore';
    } else { ob_end_clean(); echo json_encode(['success' => false, 'message' => 'Falha no upload.']); exit; }
}

if ($action === 'restore') {
    $file = $_GET['file'] ?? '';
    try {
        $backupDir = __DIR__ . '/backups/';
        $sqlContent = '';
        if (preg_match('/\.zip$/', $file)) {
            $zip = new ZipArchive();
            if ($zip->open($backupDir . $file) === TRUE) {
                for ($i = 0; $i < $zip->numFiles; $i++) { if (preg_match('/\.sql$/', $zip->getNameIndex($i))) { $sqlContent = $zip->getFromName($zip->getNameIndex($i)); break; } }
                $zip->close();
            }
        } else { $sqlContent = file_get_contents($backupDir . $file); }
        if (!$sqlContent) throw new Exception("Conteúdo inválido.");
        $pdo->beginTransaction();
        $pdo->exec($sqlContent);
        $pdo->commit();
        ob_end_clean();
        echo json_encode(['success' => true]);
    } catch (Exception $e) { if ($pdo->inTransaction()) $pdo->rollBack(); ob_end_clean(); echo json_encode(['success' => false, 'message' => $e->getMessage()]); }
    exit;
}
