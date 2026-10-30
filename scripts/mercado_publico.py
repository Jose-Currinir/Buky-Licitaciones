#!/usr/bin/env python3
"""Cliente de lectura con caché, ritmo y pausa compartida; credencial siempre privada."""
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, quote
from urllib.request import Request
from base_empresa import display_rut, DataError, moment, utc_iso
from ticket_config import configured_ticket, ConfigError


class ApiError(Exception):
    """Error seguro de mostrar: nunca incorpora URL, cuerpo ni credencial."""

    def __init__(self, message, status=None, retry_at=None, retryable=False, kind=None):
        super().__init__(message)
        self.status = status
        self.code = status
        self.retry_at = retry_at
        self.retryable = retryable
        self.kind = kind

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('recurso', choices=['agil', 'licitaciones', 'ordenes', 'proveedor'])
    p.add_argument('--codigo')
    p.add_argument('--rut', help='Buscar proveedor por RUT con dígito verificador')
    p.add_argument('--proveedor', help='V1: código de proveedor para histórico')
    p.add_argument('--fecha', help='V1: ddmmaaaa')
    p.add_argument('--estado')
    p.add_argument('--q', help='V2: palabras clave')
    p.add_argument('--region', help='V2: códigos separados por coma')
    p.add_argument('--pagina', type=int, default=1)
    p.add_argument('--tamano', type=int, default=50)
    p.add_argument('--cambio-desde')
    p.add_argument('--cambio-hasta')
    p.add_argument('--env-file', help='Ruta explícita al .env privado (no se ejecuta como shell)')
    p.add_argument('--data-dir', help='Directorio privado para caché y pausa compartida (por defecto, el del --env-file)')
    p.add_argument('--out', required=True, help='Archivo JSON en espacio privado')
    return p

