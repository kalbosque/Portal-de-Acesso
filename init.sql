CREATE TABLE IF NOT EXISTS impressoras (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    ip VARCHAR(45) NOT NULL UNIQUE,
    status VARCHAR(20) DEFAULT 'Desconhecido' CHECK (status IN ('Online', 'Offline', 'Desconhecido')),
    total_fisico_paginas INT DEFAULT 0,
    ultima_verificacao TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS impressoes (
    id SERIAL PRIMARY KEY,
    impressora_id INT NULL,
    tipo_impressao VARCHAR(20) NOT NULL CHECK (tipo_impressao IN ('Preto e Branco', 'Colorida')),
    paginas INT NOT NULL,
    preco_unitario DECIMAL(10,2) NOT NULL,
    valor_total DECIMAL(10,2) NOT NULL,
    maquina VARCHAR(100) NULL,
    usuario VARCHAR(100) NULL,
    documento VARCHAR(255) NULL,
    data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (impressora_id) REFERENCES impressoras(id)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NULL,
    email VARCHAR(100) NULL UNIQUE,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'operator' CHECK (role IN ('admin', 'operator')),
    status_conta VARCHAR(20) DEFAULT 'ativo' CHECK (status_conta IN ('ativo', 'pendente', 'bloqueado')),
    senha_temp VARCHAR(255) NULL,
    permissoes TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default admin user: admin / admin
-- Password hash for 'admin' using password_hash('admin', PASSWORD_DEFAULT)
INSERT INTO usuarios (username, password_hash, role)
VALUES ('admin', '$2y$10$.5YAekxyymCcxnY9VPdeGeewi1TflyaMpaUpVferlF.PabG4Dw.Bu', 'admin')
ON CONFLICT (username) DO NOTHING;

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_impressoes_data_hora ON impressoes(data_hora);
CREATE INDEX IF NOT EXISTS idx_impressoes_usuario ON impressoes(usuario);
CREATE INDEX IF NOT EXISTS idx_impressoes_impressora_id ON impressoes(impressora_id);
CREATE INDEX IF NOT EXISTS idx_impressoras_status ON impressoras(status);

CREATE TABLE IF NOT EXISTS cofre_senhas (
    id SERIAL PRIMARY KEY,
    titulo VARCHAR(150) NOT NULL,
    categoria VARCHAR(50) DEFAULT 'E-mail',
    setor VARCHAR(80) DEFAULT 'TI',
    login_email VARCHAR(200) NOT NULL,
    senha_cifrada TEXT NOT NULL,
    url VARCHAR(500) NULL,
    observacoes TEXT NULL,
    criado_por VARCHAR(100) DEFAULT 'admin',
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
