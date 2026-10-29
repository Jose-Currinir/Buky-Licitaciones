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

import base_empresa as base
import correo
import equipo
import oportunidades as opportunities
import recordatorios
import servicio
import ticket_config
import viabilidad as viability
from i18n import tr
from presentacion import local_date, print_json, render_evaluation


DEFAULT_DATA_DIR = '~/.buky/licitaciones'


class BukyError(ValueError):
    pass


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
    return target


def sync_company(directory, rut, queries=None, resource='agil', date=None, provider=None, ticket=None,
                 fetch_fn=None, consulted_fn=None, client=None, request_budget=100):
    directory = data_directory(directory)
    ticket = ticket or ticket_config.configured_ticket(env_path(directory))
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
    if client is None and fetch_fn is None:
        client = opportunities.api.ApiExecutor(directory=directory, max_attempts=request_budget)
    transport = client.fetch if client is not None else fetch_fn
    pending = list(queries)
    result = {
        'recurso': resource, 'consultadas': 0, 'nuevas': 0, 'omitidas': 0,
        'advertencias': [], 'errores': [], 'cobertura': 'pendiente',
        'consultas_pendientes': pending.copy(), 'detenida_por_cuota': False,
        'presupuesto_agotado': False, 'reintentar_en': None,
    }

    def persist_page(page):
        persisted = opportunities.persist_sync(directory, rut, page, resource)
        result['consultadas'] += len(page['items'])
        result['nuevas'] += persisted['actualizadas']
        result['omitidas'] += len(page['omitidos'])
        result['advertencias'].extend(page['advertencias'])

    for query in queries:
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
        matches = [item for key, item in company['oportunidades'].items() if item['codigo'] == code]
        if not matches:
            raise BukyError(tr('error.not_found'))
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


def today(directory, rut, queries=None, synchronize=False, code=None, limit=5, now=None, fetch_fn=None, consulted_fn=None):
    if limit < 1 or limit > 100:
        raise BukyError(tr('error.invalid_choice'))
    sync_result = None
    if synchronize:
        sync_result = sync_company(directory, rut, queries=queries, fetch_fn=fetch_fn, consulted_fn=consulted_fn)
    company, evaluations = evaluate_company(directory, rut, code=code, active_only=not code, now=now)
    report = {
        'schema_version': 1,
        'rut': base.normalize_rut(rut),
        'perfil': base.profile_summary(company),
        'generado_en': base.utc_now(),
        'sincronizacion': sync_result,
        'total': len(evaluations),
        'evaluaciones': evaluations,
    }
    report_path = save_report(directory, rut, report)
    report['archivo'] = str(report_path)
    return company, report


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
    return parser


def render_sync(sync, locale='es'):
    lines = [tr('viability.sync_summary', locale, consultadas=sync['consultadas'], nuevas=sync['nuevas'], omitidas=sync['omitidas'])]
    lines.append(tr('sync.complete' if sync.get('cobertura') == 'completa' else 'sync.partial', locale))
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


def render_today(company, report, limit, locale):
    evaluations = report['evaluaciones']
    lines = [tr('today.title', locale), tr('today.count', locale, cantidad=report['total'])]
    if not evaluations:
        lines.append(tr('viability.none', locale))
    for entry in evaluations[:limit]:
        item, evaluation = entry['oportunidad'], entry['evaluacion']
        lines.extend(['', render_evaluation(item, evaluation, company['preferencias']['zona_horaria'], locale)])
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
                    print(tr('reminder.item', args.locale, fecha=local_date(item['vence_utc']), titulo=item['titulo'], id=item['id']))
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
                result = equipo.resolve(directory, args.id, state, args.referencia)
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
            print_json(report)
        else:
            print(render_today(company, report, args.limite, args.locale))
        return 1 if (report.get('sincronizacion') or {}).get('errores') else 0
    except (BukyError, base.DataError, opportunities.OpportunityError, opportunities.api.ApiError, ticket_config.ConfigError, recordatorios.ReminderError, servicio.ServiceError, correo.MailError, correo.secretos.SecretError, equipo.TeamError, OSError, ValueError) as error:
        domain_errors = (BukyError, base.DataError, opportunities.OpportunityError, opportunities.api.ApiError, ticket_config.ConfigError, recordatorios.ReminderError, servicio.ServiceError, correo.MailError, correo.secretos.SecretError, equipo.TeamError)
        message = str(error) if isinstance(error, domain_errors) else tr('error.generic', args.locale, detalle=str(error))
        print(message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
