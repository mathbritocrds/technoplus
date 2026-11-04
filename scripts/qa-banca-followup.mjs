// Regression checks through the real UI, with disposable databases and no API mocks.
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
const output='/workspace/screenshots';mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
const verdict=[];
try{
 for(const [build,cwd] of [['dev',resolve('.')],['built',resolve('dist/sigi')]])for(const [viewport,width] of [['desktop',1280],['mobile',390]]){
  const root=mkdtempSync(resolve(tmpdir(),'sigi-banca-fix-')),base='http://127.0.0.1:18231';
  const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18231'],{cwd,env:{...process.env,DB_PATH:resolve(root,'production.db'),DEMO_DB_PATH:resolve(root,'demo.db'),SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let stderr='';server.stderr.on('data',chunk=>stderr+=chunk);
  try{
   let ready=false;for(let i=0;i<80;i++){if(server.exitCode!==null)throw new Error(stderr);try{if((await fetch(base+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}assert(ready,stderr);
   const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:'body{font-family:Arial,sans-serif}'}));
   const page=await context.newPage(),errors=[],patches=[];
   page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
   page.on('request',request=>{if(request.method()==='PATCH'&&/\/tasks\//.test(request.url()))patches.push(request.url())});
   await page.goto(base+'/demo/',{waitUntil:'networkidle'});await page.locator('#main h1').waitFor();
   await page.evaluate(async()=>{await go('folha',{first:true});newEmployeeDialog()});
   await page.locator('#en').fill('Ana Lima');await page.locator('#es').fill('3000');await page.locator('#ehired').fill('2024-01-01');await page.locator('#ep').fill('5432');
   const created=page.waitForResponse(r=>r.url()===base+'/demo/employees'&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Salvar funcionário',exact:true}).click();const eid=(await(await created).json()).id;await page.locator('#taskOverlay').waitFor({state:'hidden'});
   await page.evaluate(async()=>{await go('quadros',{first:true})});
   assert((await page.locator('#nw option').allTextContents()).filter(text=>text.includes('Ana Lima')).length===2);
   assert((await page.locator(`#nw option[value="${eid}"]`).innerText()).includes('#'+eid));
   await page.locator('#nt').fill('Montagem auditada');await page.locator('#nw').selectOption(String(eid));
   const added=page.waitForResponse(r=>r.url()===base+'/demo/tasks'&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Adicionar item',exact:true}).click();const tid=(await(await added).json()).id;
   assert.equal((await page.evaluate(id=>api('/tasks/'+id),tid)).assignee_employee_id,eid);
   await page.evaluate(id=>openTask(id),tid);
   const material=await page.evaluate(async()=>{const selected=+document.querySelector('#taskMaterial').value;return(await api('/materials')).find(m=>m.id===selected)});
   await page.locator('#taskMaterialQty').fill('2');
   const linked=page.waitForResponse(r=>r.url()===base+`/demo/tasks/${tid}/materials`&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Vincular insumo',exact:true}).click();assert((await linked).ok());
   await page.waitForFunction(()=>document.querySelector('#taskMaterialQty')?.value==='');await page.locator('#taskTitle').fill('');await page.locator('#taskStatus').selectOption('1');
   const beforePatches=patches.length;await page.getByRole('button',{name:'Salvar dados',exact:true}).click();await page.locator('#toast').filter({hasText:'O título não pode ficar vazio.'}).waitFor();
   assert.equal(patches.length,beforePatches);
   const invalid=await page.evaluate(async id=>({task:await api('/tasks/'+id),materials:await api('/materials')}),tid);
   assert.equal(invalid.task.status,0);assert.equal(invalid.task.materials[0].consumed_quantity,0);assert.equal(invalid.materials.find(m=>m.id===material.id).stock,material.stock);
   await page.locator('#taskTitle').fill('Montagem validada');
   const saved=page.waitForResponse(r=>r.url()===base+'/demo/tasks/'+tid&&r.request().method()==='PATCH');
   await page.getByRole('button',{name:'Salvar dados',exact:true}).click();assert((await saved).ok());
   await page.locator('#taskModalTitle').filter({hasText:'Montagem validada'}).waitFor();assert.equal(patches.length,beforePatches+1);
   const valid=await page.evaluate(async id=>({task:await api('/tasks/'+id),materials:await api('/materials')}),tid);
   assert.equal(valid.task.status,1);assert.equal(valid.task.assignee_employee_id,eid);assert.equal(valid.materials.find(m=>m.id===material.id).stock,material.stock-2);
   // An explicit external owner must stay external even with an internal homonym.
   await page.locator('#taskAssignee').selectOption('external');await page.locator('#taskAssigneeExternal').fill('Ana Lima');
   const externalForm=await page.locator('#taskAssignee').elementHandle();
   const externalSaved=page.waitForResponse(r=>r.url()===base+'/demo/tasks/'+tid&&r.request().method()==='PATCH');
   await page.getByRole('button',{name:'Salvar dados',exact:true}).click();assert((await externalSaved).ok());await page.waitForFunction(element=>!element.isConnected,externalForm);await externalForm.dispose();
   await page.waitForFunction(()=>document.querySelector('#taskAssignee')?.value==='external'&&document.querySelector('#taskAssigneeExternal')?.value==='Ana Lima');
   const externalTask=await page.evaluate(id=>api('/tasks/'+id),tid);assert.equal(externalTask.assignee_employee_id,null);assert.equal(externalTask.assignee_external,1);
   await page.locator('#taskAssignee').selectOption(String(eid));
   const internalForm=await page.locator('#taskAssignee').elementHandle();
   const internalSaved=page.waitForResponse(r=>r.url()===base+'/demo/tasks/'+tid&&r.request().method()==='PATCH');
   await page.getByRole('button',{name:'Salvar dados',exact:true}).click();assert((await internalSaved).ok());await page.waitForFunction(element=>!element.isConnected,internalForm);await internalForm.dispose();
   await page.waitForFunction(id=>document.querySelector('#taskAssignee')?.value===String(id),eid);
   await page.screenshot({path:resolve(output,`banca-fixed-${build}-${viewport}.png`),fullPage:true});
   // An archived owner remains selectable only for this existing link.
   await page.evaluate(async id=>{await api('/employees/'+id,'DELETE');closeTask()},eid);await page.evaluate(id=>openTask(id),tid);
   assert((await page.locator('#taskAssignee option:checked').innerText()).includes('inativo'));
   await page.locator('#taskTitle').fill('Edição após desligamento');
   const archived=page.waitForResponse(r=>r.url()===base+'/demo/tasks/'+tid&&r.request().method()==='PATCH');
   await page.getByRole('button',{name:'Salvar dados',exact:true}).click();assert((await archived).ok());await page.locator('#taskModalTitle').filter({hasText:'Edição após desligamento'}).waitFor();
   // A fresh active person gives us a known test PIN for the public clock form.
   const clockId=await page.evaluate(async()=>{const result=await api('/employees','POST',{name:'Ponto de teste',salary:2000,pin:'6789'});await login();await setMode('p');return result.id});
   await page.locator('#le').selectOption(String(clockId));await page.locator('#lp').fill('6789');
   const lookup=page.waitForResponse(r=>r.url()===base+'/demo/clock/tasks'&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Carregar tarefas',exact:true}).click();const response=await lookup;
   assert(response.ok());assert.equal(response.headers()['cache-control'],'no-store');assert.deepEqual(response.request().postDataJSON(),{employee_id:clockId,pin:'6789'});
   assert.deepEqual(errors,[]);await context.close();verdict.push({build,viewport,ok:true,checks:['homonym-id-selection','invalid-edit-no-stock-change','atomic-stage-and-stock','external-owner-distinct','archived-owner-kept','pin-in-body']});
  }finally{if(server.exitCode===null){server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve))}}
 }
}finally{await browser.close()}
console.log(JSON.stringify(verdict,null,2));
