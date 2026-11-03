/* Administrative controls share the application's authentication and visual tokens. */
(()=>{
 const safe=value=>esc(String(value??''));
 const today=()=>new Date().toLocaleDateString('sv',{timeZone:'America/Sao_Paulo'});
 const month=()=>today().slice(0,7);
 const field=(label,name,type='text',value='',extra='')=>`<label class="business-field">${label}<input name="${name}" type="${type}" value="${safe(value)}" ${extra}></label>`;
 const form=(action,content,label)=>`<form data-corporate-action="${action}"><div class="grid g2 form-grid">${content}</div><button class="btn" type="submit">${label}</button><p data-corporate-result class="sub" aria-live="polite"></p></form>`;
 const reason=()=>field('Justificativa','reason','text','','required minlength="5" maxlength="1000"');
 const period=(value)=>field('Competência','month','month',value,'required');
 const card=(title,content)=>`<details class="card employee-details" data-corporate><summary>${title}</summary>${content}</details>`;

 function parsePolicyWeekdays(value){
  const tokens=String(value).split(',').map(token=>token.trim());
  if(tokens.some(token=>!/^[0-6]$/.test(token)))throw new Error('Informe os dias de descanso de 0 a 6, separados por vírgula, sem campos vazios.');
  const days=tokens.map(Number);
  if(new Set(days).size!==days.length)throw new Error('Não repita os dias de descanso.');
  return days;
 }

 async function payrollControls(){
  const value=S.businessPayroll?.month||month();
  const [adjustments,checklist,obligations]=await Promise.all([api('/payroll/adjustments?month='+value),api('/compliance/checklist?month='+value),api('/compliance/obligations?month='+value)]);
  return card('Complementos e obrigações da folha',`<p class="sub">O fechamento original é preservado. Regularize o ponto antes de recalcular diferenças. Valores negativos geram crédito a compensar, sem desfazer pagamentos anteriores.</p>${form('adjustment',period(value)+field('Referência única','reference','text','','required minlength="8" maxlength="120"')+field('Data contábil do complemento','booked_on','date',today(),'required')+reason(),'Gerar folha complementar')}<p class="sub">${adjustments.length} complemento(s) registrado(s).</p>${adjustments.map(row=>`<p>${safe(row.booked_on)} · ${safe(row.reference)} · ${safe(row.reason)}</p>`).join('')}<h3>Recolhimentos e benefícios</h3><p class="sub">${safe(obligations.notice||'Feche a folha para apurar as obrigações.')} INSS, IRRF, FGTS, encargos patronais e demais benefícios não repetem a despesa já reconhecida.</p>${obligations.items.map(item=>`<p>${safe(item.kind)}${item.department_id?' · setor #'+safe(item.department_id):''}: apurado ${R(item.calculated)} · gerado ${R(item.generated)} · baixado ${R(item.paid)}</p>`).join('')}${form('obligations',period(value)+field('Vencimento conferido pelo responsável','due','date',today(),'required')+reason(),'Gerar diferenças de obrigações')}<h3>Procedimentos externos</h3><p class="sub">${safe(checklist.notice)}</p><p class="sub">${checklist.policy.configured?'Responsável externo: '+safe(checklist.policy.external_payroll_provider):'Cadastre responsável, regime e convenção em Segurança antes do uso oficial.'}</p>${form('evidence',period(value)+`<label>Procedimento<select name="kind">${['esocial','fgts','inss','irrf','vacation','thirteenth','termination','benefits_and_other'].map(kind=>`<option>${kind}</option>`).join('')}</select></label>`+field('Protocolo / referência única','reference','text','','required minlength="5"')+field('Localização da evidência ou justificativa de não aplicação','evidence','text','','required minlength="5"')+reason(),'Registrar evidência externa')}<p class="sub">${checklist.records.length} evidência(s) registrada(s) nesta competência. A confirmação é feita pelo responsável, não por transmissão automática.</p>`);
 }

 async function financeControls(){
  const value=S.financeMonth||month();
  const [periods,entries,payments]=await Promise.all([api('/accounting/periods'),api('/accounting/bank-entries?month='+value),api('/finance/payments?month='+value)]);
  return card('Conciliação bancária e fechamento contábil',`<p class="sub">Concilie todos os pagamentos e linhas importadas da competência antes de encerrar. Uma reabertura exige justificativa e fica auditada.</p>${form('close-period',period(value)+reason(),'Encerrar competência contábil')}${form('reopen-period',period(value)+reason(),'Reabrir competência contábil')}<p class="sub">${periods.map(row=>`${safe(row.month)}: ${row.closed?'encerrada':'reaberta'}`).join(' · ')||'Nenhuma competência encerrada.'}</p><h3>Importar extrato CSV</h3><p class="sub">Cabeçalho: reference;date;amount;description. Data AAAA-MM-DD; valor assinado com ponto decimal. Débito negativo e crédito positivo. Não envie senha bancária.</p>${form('bank-import',field('Identificação da conta','account','text','','required')+'<label>Arquivo CSV<input name="statement" type="file" accept=".csv,text/csv" required></label>','Importar extrato bancário')}<h3>Pagamentos disponíveis</h3><p class="sub">${payments.map(payment=>`#${safe(payment.id)} ${safe(payment.description)} · ${R(payment.amount)}`).join('<br>')||'Nenhum pagamento nesta competência.'}</p>${entries.map(entry=>`<section><p>${safe(entry.booked_on)} · ${safe(entry.account)} · ${safe(entry.description)} · ${R(entry.amount_cents/100)} · ${entry.payment_id?'conciliado com #'+safe(entry.payment_id):'pendente'}</p>${entry.payment_id?'':form('bank-match',field('Linha do extrato','entry_id','number',entry.id,'required readonly')+field('ID do pagamento','payment_id','number','','required min="1"')+reason(),'Conciliar pagamento')}</section>`).join('')}`);
 }

 async function securityControls(){
  const [policy,settings]=await Promise.all([api('/compliance/policy'),api('/admin/operational-settings')]);
  return card('Política trabalhista e revisão fiscal',`<p class="sub">Informe o enquadramento validado pela contabilidade e pelo RH. A folha gerencial não transmite eSocial, FGTS Digital nem executa pagamentos bancários.</p>${form('policy',field('Responsável / escritório externo','external_payroll_provider','text',policy.external_payroll_provider||'','required minlength="3"')+field('Regime tributário revisado','reviewed_regime','text',policy.reviewed_regime||'','required minlength="3"')+field('Contrato / convenção coletiva revisada','reviewed_agreement','text',policy.reviewed_agreement||'','required minlength="3"')+field('Dias de descanso: 0 segunda a 6 domingo, separados por vírgula','vacation_rest_weekdays','text',(policy.vacation_rest_weekdays||[6]).join(','),'required')+field('Feriados: datas AAAA-MM-DD separadas por vírgula','vacation_holidays','text',(policy.vacation_holidays||[]).join(','))+reason(),'Salvar política revisada')}${form('work-policy',field('Jornada semanal (h)','weekly_hours','number',settings.weekly_hours,'required min="1" max="80" step="0.01"')+field('Divisor mensal do salário','salary_hour_divisor','number',settings.salary_hour_divisor,'required min="1" max="744" step="0.01"')+field('Multiplicador da hora extra','overtime_multiplier','number',settings.overtime_multiplier,'required min="1" max="5" step="0.01"'),'Salvar parâmetros da jornada')}<h3>Tabelas fiscais por ano</h3><p class="sub">Não há extrapolação automática para 2027. Importe somente tabela conferida por profissional responsável, com versão e fonte oficial. Fechamentos antigos preservam a versão aplicada.</p>${form('tax-rules',field('Ano','year','number',new Date().getFullYear()+1,'required min="2026" max="2100"')+field('URL HTTPS da fonte oficial','source','url','','required')+'<label>Tabela completa em JSON<textarea name="table" required aria-label="Tabela fiscal em JSON"></textarea></label>'+reason(),'Aprovar nova versão fiscal')}`);
 }

 for(const [name,render] of [['folha',payrollControls],['financeiro',financeControls],['seguranca',securityControls]]){
  const original=TAB[name];
  TAB[name]=async function(...args){const base=await original.apply(this,args);if(ROLE!=='admin')return base;try{return base+await render()}catch(error){return base+card('Controles administrativos',`<p role="alert">${safe(error.message)}</p>`)}};
 }
 document.addEventListener('submit',async event=>{
  const target=event.target.closest?.('form[data-corporate-action]');if(!target)return;
  event.preventDefault();const button=target.querySelector('button[type="submit"]');if(button.disabled)return;
  button.disabled=true;const result=target.querySelector('[data-corporate-result]');result.textContent='Processando…';
  try{
   const values=Object.fromEntries(new FormData(target)),action=target.dataset.corporateAction;
   if(action==='adjustment')await api('/payroll/adjustments','POST',values);
   else if(action==='obligations')await api('/compliance/obligations/generate','POST',values);
   else if(action==='evidence')await api('/compliance/records','POST',values);
   else if(action==='close-period'||action==='reopen-period')await api('/accounting/periods/'+(action==='close-period'?'close':'reopen'),'POST',values);
   else if(action==='bank-import')await api('/accounting/bank-entries/import','POST',{account:values.account,content:await values.statement.text()});
   else if(action==='bank-match')await api('/accounting/bank-entries/'+Number(values.entry_id)+'/match','POST',{payment_id:Number(values.payment_id),reason:values.reason});
   else if(action==='policy')await api('/compliance/policy','PUT',{...values,vacation_rest_weekdays:parsePolicyWeekdays(values.vacation_rest_weekdays),vacation_holidays:values.vacation_holidays.split(',').map(value=>value.trim()).filter(Boolean)});
   else if(action==='work-policy'){const previous=await api('/admin/operational-settings');await api('/admin/operational-settings','PUT',{...previous,weekly_hours:Number(values.weekly_hours),salary_hour_divisor:Number(values.salary_hour_divisor),overtime_multiplier:Number(values.overtime_multiplier)})}
   else if(action==='tax-rules')await api('/compliance/tax-rules','POST',{...values,year:Number(values.year),table:JSON.parse(values.table)});
   result.textContent='Registro concluído.';toast('Registro administrativo concluído.','ok');await refresh();
  }catch(error){result.textContent=error.message;toast(error.message,'no')}finally{button.disabled=false}
 });
})();
