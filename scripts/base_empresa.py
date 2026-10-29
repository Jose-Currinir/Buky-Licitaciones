#!/usr/bin/env python3
"""Base privada por RUT y clasificación de oportunidades. Sin dependencias externas."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import version_store as versions

class DataError(ValueError):
    pass


def normalize_rut(value):
    if not isinstance(value, str):
        raise DataError('RUT inválido: se requiere texto con dígito verificador.')
    clean = value.strip().upper().replace('.', '').replace('-', '')
    if not re.fullmatch(r'[0-9]{1,8}[0-9K]', clean) or int(clean[:-1]) == 0:
        raise DataError('RUT inválido: verifica formato y dígito verificador.')
    body = str(int(clean[:-1]))
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(body)))
    digit = 11 - total % 11
    expected = '0' if digit == 11 else 'K' if digit == 10 else str(digit)
    if clean[-1] != expected:
        raise DataError('El dígito verificador del RUT no coincide.')
    return body + '-' + expected


def display_rut(value):
    body, digit = normalize_rut(value).split('-')
    return f'{int(body):,}'.replace(',', '.') + '-' + digit


def moment(value):
    if not isinstance(value, str):
        raise DataError('Fecha inválida: requiere ISO-8601 con zona horaria.')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except ValueError:
        raise DataError('Fecha inválida: requiere ISO-8601 con zona horaria.') from None


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def positive_hours(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise DataError('El umbral de cierre debe ser un número positivo de horas.')
    return value


CLOSED = {'cerrada', 'adjudicada', 'desierta', 'cancelada', 'revocada', 'proveedor_seleccionado', 'oc_emitida', '6', '7', '8', '18'}
OPEN = {'publicada', 'abierta', '5'}
SUSPENDED = {'suspendida', '19'}


def classify(item, now=None, hours=72):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DataError('La hora de clasificación requiere zona horaria.')
    positive_hours(hours)
    state = str(item.get('estado_oficial', '')).strip().lower()
    if state in CLOSED:
        return 'cerradas'
    if state in SUSPENDED:
        return 'suspendidas'
    if item.get('mecanismo') == 'planificacion':
        return 'planificadas'
    try:
        end = moment(item['fecha_cierre']) if item.get('fecha_cierre') else None
        start = moment(item['fecha_inicio_ofertas']) if item.get('fecha_inicio_ofertas') else None
    except DataError:
        return 'por_verificar'
    if end and end <= now:
        return 'cerradas'
    if state not in OPEN or end is None or (start and start >= end):
        return 'por_verificar'
    if start and start > now:
        return 'no_iniciadas'
    if end - now <= timedelta(hours=hours):
        return 'por_cerrar'
    return 'abiertas'


def path_for(directory, rut):
    return Path(directory).expanduser() / normalize_rut(rut) / 'base.json'


PROFILE_TYPES = {'empresa', 'persona_natural'}


def profile_name(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160 or any(ord(char) < 32 for char in value):
        raise DataError('El nombre del perfil debe tener entre 1 y 160 caracteres, sin controles.')
    return value.strip()


def activity_status(value):
    if value is not None and type(value) is not bool:
        raise DataError('inicio_actividades requiere true, false o null mientras no esté confirmado.')
    return value


def profile_summary(data):
    confirmed = False
    for fact in data.get('hechos', []):
        if fact.get('campo') == 'identidad_confirmada':
            confirmed = fact.get('valor') is True
    return {
        'rut': data['rut'],
        'tipo_perfil': data.get('tipo_perfil', 'empresa'),
        'nombre': data.get('nombre'),
        'inicio_actividades': data.get('inicio_actividades'),
        'identidad_confirmada': confirmed,
    }


def list_profiles(directory):
    root = Path(directory).expanduser()
    if not root.exists():
        return []
    profiles = []
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            rut = normalize_rut(entry.name)
        except DataError:
            continue
        if rut != entry.name or not (entry / 'base.json').is_file():
            continue
        profiles.append(profile_summary(load(root, rut)))
    return sorted(profiles, key=lambda item: (item['tipo_perfil'], (item['nombre'] or item['rut']).casefold(), item['rut']))


def update_identity(data, nombre=None, inicio_actividades=None):
    name = profile_name(nombre)
    status = activity_status(inicio_actividades)
    if name is None and status is None:
        raise DataError('Indica un nombre o un estado de inicio de actividades para actualizar.')
    if name is not None:
        data['nombre'] = name
    if status is not None:
        data['inicio_actividades'] = status
    return profile_summary(data)


def load(directory, rut):
    path = path_for(directory, rut)
    try:
        data = versions.read_current(path)
    except (OSError, ValueError):
        raise DataError('Base no disponible o ilegible; inicializa el perfil o revisa el archivo.') from None
    if data.get('schema_version') != 1 or data.get('rut') != normalize_rut(rut):
        raise DataError('La base no coincide con el perfil o versión esperada.')
    profile_type = data.get('tipo_perfil', 'empresa')
    if profile_type not in PROFILE_TYPES:
        raise DataError('La base contiene un tipo de perfil desconocido.')
    data['tipo_perfil'] = profile_type
    data['nombre'] = profile_name(data.get('nombre'))
    data['inicio_actividades'] = activity_status(data.get('inicio_actividades'))
    return data


def save(directory, data, create=False, reason='actualizar base', author='asistente'):
    try:
        versions.commit(path_for(directory, data['rut']), data, create=create, reason=reason, author=author)
    except versions.VersionError as error:
        raise DataError(str(error)) from None


def init(directory, rut, tipo='empresa', nombre=None, inicio_actividades=None):
    if tipo not in PROFILE_TYPES:
        raise DataError('El tipo de perfil debe ser empresa o persona_natural.')
    data = {
        'schema_version': 1,
        'rut': normalize_rut(rut),
        'tipo_perfil': tipo,
        'nombre': profile_name(nombre),
        'inicio_actividades': activity_status(inicio_actividades),
        'creado_en': utc_now(),
        'hechos': [],
        'registros': [],
        'oportunidades': {},
        'versiones': [],
        'preferencias': {'incluir_cerradas': False, 'horas_por_cerrar': 72, 'zona_horaria': 'America/Santiago'},
    }
    save(directory, data, create=True, reason='iniciar expediente de ' + tipo)
    return data


def source_record(item):
    if not isinstance(item, dict) or not isinstance(item.get('fuente'), str) or not item['fuente'].strip():
        raise DataError('Cada registro requiere una fuente no vacía.')
    moment(item.get('consultado_en'))


def merge_items(data, items):
    if not isinstance(items, list):
        raise DataError('La importación requiere una lista JSON.')
    keys = set()
    # Validate the entire batch before mutation.
    for item in items:
        source_record(item)
        if item.get('mecanismo') not in {'licitacion', 'compra_agil', 'planificacion'}:
            raise DataError('Mecanismo desconocido.')
        for field in ['codigo', 'nombre', 'estado_oficial']:
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise DataError('Faltan campos de identificación/estado en una oportunidad.')
        for field in ['fecha_cierre', 'fecha_inicio_ofertas']:
            if item.get(field) is not None:
                moment(item[field])
        key = item['mecanismo'] + ':' + item['codigo']
        if key in keys:
            raise DataError('Lote con código/mecanismo duplicado.')
        keys.add(key)
        old = data['oportunidades'].get(key)
        if old and moment(item['consultado_en']) == moment(old['consultado_en']) and item != old:
            raise DataError('Observaciones distintas con la misma fecha; revisa el conflicto.')
    updated = skipped = 0
    for item in items:
        key = item['mecanismo'] + ':' + item['codigo']
        old = data['oportunidades'].get(key)
        if old and moment(item['consultado_en']) <= moment(old['consultado_en']):
            skipped += 1
            continue
        if old:
            data['versiones'].append(old)
        data['oportunidades'][key] = item.copy()
        updated += 1
    return {'actualizadas': updated, 'omitidas': skipped}


def update_preferences(data, incoming):
    if not isinstance(incoming, dict) or set(incoming) - {'incluir_cerradas', 'horas_por_cerrar', 'zona_horaria'}:
        raise DataError('Preferencias desconocidas; usa incluir_cerradas, horas_por_cerrar o zona_horaria.')
    if 'incluir_cerradas' in incoming and type(incoming['incluir_cerradas']) is not bool:
        raise DataError('incluir_cerradas requiere true o false.')
    if 'horas_por_cerrar' in incoming:
        positive_hours(incoming['horas_por_cerrar'])
    if 'zona_horaria' in incoming:
        try:
            ZoneInfo(incoming['zona_horaria'])
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise DataError('Zona horaria IANA inválida.') from None
    data['preferencias'].update(incoming)


def select_items(data, view='todas', now=None, include_closed=None, hours=None):
    preferences = data['preferencias']
    hours = positive_hours(hours if hours is not None else preferences['horas_por_cerrar'])
    if include_closed is None:
        include_closed = preferences['incluir_cerradas']
    now = now or datetime.now(timezone.utc)
    views = {'activas': {'abiertas', 'por_cerrar'}, 'futuras': {'planificadas', 'no_iniciadas'}, 'todas': {'planificadas', 'no_iniciadas', 'abiertas', 'por_cerrar', 'cerradas', 'por_verificar', 'suspendidas'}}
    accepted = views.get(view, {view})
    result = []
    for item in data['oportunidades'].values():
        stage = classify(item, now, hours)
        if stage not in accepted or (stage == 'cerradas' and not include_closed):
            continue
        record = dict(item, etapa=stage)
        if stage in {'abiertas', 'por_cerrar', 'no_iniciadas'}:
            record['horas_hasta_cierre'] = round((moment(item['fecha_cierre']) - now).total_seconds() / 3600, 2)
        result.append(record)
    return sorted(result, key=lambda x: (x['etapa'], x.get('horas_hasta_cierre', float('inf')), x['codigo']))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', required=True)
    p.add_argument('accion', choices=['init', 'hecho', 'registro', 'preferencias', 'importar', 'oportunidades', 'historial', 'restaurar'])
    p.add_argument('--rut', required=True)
    p.add_argument('--tipo', choices=sorted(PROFILE_TYPES), default='empresa')
    p.add_argument('--nombre')
    p.add_argument('--inicio-actividades', action=argparse.BooleanOptionalAction, default=None)
    p.add_argument('--archivo')
    p.add_argument('--revision', help='Identificador del historial para restaurar')
    p.add_argument('--motivo', default='actualización desde el asistente')
    p.add_argument('--autor', default='asistente')
    p.add_argument('--out')
    p.add_argument('--vista', default='todas', choices=['todas', 'activas', 'futuras', 'planificadas', 'no_iniciadas', 'abiertas', 'por_cerrar', 'cerradas', 'suspendidas', 'por_verificar'])
    inclusion = p.add_mutually_exclusive_group()
    inclusion.add_argument('--incluir-cerradas', action='store_const', const=True, dest='incluir_cerradas')
    inclusion.add_argument('--omitir-cerradas', action='store_const', const=False, dest='incluir_cerradas')
    p.add_argument('--horas', type=float)
    p.add_argument('--ahora', help='ISO-8601 con zona; útil para informes reproducibles')
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        if a.out and Path(a.out).exists():
            raise DataError('El archivo de salida ya existe; elige uno nuevo.')
        if a.accion == 'init':
            data = init(a.data_dir, a.rut, a.tipo, a.nombre, a.inicio_actividades)
            output = dict(profile_summary(data), estado='creado', siguiente='Confirmar identidad y completar progresivamente el catálogo.')
        else:
            data = load(a.data_dir, a.rut)
            if a.accion == 'historial':
                output = versions.history(path_for(a.data_dir, a.rut))
            elif a.accion == 'restaurar':
                if not a.revision:
                    raise DataError('Restaurar requiere --revision y un motivo concreto.')
                data = versions.restore(path_for(a.data_dir, a.rut), a.revision, a.motivo, a.autor)
                output = {'estado': 'restaurada como una nueva revisión', 'revision': data['_version']['id']}
            elif a.accion == 'oportunidades':
                output = select_items(data, a.vista, moment(a.ahora) if a.ahora else None, a.incluir_cerradas, a.horas)
            else:
                if not a.archivo:
                    raise DataError('Esta acción requiere --archivo JSON.')
                incoming = json.loads(Path(a.archivo).read_text())
                if a.accion == 'importar':
                    output = merge_items(data, incoming)
                elif a.accion == 'preferencias':
                    update_preferences(data, incoming)
                    output = {'estado': 'preferencias guardadas'}
                else:
                    source_record(incoming)
                    if a.accion == 'hecho':
                        if not incoming.get('campo') or 'valor' not in incoming or incoming.get('estado') not in {'documentado', 'declarado', 'inferido', 'pendiente'}:
                            raise DataError('Hecho incompleto: requiere campo, valor y estado de evidencia.')
                        data['hechos'].append(incoming)
                    else:
                        if incoming.get('tipo') not in {'historico_propio', 'compra_rubro', 'competidor', 'senal'} or not incoming.get('clave') or not isinstance(incoming.get('datos'), dict):
                            raise DataError('Registro incompleto: requiere tipo, clave y datos.')
                        data['registros'].append(incoming)
                    output = {'estado': 'evidencia agregada'}
                save(a.data_dir, data, reason=a.accion + ': ' + a.motivo, author=a.autor)
                output['revision'] = data['_version']['id']
        rendered = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if a.out:
            target = Path(a.out)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open('x') as out:
                os.chmod(target, 0o600)
                out.write(rendered)
        else:
            print(rendered, end='')
        return 0
    except (DataError, OSError, ValueError, TypeError) as error:
        # Do not dump input content (it may include company costs).
        message = str(error) if isinstance(error, (DataError, versions.VersionError)) else 'No se pudo procesar la base; revisa archivo, formato y permisos.'
        print(message, file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
