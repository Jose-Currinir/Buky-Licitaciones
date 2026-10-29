"""Evaluación comercial determinista, separada del puntaje oficial de las bases."""
from datetime import datetime, timezone
import math
import re

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


def _matches(text, terms):
    """Coincidencia de frase o palabra completa; evita activar por subcadenas triviales."""
    return [term for term in terms if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, re.IGNORECASE)]


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

    text = ' '.join(str(opportunity.get(field, '')) for field in ['nombre', 'productos', 'descripcion']).casefold()
    catalog = _terms(facts.get('catalogo') or facts.get('catalogo_confirmado'))
    exclusions = _terms(facts.get('exclusiones'))
    matched = _matches(text, catalog)
    excluded = _matches(text, exclusions)
    if excluded:
        add_unique(blockers, _event('exclusion_comercial', ', '.join(excluded)))
    if not catalog:
        add_unique(pending, _event('catalogo_pendiente'))
        add_unique(actions, _event('confirmar_afinidad'))
    elif matched:
        add_unique(reasons, _event('afinidad_catalogo', ', '.join(matched)))
    else:
        add_unique(pending, _event('afinidad_por_confirmar'))
        add_unique(actions, _event('confirmar_afinidad'))

    delivery_region = opportunity.get('region_entrega')
    regions = _terms(facts.get('regiones_atencion'))
    if delivery_region and regions and str(delivery_region).casefold() not in regions:
        add_unique(blockers, _event('region_no_disponible', delivery_region))

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
            state = requirement.get('estado', 'pendiente')
            if state == 'no_cumple':
                add_unique(blockers, _event('requisito_incumplido', detail, fuente=requirement.get('fuente')))
            elif state == 'pendiente':
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
    closing = opportunity.get('fecha_cierre') or '9999'
    return (decision_order[evaluation['decision']], fit_order[evaluation['ajuste_comercial']], closing, opportunity['codigo'])
