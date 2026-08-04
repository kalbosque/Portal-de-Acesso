<?php
/**
 * Captura o IP real do usuário, mesmo atrás de proxies, Cloudflare ou Docker.
 */
if (!function_exists('getRealIp')) {
    function getRealIp(): string {
        $ip = $_SERVER['REMOTE_ADDR'] ?? 'Desconhecido';
        
        // Verifica se o REMOTE_ADDR é um IP interno confiável (Docker, Localhost)
        $is_trusted = preg_match('/^(127\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|192\.168\.)/', $ip);

        if ($is_trusted) {
            $headers = ['HTTP_X_FORWARDED_FOR', 'HTTP_CLIENT_IP', 'HTTP_X_REAL_IP'];
            foreach ($headers as $header) {
                if (!empty($_SERVER[$header])) {
                    $parts = explode(',', $_SERVER[$header]);
                    $candidate = trim($parts[0]);
                    if (filter_var($candidate, FILTER_VALIDATE_IP)) {
                        $ip = $candidate;
                        break;
                    }
                }
            }
        }

        // 0. Tenta pelo Cookie de Handshake do Agente 2.0 (Solução Definitiva)
        if (isset($_COOKIE['pd_machine_name'])) {
            $cookieMachine = $_COOKIE['pd_machine_name'];
            $statusFile = __DIR__ . '/../status_maquinas.json';
            if (file_exists($statusFile)) {
                $data = json_decode(@file_get_contents($statusFile), true);
                if ($data && isset($data['Maquinas'])) {
                    foreach ($data['Maquinas'] as $mIp => $m) {
                        if (strcasecmp($m['Nome'] ?? '', $cookieMachine) === 0) {
                            $ip = $mIp;
                            // Se achou pelo cookie, retorna logo
                            @file_put_contents(__DIR__ . '/last_ip_debug.json', json_encode(array_merge($_SERVER, ['DETECTED_IP' => $ip, 'METHOD' => 'COOKIE_HANDSHAKE']), JSON_PRETTY_PRINT));
                            return $ip;
                        }
                    }
                }
            }
        }

        // Se o IP detectado for do Docker (172.x) ou local, tentamos buscar o IP real no Monitor 2.0
        if (session_status() === PHP_SESSION_ACTIVE && ($ip === '127.0.0.1' || preg_match('/^172\.(1[6-9]|2[0-9]|3[0-1])\./', $ip))) {
            $targetUser = $_SESSION['username'] ?? null;
            $targetMachine = $_SESSION['maquina_vinculada'] ?? null;

            if ($targetUser || $targetMachine) {
                $statusFile = __DIR__ . '/../status_maquinas.json';
                if (file_exists($statusFile)) {
                    $data = json_decode(@file_get_contents($statusFile), true);
                    if ($data && isset($data['Maquinas'])) {
                        foreach ($data['Maquinas'] as $mIp => $m) {
                            // 1. Tenta pelo Vínculo Manual (Prioridade)
                            if ($targetMachine && strcasecmp($m['Nome'] ?? '', $targetMachine) === 0) {
                                $ip = $mIp;
                                break;
                            }
                            // 2. Tenta pelo usuário logado no Windows (Automático)
                            if (isset($m['WindowsUser']) && strcasecmp($m['WindowsUser'], $targetUser) === 0) {
                                $ip = $mIp;
                                break;
                            }
                        }
                    }
                }
            }
        }

        // DEBUG: Salva os headers para análise
        @file_put_contents(__DIR__ . '/last_ip_debug.json', json_encode(array_merge($_SERVER, ['DETECTED_IP' => $ip]), JSON_PRETTY_PRINT));

        return $ip;
    }
}

$host = getenv('DB_HOST') ?: 'db';
$db   = getenv('DB_NAME') ?: 'sistema_impressao';
$user = getenv('DB_USER') ?: 'root';
$pass = getenv('DB_PASS') ?: 'root';

// Se não estiver no Docker, tenta usar localhost (para scripts locais)
if ($host === 'db' && !isset($_SERVER['SERVER_SOFTWARE']) && strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
    $host = 'localhost';
}

$dsn = "pgsql:host=$host;dbname=$db";
$options = [
    PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    PDO::ATTR_EMULATE_PREPARES   => false,
];

try {
     $pdo = new PDO($dsn, $user, $pass, $options);
     $pdo->exec("SET timezone TO 'America/Porto_Velho'");

     // Nota: As verificações de CREATE TABLE e ALTER TABLE foram movidas
     // para public_html/install.php visando ganho de performance.
     // Rode o install.php uma vez para garantir que o banco está atualizado.

} catch (\PDOException $e) {
     throw new \PDOException($e->getMessage(), (int)$e->getCode());
}
?>
