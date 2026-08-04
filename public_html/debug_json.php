<?php
require_once 'db.php';
require_once 'includes/config.php';
header('Content-Type: application/json');

// Simula chamada get_machines sem autenticação
$_GET['action'] = 'get_machines';

// Lê os JSONs
function loadJsonStatusFile2(array $candidates, int $maxAgeMin = 20): ?array {
    foreach ($candidates as $path) {
        if (!file_exists($path)) continue;
        $mtime = filemtime($path);
        $ageSeconds = time() - $mtime;
        $content = file_get_contents($path);
        if (substr($content, 0, 3) === "\xef\xbb\xbf") $content = substr($content, 3);
        $decoded = json_decode($content, true);
        if (json_last_error() === JSON_ERROR_NONE && is_array($decoded)) {
            $decoded['__stale'] = ($maxAgeMin > 0 && $ageSeconds > ($maxAgeMin * 60));
            $decoded['__age_minutes'] = (int) round($ageSeconds / 60);
            return $decoded;
        }
    }
    return null;
}

$monitorRede = loadJsonStatusFile2(['/var/www/status_maquinas.json', __DIR__ . '/../status_maquinas.json']);
$monitorUsuarios = loadJsonStatusFile2(['/var/www/status_usuarios.json', __DIR__ . '/../../status_usuarios.json', __DIR__ . '/../status_usuarios.json']);

echo json_encode([
    'monitorRede' => $monitorRede,
    'monitorUsuarios' => $monitorUsuarios,
    'rodeStale' => !empty($monitorRede['__stale']),
    'usuariosStale' => !empty($monitorUsuarios['__stale']),
], JSON_PRETTY_PRINT);
