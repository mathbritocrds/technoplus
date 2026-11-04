// Exercise original management actions through the new boards and XLSX button.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const output=process.env.QA_SCREENSHOTS||'/workspace/screenshots';mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE_PATH?{executablePath:process.env.BROWSER_EXECUTABLE_PATH}:{}),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
const verdict=[];
try {
 for(const [build,port,cwd] of [['dev',18084,resolve('.')],['built',18085,resolve('dist/sigi')]]) {
  const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(port)],{cwd,env:{...process.env,DB_PATH:resolve(mkdtempSync(resolve(tmpdir(),'sigi-kanban-')),'qa.db'),SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let log='';server.stderr.on('data',data=>log+=data);const base=`http://127.0.0.1:${port}`;
  try {
   let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base+'/auth/status')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}assert(ready,log);
   let token;
   const request=async(path,body,method='POST',access=token)=>{
    const response=await fetch(base+path,{method,headers:{'Content-Type':'application/json',...(access?{Authorization:'Bearer '+access}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const data=await response.json();assert(response.ok,JSON.stringify(data));return data;
   };
   token=(await request('/auth/register',{email:'kanban@example.test',password:'kanban-test-password',company_name:'SIGI Kanban'})).token;
   const lead=await request('/employees',{name:'Ana Produção',role:'Supervisora',salary:3000,pin:'1234'});
   const second=await request('/employees',{name:'Bruno Operação',role:'Operador',salary:2000,pin:'4321'});
   const free=await request('/employees',{name:'Carla Logística',role:'Responsável',salary:2800,pin:'5678'});
   const missing=await request('/departments',{name:'Logística'});
   const forming=await request('/departments',{name:'Produção',lead_employee_id:lead.id});
   const readyDept=await request('/departments',{name:'Qualidade',lead_employee_id:free.id});
   await request('/employees/'+second.id,{department_id:readyDept.id},'PATCH');
   await request('/auth/register',{email:'board-manager@example.test',password:'manager-test-password',role:'manager',department_id:forming.id,employee_id:lead.id});
   await request('/employees/'+lead.id+'/account',{email:'board-worker@example.test',password:'worker-test-password'});
   const worker=(await request('/auth/employee/login',{email:'board-worker@example.test',password:'worker-test-password'})).token;
   const leave=await request('/employee/requests',{kind:'ferias',details:'Pedido de férias de janeiro'},'POST',worker);
   await request('/employee/requests',{kind:'atestado',details:'Documento médico restrito',attachment_name:'atestado.pdf',attachment_mime:'application/pdf',attachment_base64:Buffer.from('%PDF-1.7\nQA').toString('base64')},'POST',worker);
   const task=await request('/tasks',{title:'Inspeção pendente',department_id:forming.id,approval:'pendente'});
   await request('/tasks',{title:'Outro setor restrito',department_id:readyDept.id,approval:'pendente'});
   const active=await request('/integrations',{name:'ERP "Fábrica" <seguro>',kind:'erp',endpoint:'https://invalid.test/erp',active:true});
   await request('/integrations',{name:'Webhook sem destino',kind:'webhook',endpoint:'',active:true});
   await request('/integrations',{name:'Arquivo CSV',kind:'csv',endpoint:'',active:true});
   await request('/integrations',{name:'ERP pausado',kind:'erp',endpoint:'https://invalid.test/paused',active:false});
   await request('/finance',{kind:'pagar',description:'Insumos por setor',amount:125.50,due:'2026-06-10',department_id:forming.id,category:'cost'});
   for(const [viewport,width,height] of [['desktop',1280,900],['mobile',390,844]]) {
    const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
    if(process.env.QA_FONT_CSS)await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:readFileSync(process.env.QA_FONT_CSS,'utf8')}));
    const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);await page.locator('#lu').fill('kanban@example.test');await page.locator('#ls').fill('kanban-test-password');await page.locator('#lf .btn').click();await page.locator('[data-sector="rh"]').waitFor();
    const navigate=async(group,tab)=>{if(await page.locator(`[data-sector="${group}"]`).getAttribute('aria-expanded')!=='true')await page.locator(`[data-sector="${group}"]`).click();await page.locator(`#submenuItems [data-t="${tab}"]`).click();};
    const fits=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Body overflow');
    const column=key=>page.locator(`[data-management-column="${key}"]`);
    await navigate('rh','departamentos');await page.locator('[data-management-board="departamentos"]').waitFor();
    assert.equal(await column('missing').locator('[data-k]').count(),1);assert.equal(await column('forming').locator('[data-k]').count(),1);assert.equal(await column('ready').locator('[data-k]').count(),1);
    await page.locator('#management-query-departamentos').fill('producao');assert.equal(await page.locator('.management-card:visible').count(),1);await page.getByRole('button',{name:'Limpar busca',exact:true}).click();
    const department=page.locator(`[data-k="d${missing.id}"]`);await department.locator('.management-edit summary').click();await department.locator('[data-dn]').fill('Logística '+viewport);await department.getByRole('button',{name:'Salvar',exact:true}).click();await column('missing').getByRole('heading',{name:'Logística '+viewport}).waitFor();
    assert.equal(await page.locator(`[data-k="d${missing.id}"] [data-dl] option[value="${lead.id}"]`).count(),0,'Cannot borrow another department lead');
    await fits();await page.screenshot({path:`${output}/sigi-kanban-${build}-departamentos-${viewport}.png`,fullPage:true,animations:'disabled'});
    await page.locator('.management-create summary').click();await page.locator('#dn').fill('Temporário '+viewport);await page.getByRole('button',{name:'Adicionar departamento',exact:true}).click();const created=page.locator('.management-card').filter({has:page.getByRole('heading',{name:'Temporário '+viewport})});await created.locator('.management-edit summary').click();await created.getByRole('button',{name:'Excluir',exact:true}).click();await created.waitFor({state:'detached'});
    // Integration names contain quotes/markup; actions resolve their saved object.
    await page.evaluate(()=>go('integracao'));await page.locator('[data-management-board="integracoes"]').waitFor();
    assert.equal(await column('setup').locator('[data-k]').count(),1);assert.equal(await column('active').locator('[data-k]').count(),viewport==='desktop'?2:1);
    if(viewport==='desktop'){await page.locator(`[data-k="i${active.id}"]`).getByRole('button',{name:'Pausar'}).click();await column('paused').locator(`[data-k="i${active.id}"]`).waitFor();}
    await page.locator('.management-create summary').click();await page.locator('#in').fill('CSV temporário');await page.locator('#ik').selectOption('csv');await page.getByRole('button',{name:'Adicionar integração',exact:true}).click();await page.getByRole('heading',{name:'CSV temporário'}).waitFor();const integration=page.locator('.management-card').filter({has:page.getByRole('heading',{name:'CSV temporário',exact:true})});await integration.getByRole('button',{name:'Excluir',exact:true}).click();await integration.waitFor({state:'detached'});await fits();
    await page.screenshot({path:`${output}/sigi-kanban-${build}-integracoes-${viewport}.png`,fullPage:true,animations:'disabled'});
    await page.evaluate(()=>go('aprovacoes'));await page.locator('[data-management-board="aprovacoes"]').waitFor();assert.equal(await page.locator('[data-management-column]').count(),4);
    if(viewport==='desktop'){await page.locator(`[data-k="approval-task-${task.id}"]`).getByRole('button',{name:'Aprovar'}).click();await page.locator(`[data-k="approval-task-${task.id}"]`).waitFor({state:'detached'});page.once('dialog',dialog=>dialog.accept('Conforme planejamento'));await page.locator(`[data-k="approval-request-${leave.id}"]`).getByRole('button',{name:'Recusar'}).click();await page.locator(`[data-k="approval-request-${leave.id}"]`).waitFor({state:'detached'});}
    await fits();await page.screenshot({path:`${output}/sigi-kanban-${build}-aprovacoes-${viewport}.png`,fullPage:true,animations:'disabled'});
    await navigate('finance','financeiro');await page.locator('[data-density-view="results"]').click();await page.getByLabel('Ano da DRE',{exact:true}).selectOption('2026');await page.getByLabel('Setor da DRE',{exact:true}).selectOption(String(forming.id));await page.getByRole('button',{name:'Exportar Excel (modelo)',exact:true}).waitFor();
    const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Exportar Excel (modelo)',exact:true}).click();const download=await downloadPromise;assert.equal(download.suggestedFilename(),'dre-2026-01-2026-12.xlsx');const file=readFileSync(await download.path());assert.equal(file.subarray(0,2).toString(),'PK');assert(file.length>1000000);assert.equal(await download.failure(),null);
    assert.deepEqual(errors,[]);await context.close();
    const managerContext=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),managerPage=await managerContext.newPage();
    if(process.env.QA_FONT_CSS)await managerContext.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:readFileSync(process.env.QA_FONT_CSS,'utf8')}));
    await managerPage.goto(base);await managerPage.locator('#lu').fill('board-manager@example.test');await managerPage.locator('#ls').fill('manager-test-password');await managerPage.locator('#lf .btn').click();await managerPage.locator('[data-sector]').first().waitFor();await managerPage.evaluate(()=>go('aprovacoes'));await managerPage.locator('[data-management-board="aprovacoes"]').waitFor();assert.equal(await managerPage.locator('[data-management-column]').count(),3);assert.equal(await managerPage.getByText('Documento médico restrito').count(),0);assert.equal(await managerPage.getByText('Outro setor restrito').count(),0);await managerContext.close();
    verdict.push({build,viewport,ok:true,flows:['department-create-edit-delete-search','integration-toggle-create-delete','approval-decisions','manager-scope-medical-privacy','xlsx-download-period-sector','responsive-board']});
   }
  } finally {server.kill('SIGTERM');}
 }
} finally {await browser.close();}
console.log(JSON.stringify(verdict,null,2));
