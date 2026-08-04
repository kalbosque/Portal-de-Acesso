<?php
require_once 'db.php';
$initialPassword = getenv('ADMIN_INITIAL_PASSWORD');
if (!$initialPassword) {
    exit("Defina ADMIN_INITIAL_PASSWORD no ambiente antes de executar este script.\n");
}

$admin = $pdo->query("SELECT id FROM usuarios WHERE username = 'admin'")->fetch();
if ($admin) {
    $pdo->prepare("UPDATE usuarios SET status_conta='ativo', role='admin', password_hash=? WHERE username='admin'")->execute([password_hash($initialPassword, PASSWORD_DEFAULT)]);
    echo "Admin reativado.\n";
} else {
    $pdo->prepare("INSERT INTO usuarios (nome, email, username, password_hash, role, status_conta, permissoes) VALUES (?,?,?,?,?,?,?)")
        ->execute(['Administrador', 'admin@sistema.com', 'admin', password_hash($initialPassword, PASSWORD_DEFAULT), 'admin', 'ativo', '[]']);
    echo "Admin criado. Usuario: admin\n";
}
echo "\n\nUsuarios atuais:\n";
foreach ($pdo->query("SELECT id, username, role, status_conta FROM usuarios ORDER BY id")->fetchAll(PDO::FETCH_ASSOC) as $u) {
    echo "ID:{$u['id']} | {$u['username']} | {$u['role']} | {$u['status_conta']}\n";
}
?>
