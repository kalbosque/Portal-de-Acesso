# Atendimento Multiempresa: Rollout Seguro

## Estado

Documento de preparação. Existe um rascunho de migração em `db/migrations/002_tenant_foundation.draft.sql`; ele foi executado com sucesso apenas em um Postgres 15 descartável com esquema-base fictício. Nenhuma tabela, conta, permissão ou configuração de produção foi alterada.

## Objetivo

Permitir que o administrador principal cadastre empresas por CNPJ ou CPF, associe um plano e crie o administrador da empresa. Cada empresa deve acessar somente seus próprios usuários, atendimentos, contatos, arquivos e instâncias WhatsApp. O sistema atual permanece como a empresa legada até uma migração revisada.

## Papéis

- `admin`: administrador principal atual; pode administrar todas as empresas e planos.
- `tenant_admin` (nome provisório): administrador de uma empresa; gerencia somente usuários e recursos dessa empresa, dentro dos limites do plano.
- Usuários da empresa: recebem permissões específicas, sempre limitadas pelo plano.

A autorização efetiva deve ser a interseção do plano, da empresa e do usuário. Um administrador de empresa nunca pode atribuir um módulo ou limite que o plano não permite.

## Fatos verificados no código e banco

- `Usuario` já armazena nome e logo da empresa, mas não existe uma entidade de empresa nem vínculo de tenant.
- As instâncias do WhatsApp e o mapa de acesso por usuário ficam no `config.json` global.
- `Chamado` armazena `whatsapp_instance`; `ContatoWhatsApp` também pode armazená-la.
- Na auditoria de 07/10/2026, havia 89 chamados WhatsApp; 24 não tinham instância. Não devem ser atribuídos automaticamente a uma empresa nova.
- A lista de conversas e algumas rotas de histórico conferem o acesso à instância, mas há ações por ID que não fazem a mesma verificação.
- O WebSocket atual transmite eventos para todas as conexões; isso pode vazar notificações e conteúdo entre empresas.
- O ambiente Docker atual monta `backend` diretamente e executa um único serviço web. Reiniciar esse container interrompe requisições por alguns instantes.

## Etapas propostas

1. **Preparar homologação**: usar cópia isolada e anonimizada do banco; confirmar o comportamento com pelo menos duas empresas e duas instâncias WhatsApp.
2. **Adicionar estrutura, sem ativar**: revisar o rascunho `db/migrations/002_tenant_foundation.draft.sql`, aplicá-lo somente em homologação, criar tabelas de empresas e planos e vínculos opcionais. Manter os registros existentes sem alteração e deixar o modo multiempresa desligado por padrão.
3. **Fechar todos os caminhos de acesso**: aplicar o escopo da empresa em listas, buscas por ID, edição, exclusão, encaminhamento, contatos, arquivos, QR/status e WebSocket. Bloquear acesso se a empresa ou instância não puder ser determinada; não usar o fallback global para tenants novos.
4. **Painel exclusivo do administrador principal**: cadastrar empresa, identificar por CPF/CNPJ, escolher plano, criar administrador e vincular instância WhatsApp.
5. **Piloto opt-in**: habilitar uma empresa de teste sem mover dados da instalação atual; validar isolamento nos dois sentidos e limite do plano.
6. **Ativação gradual**: ampliar somente após aprovação do piloto e backup confirmado.

## Tratamento dos dados existentes

A instalação atual deve ser preservada como tenant legado. Chamados sem `whatsapp_instance` continuam no ambiente legado até serem identificados; não devem ser associados ao primeiro tenant cadastrado. A instância existente permanece vinculada apenas ao tenant legado, salvo decisão explícita posterior.

Decisão confirmada para o piloto: não importar nem migrar os chamados antigos. A empresa de teste começa vazia; seus novos usuários, instância WhatsApp, contatos e atendimentos serão criados já com o vínculo da nova empresa. A operação do legado continua sem mudança.

## Implantação e rollback

Não ativar migração nem reiniciar o serviço ativo durante o desenvolvimento. Primeiro validar em homologação. Para uma ativação realmente sem interrupção, o ambiente atual precisará de uma segunda instância web e troca gradual de tráfego (blue/green); o Compose atual usa um único serviço web, então um restart isolado não garante zero downtime.

Manter a feature flag desligada como padrão. Se qualquer teste de isolamento falhar, não habilitar tenants; reverter a versão do serviço, deixando apenas as estruturas aditivas não utilizadas. Não mover nem apagar dados na primeira implantação.

O teste descartável valida sintaxe e objetos básicos, mas não substitui uma execução contra uma cópia recente do schema real. O rascunho não deve ser aplicado ao banco ativo antes dessa validação e da atualização coordenada do código que mantém `usuarios_role_check`.

## Critérios para liberar o piloto

- Um usuário da empresa A não lista, abre, altera, apaga, encaminha nem recebe eventos da empresa B.
- QR, estado da conexão, webhook e arquivos de mídia permanecem vinculados à instância e à empresa corretas.
- Administrador principal continua vendo e administrando a instalação legada e todos os tenants.
- Administrador da empresa não consegue ultrapassar limites nem permissões do plano.
- A instalação legada mantém o comportamento atual com a feature flag desligada.
