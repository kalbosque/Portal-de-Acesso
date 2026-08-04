<?php
$backupDir = __DIR__ . '/backups/';
echo "Caminho: $backupDir\n";
echo "Existe pasta? " . (is_dir($backupDir) ? "SIM" : "NÃO") . "\n";
$files = glob($backupDir . "*.zip");
echo "Total de arquivos .zip: " . count($files) . "\n";
foreach($files as $f) {
    echo " - " . basename($f) . " (" . filesize($f) . " bytes)\n";
}
?>
