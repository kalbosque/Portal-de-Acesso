<?php
// SEGURANÇA: Configurações de Cookie de Sessão
ini_set('session.cookie_httponly', 1);
ini_set('session.use_only_cookies', 1);
ini_set('session.cookie_samesite', 'Lax');

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

// Redireciona se não estiver logado (ignora páginas de login e logout)
$page = basename($_SERVER['PHP_SELF']);
if (!isset($_SESSION['user_id']) && $page !== 'login.php' && $page !== 'logout.php') {
    header('Location: login.php');
    exit;
}

if (!function_exists('isLoggedIn')) {
    function isLoggedIn() { return isset($_SESSION['user_id']); }
}

// Gerador de Token CSRF
if (session_status() === PHP_SESSION_ACTIVE && !isset($_SESSION['csrf_token'])) {
    $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
}

function getCsrfToken() { return $_SESSION['csrf_token'] ?? ''; }

function validateCsrfToken($token) {
    return hash_equals($_SESSION['csrf_token'] ?? '', $token ?? '');
}

function isAdmin(): bool {
    return isset($_SESSION['user_role']) && $_SESSION['user_role'] === 'admin';
}

function hasPermission(string $modulo): bool {
    if (in_array($modulo, ['dashboard', 'equipamentos', 'relatorios']) && (!defined('MODULO_IMPRESSAO') || !MODULO_IMPRESSAO)) {
        return false;
    }
    if ($modulo === 'chamados' && (!defined('MODULO_SUPORTE') || !MODULO_SUPORTE)) {
        return false;
    }

    $modulos_admin = ['dashboard', 'equipamentos', 'relatorios', 'usuarios'];
    if (in_array($modulo, $modulos_admin)) {
        return isAdmin();
    }

    if (isAdmin()) return true;
    $perms = $_SESSION['user_perms'] ?? [];
    return in_array($modulo, $perms);
}

function requireAdmin(): void {
    if (!isAdmin()) {
        http_response_code(403);
        die('
            <div style="background:#0f172a;height:100vh;display:flex;align-items:center;justify-content:center;color:white;font-family:sans-serif;flex-direction:column;gap:1rem;">
                <h1 style="font-size:2rem;font-weight:900;">🔒 Acesso Restrito</h1>
                <p style="color:#94a3b8;">Esta área é exclusiva para Administradores.</p>
                <a href="chamados.php" style="margin-top:1rem;padding:.75rem 2rem;background:#6366f1;border-radius:1rem;color:white;font-weight:bold;text-decoration:none;">Voltar ao Suporte</a>
            </div>
        ');
    }
}
?>
