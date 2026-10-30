"""Datos que alimentan la evaluación —catálogo, condiciones, requisitos y costos— sin JSON manual.

Cada cambio se guarda como una revisión de la base. Los requisitos y costos viven en la
oportunidad y se conservan cuando una sincronización trae una observación oficial nueva.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re

import base_empresa as base
from i18n import tr
from viabilidad import catalog_raw, latest_facts, normalize_text, region_code, NATIONWIDE


FACT_STATES = frozenset({'documentado', 'declarado', 'inferido', 'pendiente'})
REQUIREMENT_STATES = frozenset({'cumple', 'no_cumple', 'pendiente'})
MAX_TERMS = 50
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


class AnnotationError(ValueError):
    pass


def _clean(value, limit, error_key):
    text = ' '.join(CONTROL.sub(' ', str(value or '')).split())
    if not 1 <= len(text) <= limit:
        raise AnnotationError(tr(error_key))
    return text


def _source(value):
    return _clean(value or 'usuario', 300, 'annotation.invalid_source')


def _add_fact(data, field, value, state, source):
    if state not in FACT_STATES:
        raise AnnotationError(tr('annotation.invalid_fact_state'))
    data['hechos'].append({
        'campo': field, 'valor': value, 'estado': state,
        'fuente': _source(source), 'consultado_en': base.utc_now(),
    })


def _term_list(value):
    if isinstance(value, str):
        value = [value]
    return [str(item) for item in value or [] if str(item).strip()]


def _merge_terms(current, add, remove):
    result = list(current)
    keys = {normalize_text(term) for term in result}
    for term in add or []:
        term = _clean(term, 80, 'annotation.invalid_term')
        if normalize_text(term) not in keys:
            result.append(term)
            keys.add(normalize_text(term))
    removed = {normalize_text(term) for term in remove or []}
    result = [term for term in result if normalize_text(term) not in removed]
    if len(result) > MAX_TERMS:
        raise AnnotationError(tr('annotation.too_many_terms', maximo=MAX_TERMS))
    return result


def catalog(directory, rut, add=None, remove=None, exclude=None, allow=None, state='declarado', source=None):
    """Muestra o actualiza el catálogo y las exclusiones comerciales del perfil."""
    data = base.load(directory, rut)
    facts = latest_facts(data)
    current = _term_list(catalog_raw(facts))
    exclusions = _term_list(facts.get('exclusiones'))
    new_catalog = _merge_terms(current, add, remove)
    new_exclusions = _merge_terms(exclusions, exclude, allow)
    changes = []
    if new_catalog != current:
        _add_fact(data, 'catalogo', new_catalog, state, source)
        changes.append('catálogo')
    if new_exclusions != exclusions:
        _add_fact(data, 'exclusiones', new_exclusions, state, source)
        changes.append('exclusiones')
    result = {'catalogo': new_catalog, 'exclusiones': new_exclusions, 'cambios': changes}
    if changes:
        base.save(directory, data, reason='actualiza ' + ' y '.join(changes))
        result['revision'] = data['_version']['id']
    return result


def _margin(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise AnnotationError(tr('annotation.invalid_margin')) from None
    if not number.is_finite():
        raise AnnotationError(tr('annotation.invalid_margin'))
    # Se acepta 0,15 o 15 (porcentaje); siempre se guarda como fracción.
    if 1 <= number < 100:
        number = number / 100
    if not 0 <= number < 1:
        raise AnnotationError(tr('annotation.invalid_margin'))
    return float(number)


def conditions(directory, rut, regions=None, preparation_hours=None, minimum_margin=None, state='declarado', source=None, emt=None):
    """Muestra o actualiza regiones de atención, horas de preparación y margen mínimo."""
    data = base.load(directory, rut)
    changes = []
    if regions is not None:
        cleaned = [_clean(item, 80, 'annotation.invalid_region') for item in regions]
        for item in cleaned:
            if normalize_text(item) not in NATIONWIDE and region_code(item) is None:
                raise AnnotationError(tr('annotation.unknown_region', region=item))
        _add_fact(data, 'regiones_atencion', cleaned, state, source)
        changes.append('regiones')
    if preparation_hours is not None:
        if not math.isfinite(preparation_hours) or preparation_hours < 0 or preparation_hours > 2000:
            raise AnnotationError(tr('annotation.invalid_hours'))
        _add_fact(data, 'horas_preparacion', preparation_hours, state, source)
        changes.append('horas de preparación')
    if minimum_margin is not None:
        _add_fact(data, 'margen_minimo', _margin(minimum_margin), state, source)
        changes.append('margen mínimo')
    if emt is not None:
        _add_fact(data, 'tamano_empresa', {'emt': bool(emt), 'nombre': 'empresa de menor tamaño' if emt else 'gran empresa'}, state, source)
        changes.append('tamaño de empresa')
    if changes:
        base.save(directory, data, reason='actualiza ' + ', '.join(changes))
    facts = latest_facts(data)
    result = {
        'regiones_atencion': facts.get('regiones_atencion'),
        'horas_preparacion': facts.get('horas_preparacion'),
        'margen_minimo': facts.get('margen_minimo'),
        'tamano_empresa': facts.get('tamano_empresa'),
        'cambios': changes,
    }
    if changes:
        result['revision'] = data['_version']['id']
    return result


def find_opportunity(data, code):
    matches = [item for item in data['oportunidades'].values() if item['codigo'].casefold() == str(code).strip().casefold()]
    if not matches:
        raise AnnotationError(tr('annotation.opportunity_not_found', codigo=code))
    if len(matches) > 1:
        raise AnnotationError(tr('annotation.opportunity_ambiguous', codigo=code))
    return matches[0]


def _requirement_state(state):
    if state not in REQUIREMENT_STATES:
        raise AnnotationError(tr('annotation.invalid_requirement_state'))
    return state


def requirements(directory, rut, code):
    data = base.load(directory, rut)
    item = find_opportunity(data, code)
    return {'codigo': item['codigo'], 'requisitos': item.get('requisitos', [])}


def add_requirement(directory, rut, code, text, mandatory=True, state='pendiente', source=None, evidence=None):
    data = base.load(directory, rut)
    item = find_opportunity(data, code)
    current = list(item.get('requisitos') or [])
    numbers = [int(entry['id'][1:]) for entry in current if isinstance(entry, dict) and re.fullmatch(r'R\d+', str(entry.get('id', '')))]
    requirement = {
        'id': 'R' + str(max(numbers, default=0) + 1),
        'requisito': _clean(text, 500, 'annotation.invalid_requirement'),
        'obligatorio': bool(mandatory),
        'estado': _requirement_state(state),
        'fuente': _source(source),
        'actualizado_en': base.utc_now(),
    }
    if evidence:
        requirement['evidencia'] = _clean(evidence, 500, 'annotation.invalid_evidence')
    current.append(requirement)
    item['requisitos'] = current
    base.save(directory, data, reason=f'requisito {requirement["id"]} en {item["codigo"]}: {requirement["estado"]}')
    return requirement


def mark_requirement(directory, rut, code, identifier, state, evidence=None, source=None):
    data = base.load(directory, rut)
    item = find_opportunity(data, code)
    for requirement in item.get('requisitos') or []:
        if isinstance(requirement, dict) and str(requirement.get('id', '')).upper() == str(identifier).strip().upper():
            requirement['estado'] = _requirement_state(state)
            requirement['actualizado_en'] = base.utc_now()
            if source:
                requirement['fuente'] = _source(source)
            if evidence:
                requirement['evidencia'] = _clean(evidence, 500, 'annotation.invalid_evidence')
            base.save(directory, data, reason=f'requisito {requirement["id"]} en {item["codigo"]}: {state}')
            return requirement
    raise AnnotationError(tr('annotation.requirement_not_found', id=identifier))


def _amount(value, error_key):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise AnnotationError(tr(error_key)) from None
    if not number.is_finite() or number <= 0:
        raise AnnotationError(tr(error_key))
    return number


def register_costs(directory, rut, code, cost, price, currency='CLP', source=None):
    """Guarda costo y precio netos; el margen es (precio − costo) / precio."""
    data = base.load(directory, rut)
    item = find_opportunity(data, code)
    cost, price = _amount(cost, 'annotation.invalid_cost'), _amount(price, 'annotation.invalid_price')
    currency = _clean(currency, 10, 'annotation.invalid_currency').upper()
    margin = ((price - cost) / price).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    item['costos'] = {
        'costo_neto': str(cost), 'precio_neto': str(price), 'moneda': currency,
        'margen': str(margin), 'fuente': _source(source), 'registrado_en': base.utc_now(),
    }
    item['margen_estimado'] = float(margin)
    base.save(directory, data, reason=f'costos de {item["codigo"]}: margen {margin}')
    return {'codigo': item['codigo'], **item['costos']}


def follow(directory, rut, code, active=True):
    """Marca una oportunidad como seguida (recibe avisos de cierre) o la silencia."""
    data = base.load(directory, rut)
    item = find_opportunity(data, code)
    item['seguimiento'] = {'activo': bool(active), 'actualizado_en': base.utc_now()}
    base.save(directory, data, reason=('sigue ' if active else 'silencia ') + item['codigo'])
    return {'codigo': item['codigo'], **item['seguimiento']}
