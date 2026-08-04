<?php
/**
 * API PrintDash 2.0 - Receptor de Dados do Agente Python
 */
require_once 'db.php';
require_once 'includes/config.php';


header('Content-Type: application/json');

// SEGURANÇA: Verifica a chave de API do Agente
$agent_api_key = getenv('AGENT_API_KEY') ?: (defined('APP_AGENT_TOKEN') && APP_AGENT_TOKEN !== '' ? APP_AGENT_TOKEN : 'MUST_BE_SET_IN_ENV');
$clientKey = $_SERVER['HTTP_X_API_KEY'] ?? '';

if ($clientKey !== $agent_api_key || $agent_api_key === 'MUST_BE_SET_IN_ENV') {
    http_response_code(401);
    echo json_encode(['success' => false, 'error' => 'Acesso nao autorizado']);
    exit;
}

// Bloqueia se o módulo de impressão estiver desativado globalmente
if (!MODULO_IMPRESSAO) {
    echo json_encode(['success' => false, 'error' => 'Modulo de impressao desativado nesta licenca.']);
    exit;
}


// Recebe o JSON do Agente
$input = file_get_contents('php://input');
$data = json_decode($input, true);

if (!$data || !isset($data['maquina'])) {
    http_response_code(400);
    echo json_encode(['success' => false, 'error' => 'Dados invalidos']);
    exit;
}

$maquina = $data['maquina'];
$ip = $data['ip'] ?? '0.0.0.0';
$versao = $data['versao'] ?? '2.0';
$payload = $data['dados'] ?? [];
$tipo = $payload['tipo'] ?? '';

try {
    // 1. Processar Heartbeat (Sinal de Vida)
    if ($tipo === 'heartbeat') {
        updateMachineStatus($maquina, $ip, $payload, $versao);
        
        // Resposta customizada para o Heartbeat com comandos
        $response = [
            'success' => true,
            'timestamp' => date('Y-m-d H:i:s'),
            'latest_version' => '2.4.0', // Versão alvo para auto-update
            'commands' => []
        ];

        echo json_encode($response);
        exit;
    }
    
    // 2. Processar Impressões
    if ($tipo === 'impressoes' && !empty($payload['jobs'])) {
        foreach ($payload['jobs'] as $job) {
            logPrintJob($maquina, $ip, $job);
        }
    }

    // 3. Rota para Download do Agente (para Auto-Update)
    if (isset($_GET['action']) && $_GET['action'] === 'download_latest') {
        $file = __DIR__ . '/../dist/agent_2.0.exe';
        if (file_exists($file)) {
            header('Content-Description: File Transfer');
            header('Content-Type: application/octet-stream');
            header('Content-Disposition: attachment; filename="agent_update.exe"');
            header('Expires: 0');
            header('Cache-Control: must-revalidate');
            header('Pragma: public');
            header('Content-Length: ' . filesize($file));
            readfile($file);
            exit;
        }
    }

    echo json_encode(['success' => true, 'timestamp' => date('Y-m-d H:i:s')]);

} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => $e->getMessage()]);
}

/**
 * Atualiza o status da máquina no sistema de monitoramento
 */
