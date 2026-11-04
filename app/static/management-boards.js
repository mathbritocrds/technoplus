// Kanban views derived from existing department, integration and approval data.
const managementText = value => String(value || '').normalize('NFD').replace(/\p{M}/gu,'').toLocaleLowerCase('pt-BR');
const managementSearchKey = kind => (CURRENT_USER || CURRENT_NAME) + ':' + kind;
function managementQuery(kind) { return (S.managementQueries || {})[managementSearchKey(kind)] || ''; }
function managementToolbar(kind, total) {
  return `<div class="row management-toolbar"><label>Buscar no quadro<input id="management-query-${kind}" type="search" aria-label="Buscar no quadro de ${kind}" value="${esc(managementQuery(kind))}" placeholder="Nome, responsável ou informação do cartão" oninput="filterManagementBoard('${kind}',this.value)"></label><button class="chip" onclick="clearManagementBoard('${kind}')">Limpar busca</button><span class="sub" id="management-result-${kind}" role="status" aria-live="polite">${total} cartão(ões)</span></div>`;
}
function managementBoard(kind, columns) {
  const query = managementText(managementQuery(kind));
  return `<div class="management-board" data-management-board="${kind}" style="--board-columns:${columns.length}" role="region" aria-label="Quadro Kanban de ${kind}">${columns.map(([key,title,note,cards])=>{
    const visible=cards.filter(card=>managementText(card.search).includes(query)).length;
    return `<section class="management-column" data-management-column="${key}" aria-labelledby="management-${kind}-${key}"><header><h2 id="management-${kind}-${key}">${title}<span class="cn" data-management-count>${query?visible+'/'+cards.length:cards.length}</span></h2><p class="sub">${note}</p></header><div class="management-cards">${cards.map(card=>`<article class="card management-card" data-k="${card.key}" data-management-search="${esc(managementText(card.search))}" ${managementText(card.search).includes(query)?'':'hidden'}>${card.html}</article>`).join('')}</div><p class="none management-empty" ${visible?'hidden':''}>${query?'Nenhum resultado nesta coluna.':'Nenhum cartão nesta coluna.'}</p></section>`;
  }).join('')}</div>`;
}
function filterManagementBoard(kind, value) {
  S.managementQueries ||= {}; S.managementQueries[managementSearchKey(kind)]=value;
  const board=document.querySelector(`[data-management-board="${kind}"]`); if(!board)return;
  const query=managementText(value);let total=0;
  board.querySelectorAll('[data-management-column]').forEach(column=>{
    const cards=[...column.querySelectorAll('[data-management-search]')];let visible=0;
    cards.forEach(card=>{card.hidden=!card.dataset.managementSearch.includes(query);if(!card.hidden)visible++;});
    column.querySelector('[data-management-count]').textContent=query?visible+'/'+cards.length:cards.length;
    const empty=column.querySelector('.management-empty');empty.hidden=visible>0;empty.textContent=query?'Nenhum resultado nesta coluna.':'Nenhum cartão nesta coluna.';total+=visible;
  });
  document.getElementById('management-result-'+kind).textContent=total+' cartão(ões)'+(query?' encontrados':'');
}
function clearManagementBoard(kind) { const input=document.getElementById('management-query-'+kind);input.value='';filterManagementBoard(kind,'');input.focus(); }

TAB.departamentos = async function () {
  const [departments, employees]=await Promise.all([api('/departments'),api('/employees')]);
  const groups={missing:[],forming:[],ready:[]};
  for(const department of departments){
    const people=employees.filter(person=>person.active&&person.department_id===department.id);
    const lead=people.find(person=>person.id===department.lead_employee_id);
    const group=!lead?'missing':people.length<=1?'forming':'ready';
    groups[group].push({key:'d'+department.id,search:[department.name,lead?.name,...people.map(p=>p.name+' '+p.role)].join(' '),html:`<h3>${esc(department.name)}<span class="cn">${people.length}</span></h3><p class="sub">Chefia: ${esc(lead?.name||'Definir funcionário ativo')}</p>${department.legacy_lead?`<p class="sub">Responsável anterior: ${esc(department.legacy_lead)}</p>`:''}<details class="management-team"><summary>Equipe · ${people.length} pessoa(s)</summary>${people.map(person=>`<div class="management-person"><strong>${esc(person.name)}</strong><span>${esc(person.role||'Cargo não informado')}</span></div>`).join('')||'<p class="sub">Nenhuma pessoa vinculada.</p>'}</details><details class="management-edit"><summary>Editar departamento</summary><label>Nome<input data-dn aria-label="Nome" value="${esc(department.name)}"></label><label>Chefia${departmentLeadSelect(employees,department.id,department.lead_employee_id||'','data-dl')}</label><div class="row"><button class="chip" onclick="run(()=>edD(${department.id}),this)">Salvar</button><button class="chip" onclick="run(()=>delD(${department.id}),this)">Excluir</button></div></details>`});
  }
  return `<h1>Departamentos</h1><p class="sub">Organize a chefia e a equipe de cada setor. As colunas acompanham os vínculos cadastrados.</p>${managementToolbar('departamentos',departments.length)}${managementBoard('departamentos',[
    ['missing','Sem chefia','Defina uma pessoa ativa como responsável.',groups.missing],['forming','Formando equipe','Chefia definida; até uma pessoa vinculada.',groups.forming],['ready','Equipe formada','Chefia e mais pessoas vinculadas ao setor.',groups.ready]
  ])}<section class="card management-create"><details><summary>Novo departamento</summary><div class="row"><label>Nome<input id="dn" placeholder="Nome"></label><label>Chefia${departmentLeadSelect(employees,null,'','id="dl"')}</label></div><button class="btn" onclick="run(addD,this)">Adicionar departamento</button></details></section>`;
};

