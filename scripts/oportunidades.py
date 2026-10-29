"""Adquisición paginada y normalización conservadora de oportunidades."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import base_empresa as base
import mercado_publico as api


class OpportunityError(ValueError):
    pass


def utc_iso(value=None):
    if value is None:
        return base.utc_now()
    return base.moment(value).isoformat().replace('+00:00', 'Z')


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


def _date(raw, warnings, field):
    if raw in (None, ''):
        return None
    try:
        return utc_iso(str(raw))
    except base.DataError:
        warnings.append(f'{field}: fecha ausente de zona o inválida; requiere verificación')
        return None


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


def normalize_item(raw, mechanism, source, consulted, warnings):
    if not isinstance(raw, dict):
        raise OpportunityError('Se omitió un registro que no es objeto JSON.')
    code = pick(raw, ['codigo', 'codigo_externo', 'CodigoExterno', 'id_licitacion', 'id'])
    name = pick(raw, ['nombre', 'titulo', 'Nombre', 'objeto', 'descripcion'])
    if code is None or name is None:
        raise OpportunityError('Se omitió un registro sin código o nombre verificables.')
    state = pick(raw, ['estado_oficial', 'estado', 'Estado', 'CodigoEstado', 'codigo_estado'], 'desconocido')
    buyer = pick(raw, ['comprador.nombre', 'organismo.nombre', 'NombreOrganismo', 'comprador', 'organismo'])
    if isinstance(buyer, dict):
        buyer = pick(buyer, ['nombre', 'razon_social', 'Nombre'])
    buyer_rut = pick(raw, ['comprador.rut', 'organismo.rut', 'RutOrganismo', 'rut_comprador'])
    products = pick(raw, ['productos', 'rubros', 'familias'], [])
    if isinstance(products, str):
        products = [products]
    if not isinstance(products, list):
        products = []
    products = [str(pick(item, ['nombre', 'descripcion', 'titulo'], '')) if isinstance(item, dict) else str(item) for item in products]
    item = {
        'codigo': str(code),
        'mecanismo': mechanism,
        'nombre': str(name),
        'estado_oficial': str(state).strip().lower(),
        'fuente': source,
        'consultado_en': consulted,
        'fecha_cierre': _date(pick(raw, ['fecha_cierre', 'FechaCierre', 'fechaCierre', 'fecha_fin_ofertas', 'fecha_fin']), warnings, 'fecha_cierre'),
        'fecha_inicio_ofertas': _date(pick(raw, ['fecha_inicio_ofertas', 'FechaInicio', 'fechaInicioOfertas', 'fecha_apertura_ofertas']), warnings, 'fecha_inicio_ofertas'),
        'comprador': str(buyer) if buyer is not None else None,
        'rut_comprador': str(buyer_rut) if buyer_rut is not None else None,
        'monto': _amount(pick(raw, ['monto', 'MontoEstimado', 'monto_estimado', 'presupuesto'])),
        'moneda': pick(raw, ['moneda', 'Moneda', 'codigo_moneda']),
        'region_entrega': pick(raw, ['region_entrega', 'RegionEntrega', 'regiones_entrega']),
        'url': pick(raw, ['url', 'Url', 'url_proceso', 'link']),
        'productos': [value for value in products if value],
    }
    if item['estado_oficial'] == 'desconocido':
        warnings.append(f'{item["codigo"]}: estado oficial ausente')
    if not item['fecha_cierre'] and mechanism != 'planificacion':
        warnings.append(f'{item["codigo"]}: cierre no verificado')
    return {key: value for key, value in item.items() if value is not None}


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


def request_page(resource, page, ticket, query=None, size=50, date=None, provider=None, change_from=None, change_to=None):
    args = [resource, '--out', 'no-se-escribe.json']
    if resource == 'agil':
        args += ['--pagina', str(page), '--tamano', str(size)]
        if query:
            args += ['--q', query]
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
              change_from=None, change_to=None, page_fn=None):
    """Sincroniza una ventana fija y entrega cada página válida antes de continuar."""
    fetch_fn = fetch_fn or api.fetch
    consulted_fn = consulted_fn or base.utc_now
    all_items, warnings, rejected, raw_pages = [], [], [], []
    seen_items = {}
    page = 1
    while page <= max_pages:
        request = request_page('agil', page, ticket, query, size, change_from=change_from, change_to=change_to)
        data = fetch_fn(request)
        consulted = response_consulted(data, consulted_fn)
        normalized = normalize_response(data, 'agil', 'API v2 Compra Ágil', consulted)
        new_items = []
        for item in normalized['items']:
            key = (item['mecanismo'], item['codigo'])
            if key in seen_items:
                if item != seen_items[key]:
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


def persist_sync(directory, rut, result, resource='agil'):
    """Persistencia idempotente de una página o lote; no altera el resultado recibido."""
    company = base.load(directory, rut)
    folder = 'compra_agil' if resource == 'agil' else 'mercado_publico'
    paths = [save_raw(directory, rut, folder, data, consulted) for data, consulted in result['raw_pages']]
    if not result['items']:
        return {'actualizadas': 0, 'omitidas': 0}
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
