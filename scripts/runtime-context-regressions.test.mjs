import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const html=readFileSync(new URL('../app/static/index.html',import.meta.url),'utf8');
const runtime=html.slice(html.indexOf('const RUNTIME_CONTEXT='),html.indexOf('let TOKEN='));
function browser(metadata,pathname){
 const requests=[];
 const context=vm.createContext({SIGI_CONTEXT:metadata,location:{pathname},fetch:(path,options)=>{requests.push({path,options});return Promise.resolve({ok:true})}});
 vm.runInContext(runtime,context);
 return {context,requests};
}

test('encoded demonstration URLs use the server realm rather than the address spelling',async()=>{
 const {context,requests}=browser({basePath:'/corp',demo:true},'/corp/%64emo/');
 await context.sigiApiFetch('/employees');
 assert.equal(requests[0].path,'/corp/demo/employees');
 assert.equal(vm.runInContext("sessionKey('tk')",context),'tk-demo@/corp');
});

test('real and demonstration sessions remain separate within a deployment mount',async()=>{
 const real=browser({basePath:'/corp',demo:false},'/corp/');
 const demo=browser({basePath:'/corp',demo:true},'/corp/demo/');
 await real.context.sigiApiFetch('/employees');await demo.context.sigiApiFetch('/employees');
 assert.equal(real.requests[0].path,'/corp/employees');
 assert.notEqual(vm.runInContext("sessionKey('tk')",real.context),vm.runInContext("sessionKey('tk')",demo.context));
 assert.equal(vm.runInContext("sessionKey('tk')",browser({basePath:'',demo:false},'/').context),'tk');
});

test('a page missing server routing context cannot send requests or reuse a real session',()=>{
 const {context,requests}=browser(undefined,'/%64emo/');
 assert.throws(()=>context.sigiApiFetch('/employees'),/Recarregue a página/);
 assert.equal(requests.length,0);
 assert.notEqual(vm.runInContext("sessionKey('tk')",context),'tk');
 assert.notEqual(vm.runInContext("sessionKey('tk')",context),'tk-demo');
});

test('disabling 2FA sends the current password as well as the authenticator code',async()=>{
 let submitted;
 const context=vm.createContext({$:selector=>({value:selector==='#totpDisableCode'?' 123456 ':'current-password'}),api:async(path,method,body)=>{submitted={path,method,body}},toast:()=>{},refresh:async()=>{}});
 const start=html.indexOf('async function disableTotp()');
 const source=html.slice(start,html.indexOf('\n',start));
 vm.runInContext(source,context);await context.disableTotp();
 assert.equal(submitted.path,'/auth/2fa/disable');assert.equal(submitted.method,'POST');
 assert.equal(submitted.body.code,'123456');assert.equal(submitted.body.current_password,'current-password');
});
