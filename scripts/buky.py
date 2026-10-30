#!/usr/bin/env python3
"""Punto de entrada local de Buky Licitaciones. Python 3.10+, sin dependencias."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import anotaciones
import base_empresa as base
import correo
import estado
import informe
import equipo
import oportunidades as opportunities
import recordatorios
import servicio
import sii
import ticket_config
import viabilidad as viability
from i18n import tr
from presentacion import local_date, print_json, render_evaluation


DEFAULT_DATA_DIR = '~/.buky/licitaciones'
MAX_SAVED_REPORTS = 30


class BukyError(ValueError):
    pass


def profile_zone(directory, rut):
    try:
        return base.load(directory, rut)['preferencias']['zona_horaria']
    except base.DataError:
        return 'America/Santiago'


def data_directory(value=None):
    return Path(value or os.environ.get('BUKY_DATA_DIR', DEFAULT_DATA_DIR)).expanduser().resolve()


def env_path(directory):
    return data_directory(directory) / '.env'


def save_report(directory, rut, report):
    company = base.path_for(directory, rut).parent
    folder = company / 'evaluaciones'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    digest = hashlib.sha256(content).hexdigest()[:16]
    stamp = re.sub(r'[^0-9A-Za-z]+', '', report['generado_en'])[:20]
    target = folder / f'evaluacion-{stamp}-{digest}.json'
    with target.open('xb') as out:
        os.chmod(target, 0o600)
        out.write(content)
    # Conserva solo los informes más recientes para que «hoy» no acumule archivos sin límite.
    for old in sorted(folder.glob('evaluacion-*.json'))[:-MAX_SAVED_REPORTS]:
        old.unlink(missing_ok=True)
    return target


def catalog_queries(directory, rut, limit=10):
    """Términos de búsqueda por defecto: el catálogo vigente del perfil."""
    from viabilidad import catalog_raw, latest_facts
    facts = latest_facts(base.load(directory, rut))
    catalog = catalog_raw(facts)
    if isinstance(catalog, str):
        catalog = [catalog]
    return [str(value) for value in catalog[:limit] if str(value).strip()]


def ticket_command(directory):
    script = Path(__file__).resolve().with_name('ticket_config.py')
    return f'python3 "{script}" --data-dir "{data_directory(directory)}"'


def require_ticket(directory):
    try:
        return ticket_config.configured_ticket(env_path(directory))
    except ticket_config.ConfigError:
        raise BukyError(tr('sync.ticket_missing', comando=ticket_command(directory))) from None


def sync_company(directory, rut, queries=None, resource='agil', date=None, provider=None, ticket=None,
                 fetch_fn=None, consulted_fn=None, client=None, request_budget=100):
    directory = data_directory(directory)
    if resource == 'agil' and not any(query and query.strip() for query in queries or []):
        queries = catalog_queries(directory, rut)
    if resource == 'agil':
        cleaned, seen = [], set()
        for query in queries or []:
            if not query or not query.strip():
                continue
            query = ' '.join(query.split())
            key = query.casefold()
            if key not in seen:
                cleaned.append(query)
                seen.add(key)
        queries = cleaned
        if not queries:
            raise BukyError(tr('sync.no_queries'))
    elif resource == 'licitaciones':
        if not date and not provider:
            raise BukyError(tr('sync.v1_filter_required'))
        queries = [None]
    else:
        raise BukyError(tr('error.invalid_choice'))
    ticket = ticket or require_ticket(directory)
    if client is None and fetch_fn is None:
        client = opportunities.api.ApiExecutor(directory=directory, max_attempts=request_budget)
    transport = client.fetch if client is not None else fetch_fn
    pending = list(queries)
    result = {
        'recurso': resource, 'consultadas': 0, 'nuevas': 0, 'sin_cambios': 0, 'omitidas': 0,
        'advertencias': [], 'errores': [], 'cobertura': 'pendiente',
        'consultas_pendientes': pending.copy(), 'detenida_por_cuota': False,
        'presupuesto_agotado': False, 'reintentar_en': None,
        'descartadas_cerradas': 0, 'descartadas_catalogo': 0, 'detalles': 0,
    }

    def progress(key, **params):
        # Avance por stderr: cada solicitud a la API puede tardar varios segundos y la salida --json sigue limpia.
        print(tr(key, **params), file=sys.stderr, flush=True)

    def persist_page(page):
        persisted = opportunities.persist_sync(directory, rut, page, resource)
        progress('sync.progress_page', cantidad=len(page['items']))
        result['consultadas'] += len(page['items'])
        result['nuevas'] += persisted['actualizadas']
        result['sin_cambios'] += persisted.get('sin_cambios', 0)
        result['omitidas'] += len(page['omitidos'])
        result['advertencias'].extend(page['advertencias'])

    for query in queries:
        progress('sync.progress_query', termino=query) if query else progress('sync.progress_v1')
        try:
            if resource == 'agil':
                opportunities.sync_agil(
                    ticket, query=query, fetch_fn=transport, consulted_fn=consulted_fn,
                    page_fn=persist_page,
                )
            else:
                synced = opportunities.sync_once(
                    resource, ticket, date=date, provider=provider,
                    fetch_fn=transport, consulted_fn=consulted_fn,
                )
                synced = opportunities.focus_and_enrich(
                    synced, base.load(directory, rut), ticket, fetch_fn=transport, consulted_fn=consulted_fn,
                )
                for key in ['descartadas_cerradas', 'descartadas_catalogo', 'detalles']:
                    result[key] += synced[key]
                persist_page(synced)
            pending.pop(0)
        except (opportunities.OpportunityError, ticket_config.ConfigError, base.DataError,
                opportunities.api.ApiError, OSError) as error:
            result['errores'].append(str(error))
            if isinstance(error, opportunities.api.ApiError):
                if error.status == 429 or error.kind in {'cuota', 'enfriamiento'}:
                    result['detenida_por_cuota'] = True
                    result['reintentar_en'] = error.retry_at
                    break
                if error.kind == 'presupuesto':
                    result['presupuesto_agotado'] = True
                    break
    result['consultas_pendientes'] = pending
    result['cobertura'] = 'completa' if not pending and not result['errores'] else 'parcial'
    if result['consultadas']:
        with estado.connect(directory) as connection:
            estado.set_cursor(connection, 'ultima_sincronizacion:' + base.normalize_rut(rut), base.utc_now())
    if client is not None:
        result.update({
            'solicitudes_reales': client.attempts,
            'respuestas_cache': client.cache_hits,
            'reintentos': client.retries,
        })
    return result


def api_error_types():
    # Evita capturar errores de programación o imprimir contenido privado de respuestas.
    return (ticket_config.ConfigError, base.DataError, opportunities.api.ApiError, OSError)


def evaluate_company(directory, rut, code=None, active_only=False, now=None):
    directory = data_directory(directory)
    company = base.load(directory, rut)
    if code:
        matches = [item for key, item in company['oportunidades'].items() if item['codigo'].casefold() == code.strip().casefold()]
        if not matches:
            raise BukyError(tr('annotation.opportunity_not_found', codigo=code))
    elif active_only:
        matches = base.select_items(company, 'activas', now=now)
    else:
        matches = list(company['oportunidades'].values())
    evaluations = []
    for item in matches:
        evaluation = viability.evaluate(item, company, now=now)
        evaluations.append({'oportunidad': item, 'evaluacion': evaluation})
    evaluations.sort(key=lambda entry: viability.prioritize(entry['oportunidad'], entry['evaluacion']))
    return company, evaluations


def mechanism_for(code):
    """Compra Ágil usa sufijo COTaa (p. ej. 1234-5-COT26); el resto se consulta como licitación v1."""
    return 'agil' if re.search(r'-COT\d{2}$', code.strip(), re.IGNORECASE) else 'licitaciones'


def fetch_process(directory, rut, code, fetch_fn=None, consulted_fn=None, client=None):
    """Trae el detalle oficial de un código y lo guarda, conservando las anotaciones existentes."""
    directory = data_directory(directory)
    code = code.strip()
    resource = mechanism_for(code)
    ticket = require_ticket(directory)
    request = opportunities.api.make_request(
        opportunities.api.parser().parse_args([resource, '--codigo', code, '--out', 'no-se-escribe.json']), ticket,
    )
    if client is None and fetch_fn is None:
        client = opportunities.api.ApiExecutor(directory=directory, max_attempts=5)
    data = (client.fetch if client is not None else fetch_fn)(request)
    consulted = opportunities.response_consulted(data, consulted_fn or base.utc_now)
    source = 'API v2 Compra Ágil' if resource == 'agil' else 'API v1 Mercado Público'
    normalized = opportunities.normalize_response(data, resource, source, consulted)
    normalized['items'] = [item for item in normalized['items'] if item['codigo'].casefold() == code.casefold()]
    if not normalized['items']:
        raise BukyError(tr('evaluate.not_found_remote', codigo=code))
    normalized['raw_pages'] = [(data, consulted)]
    persisted = opportunities.persist_sync(directory, rut, normalized, resource)
    return {
        'recurso': resource, 'codigo': code, 'consultadas': 1, 'nuevas': persisted['actualizadas'],
        'omitidas': 0, 'advertencias': normalized['advertencias'], 'errores': [],
        'cobertura': 'completa', 'consultas_pendientes': [],
    }


def last_sync(directory, rut):
    with estado.connect(data_directory(directory)) as connection:
        return estado.get_cursor(connection, 'ultima_sincronizacion:' + base.normalize_rut(rut))


def stage_counts(company, now=None):
    """Cuántas oportunidades hay por etapa, para no ocultar las que quedan fuera de «hoy»."""
    now = now or datetime.now(timezone.utc)
    hours = company['preferencias']['horas_por_cerrar']
    counts = {}
    for item in company['oportunidades'].values():
        stage = base.classify(item, now, hours)
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def today(directory, rut, queries=None, synchronize=False, code=None, limit=5, now=None, fetch_fn=None, consulted_fn=None):
    if limit < 1 or limit > 100:
        raise BukyError(tr('error.invalid_choice'))
    sync_result = None
    if synchronize and code:
        sync_result = fetch_process(directory, rut, code, fetch_fn=fetch_fn, consulted_fn=consulted_fn)
    elif synchronize:
        sync_result = sync_company(directory, rut, queries=queries, fetch_fn=fetch_fn, consulted_fn=consulted_fn)
    company, evaluations = evaluate_company(directory, rut, code=code, active_only=not code, now=now)
    report = {
        'schema_version': 1,
        'rut': base.normalize_rut(rut),
        'perfil': base.profile_summary(company),
        'generado_en': base.utc_now(),
        'sincronizacion': sync_result,
        'total': len(evaluations),
        'conteo_etapas': stage_counts(company, now),
        'ultima_sincronizacion': last_sync(directory, rut),
        'evaluaciones': evaluations,
    }
    report_path = save_report(directory, rut, report)
    report['archivo'] = str(report_path)
    return company, report


def write_report(directory, rut, limit=30, out=None, now=None):
    """Escribe el informe HTML privado del perfil y devuelve su ruta y cifras clave."""
    if limit < 1 or limit > 200:
        raise BukyError(tr('error.invalid_choice'))
    directory = data_directory(directory)
    now = now or datetime.now(timezone.utc)
    company, evaluations = evaluate_company(directory, rut, active_only=True, now=now)
    html = informe.render(company, evaluations, now, stage_counts(company, now), last_sync(directory, rut), limit)
    if out:
        target = Path(out).expanduser().resolve()
        if target.suffix.lower() != '.html' or target.exists():
            raise BukyError(tr('error.invalid_choice'))
    else:
        stamp = now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        target = base.path_for(directory, rut).parent / 'informes' / f'informe-{stamp}.html'
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with target.open('x', encoding='utf-8') as handle:
        os.chmod(target, 0o600)
        handle.write(html)
    decisions = {}
    for entry in evaluations:
        decisions[entry['evaluacion']['decision']] = decisions.get(entry['evaluacion']['decision'], 0) + 1
    return {'archivo': str(target), 'activas': len(evaluations), 'decisiones': decisions}


def build_parser():
    parser = argparse.ArgumentParser(prog='buky-licitaciones', description=tr('app.name'))
    parser.add_argument('--data-dir', default=DEFAULT_DATA_DIR)
    parser.add_argument('--locale', default='es')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--version', action='store_true')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('perfiles')
    profile = commands.add_parser('perfil')
    profile_commands = profile.add_subparsers(dest='profile_command', required=True)
    create = profile_commands.add_parser('crear')
    create.add_argument('--rut', required=True)
    create.add_argument('--tipo', choices=sorted(base.PROFILE_TYPES), required=True)
    create.add_argument('--nombre')
    create.add_argument('--inicio-actividades', action=argparse.BooleanOptionalAction, default=None)
    update = profile_commands.add_parser('actualizar')
    update.add_argument('--rut', required=True)
    update.add_argument('--nombre')
    update.add_argument('--inicio-actividades', action=argparse.BooleanOptionalAction, default=None)
    for name in ['hoy', 'evaluar']:
        sub = commands.add_parser(name)
        sub.add_argument('--rut', required=True)
        sub.add_argument('--codigo')
        sub.add_argument('--q', action='append', default=[])
        sub.add_argument('--sincronizar', action='store_true')
        sub.add_argument('--limite', type=int, default=5)
        sub.add_argument('--ahora', help=argparse.SUPPRESS)
    sync = commands.add_parser('sincronizar')
    sync.add_argument('--rut', required=True)
    sync.add_argument('--recurso', choices=['agil', 'licitaciones'], default='agil')
    sync.add_argument('--q', action='append', default=[])
    sync.add_argument('--fecha')
    sync.add_argument('--proveedor')
    reminder = commands.add_parser('recordar')
    reminder.add_argument('--rut', required=True)
    reminder.add_argument('--texto', required=True)
    reminder.add_argument('--fecha', required=True, help='ISO-8601 con zona horaria')
    reminder.add_argument('--detalle', default='')
    reminder.add_argument('--proceso')
    reminder_list = commands.add_parser('recordatorios')
    reminder_list.add_argument('--rut')
    reminder_list.add_argument('--todos', action='store_true')
    reminder_list.add_argument('--cancelar')
    service = commands.add_parser('servicio')
    service_commands = service.add_subparsers(dest='service_command', required=True)
    for name in ['ejecutar', 'iniciar']:
        sub = service_commands.add_parser(name)
        sub.add_argument('--ahora', help=argparse.SUPPRESS)
    for name in ['instalar', 'habilitar', 'deshabilitar', 'estado']:
        service_commands.add_parser(name)
    config = service_commands.add_parser('configurar')
    config.add_argument('--intervalo', type=int)
    config.add_argument('--intervalo-sincronizacion', type=int)
    config.add_argument('--sincronizar', action=argparse.BooleanOptionalAction, default=None)
    config.add_argument('--horas', type=float, nargs='+')
    config.add_argument('--canal', choices=['automatico', 'escritorio', 'terminal'], help=tr('service.channel_help'))
    config.add_argument('--correo', action=argparse.BooleanOptionalAction, default=None, dest='correo_recordatorios')
    mail = commands.add_parser('correo')
    mail_commands = mail.add_subparsers(dest='mail_command', required=True)
    connect = mail_commands.add_parser('conectar')
    connect.add_argument('--proveedor', choices=['gmail', 'microsoft'], required=True)
    connect.add_argument('--correo', required=True)
    connect.add_argument('--client-id')
    connect.add_argument('--sin-navegador', action='store_true', help=tr('mail.no_browser_help'))
    connect.add_argument('--puerto-oauth', type=int, help=tr('mail.oauth_port_help'))
    disconnect = mail_commands.add_parser('desconectar')
    disconnect.add_argument('--proveedor', choices=['gmail', 'microsoft'], required=True)
    disconnect.add_argument('--correo', required=True)
    mail_commands.add_parser('sincronizar')
    imported = mail_commands.add_parser('importar')
    imported.add_argument('--archivo', required=True)
    imported.add_argument('--rut')
    pending = mail_commands.add_parser('pendientes')
    pending.add_argument('--rut')
    for name in ['mostrar', 'revisar']:
        sub = mail_commands.add_parser(name)
        sub.add_argument('--proveedor', choices=['gmail', 'microsoft', 'eml'], required=True)
        sub.add_argument('--id', required=True)
    filters = mail_commands.add_parser('configurar')
    filters.add_argument('--proveedor', choices=['gmail', 'microsoft'], required=True)
    filters.add_argument('--correo', required=True)
    filters.add_argument('--palabras', nargs='+')
    filters.add_argument('--remitentes', nargs='+')
    filters.add_argument('--dias-iniciales', type=int)
    filters.add_argument('--max-mensajes', type=int)
    catalog = commands.add_parser('catalogo')
    catalog.add_argument('--rut', required=True)
    catalog.add_argument('--agregar', nargs='+', help='Términos que la empresa realmente vende')
    catalog.add_argument('--quitar', nargs='+')
    catalog.add_argument('--excluir', nargs='+', help='Rubros que no quiere licitar')
    catalog.add_argument('--permitir', nargs='+', help='Quita términos de las exclusiones')
    catalog.add_argument('--estado', choices=sorted(anotaciones.FACT_STATES), default='declarado')
    catalog.add_argument('--fuente')
    terms = commands.add_parser('condiciones')
    terms.add_argument('--rut', required=True)
    terms.add_argument('--regiones', nargs='*', help='Nombres o números de región, o «nacional»')
    terms.add_argument('--horas-preparacion', type=float)
    terms.add_argument('--margen-minimo', help='Fracción (0.15) o porcentaje (15)')
    terms.add_argument('--emt', action=argparse.BooleanOptionalAction, default=None, help='Declara si es empresa de menor tamaño cuando el SII no lo informa')
    terms.add_argument('--estado', choices=sorted(anotaciones.FACT_STATES), default='declarado')
    terms.add_argument('--fuente')
    requirement = commands.add_parser('requisito')
    requirement_commands = requirement.add_subparsers(dest='requirement_command', required=True)
    for name in ['listar', 'agregar', 'marcar']:
        sub = requirement_commands.add_parser(name)
        sub.add_argument('--rut', required=True)
        sub.add_argument('--codigo', required=True)
        if name == 'agregar':
            sub.add_argument('--texto', required=True)
            sub.add_argument('--opcional', action='store_true')
        if name == 'marcar':
            sub.add_argument('--id', required=True)
        if name != 'listar':
            sub.add_argument('--estado', choices=sorted(anotaciones.REQUIREMENT_STATES), default='pendiente' if name == 'agregar' else None, required=name == 'marcar')
            sub.add_argument('--fuente', help='Documento y página, por ejemplo «Bases administrativas, p. 12»')
            sub.add_argument('--evidencia', help='Antecedente de la empresa que lo acredita')
    follow = commands.add_parser('seguir')
    follow.add_argument('--rut', required=True)
    follow.add_argument('--codigo', required=True)
    follow.add_argument('--no', action='store_true', dest='silenciar', help='Deja de recibir avisos de cierre de esta oportunidad')
    costs = commands.add_parser('costos')
    costs.add_argument('--rut', required=True)
    costs.add_argument('--codigo', required=True)
    costs.add_argument('--costo', required=True, help='Costo neto total')
    costs.add_argument('--precio', required=True, help='Precio neto ofertado')
    costs.add_argument('--moneda', default='CLP')
    costs.add_argument('--fuente')
    lines = commands.add_parser('giros')
    lines.add_argument('--rut', required=True)
    lines.add_argument('--sin-tamano', action='store_true', help='Omite la nómina de empresas (190 MB) y busca solo los giros')
    lines.add_argument('--actualizar', action='store_true', help='Revisa si el SII publicó una nómina nueva aunque la caché sea reciente')
    report = commands.add_parser('informe')
    report.add_argument('--rut', required=True)
    report.add_argument('--limite', type=int, default=30)
    report.add_argument('--out', help='Archivo .html nuevo; por defecto en la carpeta privada del perfil')
    report.add_argument('--ahora', help=argparse.SUPPRESS)
    team = commands.add_parser('equipo')
    team_commands = team.add_subparsers(dest='team_command', required=True)
    team_list = team_commands.add_parser('listar')
    team_list.add_argument('--rut', required=True)
    team_list.add_argument('--todos', action='store_true')
    team_add = team_commands.add_parser('agregar')
    team_add.add_argument('--rut', required=True)
    team_add.add_argument('--nombre', required=True)
    team_add.add_argument('--correo', required=True)
    team_add.add_argument('--rol', choices=sorted(equipo.ROLES), default='equipo')
    team_add.add_argument('--avisos', nargs='*', choices=sorted(equipo.AVISOS))
    team_edit = team_commands.add_parser('editar')
    team_edit.add_argument('--rut', required=True)
    team_edit.add_argument('--id', required=True)
    team_edit.add_argument('--nombre')
    team_edit.add_argument('--correo')
    team_edit.add_argument('--rol', choices=sorted(equipo.ROLES))
    team_edit.add_argument('--avisos', nargs='*', choices=sorted(equipo.AVISOS))
    team_edit.add_argument('--activo', action=argparse.BooleanOptionalAction, default=None)
    team_remove = team_commands.add_parser('quitar')
    team_remove.add_argument('--rut', required=True)
    team_remove.add_argument('--id', required=True)
    outbox = commands.add_parser('aviso')
    outbox_commands = outbox.add_subparsers(dest='outbox_command', required=True)
    prepare = outbox_commands.add_parser('preparar')
    prepare.add_argument('--rut', required=True)
    prepare.add_argument('--tipo', choices=sorted(equipo.TIPOS), required=True)
    prepare.add_argument('--para', nargs='+', help='yo, equipo, todos o ids del equipo')
    prepare.add_argument('--asunto')
    prepare.add_argument('--texto')
    prepare.add_argument('--recordatorio')
    prepare.add_argument('--limite', type=int, default=5)
    prepare.add_argument('--ahora', help=argparse.SUPPRESS)
    outbox_pending = outbox_commands.add_parser('pendientes')
    outbox_pending.add_argument('--rut')
    for name in ['enviado', 'descartar']:
        sub = outbox_commands.add_parser(name)
        sub.add_argument('--id', required=True)
        sub.add_argument('--referencia')
        sub.add_argument('--rut', help='Perfil dueño del borrador; evita resolver uno de otro perfil')
    return parser


def render_sync(sync, locale='es'):
    lines = [tr('viability.sync_summary', locale, consultadas=sync['consultadas'], nuevas=sync['nuevas'], sin_cambios=sync.get('sin_cambios', 0), omitidas=sync['omitidas'])]
    lines.append(tr('sync.complete' if sync.get('cobertura') == 'completa' else 'sync.partial', locale))
    if sync.get('descartadas_cerradas') or sync.get('descartadas_catalogo') or sync.get('detalles'):
        lines.append(tr('sync.focused', locale, cerradas=sync.get('descartadas_cerradas', 0), catalogo=sync.get('descartadas_catalogo', 0), detalles=sync.get('detalles', 0)))
    pending = [str(query) for query in sync.get('consultas_pendientes', []) if query]
    if pending:
        lines.append(tr('sync.pending_queries', locale, consultas=', '.join(pending)))
    if sync.get('detenida_por_cuota') and sync.get('reintentar_en'):
        lines.append(tr('sync.retry_at', locale, fecha=sync['reintentar_en']))
    if sync.get('presupuesto_agotado'):
        lines.append(tr('sync.budget_exhausted', locale))
    if 'solicitudes_reales' in sync:
        lines.append(tr('sync.stats', locale, solicitudes=sync['solicitudes_reales'], cache=sync['respuestas_cache'], reintentos=sync['reintentos']))
    return lines


def render_today(company, report, limit, locale, single=False):
    evaluations = report['evaluaciones']
    if single:
        lines = []
    else:
        count_key = 'today.count_one' if report['total'] == 1 else 'today.count'
        lines = [tr('today.title', locale), tr(count_key, locale, cantidad=report['total'])]
        others = report.get('conteo_etapas', {})
        hidden = [tr('today.stage.' + stage, locale, cantidad=others[stage]) for stage in ['por_verificar', 'no_iniciadas', 'planificadas'] if others.get(stage)]
        if hidden:
            lines.append(tr('today.hidden', locale, detalle=', '.join(hidden)))
    if not evaluations:
        lines.append(tr('viability.none', locale))
    for entry in evaluations[:limit]:
        item, evaluation = entry['oportunidad'], entry['evaluacion']
        block = render_evaluation(item, evaluation, company['preferencias']['zona_horaria'], locale)
        lines.extend([block] if single and not lines else ['', block])
    if len(evaluations) > limit:
        lines.append(tr('today.more', locale, cantidad=len(evaluations) - limit))
    if report.get('sincronizacion'):
        sync = report['sincronizacion']
        lines.extend(['', *render_sync(sync, locale)])
        lines.extend('- ' + error for error in sync['errores'])
    return '\n'.join(lines)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        version = Path(__file__).resolve().parents[1] / 'VERSION'
        print(version.read_text().strip())
        return 0
    if not args.command:
        parser.print_help()
        return 0
    try:
        directory = data_directory(args.data_dir)
        now = base.moment(args.ahora) if getattr(args, 'ahora', None) else None
        if args.command == 'perfiles':
            profiles = base.list_profiles(directory)
            if args.json:
                print_json(profiles)
            elif not profiles:
                print(tr('profile.none', args.locale))
            else:
                for item in profiles:
                    print(tr('profile.item', args.locale, nombre=item['nombre'] or tr('profile.unknown_name', args.locale), tipo=tr('profile.type.' + item['tipo_perfil'], args.locale), rut=item['rut']))
            return 0
        if args.command == 'perfil':
            if args.profile_command == 'crear':
                data = base.init(directory, args.rut, args.tipo, args.nombre, args.inicio_actividades)
                result = base.profile_summary(data)
                message = tr('profile.created', args.locale)
            else:
                data = base.load(directory, args.rut)
                result = base.update_identity(data, args.nombre, args.inicio_actividades)
                base.save(directory, data, reason='actualizar identidad del perfil')
                message = tr('profile.updated', args.locale)
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'sincronizar':
            result = sync_company(directory, args.rut, args.q, args.recurso, args.fecha, args.proveedor)
            if args.json:
                print_json(result)
            else:
                print('\n'.join(render_sync(result, args.locale)))
                for error in result['errores']:
                    print('- ' + error, file=sys.stderr)
            return 1 if result['errores'] else 0
        if args.command == 'recordar':
            result = recordatorios.add(directory, args.rut, args.texto, args.fecha, args.detalle, args.proceso)
            if args.json:
                print_json(result)
            else:
                company = base.load(directory, args.rut)
                print(tr('reminder.saved', args.locale, fecha=local_date(result['vence_utc'], company['preferencias']['zona_horaria'])))
            return 0
        if args.command == 'recordatorios':
            if args.cancelar:
                if not args.rut:
                    raise BukyError(tr('error.company_required', args.locale))
                recordatorios.cancel(directory, args.rut, args.cancelar)
                result = {'estado': 'cancelado', 'id': args.cancelar}
            else:
                result = recordatorios.list_reminders(directory, args.rut, args.todos)
            if args.json:
                print_json(result)
            elif args.cancelar:
                print(tr('reminder.cancelled', args.locale))
            elif not result:
                print(tr('reminder.none', args.locale))
            else:
                for item in result:
                    print(tr('reminder.item', args.locale, fecha=local_date(item['vence_utc'], profile_zone(directory, item['rut'])), titulo=item['titulo'], id=item['id']))
            return 0
        if args.command == 'correo':
            command = args.mail_command
            if command == 'conectar':
                result = correo.connect(
                    directory, args.proveedor, args.correo, args.client_id,
                    open_browser=not args.sin_navegador, oauth_port=args.puerto_oauth,
                )
                message = tr('mail.connected', args.locale)
            elif command == 'desconectar':
                result = correo.disconnect(directory, args.proveedor, args.correo)
                message = tr('mail.disconnected', args.locale)
            elif command == 'sincronizar':
                result = correo.sync_configured(directory)
                message = ''
            elif command == 'importar':
                result = correo.import_eml(directory, args.archivo, args.rut)
                message = tr('mail.duplicate' if result['estado'] == 'duplicado' else 'mail.imported', args.locale)
            elif command == 'pendientes':
                result = correo.pending(directory, args.rut)
                message = tr('mail.pending_none', args.locale) if not result else ''
            elif command == 'mostrar':
                result = correo.read_message(directory, args.proveedor, args.id)
                message = ''
            elif command == 'revisar':
                result = correo.mark_reviewed(directory, args.proveedor, args.id)
                message = tr('mail.reviewed', args.locale)
            else:
                config = correo.load_config(directory)
                matches = [item for item in config['cuentas'] if item['proveedor'] == args.proveedor and item['correo'].lower() == args.correo.lower()]
                if not matches:
                    raise correo.MailError(tr('mail.not_connected', args.locale))
                updates = {
                    'palabras': args.palabras, 'remitentes': args.remitentes,
                    'dias_iniciales': args.dias_iniciales, 'max_mensajes': args.max_mensajes,
                }
                matches[0].update({key: value for key, value in updates.items() if value is not None})
                correo.validate_account(matches[0])
                correo.save_config(directory, config)
                if args.palabras is not None or args.remitentes is not None:
                    correo.forget_filtered(directory, args.proveedor)
                result = matches[0]
                message = tr('service.config_saved', args.locale)
            if args.json or command in {'mostrar', 'sincronizar'}:
                print_json(result)
            elif command == 'pendientes' and result:
                for item in result:
                    print(tr('mail.pending_item', args.locale, proveedor=item['proveedor'], id=item['mensaje_id'], archivo=item['archivo']))
            elif command == 'sincronizar':
                pass
            else:
                print(message)
            if command == 'sincronizar' and not args.json:
                for item in result.get('cuentas', []):
                    print(tr('mail.sync_summary', args.locale, importados=item['importados'], duplicados=item['duplicados'], filtrados=item['filtrados']))
                for item in result.get('errores', []):
                    print('- ' + item['error'], file=sys.stderr)
            return 1 if isinstance(result, dict) and result.get('errores') else 0
        if args.command == 'giros':
            result = sii.lookup(directory, args.rut, include_size=not args.sin_tamano, refresh=args.actualizar)
            if args.json:
                print_json(result)
            elif result['estado'] == 'no_encontrado':
                print(tr('sii.not_found', args.locale))
            else:
                print(tr('sii.found', args.locale, cantidad=len(result['actividades']), giros='; '.join(item['descripcion'] for item in result['actividades'])))
                size = (result.get('empresa') or {}).get('tramo_ventas')
                if size:
                    info = result['empresa']
                    print(tr('sii.size', args.locale, anio=info['anio_comercial'], tramo=size['nombre'], rango=f" ({size['rango_uf']})" if size['rango_uf'] else '', trabajadores=info['trabajadores'] if info['trabajadores'] is not None else '?'))
                if result['sugerencias_catalogo']:
                    print(tr('sii.suggestions', args.locale, terminos=', '.join(result['sugerencias_catalogo'])))
            return 0
        if args.command == 'informe':
            result = write_report(directory, args.rut, args.limite, args.out, now)
            print_json(result) if args.json else print(tr('report.saved', args.locale, archivo=result['archivo']))
            return 0
        if args.command == 'catalogo':
            result = anotaciones.catalog(directory, args.rut, args.agregar, args.quitar, args.excluir, args.permitir, args.estado, args.fuente)
            empty = tr('annotation.empty', args.locale)
            message = tr('annotation.catalog', args.locale, catalogo=', '.join(result['catalogo']) or empty, exclusiones=', '.join(result['exclusiones']) or empty)
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'condiciones':
            result = anotaciones.conditions(directory, args.rut, args.regiones, args.horas_preparacion, args.margen_minimo, args.estado, args.fuente, args.emt)
            empty = tr('annotation.empty', args.locale)
            margin = result['margen_minimo']
            message = tr('annotation.conditions', args.locale,
                         regiones=', '.join(result['regiones_atencion'] or []) or empty,
                         horas=f"{result['horas_preparacion']:g}" if result['horas_preparacion'] is not None else empty,
                         margen=f'{margin:.0%}' if isinstance(margin, (int, float)) else empty)
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'requisito':
            command = args.requirement_command
            if command == 'listar':
                result = anotaciones.requirements(directory, args.rut, args.codigo)
                lines = [tr('annotation.requirement_item', args.locale, id=item.get('id', '-'), estado=item.get('estado', 'pendiente'),
                            obligatorio=tr('annotation.mandatory' if item.get('obligatorio') else 'annotation.optional', args.locale),
                            requisito=item.get('requisito', '')) for item in result['requisitos'] if isinstance(item, dict)]
                message = '\n'.join(lines) or tr('annotation.requirements_none', args.locale)
            elif command == 'agregar':
                result = anotaciones.add_requirement(directory, args.rut, args.codigo, args.texto, not args.opcional, args.estado, args.fuente, args.evidencia)
                message = tr('annotation.requirement_saved', args.locale, id=result['id'], estado=result['estado'])
            else:
                result = anotaciones.mark_requirement(directory, args.rut, args.codigo, args.id, args.estado, args.evidencia, args.fuente)
                message = tr('annotation.requirement_saved', args.locale, id=result['id'], estado=result['estado'])
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'seguir':
            result = anotaciones.follow(directory, args.rut, args.codigo, not args.silenciar)
            message = tr('annotation.followed' if result['activo'] else 'annotation.muted', args.locale, codigo=result['codigo'])
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'costos':
            result = anotaciones.register_costs(directory, args.rut, args.codigo, args.costo, args.precio, args.moneda, args.fuente)
            message = tr('annotation.costs_saved', args.locale, margen=f'{float(result["margen"]):.1%}')
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'equipo':
            command = args.team_command
            if command == 'listar':
                result = equipo.list_members(directory, args.rut, args.todos)
                message = '\n'.join(tr('team.item', args.locale, nombre=item['nombre'], correo=item['correo'], rol=item['rol'], avisos=', '.join(item['avisos']) or '-', id=item['id']) for item in result) or tr('team.none', args.locale)
            elif command == 'agregar':
                result = equipo.add_member(directory, args.rut, args.nombre, args.correo, args.rol, args.avisos)
                message = tr('team.added', args.locale, nombre=result['nombre'], correo=result['correo'])
            elif command == 'editar':
                result = equipo.update_member(directory, args.rut, args.id, args.nombre, args.correo, args.rol, args.avisos, args.activo)
                message = tr('team.updated', args.locale)
            else:
                result = equipo.remove_member(directory, args.rut, args.id)
                message = tr('team.removed', args.locale)
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'aviso':
            command = args.outbox_command
            if command == 'preparar':
                summary = None
                if args.tipo == 'resumen':
                    company, report = today(directory, args.rut, limit=args.limite, now=now)
                    summary = render_today(company, report, args.limite, args.locale)
                result = equipo.prepare(directory, args.rut, args.tipo, args.para, args.asunto, args.texto, args.recordatorio, summary)
                message = tr('outbox.prepared', args.locale, id=result['id'], para=', '.join(result['para']))
            elif command == 'pendientes':
                result = equipo.pending(directory, args.rut)
                message = '\n'.join(tr('outbox.item', args.locale, id=item['id'], asunto=item['asunto'], para=', '.join(item['para'])) for item in result) or tr('outbox.none', args.locale)
            else:
                state = 'enviado' if command == 'enviado' else 'descartado'
                result = equipo.resolve(directory, args.id, state, args.referencia, args.rut)
                message = tr('outbox.resolved', args.locale, estado=state)
            print_json(result) if args.json else print(message)
            return 0
        if args.command == 'servicio':
            if args.service_command == 'configurar':
                updates = {
                    'intervalo_segundos': args.intervalo,
                    'intervalo_sincronizacion_minutos': args.intervalo_sincronizacion,
                    'sincronizar_oportunidades': args.sincronizar,
                    'horas_recordatorios': args.horas,
                    'canal_notificaciones': args.canal,
                    'correo_recordatorios': args.correo_recordatorios,
                }
                result = servicio.save_config(directory, {key: value for key, value in updates.items() if value is not None})
                message = tr('service.config_saved', args.locale)
            elif args.service_command == 'ejecutar':
                result = servicio.run_once(directory, now=now)
                message = tr('service.done', args.locale, avisos=len(result['recordatorios']['enviados']), errores=len(result['errores']))
            elif args.service_command == 'iniciar':
                result = servicio.run_forever(directory)
                message = tr('service.done', args.locale, avisos=len(result['recordatorios']['enviados']), errores=len(result['errores']))
            elif args.service_command == 'instalar':
                result = servicio.definition(directory)
                message = tr('service.definition', args.locale)
            elif args.service_command == 'habilitar':
                result = servicio.enable(directory)
                message = tr('service.enabled', args.locale)
            elif args.service_command == 'deshabilitar':
                result = servicio.disable(directory)
                message = tr('service.disabled', args.locale)
            else:
                result = servicio.status(directory)
                message = tr('service.running' if result['ejecutando'] else 'service.not_running', args.locale)
            print_json(result) if args.json else print(message)
            return 1 if isinstance(result, dict) and result.get('errores') else 0
        company, report = today(directory, args.rut, args.q, args.sincronizar, args.codigo, args.limite, now)
        if args.json:
            # El informe completo queda guardado en «archivo»; la salida se limita para no saturar al asistente.
            print_json(dict(report, evaluaciones=report['evaluaciones'][:args.limite], mostradas=min(args.limite, report['total'])))
        else:
            print(render_today(company, report, args.limite, args.locale, single=args.command == 'evaluar'))
        return 1 if (report.get('sincronizacion') or {}).get('errores') else 0
    except (BukyError, base.DataError, opportunities.OpportunityError, opportunities.api.ApiError, ticket_config.ConfigError, recordatorios.ReminderError, servicio.ServiceError, correo.MailError, correo.secretos.SecretError, equipo.TeamError, anotaciones.AnnotationError, sii.SiiError, OSError, ValueError) as error:
        domain_errors = (BukyError, base.DataError, opportunities.OpportunityError, opportunities.api.ApiError, ticket_config.ConfigError, recordatorios.ReminderError, servicio.ServiceError, correo.MailError, correo.secretos.SecretError, equipo.TeamError, anotaciones.AnnotationError, sii.SiiError)
        message = str(error) if isinstance(error, domain_errors) else tr('error.generic', args.locale, detalle=str(error))
        if args.json:
            print_json({'ok': False, 'error': {'tipo': type(error).__name__, 'mensaje': message}})
        print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
