"""Historial local de snapshots encadenados. No es firma digital ni almacén de secretos."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

LOCK_WAIT_SECONDS = 3.0
# Una escritura dura segundos: un bloqueo de más de 10 minutos casi seguro quedó huérfano.
STALE_LOCK_SECONDS = 600

class VersionError(ValueError):
    pass


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def body(data):
    return {k: v for k, v in data.items() if k != '_version'}


def digest(data):
    return hashlib.sha256(canonical(body(data))).hexdigest()


def revision_digest(data):
    metadata = {k: v for k, v in data.get('_version', {}).items() if k not in {'id', 'sha256'}}
    return hashlib.sha256(canonical({'datos': body(data), 'metadatos': metadata})).hexdigest()


def private_mkdir(directory):
    """Crea cada nivel faltante con 0700; `mkdir(parents=True)` solo aplica el modo al último."""
    directory = Path(directory)
    for level in reversed([directory, *directory.parents]):
        if not level.exists():
            level.mkdir(mode=0o700)


def atomic_write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise VersionError('No se escribe sobre enlaces simbólicos.')
    private_mkdir(path.parent)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temp = Path(out.name)
            os.chmod(temp, 0o600)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def lock_owner_alive(lock):
    """True si el proceso dueño sigue vivo, False si terminó, None si no se puede saber."""
    try:
        pid = json.loads(Path(lock).read_text(encoding='utf-8')).get('pid')
    except (OSError, ValueError, AttributeError):
        return None
    return pid_alive(pid)


def pid_alive(pid):
    """True si el proceso existe, False si terminó, None si el PID no es válido o no se puede saber."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def lock_age_seconds(lock):
    try:
        created = datetime.fromisoformat(json.loads(Path(lock).read_text(encoding='utf-8'))['creado_utc'])
        return (datetime.now(timezone.utc) - created).total_seconds()
    except (OSError, ValueError, KeyError, TypeError):
        return 0


@contextmanager
def write_lock(path, wait=None):
    """Bloqueo exclusivo por perfil: espera brevemente y retira bloqueos de procesos terminados."""
    path = Path(path)
    private_mkdir(path.parent)
    lock = path.parent / '.write.lock'
    deadline = time.monotonic() + (LOCK_WAIT_SECONDS if wait is None else wait)
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            if lock_owner_alive(lock) is False:
                # El proceso que lo creó ya no existe: el bloqueo quedó de una caída.
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                if lock_age_seconds(lock) > STALE_LOCK_SECONDS:
                    # Un PID reutilizado tras reiniciar puede parecer vivo: se pide comprobarlo a mano.
                    raise VersionError(f'Hay un bloqueo de escritura antiguo en {lock}. Si no hay otra operación de Butake en curso, bórralo y reintenta.') from None
                raise VersionError('La empresa tiene otra escritura en curso. No se guardaron cambios; reintenta en unos segundos.') from None
            time.sleep(0.1)
    try:
        os.write(fd, json.dumps({'pid': os.getpid(), 'creado_utc': datetime.now(timezone.utc).isoformat()}).encode('utf-8'))
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def revision_path(path, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'r\d{6,}-[a-f0-9]{64}', identifier):
        raise VersionError('Identificador de revisión inválido.')
    return Path(path).parent / 'historial/base' / (identifier + '.json')


def read_current(path):
    path = Path(path)
    if path.is_symlink():
        raise VersionError('La base no puede ser un enlace simbólico.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise VersionError('Formato de base inválido.')
    meta = data.get('_version')
    if not meta and any((path.parent / 'historial/base').glob('r*.json')):
        raise VersionError('Faltan los metadatos de versión de una base con historial. Revisa la recuperación.')
    if meta:
        if revision_digest(data) != meta.get('sha256'):
            raise VersionError('La base fue modificada fuera del historial; revisa antes de continuar.')
        snapshot = read_revision(path, meta.get('id'))
        if canonical(snapshot) != canonical(data):
            raise VersionError('La base no coincide con su snapshot de versión.')
    return data


def read_revision(path, identifier):
    target = revision_path(path, identifier)
    if target.is_symlink():
        raise VersionError('Snapshot inválido: enlace simbólico.')
    data = json.loads(target.read_text(encoding='utf-8'))
    meta = data.get('_version', {})
    if meta.get('id') != identifier or revision_digest(data) != meta.get('sha256'):
        raise VersionError('La integridad del snapshot no coincide.')
    expected = f"r{meta['numero']:06d}-{meta['sha256']}"
    if expected != identifier:
        raise VersionError('Número de snapshot incoherente.')
    return data


def snapshot(path, data, parent, reason, author):
    result = body(data)
    number = parent['_version']['numero'] + 1 if parent else 1
    result['_version'] = {'numero': number, 'anterior': parent['_version']['id'] if parent else None, 'fecha_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'autor': author, 'motivo': reason}
    sha = revision_digest(result)
    identifier = f'r{number:06d}-{sha}'
    result['_version'].update({'id': identifier, 'sha256': sha})
    target = revision_path(path, identifier)
    private_mkdir(target.parent)
    if target.exists():
        # A failed previous commit can leave an unreferenced snapshot. Never overwrite it.
        raise VersionError('Ya existe un snapshot con ese identificador. Revisa la recuperación antes de reintentar.')
    with target.open('xb') as out:
        os.chmod(target, 0o600)
        out.write(canonical(result) + b'\n')
        out.flush()
        os.fsync(out.fileno())
    return result


def commit(path, data, create=False, reason='actualizar base', author='asistente'):
    path = Path(path)
    if not reason.strip() or not author.strip():
        raise VersionError('Cada versión requiere autor y motivo.')
    with write_lock(path):
        if create and path.exists():
            raise VersionError('La empresa ya existe; retoma su base sin reinicializar.')
        current = read_current(path) if path.exists() else None
        if current and current.get('_version', {}).get('id') != data.get('_version', {}).get('id'):
            raise VersionError('La base cambió desde su lectura; vuelve a cargarla antes de guardar.')
        if current and current.get('_version') and digest(current) == digest(data):
            data['_version'] = current['_version']
            return data
        parent = current
        if current and not current.get('_version'):
            parent = snapshot(path, current, None, 'incorporar base anterior al historial', author)
        saved = snapshot(path, data, parent, reason, author)
        atomic_write(path, canonical(saved) + b'\n')
        data['_version'] = saved['_version']
        return data


def history(path):
    current = read_current(path)
    result = []
    seen = set()
    identifier = current.get('_version', {}).get('id')
    expected_number = current.get('_version', {}).get('numero')
    while identifier:
        if identifier in seen:
            raise VersionError('Ciclo en el historial de versiones.')
        seen.add(identifier)
        item = read_revision(path, identifier)
        meta = item['_version']
        if meta['numero'] != expected_number:
            raise VersionError('Falta una revisión en la cadena de versiones.')
        result.append(meta.copy())
        expected_number -= 1
        identifier = meta['anterior']
    if result and expected_number != 0:
        raise VersionError('Historial incompleto.')
    return result


def restore(path, identifier, reason, author):
    current = read_current(path)
    if identifier not in {v['id'] for v in history(path)}:
        raise VersionError('La revisión no pertenece al historial de esta empresa.')
    previous = read_revision(path, identifier)
    if previous.get('rut') != current.get('rut'):
        raise VersionError('La revisión pertenece a otra empresa.')
    previous['_version'] = current['_version']
    return commit(path, previous, reason='restaurar ' + identifier + ': ' + reason, author=author)
