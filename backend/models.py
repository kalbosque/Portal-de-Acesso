from datetime import datetime
from typing import Optional, List
from sqlmodel import Field, SQLModel, create_engine, Session, select, Relationship

class Usuario(SQLModel, table=True):
    __tablename__ = "usuarios"
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: Optional[str]
    email: Optional[str] = Field(unique=True)
    username: str = Field(unique=True)
    password_hash: str
    role: str = Field(default="operator")
    status_conta: str = Field(default="ativo")
    permissoes: str = Field(default="[]")
    empresa_nome: Optional[str] = None
    empresa_logo_url: Optional[str] = None
    senha_temp: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

class Impressora(SQLModel, table=True):
    __tablename__ = "impressoras"
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    ip: str = Field(unique=True)
    status: str = Field(default="Desconhecido")
    total_fisico_paginas: int = Field(default=0)
    ultima_verificacao: Optional[datetime] = None
    modelo: Optional[str] = None
    localizacao: Optional[str] = None

class Impressao(SQLModel, table=True):
    __tablename__ = "impressoes"
    id: Optional[int] = Field(default=None, primary_key=True)
    impressora_id: Optional[int] = Field(default=None, foreign_key="impressoras.id", index=True)
    usuario: str = Field(index=True)
    maquina: str
    documento: str
    tipo_documento: str = Field(default="Sistema")
    paginas: int
    tipo_impressao: str = Field(default="P&B")
    preco_unitario: float
    valor_total: float
    ip_maquina: Optional[str]
    data_hora: datetime = Field(default_factory=datetime.now, index=True)

class Licenca(SQLModel, table=True):
    __tablename__ = "licenciamento"
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True)
    data_ativacao: datetime = Field(default_factory=datetime.now)
    data_expiracao: datetime
    hardware_id: str
    status: str = Field(default="ativo") # ativo, expirado

class EquipamentoTI(SQLModel, table=True):
    __tablename__ = "equipamentos_ti"
    id: Optional[int] = Field(default=None, primary_key=True)
    colaborador: str = Field(index=True)
    nome_computador: Optional[str] = None
    setor: str = Field(default="Não Informado")
    tipo_equipamento: str = Field(default="Computador") # Desktop, Notebook, Celular, etc
    marca: Optional[str] = None
    modelo: Optional[str] = None
    modelo_monitor: Optional[str] = None
    quantidade_monitores: Optional[int] = None
    processador: Optional[str] = None
    memoria_ram: Optional[str] = None
    sistema_operacional: Optional[str] = None
    armazenamento: Optional[str] = None
    patrimonio: Optional[str] = None
    observacoes: Optional[str] = None
    data_registro: datetime = Field(default_factory=datetime.now)

class TipoProblema(SQLModel, table=True):
    __tablename__ = "tipos_problemas"
    id: Optional[int] = Field(default=None, primary_key=True)
    icone: str = Field(default="🛠️")
    label: str
    titulo_padrao: str = Field(default="")
    categoria: str = Field(default="Outros")
    prioridade_padrao: str = Field(default="Media")
    sla_horas: int = Field(default=24)

class Chamado(SQLModel, table=True):
    __tablename__ = "chamados"
    id: Optional[int] = Field(default=None, primary_key=True)
    usuario: str = Field(index=True)
    titulo: str
    categoria: str = Field(default="Outros")
    equipamento_id: Optional[str] = None
    descricao: str
    anexo_url: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    unread_admin: int = Field(default=0)
    unread_user: int = Field(default=0)
    prioridade: str = Field(default="Media") # "Baixa", "Media", "Alta"
    status: str = Field(default="Aberto", index=True) # "Aberto", "Em Atendimento", "Resolvido"
    data_abertura: datetime = Field(default_factory=datetime.now, index=True)
    vencimento_sla: Optional[datetime] = None
    data_resolucao: Optional[datetime] = None
    nota_tecnica: Optional[str] = None
    avaliacao_estrelas: Optional[int] = None
    avaliacao_comentario: Optional[str] = None
    whatsapp_cliente: Optional[str] = Field(default=None, index=True)
    whatsapp_instance: Optional[str] = Field(default=None, index=True)
    whatsapp_typing_until: Optional[datetime] = None
    whatsapp_typing_media: bool = Field(default=False)
    origem: str = Field(default="Web", index=True)
    assigned_user: Optional[str] = Field(default=None, index=True)
    visivel_suporte: bool = Field(default=True, index=True)
    
    interacoes: List["ChamadoInteracao"] = Relationship(back_populates="chamado")

