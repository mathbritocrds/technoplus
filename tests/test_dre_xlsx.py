"""Real API export: model preservation, scoped totals, literal inputs and capacity."""
import io
import zipfile
from decimal import Decimal
from xml.etree import ElementTree as ET

from app.dre_xlsx import TEMPLATES, export_workbook
from tests.test_business import service, employee

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
URL = '/finance/dre/modelo.xlsx?start=2026-01&end=2026-12'


def sheet(response, number):
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        root = ET.fromstring(archive.read(f'xl/worksheets/sheet{number}.xml'))
    return {c.get('r'): c for c in root.findall('.//s:c', NS)}


def value(cells, ref):
    cell = cells.get(ref)
    if cell is None: return None
    if cell.get('t') == 'inlineStr':
        return ''.join(cell.itertext())
    node = cell.find('s:v', NS)
    return Decimal(node.text) if node is not None and node.text else None


def post(service, path, payload):
    client, auth = service
    result = client.post(path, json=payload, headers=auth)
    assert result.is_success, result.text
    return result.json()


def test_model_export_preserves_artwork_and_reconciles_all_categories(service):
    client, auth = service
    production = post(service, '/departments', {'name': 'Produção *?'})['id']
    admin = post(service, '/departments', {'name': 'Administração'})['id']
    for category, amount in [('revenue', 10000), ('tax', 500), ('cost', 1500),
                             ('operating', 800), ('personnel', 2000), ('financial', 200)]:
        post(service, '/finance', {'kind': 'receber' if category == 'revenue' else 'pagar',
             'description': '=HYPERLINK("https://invalid.test")', 'amount': amount,
             'due': '2026-06-10', 'department_id': production if category != 'revenue' else None, 'category': category if category != 'revenue' else 'operating'})
    post(service, '/finance', {'kind': 'pagar', 'description': 'Administrativo', 'amount': 300,
                              'due': '2026-03-10', 'department_id': admin})
    post(service, '/finance', {'kind': 'pagar', 'description': 'Sem vínculo', 'amount': 100,
                              'due': '2026-12-10'})
    response = client.get(URL, headers=auth)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/vnd.openxmlformats')
    assert 'dre-modelo-2026-01-2026-12.xlsx' in response.headers['content-disposition']
    assert response.headers['cache-control'] == 'private, no-store'
    with zipfile.ZipFile(io.BytesIO(response.content)) as generated, zipfile.ZipFile(TEMPLATES/'dre-inter-empresas.xlsx') as original:
        assert generated.testzip() is None
        for name in original.namelist():
            if name.startswith(('xl/media/', 'xl/drawings/')):
                assert generated.read(name) == original.read(name)
        workbook = ET.fromstring(generated.read('xl/workbook.xml'))
        assert [s.get('name') for s in workbook.find('s:sheets', NS)][-1] == 'Gastos por setor'
        assert len(workbook.find('s:sheets', NS)) == 16
        assert 'xl/calcChain.xml' not in generated.namelist()
    annual, sectors, june = sheet(response, 3), sheet(response, 16), sheet(response, 9)
    report = client.get('/finance/dre?start=2026-01&end=2026-12', headers=auth).json()
    assert value(annual, 'C40') == Decimal(str(report['net_profit'])) == 4600
    assert value(annual, 'C14') == 1500
    assert value(annual, 'C21') == 3200
    assert value(annual, 'C34') == -200
    assert value(june, 'L19') == 5000
    assert value(sectors, 'O9') == 5400
    rows = {value(sectors, f'A{r}'): r for r in range(6, 9)}
    assert value(sectors, f'O{rows["Produção *?"]}') == 5000
    assert value(sectors, f'H{rows["Produção *?"]}') == 5000
    assert value(sectors, f'O{rows["Sem setor"]}') == 100
    assert abs(sum(value(sectors, f'P{r}') for r in range(6,9))-1) < Decimal('0.000000001')
    assert value(june, 'C11').startswith('=HYPERLINK')
    assert june['C11'].find('s:f', NS) is None
    assert 'SUBSTITUTE' in sectors[f'H{rows["Produção *?"]}'].find('s:f', NS).text
    assert "'Jun'!" in annual['C17'].find('s:f', NS).text


def test_empty_period_and_more_than_template_capacity(service):
    client, auth = service
    empty = client.get(URL, headers=auth)
    assert value(sheet(empty, 3), 'C40') == 0
    assert value(sheet(empty, 16), 'P6') is None
    assert value(sheet(empty, 4), 'E15') is None  # No template example revenue.
    content = 'ano;mes;categoria;descricao;valor;referencia\n' + ''.join(
        f'2026;02;cost;Insumo {i};1,01;ref-{i}\n' for i in range(811))
    assert post(service, '/finance/dre/import', {'content': content, 'preview': False})['imported'] == 811
    response = client.get(URL, headers=auth)
    february = sheet(response, 5)
    assert value(february, 'E821') == Decimal('1.01')
    assert value(february, 'I821') == Decimal('-819.11')
    assert value(sheet(response, 3), 'C40') == Decimal('-819.11')
    assert value(sheet(response, 16), 'O7') == Decimal('819.11')


def test_model_scope_and_calendar_validation(service):
    client, auth = service
    own = post(service, '/departments', {'name': 'Meu setor'})['id']
    other = post(service, '/departments', {'name': 'Outro setor'})['id']
    eid = employee(service)
    assert client.patch(f'/employees/{eid}', json={'department_id': own}, headers=auth).status_code == 200
    post(service, '/auth/register', {'email': 'xlsx-manager@test.com',
        'password': 'manager-test-password', 'role': 'manager', 'department_id': own, 'employee_id': eid})
    token = client.post('/auth/login', json={'email': 'xlsx-manager@test.com', 'password': 'manager-test-password'}).json()['token']
    access = {'Authorization': 'Bearer '+token}
    for did, total in [(own,100),(other,700)]:
        post(service, '/finance', {'kind':'pagar','description':'Custo','amount':total,'due':'2026-06-01','department_id':did})
    response = client.get(URL, headers=access)
    assert value(sheet(response, 3), 'C40') == -100
    assert value(sheet(response, 16), 'A6') == 'Meu setor'
    assert client.get(URL+f'&department_id={other}', headers=access).status_code == 403
    assert value(sheet(client.get(URL+f'&department_id={other}', headers=auth), 3), 'C40') == -700
    assert client.get(URL+'&department_id=9999', headers=auth).status_code == 404
    for period in ['start=2025-12&end=2026-01','start=2026-13&end=2026-13','start=2026-12&end=2026-01']:
        assert client.get('/finance/dre/modelo.xlsx?'+period, headers=auth).status_code == 400
    assert client.get(URL).status_code == 401


def test_duplicate_sector_names_are_distinct_in_formula_criteria():
    entries = [dict(origin='payroll_adjustment', month='2026-06', department_id=did,
        department=name, category='cost', description='Insumo', amount=amount)
        for did,name,amount in [(1,'Produção',10),(2,'Produção',20),(3,'Produção (ID 1)',30)]]
    content = export_workbook(dict(start='2026-01',end='2026-12',scope_label='Todos',entries=entries))
    class Download: pass
    response=Download();response.content=content
    cells=sheet(response,16)
    labels=[value(cells,f'A{row}') for row in range(6,9)]
    assert len(set(labels))==3
    assert sorted(value(cells,f'O{row}') for row in range(6,9))==[10,20,30]

    assert value(sheet(response,9),'H11') == 'Complemento de folha'
