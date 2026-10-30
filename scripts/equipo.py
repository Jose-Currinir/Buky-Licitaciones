"""Equipo por perfil y bandeja de salida de correo.

La skill no envía correos: prepara borradores con destinatarios del equipo y el asistente
los entrega con el complemento de correo del host (por ejemplo, Gmail en ChatGPT) tras
la confirmación del usuario. Después se marcan como enviados o descartados.
"""
import hashlib
import json
import re
import uuid

import base_empresa as base
import estado
from i18n import tr
from presentacion import local_date


ROLES = frozenset({'titular', 'equipo'})
AVISOS = frozenset({'recordatorios', 'resumen'})
DESTINOS = frozenset({'yo', 'equipo', 'todos'})
TIPOS = frozenset({'resumen', 'recordatorio', 'mensaje'})
ESTADOS_FINALES = frozenset({'enviado', 'descartado'})
EMAIL = re.compile(r'[^@\s<>,;:"()\[\]\\]+@[^@\s<>,;:"()\[\]\\]+\.[^@\s<>,;:"()\[\]\\]+')
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
SUBJECT_PREFIX = '[Buky Licitaciones] '
MAX_BODY = 20000


class TeamError(ValueError):
    pass


def normalize_email(value):
    email = str(value or '').strip().lower()
    if len(email) > 254 or not EMAIL.fullmatch(email):
        raise TeamError(tr('team.invalid_email'))
    return email


def _name(value):
    name = CONTROL.sub('', str(value or '')).strip()
    name = re.sub(r'\s+', ' ', name)
    if not 1 <= len(name) <= 120:
        raise TeamError(tr('team.invalid_name'))
    return name


def _avisos(values):
    values = sorted(set(values))
    if any(value not in AVISOS for value in values):
        raise TeamError(tr('team.invalid_alerts'))
    return values


def _member(row):
    item = dict(row)
    item['avisos'] = json.loads(item['avisos'])
    item['activo'] = bool(item['activo'])
    return item




def list_members(directory, rut, include_inactive=False):
    rut = base.normalize_rut(rut)
    query = 'SELECT * FROM equipo WHERE rut = ?' + ('' if include_inactive else ' AND activo = 1')
    with estado.connect(directory) as connection:
        rows = connection.execute(query + " ORDER BY rol = 'equipo', nombre, correo", (rut,)).fetchall()
    return [_member(row) for row in rows]


def get_member(directory, rut, identifier):
    rut = base.normalize_rut(rut)
    with estado.connect(directory) as connection:
        row = connection.execute('SELECT * FROM equipo WHERE rut = ? AND id = ?', (rut, identifier)).fetchone()
    if not row:
        raise TeamError(tr('team.not_found'))
    return _member(row)


def add_member(directory, rut, name, email, role='equipo', alerts=None):
    rut = base.normalize_rut(rut)
    base.load(directory, rut)
    name, email = _name(name), normalize_email(email)
    if role not in ROLES:
        raise TeamError(tr('team.invalid_role'))
    alerts = _avisos(sorted(AVISOS) if alerts is None else alerts)
    now = base.utc_now()
    with estado.connect(directory) as connection:
        existing = connection.execute('SELECT id, activo FROM equipo WHERE rut = ? AND correo = ?', (rut, email)).fetchone()
        if existing and existing['activo']:
            raise TeamError(tr('team.duplicate'))
        if existing:
            # Reincorporar a alguien conserva su id y la auditoría de envíos anteriores.
            identifier = existing['id']
            connection.execute(
                'UPDATE equipo SET nombre = ?, rol = ?, avisos = ?, activo = 1, actualizado_utc = ? WHERE id = ?',
                (name, role, json.dumps(alerts), now, identifier),
            )
        else:
            identifier = uuid.uuid4().hex[:12]
            connection.execute(
                'INSERT INTO equipo(id, rut, nombre, correo, rol, avisos, activo, creado_utc, actualizado_utc) '
                'VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)',
                (identifier, rut, name, email, role, json.dumps(alerts), now, now),
            )
        connection.commit()
    return get_member(directory, rut, identifier)


