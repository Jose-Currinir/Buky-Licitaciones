"""Evaluación comercial determinista, separada del puntaje oficial de las bases."""
from datetime import datetime, timezone
import math
import re
import unicodedata

import base_empresa as base


DECISIONS = {'participar', 'participar_condicionado', 'no_participar'}


def latest_facts(company):
    """Resuelve hechos por campo sin borrar la evidencia histórica."""
    facts = {}
    for fact in company.get('hechos', []):
        field = fact.get('campo')
        if field:
            facts[field] = fact.get('valor')
    return facts


def catalog_raw(facts):
    """Catálogo vigente tal como se guardó: el último `catalogo`, aunque esté vacío; si nunca se guardó, el confirmado."""
    value = facts['catalogo'] if 'catalogo' in facts else facts.get('catalogo_confirmado')
    if isinstance(value, str):
        value = [value]
    return [str(item) for item in value or [] if str(item).strip()]


def catalog_terms(facts):
    """Catálogo vigente normalizado para comparar."""
    return _terms(catalog_raw(facts))


def _terms(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip().casefold() for item in value if str(item).strip()]


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _event(code, detail=None, **params):
    result = {'codigo': code}
    if detail is not None:
        result['detalle'] = str(detail)
    result.update(params)
    return result


STOPWORDS = frozenset('a al con de del e el en la las los o para por sus su u un una y'.split())
# Palabras frecuentes en títulos de compras que por sí solas no indican afinidad.
GENERIC = frozenset((
    'adquisicion compra compras contratacion servicio suministro provision producto material '
    'insumo varios general anual mensual proyecto programa equipo implementacion'
).split())
NATIONWIDE = frozenset({'todas', 'todo el pais', 'nacional', 'chile', 'todas las regiones'})
REGIONS = {
    15: ('arica', 'parinacota'), 1: ('tarapaca',), 2: ('antofagasta',), 3: ('atacama',),
    4: ('coquimbo',), 5: ('valparaiso',), 13: ('metropolitana', 'santiago'),
    6: ('ohiggins', 'libertador'), 7: ('maule',), 16: ('nuble',), 8: ('biobio',),
    9: ('araucania',), 14: ('los rios',), 10: ('los lagos',), 11: ('aysen', 'aisen'), 12: ('magallanes',),
}
ROMAN = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
         'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15, 'xvi': 16, 'rm': 13}


def normalize_text(value):
    """Minúsculas sin tildes ni signos, para comparar títulos y catálogos de forma estable."""
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    text = text.casefold().replace("'", '')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def _stem(word):
    if len(word) > 4 and word.endswith('es') and word[-3] in 'rlndzj':
        return word[:-2]
    if len(word) > 3 and word.endswith('s'):
        return word[:-1]
    return word


def _tokens(text):
    return [_stem(word) for word in normalize_text(text).split() if word not in STOPWORDS]


def _matches(text, terms):
    """Coincidencia completa: todas las palabras significativas del término están en el texto."""
    available = set(_tokens(text))
    return [term for term in terms if _tokens(term) and set(_tokens(term)) <= available]


def _partial_matches(text, terms):
    """Palabras distintivas compartidas (no genéricas, de 4+ letras) cuando no hay coincidencia completa."""
    available = set(_tokens(text))
    shared = []
    for term in terms:
        for word in _tokens(term):
            if len(word) >= 4 and word not in GENERIC and word in available and word not in shared:
                shared.append(word)
    return shared


