<?php
/**
 * Configuracoes dinamicas da empresa / marca.
 */
$configFile = __DIR__ . '/config.json';
$configData = [];

if (file_exists($configFile)) {
    $configData = json_decode(file_get_contents($configFile), true) ?: [];
}

define('APP_NAME', $configData['APP_NAME'] ?? 'PrintDash');
define('APP_TAGLINE', $configData['APP_TAGLINE'] ?? 'Controle de Impressao');
define('APP_LOGO_URL', $configData['APP_LOGO_URL'] ?? '');
define('APP_COLOR', $configData['APP_COLOR'] ?? '#6366f1');
define('APP_PRICE_BW', floatval($configData['APP_PRICE_BW'] ?? 0.50));
define('APP_PRICE_COLOR', floatval($configData['APP_PRICE_COLOR'] ?? 1.00));
define('APP_AGENT_TOKEN', getenv('APP_AGENT_TOKEN') ?: ($configData['APP_AGENT_TOKEN'] ?? ''));

// Módulos Ativos (Feature Toggles)
define('MODULO_IMPRESSAO',    (bool)($configData['MODULO_IMPRESSAO'] ?? true));
define('MODULO_SUPORTE',      (bool)($configData['MODULO_SUPORTE'] ?? true));
define('MODULO_ATENDIMENTO',  (bool)($configData['MODULO_ATENDIMENTO'] ?? false));
define('URL_ATENDIMENTO',     (string)($configData['URL_ATENDIMENTO'] ?? 'http://192.168.1.236:3000'));
define('GUIA_SUPORTE_URL',    (string)($configData['GUIA_SUPORTE_URL'] ?? ''));

