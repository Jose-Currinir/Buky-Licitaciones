"""Oportunidades de mejora y desarrollo del perfil a partir de lo guardado; no consulta la red."""
from collections import Counter, defaultdict
from datetime import datetime, timezone

import base_empresa as base
import viabilidad as viability


# Condiciones del perfil que se repiten en muchas oportunidades: resolverlas una vez mejora todas.
IMPROVEMENT_EVENTS = {
    'catalogo_pendiente': 'Completar el catálogo con lo que realmente vendes.',
    'afinidad_parcial': 'Confirmar o descartar las coincidencias parciales y agregar sinónimos al catálogo.',
    'region_no_disponible': 'Evaluar si conviene atender esas regiones (despacho, socio local o servicio remoto).',
    'region_por_verificar': 'Declarar las regiones de atención con su nombre o número.',
    'tamano_por_confirmar': 'Confirmar el tamaño de empresa con «giros» o «condiciones --emt».',
    'compra_agil_solo_emt': 'Como gran empresa, enfocarse en licitaciones y segundos llamados de Compra Ágil.',
    'tiempo_insuficiente': 'Reducir las horas de preparación con plantillas y antecedentes listos.',
    'margen_insuficiente': 'Revisar costos o descartar rubros donde el margen no alcanza.',
    'requisito_incumplido': 'Obtener los requisitos que bloquean con más frecuencia.',
    'requisito_pendiente': 'Preparar una vez los antecedentes que se piden una y otra vez.',
    'inicio_actividades_pendiente': 'Regularizar el inicio de actividades para poder ofertar.',
    'inicio_actividades_por_confirmar': 'Confirmar el inicio de actividades y la habilidad como proveedor.',
}
# Palabras de títulos que no describen un rubro.
NOISE = viability.GENERIC | frozenset((
    'municipalidad hospital servicio salud region regional comuna comunal unidad departamento direccion '
    'oficina ano anos segun bases tecnicas requerimiento solicitud cotizacion ca compra agil para uso '
    'otro otros diverso diversos nuevo nueva'
).split())
LOW_COMPETITION = 2


def _amount(item):
    return item.get('monto') if item.get('moneda') in (None, 'CLP') and isinstance(item.get('monto'), (int, float)) else 0


def _phrases(name, catalog_tokens):
    """Pares de palabras con significado (p. ej. «tóner impresora»), sin términos ya catalogados."""
    words = [word for word in viability._tokens(name) if len(word) > 2 and not word.isdigit() and word not in NOISE]
    pairs = {f'{a} {b}' for a, b in zip(words, words[1:]) if not {a, b} <= catalog_tokens}
    return pairs or {word for word in words if word not in catalog_tokens and len(word) > 4}


def _top(counter, amounts=None, limit=5, examples=None):
    return [
        {'valor': key, 'oportunidades': count,
         **({'monto_clp': amounts[key]} if amounts is not None else {}),
         **({'ejemplos': examples[key][:3]} if examples is not None else {})}
        for key, count in counter.most_common(limit)
    ]


def profile_checks(facts, items, fitting):
    """Problemas del perfil que no aparecen como evento de una oportunidad, pero las afectan a todas."""
    checks = []
    catalog = viability.catalog_raw(facts)
    if catalog and items and not fitting:
        # Típico: nombres de marca o de producto propio, que los compradores no usan en sus títulos.
        checks.append({'codigo': 'catalogo_sin_coincidencias', 'oportunidades': len(items), 'detalles': catalog[:5],
                       'accion': 'Describir el catálogo con las palabras de los compradores (por ejemplo, «software de '
                                 'contabilidad» en vez del nombre comercial) y revisar las líneas cercanas.'})
    if not facts.get('regiones_atencion'):
        checks.append({'codigo': 'regiones_sin_declarar', 'oportunidades': len(items), 'detalles': [],
                       'accion': 'Declarar las regiones de atención (o «nacional») con «condiciones --regiones».'})
    if facts.get('horas_preparacion') is None or facts.get('margen_minimo') is None:
        checks.append({'codigo': 'condiciones_incompletas', 'oportunidades': len(items), 'detalles': [],
                       'accion': 'Indicar horas de preparación y margen mínimo para descartar a tiempo lo inviable.'})
    return checks


