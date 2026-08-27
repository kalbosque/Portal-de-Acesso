-- Migration: add whatsapp_instance to chamados
ALTER TABLE chamados ADD COLUMN IF NOT EXISTS whatsapp_instance VARCHAR;
CREATE INDEX IF NOT EXISTS idx_chamados_whatsapp_instance ON chamados (whatsapp_instance);