def iso_date(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if d.tzinfo is None:
            raise ValueError()
        return d
    except ValueError:
        raise ApiError('Las fechas de cambio requieren ISO-8601 con zona horaria.') from None

def make_request(a, ticket):
    if not ticket or not ticket.strip():
        raise ApiError('Configura MERCADO_PUBLICO_TICKET en el entorno privado.')
    if a.recurso == 'proveedor':
        if not a.rut or any([a.codigo, a.fecha, a.estado, a.q, a.region, a.proveedor, a.cambio_desde, a.cambio_hasta, a.pagina != 1, a.tamano != 50]):
            raise ApiError('Buscar proveedor requiere --rut sin filtros de procesos.')
        try:
            rut = display_rut(a.rut)
        except DataError as error:
            raise ApiError(str(error)) from None
        return Request('https://api.mercadopublico.cl/servicios/v1/Publico/Empresas/BuscarProveedor?' + urlencode({'rutempresaproveedor': rut, 'ticket': ticket}), headers={'Accept': 'application/json'})
    if a.rut:
        raise ApiError('--rut solo corresponde a la búsqueda de proveedor.')
    if a.proveedor and (a.recurso == 'agil' or a.codigo or not a.proveedor.isdigit()):
        raise ApiError('--proveedor requiere listado v1 y código numérico, sin --codigo.')
    if a.codigo and not re.fullmatch(r'[A-Za-z0-9-]+', a.codigo):
        raise ApiError('Código inválido: usa el código externo del proceso.')
    if a.recurso == 'agil':
        if a.fecha:
            raise ApiError('--fecha es exclusivo de v1; usa fechas de cambio para v2.')
        if a.codigo and any([a.q, a.estado, a.region, a.cambio_desde, a.cambio_hasta, a.pagina != 1, a.tamano != 50]):
            raise ApiError('El detalle por código no admite filtros de listado.')
        if not 10 <= a.tamano <= 50 or a.pagina < 1:
            raise ApiError('Paginación inválida: página >= 1 y tamaño entre 10 y 50 (límite de la API).')
        if bool(a.cambio_desde) != bool(a.cambio_hasta):
            raise ApiError('Indica ambos límites de la ventana de cambios.')
        if a.cambio_desde and iso_date(a.cambio_desde) >= iso_date(a.cambio_hasta):
            raise ApiError('El inicio de cambios debe ser anterior al fin.')
        if a.region:
            try:
                valid = all(1 <= int(v) <= 16 for v in a.region.split(','))
            except ValueError:
                valid = False
            if not valid:
                raise ApiError('Región inválida: códigos de 1 a 16 separados por coma.')
        base = 'https://api2.mercadopublico.cl/v2/compra-agil'
        if a.codigo:
            url = base + '/' + quote(a.codigo, safe='')
        else:
            params = {'numero_pagina': a.pagina, 'tamano_pagina': a.tamano}
            for key, value in [('q', a.q), ('estado', a.estado), ('region', a.region), ('cambio_desde', a.cambio_desde), ('cambio_hasta', a.cambio_hasta)]:
                if value:
                    params[key] = value
            url = base + '?' + urlencode(params)
        return Request(url, headers={'ticket': ticket, 'Accept': 'application/json'})
    if any([a.q, a.region, a.cambio_desde, a.cambio_hasta, a.pagina != 1, a.tamano != 50]):
        raise ApiError('Esos filtros son exclusivos de Compra Ágil v2.')
    if a.codigo and (a.fecha or a.estado):
        raise ApiError('Consulta v1 por código o por fecha/estado, sin mezclarlos.')
    if a.fecha:
        try:
            if not re.fullmatch(r'\d{8}', a.fecha):
                raise ValueError()
            datetime.strptime(a.fecha, '%d%m%Y')
        except ValueError:
            raise ApiError('Fecha inválida: usa ddmmaaaa.') from None
    params = {'ticket': ticket}
    for key, value in [('codigo', a.codigo), ('fecha', a.fecha), ('estado', a.estado), ('CodigoProveedor', a.proveedor)]:
        if value:
            params[key] = value
    resource = 'licitaciones' if a.recurso == 'licitaciones' else 'ordenesdecompra'
    return Request('https://api.mercadopublico.cl/servicios/v1/publico/' + resource + '.json?' + urlencode(params), headers={'Accept': 'application/json'})

def _utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataError('La hora de consulta requiere zona horaria.')
        return value.astimezone(timezone.utc)
    return moment(value)


def _iso(value):
    return utc_iso(_utc(value))


def retry_time(value, now=None):
    """Convierte Retry-After en UTC; entradas inválidas no producen una fecha."""
    if not value:
        return None
    now = _utc(now)
    try:
        if re.fullmatch(r'\d+', value.strip()):
            return _iso(now + timedelta(seconds=int(value)))
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _iso(parsed)
    except (ValueError, TypeError, OverflowError):
        return None


def quota_pause(now=None):
    # Pausa operativa, no una promesa sobre la hora oficial de reposición: se espera hasta el más
    # tardío entre las 00:01 UTC del ejemplo de la guía y las 00:01 del día siguiente en Chile.
    from zoneinfo import ZoneInfo
    now = _utc(now)
    utc_resume = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
    local = now.astimezone(ZoneInfo('America/Santiago'))
    chile_resume = (local + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
    return _iso(max(utc_resume, chile_resume.astimezone(timezone.utc)))


def fetch(request, opener=None, now_fn=None):
    """Hace una sola solicitud; los reintentos pertenecen a ApiExecutor."""
    # No redirects: prevent a ticket header/query from being forwarded elsewhere.
    if opener is None:
        from urllib.request import build_opener, HTTPRedirectHandler
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = build_opener(NoRedirect()).open
    try:
        with opener(request, timeout=30) as response:
            body = response.read(20_000_001)
            if len(body) > 20_000_000:
                raise ApiError('Respuesta demasiado grande; acota la consulta.')
        data = json.loads(body)
    except HTTPError as e:
        # Never include exception URL, body or reason (v1 URL contains the ticket).
        code = e.code
        now = now_fn() if now_fn else None
        retry_at = retry_time(e.headers.get('Retry-After'), now) if e.headers else None
        e.close()
        if code == 429:
            raise ApiError(
                'La API alcanzó el límite de solicitudes. Se detiene el lote y se respeta la pausa.',
                status=code, retry_at=retry_at or quota_pause(now), kind='cuota',
            ) from None
        transient = code in {500, 502, 503, 504}
        raise ApiError(
            f'La API respondió HTTP {code}. Revisa la guía de errores y cuota.',
            status=code, retry_at=retry_at, retryable=transient,
            kind='transitorio' if transient else 'http',
        ) from None
    except (URLError, TimeoutError, OSError, HTTPException):
        raise ApiError(
            'No fue posible consultar la API; revisa conexión y disponibilidad.',
            retryable=True, kind='red',
        ) from None
    except (ValueError, UnicodeError):
        raise ApiError('La API no devolvió JSON válido.') from None
    if not isinstance(data, dict):
        raise ApiError('Formato de respuesta inesperado.')
    if data.get('success') not in (None, 'OK') or data.get('errors') or data.get('Codigo') is not None:
        raise ApiError('La API informó un error de aplicación; revisa credencial y parámetros.')
    return data


class ApiResponse(dict):
    """JSON compatible con dict, con procedencia fuera del cuerpo de la API."""

    def __init__(self, data, consulted_at, from_cache=False):
        super().__init__(data)
        self.consulted_at = consulted_at
        self.from_cache = from_cache


def cache_key(request):
    """Clave opaca sin ticket, incluso para endpoints v1 con ticket en query."""
    parts = urlsplit(request.full_url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != 'ticket']
    clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), ''))
    material = request.get_method().upper() + '\n' + clean
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


