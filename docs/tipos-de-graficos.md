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


Nos gráficos de comparação por setor, Linhas desenha uma série independente para cada ID de departamento, com cor estável entre as telas, legenda e tabela de valores. No painel, resultado, receita e gastos são comparados por mês; no custeio financeiro, as linhas comparam pago, em aberto e folha. No RH, comparam componentes do custo ou totais líquido/custo por setor. A visão anual atribui cada mês ao setor registrado naquela folha, preservando transferências e fechamentos. Sem setor tem uma série própria; departamentos com nomes iguais são diferenciados pelo ID. Gráficos individuais de funcionário continuam restritos à pessoa selecionada.

Em séries mensais longas no celular, o gráfico inicia pelos meses mais recentes e mantém rolagem horizontal para consultar os anteriores. As cores se adaptam aos temas claro/escuro. Valores negativos são preservados e valores indisponíveis interrompem a linha, em vez de virar zeros inventados.
