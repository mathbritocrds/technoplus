import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const business=readFileSync(new URL('../app/static/business.js',import.meta.url),'utf8');
const enhancements=readFileSync(new URL('../app/static/enhancements.js',import.meta.url),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
test('annual employee chart reconciles cost without adding withheld INSS again',()=>{
 const context=vm.createContext({esc,R:value=>'R$ '+Number(value).toFixed(2),pctLabel:value=>value+'%'});
 vm.runInContext(business.slice(business.indexOf('function hrHours('),business.indexOf('function employeeChartData(')),context);
 const employee={id:7,name:'<Ana>',salary:36000,benefits:1200,fgts:2880,employer_charges:7200,
  thirteenth:3000,vacation:4000,vacation_salary_offset:3000,provisions:5120,total:52400,inss:3040.92,irrf:0,worked_hours:0,cost_per_worked_hour:null};
 const parts=context.annualEmployeeParts(employee);
 assert.equal(parts.reduce((sum,part)=>sum+part.value,0),employee.total);
 assert(!parts.some(part=>part.label.includes('INSS')));
 const rendered=context.annualEmployeeComposition({year:2026,employees:[employee]},7);
 assert(rendered.includes('R$ 3040.92'));assert(rendered.includes('&lt;Ana&gt;'));assert(!rendered.includes('<Ana>'));
 assert(rendered.includes('Sem horas concluídas'));assert(!rendered.includes('NaN'));
 employee.id=8;assert(context.annualEmployeeComposition({year:2026,employees:[employee]},7).includes('data-annual-chart="8"'));
});
test('Inter web table uses model month cells and subtotal signs literally',()=>{
 const context=vm.createContext({esc,R:value=>'R$ '+Number(value).toFixed(2),dbr:value=>value,pctLabel:value=>value==null?'—':value+'%'});
 vm.runInContext(enhancements.slice(enhancements.indexOf('function interDreTable('),enhancements.indexOf('async function dreView(')),context);
 const html=context.interDreTable({months:['2026-06'],rows:[{key:'financial_result',label:'(+/-) Receitas/despesas diversas',subtotal:false,months:{'2026-06':-200},amount:-200,revenue_pct:null}]});
 assert(html.includes('R$ -200.00'));assert(html.includes('2026-06'));assert(html.includes('Total do período'));
 assert(!html.includes('NaN'));assert(!html.includes('Obrigatório'));
});
test('monthly contract disables hidden hourly inputs so their default zero cannot block saving',()=>{
 const fields=[{disabled:false},{disabled:false}],box={hidden:false,querySelectorAll:()=>fields};
 const context=vm.createContext({$:()=>box});
 vm.runInContext(business.slice(business.indexOf('function toggleHourlyContract('),business.indexOf('async function openHR(')),context);
 context.toggleHourlyContract('monthly');assert(box.hidden);assert(fields.every(field=>field.disabled));
 context.toggleHourlyContract('hourly');assert(!box.hidden);assert(fields.every(field=>!field.disabled));
});
