/**
 * PrintDash 2.0 - Agent Handshake
 * Identifica a máquina local conversando com o agente via localhost
 */
(function() {
    async function detectLocalMachine() {
        try {
            // Tenta falar com o Agente no computador local
            const response = await fetch('http://127.0.0.1:5050/whoami', {
                method: 'GET',
                mode: 'cors'
            });
            
            if (response.ok) {
                const data = await response.json();
                console.log("Agente Local Detectado:", data.hostname);
                
                // Salva o nome da máquina em um cookie para o PHP ler
                document.cookie = "pd_machine_name=" + data.hostname + "; path=/; max-age=86400"; // 24h
            }
        } catch (e) {
            // Agente não está rodando nesta máquina ou porta bloqueada
            console.log("Agente local não detectado.");
        }
    }

    // Executa ao carregar a página
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', detectLocalMachine);
    } else {
        detectLocalMachine();
    }
})();