def update_member(directory, rut, identifier, name=None, email=None, role=None, alerts=None, active=None):
    current = get_member(directory, rut, identifier)
    updates = {}
    if name is not None:
        updates['nombre'] = _name(name)
    if email is not None and normalize_email(email) != current['correo']:
        updates['correo'] = normalize_email(email)
    if role is not None:
        if role not in ROLES:
            raise TeamError(tr('team.invalid_role'))
        updates['rol'] = role
    if alerts is not None:
        updates['avisos'] = json.dumps(_avisos(alerts))
    if active is not None:
        updates['activo'] = 1 if active else 0
    if not updates:
        return current
    updates['actualizado_utc'] = base.utc_now()
    assignments = ', '.join(key + ' = ?' for key in updates)
    try:
        with estado.connect(directory) as connection:
            connection.execute(f'UPDATE equipo SET {assignments} WHERE id = ?', (*updates.values(), identifier))
            connection.commit()
    except estado.sqlite3.IntegrityError:
        raise TeamError(tr('team.duplicate')) from None
    return get_member(directory, rut, identifier)


def remove_member(directory, rut, identifier):
    return update_member(directory, rut, identifier, active=False)


def recipients(directory, rut, targets=None, alert=None):
    """Resuelve yo/equipo/todos o ids a correos activos, sin duplicados y en orden estable."""
    members = list_members(directory, rut)
    targets = list(targets or ['todos'])
    selected = []
    for target in targets:
        if target == 'yo':
            matches = [item for item in members if item['rol'] == 'titular']
        elif target == 'equipo':
            matches = [item for item in members if item['rol'] == 'equipo']
        elif target == 'todos':
            matches = members
        else:
            matches = [item for item in members if item['id'] == target]
            if not matches:
                raise TeamError(tr('team.not_found'))
        selected.extend(item for item in matches if alert is None or alert in item['avisos'])
    unique, seen = [], set()
    for item in selected:
        if item['id'] not in seen:
            unique.append(item)
            seen.add(item['id'])
    if not unique:
        raise TeamError(tr('team.no_recipients'))
    return unique


def _clean_subject(value):
    subject = re.sub(r'[\r\n\t]+', ' ', CONTROL.sub('', str(value or ''))).strip()
    if not subject or len(subject) > 200:
        raise TeamError(tr('outbox.invalid_subject'))
    return subject if subject.startswith(SUBJECT_PREFIX) else SUBJECT_PREFIX + subject


def _clean_body(value):
    body = CONTROL.sub('', str(value or '')).replace('\r\n', '\n').replace('\r', '\n').strip()
    if not body or len(body) > MAX_BODY:
        raise TeamError(tr('outbox.invalid_body'))
    return body + '\n\n— ' + tr('outbox.footer')


def enqueue(directory, rut, origin, recipients_list, subject, body, automatic=False):
    rut = base.normalize_rut(rut)
    to = sorted({normalize_email(item['correo'] if isinstance(item, dict) else item) for item in recipients_list})
    if not to:
        raise TeamError(tr('team.no_recipients'))
    subject, body = _clean_subject(subject), _clean_body(body)
    identifier = hashlib.sha256(origin.encode('utf-8')).hexdigest()[:16]
    with estado.connect(directory) as connection:
        connection.execute(
            'INSERT INTO correo_salida(id, rut, origen, para, asunto, cuerpo, automatico, creado_utc) '
            'VALUES(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(origen) DO NOTHING',
            (identifier, rut, origin, json.dumps(to), subject, body, 1 if automatic else 0, base.utc_now()),
        )
        connection.commit()
    return get_draft(directory, identifier)


def _draft(row):
    item = dict(row)
    item['para'] = json.loads(item['para'])
    item['automatico'] = bool(item['automatico'])
    return item


def get_draft(directory, identifier):
    with estado.connect(directory) as connection:
        row = connection.execute('SELECT * FROM correo_salida WHERE id = ?', (identifier,)).fetchone()
    if not row:
        raise TeamError(tr('outbox.not_found'))
    return _draft(row)


