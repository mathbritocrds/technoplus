# Controles de fechamento, jornada e obrigações externas

Esta versão corrige os fluxos reproduzidos na auditoria corporativa. A folha gerencial, as contas financeiras, o razão contábil e as evidências externas têm funções distintas. Um fechamento interno não confirma pagamento bancário nem entrega de obrigação governamental.

## Jornada e competência

`app/timekeeping.py` pareia as marcações aceitas em ordem cronológica, considerando os horários efetivos após ajustes. A entrada e sua saída podem estar em dias, meses ou anos diferentes. A escolha de entrada/saída na coleta usa a última marcação aceita do funcionário, sem reiniciar a sequência à meia-noite.

O par é dividido na meia-noite local da empresa. Cada parcela pertence ao seu dia e à respectiva competência. Assim, um turno das 22h de 31/01 às 6h de 01/02 atribui duas horas a janeiro e seis a fevereiro. A apuração semanal considera segunda a domingo, inclusive os dias da mesma semana que estejam fora do mês consultado.

O limite diário acompanha a jornada iniciada na entrada e não reinicia à meia-noite: uma jornada das 19h às 5h tem dez horas trabalhadas e, com limite diário de oito, duas extras. As horas acima do limite diário ou semanal são classificadas como extras sem dupla contagem. Os valores padrão são oito horas diárias, 44 semanais, divisor mensal 220 e multiplicador de hora extra 1,5. Esses valores são parâmetros; não determinam o enquadramento de cada contrato. Em **Segurança → Política trabalhista e revisão fiscal**, o responsável registra o regime e a convenção revisados e configura os parâmetros aplicáveis. Contratos com escalas, banco de horas, adicionais noturnos ou regras especiais que não sejam representadas pelos parâmetros exigem apuração no processo externo registrado.

O espelho, o painel, os indicadores operacionais e a folha usam a mesma apuração de horários efetivos. Marcações sem par ou com sequência inválida permanecem identificadas como pendências. O fechamento e a complementação da folha exigem sua regularização; não convertem uma entrada aberta em zero horas silenciosamente.

## Férias e vínculo

O cálculo de aquisição para no desligamento. A concessão exige vínculo ativo e todos os dias de gozo dentro do contrato. Um período aquisitivo posterior ao desligamento não gera saldo novo.

A prévia informa remuneração bruta e prazo indicativo de pagamento. Para registrar o gozo, o administrador deve confirmar a concordância do funcionário. A trilha de auditoria conserva o período solicitado, a concordância e o calendário utilizado.

Para o fracionamento ordinário, o sistema admite até três períodos no ciclo, com períodos menores de pelo menos cinco dias e reserva de um período de quatorze dias quando o direito anual comporta essa duração. Direitos reduzidos, como doze dias, podem ser gozados integralmente. Saldo e sobreposição também são verificados. Exceções contratuais ou legais não devem ser simuladas com datas ou consentimento fictícios.

Os dias de descanso semanal e os feriados precisam ser cadastrados em **Segurança → Política trabalhista e revisão fiscal**. O início nos dois dias que antecedem um descanso ou feriado cadastrado é recusado. O aplicativo não deduz feriados municipais nem a escala individual a partir do endereço da empresa.

Registrar gozo continua sendo diferente de liquidar férias: retenções, adiantamentos e pagamentos são apurados no processo de folha oficial externo e recebem evidência própria.

## Fechamento e folha complementar

O fechamento exige funcionários elegíveis, admissão informada, líquidos não negativos e ponto regularizado. Competência futura, folha vazia e marcações pendentes são recusadas. Repetir um fechamento concluído retorna o mesmo resultado, sem gerar salários duplicados.

Os snapshots originais de `payroll_runs` e `payroll_items` permanecem preservados. Uma mudança posterior não reescreve silenciosamente o salário já fechado. Em **Folha → Complementação da folha e obrigações**, o administrador informa competência, data contábil em período aberto, referência única e justificativa.

A complementação recalcula os dados atuais e compara com a última posição efetiva, que inclui complementos anteriores. O registro mantém os snapshots recalculados e as diferenças por funcionário. Diferenças positivas geram obrigações adicionais; diferenças negativas geram valores a compensar, sem apagar um pagamento anterior. As partidas de custo e obrigação são ajustadas pelo valor da diferença. Repetir a mesma referência é idempotente; referência reutilizada com outro conteúdo é recusada.

A consulta de folha fechada e os relatórios passam a apresentar a posição efetiva com complementos, mantendo o fechamento original disponível como evidência. O FGTS acumulado também incorpora as diferenças. Se um funcionário da folha original desaparecer do recálculo, o complemento é bloqueado para permitir regularizar o vínculo antes de alterar obrigações.

