[readme_md.md](https://github.com/user-attachments/files/34577733/readme_md.md)
# SIGI Gestão

Sistema integrado de gestão empresarial para controle de tarefas, matéria-prima, folha de pagamento, contabilidade e ponto eletrônico com validação por GPS e IP.

## 📌 Informações Gerais

- **Nome do Projeto:** SIGI Gestão (Sistema Integrado de Gestão)
- **Equipe:** Techno+
- **Curso:** Técnico em Informática / Desenvolvimento de Sistemas
- **Instituição:** Instituição de Ensino
- **Ano/Semestre:** 2026 / 1º Semestre
- **Professor Orientador:** Orientador do Projeto
- **Cliente/Setor Solicitante:** Gestão Operacional, Recursos Humanos e Departamento Financeiro

## 🎯 Objetivo do Projeto

Desenvolver uma solução web integrada para centralizar a gestão operacional e financeira de empresas, permitindo o acompanhamento de tarefas (Kanban/Tabela), automação de custeio por projeto, controle de estoque de matéria-prima, cálculo da folha de pagamento, registro de ponto com geolocalização e emissão de relatórios contábeis em partidas dobradas.

## 👥 Público-Alvo

- **Administradores:** Liderança executiva com controle total sobre configurações, usuários, finanças e auditoria.
- **Gestores:** Responsáveis por departamentos encarregados do acompanhamento de quadros, aprovação de tarefas e gestão de espaços.
- **Operadores:** Colaboradores operacionais que visualizam e atualizam quadros de trabalho e tarefas.
- **Funcionários:** Colaboradores da empresa que realizam marcações de ponto eletrônico e acessam o canal de comunicação interna.

## 🧩 Problema a Ser Resolvido

A descentralização das informações operacionais e financeiras em planilhas ou sistemas isolados gera inconsistência de dados, falta de rastreabilidade do custo real por tarefa, atrasos na reposição de insumos e dificuldades no cálculo exato da folha e demonstrações contábeis (DRE e Balanço).

## 💡 Solução Proposta

Um sistema web completo, modular e responsivo (com suporte offline/PWA) que conecta o registro de ponto do colaborador diretamente ao custeio de mão de obra das tarefas, automatiza a baixa de estoques, gera DRE sintético/analítico em tempo real e permite a contabilidade em partidas dobradas com auditoria completa das operações.

## ⚙️ Funcionalidades do Sistema

### Funcionalidades Principais

- **Autenticação e Segurança:** Login por usuário ou e-mail, autenticação de dois fatores (2FA/TOTP), controle de acesso baseado em funções (RBAC) e auditoria de ações de escrita da API.
- **Gestão de Quadros e Tarefas:** Visualização em Kanban e Tabela, anexos (até 6 MB), checklists com progresso, tags, prazos e regras de automação por custo/progresso.
- **Ponto Eletrônico e RH:** Marcação de ponto com validação por GPS e restrição opcional por faixa de IP (CIDR), apuração de horas extras e fechamento de folha de pagamento.
- **Gestão de Matéria-Prima e Custeio:** Cadastro de estoque com limite mínimo, baixa automática de insumos ao iniciar tarefas e apuração de mão de obra via ponto.
- **Módulo Financeiro e Contábil:** DRE sintético/analítico (até 15 níveis), Balanço Patrimonial, Balancete, lançamentos em partidas dobradas, conciliação e exportação em CSV.
- **Reserva de Espaços:** Calendário compartilhado para agendamento de salas e bancadas com bloqueio de conflitos de horários.
- **Comunicação e Notificações:** Canal de avisos gerais, mensagens privadas entre gestão e funcionários, além de alertas por E-mail (SMTP) e WhatsApp Cloud API.
- **Suporte Offline (PWA) e WebSocket:** Sincronização offline para tarefas/materiais e atualizações em tempo real para painéis e quadros.

## 🛠️ Tecnologias Utilizadas

- **Front-end:** HTML5, CSS3, JavaScript / React (Módulo Contábil), Tailwind CSS, PWA (IndexedDB e Service Workers)
- **Back-end:** Python, FastAPI, Uvicorn
- **Banco de Dados:** SQLite (`data/flux.db`) para desenvolvimento local; PostgreSQL / Supabase para produção (com Row Level Security - RLS)
- **Versionamento & Ferramentas:** Git, GitHub, Pytest, Node.js / npm

## 🗂️ Estrutura do Projeto

```text
/sigi-gestao
│
├── app/                  # Código-fonte principal da aplicação FastAPI
├── docs/                 # Documentação técnica e arquitetural dos módulos
├── scripts/              # Scripts de migração de banco e testes em PG
├── supabase/             # Schemas SQL e políticas de RLS para PostgreSQL
├── tests/                # Testes automatizados (pytest)
├── requirements.txt      # Dependências em Python (produção)
├── requirements-dev.txt  # Dependências em Python (desenvolvimento)
├── package.json          # Scripts e dependências de frontend / React
└── README.md             # Documentação principal do repositório
```

## 🧪 Requisitos Funcionais

- **RF01 – Autenticação:** O sistema deve permitir o login de administradores, gestores, operadores e funcionários com senha com hash seguro e suporte opcional a 2FA.
- **RF02 – Gestão de Tarefas:** O sistema deve permitir criar, editar, mover e aprovar tarefas nos modos Kanban e Tabela.
- **RF03 – Ponto Eletrônico:** O sistema deve registrar marcações de entrada e saída validando as coordenadas de GPS do cliente e a faixa de IP configurada.
- **RF04 – Baixa de Matéria-Prima:** O sistema deve realizar a baixa automática do saldo de matéria-prima associada ao card ao transicioná-lo da coluna "A fazer".
- **RF05 – Cálculo de Custeio:** O sistema deve calcular o custo de mão de obra da tarefa multiplicando o tempo registrado no ponto pela taxa horária do colaborador.
- **RF06 – Demonstrações Financeiras:** O sistema deve gerar DRE sintético/analítico, Balanço Patrimonial e Balancete por período e setor.
- **RF07 – Agendamento de Espaços:** O sistema deve permitir a reserva de salas e recursos impedindo agendamentos em horários conflitantes.

## 🚫 Requisitos Não Funcionais

- **RNF01 – Acessibilidade:** O sistema deve ser acessível via navegadores modernos de desktop e dispositivos móveis.
- **RNF02 – Desempenho:** O painel principal e as métricas operacionais devem atualizar automaticamente a cada 30 segundos ou via eventos WebSocket.
- **RNF03 – Segurança:** O sistema não deve expor credenciais no código, deve aplicar limite de tentativas no ponto (anti-brute force) e sanitizar exportações CSV contra fórmula injection.
- **RNF04 – Disponibilidade Offline:** A interface de quadros e estoque deve manter suporte de leitura e enfileiramento de edições via PWA (IndexedDB) em caso de queda de conexão.

## 📅 Cronograma do Projeto

| Etapa | Descrição | Responsável | Data |
| :--- | :--- | :--- | :--- |
| 1 | Levantamento de Requisitos e Regras de Negócio | Equipe SIGI | Concluído |
| 2 | Modelagem de Banco de Dados e Arquitetura | Equipe SIGI | Concluído |
| 3 | Desenvolvimento do Core (FastAPI, SQLite, Kanban) | Equipe SIGI | Concluído |
| 4 | Módulos de Ponto GPS, DRE, RH e Contabilidade | Equipe SIGI | Concluído |
| 5 | Testes Automatizados, Migração Supabase e Ajustes | Equipe SIGI | Concluído |

## 🧑‍💻 Integrantes da Equipe

| Nome | Função | Responsabilidade |
| :--- | :--- | :--- |
| **Desenvolvedor Lead** | Desenvolvedor Full-Stack | Arquitetura FastAPI, API REST, WebSocket e Regras de Custeio |
| **Engenheiro de Dados** | DB Admin / Backend | Modelagem PostgreSQL/Supabase, RLS e Scripts de Migração |
| **Designer / Frontend** | UI/UX & Frontend | Interfaces Kanban, PWA offline, Console React Contábil |
| **QA & Documentação** | Testador & Documentador | Cobertura com Pytest, Validação Contábil e Redação de Docs |

## 🔐 Controle de Acesso

- **Administrador:** Acesso irrestrito a todos os módulos, configurações de segurança (2FA, IP/CIDR), permissões de usuários e auditoria.
- **Gestor:** Leitura e edição de quadros e tarefas do próprio setor, reserva de espaços em nome do departamento e aprovação de entregas.
- **Operador:** Visualização e atualização de progresso de quadros e checklists.
- **Funcionário:** Acesso exclusivo ao terminal de ponto eletrônico, mensagens da equipe e consulta de comprovantes.

## 📷 Protótipos / Telas

Consulte os guias visuais e documentos de arquitetura das telas nos links:
- [Documentação do Módulo RH e Eventos](docs/modulos-rh-financeiro-eventos.md)
- [Documentação da Arquitetura Contábil](docs/contabilidade-cpc51-arquitetura.md)
- [Documentação de Controles Corporativos](docs/controles-corporativos.md)

## 📦 Como Executar o Projeto

### 1. Clonar e preparar o ambiente

```bash
git clone https://github.com/seu-usuario/sigi-gestao.git
cd sigi-gestao

python -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Rodar a aplicação

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Acesse a aplicação no seu navegador em `http://localhost:8080`. No primeiro acesso, selecione **Criar conta da empresa** para cadastrar o usuário Administrador inicial.

### 3. Executar Testes Automatizados

```bash
pip install -r requirements-dev.txt
pytest -q
```
