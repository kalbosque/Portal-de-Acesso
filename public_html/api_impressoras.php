<?php
require_once 'auth.php';
require_once 'includes/config.php';
require_once 'db.php';

header('Content-Type: application/json');

// A ação get_machines e scan_pcs não requerem autenticação (público)
$action = $_GET['action'] ?? '';

// Só requer autenticação se não for get_machines ou scan_pcs
if ($action !== 'get_machines' && $action !== 'scan_pcs') {
    if (!hasPermission('equipamentos')) {
        http_response_code(403);
        echo json_encode(['success' => false, 'error' => 'Acesso negado']);
        exit;
    }

    // Validação de CSRF para todas as ações que modificam dados (POST/GET de escrita)
    $isWriteAction = in_array($action, ['add_printer', 'delete_printer', 'update_name', 'set_machine_alias', 'sync_network_printers']);
    if ($isWriteAction) {
        $csrfToken = null;
        if ($_SERVER['REQUEST_METHOD'] === 'POST') {
            $input = json_decode(file_get_contents('php://input'), true);
            $csrfToken = $input['csrf_token'] ?? $_SERVER['HTTP_X_CSRF_TOKEN'] ?? null;
        } else {
            $csrfToken = $_GET['csrf_token'] ?? null;
        }
        if (!$csrfToken || !validateCsrfToken($csrfToken)) {
            http_response_code(403);
            echo json_encode(['success' => false, 'error' => 'Token CSRF inválido ou ausente.']);
            exit;
        }
    }
}

function respond(array $payload, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($payload);
    exit;
}

function isValidIp(string $ip): bool
{
    return filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false;
}

/**
 * Pinga um IP e retorna true se responder.
 * Compatível com Windows e Linux.
 */
function pingIpAddress(string $ip): bool
{
    if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
        // Primeiro tenta PowerShell Test-Connection que é o mais rápido e confiável no Windows se disponível
        $output = [];
        $resultCode = 0;
        $cmd = 'powershell.exe -NoProfile -Command "Test-Connection -ComputerName ' . escapeshellarg($ip) . ' -Count 1 -Quiet"';
        @exec($cmd, $output, $resultCode);
        $resultStr = trim(implode('', $output));
        if ($resultStr === 'True') {
            return true;
        } elseif ($resultStr === 'False') {
            return false;
        }
        
        // Fallback: ping tradicional do Windows.
        $outputPing = [];
        $resultCodePing = 0;
        @exec('ping -n 1 -w 800 ' . escapeshellarg($ip), $outputPing, $resultCodePing);
        $pingStr = implode("\n", $outputPing);
        return (stripos($pingStr, 'TTL=') !== false);
    } else {
        // Linux/Unix (dentro do contêiner Docker): ping rápido e silencioso
        $output = [];
        $resultCode = 0;
        // -c 1 (1 pacote), -W 1 (espera 1 segundo por resposta)
        @exec("ping -c 1 -W 1 " . escapeshellarg($ip) . " 2>&1", $output, $resultCode);
        return ($resultCode === 0);
    }
}

/**
 * Carrega e valida um arquivo JSON de status da rede.
 * Retorna null se o arquivo não existir, for inválido ou estiver desatualizado.
 * @param string[] $candidates  Caminhos candidatos para o arquivo.
 * @param int      $maxAgeMin   Idade máxima em minutos (padrão: 20). 0 = sem limite.
 */