def diagnose(company, now=None, limit=5):
    now = now or datetime.now(timezone.utc)
    facts = viability.latest_facts(company)
    catalog_tokens = {token for term in viability.catalog_raw(facts) for token in viability._tokens(term)}
    items = [item for item in company['oportunidades'].values() if item.get('mecanismo') != 'planificacion']

    events, event_examples, event_details = Counter(), defaultdict(list), defaultdict(Counter)
    regions_out, requirements = Counter(), Counter()
    lines, line_amounts, line_examples = Counter(), Counter(), defaultdict(list)
    buyers, buyer_amounts, buyer_regions = Counter(), Counter(), Counter()
    low_competition = []
    fitting = fitting_amount = 0
    consulted = []
    for item in items:
        evaluation = viability.evaluate(item, company, now)
        consulted.append(item.get('consultado_en'))
        for event in evaluation['bloqueos'] + evaluation['pendientes']:
            code = event['codigo']
            if code not in IMPROVEMENT_EVENTS:
                continue
            events[code] += 1
            if len(event_examples[code]) < 3:
                event_examples[code].append(item['codigo'])
            if event.get('detalle'):
                event_details[code][event['detalle']] += 1
            if code == 'region_no_disponible':
                regions_out[event.get('detalle')] += 1
            if code in {'requisito_pendiente', 'requisito_incumplido'}:
                requirements[event.get('detalle')] += 1
        affinity = any(event['codigo'] == 'afinidad_catalogo' for event in evaluation['razones'])
        if affinity:
            fitting += 1
            fitting_amount += _amount(item)
            if item.get('comprador'):
                buyers[item['comprador']] += 1
                buyer_amounts[item['comprador']] += _amount(item)
            if item.get('region_comprador'):
                buyer_regions[item['region_comprador']] += 1
            offers = item.get('ofertas_recibidas')
            # Solo en procesos cerrados el conteo de ofertas es definitivo.
            if evaluation['etapa'] == 'cerradas' and isinstance(offers, int) and offers <= LOW_COMPETITION:
                low_competition.append({'codigo': item['codigo'], 'nombre': item['nombre'], 'ofertas_recibidas': offers,
                                        'comprador': item.get('comprador'), 'monto_clp': _amount(item) or None})
        else:
            # Lo que compran fuera del catálogo y se repite: posibles líneas de negocio nuevas.
            for phrase in _phrases(item['nombre'], catalog_tokens):
                lines[phrase] += 1
                line_amounts[phrase] += _amount(item)
                line_examples[phrase].append(item['codigo'])

    improvements = profile_checks(facts, items, fitting) + [
        {'codigo': code, 'oportunidades': count, 'accion': IMPROVEMENT_EVENTS[code], 'ejemplos': event_examples[code],
         'detalles': [detail for detail, _ in event_details[code].most_common(3)]}
        for code, count in events.most_common()
    ]
    # Una línea vista una sola vez no es un patrón.
    recurrent_lines = Counter({phrase: count for phrase, count in lines.items() if count >= 2})
    history = [record for record in company.get('registros', []) if record.get('tipo') == 'historico_propio']
    dates = sorted(value for value in consulted if value)
    return {
        'schema_version': 1,
        'rut': company['rut'],
        'generado_en': base.utc_iso(now),
        'cobertura': {
            'oportunidades': len(items),
            'por_mecanismo': dict(Counter(item['mecanismo'] for item in items)),
            'consultadas_desde': dates[0] if dates else None,
            'consultadas_hasta': dates[-1] if dates else None,
            'advertencia': 'Solo considera las oportunidades guardadas en el perfil, no todo el mercado.',
        },
        'mejora': {
            'condiciones': improvements[:limit * 2],
            'regiones_fuera': _top(regions_out, limit=limit),
            'requisitos_recurrentes': _top(Counter({key: value for key, value in requirements.items() if value >= 2}), limit=limit),
        },
        'desarrollo': {
            'con_afinidad': {'oportunidades': fitting, 'monto_clp': fitting_amount},
            'baja_competencia': sorted(low_competition, key=lambda entry: (entry['ofertas_recibidas'], -(entry['monto_clp'] or 0)))[:limit],
            'compradores_frecuentes': _top(buyers, buyer_amounts, limit=limit),
            'regiones_comprador': _top(buyer_regions, limit=limit),
            'lineas_cercanas': _top(recurrent_lines, line_amounts, limit=limit, examples=line_examples),
        },
        'historial_propio': {
            'registros': len(history),
            'estado': 'disponible' if history else 'sin_historial',
        },
    }
