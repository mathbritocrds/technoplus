// Optional asset authoring: requires an environment with @oai/artifact-tool.
import fs from 'node:fs/promises';
import {resolve} from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const outputDir=resolve('app/templates');
const wb=Workbook.create(),sheet=wb.worksheets.add('Gastos por setor');
sheet.showGridLines=false;
sheet.getRange('A1:P14').format.font={name:'Arial',size:11,color:'#202020'};
sheet.getRange('A1:P14').format.rowHeight=23;
sheet.getRange('A:A').format.columnWidth=28;sheet.getRange('B:B').format.columnWidth=32;
sheet.getRange('C:N').format.columnWidth=14;sheet.getRange('O:O').format.columnWidth=18;sheet.getRange('P:P').format.columnWidth=13;
sheet.getRange('A2').values=[['Gastos por setor']];sheet.getRange('A2').format.font={name:'Arial',size:16,bold:true,color:'#72370E'};
sheet.getRange('A3').values=[['Período e setor selecionados na consulta']];sheet.getRange('A3:P3').format.font={name:'Arial',size:10,color:'#72370E'};
const headers=[['Setor','Categoria','Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez','Total','% gastos']];
for(const row of [5,12]){sheet.getRange(`A${row}:P${row}`).values=headers;sheet.getRange(`A${row}:P${row}`).format={fill:'#72370E',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:26,horizontalAlignment:'center'};}
sheet.getRange('A6:B6').values=[['Setor','Total do setor']];sheet.getRange('C6:N6').values=[[0,0,0,0,0,0,0,0,0,0,0,0]];sheet.getRange('O6').formulas=[['=SUM(C6:N6)']];sheet.getRange('P6').formulas=[['=IF($O$7=0,"",O6/$O$7)']];
sheet.getRange('A7').values=[['Total dos gastos']];sheet.getRange('C7:O7').formulas=[Array.from({length:13},(_,i)=>`=SUM(${String.fromCharCode(67+i)}6:${String.fromCharCode(67+i)}6)`)];sheet.getRange('P7').formulas=[['=IF(O7=0,"",1)']];
sheet.getRange('A10').values=[['Detalhamento por categoria']];sheet.getRange('A10').format.font={name:'Arial',size:13,bold:true,color:'#72370E'};
sheet.getRange('A13:B13').values=[['Setor','Categoria']];sheet.getRange('C13:N13').values=[[0,0,0,0,0,0,0,0,0,0,0,0]];sheet.getRange('O13').formulas=[['=SUM(C13:N13)']];sheet.getRange('P13').formulas=[['=IF($O$14=0,"",O13/$O$14)']];sheet.getRange('A14').values=[['Total por categoria']];
for(const row of [7,14])sheet.getRange(`A${row}:P${row}`).format={fill:'#FFCA96',font:{name:'Arial',size:11,bold:true,color:'#72370E'},rowHeight:26};
sheet.getRange('C6:O14').setNumberFormat('"R$" #,##0.00;[Red]("R$" #,##0.00);"-"');sheet.getRange('P6:P14').setNumberFormat('0.00%');
sheet.freezePanes.freezeRows(5);
wb.recalculate();
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:10},maxChars:1000})).ndjson);
await fs.mkdir(outputDir,{recursive:true});
const out=await SpreadsheetFile.exportXlsx(wb);
await out.save(resolve(outputDir,'dre-sector-layout.xlsx'));
console.log('Sector layout saved. The original user-supplied model is kept separately.');