function loadJsonStatusFile(array $candidates, int $maxAgeMin = 20): ?array
{
    foreach ($candidates as $path) {
        if (!file_exists($path)) {
            continue;
        }

        // Tenta ler o arquivo de forma segura. Em caso de leitura vazia/parcial por concorrência, tenta até 3 vezes.
        $content = false;
        for ($i = 0; $i < 3; $i++) {
            $handle = @fopen($path, 'r');
            if ($handle) {
                if (@flock($handle, LOCK_SH)) {
                    $size = filesize($path);
                    $content = $size > 0 ? @fread($handle, $size) : '';
                    @flock($handle, LOCK_UN);
                }
                @fclose($handle);
            }
            if ($content !== false && trim($content) !== '') {
                break;
            }
            usleep(50000); // Aguarda 50ms antes de tentar novamente
        }

        if ($content === false || trim($content) === '') {
            continue;
        }

        if (substr($content, 0, 3) === "\xef\xbb\xbf") {
            $content = substr($content, 3);
        }

        $decoded = json_decode($content, true);
        if (json_last_error() !== JSON_ERROR_NONE || !is_array($decoded)) {
            continue;
        }

        // Verifica se o arquivo está desatualizado com base no mtime do sistema
        if ($maxAgeMin > 0) {
            $mtime = filemtime($path);
            if ($mtime !== false) {
                $ageSeconds = time() - $mtime;
                if ($ageSeconds > ($maxAgeMin * 60)) {
                    $decoded['__stale'] = true;
                    $decoded['__age_minutes'] = (int) round($ageSeconds / 60);
                    return $decoded;
                }
            }
        }

        $decoded['__stale'] = false;
        return $decoded;
    }

    return null;
}

function normalizeMachineName(?string $value): string
{
    $value = trim((string) $value);
    if ($value === '') {
        return '';
    }

    if (function_exists('mb_strtoupper')) {
        return mb_strtoupper($value, 'UTF-8');
    }

    return strtoupper($value);
}

/**
 * Pinga um conjunto de IPs em paralelo usando fping.
 * Retorna um mapa [ip => true/false].
 * Resultados são cacheados por $cacheTtlSec segundos para evitar
 * ping flood quando a página atualiza a cada poucos segundos.
 * @param string[] $ips
 * @param int      $timeoutMs  Timeout por IP em milissegundos (padrão 250ms)
 * @param int      $cacheTtlSec TTL do cache em segundos (padrão 300s / 5 min)
 */
function pingMachinesParallel(array $ips, int $timeoutMs = 250, int $cacheTtlSec = 300): array
{
    $ips = array_unique(array_filter(
        $ips,
        static fn($ip) => filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false
    ));

    if (empty($ips)) {
        return [];
    }

    // Chave de cache baseada nos IPs
    sort($ips);
    $cacheKey  = md5(implode(',', $ips));
    $cacheFile = sys_get_temp_dir() . '/fping_cache_' . $cacheKey . '.json';

    // Retorna cache se ainda for válido
    if (file_exists($cacheFile) && (time() - filemtime($cacheFile)) < $cacheTtlSec) {
        $cached = json_decode(file_get_contents($cacheFile), true);
        if (is_array($cached)) {
            return $cached;
        }
    }

    $results = array_fill_keys($ips, false);

    if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
        // No Windows, como não temos fping nativo, pingamos com pingIpAddress
        foreach ($ips as $ip) {
            $results[$ip] = pingIpAddress($ip);
        }
    } else {
        // fping -r 0 (sem retentativas) -t <timeout_ms> -q -a retorna apenas os IPs que responderam
        $ipList = implode(' ', array_map('escapeshellarg', $ips));
        $cmd = "fping -r 0 -t {$timeoutMs} -q -a {$ipList} 2>/dev/null";

        $output = [];
        exec($cmd, $output);

        foreach ($output as $line) {
            $ip = trim($line);
            if (isset($results[$ip])) {
                $results[$ip] = true;
            }
        }
    }

    // Salva cache
    file_put_contents($cacheFile, json_encode($results));

    return $results;
}

if ($action === 'scan_ip') {
    $ip = trim($_GET['ip'] ?? '');
    if (!isValidIp($ip)) {
        respond(['success' => false, 'error' => 'IP invalido'], 400);
    }

    $isOnline = pingIpAddress($ip);

    $deviceName = 'Dispositivo Desconhecido';
    $isPrinter = false;

    if ($isOnline) {
        try {
            $snmpVal = @snmpget($ip, 'public', '.1.3.6.1.2.1.1.1.0', 500000, 1);
            if ($snmpVal) {
                $isPrinter = true;
                $deviceName = str_replace('STRING: ', '', $snmpVal);
            }
        } catch (Exception $e) {
            // Mantem resposta generica se SNMP falhar.
        }
    }

    respond([
        'success' => true,
        'ip' => $ip,
        'online' => $isOnline,
        'is_printer' => $isPrinter,
        'device_name' => trim($deviceName, '"')
    ]);
}