class ChamadoInteracao(SQLModel, table=True):
    __tablename__ = "chamados_interacoes"
    id: Optional[int] = Field(default=None, primary_key=True)
    chamado_id: int = Field(foreign_key="chamados.id")
    usuario: str
    mensagem: str
    responde_a_id: Optional[int] = None
    responde_a_usuario: Optional[str] = None
    responde_a_texto: Optional[str] = None
    whatsapp_message_id: Optional[str] = None
    whatsapp_remote_jid: Optional[str] = None
    reacao: Optional[str] = None
    favorito: bool = Field(default=False, index=True)
    whatsapp_status: str = Field(default="sent")
    data_hora: datetime = Field(default_factory=datetime.now)
    
    chamado: Chamado = Relationship(back_populates="interacoes")


class ContatoWhatsApp(SQLModel, table=True):
    __tablename__ = "contatos_whatsapp"
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    numero: str = Field(index=True)
    empresa: Optional[str] = None
    observacao: Optional[str] = None
    status_interno: str = Field(default="Normal", index=True)
    whatsapp_instance: Optional[str] = None
    data_cadastro: datetime = Field(default_factory=datetime.now)

class StatusMaquina(SQLModel, table=True):
    __tablename__ = "status_maquinas"
    ip: str = Field(primary_key=True)
    nome: str
    status: str = Field(default="Online")
    windows_user: str = Field(default="Desconhecido")
    timestamp: datetime = Field(default_factory=datetime.now)
    versao_agente: str = Field(default="2.0")
    alerta_enviado: bool = Field(default=False)

class AvisoCarrossel(SQLModel, table=True):
    __tablename__ = "avisos_carrossel"
    id: Optional[int] = Field(default=None, primary_key=True)
    icone: str = Field(default="📣")
    titulo: str
    mensagem: str
    cor: str = Field(default="indigo")  # indigo, amber, emerald, rose
    ativo: bool = Field(default=True)
    criado_por: str = Field(default="admin")
    criado_em: datetime = Field(default_factory=datetime.now)

class MarmitaCardapio(SQLModel, table=True):
    __tablename__ = "marmita_cardapio"
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: str = Field(index=True)
    descricao: Optional[str] = None
    horario_limite: Optional[str] = None
    ativo: bool = Field(default=True)
    data_referencia: datetime = Field(default_factory=datetime.now, index=True)
    criado_por: str = Field(default="admin")
    criado_em: datetime = Field(default_factory=datetime.now)

class MarmitaPedido(SQLModel, table=True):
    __tablename__ = "marmita_pedidos"
    id: Optional[int] = Field(default=None, primary_key=True)
    cardapio_id: int = Field(foreign_key="marmita_cardapio.id", index=True)
    colaborador: str = Field(index=True)
    setor: Optional[str] = Field(default=None, index=True)
    quantidade: int = Field(default=1)
    observacao: Optional[str] = None
    status: str = Field(default="Pendente")
    data_pedido: datetime = Field(default_factory=datetime.now, index=True)
    criado_por: str = Field(default="admin")
    entregue_em: Optional[datetime] = None

class CofreSenha(SQLModel, table=True):
    __tablename__ = "cofre_senhas"
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: str
    categoria: str = Field(default="E-mail")
    setor: str = Field(default="TI")
    login_email: str
    senha_cifrada: str
    url: Optional[str] = None
    observacoes: Optional[str] = None
    criado_por: str = Field(default="admin")
    criado_em: datetime = Field(default_factory=datetime.now)
    atualizado_em: datetime = Field(default_factory=datetime.now)
