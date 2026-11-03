// A mounted deployment and encoded URL must not turn a real session into a demo session.
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
  const directory=mkdtempSync(resolve(tmpdir(),'sigi-routing-qa-')),base='http://127.0.0.1:18186',prefix='/corp';
  const program="from fastapi import FastAPI; from app.main import app; import uvicorn; outer=FastAPI(); outer.mount('/corp',app); uvicorn.run(outer,host='127.0.0.1',port=18186)";
  const server=spawn('python',['-c',program],{cwd,env:{...process.env,DB_PATH:resolve(directory,'real.db'),DEMO_DB_PATH:resolve(directory,'demo.db'),SUPABASE_DATABASE_URL:''},stdio:['ignore','ignore','pipe']});
  let serverErrors='';server.stderr.on('data',chunk=>serverErrors+=chunk);
  try{
   let ready=false;for(let attempt=0;attempt<80;attempt++){try{if((await fetch(base+prefix+'/auth/status')).ok){ready=true;break}}catch{}await new Promise(resolve=>setTimeout(resolve,100))}assert(ready,serverErrors);
   const registration=await fetch(base+prefix+'/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'real@routing.example',password:'routing-password',company_name:'Real routing installation'})});
   const account=await registration.json();assert(registration.ok,JSON.stringify(account));
   const realHeaders={'Content-Type':'application/json',Authorization:'Bearer '+account.token};
   const created=await fetch(base+prefix+'/employees',{method:'POST',headers:realHeaders,body:JSON.stringify({name:'Real routing employee',salary:1234,pin:'1234',hired_on:'2024-01-01'})});assert(created.ok);
   for(const [viewport,width] of [['desktop',1280],['mobile',390]]){
    const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
    await context.route('https://fonts.googleapis.com/**',route=>route.fulfill({contentType:'text/css',body:'body{font-family:Arial,sans-serif}'}));
    await context.addInitScript(({token})=>{sessionStorage.setItem('tk',token);sessionStorage.setItem('tk@/corp',token);sessionStorage.setItem('role@/corp','admin');sessionStorage.setItem('name@/corp','Real routing account')},{token:account.token});
    const page=await context.newPage(),errors=[],leakedRealAuthorization=[];
    page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())});
    page.on('request',request=>{if(request.url().startsWith(base+prefix+'/demo/')&&request.headers().authorization==='Bearer '+account.token)leakedRealAuthorization.push(request.url())});
    await page.goto(base+prefix+'/%64emo/',{waitUntil:'networkidle'});await page.locator('#main h1').waitFor();
    assert.deepEqual(await page.evaluate(()=>globalThis.SIGI_CONTEXT),{basePath:prefix,demo:true});
    assert(await page.getByText(/Empresa de demonstração · todos os dados são fictícios/).isVisible());
    await page.evaluate(async()=>{await go('folha',{first:true})});await page.locator('.employee-name').filter({hasText:'Ana Lima'}).first().waitFor();
    const selected=await page.evaluate(()=>({key:sessionKey('tk'),token:sessionStorage.getItem(sessionKey('tk')),real:sessionStorage.getItem('tk@/corp')}));
    assert(selected.key.includes('demo')&&selected.key.includes(prefix));assert(selected.token&&selected.token!==account.token);assert.equal(selected.real,account.token);
    const downloadWait=page.waitForEvent('download');await page.getByRole('button',{name:'Exportar funcionários (CSV)',exact:true}).click();const download=await downloadWait;assert.equal(download.suggestedFilename(),'funcionarios.csv');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:resolve(output,`demo-routing-${build}-${viewport}.png`),fullPage:true});
    assert.deepEqual(leakedRealAuthorization,[]);
    await page.getByRole('link',{name:'Voltar ao acesso da empresa',exact:true}).click();await page.waitForURL(base+prefix+'/');
    assert.deepEqual(await page.evaluate(()=>globalThis.SIGI_CONTEXT),{basePath:prefix,demo:false});
    assert.equal(await page.evaluate(()=>sessionStorage.getItem(sessionKey('tk'))),account.token);
    const realStaff=await (await fetch(base+prefix+'/employees',{headers:realHeaders})).json();assert.deepEqual(realStaff.map(row=>[row.name,row.salary]),[['Real routing employee',1234]]);
    assert.deepEqual(errors,[]);verdict.push({build,viewport,ok:true,flows:['mounted-encoded-demo','real-token-not-sent-to-demo','independent-session','prefixed-export','return-to-real-installation']});await context.close();
   }
  }finally{server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve))}
 }
}finally{await browser.close()}
console.log(JSON.stringify(verdict,null,2));