if ($action === 'add_printer') {
    $data = json_decode(file_get_contents('php://input'), true) ?: [];
    $nome = trim($data['nome'] ?? '');
    $ip = trim($data['ip'] ?? '');
    $modelo = trim($data['modelo'] ?? '');
    $localizacao = trim($data['localizacao'] ?? '');

    if ($nome === '' || !isValidIp($ip)) {
        respond(['success' => false, 'error' => 'Dados invalidos'], 400);
    }

    try {
        $stmt = $pdo->prepare("SELECT id FROM impressoras WHERE ip = ?");
        $stmt->execute([$ip]);
        if ($stmt->fetch()) {
            $stmt = $pdo->prepare("UPDATE impressoras SET nome = ?, modelo = ?, localizacao = ? WHERE ip = ?");
            $stmt->execute([$nome, $modelo, $localizacao, $ip]);
        } else {
            $stmt = $pdo->prepare("INSERT INTO impressoras (nome, ip, status, modelo, localizacao) VALUES (?, ?, 'Desconhecido', ?, ?)");
            $stmt->execute([$nome, $ip, $modelo, $localizacao]);
        }
        respond(['success' => true]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], 500);
    }
}

if ($action === 'check_all') {
    try {
        $stmt = $pdo->query("SELECT * FROM impressoras");
        $printers = $stmt->fetchAll();
        $results = [];

        foreach ($printers as $printer) {
            $isOnline = pingIpAddress($printer['ip']);
            
            $newStatus = $isOnline ? 'Online' : 'Offline';

            $upd = $pdo->prepare("UPDATE impressoras SET status = ?, ultima_verificacao = NOW() WHERE id = ?");
            $upd->execute([$newStatus, $printer['id']]);

            $results[] = ['id' => $printer['id'], 'status' => $newStatus];
        }

        respond(['success' => true, 'results' => $results]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], 500);
    }
}

if ($action === 'update_name') {
    $data = json_decode(file_get_contents('php://input'), true) ?: [];
    $id = intval($data['id'] ?? 0);
    $nome = trim($data['nome'] ?? '');
    $modelo = trim($data['modelo'] ?? '');
    $localizacao = trim($data['localizacao'] ?? '');

    if ($id <= 0 || $nome === '') {
        respond(['success' => false, 'error' => 'Dados invalidos'], 400);
    }

    try {
        $stmt = $pdo->prepare("UPDATE impressoras SET nome = ?, modelo = ?, localizacao = ? WHERE id = ?");
        $stmt->execute([$nome, $modelo, $localizacao, $id]);
        respond(['success' => true]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], 500);
    }
}

if ($action === 'delete_printer') {
    $id = intval($_GET['id'] ?? 0);
    if ($id <= 0) {
        respond(['success' => false, 'error' => 'ID invalido'], 400);
    }

    try {
        $stmt = $pdo->prepare("DELETE FROM impressoras WHERE id = ?");
        $stmt->execute([$id]);
        respond(['success' => true]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], 500);
    }
}