def pending(directory, rut=None):
    query, params = "SELECT * FROM correo_salida WHERE estado = 'pendiente'", []
    if rut:
        query += ' AND rut = ?'
        params.append(base.normalize_rut(rut))
    with estado.connect(directory) as connection:
        rows = connection.execute(query + ' ORDER BY creado_utc, id', params).fetchall()
    return [_draft(row) for row in rows]


def resolve(directory, identifier, status, reference=None, rut=None):
    if status not in ESTADOS_FINALES:
        raise TeamError(tr('error.invalid_choice'))
    if reference is not None:
        reference = CONTROL.sub('', str(reference)).strip()[:300] or None
    draft = get_draft(directory, identifier)
    if rut and draft['rut'] != base.normalize_rut(rut):
        raise TeamError(tr('outbox.not_found'))
    with estado.connect(directory) as connection:
        changed = connection.execute(
            "UPDATE correo_salida SET estado = ?, resuelto_utc = ?, referencia = ? WHERE id = ? AND estado = 'pendiente'",
            (status, base.utc_now(), reference, identifier),
        )
        connection.commit()
    if not changed.rowcount:
        raise TeamError(tr('outbox.already_resolved'))
    return get_draft(directory, identifier)


def prepare(directory, rut, kind, targets=None, subject=None, text=None, reminder_id=None, summary=None, stamp=None):
    """Crea un borrador pendiente. El resumen llega ya renderizado desde buky.today."""
    if kind not in TIPOS:
        raise TeamError(tr('error.invalid_choice'))
    rut = base.normalize_rut(rut)
    company = base.load(directory, rut)
    zone = company['preferencias']['zona_horaria']
    stamp = stamp or base.utc_now()
    alert = None if targets else ('resumen' if kind == 'resumen' else 'recordatorios' if kind == 'recordatorio' else None)
    to = recipients(directory, rut, targets, alert)
    if kind == 'resumen':
        subject = subject or tr('outbox.summary_subject', fecha=local_date(stamp, zone)[:10])
        body = summary
        origin = 'resumen:' + rut + ':' + stamp
    elif kind == 'recordatorio':
        with estado.connect(directory) as connection:
            row = connection.execute('SELECT * FROM recordatorios WHERE id = ? AND rut = ?', (reminder_id, rut)).fetchone()
        if not row:
            raise TeamError(tr('reminder.not_found'))
        subject = subject or tr('outbox.reminder_subject', titulo=row['titulo'])
        body = tr('outbox.reminder_body', titulo=row['titulo'], fecha=local_date(row['vence_utc'], zone), detalle=row['detalle'] or '')
        origin = 'recordatorio:' + row['id'] + ':' + stamp
    else:
        if not subject or not text:
            raise TeamError(tr('outbox.message_required'))
        body = text
        origin = 'mensaje:' + rut + ':' + stamp + ':' + hashlib.sha256((subject + '\0' + text).encode('utf-8')).hexdigest()[:12]
    return enqueue(directory, rut, origin, to, subject, body)


def enqueue_reminders(directory, reminder_ids):
    """Usado por el servicio: un borrador por aviso entregado y por perfil, solo a quienes lo pidieron."""
    created = []
    if not reminder_ids:
        return created
    with estado.connect(directory) as connection:
        marks = ','.join('?' for _ in reminder_ids)
        rows = connection.execute(f'SELECT * FROM recordatorios WHERE id IN ({marks})', list(reminder_ids)).fetchall()
    for row in rows:
        try:
            to = recipients(directory, row['rut'], ['todos'], 'recordatorios')
        except TeamError:
            continue
        zone = base.load(directory, row['rut'])['preferencias']['zona_horaria']
        body = tr('outbox.reminder_body', titulo=row['titulo'], fecha=local_date(row['vence_utc'], zone), detalle=row['detalle'] or '')
        created.append(enqueue(
            directory, row['rut'], 'recordatorio:' + row['id'], to,
            tr('outbox.reminder_subject', titulo=row['titulo']), body, automatic=True,
        ))
    return created
