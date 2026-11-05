# Correções da banca de revisão

A edição de dados e etapa de uma tarefa usa um único `PATCH /tasks/{id}`. Validação, consumo de material, histórico e automações pertencem à mesma transação. Qualquer erro deixa os dados e o estoque anteriores intactos; repetir a edição não repete a baixa já realizada.

O formulário de responsável seleciona o funcionário pelo ID e mostra seu número de cadastro, nome e setor. Novas atribuições por nome ambíguo retornam 409; funcionários inativos são rejeitados por ID, nome atual ou nome antigo. Um vínculo existente com funcionário inativo pode ser mantido ao editar outros campos.

Na API, `assignee_employee_id` com ID positivo seleciona um funcionário. O campo omitido mantém a resolução legada por nome. O campo explicitamente nulo com `assignee` preenchido escolhe um responsável externo: `assignee_external=1` é persistido para impedir que recuperação de vínculos ou renomeação o associe posteriormente a um funcionário homônimo. ID nulo sem nome remove o responsável. `department_id:null` remove explicitamente o setor; omitir o campo mantém o setor atual.

A recuperação de chefias antigas usa a mesma validação do cadastro: funcionário ativo, setor compatível e uma única chefia. Casos ambíguos permanecem sem vínculo para seleção explícita. Ao recuperar uma chefia única, o departamento do funcionário é sincronizado.

Redefinir as credenciais pelo administrador revoga todas as sessões daquele funcionário na mesma transação. Os demais usuários mantêm suas sessões.

A consulta de tarefas para o ponto agora usa `POST /clock/tasks` com JSON `employee_id` e `pin`. O PIN não faz parte da URL. Respostas desse caminho recebem `Cache-Control: no-store`, inclusive erros. O antigo GET foi removido; integrações devem usar POST e evitar registrar corpos com credenciais.

As migrações SQLite são aplicadas pela aplicação. Instalações PostgreSQL devem aplicar o `supabase/schema.sql` atualizado, que inclui `tasks.assignee_external`.

Regressões: `tests/test_banca_followup.py`. Verificação de interface com dados descartáveis: `scripts/qa-banca-followup.mjs`, em desenvolvimento e pacote compilado, desktop e celular.

## Terceira rodada — ponto, provisões e edição de RH

A folha limita os intervalos de ponto ao vínculo antes de classificar horas normais e extras. Registros originais permanecem intactos. A composição anual lê e pareia o ponto uma vez por consulta, reutilizando a apuração nas competências abertas. A seleção preserva o contexto semanal, entradas antigas ainda pendentes e a saída que conclui uma jornada após o fim do período.

Horistas mantêm a provisão integral de férias e respectivos encargos; a compensação de salário já previsto nas doze mensalidades aplica-se aos mensalistas. A versão de cálculo passou a `PAYROLL-2026.5`. Folhas já fechadas conservam seus snapshots.

O salvamento de RH usa o formulário que originou a solicitação. Uma resposta atrasada identifica o funcionário no aviso e não fecha nem atualiza outro formulário aberto posteriormente. Campos horistas desabilitados não enviam rascunhos inválidos; conservam os valores válidos carregados do cadastro.

Regressões: `tests/test_banca3_regressions.py`, `scripts/qa-banca3-rh.mjs` e `scripts/test-payroll-pg.mjs`.
