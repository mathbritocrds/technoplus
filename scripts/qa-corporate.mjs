// Real administrative forms, isolated databases, desktop/mobile and built package.
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
  const port=18182,base=`http://127.0.0.1:${port}`,db=resolve(mkdtempSync(resolve(tmpdir(),'sigi-corporate-ui-')),'test.db');
  const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(port)],{cwd,env:{...process.env,DB_PATH:db,SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let stderr='';server.stderr.on('data',chunk=>stderr+=chunk);
  try{
   let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}assert(ready,stderr);
   const register=await fetch(base+'/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'corporate@example.test',username:'Corporate QA',password:'corporate-test-password'})});const auth=await register.json();assert(register.ok,JSON.stringify(auth));
   const headers={'Content-Type':'application/json',Authorization:'Bearer '+auth.token};
   const api=async(path,method='GET',body)=>{const response=await fetch(base+path,{method,headers,...(body?{body:JSON.stringify(body)}:{})});const value=await response.json();assert(response.ok,`${path}: ${JSON.stringify(value)}`);return value};
   const employee=await api('/employees','POST',{name:'Funcionária QA',salary:3000,pin:'1234',hired_on:'2025-01-01'});
   await api('/payroll/close','POST',{month:'2026-10'});await api(`/employees/${employee.id}`,'PATCH',{salary:3300});
   const today=new Date().toLocaleDateString('sv',{timeZone:'America/Sao_Paulo'}),current=today.slice(0,7);
   if(current!=='2026-10')await api('/payroll/close','POST',{month:current});
   const transaction=await api('/finance','POST',{kind:'pagar',description:'Conciliação QA',amount:100,due:today});await api(`/finance/${transaction.id}/paid`,'PATCH',{});
   const payment=(await api('/finance/payments?month='+current))[0];
   const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   // External font delivery is restricted in this environment. No API is mocked.
   await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:'body{font-family:Arial,sans-serif}'}));
   await context.addInitScript(({token})=>{sessionStorage.setItem('tk',token);sessionStorage.setItem('role','admin')},{token:auth.token});
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
   await page.goto(base,{waitUntil:'networkidle'});await page.evaluate(async()=>{S.payrollMonth='2026-10';await go('folha',{first:true})});
   await page.getByText('Complementos e obrigações da folha',{exact:true}).click();
   const submit=async(form,path,fill)=>{await fill(form);const wait=page.waitForResponse(r=>r.url()===base+path&&r.request().method()!=='GET');await form.locator('button[type="submit"]').click();const response=await wait;assert(response.ok(),await response.text());await page.waitForTimeout(200)};
   await submit(page.locator('[data-corporate-action="adjustment"]'),'/payroll/adjustments',async form=>{await form.locator('[name="reference"]').fill('ui-complement-1');await form.locator('[name="reason"]').fill('Reajuste retroativo aprovado na revisão');});
   assert.equal((await api('/payroll/adjustments?month=2026-10')).length,1);
   await page.getByText('Complementos e obrigações da folha',{exact:true}).click();
   await submit(page.locator('[data-corporate-action="obligations"]'),'/compliance/obligations/generate',async form=>{await form.locator('[name="reason"]').fill('Obrigações conferidas pelo escritório');});
   await page.getByText('Complementos e obrigações da folha',{exact:true}).click();
   await submit(page.locator('[data-corporate-action="evidence"]'),'/compliance/records',async form=>{await form.locator('[name="reference"]').fill('ui-esocial-protocol');await form.locator('[name="evidence"]').fill('Documento assinado e conferido externamente');await form.locator('[name="reason"]').fill('Conferência de transmissão externa');});
   await page.evaluate(async()=>{await go('seguranca',{first:true})});await page.getByText('Política trabalhista e revisão fiscal',{exact:true}).click();
   await submit(page.locator('[data-corporate-action="policy"]'),'/compliance/policy',async form=>{await form.locator('[name="external_payroll_provider"]').fill('Escritório de teste');await form.locator('[name="reviewed_regime"]').fill('Regime revisado pelo contador');await form.locator('[name="reviewed_agreement"]').fill('Convenção revisada pelo RH');await form.locator('[name="reason"]').fill('Revisão conjunta dos parâmetros fiscais');});
   await page.evaluate(async value=>{S.financeMonth=value;await go('financeiro',{first:true})},current);await page.getByText('Conciliação bancária e fechamento contábil',{exact:true}).click();
   await submit(page.locator('[data-corporate-action="bank-import"]'),'/accounting/bank-entries/import',async form=>{await form.locator('[name="account"]').fill('Conta QA');await form.locator('[name="statement"]').setInputFiles({name:'extrato.csv',mimeType:'text/csv',buffer:Buffer.from(`reference;date;amount;description\nqa-ref-1;${today};-100.00;Pagamento QA\n`)});});
   await page.getByText('Conciliação bancária e fechamento contábil',{exact:true}).click();
   const entry=(await api('/accounting/bank-entries?month='+current))[0];
   await submit(page.locator('[data-corporate-action="bank-match"]'),`/accounting/bank-entries/${entry.id}/match`,async form=>{await form.locator('[name="payment_id"]').fill(String(payment.id));await form.locator('[name="reason"]').fill('Valor e data conferidos contra o extrato');});
   await page.getByText('Conciliação bancária e fechamento contábil',{exact:true}).click();
   await submit(page.locator('[data-corporate-action="close-period"]'),'/accounting/periods/close',async form=>{await form.locator('[name="reason"]').fill('Balancete e conciliação conferidos');});
   assert((await api('/accounting/periods')).find(row=>row.month===current).closed);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Corporate forms must fit mobile');
   await page.getByText('Conciliação bancária e fechamento contábil',{exact:true}).click();await page.screenshot({path:resolve(output,`corporate-${build}-${viewport}.png`),fullPage:true});
   assert.deepEqual(errors,[]);verdict.push({build,viewport,ok:true,flows:['complement','obligations','external-evidence','policy','statement-import','reconciliation','period-close']});await context.close();
  }finally{server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve))}
 }
}finally{await browser.close()}
console.log(JSON.stringify(verdict,null,2));
