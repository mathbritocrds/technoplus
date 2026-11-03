"""Approved, versioned tax tables. Never extrapolate rates into another year."""
import json
import math
from urllib.parse import urlsplit

from app import payroll as hr

REDUCTION_FIELDS = ('irrf_reduction_full_limit', 'irrf_reduction_full_amount',
                    'irrf_reduction_taper_limit', 'irrf_reduction_taper_offset',
                    'irrf_reduction_taper_rate')


def with_inss_offsets(table):
    """Derive display-only deductions from the progressive contribution bands.

    Historical approvals may not contain this metadata. It is not an input to
    the progressive calculation and must never override the approved bands.
    """
    previous, contribution = hr.ZERO, hr.ZERO
    offsets = []
    for ceiling, rate in table['inss']:
        ceiling, rate = hr.D(ceiling), hr.D(rate)
        offsets.append(hr.money(previous * rate - contribution))
        contribution += (ceiling - previous) * rate
        previous = ceiling
    return {**table, 'inss_offsets': offsets}


def get_tax_rules(connection, month):
    start, _ = hr.validate_month(month)
    row = connection.execute('SELECT v FROM settings WHERE k=?', (f'tax_rules:{start.year}',)).fetchone()
    if row:
        return with_inss_offsets(json.loads(row['v'])['table'])
    return with_inss_offsets(hr.tax_rules(month))


def validate_table(year, table):
    if not 2026 <= year <= 2100 or not isinstance(table, dict):
        raise ValueError('Ano ou tabela inválida.')
    required = {'version', 'inss', 'inss_max', 'irrf', 'dependent_deduction', 'simplified_deduction', *REDUCTION_FIELDS}
    if not required.issubset(table) or not isinstance(table['version'], str) or not table['version'].strip():
        raise ValueError('Informe versão e todos os parâmetros fiscais, inclusive a redução do IRRF.')
    for name in required - {'version', 'inss', 'irrf'}:
        value = table[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Parâmetro fiscal inválido: ' + name)
    for field, width in [('inss', 2), ('irrf', 3)]:
        bands = table[field]
        if not isinstance(bands, list) or not 1 <= len(bands) <= 20:
            raise ValueError('Faixas fiscais inválidas.')
        previous = 0
        for i, band in enumerate(bands):
            if not isinstance(band, (list, tuple)) or len(band) != width:
                raise ValueError('Formato de faixa inválido.')
            ceiling, rate = band[:2]
            if ceiling is None:
                if field != 'irrf' or i != len(bands)-1:
                    raise ValueError('Somente a última faixa do IRRF pode não ter teto.')
            elif isinstance(ceiling, bool) or not isinstance(ceiling, (float, int)) or not math.isfinite(ceiling) or ceiling <= previous:
                raise ValueError('Tetos devem ser finitos, positivos e crescentes.')
            else:
                previous = ceiling
            if isinstance(rate, bool) or not isinstance(rate, (float, int)) or not math.isfinite(rate) or not 0 <= rate <= 1:
                raise ValueError('Alíquota inválida.')
            if width == 3 and (not isinstance(band[2], (float, int)) or not math.isfinite(band[2]) or band[2] < 0):
                raise ValueError('Parcela a deduzir inválida.')
        if field == 'irrf' and bands[-1][0] is not None:
            raise ValueError('A última faixa de IRRF deve ser aberta.')
    if table['irrf_reduction_taper_limit'] < table['irrf_reduction_full_limit']:
        raise ValueError('Limites da redução do IRRF estão invertidos.')
    return with_inss_offsets(table)


def approve_table(connection, year, table, source, actor, approved_at):
    table = validate_table(year, table)
    url = urlsplit(source)
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Informe a URL HTTPS da fonte oficial, sem credenciais.')
    version = table['version'].strip()
    record = {'year': year, 'table': table, 'source': source, 'approved_by': actor, 'approved_at': approved_at}
    key = f'tax_rules:{year}:{version}'
    existing = connection.execute('SELECT v FROM settings WHERE k=?', (key,)).fetchone()
    if existing:
        previous = json.loads(existing['v'])
        if with_inss_offsets(previous['table']) != table or previous['source'] != source:
            raise ValueError('Versão já registrada com outro conteúdo. Cadastre uma nova versão.')
        return previous
    encoded = json.dumps(record, ensure_ascii=False)
    connection.execute('INSERT INTO settings(k,v) VALUES(?,?)', (key, encoded))
    connection.execute('INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',
                       (f'tax_rules:{year}', encoded))
    return record