## Obrigações financeiras e processo oficial externo

**Folha → Complementação da folha e obrigações** apresenta os valores apurados, gerados e baixados por competência. A geração de obrigações cria somente as diferenças ainda não geradas para INSS, IRRF, FGTS, encargos patronais e demais benefícios. O vencimento deve ser conferido e informado pelo responsável; o aplicativo não presume uma data legal única para regimes distintos. A geração não repete a despesa já reconhecida na folha.

A empresa deve cadastrar o escritório ou profissional responsável pelo processo externo, o regime tributário revisado e a convenção coletiva aplicável. Rescisão, liquidação e retenções específicas de férias e 13º, múltiplos vínculos, afastamentos e transmissão ao eSocial/FGTS Digital continuam dependendo desse processo oficial externo. O software não executa essas transmissões nem transferências bancárias.

Depois da execução externa, registre o tipo de procedimento, a competência, uma referência ou protocolo único, a localização da evidência e a justificativa. Quando um procedimento não se aplicar àquela competência, registre a razão concreta de não aplicação em vez de afirmar que foi transmitido. Os registros são imutáveis e identificam autor e data; representam informação prestada pelo responsável, não uma confirmação obtida de um serviço governamental.

O controle da competência expõe essas evidências e o responsável cadastrado. Ele não transforma automaticamente uma pasta completa de registros em certificação fiscal ou trabalhista.

## Conciliação bancária e encerramento contábil

Em **Financeiro → Conciliação bancária e fechamento contábil**, importe um extrato CSV com o cabeçalho:

```csv
reference;date;amount;description
extrato-2026-11-001;2026-11-05;-2751.40;Pagamento de salário
```

A data usa `AAAA-MM-DD`; valores usam ponto decimal, sinal negativo para saída e positivo para entrada. A combinação de identificação da conta e referência é única. Uma reimportação idêntica não duplica linhas; conteúdo diferente com a mesma referência é recusado. Não inclua senha bancária no arquivo.

A conciliação associa explicitamente uma linha ao pagamento interno. O valor em centavos e o sentido precisam coincidir; diferença de data superior a dez dias é recusada. Uma linha ou pagamento não pode ser associado a registros diferentes. A associação conserva a justificativa e o autor.

O encerramento contábil da competência exige balancete equilibrado e ausência de linhas importadas ou pagamentos do mês sem conciliação. Após encerrar, novas partidas, estornos e integrações para aquele período são bloqueados. A reabertura exige justificativa e é auditada. Quando apropriado, um complemento pode ser escriturado em período aberto, sem alterar as partidas do período encerrado.

A conciliação atual é por pagamento individual. Tarifas, lotes, pagamentos parciais e compensações que não correspondam a essa relação precisam ser regularizados pelo financeiro antes da associação. Importar extrato não baixa contas automaticamente.

## Tabelas fiscais e transição de ano

A tabela incorporada cobre 2026. Não há tabela de 2027 presumida nem cópia automática das alíquotas de 2026 para anos futuros. Uma competência sem tabela aprovada é recusada.

O administrador pode registrar uma nova versão em **Segurança → Política trabalhista e revisão fiscal**, informando ano, versão, URL HTTPS da fonte oficial, tabela completa em JSON e justificativa. O registro valida faixas, limites, deduções e todos os parâmetros de redução do IRRF. A URL e a aprovação identificam a fonte e o responsável; a aplicação não verifica automaticamente o conteúdo da publicação externa.

A versão é preservada com autor e data. Reutilizar a mesma versão com valores diferentes é recusado. Fechamentos anteriores mantêm a versão originalmente usada; eventual correção deve seguir o procedimento de complemento. Antes do primeiro fechamento de um novo ano, o responsável fiscal deve conferir as tabelas publicadas e comparar os casos-limite com a folha oficial.

## Homologação antes do uso operacional

A liberação precisa ser feita com o responsável de RH, o responsável contábil/fiscal e o administrador da instalação, usando o regime e a convenção registrados para a empresa. Os cenários concretos desta alteração são:

