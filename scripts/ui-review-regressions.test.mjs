import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const html=readFileSync(new URL('../app/static/index.html',import.meta.url),'utf8');
const business=readFileSync(new URL('../app/static/business.js',import.meta.url),'utf8');
const section=(source,start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

test('rapid product edits patch independent fields without overwriting existing costs',async()=>{
 const product={id:1,name:'Produto',material:10,labor:0,overhead:0,price:30},pending=[],calls=[];
 const context=vm.createContext({P:[product],refresh:async()=>{},api:async(path,method,body)=>{calls.push({path,method,body});await new Promise(resolve=>pending.push(resolve));Object.assign(product,body)}});
 vm.runInContext(section(html,'async function edP(','async function addP('),context);
 const first=context.edP(0,'material','20'),second=context.edP(0,'price','50');
 assert.deepEqual(calls.map(c=>[c.method,Object.keys(c.body)]),[['PATCH',['material']],['PATCH',['price']]]);
 pending[1]();pending[0]();await Promise.all([first,second]);
 assert.equal(product.material,20);assert.equal(product.price,50);
});

test('blank or invalid product prices are rejected instead of silently stored as zero',async()=>{
 let calls=0;const context=vm.createContext({P:[{id:1}],api:async()=>calls++,refresh:async()=>{}});
 vm.runInContext(section(html,'async function edP(','async function addP('),context);
 for(const value of ['', '   ','texto','Infinity','-1'])await assert.rejects(context.edP(0,'price',value),/valor numérico/);
 assert.equal(calls,0);await context.edP(0,'price','0');assert.equal(calls,1);
});

test('employee edits reject a whitespace-only name',()=>{
 const context=vm.createContext({$:()=>({value:'   '})});
 vm.runInContext(section(business,'function employeePayload(','async function createEmployee('),context);
 assert.throws(()=>context.employeePayload(),/nome do funcionário/);
});

test('integration handlers contain numeric IDs only while user text remains data',async()=>{
 const integration={id:7,name:"');globalThis.attacked=true;//",kind:'webhook',endpoint:"https://example.test/');alert(1)//",active:true};
 let sent;
 const context=vm.createContext({S:{},INT:{webhook:'Webhook'},esc,refresh:async()=>{},api:async(path,method,body)=>{if(method){sent=body;return {ok:true}}return [integration]}});
 vm.runInContext(section(html,'async function integracao(){','async function addI(')+section(html,'async function tgI(','async function delI('),context);
 const rendered=await context.integracao();
 const handlers=[...rendered.matchAll(/onclick="([^"]*)"/g)].map(match=>match[1]);
 assert.ok(handlers.includes('run(()=>tgI(7,0),this)'));
 assert.ok(handlers.every(handler=>!handler.includes('attacked')&&!handler.includes('example.test')));
 assert.ok(rendered.includes(esc(integration.name)));await context.tgI(7,0);
 assert.equal(sent.name,integration.name);assert.equal(sent.endpoint,integration.endpoint);assert.equal(sent.active,false);
});

test('base spaces renderer supplies capacity, sharing and event fields without HTML rewriting',async()=>{
 const space={id:1,name:'Sala',kind:'sala',capacity:12,allow_shared:true,admin_email:''};
 const context=vm.createContext({URLSearchParams,S:{spaceMonth:'2026-11'},ROLE:'admin',KND:{sala:'Sala'},esc,api:async path=>path==='/spaces'?[space]:[]});
 vm.runInContext(section(html,'async function espacos(){','function shiftSpaceMonth('),context);
 const rendered=await context.espacos();
 for(const marker of ['data-capacity','data-shared','id="spaceCapacity"','id="spaceShared"','id="bookingAttendees"','id="bookingExclusive"','id="bookingCompatibility"'])assert.ok(rendered.includes(marker),marker);
 assert.match(rendered,/data-capacity[^>]*value="12"/);
 assert.match(rendered,/option value="1" selected>Permitir eventos compatíveis/);
});

test('base finance renderer supplies accounting category and competence fields',async()=>{
 const summary={payroll_unavailable_months:[],fluxo:[]},costs={departments:[],totals:{}};
 const context=vm.createContext({S:{financeRequest:1},esc,cnt:()=>'',R:()=>'',financeToolbar:()=>'',financeAccountParams:()=>'',api:async path=>path.startsWith('/finance/summary')?summary:path.startsWith('/finance/department-costs')?costs:[]});
 const categories=html.split('\n').find(line=>line.startsWith('const financialCategories'));
 vm.runInContext(categories+'\n'+section(html,'async function financeiro(','async function exportFinanceCsv('),context);
 const rendered=await context.financeiro({params:new URLSearchParams(),month:'2026-11',label:'Novembro'},1);
 assert.match(rendered,/<select id="fcategory"/);assert.match(rendered,/<input id="fcompetence"[^>]*value="2026-11"/);
 assert.match(rendered,/<option value="operating" selected>/);
});
