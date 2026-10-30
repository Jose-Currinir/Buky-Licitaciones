"""Presentación local: traducciones y conversiones de tiempo solo al mostrar."""
import json
from zoneinfo import ZoneInfo

import base_empresa as base
from i18n import tr


def local_date(value, timezone_name='America/Santiago'):
    if not value:
        return None
    moment = base.moment(value)
    return moment.astimezone(ZoneInfo(timezone_name)).strftime('%d-%m-%Y %H:%M %Z')


def event_text(event, locale='es'):
    key = event['codigo']
    params = {key: value for key, value in event.items() if key not in {'codigo', 'fuente'}}
    return tr('reason.' + key, locale, **params)


def action_text(event, locale='es'):
    return tr('action.' + event['codigo'], locale)


def render_evaluation(item, evaluation, timezone_name='America/Santiago', locale='es'):
    lines = [
        tr('viability.title', locale, nombre=item['nombre']),
        tr('viability.decision.' + evaluation['decision'], locale),
        tr('viability.fit_label', locale, valor=tr('viability.fit.' + evaluation['ajuste_comercial'], locale)),
        tr('today.closing', locale, fecha=local_date(item['fecha_cierre'], timezone_name)) if item.get('fecha_cierre') else tr('today.no_closing', locale),
    ]
    for title_key, events in [('viability.blockers', evaluation['bloqueos']), ('viability.pending', evaluation['pendientes']), ('viability.reasons', evaluation['razones'])]:
        if events:
            lines.append(tr(title_key, locale) + ':')
            lines.extend('- ' + event_text(event, locale) for event in events)
    if evaluation['proximas_acciones']:
        lines.append(tr('viability.actions', locale) + ':')
        lines.extend('- ' + action_text(event, locale) for event in evaluation['proximas_acciones'])
    return '\n'.join(lines)


def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
