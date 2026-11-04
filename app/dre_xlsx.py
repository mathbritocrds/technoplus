"""Populate the supplied Inter workbook without rewriting its drawings or styles.

The application only needs Python's standard library: template authoring is done
ahead of deployment; this module binds scoped report data to the packaged model.
"""
import copy
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import HTTPException

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('', NS)
Q = lambda name: '{'+NS+'}'+name
MONTHS = ('Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez')
CATEGORIES = {'revenue':'Receitas operacionais','tax':'Impostos e deduções',
              'cost':'Custos diretos','operating':'Despesas operacionais',
              'personnel':'Pessoal, encargos e provisões','financial':'Despesas financeiras'}
ORIGINS = {'transaction':'Conta','payroll':'Folha fechada','payroll_adjustment':'Complemento de folha','import':'Importação'}
TEMPLATES = Path(__file__).parent/'templates'


def amount(value):
    return Decimal(str(value)).quantize(Decimal('.01'))


class Sheet:
    def __init__(self, xml):
        self.xml = xml.decode() if isinstance(xml, bytes) else xml
        self.root = ET.fromstring(self.xml)
        self.data = self.root.find(Q('sheetData'))
        self.rows = {int(row.get('r')): row for row in self.data}
        self.cells = {cell.get('r'): cell for row in self.data for cell in row if cell.tag == Q('c')}

    def cell(self, reference, style=None):
        if reference not in self.cells:
            number = int(re.search(r'\d+',reference).group())
            row = self.rows.get(number)
            if row is None:
                row=ET.SubElement(self.data,Q('row'),{'r':str(number)})
                self.rows[number]=row
            self.cells[reference]=ET.SubElement(row,Q('c'),{'r':reference})
        cell=self.cells[reference]
        if style is not None: cell.set('s',str(style))
        return cell

    def set(self, reference, value=None, formula=None, style=None):
        cell=self.cell(reference,style)
        for tag in ('f','v','is'):
            for child in list(cell.findall(Q(tag))): cell.remove(child)
        cell.attrib.pop('t',None)
        if formula is not None:
            ET.SubElement(cell,Q('f')).text=formula.lstrip('=')
            if value is None:
                cell.set('t','str');ET.SubElement(cell,Q('v')).text=''
            else: ET.SubElement(cell,Q('v')).text=str(value)
        elif isinstance(value,str):
            cell.set('t','inlineStr')
            ET.SubElement(ET.SubElement(cell,Q('is')),Q('t'),{'{http://www.w3.org/XML/1998/namespace}space':'preserve'}).text=value
        elif value is not None:
            ET.SubElement(cell,Q('v')).text=str(value)

    def export(self, last=None):
        for row in self.data:
            row[:] = sorted(row,key=lambda c:(len(re.sub(r'\d','',c.get('r',''))),re.sub(r'\d','',c.get('r',''))))
        self.data[:] = sorted(self.data,key=lambda r:int(r.get('r')))
        result=re.sub(r'<(?:[\w]+:)?sheetData\b[^>]*>[\s\S]*?</(?:[\w]+:)?sheetData>',ET.tostring(self.data,encoding='unicode'),self.xml,count=1)
        if last: result=re.sub(r'<(?:[\w]+:)?dimension\b[^>]*/>',f'<dimension ref="A1:{last}"/>',result,count=1)
        return result.encode()


def replace_section(xml, tag, node):
    return re.sub(fr'<{tag}\b[^>]*>[\s\S]*?</{tag}>',ET.tostring(node,encoding='unicode'),xml,count=1)


