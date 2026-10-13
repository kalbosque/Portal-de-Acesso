-- DRAFT ONLY: DO NOT APPLY to the active database.
-- Apply only in an isolated staging database after tenant-scoped code and tests exist.
-- Existing rows intentionally keep empresa_atendimento_id = NULL (legacy tenant).
-- Tenant roles live in the association table; the legacy usuarios.role is untouched.

CREATE TABLE IF NOT EXISTS planos_atendimento (
    id BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(80) NOT NULL UNIQUE,
    nome VARCHAR(120) NOT NULL,
    modulos JSONB NOT NULL DEFAULT '[]'::jsonb,
    limite_usuarios INTEGER,
    limite_instancias_whatsapp INTEGER,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_planos_atendimento_limite_usuarios
        CHECK (limite_usuarios IS NULL OR limite_usuarios > 0),
    CONSTRAINT ck_planos_atendimento_limite_instancias
        CHECK (limite_instancias_whatsapp IS NULL OR limite_instancias_whatsapp > 0)
);

CREATE TABLE IF NOT EXISTS empresas_atendimento (
    id BIGSERIAL PRIMARY KEY,
    documento VARCHAR(14) NOT NULL UNIQUE,
    nome VARCHAR(180) NOT NULL,
    plano_id BIGINT REFERENCES planos_atendimento(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'ativa',
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_empresas_atendimento_status
        CHECK (status IN ('ativa', 'suspensa', 'encerrada'))
);

CREATE TABLE IF NOT EXISTS usuarios_empresas_atendimento (
    id BIGSERIAL PRIMARY KEY,
    empresa_atendimento_id BIGINT NOT NULL REFERENCES empresas_atendimento(id) ON DELETE CASCADE,
    usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    papel VARCHAR(30) NOT NULL DEFAULT 'operador',
    modulos JSONB NOT NULL DEFAULT '[]'::jsonb,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_usuario_empresa_atendimento UNIQUE (empresa_atendimento_id, usuario_id),
    CONSTRAINT ck_usuario_empresa_atendimento_papel
        CHECK (papel IN ('tenant_admin', 'operador'))
);

CREATE INDEX IF NOT EXISTS ix_usuario_empresa_usuario
    ON usuarios_empresas_atendimento (usuario_id);

CREATE TABLE IF NOT EXISTS instancias_whatsapp_tenant (
    id BIGSERIAL PRIMARY KEY,
    empresa_atendimento_id BIGINT NOT NULL REFERENCES empresas_atendimento(id) ON DELETE RESTRICT,
    instance_name VARCHAR(120) NOT NULL UNIQUE,
    label VARCHAR(160) NOT NULL,
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    padrao BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_instancia_whatsapp_padrao_por_empresa
    ON instancias_whatsapp_tenant (empresa_atendimento_id)
    WHERE padrao = TRUE AND ativa = TRUE;

ALTER TABLE chamados
    ADD COLUMN IF NOT EXISTS empresa_atendimento_id BIGINT;

ALTER TABLE contatos_whatsapp
    ADD COLUMN IF NOT EXISTS empresa_atendimento_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_chamados_empresa_atendimento'
    ) THEN
        ALTER TABLE chamados
            ADD CONSTRAINT fk_chamados_empresa_atendimento
            FOREIGN KEY (empresa_atendimento_id)
            REFERENCES empresas_atendimento(id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_contatos_whatsapp_empresa_atendimento'
    ) THEN
        ALTER TABLE contatos_whatsapp
            ADD CONSTRAINT fk_contatos_whatsapp_empresa_atendimento
            FOREIGN KEY (empresa_atendimento_id)
            REFERENCES empresas_atendimento(id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_chamados_empresa_atendimento_id
    ON chamados (empresa_atendimento_id);

CREATE INDEX IF NOT EXISTS ix_contatos_whatsapp_empresa_atendimento_id
    ON contatos_whatsapp (empresa_atendimento_id);
