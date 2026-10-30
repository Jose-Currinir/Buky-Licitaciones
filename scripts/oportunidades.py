"""Adquisición paginada y normalización conservadora de oportunidades."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import re

import base_empresa as base
import mercado_publico as api


class OpportunityError(ValueError):
    pass


def utc_iso(value=None):
    if value is None:
        return base.utc_now()
    return base.utc_iso(base.moment(value))


def pick(data, names, default=None):
    for name in names:
        current = data
        found = True
        for part in name.split('.'):
            if not isinstance(current, dict) or part not in current:
                found = False
                break
            current = current[part]
        if found and current is not None and current != '':
            return current
    return default


OFFICIAL_ZONE = 'America/Santiago'


def _date(raw, warnings, field, inferred=None):
    """Fecha oficial en UTC. Sin zona, Mercado Público publica hora de Chile: se asume y se marca."""
    if raw in (None, ''):
        return None
    try:
        return utc_iso(str(raw))
    except base.DataError:
        pass
    try:
        local = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        warnings.append(f'{field}: fecha inválida; requiere verificación')
        return None
    if local.tzinfo is not None:
        warnings.append(f'{field}: fecha inválida; requiere verificación')
        return None
    if inferred is not None:
        inferred.append(field)
    warnings.append(f'{field}: sin zona en la fuente; se interpretó como hora de Chile ({OFFICIAL_ZONE})')
    return base.utc_iso(local.replace(tzinfo=ZoneInfo(OFFICIAL_ZONE)))


def _amount(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        cleaned = value.strip().replace(' ', '')
        if re.fullmatch(r'-?\d+(?:[.,]\d+)?', cleaned):
            return float(cleaned.replace(',', '.'))
    return value


def _text(value):
    if value is None:
        return None
    text = ' '.join(str(value).split())
    return text or None


def _products(raw):
    """Productos del proceso: lista simple, o ítems v1 con nombre y categoría."""
    products = pick(raw, ['productos', 'rubros', 'familias'], None)
    if products is None:
        products = pick(raw, ['Items.Listado'], [])
    if isinstance(products, str):
        products = [products]
    if not isinstance(products, list):
        return [], []
    names, categories = [], []
    for entry in products:
        if isinstance(entry, dict):
            name = _text(pick(entry, ['nombre', 'NombreProducto', 'descripcion', 'Descripcion', 'titulo']))
            category = _text(pick(entry, ['Categoria', 'categoria']))
            if name and name not in names:
                names.append(name)
            if category and category not in categories:
                categories.append(category)
        elif _text(entry):
            names.append(_text(entry))
    return names, categories


# Códigos v1 verificados con la API el 30-10-2026.
V1_STATES = {'5': 'publicada', '6': 'cerrada', '7': 'desierta', '8': 'adjudicada', '15': 'revocada'}


def normalize_item(raw, mechanism, source, consulted, warnings):
    """Adapta v1 (licitaciones) y v2 (Compra Ágil, con campos anidados) a un contrato común."""
    if not isinstance(raw, dict):
        raise OpportunityError('Se omitió un registro que no es objeto JSON.')
    code = pick(raw, ['codigo', 'codigo_externo', 'CodigoExterno', 'id_licitacion', 'id'])
    name = pick(raw, ['nombre', 'titulo', 'Nombre', 'objeto', 'descripcion'])
    if code is None or name is None:
        raise OpportunityError('Se omitió un registro sin código o nombre verificables.')
    # En v1 el listado trae solo CodigoEstado y el detalle además Estado: se prefiere el código y se
    # traduce, para que ambas observaciones coincidan y no generen revisiones sin cambios reales.
    state = pick(raw, ['estado_oficial', 'estado.codigo', 'CodigoEstado', 'Estado', 'estado', 'codigo_estado'], 'desconocido')
    if isinstance(state, dict):
        state = pick(state, ['codigo', 'glosa'], 'desconocido')
    state = str(state).strip().lower()
    # «Desierta (o art. 3 ó 9 Ley 19.886)»: la aclaración legal no forma parte del estado.
    state = V1_STATES.get(state, re.sub(r'\s*\(.*$', '', state))
    buyer = pick(raw, ['institucion.organismo_comprador', 'Comprador.NombreOrganismo', 'comprador.nombre', 'organismo.nombre', 'NombreOrganismo', 'comprador', 'organismo'])
    if isinstance(buyer, dict):
        buyer = pick(buyer, ['nombre', 'razon_social', 'Nombre', 'NombreOrganismo'])
    buyer_rut = pick(raw, ['institucion.rut', 'Comprador.RutUnidad', 'comprador.rut', 'organismo.rut', 'RutOrganismo', 'rut_comprador'])
    products, categories = _products(raw)
    amount = pick(raw, ['montos.monto_disponible_clp', 'presupuesto.monto_disponible_clp', 'monto', 'MontoEstimado', 'monto_estimado', 'presupuesto.presupuesto_estimado', 'presupuesto'])
    clp_amount = pick(raw, ['montos.monto_disponible_clp', 'presupuesto.monto_disponible_clp']) is not None
    currency = 'CLP' if clp_amount else pick(raw, ['moneda', 'Moneda', 'montos.moneda', 'presupuesto.moneda', 'codigo_moneda'])
    if isinstance(amount, dict):
        amount = None
    description = _text(pick(raw, ['descripcion', 'Descripcion']))
    documents = pick(raw, ['documentos'], [])
    documents = [_text(pick(doc, ['nombre'])) for doc in documents if isinstance(doc, dict) and _text(pick(doc, ['nombre']))] if isinstance(documents, list) else []
    inferred = []
    item = {
        'codigo': str(code),
        'mecanismo': mechanism,
        'nombre': str(name),
        'estado_oficial': state,
        'fuente': source,
        'consultado_en': consulted,
        # En v2, `fechas.fecha_cierre` viene sin zona (hora de Chile); otros campos rotulan esa misma hora como Z.
        'fecha_cierre': _date(pick(raw, ['fecha_cierre', 'fechas.fecha_cierre', 'FechaCierre', 'Fechas.FechaCierre', 'fechaCierre', 'fecha_fin_ofertas', 'fecha_fin']), warnings, 'fecha_cierre', inferred),
        'fecha_inicio_ofertas': _date(pick(raw, ['fecha_inicio_ofertas', 'FechaInicio', 'fechaInicioOfertas', 'fecha_apertura_ofertas']), warnings, 'fecha_inicio_ofertas', inferred),
        'fecha_publicacion': _date(pick(raw, ['fecha_publicacion', 'fechas.fecha_publicacion', 'Fechas.FechaPublicacion']), [], 'fecha_publicacion'),
        'comprador': _text(buyer),
        'rut_comprador': _text(buyer_rut),
        'unidad_compra': _text(pick(raw, ['institucion.unidad_compra', 'Comprador.NombreUnidad'])),
        'region_comprador': _text(pick(raw, ['institucion.nombre_region', 'Comprador.RegionUnidad'])),
        'comuna_comprador': _text(pick(raw, ['Comprador.ComunaUnidad'])),
        'monto': _amount(amount),
        'moneda': currency,
        # La región del comprador no se usa como región de entrega: solo una región explícita.
        'region_entrega': pick(raw, ['region_entrega', 'RegionEntrega', 'regiones_entrega']),
        'direccion_entrega': _text(pick(raw, ['entrega.direccion_entrega', 'DireccionEntrega'])),
        'plazo_entrega_dias': pick(raw, ['entrega.plazo_entrega_dias']),
        'descripcion': description[:2000] if description else None,
        'tipo': _text(pick(raw, ['Tipo', 'tipo'])),
        'llamado': pick(raw, ['convocatoria.estado_convocatoria']),
        'ofertas_recibidas': pick(raw, ['resumen.total_ofertas_recibidas']),
        'documentos': documents[:30] or None,
        'url': pick(raw, ['url', 'Url', 'url_proceso', 'link']),
        'productos': products,
        'categorias': categories or None,
    }
    if inferred:
        item['zona_inferida'] = inferred
    if item['estado_oficial'] == 'desconocido':
        warnings.append(f'{item["codigo"]}: estado oficial ausente')
    if not item['fecha_cierre'] and mechanism != 'planificacion':
        warnings.append(f'{item["codigo"]}: cierre no verificado')
    # Sin valores vacíos: una observación más pobre (listado) no debe pisar lo que trajo el detalle.
    return {key: value for key, value in item.items() if value is not None and value != []}


def payload_items(data, resource):
    """Extrae listados sin confundir el detalle de un proceso con una página."""
    if resource == 'agil':
        payload = data.get('payload')
        if isinstance(payload, list):
            return payload, {}
        if not isinstance(payload, dict):
            raise OpportunityError('La respuesta v2 no contiene payload de lista o detalle.')
        pagination = payload.get('paginacion') if isinstance(payload.get('paginacion'), dict) else {}
        for key in ['items', 'resultados', 'licitaciones', 'compras_agiles', 'data']:
            if isinstance(payload.get(key), list):
                return payload[key], pagination
        if any(key in payload for key in ['codigo', 'id', 'codigo_externo']):
            return [payload], pagination
        if not payload:
            return [], pagination
        raise OpportunityError('No se reconoció la colección dentro de payload; conserva la respuesta para ajustar el adaptador.')
    listing = data.get('Listado')
    if isinstance(listing, list):
        return listing, {}
    if isinstance(data.get('licitacion'), dict):
        return [data['licitacion']], {}
    if isinstance(data.get('Licitacion'), dict):
        return [data['Licitacion']], {}
    if not data:
        return [], {}
    raise OpportunityError('No se reconoció el listado v1; conserva la respuesta original.')


def normalize_response(data, resource, source, consulted=None):
    consulted = utc_iso(consulted)
    mechanism = 'compra_agil' if resource == 'agil' else 'licitacion'
    raw_items, pagination = payload_items(data, resource)
    items, warnings, rejected = [], [], []
    for raw in raw_items:
        local_warnings = []
        try:
            item = normalize_item(raw, mechanism, source, consulted, local_warnings)
            items.append(item)
            warnings.extend(local_warnings)
        except OpportunityError as error:
            rejected.append(str(error))
    return {'items': items, 'paginacion': pagination, 'advertencias': warnings, 'omitidos': rejected}


def total_pages(pagination):
    for key in ['total_paginas', 'totalPaginas', 'total_pages', 'paginas']:
        value = pagination.get(key)
        if isinstance(value, int) and value >= 1:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) >= 1:
            return int(value)
    return None


def save_raw(directory, rut, resource, data, consulted):
    company = base.path_for(directory, rut).parent
    folder = company / 'fuentes' / resource
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    digest = hashlib.sha256(content).hexdigest()[:16]
    stamp = re.sub(r'[^0-9A-Za-z]+', '', consulted)[:20]
    target = folder / f'{stamp}-{digest}.json'
    if not target.exists():
        with target.open('xb') as out:
            os.chmod(target, 0o600)
            out.write(content)
    return target.relative_to(company).as_posix()


def request_page(resource, page, ticket, query=None, size=50, date=None, provider=None, change_from=None, change_to=None, state=None):
    args = [resource, '--out', 'no-se-escribe.json']
    if resource == 'agil':
        args += ['--pagina', str(page), '--tamano', str(size)]
        if query:
            args += ['--q', query]
        if state:
            args += ['--estado', state]
        if change_from and change_to:
            args += ['--cambio-desde', change_from, '--cambio-hasta', change_to]
    else:
        if date:
            args += ['--fecha', date]
        if provider:
            args += ['--proveedor', provider]
    parsed = api.parser().parse_args(args)
    return api.make_request(parsed, ticket)


def response_consulted(data, consulted_fn):
    """Una respuesta de caché conserva su observación original, no la hora del acceso."""
    return getattr(data, 'consulted_at', None) or consulted_fn()


def sync_agil(ticket, query=None, size=50, max_pages=100, fetch_fn=None, consulted_fn=None,
              change_from=None, change_to=None, page_fn=None, state='publicada'):
    """Sincroniza una ventana fija y entrega cada página válida antes de continuar."""
    fetch_fn = fetch_fn or api.fetch
    consulted_fn = consulted_fn or base.utc_now
    all_items, warnings, rejected, raw_pages = [], [], [], []
    seen_items = {}
    page = 1
    while page <= max_pages:
        request = request_page('agil', page, ticket, query, size, change_from=change_from, change_to=change_to, state=state)
        data = fetch_fn(request)
        consulted = response_consulted(data, consulted_fn)
        normalized = normalize_response(data, 'agil', 'API v2 Compra Ágil', consulted)
        new_items = []
        for item in normalized['items']:
            key = (item['mecanismo'], item['codigo'])
            if key in seen_items:
                if base.material_view(item) != base.material_view(seen_items[key]):
                    raise OpportunityError(f'El proceso {item["codigo"]} cambió durante el barrido; reintenta con una ventana acotada.')
                continue
            seen_items[key] = item
            all_items.append(item)
            new_items.append(item)
        if page > 1 and normalized['items'] and not new_items:
            raise OpportunityError('La paginación no avanzó; se detuvo antes de mover el cursor.')
        raw_pages.append((data, consulted))
        warnings.extend(normalized['advertencias'])
        rejected.extend(normalized['omitidos'])
        if page_fn:
            page_fn({
                'items': new_items, 'raw_pages': [(data, consulted)],
                'advertencias': normalized['advertencias'], 'omitidos': normalized['omitidos'],
                'paginas': 1, 'completa': False,
            })
        declared = total_pages(normalized['paginacion'])
        if declared is not None and page >= declared:
            return {'items': all_items, 'raw_pages': raw_pages, 'advertencias': warnings, 'omitidos': rejected, 'paginas': page, 'completa': True}
        if declared is None and not normalized['items']:
            return {'items': all_items, 'raw_pages': raw_pages, 'advertencias': warnings, 'omitidos': rejected, 'paginas': page - 1, 'completa': True}
        if declared is None and len(normalized['items']) < size:
            return {'items': all_items, 'raw_pages': raw_pages, 'advertencias': warnings, 'omitidos': rejected, 'paginas': page, 'completa': True}
        page += 1
    raise OpportunityError(f'Se alcanzó el límite de {max_pages} páginas; acota la búsqueda antes de continuar.')


def sync_once(resource, ticket, query=None, date=None, provider=None, fetch_fn=None, consulted_fn=None):
    fetch_fn = fetch_fn or api.fetch
    consulted_fn = consulted_fn or base.utc_now
    request = request_page(resource, 1, ticket, query=query, date=date, provider=provider)
    data = fetch_fn(request)
    consulted = response_consulted(data, consulted_fn)
    normalized = normalize_response(data, resource, 'API v1 Mercado Público', consulted)
    normalized.update({'raw_pages': [(data, consulted)], 'paginas': 1, 'completa': True})
    return normalized


MAX_DETAILS = 20


def focus_and_enrich(result, company, ticket, fetch_fn=None, consulted_fn=None, now=None, max_details=MAX_DETAILS):
    """Deja solo procesos abiertos afines al catálogo y trae su detalle v1.

    El listado v1 por fecha trae cientos de procesos con solo código, nombre, estado y cierre.
    Guardarlos todos inflaría la base sin aportar; el detalle agrega comprador, ítems y descripción.
    Un 429 o un presupuesto agotado se propaga para detener el lote.
    """
    import viabilidad
    fetch_fn = fetch_fn or api.fetch
    consulted_fn = consulted_fn or base.utc_now
    now = now or datetime.now(timezone.utc)
    facts = viabilidad.latest_facts(company)
    catalog = viabilidad.catalog_terms(facts)
    hours = company['preferencias']['horas_por_cerrar']
    kept, discarded_closed, discarded_catalog = [], 0, 0
    for item in result['items']:
        if base.classify(item, now, hours) in {'cerradas', 'suspendidas'}:
            discarded_closed += 1
            continue
        if catalog and not (viabilidad.matches(item['nombre'], catalog) or viabilidad.partial_matches(item['nombre'], catalog)):
            discarded_catalog += 1
            continue
        kept.append(item)
    enriched, raw_pages, warnings = [], list(result['raw_pages']), list(result['advertencias'])
    for index, item in enumerate(kept):
        if index >= max_details:
            enriched.append(item)
            continue
        request = api.make_request(api.parser().parse_args(['licitaciones', '--codigo', item['codigo'], '--out', 'no-se-escribe.json']), ticket)
        try:
            data = fetch_fn(request)
        except api.ApiError as error:
            if error.status == 429 or error.kind in {'cuota', 'enfriamiento', 'presupuesto'}:
                raise
            warnings.append(f'{item["codigo"]}: no se obtuvo el detalle; se conserva el listado')
            enriched.append(item)
            continue
        consulted = response_consulted(data, consulted_fn)
        detail = normalize_response(data, 'licitaciones', 'API v1 Mercado Público (detalle)', consulted)
        match = [entry for entry in detail['items'] if entry['codigo'] == item['codigo']]
        enriched.append(match[0] if match else item)
        warnings.extend(detail['advertencias'])
        raw_pages.append((data, consulted))
    focused = dict(result, items=enriched, raw_pages=raw_pages, advertencias=warnings)
    focused.update({
        'descartadas_cerradas': discarded_closed, 'descartadas_catalogo': discarded_catalog,
        'detalles': min(len(kept), max_details),
    })
    return focused


def persist_sync(directory, rut, result, resource='agil'):
    """Persistencia idempotente de una página o lote; no altera el resultado recibido."""
    company = base.load(directory, rut)
    folder = 'compra_agil' if resource == 'agil' else 'mercado_publico'
    paths = [save_raw(directory, rut, folder, data, consulted) for data, consulted in result['raw_pages']]
    if not result['items']:
        return {'actualizadas': 0, 'omitidas': 0, 'sin_cambios': 0}
    items = []
    for original in result['items']:
        item = original.copy()
        if paths:
            item['fuente'] = item['fuente'].split('; archivos=', 1)[0] + '; archivos=' + ', '.join(paths)
        items.append(item)
    outcome = base.merge_items(company, items)
    if outcome['actualizadas']:
        base.save(directory, company, reason=f'sincronizar {resource}: {outcome["actualizadas"]} oportunidades', author='asistente')
    return outcome