if ($action === 'sync_network_printers') {
    try {
        $monitorRede = loadJsonStatusFile([
            '/var/www/status_maquinas.json',
            __DIR__ . '/../status_maquinas.json',
        ]);

        if (empty($monitorRede['Maquinas'])) {
            throw new Exception('Nao ha dados de rede recentes. Execute o scanner_rede.ps1');
        }

        $added = 0;
        $printersKeywords = ['PRINTER', 'LEXMARK', 'HP', 'EPSON', 'CANON', 'BROTHER', 'SAMSUNG', 'RICOH', 'XEROX', 'KYOCERA'];

        foreach ($monitorRede['Maquinas'] as $ip => $machine) {
            if (($machine['Status'] ?? '') !== 'Online') continue;
            
            $name = strtoupper($machine['Nome'] ?? '');
            $isPotentialPrinter = false;
            
            foreach ($printersKeywords as $kw) {
                if (strpos($name, $kw) !== false) {
                    $isPotentialPrinter = true;
                    break;
                }
            }

            if ($isPotentialPrinter) {
                $stmt = $pdo->prepare("SELECT id FROM impressoras WHERE ip = ?");
                $stmt->execute([$ip]);
                if ($stmt->fetch()) {
                    $stmt = $pdo->prepare("UPDATE impressoras SET nome = ?, status = 'Online' WHERE ip = ?");
                    $stmt->execute([$machine['Nome'], $ip]);
                } else {
                    $stmt = $pdo->prepare("INSERT INTO impressoras (nome, ip, status) VALUES (?, ?, 'Online')");
                    $stmt->execute([$machine['Nome'], $ip]);
                }
                $added++;
            }
        }

        respond(['success' => true, 'added' => $added]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], 500);
    }
}

$maquinasAliasesFile = __DIR__ . '/maquinas_aliases.json';

if ($action === 'set_machine_alias') {
    $data = json_decode(file_get_contents('php://input'), true) ?: [];
    $maquina = trim($data['maquina'] ?? '');
    $usuario = trim($data['usuario'] ?? '');

    if ($maquina === '') {
        respond(['success' => false, 'error' => 'Nome da maquina invalido'], 400);
    }

    $aliases = [];
    if (file_exists($maquinasAliasesFile)) {
        $aliases = json_decode(file_get_contents($maquinasAliasesFile), true) ?: [];
    }

    if ($usuario === '') {
        unset($aliases[$maquina]); // Se vazio, remove o alias
    } else {
        $aliases[$maquina] = $usuario;
    }

    file_put_contents($maquinasAliasesFile, json_encode($aliases, JSON_PRETTY_PRINT));
    respond(['success' => true]);
}

if ($action === 'get_toner_level') {
    $ip = trim($_GET['ip'] ?? '');
    if (!$ip) {
        respond(['success' => false, 'error' => 'IP invalido'], 400);
    }

    try {
        file_put_contents('debug_toner.log', date('H:i:s') . " - Solicitando Toner para IP: $ip\n", FILE_APPEND);
        
        if (!function_exists('snmpget')) {
            file_put_contents('debug_toner.log', "   ERRO: Extensao SNMP nao encontrada.\n", FILE_APPEND);
            respond(['success' => true, 'snmp_enabled' => false, 'toner' => null, 'reason' => 'Extensao SNMP nao instalada no PHP']);
        }

        // OIDs padrão RFC 3805 Printer MIB (Mais comuns)
        $oids = [
            '1.3.6.1.2.1.43.11.1.1.9.1.1', // Nível atual (Padrão)
            '1.3.6.1.2.1.43.11.1.1.9.1.2', // Nível atual (Alternativo)
            '1.3.6.1.4.1.641.2.1.5.2.1.1.1.1.6', // Lexmark específico
            '1.3.6.1.4.1.11.2.3.9.4.2.1.1.2.1.0'  // HP específico
        ];
        
        $oidMax = '1.3.6.1.2.1.43.11.1.1.8.1.1';   // Capacidade máxima
        
        $timeout = 800000; // 800ms
        $retries = 1;

        $rawLevel = false;
        foreach ($oids as $oid) {
            $rawLevel = @snmpget($ip, 'public', $oid, $timeout, $retries);
            if ($rawLevel !== false) break;
        }

        $rawMax = @snmpget($ip, 'public', $oidMax, $timeout, $retries);

        if ($rawLevel === false || $rawMax === false) {
            file_put_contents('debug_toner.log', "   FALHA: A impressora no IP $ip nao respondeu aos comandos SNMP.\n", FILE_APPEND);
            respond(['success' => true, 'snmp_enabled' => true, 'toner' => null, 'reason' => 'Impressora nao respondeu via SNMP']);
        }

        file_put_contents('debug_toner.log', "   BRUTO: Level=$rawLevel, Max=$rawMax\n", FILE_APPEND);

        // Limpa o retorno "INTEGER: 50" para pegar apenas o número
        $level = intval(preg_replace('/[^0-9-]/', '', $rawLevel));
        $max = intval(preg_replace('/[^0-9-]/', '', $rawMax));

        if ($max <= 0) {
            // Se não souber o máximo, tentamos ver se o level já veio em porcentagem (comum em algumas marcas)
            if ($level > 0 && $level <= 100) {
                 respond(['success' => true, 'snmp_enabled' => true, 'toner' => $level]);
            }
            respond(['success' => true, 'snmp_enabled' => true, 'toner' => null, 'reason' => 'Capacidade Maxima invalida']);
        }

        // Algumas impressoras retornam -2 para Desconhecido ou -3 para "Tem alguma tinta, mas não sabe o exato"
        if ($level === -3) {
            respond(['success' => true, 'snmp_enabled' => true, 'toner' => 'OK']);
        } elseif ($level < 0) {
            respond(['success' => true, 'snmp_enabled' => true, 'toner' => null, 'raw_level' => $level]);
        }

        // Calcula porcentagem
        $percentage = round(($level / $max) * 100);
        if ($percentage > 100) $percentage = 100;
        if ($percentage < 0) $percentage = 0;

        respond(['success' => true, 'snmp_enabled' => true, 'toner' => $percentage]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage()], 500);
    }
}

