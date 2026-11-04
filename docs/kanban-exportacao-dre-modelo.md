# Quadros de gestão e exportação DRE em Excel

## Uso

Departamentos passa a apresentar três colunas: **Sem chefia**, **Formando equipe** e **Equipe formada**. A classificação acompanha os vínculos reais: funcionário ativo designado como chefe e quantidade de funcionários ativos do setor. Os cartões permitem consultar a equipe, editar nome/chefia e excluir pelo fluxo existente. O cadastro fica em **Novo departamento**. A busca local aceita nomes sem acentos.

Integrações usa **A configurar**, **Ativas** e **Pausadas**. São estados do cadastro; não representam um teste de conexão com o serviço externo. Integrações CSV não exigem endereço. As ações anteriores de ativação, pausa, cadastro e exclusão continuam disponíveis.

A Central de aprovações separa tarefas, férias, folgas e atestados. Gestores consultam o escopo autorizado pelo backend; atestados continuam exclusivos da administração. Após uma decisão, o cartão sai da fila de pendências. Não há arrastar cartões para aprovar nem novos estados gravados no banco.

Os quadros reutilizam a paleta dos dois temas. No celular, cada coluna mantém largura legível e o quadro permite rolagem horizontal própria. Controles usam os alvos de toque existentes. O painel, funcionários e demais tabelas continuam com suas apresentações anteriores.

Em **Financeiro → DRE e fluxo**, o botão **Exportar Excel (modelo)** baixa o modelo fornecido pelo usuário, preenchido com os dados do período e setor selecionados. Selecione um ano ou intervalo de meses dentro do mesmo ano; para anos diferentes, exporte um arquivo por ano. Meses fora do intervalo ficam zerados, sem dados de exemplo.

## Conteúdo do arquivo

- Capa, DRE anual e doze abas mensais mantêm a estrutura e as imagens do modelo.
- Os lançamentos mensais mostram competência, descrição, receita/despesa, valor, categoria SIGI, setor, origem e resultado acumulado.
- **Gastos por setor** contém meses, total e participação no total de gastos, além de uma tabela por setor e categoria. Sem vínculo aparece como **Sem setor**. Os percentuais ficam em branco quando não há gastos.
- O arquivo contém fórmulas e valores calculados para leitores que não recalculam ao abrir. Alterações nos valores dos lançamentos recalculam os resultados e a composição por setor. O intervalo exportado comporta mais linhas que as 790 linhas originais do modelo.

A base é **competência**, a mesma da DRE integrada: contas, folhas efetivamente fechadas, seus complementos e lançamentos importados. Não são saldos bancários, nem pagamentos recebidos/realizados. A folha considera o custo por competência e não duplica sua conta de pagamento. O filtro de categoria é exclusivo do detalhamento CSV/web; a demonstração e o Excel mantêm todas as categorias no período/setor para preservar os subtotais.

SIGI não distingue contas contábeis detalhadas como água, aluguel e frete nas seis categorias operacionais. Por isso, a exportação agrega em receitas operacionais, impostos/deduções, custos diretos, despesas operacionais, pessoal/encargos/provisões e despesas financeiras, sem inferir uma classificação pelo texto. As rubricas originais não usadas permanecem zeradas. Foram corrigidos os vínculos de junho, o custo direto antes vazio e o sinal do resultado financeiro na soma do lucro líquido. A DRE CPC 51 web/CSV continua disponível separadamente.

## Implementação

`GET /finance/dre/modelo.xlsx?start=YYYY-MM&end=YYYY-MM&department_id=ID` exige administrador ou gestor e usa as mesmas restrições de departamento da consulta DRE. O servidor responde com XLSX, nome de arquivo do período e `Cache-Control: private, no-store`. Operadores não podem exportar. Não há alteração de schema ou migração.

`app/dre_xlsx.py` preenche o pacote OOXML com biblioteca padrão Python. O modelo original e o layout adicional de setores ficam em `app/templates` e são incluídos pelo build atual no Render. O layout adicional foi preparado com artifact-tool; esse recurso não é necessário no servidor. O código de autoria está em `scripts/author-dre-sector-layout.mjs` para manutenção do asset em um ambiente com artifact-tool. As imagens e relações de desenho originais são preservadas. Textos de usuário são gravados como strings literais, nunca como fórmulas. Setores com nomes iguais recebem seu ID no rótulo e critérios de soma escapam caracteres curinga.

`management-boards.js` registra as três apresentações no mapa `TAB`, utilizando as mesmas APIs, permissões e ações de negócio. O build valida o script e o service worker renova o cache do shell.

## Validação

`python -m pytest -q`, `npm run build`, `npm run typecheck`, `node scripts/qa-kanban.mjs`, `node scripts/qa-density.mjs` e `node scripts/qa-business.mjs`. Os testes de navegador usam banco temporário e execução em desenvolvimento e pacote de produção, com telas desktop e celular. O teste XLSX verifica escopo, totais, categorias, dados literais, preservação das imagens, período vazio e mais de 790 lançamentos. A planilha também foi recalculada e renderizada para conferir apresentação, percentuais e atualização das fórmulas após editar um valor de entrada.
