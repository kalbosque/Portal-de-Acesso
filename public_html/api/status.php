<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: X-Agent-Token, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    http_response_code(405);
    echo json_encode(['status' => 'erro', 'detalhe' => 'Metodo nao permitido']);
    exit;
}

require_once '../db.php';
require_once '../includes/config.php';

function getAgentTokenFromRequest(): string
{
    $headerToken = $_SERVER['HTTP_X_AGENT_TOKEN'] ?? '';
    if ($headerToken !== '') {
        return trim($headerToken);
    }

    $authHeader = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (stripos($authHeader, 'Bearer ') === 0) {
        return trim(substr($authHeader, 7));
    }

    return '';
}

try {
    if (defined('APP_AGENT_TOKEN') && APP_AGENT_TOKEN !== '') {
        $providedToken = getAgentTokenFromRequest();
        if (!hash_equals(APP_AGENT_TOKEN, $providedToken)) {
            throw new Exception('Token do agente invalido');
        }
    }

    $stmt = $pdo->query("SELECT COUNT(*) as total FROM impressoras");
    $row = $stmt->fetch();

    echo json_encode([
        'status' => 'ok',
        'servidor' => gethostname(),
        'hora' => date('d/m/Y H:i:s'),
        'impressoras' => (int)$row['total'],
    ]);
} catch (Exception $e) {
    $message = $e->getMessage();
    $status = str_contains($message, 'Token do agente invalido') ? 401 : 500;
    http_response_code($status);
    echo json_encode(['status' => 'erro', 'detalhe' => $message]);
}
