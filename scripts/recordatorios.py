"""Recordatorios UTC, deduplicados y con reintentos; notificaciones sin shell."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys

import base_empresa as base
import estado
import viabilidad as viability
from i18n import tr
from presentacion import local_date


class ReminderError(ValueError):
    pass


def _utc(value):
    if isinstance(value, str):
        value = base.moment(value)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReminderError(tr('reminder.timezone_required'))
    return base.utc_iso(value)


def _id(rut, process, kind, due):
    raw = '\0'.join([rut, process or '', kind, due]).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:32]


def valid_kind(kind):
    if kind in {'manual', 'cierre_proximo'}:
        return True
    if not isinstance(kind, str) or not kind.startswith('cierre_'):
        return False
    try:
        return 0 < float(kind.removeprefix('cierre_')) < 100000
    except ValueError:
        return False


def add(directory, rut, title, due, detail='', process=None, kind='manual', available=None, key=None):
    """Crea un aviso idempotente. `key` fija la identidad cuando la fecha de entrega varía."""
    rut = base.normalize_rut(rut)
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        raise ReminderError(tr('reminder.title_required'))
    if not valid_kind(kind):
        raise ReminderError(tr('reminder.kind_unknown'))
    due = _utc(due)
    available = _utc(available or due)
    if key is None:
        # Dos avisos manuales a la misma hora con distinto texto son avisos distintos.
        key = due + '\0' + title.strip() if kind == 'manual' else due
    identifier = _id(rut, process, kind, key)
    now = base.utc_now()
    with estado.connect(directory) as connection:
        inserted = connection.execute(
            'INSERT INTO recordatorios(id, rut, proceso, tipo, titulo, detalle, vence_utc, disponible_utc, creado_utc) '
            'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING',
            (identifier, rut, process, kind, title.strip(), str(detail or '')[:2000], due, available, now),
        ).rowcount
        connection.commit()
        row = connection.execute('SELECT * FROM recordatorios WHERE id = ?', (identifier,)).fetchone()
    return dict(row, creado=bool(inserted))


def wants_closing_alerts(item, evaluation):
    """Avisa lo que vale la pena: decisión participar, condicionada con buen ajuste o seguida por el usuario."""
    if (item.get('seguimiento') or {}).get('activo') is False:
        return False
    if (item.get('seguimiento') or {}).get('activo'):
        return evaluation['decision'] != 'no_participar'
    if evaluation['decision'] == 'participar':
        return True
    return evaluation['decision'] == 'participar_condicionado' and evaluation['ajuste_comercial'] in {'alto', 'medio'}


def sync_company(directory, rut, thresholds=(72, 24, 2), now=None):
    """Reconcilia cierres: nuevas fechas crean avisos y las anteriores se cancelan."""
    now = base.moment(_utc(now or datetime.now(timezone.utc)))
    rut = base.normalize_rut(rut)
    company = base.load(directory, rut)
    zone = company['preferencias']['zona_horaria']
    desired = set()
    created = 0
    for item in company['oportunidades'].values():
        evaluation = viability.evaluate(item, company, now)
        if not item.get('fecha_cierre') or not wants_closing_alerts(item, evaluation):
            continue
        closing = base.moment(item['fecha_cierre'])
        if closing <= now or evaluation['etapa'] not in {'abiertas', 'por_cerrar'}:
            continue
        future_thresholds = []
        for hours in sorted(set(thresholds), reverse=True):
            if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours <= 0:
                raise ReminderError(tr('reminder.threshold_positive'))
            due = closing - timedelta(hours=hours)
            if due > now:
                future_thresholds.append((hours, due))
        if future_thresholds:
            scheduled = future_thresholds
        else:
            scheduled = [('proximo', now)]
        for hours, due in scheduled:
            kind = f'cierre_{hours}' if hours != 'proximo' else 'cierre_proximo'
            due_utc = _utc(due)
            # El aviso inmediato se identifica por el cierre, no por «ahora», para no repetirse en cada ciclo.
            key = 'cierre:' + _utc(closing) if hours == 'proximo' else due_utc
            desired.add(_id(rut, item['codigo'], kind, key))
            saved = add(directory, rut, item['nombre'], due_utc, detail=tr('reminder.closing_detail', cierre=local_date(item['fecha_cierre'], zone), codigo=item['codigo']), process=item['codigo'], kind=kind, key=key)
            created += saved['creado']
    cancelled = 0
    with estado.connect(directory) as connection:
        rows = connection.execute(
            "SELECT id FROM recordatorios WHERE rut = ? AND estado = 'pendiente' AND tipo != 'manual'", (rut,)
        ).fetchall()
        for row in rows:
            if row['id'] not in desired:
                connection.execute("UPDATE recordatorios SET estado = 'cancelado' WHERE id = ?", (row['id'],))
                cancelled += 1
        connection.commit()
    return {'creados': created, 'cancelados': cancelled, 'activos': len(desired)}


def list_reminders(directory, rut=None, include_finished=False):
    query = 'SELECT * FROM recordatorios'
    clauses, params = [], []
    if rut:
        clauses.append('rut = ?')
        params.append(base.normalize_rut(rut))
    if not include_finished:
        clauses.append("estado = 'pendiente'")
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY vence_utc, id'
    with estado.connect(directory) as connection:
        return estado.rows_dict(connection.execute(query, params).fetchall())


def due(directory, now=None):
    now_utc = _utc(now or datetime.now(timezone.utc))
    with estado.connect(directory) as connection:
        return estado.rows_dict(connection.execute(
            "SELECT * FROM recordatorios WHERE estado = 'pendiente' AND disponible_utc <= ? ORDER BY vence_utc, id", (now_utc,)
        ).fetchall())


def applescript_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', ' ') + '"'


CHANNELS = frozenset({'automatico', 'escritorio', 'terminal'})
CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


def resolve_channel(channel='automatico', system=None, environ=None):
    if channel not in CHANNELS:
        raise ReminderError(tr('reminder.channel_unknown'))
    if channel != 'automatico':
        return channel
    system = system or platform.system()
    environ = os.environ if environ is None else environ
    headless = system == 'Linux' and not environ.get('DISPLAY') and not environ.get('WAYLAND_DISPLAY')
    return 'terminal' if headless else 'escritorio'


def terminal_text(value, single_line=False):
    text = CONTROL_CHARS.sub('', str(value or ''))
    if single_line:
        return re.sub(r'[\r\n\t]+', ' ', text)
    return text.replace('\r\n', '\n').replace('\r', '\n')


def terminal_notification(title, body):
    header = tr('reminder.terminal_header', titulo=terminal_text(title, single_line=True))
    detail = terminal_text(body)
    return header + ('\n' + detail if detail else '')


def powershell_string(value):
    # En una cadena con comillas simples PowerShell no expande variables ni subexpresiones;
    # también trata como comilla simple las variantes tipográficas, que se duplican igual.
    text = terminal_text(value)
    return "'" + re.sub(r"(['\u2018\u2019\u201a\u201b])", r"\1\1", text) + "'"


def notification_command(title, body, system=None):
    system = system or platform.system()
    if system == 'Darwin':
        script = 'display notification ' + applescript_string(body) + ' with title ' + applescript_string(title)
        return ['osascript', '-e', script]
    if system == 'Linux':
        if not shutil.which('notify-send'):
            raise ReminderError(tr('reminder.linux_missing'))
        return ['notify-send', '--', title, body]
    if system == 'Windows':
        # Título y cuerpo pueden venir de la API: van como literales entre comillas simples y el
        # script completo viaja codificado, de modo que PowerShell nunca los interpreta como código.
        script = (
            '$title = ' + powershell_string(title) + '; $body = ' + powershell_string(body) + '; '
            'Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; '
            '$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; '
            '$n.Visible = $true; $n.ShowBalloonTip(10000, $title, $body, [System.Windows.Forms.ToolTipIcon]::Info); '
            'Start-Sleep -Seconds 11; $n.Dispose()'
        )
        executable = shutil.which('powershell') or shutil.which('pwsh')
        if not executable:
            raise ReminderError(tr('reminder.windows_missing'))
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        return [executable, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    raise ReminderError(tr('reminder.unsupported'))


def notify(title, body, runner=None, system=None, channel='automatico', environ=None, output=None):
    channel = resolve_channel(channel, system, environ)
    if channel == 'terminal':
        print(terminal_notification(title, body), file=output or sys.stderr, flush=True)
        return channel
    runner = runner or subprocess.run
    command = notification_command(title, body, system)
    result = runner(command, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ReminderError(tr('reminder.notify_failed'))
    return channel


def dispatch(directory, now=None, notifier=None, channel='automatico'):
    channel = resolve_channel(channel)
    if notifier is None:
        notifier = lambda title, body: notify(title, body, channel=channel)
    now = now or datetime.now(timezone.utc)
    sent, failed = [], []
    if now.tzinfo is None:
        raise ReminderError(tr('reminder.dispatch_timezone_required'))
    for reminder in due(directory, now):
        # Lease atómico: otro proceso no puede reclamar el mismo aviso durante 5 minutos.
        lease = _utc(now + timedelta(minutes=5))
        with estado.connect(directory) as connection:
            claimed = connection.execute(
                "UPDATE recordatorios SET disponible_utc = ? WHERE id = ? AND estado = 'pendiente' AND disponible_utc = ?",
                (lease, reminder['id'], reminder['disponible_utc']),
            )
            connection.commit()
        if not claimed.rowcount:
            continue
        try:
            notifier(reminder['titulo'], reminder['detalle'])
            sent_at = base.utc_now()
            with estado.connect(directory) as connection:
                finished = connection.execute(
                    "UPDATE recordatorios SET estado = 'enviado', enviado_utc = ?, ultimo_error = NULL WHERE id = ? AND estado = 'pendiente' AND disponible_utc = ?",
                    (sent_at, reminder['id'], lease),
                )
                connection.commit()
            if finished.rowcount:
                sent.append(reminder['id'])
        except (ReminderError, OSError, subprocess.SubprocessError) as error:
            attempts = reminder['intentos'] + 1
            retry = now + timedelta(minutes=min(60, 2 ** min(attempts, 6)))
            message = str(error)[:500]
            with estado.connect(directory) as connection:
                connection.execute(
                    "UPDATE recordatorios SET intentos = ?, disponible_utc = ?, ultimo_error = ? WHERE id = ? AND estado = 'pendiente' AND disponible_utc = ?",
                    (attempts, _utc(retry), message, reminder['id'], lease),
                )
                connection.commit()
            failed.append({'id': reminder['id'], 'error': message, 'reintento_utc': _utc(retry)})
    return {'enviados': sent, 'fallidos': failed}


def cancel(directory, rut, identifier):
    with estado.connect(directory) as connection:
        result = connection.execute(
            "UPDATE recordatorios SET estado = 'cancelado' WHERE id = ? AND rut = ? AND estado = 'pendiente'",
            (identifier, base.normalize_rut(rut)),
        )
        connection.commit()
    if not result.rowcount:
        raise ReminderError(tr('reminder.not_found'))
