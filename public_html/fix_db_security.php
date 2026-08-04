<?php
require_once 'db.php';

echo "--- REFORÇO DE SEGURANÇA: USUÁRIOS ---\n\n";

try {
    // 1. Limpar espaços extras
    $pdo->exec("UPDATE usuarios SET email = TRIM(email), username = TRIM(username)");
    echo "✅ Espaços extras removidos.\n";

    // 2. Tentar adicionar CONSTRAINT de e-mail único
    // Usamos um bloco TRY/CATCH por coluna para não travar se já existir
    try {
        $pdo->exec("ALTER TABLE usuarios ADD CONSTRAINT uk_usuario_email UNIQUE (email)");
        echo "✅ REGRA ATIVADA: O Banco de Dados agora proíbe e-mails duplicados.\n";
    } catch (Exception $e) {
        if (strpos($e->getMessage(), 'already exists') !== false) {
            echo "ℹ️ A regra de e-mail único já estava ativa.\n";
        } else {
            echo "❌ Erro ao aplicar regra de e-mail: " . $e->getMessage() . "\n";
            echo "   DICA: Se houver e-mails repetidos agora, você precisa apagar um deles antes.\n";
        }
    }

    // 3. Tentar adicionar CONSTRAINT de username único
    try {
        $pdo->exec("ALTER TABLE usuarios ADD CONSTRAINT uk_usuario_username UNIQUE (username)");
        echo "✅ REGRA ATIVADA: O Banco de Dados agora proíbe nomes de usuário duplicados.\n";
    } catch (Exception $e) {
        if (strpos($e->getMessage(), 'already exists') !== false) {
            echo "ℹ️ A regra de username único já estava ativa.\n";
        } else {
            echo "❌ Erro ao aplicar regra de username: " . $e->getMessage() . "\n";
        }
    }

} catch (Exception $e) {
    echo "❌ Erro Geral: " . $e->getMessage();
}
?>
