<?php
echo "PHP Version: " . phpversion() . "\n";
echo "ZipArchive: " . (class_exists('ZipArchive') ? "OK" : "MISSING") . "\n";
echo "Backups Dir Writable: " . (is_writable(__DIR__ . '/backups') ? "YES" : "NO") . "\n";
echo "Uploads Dir: " . (is_dir(__DIR__ . '/uploads') ? "EXISTS" : "MISSING") . "\n";
?>
