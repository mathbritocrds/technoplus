// Populated demo login with real API/database and production isolation.
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
 for(const [build,cwd] of [['dev',resolve('.')],['built',resolve('dist/sigi')]]){
  const root=mkdtempSync(resolve(tmpdir(),'sigi-demo-ui-')),base='http://127.0.0.1:18184';
  const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18184'],{cwd,env:{...process.env,DB_PATH:resolve(root,'production.db'),DEMO_DB_PATH:resolve(root,'demo.db'),SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let stderr='';server.stderr.on('data',chunk=>stderr+=chunk);
  try{
   let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}assert(ready,stderr);
   for(const [viewport,width] of [['desktop',1280],['mobile',390]]){
    const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
    await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:'body{font-family:Arial,sans-serif}'}));
    const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
    await page.goto(base,{waitUntil:'networkidle'});
    assert.equal(await page.locator('#ls').inputValue(),'');
    await page.getByRole('link',{name:'Explorar empresa de demonstração',exact:true}).click();
    await page.waitForURL('**/demo/');await page.locator('#main h1').waitFor();
    assert(await page.getByText(/Empresa de demonstração · todos os dados são fictícios/).isVisible());
    await page.evaluate(async()=>{await go('folha',{first:true})});
    await page.locator('.employee-name').filter({hasText:'Ana Lima'}).first().waitFor();
    const demoToken=await page.evaluate(()=>sessionStorage.getItem('tk-demo'));
    assert(demoToken);assert.equal(await page.evaluate(()=>sessionStorage.getItem('tk')),null);
    const response=await fetch(base+'/demo/employees',{headers:{Authorization:'Bearer '+demoToken}});const employees=await response.json();assert.equal(employees.length,6);assert(employees.every(row=>row.salary>0));
    assert((await fetch(base+'/demo/time-entries/verify',{headers:{Authorization:'Bearer '+demoToken}})).ok);
    assert.deepEqual(await (await fetch(base+'/auth/status')).json(),{setup_required:true});
    assert.equal((await fetch(base+'/employees',{headers:{Authorization:'Bearer '+demoToken}})).status,401);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Demo should fit mobile');
    await page.screenshot({path:resolve(output,`demo-${build}-${viewport}.png`),fullPage:true});
    await page.evaluate(async()=>{await go('contabilidade',{first:true})});await page.locator('#accountingRoot').waitFor();
    await page.getByRole('link',{name:'Voltar ao acesso da empresa',exact:true}).click();await page.waitForURL(base+'/');await page.locator('#ls').waitFor();
    assert.deepEqual(errors,[]);verdict.push({build,viewport,ok:true,employees:employees.length,flows:['demo-login','populated-payroll','accounting','session-isolation','production-untouched','return-login']});
    await context.close();
   }
  }finally{server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve))}
 }
}finally{await browser.close()}
console.log(JSON.stringify(verdict,null,2));
