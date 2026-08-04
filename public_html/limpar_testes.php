<?php
require_once 'db.php';
require_once 'auth.php';

if (!isAdmin()) {
    die('Acesso negado. Apenas administradores podem limpar o sistema.');
}

try {
    $pdo->exec("TRUNCATE TABLE chamados_interacoes CASCADE");
    $pdo->exec("TRUNCATE TABLE chamados RESTART IDENTITY CASCADE");
    echo "<h1 style='color:green; font-family:sans-serif;'>✅ Sistema de Chamados Limpo com Sucesso!</h1>";
    echo "<p>Todos os tickets e mensagens de teste foram removidos. Você já pode deletar este arquivo.</p>";
    echo "<a href='chamados.php'>Voltar ao Sistema</a>";
} catch (Exception $e) {
    echo "<h1 style='color:red;'>❌ Erro ao limpar: " . $e->getMessage() . "</h1>";
}
?>