def merge_sector_styles(original, additional):
    """Append the authored sector styles; preserve all original style indices."""
    target,source=ET.fromstring(original),ET.fromstring(additional)
    xml=original.decode();maps={}
    for name in ('fonts','fills','borders'):
        a,b=target.find(Q(name)),source.find(Q(name));offset=len(a)
        maps[name]={i:offset+i for i in range(len(b))}
        a.extend(copy.deepcopy(list(b)));a.set('count',str(len(a)))
        xml=replace_section(xml,name,a)
    a,b=target.find(Q('numFmts')),source.find(Q('numFmts'))
    by_code={item.get('formatCode'):int(item.get('numFmtId')) for item in a}
    fmtmap={};next_fmt=max([163,*[int(item.get('numFmtId')) for item in a]])+1
    if b is not None:
        for item in b:
            code=item.get('formatCode');new_id=by_code.get(code)
            if new_id is None:
                new_id=next_fmt;next_fmt+=1;by_code[code]=new_id
                clone=copy.deepcopy(item);clone.set('numFmtId',str(new_id));a.append(clone)
            fmtmap[int(item.get('numFmtId'))]=new_id
    a.set('count',str(len(a)));xml=replace_section(xml,'numFmts',a)
    a,b=target.find(Q('cellXfs')),source.find(Q('cellXfs'));offset=len(a)
    for item in b:
        clone=copy.deepcopy(item)
        for attr,collection in [('fontId','fonts'),('fillId','fills'),('borderId','borders')]:clone.set(attr,str(maps[collection][int(clone.get(attr,'0'))]))
        old_fmt=int(clone.get('numFmtId','0'));clone.set('numFmtId',str(fmtmap.get(old_fmt,old_fmt)));clone.set('xfId','0');a.append(clone)
    a.set('count',str(len(a)));xml=replace_section(xml,'cellXfs',a)
    return xml.encode(),{i:offset+i for i in range(len(b))}


def summary_labels():
    return {'B5':'(+) Receita operacional','B6':'Receitas operacionais','B9':'Impostos e deduções',
            'B14':'(-) Custos diretos','B22':'Despesas operacionais',
            'B31':'Pessoal, encargos e provisões','B37':'Despesas financeiras'}


