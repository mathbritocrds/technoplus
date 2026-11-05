# Tipos de gráficos

Os gráficos do painel, presença, tarefas, custos por setor, RH e composição anual por funcionário têm o seletor **Tipo de gráfico**. A escolha modifica somente a apresentação dos mesmos valores; não consulta outra base nem altera cálculos ou registros.

- **Gráfico atual** mantém o desenho anterior, incluindo divisões e indicadores existentes.
- **Barras** facilita comparar categorias, com eixo zero e valores negativos preservados.
- **Colunas** mostra categorias ou períodos lado a lado; séries extensas têm rolagem dentro do gráfico.
- **Linhas** está disponível em todos os seletores. Nas séries por mês/dia mantém a ordem cronológica recebida; nas comparações de categorias conecta os pontos na ordem exibida.
- **Rosca** aparece apenas em conjuntos de composição não negativos, como gastos por setor, partes do custo e etapas das tarefas. Resultados que misturam receitas, custos e lucro não oferecem rosca, pois esses valores não são partes de um mesmo total.
- **Tabela** apresenta os valores e rótulos para consulta direta. Linhas também permitem abrir os valores abaixo do desenho.

A escolha é salva por gráfico na sessão do navegador, separando os caminhos da empresa e da demonstração. Ao trocar o funcionário ou o período, o tipo continua selecionado quando for compatível com os novos valores. Dados vazios ou zerados não geram divisões por zero; rótulos são tratados como texto.

A implementação fica em `app/static/charts.js` e `charts.css`, sem dependências externas ou requisições para serviços de gráficos. Os assets entram no build e no cache offline atualizado. Testes: `scripts/chart-types.test.mjs` e `scripts/qa-chart-types.mjs`, com fluxo real em desenvolvimento/compilado, desktop/celular, preservação de dados, preferências, tema escuro e ausência de erros de console.
