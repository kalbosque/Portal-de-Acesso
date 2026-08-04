<?php
require_once 'db.php';

echo "Iniciando verificação de banco de dados...\n";

try {
     $pdo->exec("CREATE TABLE IF NOT EXISTS chamados (
         id SERIAL PRIMARY KEY,
         usuario VARCHAR(100) NOT NULL,
         titulo VARCHAR(150) NOT NULL,
         descricao TEXT NOT NULL,
         nota_tecnica TEXT NULL,
         prioridade VARCHAR(20) DEFAULT 'Media' CHECK (prioridade IN ('Baixa', 'Media', 'Alta')),
         status VARCHAR(20) DEFAULT 'Aberto' CHECK (status IN ('Aberto', 'Em Atendimento', 'Resolvido')),
         data_abertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         data_resolucao TIMESTAMP NULL
     )");

     // Função auxiliar para checar colunas no PostgreSQL
     if (!function_exists('columnExists')) {
         function columnExists($pdo, $table, $column) {
             $stmt = $pdo->prepare("SELECT column_name FROM information_schema.columns WHERE table_name = ? AND column_name = ?");
             $stmt->execute([$table, $column]);
             return $stmt->rowCount() > 0;
         }
     }

     // Atualizar e adicionar colunas se a tabela já existir
     try {
         if (!columnExists($pdo, 'chamados', 'prioridade')) {
             $pdo->exec("ALTER TABLE chamados ADD COLUMN prioridade VARCHAR(20) DEFAULT 'Media' CHECK (prioridade IN ('Baixa', 'Media', 'Alta'))");
         }

         if (!columnExists($pdo, 'chamados', 'nota_tecnica')) {
             $pdo->exec("ALTER TABLE chamados ADD COLUMN nota_tecnica TEXT NULL");
         }

         // Colunas para Suporte Inteligente
         if (!columnExists($pdo, 'chamados', 'categoria')) {
             $pdo->exec("ALTER TABLE chamados ADD COLUMN categoria VARCHAR(50) DEFAULT 'Outros'");
         }

         if (!columnExists($pdo, 'chamados', 'equipamento_id')) {
             $pdo->exec("ALTER TABLE chamados ADD COLUMN equipamento_id VARCHAR(100) NULL");
         }

         if (!columnExists($pdo, 'chamados', 'anexo_url')) {
             $pdo->exec("ALTER TABLE chamados ADD COLUMN anexo_url VARCHAR(255) NULL");
         }
          
         // Colunas básicas de usuário
         if (!columnExists($pdo, 'usuarios', 'nome')) {
             $pdo->exec("ALTER TABLE usuarios ADD COLUMN nome VARCHAR(100) NULL");
         }
         
         if (!columnExists($pdo, 'usuarios', 'email')) {
             $pdo->exec("ALTER TABLE usuarios ADD COLUMN email VARCHAR(100) NULL UNIQUE");
         }

         // Coluna de status da conta (ativo, pendente, bloqueado)
         if (!columnExists($pdo, 'usuarios', 'status_conta')) {
             $pdo->exec("ALTER TABLE usuarios ADD COLUMN status_conta VARCHAR(20) DEFAULT 'ativo' CHECK (status_conta IN ('ativo', 'pendente', 'bloqueado'))");
         }

         // Coluna de senha temporária (reset de senha)
         if (!columnExists($pdo, 'usuarios', 'senha_temp')) {
             $pdo->exec("ALTER TABLE usuarios ADD COLUMN senha_temp VARCHAR(255) NULL");
         }
 
         // Coluna para Tipo de Documento na auditoria de impressões
         if (!columnExists($pdo, 'impressoes', 'tipo_documento')) {
             $pdo->exec("ALTER TABLE impressoes ADD COLUMN tipo_documento VARCHAR(50) DEFAULT 'Sistema'");
             
             // Adiciona ip_maquina se não existir
             try { $pdo->exec("ALTER TABLE impressoes ADD COLUMN ip_maquina VARCHAR(45)"); } catch (Exception $e) {}
             
             // Migração Inicial: Tenta classificar o que já existe no banco
             $pdo->exec("UPDATE impressoes SET tipo_documento = 'PDF' WHERE documento ILIKE '%.pdf%' AND (tipo_documento = 'Sistema' OR tipo_documento IS NULL)");
             $pdo->exec("UPDATE impressoes SET tipo_documento = 'Word' WHERE (documento ILIKE '%.doc%' OR documento ILIKE '%.docx%') AND (tipo_documento = 'Sistema' OR tipo_documento IS NULL)");
             $pdo->exec("UPDATE impressoes SET tipo_documento = 'Excel' WHERE (documento ILIKE '%.xls%' OR documento ILIKE '%.xlsx%' OR documento ILIKE '%.csv%') AND (tipo_documento = 'Sistema' OR tipo_documento IS NULL)");
             $pdo->exec("UPDATE impressoes SET tipo_documento = 'Imagem' WHERE (documento ILIKE '%.jpg%' OR documento ILIKE '%.png%' OR documento ILIKE '%.jpeg%') AND (tipo_documento = 'Sistema' OR tipo_documento IS NULL)");
             $pdo->exec("UPDATE impressoes SET tipo_documento = 'Web' WHERE (documento ILIKE '%chrome%' OR documento ILIKE '%edge%' OR documento ILIKE '%http%') AND (tipo_documento = 'Sistema' OR tipo_documento IS NULL)");
         }
     } catch (Exception $e) { echo "Aviso na atualização de colunas: " . $e->getMessage() . "\n"; }

     // Verificar e adicionar coluna permissoes se não existir
     if (!columnExists($pdo, 'usuarios', 'permissoes')) {
         $pdo->exec("ALTER TABLE usuarios ADD COLUMN permissoes TEXT NULL");
     }

     if (!columnExists($pdo, 'usuarios', 'maquina_vinculada')) {
         $pdo->exec("ALTER TABLE usuarios ADD COLUMN maquina_vinculada VARCHAR(100) NULL");
     }

     // Tabela de Histórico de Acessos (Auditoria)
     $pdo->exec("CREATE TABLE IF NOT EXISTS historico_acessos (
         id SERIAL PRIMARY KEY,
         usuario_id INT NOT NULL,
         usuario_nome VARCHAR(100),
         ip VARCHAR(45),
         acao VARCHAR(255),
         data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
     )");

     // Tabela de Interações (Chat/Mural) dos Chamados
     $pdo->exec("CREATE TABLE IF NOT EXISTS chamados_interacoes (
         id SERIAL PRIMARY KEY,
         chamado_id INT NOT NULL,
         usuario VARCHAR(100) NOT NULL,
         mensagem TEXT NOT NULL,
         data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         FOREIGN KEY (chamado_id) REFERENCES chamados(id) ON DELETE CASCADE
     )");

     // Tabela de status de digitação em tempo real
     $pdo->exec("CREATE TABLE IF NOT EXISTS chat_typing (
         chamado_id INT NOT NULL,
         usuario VARCHAR(100) NOT NULL,
         ultima_atividade TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         PRIMARY KEY (chamado_id, usuario)
     )");
     
     // Tabela de Configurações do Sistema
     $pdo->exec("CREATE TABLE IF NOT EXISTS configuracoes (
         chave VARCHAR(50) PRIMARY KEY,
         valor TEXT NULL
     )");

     // ÍNDICES DE PERFORMANCE (Crucial para produção)
     try {
         $pdo->exec("CREATE INDEX IF NOT EXISTS idx_impressoes_data ON impressoes(data_hora)");
         $pdo->exec("CREATE INDEX IF NOT EXISTS idx_impressoes_usuario ON impressoes(usuario)");
         $pdo->exec("CREATE INDEX IF NOT EXISTS idx_chamados_status ON chamados(status)");
         $pdo->exec("CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios(username)");
     } catch (Exception $e) { echo "Aviso nos índices: " . $e->getMessage() . "\n"; }

     echo "Banco de dados verificado e atualizado com sucesso!\n";
} catch (\PDOException $e) {
     echo "Erro crítico: " . $e->getMessage() . "\n";
}
?>