class ApiExecutor:
    """Ejecutor compartido: caché privada, ritmo, presupuesto y enfriamiento."""

    def __init__(self, directory=None, fetch_fn=None, opener=None, min_interval=0.5,
                 cache_ttl=600, max_attempts=100, now_fn=None, sleep_fn=None):
        if isinstance(min_interval, bool) or not isinstance(min_interval, (int, float)) or not 0 <= min_interval <= 60:
            raise ValueError('El intervalo entre solicitudes debe estar entre 0 y 60 segundos.')
        if isinstance(cache_ttl, bool) or not isinstance(cache_ttl, (int, float)) or not 0 <= cache_ttl <= 86400:
            raise ValueError('El TTL de caché debe estar entre 0 y 86400 segundos.')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10000:
            raise ValueError('El presupuesto de solicitudes debe ser un entero positivo.')
        self.directory = Path(directory).expanduser().resolve() if directory is not None else None
        self.fetch_fn = fetch_fn or (lambda request: fetch(request, opener))
        self.min_interval = float(min_interval)
        self.cache_ttl = float(cache_ttl)
        self.max_attempts = max_attempts
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.sleep_fn = sleep_fn or time.sleep
        self.attempts = 0
        self.cache_hits = 0
        self.retries = 0
        self._last_started = None

    def _now(self):
        return _utc(self.now_fn())

    def _cache_path(self, request):
        if self.directory is None:
            return None
        return self.directory / 'cache' / 'api' / (cache_key(request) + '.json')

    def _read_cache(self, request, now):
        path = self._cache_path(request)
        if path is None or self.cache_ttl == 0 or not path.is_file() or path.is_symlink():
            return None
        try:
            if path.stat().st_size > 20_100_000:
                return None
            cached = json.loads(path.read_text(encoding='utf-8'))
            consulted = _utc(cached['consultado_en'])
            age = (now - consulted).total_seconds()
            if cached.get('schema_version') != 1 or not isinstance(cached.get('datos'), dict) or not 0 <= age < self.cache_ttl:
                return None
            self.cache_hits += 1
            return ApiResponse(cached['datos'], _iso(consulted), from_cache=True)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _write_cache(self, request, data, consulted):
        path = self._cache_path(request)
        if path is None or self.cache_ttl == 0:
            return
        try:
            import version_store
            content = json.dumps({
                'schema_version': 1, 'consultado_en': consulted, 'datos': data,
            }, ensure_ascii=False, allow_nan=False).encode('utf-8')
            version_store.atomic_write(path, content)
        except (OSError, ValueError):
            # La caché es una optimización; no invalida una respuesta oficial ya recibida.
            pass

    def _cooldown(self, now):
        if self.directory is None:
            return None
        import estado
        with estado.connect(self.directory) as connection:
            value = estado.get_cursor(connection, 'api:no_antes_de')
        if value and _utc(value) > now:
            return _iso(value)
        return None

    def _pause(self, retry_at):
        retry_at = _iso(retry_at)
        if self.directory is not None:
            import estado
            with estado.connect(self.directory) as connection:
                previous = estado.get_cursor(connection, 'api:no_antes_de')
                if not previous or _utc(previous) < _utc(retry_at):
                    estado.set_cursor(connection, 'api:no_antes_de', retry_at)
        return retry_at

    def _before_attempt(self):
        if self.attempts >= self.max_attempts:
            raise ApiError(
                'Se alcanzó el presupuesto local de solicitudes; acota la búsqueda antes de continuar.',
                kind='presupuesto',
            )
        now = self._now()
        if self._last_started is not None:
            remaining = self.min_interval - (now - self._last_started).total_seconds()
            if remaining > 0:
                self.sleep_fn(remaining)
        self._last_started = self._now()
        self.attempts += 1

    def fetch(self, request):
        now = self._now()
        cached = self._read_cache(request, now)
        if cached is not None:
            return cached
        paused_until = self._cooldown(now)
        if paused_until:
            raise ApiError(
                'Las consultas están en pausa por el límite de la API; no se hizo una nueva solicitud.',
                status=429, retry_at=paused_until, kind='enfriamiento',
            )
        for attempt in range(1, 4):
            self._before_attempt()
            try:
                data = self.fetch_fn(request)
                if not isinstance(data, dict):
                    raise ApiError('Formato de respuesta inesperado.')
                consulted = _iso(self._now())
                self._write_cache(request, data, consulted)
                return ApiResponse(data, consulted)
            except ApiError as error:
                if error.status == 429 or error.kind == 'cuota':
                    error.status = 429
                    error.kind = 'cuota'
                    error.retryable = False
                    error.retry_at = self._pause(error.retry_at or quota_pause(self._now()))
                    raise
                if not error.retryable or attempt >= 3:
                    raise
                if self.attempts >= self.max_attempts:
                    raise ApiError(
                        'Se alcanzó el presupuesto local de solicitudes; acota la búsqueda antes de continuar.',
                        kind='presupuesto',
                    ) from None
                self.retries += 1
                self.sleep_fn(2 ** (attempt - 1))
        raise ApiError('No fue posible completar la consulta.')

def save_json(path, data):
    # Exclusive creation prevents accidentally replacing an earlier source snapshot.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('x', encoding='utf-8') as f:
        os.chmod(path, 0o600)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

def operating_directory(a):
    """Caché y pausa por cuota se comparten con buky.py: viven en el directorio de datos, no junto a --out."""
    if a.data_dir:
        return Path(a.data_dir).expanduser().resolve()
    if a.env_file:
        return Path(a.env_file).expanduser().resolve().parent
    return Path(os.environ.get('BUKY_DATA_DIR', '~/.buky/licitaciones')).expanduser().resolve()


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        request = make_request(a, configured_ticket(a.env_file))
        path = Path(a.out)
        if path.exists():
            raise ApiError('El archivo destino ya existe; usa otro nombre para conservar la fuente.')
        data = ApiExecutor(directory=operating_directory(a)).fetch(request)
        save_json(path, data)
    except (ApiError, ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    except OSError:
        print('No se pudo guardar el archivo; revisa destino y permisos.', file=sys.stderr)
        return 1
    print('Respuesta guardada. Revisa paginación y cobertura antes de analizar.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
