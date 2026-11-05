import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {spawn} from 'node:child_process';import {mkdirSync,mkdtempSync,writeFileSync} from 'node:fs';
mkdirSync('/workspace/screenshots',{recursive:true});
const folder=mkdtempSync('/tmp/banca3-confuso-'),base='http://127.0.0.1:18261';
const server=spawn('/workspace/technoplus/.venv/bin/python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18261'],{cwd:process.env.QA_APP_ROOT||process.cwd(),env:{...process.env,DB_PATH:folder+'/prod.db',DEMO_DB_PATH:folder+'/demo.db',SUPABASE_DATABASE_URL:''},stdio:'ignore'});
let browser;const result=[];
try{let ready=false;for(let n=0;n<100;n++){try{if((await fetch(base+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}if(!ready)throw Error('server unavailable');
browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox','--disable-dev-shm-usage']});const context=await browser.newContext({viewport:{width:Number(process.env.QA_WIDTH||390),height:844},reducedMotion:'reduce'});await context.route('https://fonts.googleapis.com/**',r=>r.fulfill({contentType:'text/css',body:'body{font-family:Arial}'}));const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(base+'/demo/',{waitUntil:'networkidle'});await page.evaluate(async()=>{await go('folha',{first:true});await openHR(1)});
for(const [field,value] of [['payroll_holidays','2026-02-31'],['reference_monthly_hours','-1']]){
await page.locator('[data-profile="pay_basis"]').selectOption('hourly');
await page.locator('[data-profile="hourly_rate"]').fill('20');
await page.locator(`[data-profile="${field}"]`).fill(value);
await page.locator('[data-profile="pay_basis"]').selectOption('monthly');
const responseWait=page.waitForResponse(r=>r.url()===base+'/demo/employees/1/payroll-profile'&&r.request().method()==='PUT');
await page.getByRole('button',{name:'Salvar dados de RH',exact:true}).click();
const response=await responseWait;assert.equal(response.status(),200);assert.notEqual(response.request().postDataJSON()[field],value);
await page.locator('#taskOverlay').waitFor({state:'hidden'});
result.push({case:'disabled-hourly-draft-'+field,status:response.status()});
await page.evaluate(()=>openHR(1));
}
let started;const startedWait=new Promise(r=>started=r);await page.route('**/demo/employees/1/payroll-profile',async route=>{if(route.request().method()==='PUT'){started();await new Promise(r=>setTimeout(r,2000))}await route.continue()});
await page.locator('[data-profile="vt_amount"]').fill('111');const saved=page.waitForResponse(r=>r.url()===base+'/demo/employees/1/payroll-profile'&&r.request().method()==='PUT');await page.getByRole('button',{name:'Salvar dados de RH',exact:true}).click();await startedWait;
await page.getByRole('button',{name:'Fechar',exact:true}).click();
const second=page.locator('[data-k="e2"]');await second.locator('summary').first().click();await second.getByRole('button',{name:'Benefícios e férias',exact:true}).click();await page.locator('[data-profile="vt_amount"]').fill('333');
const before={title:await page.locator('#taskModalTitle').innerText(),typed:await page.locator('[data-profile="vt_amount"]').inputValue(),visible:await page.locator('#taskOverlay').isVisible()};
const firstSaved=await saved;await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Dados de RH salvos para'));assert.equal(await page.locator('#taskOverlay').isVisible(),true);assert.equal(await page.locator('[data-profile=vt_amount]').inputValue(),'333');const after={firstSaved:firstSaved.status(),visible:await page.locator('#taskOverlay').isVisible(),secondProfile:await page.evaluate(()=>api('/employees/2/payroll-profile')),toast:await page.locator('#toast').innerText()};result.push({case:'stale-save-preserves-new-employee-dialog',before,after});await page.screenshot({path:'/workspace/screenshots/banca3-stale-rh-save.png',fullPage:true});
assert.deepEqual(errors,[]);result.push({case:'page-errors',errors});writeFileSync('/tmp/banca3-confuso-race-evidence.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await context.close();
}finally{if(browser)await browser.close();server.kill('SIGTERM')}