def fill_month(xml, index, entries, year, sector_labels):
    sheet=Sheet(xml);header=14 if index==0 else 10;first=header+1
    last=max(804 if index==0 else 800,first+len(entries)-1)
    styles={column:sheet.cell(column+str(first)).get('s','0') for column in 'BCDEFGHI'}
    for row in range(first,last+1):
        for col in 'BCDEFGH':sheet.set(col+str(row),style=styles[col])
    totals=defaultdict(Decimal);running=Decimal(0)
    for offset,entry in enumerate(entries):
        row=first+offset;value=amount(entry['amount']);key=entry['category'];totals[key]+=value
        signed=value if key=='revenue' else -value;running+=signed
        data=[(date(year,index+1,1)-date(1899,12,30)).days,entry['description'],
              'Receita' if key=='revenue' else 'Despesa',value,CATEGORIES[key],sector_labels[entry['department_id']],ORIGINS[entry['origin']]]
        for col,v in zip('BCDEFGH',data):sheet.set(col+str(row),v,style=styles[col])
    running=Decimal(0)
    for row in range(first,last+1):
        if row-first<len(entries):
            entry=entries[row-first];running+=amount(entry['amount'])*(1 if entry['category']=='revenue' else -1)
        base='0' if row==first else f'I{row-1}'
        sheet.set(f'I{row}',running,f'{base}+IF(D{row}="Receita",E{row},IF(D{row}="Despesa",-E{row},0))',styles['I'])
    for col,label in zip('BCDEFGHI',['Competência','Descrição','Conta','Valor','Categoria SIGI','Setor','Origem','Resultado acumulado']):sheet.set(col+str(header),label)
    balance_row=9 if index==0 else 7
    for col,label in [('B','Resultado inicial'),('C','Receitas'),('D','Despesas'),('F','Resultado acumulado'),('G','Resultado do mês')]:sheet.set(col+str(balance_row-1),label)
    sheet.set('B'+str(balance_row),0)
    revenue=totals['revenue'];expenses=sum(value for key,value in totals.items() if key!='revenue')
    sheet.set('C'+str(balance_row),revenue,f'SUMIFS(E{first}:E{last},D{first}:D{last},"Receita")')
    sheet.set('D'+str(balance_row),expenses,f'SUMIFS(E{first}:E{last},D{first}:D{last},"Despesa")')
    sheet.set('F'+str(balance_row),revenue-expenses,f'I{last}')
    sheet.set('G'+str(balance_row),revenue-expenses,f'C{balance_row}-D{balance_row}')
    sheet.set('B4',f'{MONTHS[index]} / {year}')
    if index==0:
        sheet.set('B6','Base: competência dos lançamentos');sheet.set('C6','Resultado contábil; não representa saldo bancário.')
        sheet.set('F6','Resultado acumulado do mês.');sheet.set('G6','Receitas menos despesas.')
    # The supplied leaf classifications are not present in SIGI. Aggregate only
    # known categories, without guessing whether a description is water or rent.
    for text_col,value_col,length in [('N','O',2),('Q','R',2),('T','U',11),('W','X',4),('Z','AA',4),('AC','AD',4)]:
        for offset in range(1,length+1):sheet.set(text_col+str(header+offset),'');sheet.set(value_col+str(header+offset),0)
    destinations={'revenue':('N','O',1),'tax':('AC','AD',1),'operating':('T','U',1),'personnel':('T','U',10),'financial':('Z','AA',1)}
    for key,(text_col,value_col,offset) in destinations.items():
        sheet.set(text_col+str(header+offset),CATEGORIES[key])
        sheet.set(value_col+str(header+offset),totals[key],f'SUMIFS($E${first}:$E${last},$F${first}:$F${last},{text_col}{header+offset})')
    for col,length in [('O',2),('R',2),('U',11),('X',4),('AA',4),('AD',4)]:
        value=sum(totals[k] for k,d in destinations.items() if d[1]==col)
        sheet.set(col+str(header),value,f'SUM({col}{header+1}:{col}{header+length})')
    gross=revenue-totals['tax']-totals['cost'];operating=gross-totals['operating']-totals['personnel']
    data={0:(revenue,f'O{header}'),1:(totals['tax'],f'AD{header}'),2:(revenue-totals['tax'],f'L{header}-L{header+1}'),
          3:(totals['cost'],f'SUMIFS($E${first}:$E${last},$F${first}:$F${last},"{CATEGORIES["cost"]}")'),
          4:(gross,f'L{header+2}-L{header+3}'),5:(Decimal(0),f'X{header}'),6:(totals['operating']+totals['personnel'],f'U{header}'),
          7:(operating,f'L{header+4}-L{header+5}-L{header+6}'),8:(-totals['financial'],f'R{header}-AA{header}'),9:(revenue-expenses,f'L{header+7}+L{header+8}')}
    for offset,(value,formula) in data.items():sheet.set('L'+str(header+offset),value,formula)
    sheet.set('K'+str(header),'(+) Receita operacional');sheet.set('K'+str(header+3),'(-) Custos diretos')
    # Only the export's new category field is validated; original payment/dropdown
    # validations would reject these different, explicitly labeled source fields.
    result=sheet.export('AE'+str(max(last,1025)))
    result=re.sub(rb'<dataValidations\b[^>]*>[\s\S]*?</dataValidations>',b'',result)
    return result,last,dict(totals)


