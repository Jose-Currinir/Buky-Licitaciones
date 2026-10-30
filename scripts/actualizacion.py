"""Compara la versión instalada con la publicada; solo descarga el archivo VERSION público."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib import error as urlerror
from urllib import request

import base_empresa as base
import version_store
from i18n import tr


VERSION_URL = 'https://raw.githubusercontent.com/Jose-Currinir/Buky-Licitaciones/main/VERSION'
CHECK_EVERY = timedelta(hours=24)
VERSION_PATTERN = re.compile(r'\d+\.\d+\.\d+')


def skill_dir():
    return Path(__file__).resolve().parents[1]


def installed_version(directory=None):
    return ((directory or skill_dir()) / 'VERSION').read_text(encoding='utf-8').strip()


def _tuple(version):
    return tuple(int(part) for part in version.split('.'))


def update_command(directory=None):
    """El comando depende de cómo se instaló: instalador propio, clon de git o `npx skills`."""
    directory = directory or skill_dir()
    if (directory / 'INSTALLATION.json').is_file():
        return 'npx --no-install buky-licitaciones update'
    if (directory / '.git').exists():
        return f'git -C "{directory}" pull --ff-only'
    return 'npx skills update licitaciones-chile'


def fetch_latest(url=None, opener=None):
    opener = opener or request.urlopen
    try:
        with opener(request.Request(url or VERSION_URL, headers={'User-Agent': 'buky-licitaciones'}), timeout=5) as response:
            text = response.read(64).decode('utf-8', 'replace').strip()
    except (urlerror.URLError, TimeoutError, OSError, ValueError):
        return None
    return text if VERSION_PATTERN.fullmatch(text) else None


def check(data_dir, now=None, force=False, opener=None, directory=None):
    """Estado de la versión. Usa una caché de 24 h para no consultar la red en cada conversación."""
    now = now or datetime.now(timezone.utc)
    installed = installed_version(directory)
    result = {'instalada': installed, 'disponible': None, 'comprobado_en': None, 'desde_cache': False,
              'comando_actualizar': update_command(directory)}
    if os.environ.get('BUKY_SIN_ACTUALIZACIONES'):
        return dict(result, estado='desactivada')
    cache = Path(data_dir).expanduser().resolve() / 'cache' / 'actualizacion.json'
    cached = {}
    try:
        cached = json.loads(cache.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cached = {}
    fresh = (not force and isinstance(cached, dict) and VERSION_PATTERN.fullmatch(str(cached.get('disponible', '')))
             and cached.get('comprobado_en') and now - base.moment(cached['comprobado_en']) < CHECK_EVERY)
    if fresh:
        result.update(disponible=cached['disponible'], comprobado_en=cached['comprobado_en'], desde_cache=True)
    else:
        latest = fetch_latest(os.environ.get('BUKY_URL_VERSION'), opener)
        if latest is None:
            return dict(result, estado='no_verificada', mensaje=tr('update.unverified'))
        result.update(disponible=latest, comprobado_en=base.utc_iso(now))
        version_store.private_mkdir(cache.parent)
        version_store.atomic_write(cache, json.dumps({'disponible': latest, 'comprobado_en': result['comprobado_en']}).encode('utf-8'))
    if VERSION_PATTERN.fullmatch(installed) and _tuple(result['disponible']) > _tuple(installed):
        return dict(result, estado='actualizacion_disponible',
                    mensaje=tr('update.available', instalada=installed, disponible=result['disponible'], comando=result['comando_actualizar']))
    return dict(result, estado='al_dia', mensaje=tr('update.current', instalada=installed))
