#!/usr/bin/env python3
"""Configura el ticket en un .env privado mediante diálogo nativo o entrada oculta."""
import argparse
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import webbrowser

TICKET_KEY = 'MERCADO_PUBLICO_TICKET'
TICKET_URL = 'https://www.chilecompra.cl/api/'
KEY_LINE = re.compile(r'^\s*(?:export\s+)?MERCADO_PUBLICO_TICKET\s*=')

class ConfigError(ValueError):
    pass


def validate_ticket(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{8,512}', value.strip()):
        raise ConfigError('Formato de ticket inválido. Pega solo el código recibido por correo.')
    return value.strip()


def read_ticket(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ConfigError('El .env no puede ser un enlace simbólico.')
    try:
        if path.stat().st_size > 65_536:
            raise ConfigError('El archivo .env es demasiado grande; revisa la configuración.')
        text = path.read_text(encoding='utf-8')
    except OSError:
        raise ConfigError('No se pudo leer el .env indicado.') from None
    values = []
    for line in text.splitlines():
        if KEY_LINE.match(line):
            value = line.split('=', 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values.append(validate_ticket(value))
    if len(values) != 1:
        raise ConfigError('El .env debe contener exactamente un MERCADO_PUBLICO_TICKET válido.')
    return values[0]


def configured_ticket(env_file=None):
    if os.environ.get(TICKET_KEY, '').strip():
        return validate_ticket(os.environ[TICKET_KEY])
    if env_file:
        return read_ticket(env_file)
    raise ConfigError('Configura el ticket con ticket_config.py y usa --env-file, o define MERCADO_PUBLICO_TICKET.')


def save_ticket(path, ticket):
    ticket = validate_ticket(ticket)
    path = Path(path).expanduser()
    if path.name != '.env' or path.is_symlink():
        raise ConfigError('El destino debe ser un archivo .env privado, sin enlaces simbólicos.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Refuse accidentally tracked secret files. An ignored .env in a checkout is allowed.
    try:
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', '--', path.name], cwd=path.parent, capture_output=True, timeout=5)
        if tracked.returncode == 0:
            raise ConfigError('Ese .env está rastreado por Git; elige un directorio privado fuera del repositorio.')
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if path.exists() and path.stat().st_size > 65_536:
        raise ConfigError('El archivo .env es demasiado grande; revisa la configuración.')
    previous = path.read_text(encoding='utf-8') if path.exists() else ''
    lines = [line for line in previous.splitlines() if not KEY_LINE.match(line)]
    lines.append(TICKET_KEY + '=' + ticket)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, encoding='utf-8', delete=False) as out:
            temporary = Path(out.name)
            os.chmod(temporary, 0o600)
            out.write('\n'.join(lines) + '\n')
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return path


def _terminal_ticket():
    if not sys.stdin.isatty():
        raise ConfigError('La entrada oculta requiere una terminal interactiva; ejecuta el comando tú mismo en una sesión de terminal o SSH.')
    return getpass.getpass('Pega tu ticket (entrada oculta): ')


def prompt_ticket(terminal=False):
    linux_headless = sys.platform.startswith('linux') and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
    if terminal or linux_headless:
        return _terminal_ticket()
    if sys.platform == 'darwin':
        code = '''text returned of (display dialog "Pega tu ticket de Mercado Público. Se guardará en el .env privado indicado en la terminal." with title "Butake Licitaciones" default answer "" with hidden answer buttons {"Cancelar", "Guardar"} default button "Guardar" cancel button "Cancelar")'''
        result = subprocess.run(['osascript', '-e', code], capture_output=True, text=True)
        if result.returncode:
            raise ConfigError('Configuración cancelada o diálogo no disponible. Puedes usar --terminal.')
        return result.stdout.rstrip('\r\n')
    try:
        import tkinter
        from tkinter import simpledialog
        root = tkinter.Tk()
        root.withdraw()
        try:
            value = simpledialog.askstring('Butake Licitaciones', 'Pega tu ticket de Mercado Público:', show='*', parent=root)
        finally:
            root.destroy()
        if value is None:
            raise ConfigError('Configuración cancelada; no se guardó ningún cambio.')
        return value
    except (ImportError, RuntimeError) as error:
        raise ConfigError('No hay diálogo gráfico disponible. Ejecuta el comando con --terminal.') from None
    except Exception as error:
        if isinstance(error, ConfigError):
            raise
        raise ConfigError('No se pudo abrir el diálogo. Ejecuta el comando con --terminal.') from None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', required=True, help='Carpeta privada; el ticket se guarda en su .env')
    p.add_argument('--terminal', action='store_true', help='Entrada oculta en terminal como alternativa al diálogo')
    p.add_argument('--abrir-solicitud', action='store_true', help='Abre la página oficial para solicitar el ticket')
    p.add_argument('--estado', action='store_true', help='Comprueba configuración local sin mostrar el ticket ni consultar la API')
    a = p.parse_args(argv)
    path = Path(a.data_dir).expanduser().resolve() / '.env'
    print('Solicita tu ticket en ' + TICKET_URL + ' → Pide tu ticket → Clave Única → formulario. Llega por correo.')
    try:
        if a.estado:
            configured_ticket(path)
            print('Ticket configurado localmente. Aún no se ha validado su acceso a la API.')
            return 0
        if a.abrir_solicitud:
            webbrowser.open(TICKET_URL)
        print('Destino privado: ' + str(path))
        save_ticket(path, prompt_ticket(a.terminal))
        print('Ticket guardado. El cliente puede usar --env-file con ese archivo. No se consultó la API.')
        return 0
    except (ConfigError, OSError, KeyboardInterrupt) as error:
        print(str(error) if isinstance(error, ConfigError) else 'No se completó la configuración. Revisa permisos o usa --terminal.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
