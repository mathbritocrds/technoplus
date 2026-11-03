import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const controls=readFileSync(new URL('../app/static/corporate-controls.js',import.meta.url),'utf8');
const business=readFileSync(new URL('../app/static/business.js',import.meta.url),'utf8');

test('rest-day input rejects empty comma tokens and duplicates instead of silently choosing Monday',()=>{
 const context=vm.createContext({});
 vm.runInContext(controls.slice(controls.indexOf(' function parsePolicyWeekdays('),controls.indexOf(' async function payrollControls(')),context);
 for(const input of ['',',','6,',' , 6','0,0','7','-1','1.5','texto'])assert.throws(()=>context.parsePolicyWeekdays(input));
 assert.deepEqual([...context.parsePolicyWeekdays('0, 6')],[0,6]);
 assert.deepEqual([...context.parsePolicyWeekdays(' 6 ')],[6]);
});

test('future payroll renderer tolerates legacy rules lacking optional offsets',async()=>{
 const payroll={month:'2027-01',closed:false,employees:[],total_net:0,total_accrual_cost:0};
 const annual={year:2027,employees:[],total_cost:0,total_net:0};
 const rules={inss:[[1000,.1],[2000,.2]],inss_max:300};
 const context=vm.createContext({TAB:{},S:{payrollMonth:'2027-01'},R:value=>'R$ '+Number(value).toFixed(2),
  dbr:value=>value,employeeCharts:()=>'',pctLabel:value=>value+'%',esc:value=>String(value),
  api:async path=>path.startsWith('/payroll/rules')?rules:path.startsWith('/payroll/annual')?annual:path.startsWith('/payroll?')?payroll:[]});
 vm.runInContext(business.slice(0,business.indexOf('function employeeChartData(')),context);
 const html=await context.TAB.folha();
 assert.match(html,/Funcionários e folha/);
 assert.match(html,/Tabela INSS · 2027/);
 assert.match(html,/Cálculo progressivo/);
 assert.ok(!html.includes('NaN'));
 rules.inss_offsets=[0,100];
 const normalized=await context.TAB.folha();
 assert.match(normalized,/R\$ 100\.00/);
});