def sector_sheet(layout, style_map, report, sector_labels, month_ends):
    sheet=Sheet(layout);styles={ref:style_map[int(cell.get('s','0'))] for ref,cell in sheet.cells.items()}
    sheet.data.clear();sheet.rows={};sheet.cells={}
    groups=defaultdict(lambda:defaultdict(Decimal));details=defaultdict(lambda:defaultdict(Decimal))
    for entry in report['entries']:
        if entry['category']=='revenue':continue
        month=int(entry['month'][5:]);value=amount(entry['amount'])
        groups[entry['department_id']][month]+=value;details[(entry['department_id'],entry['category'])][month]+=value
    ids=sorted(groups,key=lambda key:(sector_labels[key],key or 0))
    detail_ids=sorted(details,key=lambda key:(sector_labels[key[0]],key[0] or 0,key[1]))
    top_total=6+max(1,len(ids));detail_title=top_total+3;detail_header=detail_title+2;detail_first=detail_header+1;detail_total=detail_first+max(1,len(detail_ids))
    sheet.set('A2','Gastos por setor',style=styles['A2'])
    sheet.set('A3',f"Período: {report['start']} a {report['end']} · {report['scope_label']}",style=styles['A3'])
    headers=['Setor','Categoria',*MONTHS,'Total','% gastos']
    for row in [5,detail_header]:
        sheet.rows[row]=ET.SubElement(sheet.data,Q('row'),{'r':str(row),'ht':'26','customHeight':'1'})
        for index,label in enumerate(headers):sheet.set(chr(65+index)+str(row),label,style=styles[chr(65+index)+'5'])
    sheet.set('A'+str(detail_title),'Detalhamento por categoria',style=styles['A10'])
    def exact(reference):return '"="&SUBSTITUTE(SUBSTITUTE(SUBSTITUTE('+reference+',"~","~~"),"*","~*"),"?","~?")'
    def rows(items,first,total,detail=False):
        for offset,key in enumerate(items):
            row=first+offset;did,category=key if detail else (key,None);values=details[key] if detail else groups[key]
            sheet.set('A'+str(row),sector_labels[did],style=styles['A6']);sheet.set('B'+str(row),CATEGORIES[category] if detail else 'Total do setor',style=styles['B6'])
            for month in range(1,13):
                col=chr(66+month);data_first=15 if month==1 else 11;last=month_ends[month-1];name=MONTHS[month-1]
                formula=f'SUMIFS(\'{name}\'!$E${data_first}:$E${last},\'{name}\'!$G${data_first}:$G${last},{exact("$A"+str(row))},\'{name}\'!$D${data_first}:$D${last},"Despesa"'
                if detail:formula+=f',\'{name}\'!$F${data_first}:$F${last},$B{row}'
                sheet.set(col+str(row),values[month],formula+')',styles[col+'6'])
            value=sum(values.values());sheet.set('O'+str(row),value,f'SUM(C{row}:N{row})',styles['O6'])
            grand=sum(sum(v.values()) for v in groups.values())
            sheet.set('P'+str(row),value/grand if grand else None,f'IF($O${top_total}=0,"",O{row}/$O${top_total})',styles['P6'])
        if not items:sheet.set('A'+str(first),'Sem gastos no período',style=styles['A6'])
        sheet.set('A'+str(total),'Total por categoria' if detail else 'Total dos gastos',style=styles['A7'])
        for index in range(2,15):
            col=chr(65+index)
            value=sum(sum(v.values()) if col=='O' else v[index-1] for v in (details.values() if detail else groups.values()))
            sheet.set(col+str(total),value,f'SUM({col}{first}:{col}{total-1})',styles[col+'7'])
        grand=sum(sum(v.values()) for v in groups.values())
        sheet.set('P'+str(total),Decimal(1) if grand else None,f'IF(O{total}=0,"",1)',styles['P7'])
    rows(ids,6,top_total);rows(detail_ids,detail_first,detail_total,True)
    result=sheet.export('P'+str(detail_total)).decode()
    result=result.replace('</sheetData>',f'</sheetData><autoFilter ref="A{detail_header}:P{detail_total-1}"/>',1)
    return result.encode()