function updateMachineStatus($nome, $ip, $payload, $versao = 'Agente Antigo') {
    global $pdo;
    
    // $payload JÁ É $data['dados'] — ler as chaves diretamente (sem double-nesting)
    $usuario = $payload['windows_user'] ?? 'Desconhecido';
    $agora   = date('d/m/Y H:i:s');
    $tipo    = $payload['tipo'] ?? 'desconhecido';

    // Salvar/Atualizar no banco de dados (Single Source of Truth do FastAPI)
    if (isset($pdo)) {
        try {
            $stmtStatus = $pdo->prepare("
                INSERT INTO status_maquinas (ip, nome, status, windows_user, timestamp, versao_agente)
                VALUES (?, ?, 'Online', ?, NOW(), ?)
                ON CONFLICT (ip) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    status = 'Online',
                    windows_user = EXCLUDED.windows_user,
                    timestamp = NOW(),
                    versao_agente = EXCLUDED.versao_agente
            ");
            $stmtStatus->execute([$ip, $nome, $usuario, $versao]);
        } catch (Exception $e) {
            error_log("Erro ao atualizar status_maquinas DB: " . $e->getMessage());
        }
    }

    // Log de Debug para acompanharmos a conexão
    file_put_contents(__DIR__ . '/debug_agente_v2.log', date('H:i:s') . " - Versão: $versao - Recebido: $nome ($ip) - Tipo: $tipo - User: $usuario\n", FILE_APPEND);

    // 1. Atualiza status_maquinas.json (Novo)
    $fileNew = __DIR__ . '/../status_maquinas.json';
    $statusNew = ['Maquinas' => []];
    if (file_exists($fileNew)) $statusNew = json_decode(file_get_contents($fileNew), true) ?: ['Maquinas' => []];
    $statusNew['Maquinas'][$ip] = [
        'Nome' => $nome,
        'Status' => 'Online',
        'WindowsUser' => $usuario,
        'Timestamp' => date('Y-m-d H:i:s'),
        'VersaoAgente' => $versao
    ];
    $statusNew['UltimaAtualizacao'] = date('Y-m-d H:i:s');
    file_put_contents($fileNew, json_encode($statusNew, JSON_PRETTY_PRINT));

    // 2. Atualiza status_usuarios.json (Legado - para o Painel Principal)
    $fileOld = __DIR__ . '/../status_usuarios.json';
    if (!file_exists($fileOld)) $fileOld = __DIR__ . '/status_usuarios.json'; // Fallback
    
    $statusOld = ['Maquinas' => []];
    if (file_exists($fileOld)) $statusOld = json_decode(file_get_contents($fileOld), true) ?: ['Maquinas' => []];
    
    $encontrada = false;
    $nomeLimpo = strtoupper(trim($nome));
    $ipLimpo = trim($ip);

    foreach ($statusOld['Maquinas'] as &$m) {
        $mNome = strtoupper(trim($m['Nome'] ?? ''));
        $mIp = trim($m['IP'] ?? '');

        // Considera a mesma máquina se o NOME for igual ou se o IP for igual (e não vazio)
        if (($mNome === $nomeLimpo && $nomeLimpo !== '') || ($mIp === $ipLimpo && $ipLimpo !== '')) {
            $m['Nome'] = $nome; // Atualiza o nome pro caso de ter mudado o case
            $m['Status'] = 'Online';
            $m['IP'] = $ip;
            $m['HoraVerificacao'] = $agora;
            $m['Usuarios'] = [['Usuario' => $usuario, 'Sessao' => 'Console', 'Status' => 'Ativo', 'DataHoraCaptura' => $agora]];
            $encontrada = true;
            break;
        }
    }
    
    if (!$encontrada) {
        $statusOld['Maquinas'][] = [
            'Nome' => $nome, 'IP' => $ip, 'Status' => 'Online', 'HoraVerificacao' => $agora,
            'Usuarios' => [['Usuario' => $usuario, 'Sessao' => 'Console', 'Status' => 'Ativo', 'DataHoraCaptura' => $agora]]
        ];
    }
    
    // Limpar duplicatas de segurança, priorizando a mais recente (do fim pro começo)
    $maquinasUnicas = [];
    $chavesUsadas = [];
    foreach (array_reverse($statusOld['Maquinas']) as $m) {
        $key = strtoupper(trim($m['Nome']));
        if (!isset($chavesUsadas[$key])) {
            $chavesUsadas[$key] = true;
            $maquinasUnicas[] = $m;
        }
    }
    $statusOld['Maquinas'] = array_reverse($maquinasUnicas);

    // ADIÇÃO CRUCIAL: Gerar contadores para o painel antigo
    $statusOld['MaquinasOnline'] = 0;
    $statusOld['UsuariosAtivos'] = 0;
    foreach ($statusOld['Maquinas'] as $m) {
        if (($m['Status'] ?? '') === 'Online') $statusOld['MaquinasOnline']++;
        if (!empty($m['Usuarios']) && ($m['Usuarios'][0]['Usuario'] ?? '') !== 'Disponível') $statusOld['UsuariosAtivos']++;
    }
    $statusOld['TotalMaquinas'] = count($statusOld['Maquinas']);
    $statusOld['HoraAtualizacao'] = date('H:i:s');

    file_put_contents($fileOld, json_encode($statusOld, JSON_PRETTY_PRINT));
}

/**
 * Registra um trabalho de impressão no banco de dados com verificação de duplicidade
 */
function logPrintJob($maquina, $ip, $job) {
    global $pdo;
    
    $documento = $job['DocumentName'] ?? 'Documento de Impressão';
    $usuario = $job['UserName'] ?? 'Sistema';
    $impressora = $job['PrinterName'] ?? 'Padrao';
    $paginas = intval($job['TotalPages'] ?? 1);
    

    // 1. Limpeza e Recuperação do Nome
    $documento = trim($documento);
    
    // Lista estendida de nomes genéricos (incluindo variações de codificação)
    $nomesGenericos = [
        "documento de impressão", "documento de impressao",
        "documento de impressæo", "documento de impressÆo",
        "documento de impressã£o", "documento de impressao",
        "sem título", "sem titulo", "print document", "document",
        "página de teste", "pagina de teste"
    ];

    $isGenerico = false;
    foreach ($nomesGenericos as $g) {
        if (mb_strtolower($documento) === $g) {
            $isGenerico = true;
            break;
        }
    }

    if ($isGenerico || empty($documento)) {
        $documento = "Documento sem Título (Capturado)";
    }

    // 2. Classificação de Tipo de Documento (Antes de limpar os prefixos)
    $docLower = strtolower($documento);
    $tipoDoc = 'Sistema';

    $extMap = [
        'pdf'  => 'PDF',
        'doc'  => 'Word',  'docx' => 'Word',
        'xls'  => 'Excel', 'xlsx' => 'Excel', 'csv' => 'Excel',
        'ppt'  => 'PPT',   'pptx' => 'PPT',
        'txt'  => 'Texto', 'log'  => 'Texto',
        'jpg'  => 'Imagem','png'  => 'Imagem','jpeg' => 'Imagem',
        'html' => 'Web',   'htm'  => 'Web'
    ];

    $appProcess = strtolower($job['AppProcess'] ?? '');

    // Tenta identificar por extensão
    $ext = pathinfo($docLower, PATHINFO_EXTENSION);
    if ($ext && isset($extMap[$ext])) {
        $tipoDoc = $extMap[$ext];
    } else {
        // Tenta identificar por Processo do Aplicativo (MAIS PRECISO)
        if ($appProcess) {
            if (str_contains($appProcess, 'winword')) $tipoDoc = 'Word';
            elseif (str_contains($appProcess, 'excel')) $tipoDoc = 'Excel';
            elseif (str_contains($appProcess, 'powerpnt')) $tipoDoc = 'PPT';
            elseif (str_contains($appProcess, 'acrord') || str_contains($appProcess, 'pdf')) $tipoDoc = 'PDF';
            elseif (str_contains($appProcess, 'chrome') || str_contains($appProcess, 'msedge') || str_contains($appProcess, 'firefox')) $tipoDoc = 'Web';
            elseif (str_contains($appProcess, 'outlook')) $tipoDoc = 'E-mail';
            elseif (str_contains($appProcess, 'notepad')) $tipoDoc = 'Texto';
        }
        
        // Fallback por palavras-chave (EXTREMAMENTE AGRESSIVO)
        if ($tipoDoc === 'Sistema') {
            if (preg_match('/pdf|acrobat|reader|foxit/i', $docLower)) $tipoDoc = 'PDF';
            elseif (preg_match('/word|winword|doc|docx|contrato|memo|oficio|declaração/i', $docLower)) $tipoDoc = 'Word';
            elseif (preg_match('/excel|xls|xlsx|csv|planilha|calc|tabela|faturamento/i', $docLower)) $tipoDoc = 'Excel';
            elseif (preg_match('/powerpoint|pptx|ppt|apresentação/i', $docLower)) $tipoDoc = 'PPT';
            elseif (preg_match('/chrome|edge|http|firefox|google|web|navegador/i', $docLower)) $tipoDoc = 'Web';
            elseif (preg_match('/outlook|e-mail|email|mensagem/i', $docLower)) $tipoDoc = 'E-mail';
            elseif (preg_match('/txt|bloco|nota|notepad|log/i', $docLower)) $tipoDoc = 'Texto';
            elseif (preg_match('/imagem|jpg|png|jpeg|foto|print/i', $docLower)) $tipoDoc = 'Imagem';
        }
    }

    // 3. Limpeza Final (Remove prefixos chatos agora que já identificamos o tipo)
    $prefixos = [
        "/^Microsoft Word - /i", "/^Microsoft Excel - /i", "/^Microsoft PowerPoint - /i",
        "/^Google Chrome - /i", "/^Adobe Acrobat Reader [^-]+ - /i", "/^Foxit Reader - /i",
        "/^Notepad - /i", "/^Bloco de Notas - /i"
    ];
    foreach ($prefixos as $regex) $documento = preg_replace($regex, '', $documento);
    $documento = trim($documento);
    
    file_put_contents(__DIR__ . '/debug_agente_v2.log', sprintf(
        "%s - CLASSIFY: Doc=[%s], App=[%s], Result=[%s]\n",
        date('H:i:s'), $documento, $appProcess, $tipoDoc
    ), FILE_APPEND);

    // Evita duplicatas nos últimos 2 minutos
    // Melhorado para ser Case-Insensitive e ignorar espaços extras
    $check = $pdo->prepare("
        SELECT id FROM impressoes 
        WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(?)) 
        AND LOWER(TRIM(documento)) = LOWER(TRIM(?)) 
        AND paginas = ? 
        AND LOWER(TRIM(maquina)) = LOWER(TRIM(?)) 
        AND data_hora > NOW() - INTERVAL '2 minutes'
        LIMIT 1
    ");
    // DEBUG: Verificação de duplicata
    file_put_contents(__DIR__ . '/debug_agente_v2.log', sprintf(
        "%s - CHECK: User=[%s], Doc=[%s], Pag=[%d], Maq=[%s]\n",
        date('H:i:s'), $usuario, $documento, $paginas, $maquina
    ), FILE_APPEND);

    $check->execute([$usuario, $documento, $paginas, $maquina]);
    $existingId = $check->fetchColumn();
    
    if ($existingId) {
        file_put_contents(__DIR__ . '/debug_agente_v2.log', date('H:i:s') . " - SKIP: Duplicata encontrada (ID: $existingId)\n", FILE_APPEND);
        return;
    }

    // Busca ou cria a impressora para obter o impressora_id
    $stmtImp = $pdo->prepare("SELECT id FROM impressoras WHERE nome = ? LIMIT 1");
    $stmtImp->execute([$impressora]);
    $impressoraId = $stmtImp->fetchColumn();

    if (!$impressoraId) {
        try {
            $stmtIns = $pdo->prepare("INSERT INTO impressoras (nome, ip, status) VALUES (?, ?, 'Online') RETURNING id");
            $stmtIns->execute([$impressora, $ip]);
            $impressoraId = $stmtIns->fetchColumn();
        } catch (Exception $e) {
            $impressoraId = null; // Caso de falha (ex: IP duplicado)
        }
    }
    
    // Insere com as colunas obrigatórias
    $tipoImpressao = 'P&B'; // O Agente atual não detecta cor via Event 307
    $precoUnitario = defined('APP_PRICE_BW') ? APP_PRICE_BW : 0.10;
    $valorTotal = $paginas * $precoUnitario;

    $stmt = $pdo->prepare("
        INSERT INTO impressoes (usuario, impressora_id, maquina, documento, tipo_documento, paginas, ip_maquina, data_hora, tipo_impressao, preco_unitario, valor_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, NOW(), ?, ?, ?)
    ");
    $stmt->execute([$usuario, $impressoraId, $maquina, $documento, $tipoDoc, $paginas, $ip, $tipoImpressao, $precoUnitario, $valorTotal]);

}

// Fecha a conexão para liberar o pool do PostgreSQL
$pdo = null;
?>
