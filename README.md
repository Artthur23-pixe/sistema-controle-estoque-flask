Sistema de Controle de Estoque com Flask
Aplicação web completa para gestão de estoque, focada no fluxo de trabalho de equipas de TI que precisam de rastrear a retirada, distribuição e devolução de equipamentos.


🚀 Funcionalidades Principais
Dashboard Interativo: Visão geral do status do estoque, com contadores de produtos distintos, total de itens e alertas para estoque baixo.

Gestão de Produtos: CRUD completo (Criar, Ler, Atualizar, Excluir) para os produtos, com suporte para categorias e filtro de visualização.

Fluxo de Trabalho de Movimentação em 2 Etapas:

1. Retirada: Registo de saídas de múltiplos itens do estoque central para um destino geral (ex: cidade), com um status "Pendente".

2. Distribuição: Página dedicada para selecionar uma retirada pendente e detalhar para onde cada item foi efetivamente entregue (ex: Unidades de Saúde), com a opção de registar sobras que voltam automaticamente para o estoque.

3. Devolução Direta: Página para devoluções simples que não estão ligadas a uma retirada.

Relatórios Profissionais em PDF:

Geração de Termos de Recebimento para cada retirada, com cabeçalho personalizado e campo de assinatura.

Exportação de Relatórios de Histórico (Distribuições, Devoluções) para PDF, mantendo os filtros de busca aplicados.

Busca e Paginação: Todos os históricos possuem filtros de busca avançados e paginação para facilitar a navegação.

Interface Moderna: Tema escuro e design responsivo construído com Bootstrap 5.

🛠️ Tecnologias Utilizadas
Backend: Python 3, Flask, Flask-SQLAlchemy

Base de Dados: SQLite

Frontend: HTML5, CSS3, JavaScript, Bootstrap 5

Geração de PDF: WeasyPrint
