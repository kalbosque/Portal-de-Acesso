<?php
// Chama a API get_machines de forma real
$ch = curl_init('http://localhost/api_impressoras.php?action=get_machines');
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 30);
$result = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

echo "HTTP: $httpCode\n";
$data = json_decode($result, true);
if ($data) {
    echo "Success: " . ($data['success'] ? 'true' : 'false') . "\n";
    echo "Total: " . ($data['total'] ?? 'N/A') . "\n";
    echo "Data Stale: " . ($data['data_stale'] ? 'YES' : 'NO') . "\n";
    echo "Stale Age: " . ($data['stale_age_min'] ?? 'N/A') . " min\n";
    echo "\nMachines:\n";
    if (!empty($data['machines'])) {
        foreach ($data['machines'] as $m) {
            printf("  %-20s IP=%-16s Status=%-12s Fonte=%-20s\n",
                $m['nome_maquina'], $m['ip'] ?? '-', $m['status'], $m['fonte_status'] ?? 'n/a');
        }
    }
} else {
    echo "RAW: " . substr($result, 0, 500) . "\n";
}
