// Rename through the real form and check the same person in other modules.
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
  const root=mkdtempSync(resolve(tmpdir(),'sigi-rename-ui-')),base='http://127.0.0.1:18188';
  const server=spawn('python',['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18188'],{cwd,env:{...process.env,DB_PATH:resolve(root,'production.db'),DEMO_DB_PATH:resolve(root,'demo.db'),SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let stderr='';server.stderr.on('data',chunk=>stderr+=chunk);
  try{
   let ready=false;for(let i=0;i<80;i++){try{if((await fetch(base+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,100))}assert(ready,stderr);
   const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   // Only external font delivery is replaced; API and persistence are real.
   await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:'body{font-family:Arial,sans-serif}'}));
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
   await page.goto(base+'/demo/',{waitUntil:'networkidle'});await page.locator('#main h1').waitFor();
   await page.evaluate(async()=>{await go('folha',{first:true})});
   const person=page.locator('[data-k="e1"]');await person.locator('summary').first().click();
   await person.getByRole('button',{name:'Editar cadastro',exact:true}).click();
   await page.locator('#en').fill('Ana Torres');
   const saved=page.waitForResponse(response=>response.url()===base+'/demo/employees/1'&&response.request().method()==='PATCH');
   await page.getByRole('button',{name:'Salvar cadastro',exact:true}).click();assert((await saved).ok());
   await page.locator('#taskOverlay').waitFor({state:'hidden'});await page.locator('.employee-name').filter({hasText:'Ana Torres'}).waitFor();
   await page.evaluate(async()=>{await go('quadros',{first:true})});
   assert((await page.locator('[data-k="t1"]').innerText()).includes('Ana Torres'));
   assert(!(await page.locator('[data-k="t1"]').innerText()).includes('Ana Lima'));
   await page.evaluate(async()=>{await go('departamentos',{first:true})});
   assert((await page.locator('#main').innerText()).includes('Ana Torres'));
   await page.evaluate(async()=>{await go('financeiro',{first:true})});
   await page.getByRole('cell').filter({hasText:'Salário fictício · Ana Torres'}).waitFor();
   await page.screenshot({path:resolve(output,`employee-rename-${build}-${viewport}.png`),fullPage:true});
   assert.deepEqual(errors,[]);
   verdict.push({build,viewport,ok:true,flows:['rename-form','payroll-current-name','task-owner-preserved','department-lead','finance-current-name']});await context.close();
  }finally{server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve))}
 }
}finally{await browser.close()}
console.log(JSON.stringify(verdict,null,2));