| Responsável | Conferência e resultado esperado |
| --- | --- |
| RH | Turnos noturnos, virada de competência e semana de 48 horas: total preservado, distribuição por dia correta e extras segundo os parâmetros aprovados. |
| RH | Entrada sem saída: fechamento recusado; após regularizar, folha calculada sem perda de horas. |
| RH | Férias após desligamento, fragmentação inválida, falta de concordância ou início anterior a descanso/feriado cadastrado: registro recusado. |
| RH e financeiro | Fechar uma competência, corrigir o dado de origem e registrar complemento: diferença liquidável sem reescrever o snapshot nem duplicar obrigações em nova tentativa. |
| Contabilidade | Excluir setor com histórico: operação recusada; criar outro setor não herda escrituração anterior. |
| Financeiro | Importar extrato duas vezes, conciliar pagamento e tentar associação de valor ou sentido divergente: sem duplicação e com divergências recusadas. |
| Contabilidade | Encerrar competência conciliada e tentar lançamento retroativo: bloqueio; reabertura motivada permite a correção e conserva auditoria. |
| Responsável fiscal | Conferir tabela aprovada e valores nos limites de INSS/IRRF contra a fonte oficial e a folha externa, incluindo a transição anual. |
| Administrador | Gestor de um setor não recebe conversas privadas de funcionários de outro setor ao delegar acesso ao módulo de mensagens. |

Os testes automatizados cobrem as regressões reproduzidas; a homologação com dados representativos da empresa confirma os parâmetros contratuais e os procedimentos externos. Referências de documentos e evidências devem apontar para armazenamento controlado pela empresa, evitando expor documentos pessoais em links públicos.

## Referência técnica

- `app/timekeeping.py`: pareamento, distribuição de horas e limites diários/semanais.
- `app/business.py` e `app/payroll.py`: folha em lote, férias, fechamento e cálculo com parâmetros.
- `app/corporate.py`: complementos, obrigações, evidências externas, política, tabelas e conciliação.
- `app/corporate_schema.py`: registros administrativos e proteções de imutabilidade.
- `app/financial_controls.py`: verificação de período contábil aberto.
- `app/tax_registry.py`: validação e aprovação das versões fiscais.
- `app/static/corporate-controls.js`: formulários administrativos na interface existente.

Complementos de funcionários já incluídos conservam o departamento da competência original, mesmo após uma transferência. A DRE operacional apresenta o complemento na competência da folha; o razão registra a data contábil escolhida para o ajuste. Compare os fundamentos e o intervalo completo ao reconciliar uma correção de período anterior.

## Demonstração e login

O login não pré-preenche senha nem divulga identidades de administradores pela consulta pública de configuração. A carga de dados demonstrativos recebida em outra alteração do repositório só executa com `SIGI_DEMO_MODE=1`, numa instalação sem dados operacionais. Ela nunca deve ser habilitada no banco de produção. A localização padrão demonstrativa também depende desse modo; a empresa deve configurar sua sede real antes de registrar ponto.

## Acesso à empresa de demonstração preenchida

Na tela de login, **Explorar empresa de demonstração** abre `/demo/` e entra automaticamente numa conta administrativa fictícia, sem senha compartilhada com a empresa real. O ambiente vem com seis funcionários, salários, benefícios, dependentes, férias, bonificações, ponto encadeado, tarefas, estoque, produtos, departamentos, espaços, contas financeiras e escrituração. Quando há tabela fiscal conhecida para o mês anterior, uma folha fechada também é criada.

A demonstração usa um banco SQLite separado, inclusive quando a empresa real usa PostgreSQL. Seus tokens, fila offline e eventos são separados; uma sessão de demonstração não autentica na empresa real. E-mails e WhatsApp externos são desativados. As edições são permitidas e ficam somente na demonstração compartilhada. Não cadastre informações reais ali. O cabeçalho identifica os dados fictícios e permite voltar ao acesso normal. `DEMO_DB_PATH`, quando configurado, precisa apontar para um arquivo diferente de `DB_PATH`.

## Revisão de isolamento e configuração

A identificação de produção ou demonstração vem do servidor, inclusive quando o aplicativo é publicado sob um prefixo de endereço ou acessado por uma URL codificada. O navegador utiliza esse contexto para chamadas, exportações e sessões; sem contexto válido, não consulta dados. Sessões e caches mantêm separados o ambiente e o prefixo da instalação.

Tentativas de login e PIN são limitadas por ambiente, origem e identidade. E-mail e nome de usuário da mesma conta compartilham o limite. Falhas na demonstração não bloqueiam a empresa real. Desativar 2FA exige senha atual e código do autenticador; cinco tentativas incorretas provocam bloqueio temporário. Os limitadores permanecem locais ao processo, conforme a limitação de implantação já documentada.

Antes de preparar o banco demonstrativo, o servidor o inspeciona em leitura. Um arquivo desconhecido, marcador inválido ou banco substituído é recusado sem alterar esquema ou registros. As tabelas fiscais geram os metadados de apresentação do INSS a partir das faixas progressivas, inclusive para registros antigos. Responsável, regime e convenção não aceitam apenas espaços; dias de descanso vazios, inválidos ou repetidos são recusados.