def region_code(value):
    """Código 1–16 de una región escrita como número, romano o nombre; None si no se reconoce."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 1 <= value <= 16 else None
    text = normalize_text(value)
    if not text:
        return None
    if text.isdigit():
        return int(text) if 1 <= int(text) <= 16 else None
    words = [word for word in text.split() if word not in {'region', 'de', 'del', 'la'}]
    if len(words) == 1 and words[0] in ROMAN:
        return ROMAN[words[0]]
    if len(words) == 1 and words[0].isdigit() and 1 <= int(words[0]) <= 16:
        return int(words[0])
    compact = text.replace(' ', '')
    for code, names in REGIONS.items():
        if any(name.replace(' ', '') in compact for name in names):
            return code
    return None


def _region_check(delivery, served):
    """Devuelve 'ok', 'fuera' o 'por_verificar' comparando por código de región."""
    deliveries = delivery if isinstance(delivery, list) else [delivery]
    deliveries = [item for item in deliveries if item not in (None, '')]
    if not deliveries or not served:
        return 'ok'
    if any(normalize_text(item) in NATIONWIDE for item in served):
        return 'ok'
    served_codes = {region_code(item) for item in served}
    delivery_codes = {region_code(item) for item in deliveries}
    if (delivery_codes & served_codes) - {None}:
        return 'ok'
    if None not in served_codes and None not in delivery_codes:
        return 'fuera'
    served_text = {normalize_text(item) for item in served}
    return 'ok' if any(normalize_text(item) in served_text for item in deliveries) else 'por_verificar'


def evaluate(opportunity, company, now=None):
    """Entrega participar / participar_condicionado / no_participar con evidencia.

    No calcula probabilidad de adjudicación ni sustituye la matriz oficial. Un requisito
    obligatorio incumplido siempre prevalece sobre afinidad, margen o puntaje comercial.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise base.DataError('La evaluación requiere una hora con zona.')
    facts = latest_facts(company)
    stage = base.classify(opportunity, now, company.get('preferencias', {}).get('horas_por_cerrar', 72))
    reasons, blockers, pending, actions = [], [], [], []

    def add_unique(target, event):
        if event not in target:
            target.append(event)

    if company.get('tipo_perfil') == 'persona_natural':
        activity = company.get('inicio_actividades')
        if activity is False:
            add_unique(blockers, _event('inicio_actividades_pendiente'))
            add_unique(actions, _event('regularizar_inicio_actividades'))
        elif activity is not True:
            add_unique(pending, _event('inicio_actividades_por_confirmar'))
            add_unique(actions, _event('confirmar_inicio_actividades'))

    if stage in {'cerradas', 'suspendidas'}:
        add_unique(blockers, _event('proceso_no_activo'))
    elif stage == 'por_verificar':
        add_unique(pending, _event('proceso_por_verificar'))
        add_unique(actions, _event('verificar_proceso'))

    products = opportunity.get('productos')
    products = ' '.join(map(str, products)) if isinstance(products, list) else str(products or '')
    text = ' '.join([str(opportunity.get('nombre', '')), products, str(opportunity.get('descripcion', ''))])
    catalog = catalog_terms(facts)
    exclusions = _terms(facts.get('exclusiones'))
    matched = _matches(text, catalog)
    partial = [] if matched else _partial_matches(text, catalog)
    excluded = _matches(text, exclusions)
    if excluded:
        add_unique(blockers, _event('exclusion_comercial', ', '.join(excluded)))
    if not catalog:
        add_unique(pending, _event('catalogo_pendiente'))
        add_unique(actions, _event('confirmar_afinidad'))
    elif matched:
        add_unique(reasons, _event('afinidad_catalogo', ', '.join(matched)))
    elif partial:
        add_unique(pending, _event('afinidad_parcial', ', '.join(partial)))
        add_unique(actions, _event('confirmar_afinidad'))
    else:
        add_unique(pending, _event('afinidad_por_confirmar'))
        add_unique(actions, _event('confirmar_afinidad'))

    delivery_region = opportunity.get('region_entrega')
    region = _region_check(delivery_region, _terms(facts.get('regiones_atencion')))
    if region == 'fuera':
        add_unique(blockers, _event('region_no_disponible', delivery_region))
    elif region == 'por_verificar':
        add_unique(pending, _event('region_por_verificar', delivery_region))

    # Compra Ágil: el primer llamado es para empresas de menor tamaño (Decreto 661, art. 97).
    if opportunity.get('mecanismo') == 'compra_agil' and opportunity.get('llamado') != 2:
        size = facts.get('tamano_empresa') if isinstance(facts.get('tamano_empresa'), dict) else {}
        emt = size.get('emt')
        size_name = size.get('nombre') or ''
        if emt is True:
            add_unique(reasons, _event('empresa_menor_tamano', size_name or 'declarada'))
        elif emt is False and opportunity.get('llamado') == 1:
            add_unique(blockers, _event('compra_agil_solo_emt', size_name or 'gran empresa'))
        elif emt is False:
            add_unique(pending, _event('compra_agil_llamado_por_verificar'))
        elif opportunity.get('llamado') == 1:
            add_unique(pending, _event('tamano_por_confirmar'))
            add_unique(actions, _event('confirmar_tamano'))

    preparation_hours = facts.get('horas_preparacion')
    closing = None
    if opportunity.get('fecha_cierre'):
        try:
            closing = base.moment(opportunity['fecha_cierre'])
        except base.DataError:
            closing = None
    if closing and _number(preparation_hours) and preparation_hours >= 0:
        remaining = (closing - now).total_seconds() / 3600
        if stage not in {'cerradas', 'suspendidas'} and remaining < preparation_hours:
            add_unique(blockers, _event('tiempo_insuficiente', horas=round(remaining, 1), requeridas=preparation_hours))
        elif remaining >= preparation_hours:
            add_unique(reasons, _event('plazo_suficiente'))

    requirements = opportunity.get('requisitos')
    if not isinstance(requirements, list) or not requirements:
        add_unique(pending, _event('requisitos_sin_evaluar'))
        add_unique(actions, _event('revisar_bases'))
    else:
        for requirement in requirements:
            if not isinstance(requirement, dict) or not requirement.get('obligatorio', False):
                continue
            detail = requirement.get('requisito') or requirement.get('id') or 'sin descripción'
            state = requirement.get('estado')
            if state == 'no_cumple':
                add_unique(blockers, _event('requisito_incumplido', detail, fuente=requirement.get('fuente')))
            elif state != 'cumple':
                # Cualquier estado distinto de «cumple», incluido uno desconocido o ausente, queda pendiente.
                add_unique(pending, _event('requisito_pendiente', detail, fuente=requirement.get('fuente')))
        if any(item.get('codigo') == 'requisito_pendiente' for item in pending):
            add_unique(actions, _event('resolver_requisitos'))

    margin = opportunity.get('margen_estimado')
    minimum_margin = facts.get('margen_minimo')
    if _number(margin) and _number(minimum_margin):
        if margin < minimum_margin:
            add_unique(blockers, _event('margen_insuficiente'))
        else:
            add_unique(reasons, _event('margen_suficiente'))
    elif opportunity.get('monto') is not None:
        add_unique(pending, _event('rentabilidad_sin_evaluar'))
        add_unique(actions, _event('evaluar_costos'))

    if blockers:
        decision = 'no_participar'
    elif pending:
        decision = 'participar_condicionado'
    else:
        decision = 'participar'
        add_unique(actions, _event('preparar_oferta'))

    if excluded or any(item.get('codigo') == 'afinidad_por_confirmar' for item in pending):
        fit = 'bajo'
    elif stage == 'por_verificar' or not catalog:
        fit = 'por_verificar'
    elif matched and decision == 'participar':
        fit = 'alto'
    else:
        fit = 'medio'

    return {
        'schema_version': 1,
        'codigo': opportunity['codigo'],
        'mecanismo': opportunity['mecanismo'],
        'decision': decision,
        'ajuste_comercial': fit,
        'etapa': stage,
        'razones': reasons,
        'bloqueos': blockers,
        'pendientes': pending,
        'proximas_acciones': actions,
        'evaluado_en': base.utc_now(),
        'evidencia': {
            'fuente': opportunity.get('fuente'),
            'consultado_en': opportunity.get('consultado_en'),
            'url': opportunity.get('url'),
        },
        'alcance': 'criterio_comercial_interno_no_puntaje_oficial',
    }


def prioritize(opportunity, evaluation):
    decision_order = {'participar': 0, 'participar_condicionado': 1, 'no_participar': 2}
    fit_order = {'alto': 0, 'medio': 1, 'por_verificar': 2, 'bajo': 3}
    try:
        closing = base.moment(opportunity['fecha_cierre']).timestamp() if opportunity.get('fecha_cierre') else math.inf
    except base.DataError:
        closing = math.inf
    return (decision_order[evaluation['decision']], fit_order[evaluation['ajuste_comercial']], closing, opportunity['codigo'])
