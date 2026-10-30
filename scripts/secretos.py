"""Secretos en Keychain, Secret Service o DPAPI. Nunca usa texto plano de respaldo."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

import version_store
from i18n import tr

SERVICE = 'cl.butake.licitaciones'
# `security -i` lee órdenes de hasta ~4 KB por línea y el valor viaja en hexadecimal (el doble):
# los secretos más largos se guardan en partes y la entrada principal solo guarda cuántas son.
KEYCHAIN_PART_BYTES = 1800
KEYCHAIN_MAX_LINE = 4000
PARTS_MARK = 'BUKY-PARTES:'


class SecretError(ValueError):
    pass


def account_name(provider, email):
    if (provider not in {'gmail', 'microsoft'} or not isinstance(email, str) or not 3 <= len(email) <= 320
            or any(c.isspace() for c in email) or email.count('@') != 1 or email.startswith('@') or email.endswith('@')):
        raise SecretError(tr('mail.invalid_account'))
    return provider + ':' + email.lower()


class SecretStore:
    def __init__(self, directory, system=None, runner=None):
        self.directory = Path(directory).expanduser().resolve()
        self.system = system or platform.system()
        self.runner = runner or subprocess.run
        self.backend = {'Darwin': 'keychain', 'Linux': 'secret_service', 'Windows': 'dpapi'}.get(self.system)
        if not self.backend:
            raise SecretError(tr('secrets.unsupported'))

    def _run(self, command, value=None):
        try:
            result = self.runner(command, input=value, capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            raise SecretError(tr('secrets.backend_failed')) from None
        if result.returncode:
            raise SecretError(tr('secrets.backend_failed'))
        return result.stdout

    def _command(self, action, account):
        if self.backend == 'keychain':
            executable = shutil.which('security')
            if not executable:
                raise SecretError(tr('secrets.unavailable'))
            if action == 'save':
                # Modo interactivo: la orden llega por stdin, así el secreto no aparece en los argumentos
                # del proceso ni depende de una terminal (-w sin valor pediría la clave por /dev/tty).
                return [executable, '-i']
            if action == 'load':
                return [executable, 'find-generic-password', '-s', SERVICE, '-a', account, '-w']
            return [executable, 'delete-generic-password', '-s', SERVICE, '-a', account]
        executable = shutil.which('secret-tool')
        if not executable:
            raise SecretError(tr('secrets.unavailable'))
        attributes = ['service', SERVICE, 'account', account]
        if action == 'save':
            return [executable, 'store', '--label', 'Buky Licitaciones', *attributes]
        if action == 'load':
            return [executable, 'lookup', *attributes]
        return [executable, 'clear', *attributes]

    def save(self, account, value):
        if not isinstance(value, str) or not value:
            raise SecretError(tr('secrets.empty'))
        if self.backend == 'keychain':
            self._keychain_save(account, value)
            return
        if self.backend != 'dpapi':
            self._run(self._command('save', account), value)
            return
        from ctypes import byref
        blob, keepalive = _dpapi_blob(value.encode('utf-8'))
        encrypted, output = _dpapi_blob(b'')
        import ctypes
        if not ctypes.windll.crypt32.CryptProtectData(byref(blob), 'Buky Licitaciones', None, None, None, 1, byref(encrypted)):
            raise SecretError(tr('secrets.backend_failed'))
        try:
            content = ctypes.string_at(encrypted.pbData, encrypted.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(encrypted.pbData)
        path = self._path(account)
        version_store.atomic_write(path, content)

    def _keychain_get(self, account):
        value = self._run(self._command('load', account))
        value = value[:-1] if value.endswith('\n') else value
        if value and re.fullmatch(r'(?:[0-9a-f]{2})+', value):
            # Keychain muestra en hexadecimal los valores que no son texto imprimible.
            try:
                return bytes.fromhex(value).decode('utf-8')
            except UnicodeDecodeError:
                return value
        return value

    def _keychain_put(self, account, value):
        line = f'add-generic-password -U -s {SERVICE} -a {account} -X {value.encode("utf-8").hex()}\n'
        if len(line.encode('ascii')) > KEYCHAIN_MAX_LINE:
            raise SecretError(tr('secrets.backend_failed'))
        self._run(self._command('save', account), line)
        # `security -i` puede terminar bien aunque la orden falle: se confirma leyendo el valor.
        if self._keychain_get(account) != value:
            raise SecretError(tr('secrets.backend_failed'))

    def _keychain_save(self, account, value):
        parts, current = [], ''
        for char in value:
            if len((current + char).encode('utf-8')) > KEYCHAIN_PART_BYTES:
                parts.append(current)
                current = ''
            current += char
        parts.append(current)
        try:
            previous = self._keychain_get(account)
        except SecretError:
            previous = ''
        if len(parts) == 1 and not value.startswith(PARTS_MARK):
            self._keychain_put(account, value)
        else:
            # Las partes se escriben antes que la entrada principal: si algo falla, el valor anterior sigue intacto.
            for index, part in enumerate(parts):
                self._keychain_put(f'{account}.parte{index}', part)
            self._keychain_put(account, PARTS_MARK + str(len(parts)))
        old_count = int(previous[len(PARTS_MARK):]) if previous.startswith(PARTS_MARK) and previous[len(PARTS_MARK):].isdigit() else 0
        for index in range(len(parts) if len(parts) > 1 else 0, old_count):
            try:
                self._run(self._command('delete', f'{account}.parte{index}'))
            except SecretError:
                pass

    def load(self, account):
        if self.backend == 'keychain':
            value = self._keychain_get(account)
            if value.startswith(PARTS_MARK) and value[len(PARTS_MARK):].isdigit():
                return ''.join(self._keychain_get(f'{account}.parte{index}') for index in range(int(value[len(PARTS_MARK):])))
            return value
        if self.backend != 'dpapi':
            value = self._run(self._command('load', account))
            return value[:-1] if value.endswith('\n') else value
        path = self._path(account)
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            raise SecretError(tr('secrets.not_found')) from None
        from ctypes import byref
        import ctypes
        blob, keepalive = _dpapi_blob(content)
        plain, output = _dpapi_blob(b'')
        if not ctypes.windll.crypt32.CryptUnprotectData(byref(blob), None, None, None, None, 1, byref(plain)):
            raise SecretError(tr('secrets.backend_failed'))
        try:
            content = ctypes.string_at(plain.pbData, plain.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(plain.pbData)
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            raise SecretError(tr('secrets.backend_failed')) from None

    def delete(self, account):
        if self.backend == 'keychain':
            try:
                value = self._keychain_get(account)
            except SecretError:
                value = ''
            if value.startswith(PARTS_MARK) and value[len(PARTS_MARK):].isdigit():
                for index in range(int(value[len(PARTS_MARK):])):
                    try:
                        self._run(self._command('delete', f'{account}.parte{index}'))
                    except SecretError:
                        pass
        if self.backend != 'dpapi':
            self._run(self._command('delete', account))
            return
        self._path(account).unlink(missing_ok=True)

    def _path(self, account):
        digest = hashlib.sha256(account.encode('utf-8')).hexdigest()
        return self.directory / 'secretos' / (digest + '.dpapi')

    def status(self):
        return {'backend': self.backend, 'disponible': self.backend == 'dpapi' or bool(shutil.which('security' if self.backend == 'keychain' else 'secret-tool'))}


def save_json(store, account, data):
    store.save(account, json.dumps(data, ensure_ascii=True, separators=(',', ':'), allow_nan=False))


def load_json(store, account):
    try:
        data = json.loads(store.load(account))
    except (json.JSONDecodeError, TypeError):
        raise SecretError(tr('secrets.backend_failed')) from None
    if not isinstance(data, dict):
        raise SecretError(tr('secrets.backend_failed'))
    return data


def _dpapi_blob(content):
    """Construye DATA_BLOB manteniendo viva la memoria en la tupla devuelta."""
    import ctypes
    from ctypes import wintypes
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    buffer = ctypes.create_string_buffer(content)
    blob = DATA_BLOB(len(content), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, (buffer, DATA_BLOB)
