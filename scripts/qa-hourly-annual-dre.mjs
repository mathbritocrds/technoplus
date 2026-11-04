// Real forms and APIs, disposable data; only external font delivery is replaced.
import {chromium} from 'playwright';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
const output='/workspace/screenshots';mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH||'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});
const verdict=[];
try{
 for(const [build,cwd] of [['dev',resolve('.')],['built',resolve('dist/sigi')]])for(const [viewport,width] of [['desktop',1280],['mobile',390]]){
  const root=mkdtempSync(resolve(tmpdir(),'sigi-hourly-ui-')),base='http://127.0.0.1:18241',demoDb=resolve(root,'demo.db');
  const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18241'],{cwd,env:{...process.env,DB_PATH:resolve(root,'production.db'),DEMO_DB_PATH:demoDb,SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let stderr='';server.stderr.on('data',chunk=>stderr+=chunk);
  try{
   let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw new Error(stderr);try{if((await fetch(base+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}assert(ready,stderr);
   const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'});
   await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:'body{font-family:Arial,sans-serif}'}));
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
   await page.goto(base+'/demo/',{waitUntil:'networkidle'});await page.locator('#main h1').waitFor();
   await page.evaluate(async()=>{S.payrollMonth='2026-02';await go('folha',{first:true})});
   await page.getByRole('button',{name:'Adicionar funcionário',exact:true}).click();
   await page.locator('#en').fill('Horista QA');await page.locator('#es').fill('9999');await page.locator('#ehired').fill('2024-01-01');await page.locator('#ep').fill('6789');
   const created=page.waitForResponse(r=>r.url()===base+'/demo/employees'&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Salvar funcionário',exact:true}).click();const eid=(await(await created).json()).id;await page.locator('#taskOverlay').waitFor({state:'hidden'});
   // Historical accepted clock fixtures are inserted as setup, not as API mocks.
   const seed=spawnSync('python',['-c',`import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as c:
 for kind,hour in [('entrada',9),('saida',19)]:
  c.execute('INSERT INTO time_entries(employee_id,kind,at,accepted) VALUES(?,?,?,1)',(int(sys.argv[2]),kind,f'2026-02-02T{hour:02d}:00:00-03:00'))
`,demoDb,String(eid)],{encoding:'utf8'});assert.equal(seed.status,0,seed.stderr);
   await page.evaluate(async()=>{await go('folha',{first:true})});const card=page.locator(`[data-k="e${eid}"]`);await card.locator('summary').first().click();
   await card.getByRole('button',{name:'Benefícios e férias',exact:true}).click();
   // Saving a monthly profile must not be blocked by hidden hourly-rate defaults.
   assert(await page.locator('[data-profile="hourly_rate"]').isDisabled());
   const monthlySaved=page.waitForResponse(r=>r.url()===base+`/demo/employees/${eid}/payroll-profile`&&r.request().method()==='PUT');
   await page.getByRole('button',{name:'Salvar dados de RH',exact:true}).click();assert((await monthlySaved).ok());await page.locator('#taskOverlay').waitFor({state:'hidden'});
   await page.evaluate(id=>openHR(id),eid);await page.locator('[data-profile="pay_basis"]').selectOption('hourly');
   assert(await page.locator('[data-profile="hourly_rate"]').isEnabled());
   await page.locator('[data-profile="hourly_rate"]').fill('20');await page.locator('[data-profile="reference_monthly_hours"]').fill('160');
   const saved=page.waitForResponse(r=>r.url()===base+`/demo/employees/${eid}/payroll-profile`&&r.request().method()==='PUT');
   await page.getByRole('button',{name:'Salvar dados de RH',exact:true}).click();assert((await saved).ok());await page.locator('#taskOverlay').waitFor({state:'hidden'});
   const monthly=await page.evaluate(async id=>(await api('/payroll?month=2026-02')).employees.find(person=>person.id===id),eid);
   assert.equal(monthly.gross,256.67);assert.equal(monthly.worked_hours,10);assert.equal(monthly.overtime_pay,60);assert.equal(monthly.dsr_pay,36.67);
   await page.waitForFunction(id=>document.querySelector('[data-k="e'+id+'"]')?.textContent.includes('Horista ·'),eid);
   await page.getByRole('button',{name:'Custos e gráficos',exact:true}).click();
   await page.locator('#annualEmployeeComposition > summary').click();await page.locator('#annualCompositionEmployee').selectOption(String(eid));
   await page.locator(`[data-annual-chart="${eid}"]`).waitFor();
   const annual=await page.evaluate(async id=>(await api('/payroll/annual-cost?year=2026')).employees.find(person=>person.id===id),eid);
   const chartTotal=(await page.locator('#annualEmployeeChart [data-annual-component]').evaluateAll(nodes=>nodes.reduce((total,node)=>total+Number(node.dataset.annualComponent),0)));
   assert(Math.abs(chartTotal-annual.total)<.02);assert.equal(annual.inss,19.25);
   const formattedInss=await page.evaluate(value=>R(value),annual.inss);assert.equal(await page.locator('[data-annual-inss]').innerText(),formattedInss);
   assert((await page.locator('#annualEmployeeChart').innerText()).includes('10 h'));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.getByRole('button',{name:'Alternar tema claro ou escuro'}).click();
   await page.locator('#annualEmployeeComposition').screenshot({path:resolve(output,`annual-hourly-${build}-${viewport}.png`)});
   // Reopen the persisted contract and simulate the split at concession expiry.
   await page.evaluate(id=>openHR(id),eid);assert.equal(await page.locator('[data-profile="pay_basis"]').inputValue(),'hourly');
   const vacation=page.getByText('Simular e registrar férias',{exact:true});await vacation.click();
   await page.locator('#vacationCycle').selectOption('2024-01-01');await page.locator('#vacationStart').fill('2025-12-20');await page.locator('#vacationDays').fill('20');
   const quoted=page.waitForResponse(r=>r.url()===base+`/demo/employees/${eid}/vacations/quote`&&r.request().method()==='POST');
   await page.getByRole('button',{name:'Calcular férias',exact:true}).click();const quote=await(await quoted).json();assert.equal(quote.overdue_days,8);assert.equal(quote.gross,3982.22);
   await page.locator('#vacationQuote').filter({hasText:'8 dia(s)'}).waitFor();await page.evaluate(()=>closeTask());
   await page.evaluate(async()=>{S.financeMode='year';S.financeYear='2026';await go('financeiro',{first:true})});
   await page.getByRole('button',{name:'DRE e fluxo',exact:true}).click();await page.getByRole('heading',{name:'DRE · modelo Inter Empresas',exact:true}).waitFor();
   assert.equal(await page.locator('.dre-inter-table tbody tr').count(),10);
   assert.equal(await page.locator('.dre-inter-table thead th').count(),15);
   const dre=await page.evaluate(()=>api('/finance/dre?start=2026-01&end=2026-12'));
   const result=dre.inter_model.rows.find(row=>row.key==='net_profit');assert.equal(result.amount,dre.net_profit);
   const formattedResult=await page.evaluate(value=>R(value),result.amount);
   assert.equal(await page.locator('[data-dre-line="net_profit"] [data-dre-total]').innerText(),formattedResult);
   const section=page.locator('section').filter({has:page.getByRole('heading',{name:'DRE · modelo Inter Empresas',exact:true})}).last();
   await section.screenshot({path:resolve(output,`dre-inter-${build}-${viewport}.png`)});
   const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Exportar Excel (modelo)',exact:true}).click();const download=await downloadPromise;assert(download.suggestedFilename().endsWith('.xlsx'));assert.equal(await download.failure(),null);
   // The first screenshot is a separate React accounting screen, also using Inter.
   await page.evaluate(async()=>{await api('/accounting/journals','POST',{
    booked_on:'2026-11-02',description:'Receita para conferir a tela',reference:'screen-inter-revenue',
    lines:[{account_code:'1.1.01',debit:'1000'},{account_code:'4.1.01',credit:'1000'}]});await go('contabilidade',{first:true})});
   await page.getByRole('heading',{name:'DRE · modelo Inter Empresas',exact:true}).waitFor();
   const accounting=await page.evaluate(()=>api('/accounting/reports?start=2026-11-01&end=2026-11-30'));
   assert.equal(await page.locator('[data-statement-row]').count(),accounting.inter_dre.length);
   const expected=await page.evaluate(cents=>'R$ '+(cents/100).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}),accounting.inter_dre.find(row=>row.key==='net_profit').amount_cents);
   assert((await page.locator('[data-statement-row="net_profit"]').innerText()).includes(expected));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.locator('#accountingRoot').screenshot({path:resolve(output,`accounting-inter-${build}-${viewport}.png`)});
   const accountingDownload=page.waitForEvent('download');await page.getByRole('button',{name:'Exportar DRE CSV',exact:true}).click();assert((await accountingDownload).suggestedFilename().endsWith('.csv'));
   const code=await fetch(base+'/demo/business.js');assert.equal(code.headers.get('cache-control'),'no-cache, must-revalidate');
   assert.deepEqual(errors,[]);await context.close();verdict.push({build,viewport,ok:true,checks:['monthly-form-valid','hourly-normal-extra-dsr','annual-inss-chart-reconciled','vacation-partial-double','dre-inter-web-and-xlsx','accounting-inter-screen-and-csv','current-code-assets']});
  }finally{if(server.exitCode===null){server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve))}}
 }
}finally{await browser.close()}
console.log(JSON.stringify(verdict,null,2));