if ($action === 'get_machines') {
    try {
        $stmt = $pdo->query("
            SELECT
                i.maquina AS nome_maquina,
                COALESCE((
                    SELECT i2.usuario
                    FROM impressoes i2
                    WHERE i2.maquina = i.maquina
                    ORDER BY i2.data_hora DESC
                    LIMIT 1
                ), 'Sem registro') AS usuario,
                MAX(i.data_hora) AS ultima_acao,
                COUNT(*) AS total_impressoes,
                MAX(i.ip_maquina) AS ip_maquina
            FROM impressoes i
            WHERE i.maquina IS NOT NULL AND i.maquina != ''
            GROUP BY i.maquina
            ORDER BY MAX(i.data_hora) DESC
        ");
        $machines = $stmt->fetchAll(PDO::FETCH_ASSOC);

        $printMap = [];
        foreach ($machines as $machine) {
            $name = trim((string) ($machine['nome_maquina'] ?? ''));
            if ($name === '') {
                continue;
            }

            $printMap[normalizeMachineName($name)] = [
                'nome_maquina' => $name,
                'usuario' => trim((string) ($machine['usuario'] ?? 'Sem registro')),
                'ultima_acao' => $machine['ultima_acao'] ?: null,
                'total_impressoes' => (int) ($machine['total_impressoes'] ?? 0),
                'ip' => $machine['ip_maquina'] ?: '-',
            ];
        }

        $monitorUsuarios = loadJsonStatusFile([
            '/var/www/status_usuarios.json',
            __DIR__ . '/../../status_usuarios.json',
            __DIR__ . '/../status_usuarios.json',
        ]);

        $monitorRede = loadJsonStatusFile([
            '/var/www/status_maquinas.json',
            __DIR__ . '/../status_maquinas.json',
        ]);

        // Cria um mapa global de IP por Nome de Máquina para garantir que nada fique vazio
        $globalIpMap = [];
        if (!empty($monitorUsuarios['Maquinas'])) {
            foreach ($monitorUsuarios['Maquinas'] as $m) {
                if (!empty($m['IP'])) $globalIpMap[normalizeMachineName($m['Nome'])] = $m['IP'];
            }
        }
        if (!empty($monitorRede['Maquinas'])) {
            foreach ($monitorRede['Maquinas'] as $ip => $m) {
                if (!empty($ip)) $globalIpMap[normalizeMachineName($m['Nome'])] = $ip;
            }
        }

        // Carrega aliases uma única vez
        $aliases = [];
        if (file_exists($maquinasAliasesFile)) {
            $aliases = json_decode(file_get_contents($maquinasAliasesFile), true) ?: [];
        }

        // Determina se os arquivos estão desatualizados
        $usuariosStale = !empty($monitorUsuarios['__stale']);
        $redeStale     = !empty($monitorRede['__stale']);
        $anyStale      = $usuariosStale || $redeStale;

        // --- Coleta todos os IPs para ping paralelo ---
        $ipsToVerify = [];
        if (!empty($monitorUsuarios['Maquinas'])) {
            foreach ($monitorUsuarios['Maquinas'] as $m) {
                $ip = trim((string) ($m['IP'] ?? ''));
                if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                    $ipsToVerify[] = $ip;
                }
            }
        }
        if (!empty($monitorRede['Maquinas'])) {
            foreach ($monitorRede['Maquinas'] as $ip => $m) {
                if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                    $ipsToVerify[] = $ip;
                }
            }
        }
        foreach ($printMap as $info) {
            $ip = trim((string) ($info['ip'] ?? ''));
            if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                $ipsToVerify[] = $ip;
            }
        }
        $ipsToVerify = array_values(array_unique($ipsToVerify));

        // Executa pings paralelos sempre que houver IPs conhecidos
        $liveStatus = [];
        if (!empty($ipsToVerify)) {
            $liveStatus = pingMachinesParallel($ipsToVerify);
        }

        if (!empty($monitorUsuarios['Maquinas']) && is_array($monitorUsuarios['Maquinas'])) {
            foreach ($monitorUsuarios['Maquinas'] as $machine) {
                $name = trim((string) ($machine['Nome'] ?? ''));
                if ($name === '') {
                    continue;
                }

                $key = normalizeMachineName($name);
                $printInfo = $printMap[$key] ?? null;
                $users = is_array($machine['Usuarios'] ?? null) ? $machine['Usuarios'] : [];
                $activeUser = 'Sem usuario';

                foreach ($users as $user) {
                    if (($user['Status'] ?? '') === 'Ativo') {
                        $activeUser = trim((string) ($user['Usuario'] ?? 'Sem usuario'));
                        break;
                    }
                }

                if ($activeUser === 'Sem usuario' && !empty($users[0]['Usuario'])) {
                    $activeUser = trim((string) $users[0]['Usuario']);
                }

                if (isset($aliases[$name])) {
                    $activeUser = $aliases[$name];
                }

                // Status: se arquivo fresco → confiar no JSON; se velho → usar ping
                $machineIp = trim((string)($machine['IP'] ?? ''));
                if ($machineIp !== '' && isset($liveStatus[$machineIp])) {
                    $statusFinal = $liveStatus[$machineIp] ? 'Online' : 'Offline';
                } elseif ($usuariosStale && ($machineIp === '' || !isset($liveStatus[$machineIp]))) {
                    $statusFinal = 'Desconhecido';
                } else {
                    $statusFinal = $machine['Status'] ?? 'Desconhecido';
                }

                $machinesWithStatus[] = [
                    'nome_maquina'       => $name,
                    'usuario'            => $activeUser,
                    'status'             => $statusFinal,
                    'ultima_acao'        => $printInfo['ultima_acao'] ?? null,
                    'ultima_verificacao' => $machine['HoraVerificacao'] ?? ($monitorUsuarios['DataCaptura'] ?? null),
                    'total_impressoes'   => $printInfo['total_impressoes'] ?? 0,
                    'minutos_ago'        => null,
                    'fonte_status'       => $usuariosStale ? 'live_ping' : 'monitor_usuarios',
                    'stale'              => $usuariosStale,
                    'ip'                 => $machineIp ?: ($globalIpMap[$key] ?? '-'),
                    'has_alias'          => isset($aliases[$name])
                ];
                $knownNames[$key] = true;
            }
        }

        if (!empty($monitorRede['Maquinas']) && is_array($monitorRede['Maquinas'])) {
            foreach ($monitorRede['Maquinas'] as $ip => $machine) {
                $name = trim((string) ($machine['Nome'] ?? ''));
                if ($name === '' || in_array($name, ['OFFLINE', 'SEM-NOME'], true)) {
                    continue;
                }

                $key = normalizeMachineName($name);
                if (isset($knownNames[$key])) {
                    continue;
                }

                $printInfo = $printMap[$key] ?? null;
                $activeUser = $printInfo['usuario'] ?? 'Sem usuario';

                if (isset($aliases[$name])) {
                    $activeUser = $aliases[$name];
                }

                // Status: se arquivo fresco → confiar no JSON; se velho → usar ping
                if (isset($liveStatus[$ip])) {
                    $statusFinal = $liveStatus[$ip] ? 'Online' : 'Offline';
                } elseif ($redeStale && !isset($liveStatus[$ip])) {
                    $statusFinal = 'Desconhecido';
                } else {
                    $statusFinal = $machine['Status'] ?? 'Desconhecido';
                }

                $machinesWithStatus[] = [
                    'nome_maquina'       => $name,
                    'usuario'            => $activeUser,
                    'status'             => $statusFinal,
                    'ultima_acao'        => $printInfo['ultima_acao'] ?? null,
                    'ultima_verificacao' => $machine['Timestamp'] ?? ($monitorRede['UltimaAtualizacao'] ?? null),
                    'total_impressoes'   => $printInfo['total_impressoes'] ?? 0,
                    'minutos_ago'        => null,
                    'fonte_status'       => $redeStale ? 'live_ping' : 'status_maquinas',
                    'stale'              => $redeStale,
                    'ip'                 => $ip,
                    'has_alias'          => isset($aliases[$name])
                ];
                $knownNames[$key] = true;
            }
        }

        foreach ($printMap as $key => $printInfo) {
            if (isset($knownNames[$key])) {
                continue;
            }

            $status = 'Desconhecido';
            $minutesAgo = null;

            if (!empty($printInfo['ultima_acao'])) {
                $now = new DateTime('now');
                $lastAction = new DateTime($printInfo['ultima_acao']);
                $interval = $now->diff($lastAction);
                $minutesAgo = ($interval->days * 24 * 60) + ($interval->h * 60) + $interval->i;
                if ($minutesAgo < 0) {
                    $minutesAgo = 0;
                }
                $status = $minutesAgo <= 60 ? 'Online' : 'Offline';
            }

            $activeUser = $printInfo['usuario'] ?? 'Sem usuario';
            $origName = $printInfo['nome_maquina'];
            if (isset($aliases[$origName])) {
                $activeUser = $aliases[$origName];
            }

            $machinesWithStatus[] = [
                'nome_maquina' => $origName,
                'usuario' => $activeUser,
                'status' => $status,
                'ultima_acao' => $printInfo['ultima_acao'],
                'ultima_verificacao' => null,
                'total_impressoes' => $printInfo['total_impressoes'],
                'minutos_ago' => $minutesAgo,
                'fonte_status' => 'impressoes',
                'ip' => $printInfo['ip'] !== '-' ? $printInfo['ip'] : ($globalIpMap[$key] ?? '-'),
                'has_alias' => isset($aliases[$origName])
            ];
        }

        usort($machinesWithStatus, static function (array $a, array $b): int {
            $statusOrder = ['Online' => 0, 'Desconhecido' => 1, 'Offline' => 2];
            $statusA = $statusOrder[$a['status']] ?? 3;
            $statusB = $statusOrder[$b['status']] ?? 3;

            if ($statusA !== $statusB) {
                return $statusA <=> $statusB;
            }

            return strcmp($a['nome_maquina'], $b['nome_maquina']);
        });

        respond([
            'success'    => true,
            'machines'   => $machinesWithStatus,
            'updated_at' => $monitorUsuarios['DataCaptura']
                ?? $monitorRede['UltimaAtualizacao']
                ?? date('Y-m-d H:i:s'),
            'total'      => count($machinesWithStatus),
            'data_stale' => ($usuariosStale ?? false) || ($redeStale ?? false),
            'stale_age_min' => $monitorUsuarios['__age_minutes'] ?? $monitorRede['__age_minutes'] ?? null,
        ]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage(), 'debug' => true], 500);
    }
}

