"""Coordinador local opcional: una instancia por directorio de datos."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import platform
import plistlib
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid

import base_empresa as base
import estado
import recordatorios
import version_store
from i18n import tr


# Errores de un perfil o del correo que se registran sin detener el ciclo del servicio.
RECOVERABLE = (ValueError, OSError, sqlite3.Error, HTTPException)


DEFAULT_CONFIG = {
    'schema_version': 1,
    'intervalo_segundos': 300,
    'sincronizar_oportunidades': False,
    'intervalo_sincronizacion_minutos': 60,
    'horas_recordatorios': [72, 24, 2],
    'canal_notificaciones': 'automatico',
    'correo_recordatorios': False,
}
OPTIONAL_CONFIG = {'canal_notificaciones', 'correo_recordatorios'}


class ServiceError(ValueError):
    pass


def config_path(directory):
    return Path(directory).expanduser().resolve() / 'servicio.json'


def validate_config(config):
    required = set(DEFAULT_CONFIG) - OPTIONAL_CONFIG
    if (not isinstance(config, dict) or not required.issubset(config)
            or set(config) - set(DEFAULT_CONFIG) or config.get('schema_version') != 1):
        raise ServiceError(tr('service.config_version'))
    config = {**DEFAULT_CONFIG, **config}
    if type(config['intervalo_segundos']) is not int or not 30 <= config['intervalo_segundos'] <= 86400:
        raise ServiceError(tr('service.config_interval'))
    if type(config['sincronizar_oportunidades']) is not bool:
        raise ServiceError(tr('service.config_sync'))
    if type(config['intervalo_sincronizacion_minutos']) is not int or not 5 <= config['intervalo_sincronizacion_minutos'] <= 10080:
        raise ServiceError(tr('service.config_sync_interval'))
    if config['canal_notificaciones'] not in recordatorios.CHANNELS:
        raise ServiceError(tr('service.config_channel'))
    if type(config['correo_recordatorios']) is not bool:
        raise ServiceError(tr('service.config_mail'))
    hours = config['horas_recordatorios']
    if not isinstance(hours, list) or not hours or len(hours) > 20:
        raise ServiceError(tr('service.config_thresholds'))
    try:
        for value in hours:
            base.positive_hours(value)
    except base.DataError:
        raise ServiceError(tr('reminder.threshold_positive')) from None
    return config


def load_config(directory):
    path = config_path(directory)
    config = DEFAULT_CONFIG.copy() if not path.exists() else json.loads(path.read_text(encoding='utf-8'))
    return validate_config(config)


def save_config(directory, updates):
    allowed = set(DEFAULT_CONFIG) - {'schema_version'}
    if not isinstance(updates, dict) or set(updates) - allowed:
        raise ServiceError(tr('service.config_unknown'))
    config = validate_config({**load_config(directory), **updates})
    path = config_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    version_store.atomic_write(path, (json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
    return config


def companies(directory):
    root = Path(directory).expanduser().resolve()
    if not root.exists():
        return []
    result = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith('.') or not (child / 'base.json').is_file():
            continue
        try:
            result.append(base.normalize_rut(child.name))
        except base.DataError:
            continue
    return sorted(result)


def process_alive(pid):
    return version_store.pid_alive(pid) is True


@contextmanager
def instance_lock(directory):
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / 'servicio.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            metadata = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise ServiceError(tr('service.lock_invalid', archivo=path)) from None
        if process_alive(metadata.get('pid')):
            raise ServiceError(tr('service.lock_active'))
        # El proceso anterior terminó sin limpiar: se retira el bloqueo y se reintenta una vez.
        path.unlink(missing_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ServiceError(tr('service.lock_active')) from None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump({'pid': os.getpid(), 'instancia': uuid.uuid4().hex, 'creado_utc': base.utc_now()}, out)
        yield
    finally:
        path.unlink(missing_ok=True)


def should_sync(connection, rut, now):
    value = estado.get_cursor(connection, 'siguiente_sync:' + rut)
    return value is None or base.moment(value) <= now


def run_once(directory, synchronize=None, notifier=None, now=None, use_lock=True):
    directory = Path(directory).expanduser().resolve()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ServiceError(tr('service.timezone_required'))
    config = load_config(directory)
    synchronize = config['sincronizar_oportunidades'] if synchronize is None else synchronize
    channel = config['canal_notificaciones']
    report = {
        'empresas': [], 'recordatorios': None, 'correo': None, 'errores': [],
        'canal_notificaciones': recordatorios.resolve_channel(channel),
    }

    def work():
        for rut in companies(directory):
            company_report = {'rut': rut, 'sincronizacion': None, 'recordatorios': None}
            try:
                if synchronize:
                    with estado.connect(directory) as connection:
                        due = should_sync(connection, rut, now)
                    if due:
                        import butake
                        queries = butake.catalog_queries(directory, rut)
                        if queries:
                            result = butake.sync_company(directory, rut, queries=queries, request_budget=25)
                            company_report['sincronizacion'] = result
                            delay = config['intervalo_sincronizacion_minutos'] if not result['errores'] else 15
                            next_sync = base.utc_iso(now + timedelta(minutes=delay))
                            if result.get('detenida_por_cuota') and result.get('reintentar_en'):
                                next_sync = result['reintentar_en']
                            with estado.connect(directory) as connection:
                                estado.set_cursor(connection, 'siguiente_sync:' + rut, next_sync)
                company_report['recordatorios'] = recordatorios.sync_company(directory, rut, config['horas_recordatorios'], now)
            except RECOVERABLE as error:
                company_report['error'] = str(error)[:500]
                report['errores'].append({'rut': rut, 'error': company_report['error']})
            report['empresas'].append(company_report)
        try:
            import correo
            report['correo'] = correo.sync_configured(directory)
        except ImportError:
            report['correo'] = {'estado': 'no_disponible'}
        except RECOVERABLE as error:
            report['errores'].append({'correo': str(error)[:500]})
        try:
            report['recordatorios'] = recordatorios.dispatch(directory, now, notifier, channel)
        except RECOVERABLE as error:
            report['recordatorios'] = {'enviados': [], 'fallidos': []}
            report['errores'].append({'recordatorios': str(error)[:500]})
        if config['correo_recordatorios']:
            # El servicio solo deja borradores; el asistente los envía con el complemento de correo.
            import equipo
            try:
                drafts = equipo.enqueue_reminders(directory, report['recordatorios']['enviados'])
                report['correo_salida'] = [item['id'] for item in drafts]
            except RECOVERABLE as error:
                report['errores'].append({'correo_salida': str(error)[:500]})
        append_log(directory, {'evento': 'ejecucion', 'errores': len(report['errores']), 'avisos_enviados': len(report['recordatorios']['enviados'])})

    if use_lock:
        with instance_lock(directory):
            work()
    else:
        work()
    return report


def append_log(directory, event):
    path = Path(directory).expanduser().resolve() / 'servicio.log'
    record = {'fecha_utc': base.utc_now(), **event}
    with path.open('a', encoding='utf-8') as out:
        os.chmod(path, 0o600)
        out.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')


def run_forever(directory, sleep_fn=time.sleep, iterations=None, notifier=None):
    if iterations is not None and (type(iterations) is not int or iterations < 1):
        raise ServiceError(tr('service.iterations_positive'))
    config = load_config(directory)
    completed = 0
    report = None
    with instance_lock(directory):
        while iterations is None or completed < iterations:
            report = run_once(directory, notifier=notifier, use_lock=False)
            completed += 1
            if iterations is not None and completed >= iterations:
                return report
            sleep_fn(config['intervalo_segundos'])
    return report


def service_command(directory):
    script = Path(__file__).resolve().with_name('butake.py')
    return [sys.executable, str(script), '--data-dir', str(Path(directory).expanduser().resolve()), 'servicio', 'iniciar']


def definition(directory, system=None):
    directory = Path(directory).expanduser().resolve()
    folder = directory / 'servicio'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = service_command(directory)
    system = system or platform.system()
    if system == 'Darwin':
        path = folder / 'cl.butake.licitaciones.plist'
        payload = {
            'Label': 'cl.butake.licitaciones', 'ProgramArguments': command, 'RunAtLoad': True, 'KeepAlive': True,
            'WorkingDirectory': str(directory), 'StandardOutPath': str(directory / 'servicio-salida.log'), 'StandardErrorPath': str(directory / 'servicio-error.log'),
        }
        content = plistlib.dumps(payload)
    elif system == 'Linux':
        path = folder / 'butake-licitaciones.service'
        content = ('[Unit]\nDescription=Butake Licitaciones\n\n[Service]\nType=simple\n'
                   f'WorkingDirectory={directory}\nExecStart={shlex.join(command)}\nRestart=on-failure\nRestartSec=30\n'
                   'StandardOutput=journal\nStandardError=journal\nSyslogIdentifier=butake-licitaciones\n'
                   '\n[Install]\nWantedBy=default.target\n').encode('utf-8')
    elif system == 'Windows':
        path = folder / 'butake-licitaciones-task.json'
        content = (json.dumps({'nombre': 'ButakeLicitaciones', 'comando': command, 'inicio': 'ONLOGON'}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    else:
        raise ServiceError(tr('service.definition_unsupported'))
    version_store.atomic_write(path, content)
    return {'sistema': system, 'archivo': str(path), 'comando': command}


def run_checked(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ServiceError(tr('service.system_change_failed'))


LAUNCH_LABEL = 'cl.butake.licitaciones'


def launch_agents_dir():
    return Path.home() / 'Library' / 'LaunchAgents'


def enable(directory, system=None, runner=None, agents_dir=None):
    runner = runner or run_checked
    info = definition(directory, system=system)
    system = info['sistema']
    if system == 'Darwin':
        # launchd solo vuelve a cargar al iniciar sesión los agentes de ~/Library/LaunchAgents.
        target = Path(agents_dir or launch_agents_dir()) / (LAUNCH_LABEL + '.plist')
        version_store.atomic_write(target, Path(info['archivo']).read_bytes())
        os.chmod(target, 0o644)
        try:
            runner(['launchctl', 'bootout', f'gui/{os.getuid()}/{LAUNCH_LABEL}'])
        except ServiceError:
            pass  # No estaba cargado: es el caso normal en la primera habilitación.
        for attempt in range(3):
            try:
                runner(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(target)])
                break
            except ServiceError:
                # Tras un bootout, launchd puede tardar un momento en liberar el servicio.
                if attempt == 2:
                    raise
                time.sleep(1)
        info['archivo'] = str(target)
    elif system == 'Linux':
        runner(['systemctl', '--user', 'daemon-reload'])
        runner(['systemctl', '--user', 'enable', '--now', info['archivo']])
    elif system == 'Windows':
        command = subprocess.list2cmdline(info['comando'])
        runner(['schtasks', '/Create', '/TN', 'ButakeLicitaciones', '/SC', 'ONLOGON', '/RL', 'LIMITED', '/F', '/TR', command])
    else:
        raise ServiceError(tr('service.manager_unsupported'))
    return {'estado': 'habilitado', **info}


def disable(directory, system=None, runner=None, agents_dir=None):
    runner = runner or run_checked
    system = system or platform.system()
    info = {'sistema': system}
    if system == 'Darwin':
        try:
            runner(['launchctl', 'bootout', f'gui/{os.getuid()}/{LAUNCH_LABEL}'])
        except ServiceError:
            pass  # Ya estaba detenido; igual se retira del inicio de sesión.
        (Path(agents_dir or launch_agents_dir()) / (LAUNCH_LABEL + '.plist')).unlink(missing_ok=True)
    elif system == 'Linux':
        runner(['systemctl', '--user', 'disable', '--now', 'butake-licitaciones.service'])
    elif system == 'Windows':
        runner(['schtasks', '/Delete', '/TN', 'ButakeLicitaciones', '/F'])
    else:
        raise ServiceError(tr('service.manager_unsupported'))
    return {'estado': 'deshabilitado', **info}


def status(directory):
    path = Path(directory).expanduser().resolve() / 'servicio.lock'
    if not path.exists():
        return {'ejecutando': False}
    metadata = json.loads(path.read_text(encoding='utf-8'))
    return {'ejecutando': process_alive(metadata.get('pid')), 'pid': metadata.get('pid'), 'creado_utc': metadata.get('creado_utc')}