async function toggleManagementIntegration(id) {
  const integration=S.managementIntegrations.find(item=>item.id===id);
  await tgI(id,integration.active?0:1,integration.name,integration.kind,integration.endpoint);
}
TAB.integracao = async function () {
  const integrations=await api('/integrations');S.managementIntegrations=integrations;S.integrations=integrations;
  const groups={setup:[],active:[],paused:[]};
  for(const item of integrations){
    const group=item.kind!=='csv'&&!item.endpoint.trim()?'setup':item.active?'active':'paused';
    groups[group].push({key:'i'+item.id,search:[item.name,INT[item.kind],item.endpoint].join(' '),html:`<h3>${esc(item.name)}</h3><span class="tag">${esc(INT[item.kind]||item.kind)}</span><p class="management-endpoint">${esc(item.endpoint||'Destino não informado')}</p><p class="sub">Cadastro ${item.active?'ativo':'pausado'}</p><div class="row"><button class="chip" onclick="run(()=>toggleManagementIntegration(${item.id}),this)">${item.active?'Pausar':'Ativar'}</button><button class="chip" onclick="run(()=>delI(${item.id}),this)">Excluir</button></div>`});
  }
  return `<h1>Integração</h1><p class="sub">Acompanhe as integrações pelo estado cadastrado.</p>${managementToolbar('integracoes',integrations.length)}${managementBoard('integracoes',[
    ['setup','A configurar','Integrações que ainda precisam de um destino.',groups.setup],['active','Ativas','Integrações ativadas no cadastro.',groups.active],['paused','Pausadas','Integrações desativadas no cadastro.',groups.paused]
  ])}<section class="card management-create"><details><summary>Nova integração</summary><div class="row"><label>Nome<input id="in" placeholder="Nome"></label><label>Tipo<select id="ik" aria-label="Tipo">${Object.entries(INT).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><label>Destino<input id="ie" placeholder="URL, telefone ou chave"></label></div><button class="btn" onclick="run(addI,this)">Adicionar integração</button></details></section>`;
};

TAB.aprovacoes = async function () {
  const inbox=await api('/approvals/inbox'),groups={tasks:[],ferias:[],folga:[],atestado:[]};
  for(const task of inbox.tasks)groups.tasks.push({key:'approval-task-'+task.id,search:[task.title,task.assignee,task.due].join(' '),html:`<h3>${esc(task.title)}</h3><p class="sub">${esc(task.assignee||'Sem responsável')} · ${task.due?'Prazo '+esc(dbr(task.due)):'Sem prazo'}</p><div class="row"><button class="chip" onclick="run(()=>decideTask(${task.id},'aprovado'),this)">Aprovar</button><button class="chip" onclick="run(()=>decideTask(${task.id},'recusado'),this)">Recusar</button></div>`});
  for(const request of inbox.requests){
    if(!groups[request.kind]||request.kind==='atestado'&&ROLE!=='admin')continue;
    groups[request.kind].push({key:'approval-request-'+request.id,search:[request.employee_name,request.details].join(' '),html:`<h3>${esc(request.employee_name)}</h3><p class="management-description">${esc(request.details)}</p><p class="sub">${esc(new Date(request.created_at).toLocaleString('pt-BR'))}</p>${ROLE==='admin'&&request.attachment_name?`<button class="chip" onclick="run(()=>downloadApprovalAttachment(${request.id}),this)">Baixar anexo</button>`:''}<div class="row"><button class="chip" onclick="run(()=>decideEmployeeRequest(${request.id},'aprovado'),this)">Aprovar</button><button class="chip" onclick="run(()=>decideEmployeeRequest(${request.id},'recusado'),this)">Recusar</button></div>`});
  }
  const columns=[['tasks','Tarefas','Cartões aguardando uma decisão.',groups.tasks],['ferias','Férias','Pedidos de férias para analisar.',groups.ferias],['folga','Folgas','Solicitações de banco de horas.',groups.folga]];
  if(ROLE==='admin')columns.push(['atestado','Atestados','Documentos restritos ao RH/Admin.',groups.atestado]);
  return `<h1>Central de aprovações</h1><p class="sub">Filas de análise por tipo de solicitação. Os cartões saem da fila após a decisão.</p>${managementToolbar('aprovacoes',columns.reduce((sum,column)=>sum+column[3].length,0))}${managementBoard('aprovacoes',columns)}`;
};
