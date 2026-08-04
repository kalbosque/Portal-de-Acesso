<?php
// capture.php - LEGACY FALLBACK
// Este arquivo recebe dados de agentes antigos e aplica a mesma limpeza do Agente V2.

require_once '../db.php';
require_once '../includes/config.php';

$raw = file_get_contents('php://input');
$data = json_decode($raw, true);

if (!$data) {
    echo json_encode(['success' => false, 'error' => 'No data']);
    exit;
}

$maquina = $data['maquina'] ?? 'Desconhecida';
$ip = $data['ip_maquina'] ?? $_SERVER['REMOTE_ADDR'];
$documento = $data['documento'] ?? 'Sem Titulo';
$usuario = $data['usuario'] ?? 'Desconhecido';
$impressora = $data['nome_impressora'] ?? 'Padrao';
$paginas = intval($data['paginas'] ?? 1);
file_put_contents(__DIR__ . '/../debug_agente_v2.log', date('H:i:s') . " - LEGACY CAPTURE: Maq=$maquina, Doc=$documento, User=$usuario\n", FILE_APPEND);

// Limpeza de Nomes
if ($documento === "Documento de Impressão" || $documento === "Sem Título") {
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

$appProcess = strtolower($data['AppProcess'] ?? '');

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
    
    // Fallback por palavras-chave
    if ($tipoDoc === 'Sistema') {
        if (str_contains($docLower, 'pdf') || str_contains($docLower, 'acrobat')) $tipoDoc = 'PDF';
        elseif (str_contains($docLower, 'word') || str_contains($docLower, 'winword')) $tipoDoc = 'Word';
        elseif (str_contains($docLower, 'excel') || str_contains($docLower, 'planilha') || str_contains($docLower, 'calc')) $tipoDoc = 'Excel';
        elseif (str_contains($docLower, 'powerpoint') || str_contains($docLower, 'powerpnt') || str_contains($docLower, 'impress')) $tipoDoc = 'PPT';
        elseif (str_contains($docLower, 'chrome') || str_contains($docLower, 'edge') || str_contains($docLower, 'http') || str_contains($docLower, 'firefox')) $tipoDoc = 'Web';
        elseif (str_contains($docLower, 'outlook') || str_contains($docLower, 'e-mail') || str_contains($docLower, 'email')) $tipoDoc = 'E-mail';
        elseif (str_contains($docLower, 'txt') || str_contains($docLower, 'bloco de notas') || str_contains($docLower, 'notepad')) $tipoDoc = 'Texto';
    }
}

// 3. Limpeza Final (Remove prefixos chatos agora que já identificamos o tipo)
$prefixos = ["/^Microsoft Word - /i", "/^Microsoft Excel - /i", "/^Google Chrome - /i", "/^Adobe Acrobat Reader [^-]+ - /i", "/^Notepad - /i", "/^Bloco de Notas - /i"];
foreach ($prefixos as $regex) $documento = preg_replace($regex, '', $documento);
$documento = trim($documento);

// Busca ou cria a impressora
$stmtImp = $pdo->prepare("SELECT id FROM impressoras WHERE nome = ? LIMIT 1");
$stmtImp->execute([$impressora]);
$impressoraId = $stmtImp->fetchColumn();

if (!$impressoraId) {
    try {
        $stmtIns = $pdo->prepare("INSERT INTO impressoras (nome, ip, status) VALUES (?, ?, 'Online') RETURNING id");
        $stmtIns->execute([$impressora, $ip]);
        $impressoraId = $stmtIns->fetchColumn();
    } catch (Exception $e) {
        $impressoraId = null;
    }
}

// Registro
$tipoImpressao = 'P&B';
$precoUnitario = defined('APP_PRICE_BW') ? APP_PRICE_BW : 0.10;
$valorTotal = $paginas * $precoUnitario;

$stmt = $pdo->prepare("
    INSERT INTO impressoes (usuario, impressora_id, maquina, documento, tipo_documento, paginas, ip_maquina, data_hora, tipo_impressao, preco_unitario, valor_total)
    VALUES (?, ?, ?, ?, ?, ?, ?, NOW(), ?, ?, ?)
");
$stmt->execute([$usuario, $impressoraId, $maquina, $documento, $tipoDoc, $paginas, $ip, $tipoImpressao, $precoUnitario, $valorTotal]);


echo json_encode(['success' => true]);
