<?php
header('Content-Type: application/json');
require_once '../includes/config.php';

$arquivoStatus = __DIR__ . '/../status_usuarios.json';

try {
    $raw = file_get_contents('php://input');
    $data = json_decode($raw, true);
    
    if (!$data || !isset($data['maquina'])) {
        throw new Exception('Dados invalidos');
    }

    $maquina = strtoupper($data['maquina']);
    $usuario = $data['usuario'] ?? 'Nenhum';
    $ip = $_SERVER['REMOTE_ADDR'];

    // Carrega o status atual
    $status = ['Maquinas' => []];
    if (file_exists($arquivoStatus)) {
        $status = json_decode(file_get_contents($arquivoStatus), true) ?: ['Maquinas' => []];
    }

    $encontrada = false;
    $agora = date('d/m/Y H:i:s');

    foreach ($status['Maquinas'] as &$m) {
        if (strtoupper($m['Nome']) === $maquina || $m['IP'] === $ip) {
            $m['Status'] = 'Online';
            $m['IP'] = $ip;
            $m['HoraVerificacao'] = $agora;
            $m['TotalUsuarios'] = 1;
            $m['Usuarios'] = [[
                'Usuario' => $usuario,
                'Sessao' => 'Console (Agente)',
                'Status' => 'Ativo',
                'TempoOcioso' => '0m',
                'DataHoraCaptura' => $agora
            ]];
            $encontrada = true;
            break;
        }
    }

    if (!$encontrada) {
        $status['Maquinas'][] = [
            'Nome' => $maquina,
            'IP' => $ip,
            'Status' => 'Online',
            'HoraVerificacao' => $agora,
            'TotalUsuarios' => 1,
            'Usuarios' => [[
                'Usuario' => $usuario,
                'Sessao' => 'Console (Agente)',
                'Status' => 'Ativo',
                'TempoOcioso' => '0m',
                'DataHoraCaptura' => $agora
            ]]
        ];
    }

    $status['HoraAtualizacao'] = date('H:i:s');
    $status['MaquinasOnline'] = count(array_filter($status['Maquinas'], function($m) { return $m['Status'] === 'Online'; }));
    $status['TotalMaquinas'] = count($status['Maquinas']);
    $status['UsuariosAtivos'] = count(array_filter($status['Maquinas'], function($m) { return !empty($m['Usuarios']); }));

    file_put_contents($arquivoStatus, json_encode($status, JSON_PRETTY_PRINT));

    echo json_encode(['success' => true]);

} catch (Exception $e) {
    http_response_code(400);
    echo json_encode(['success' => false, 'error' => $e->getMessage()]);
}