if ($action === 'get_machines_v2_internal_disabled') {
    try {
        // Get all unique machines with their last user and print job timestamp
        // Agrupa por maquina E usuario, pegando o usuário e data da última ação
        $stmt = $pdo->query("
            SELECT 
                maquina as nome_maquina,
                usuario,
                MAX(data_hora) as ultima_acao,
                COUNT(*) as total_impressoes
            FROM impressoes
            WHERE maquina IS NOT NULL AND maquina != ''
            GROUP BY maquina, usuario
            ORDER BY MAX(data_hora) DESC
        ");
        $machines = $stmt->fetchAll(PDO::FETCH_ASSOC);

        // Determine online/offline status based on recent activity (within 1 hour = online)
        $now = new DateTime('now');
        $machinesWithStatus = [];
        
        foreach ($machines as $machine) {
            try {
                if (empty($machine['ultima_acao'])) {
                    continue;
                }
                
                $lastAction = new DateTime($machine['ultima_acao']);
                $interval = $now->diff($lastAction);
                // Calculate minutes ago considering days and hours
                $minutesAgo = ($interval->days * 24 * 60) + ($interval->h * 60) + $interval->i;
                
                // Handle negative values (future dates)
                if ($minutesAgo < 0) {
                    $minutesAgo = 0;
                }
                
                // If last action was within 1 hour, consider online
                $status = $minutesAgo <= 60 ? 'Online' : 'Offline';
                
                $machinesWithStatus[] = [
                    'nome_maquina' => trim($machine['nome_maquina']),
                    'usuario' => trim($machine['usuario']),
                    'status' => $status,
                    'ultima_acao' => $machine['ultima_acao'],
                    'total_impressoes' => intval($machine['total_impressoes']),
                    'minutos_ago' => $minutesAgo
                ];
            } catch (Exception $e) {
                // Skip machines with invalid dates
                continue;
            }
        }

        respond([
            'success' => true,
            'machines' => $machinesWithStatus,
            'total' => count($machinesWithStatus)
        ]);
    } catch (Exception $e) {
        respond(['success' => false, 'error' => $e->getMessage(), 'debug' => true], 500);
    }
}

if ($action === 'scan_pcs') {
    $prefix = trim($_GET['prefix'] ?? '192.168.1.');
    
    // Normalizar prefixo
    $prefix = rtrim($prefix, '.') . '.';

    $devices = [];
    
    // Ler arquivo status_maquinas.json criado pelo scanner_rede.ps1
    $statusFile = '/var/www/status_maquinas.json';
    
    // Se não encontrar em Docker, tentar no Windows
    if (!file_exists($statusFile)) {
        $statusFile = __DIR__ . '/../status_maquinas.json';
    }
    
    if (file_exists($statusFile)) {
        $content = file_get_contents($statusFile);
        
        // Remover BOM UTF-8 se presente
        if (substr($content, 0, 3) === "\xef\xbb\xbf") {
            $content = substr($content, 3);
        }
        
        $data = json_decode($content, true);
        
        if ($data && isset($data['Maquinas'])) {
            foreach ($data['Maquinas'] as $ip => $machine) {
                // Filtrar: apenas máquinas no prefixo correto e que estão Online
                if (strpos($ip, $prefix) === 0 && isset($machine['Status']) && $machine['Status'] === 'Online') {
                    $hostname = $machine['Nome'] ?? null;
                    
                    // Ignorar nomes genéricos
                    if ($hostname === 'OFFLINE' || $hostname === 'SEM-NOME' || empty($hostname)) {
                        $hostname = null;
                    }
                    
                    $devices[] = [
                        'ip' => $ip,
                        'hostname' => $hostname,
                        'mac' => null,
                        'online' => true
                    ];
                }
            }
        }
    }
    
    respond([
        'success' => true,
        'devices' => $devices,
        'total' => count($devices),
        'prefix' => $prefix,
        'source' => 'status_file'
    ]);
    return;
}

respond(['success' => false, 'error' => 'Acao invalida'], 400);
