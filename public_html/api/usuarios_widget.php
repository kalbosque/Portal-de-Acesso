<?php
// =============================================================
// api/usuarios_widget.php - Widget JSON de usuários para dashboard
// =============================================================

header('Content-Type: application/json');

$arquivoStatus = null;
$candidatos = [
    '/var/www/status_usuarios.json',
    __DIR__ . '/../../status_usuarios.json',
    __DIR__ . '/../status_usuarios.json'
];

foreach ($candidatos as $path) {
    if (file_exists($path)) {
        $arquivoStatus = $path;
        break;
    }
}

$dados = [
    'success' => false,
    'data' => null,
    'mensagem' => 'Sem dados'
];

if ($arquivoStatus && file_exists($arquivoStatus)) {
    try {
        $json = file_get_contents($arquivoStatus);
        $statusData = json_decode($json, true);
        
        if ($statusData) {
            $dados['success'] = true;
            $dados['data'] = [
                'data_captura' => $statusData['DataCaptura'] ?? date('d/m/Y H:i:s'),
                'total_maquinas' => $statusData['TotalMaquinas'] ?? 0,
                'maquinas_online' => $statusData['MaquinasOnline'] ?? 0,
                'usuarios_ativos' => $statusData['UsuariosAtivos'] ?? 0,
                'status_pct' => ($statusData['TotalMaquinas'] ?? 0) > 0 ? round(($statusData['MaquinasOnline'] / $statusData['TotalMaquinas']) * 100) : 0
            ];
            $dados['mensagem'] = 'OK';
        }
    } catch (Exception $e) {
        $dados['mensagem'] = 'Erro ao ler dados: ' . $e->getMessage();
    }
} else {
    $dados['mensagem'] = 'Arquivo de status não encontrado. Inicie o monitor pelo INICIAR.bat';
}

echo json_encode($dados, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
?>