def export_workbook(report, company_name='SIGI'):
    if report['start'][:4]!=report['end'][:4]:raise HTTPException(400,'O modelo é anual. Exporte um ano por vez.')
    year=int(report['start'][:4]);monthly=defaultdict(list)
    unique={entry['department_id']:entry['department'] for entry in report['entries']}
    counts=Counter(unique.values());labels={};used=set()
    for key,name in sorted(unique.items(),key=lambda item:item[0] or 0):
        label=name+(f' (ID {key})' if counts[name]>1 and key is not None else '')
        while label in used:label+=f' (ID {key})'
        labels[key]=label;used.add(label)
    for entry in report['entries']:monthly[int(entry['month'][5:])].append(entry)
    with zipfile.ZipFile(TEMPLATES/'dre-inter-empresas.xlsx') as original,zipfile.ZipFile(TEMPLATES/'dre-sector-layout.xlsx') as layout:
        changes={};month_ends=[];totals=[]
        for index in range(12):
            path=f'xl/worksheets/sheet{index+4}.xml'
            data,last,values=fill_month(original.read(path),index,monthly[index+1],year,labels)
            changes[path]=data;month_ends.append(last);totals.append(values)
        annual=Sheet(original.read('xl/worksheets/sheet3.xml'))
        month_cells=[Sheet(changes[f'xl/worksheets/sheet{index+4}.xml']).cells for index in range(12)]
        annual.set('B4',f'DRE · {year}')
        for ref,label in summary_labels().items():annual.set(ref,label)
        # Rebuild the affected links, including June, and apply the signed diverse
        # result once. The supplied example subtracts that signed result twice.
        for row,col,offset in [(6,'O',1),(7,'O',2),*[(r,'AD',r-8) for r in range(9,13)],*[(r,'X',r-16) for r in range(17,21)],*[(r,'U',r-21) for r in range(22,33)],*[(r,'R',r-34) for r in range(35,37)],*[(r,'AA',r-36) for r in range(37,40)]]:
            refs=[f"'{name}'!{col}{(14 if i==0 else 10)+offset}" for i,name in enumerate(MONTHS)]
            values=[]
            for i,ref in enumerate(refs):
                cell=month_cells[i].get(ref.split('!')[1]);v=cell.find(Q('v')) if cell is not None else None;values.append(Decimal(v.text) if v is not None and v.text else Decimal(0))
            annual.set('C'+str(row),sum(values),'SUM('+','.join(refs)+')')
        total=defaultdict(Decimal)
        for values in totals:
            for key,value in values.items():total[key]+=value
        annual.set('C14',total['cost'],'SUM('+','.join(f"'{name}'!L{17 if i==0 else 13}" for i,name in enumerate(MONTHS))+')')
        revenue=total['revenue'];tax=total['tax'];gross=revenue-tax-total['cost'];opex=total['operating']+total['personnel'];operating=gross-opex
        for row,value,formula in [(5,revenue,'SUM(C6:C7)'),(8,tax,'SUM(C9:C12)'),(13,revenue-tax,'C5-C8'),(15,gross,'C13-C14'),(16,0,'SUM(C17:C20)'),(21,opex,'SUM(C22:C32)'),(33,operating,'C15-C16-C21'),(34,-total['financial'],'SUM(C35:C36)-SUM(C37:C39)'),(40,operating-total['financial'],'C33+C34')]:annual.set('C'+str(row),value,formula)
        changes['xl/worksheets/sheet3.xml']=annual.export()
        cover=Sheet(original.read('xl/worksheets/sheet2.xml'));cover.set('B6',company_name);cover.set('B7',f"Período: {report['start']} a {report['end']} · {report['scope_label']}")
        cover.set('B8','DRE por competência');cover.set('C8','Lançamentos e folhas fechadas do período consultado.\nAs categorias do SIGI são agregadas nos campos correspondentes do modelo.\nOs gastos por setor e categoria estão na aba Gastos por setor.\nResultado acumulado não representa saldo de caixa ou bancário.');changes['xl/worksheets/sheet2.xml']=cover.export()
        changes['xl/styles.xml'],style_map=merge_sector_styles(original.read('xl/styles.xml'),layout.read('xl/styles.xml'))
        new_path='xl/worksheets/sheet16.xml';changes[new_path]=sector_sheet(layout.read('xl/worksheets/sheet1.xml'),style_map,report,labels,month_ends)
        workbook=original.read('xl/workbook.xml').decode();workbook=workbook.replace('</sheets>','<sheet name="Gastos por setor" sheetId="17" r:id="rIdSIGISetores"/></sheets>')
        workbook=re.sub(r'activeTab="\d+"','activeTab="2"',workbook)
        workbook=re.sub(r'<calcPr\b[^>]*/>','<calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1" calcMode="auto"/>',workbook)
        changes['xl/workbook.xml']=workbook.encode()
        rels=original.read('xl/_rels/workbook.xml.rels').decode();rels=re.sub(r'<Relationship\b[^>]*Type="[^"]*/calcChain"[^>]*/>','',rels)
        rels=rels.replace('</Relationships>','<Relationship Id="rIdSIGISetores" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet16.xml"/></Relationships>');changes['xl/_rels/workbook.xml.rels']=rels.encode()
        types=original.read('[Content_Types].xml').decode();types=re.sub(r'<Override\b[^>]*PartName="/xl/calcChain.xml"[^>]*/>','',types)
        types=types.replace('</Types>','<Override PartName="/xl/worksheets/sheet16.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>');changes['[Content_Types].xml']=types.encode()
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as result:
            for item in original.infolist():
                if item.filename=='xl/calcChain.xml':continue
                result.writestr(item,changes.pop(item.filename,original.read(item.filename)))
            for path,data in changes.items():result.writestr(path,data)
    return output.getvalue()
