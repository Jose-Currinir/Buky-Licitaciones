"""Giros y tamaño de empresa desde las nóminas abiertas del SII (personas jurídicas).

Fuente: https://www.sii.cl/sobre_el_sii/nominapersonasjuridicas.html. Los archivos se descargan una
vez a la caché privada y se leen en streaming, sin descomprimirlos completos. Las personas naturales
no se publican: para ellas el usuario consulta la situación tributaria de terceros en sii.cl.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib import error as urlerror
from urllib import request
import zipfile

import base_empresa as base
from i18n import tr

BASE_URL = 'https://www.sii.cl/estadisticas/nominas/'
SOURCE_PAGE = 'https://www.sii.cl/sobre_el_sii/nominapersonasjuridicas.html'
NOMINAS = {
    'actividades': 'PUB_NOM_ACTECOS.zip',
    'empresas': 'PUB_EMPRESAS_PJ_2020_A_2024.zip',
}
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
REFRESH_AFTER = timedelta(days=30)
# Nota metodológica 5 de la página del SII: el tramo 1 es «Sin información»; 2–9 son micro,
# pequeña y mediana empresa (Ley 20.416: hasta 100.000 UF anuales); 10–13, gran empresa.
TRAMOS = {
    1: ('Sin información', None),
    2: ('1er rango micro empresa', '0,01 a 200 UF'),
    3: ('2do rango micro empresa', '200,01 a 600 UF'),
    4: ('3er rango micro empresa', '600,01 a 2.400 UF'),
    5: ('1er rango pequeña empresa', '2.400,01 a 5.000 UF'),
    6: ('2do rango pequeña empresa', '5.000,01 a 10.000 UF'),
    7: ('3er rango pequeña empresa', '10.000,01 a 25.000 UF'),
    8: ('1er rango mediana empresa', '25.000,01 a 50.000 UF'),
    9: ('2do rango mediana empresa', '50.000,01 a 100.000 UF'),
    10: ('1er rango gran empresa', '100.000,01 a 200.000 UF'),
    11: ('2do rango gran empresa', '200.000,01 a 600.000 UF'),
    12: ('3er rango gran empresa', '600.000,01 a 1.000.000 UF'),
    13: ('4to rango gran empresa', 'más de 1.000.000 UF'),
}
GENERIC_PHRASES = ('otras actividades de', 'otras actividades', 'actividades conexas', 'n.c.p.', 'n.c.p', 'entre otros', 'otros')


class SiiError(ValueError):
    pass


class _SameHostRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith('https://www.sii.cl/'):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, method='GET', opener=None):
    opener = opener or request.build_opener(_SameHostRedirect()).open
    try:
        return opener(request.Request(url, method=method, headers={'User-Agent': 'buky-licitaciones'}), timeout=60)
    except (urlerror.URLError, TimeoutError, OSError):
        raise SiiError(tr('sii.network')) from None


def cache_dir(directory):
    return Path(directory).expanduser().resolve() / 'cache' / 'sii'


def _meta_path(target):
    return target.with_suffix(target.suffix + '.json')


def ensure_file(directory, kind, refresh=False, opener=None, now=None, output=None):
    """Ruta local de la nómina, descargándola o renovándola solo cuando el SII publica otra."""
    name = NOMINAS[kind]
    target = cache_dir(directory) / name
    meta_path = _meta_path(target)
    now = now or datetime.now(timezone.utc)
    meta = {}
    if target.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except ValueError:
            meta = {}
        checked = meta.get('revisado_utc')
        if not refresh and checked and now - base.moment(checked) < REFRESH_AFTER:
            return target, meta
        try:
            with _open(BASE_URL + name, 'HEAD', opener) as response:
                modified = response.headers.get('Last-Modified')
        except SiiError:
            # Sin red se sigue usando la nómina guardada; se volverá a revisar en la próxima consulta.
            return target, meta
        if modified and modified == meta.get('last_modified'):
            meta['revisado_utc'] = base.utc_iso(now)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            return target, meta
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    emit = output or (lambda message: print(message, file=sys.stderr, flush=True))
    emit(tr('sii.downloading', archivo=name))
    temp = None
    try:
        with _open(BASE_URL + name, 'GET', opener) as response:
            modified = response.headers.get('Last-Modified')
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                temp = Path(out.name)
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise SiiError(tr('sii.too_large'))
                    out.write(chunk)
        if not zipfile.is_zipfile(temp):
            raise SiiError(tr('sii.invalid_file'))
        os.chmod(temp, 0o600)
        temp.replace(target)
        temp = None
    finally:
        if temp and temp.exists():
            temp.unlink()
    meta = {
        'archivo': name, 'last_modified': modified,
        'publicado_utc': base.utc_iso(parsedate_to_datetime(modified)) if modified else None,
        'descargado_utc': base.utc_iso(now), 'revisado_utc': base.utc_iso(now),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    return target, meta


def _rut_body(rut):
    return base.normalize_rut(rut).split('-')[0]


def _rows(archive, member, body):
    """Filas de `member` cuyo RUT coincide, leídas en streaming. Devuelve encabezado y filas."""
    key = body.encode('ascii')
    with zipfile.ZipFile(archive) as bundle, bundle.open(member) as handle:
        header = handle.readline().decode('utf-8', 'replace').rstrip('\r\n').split('\t')
        rut_index = header.index('RUT') if 'RUT' in header else 0
        matches = []
        for raw in handle:
            if key not in raw:
                continue
            columns = raw.rstrip(b'\r\n').split(b'\t')
            if len(columns) > rut_index and columns[rut_index].lstrip(b'0') == key:
                matches.append([value.decode('utf-8', 'replace').strip() for value in columns])
    return header, matches


def _header_key(value):
    import unicodedata
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii').casefold().strip()


def forget(directory, kind):
    target = cache_dir(directory) / NOMINAS[kind]
    target.unlink(missing_ok=True)
    _meta_path(target).unlink(missing_ok=True)


def _date(value, pattern):
    try:
        return datetime.strptime(value, pattern).date().isoformat() if value else None
    except ValueError:
        return None


def activities(archive, rut):
    _, rows = _rows(archive, 'PUB_NOM_ACTECOS.txt', _rut_body(rut))
    result = []
    for row in rows:
        if len(row) < 4:
            continue
        result.append({
            'codigo': row[2], 'descripcion': row[3].capitalize(),
            'desde': _date(row[4] if len(row) > 4 else '', '%d-%m-%Y'),
            'afecta_iva': (row[5] == 'S') if len(row) > 5 and row[5] in {'S', 'N'} else None,
        })
    return sorted(result, key=lambda item: item['desde'] or '')


def tramo(code):
    try:
        number = int(code)
    except (TypeError, ValueError):
        return None
    if number not in TRAMOS:
        return None
    name, uf_range = TRAMOS[number]
    return {'codigo': number, 'nombre': name, 'rango_uf': uf_range, 'emt': None if number == 1 else number <= 9}


def company(archive, rut):
    """Registro del año comercial más reciente disponible en la nómina de empresas."""
    with zipfile.ZipFile(archive) as bundle:
        members = sorted((name for name in bundle.namelist() if re.fullmatch(r'PUB_EMPRESAS_PJ_\d{4}\.txt', name)), reverse=True)
    for member in members:
        header, rows = _rows(archive, member, _rut_body(rut))
        if rows:
            data = {_header_key(key): value for key, value in zip(header, rows[-1])}
            get = lambda prefix: next((value for key, value in data.items() if key.startswith(_header_key(prefix))), '') or None
            return {
                'anio_comercial': int(get('Año comercial') or member[-8:-4]),
                'razon_social': get('Razón social'),
                'tramo_ventas': tramo(get('Tramo según ventas')),
                'trabajadores': int(get('Número de trabajadores')) if (get('Número de trabajadores') or '').isdigit() else None,
                'inicio_actividades': get('Fecha inicio de actividades'),
                'termino_giro': get('Fecha término de giro'),
                'tipo_contribuyente': get('Tipo de contribuyente'),
                'subtipo_contribuyente': get('Subtipo de contribuyente'),
                'rubro': get('Rubro económico'),
                'subrubro': get('Subrubro económico'),
                'actividad_principal': get('Actividad económica'),
                'region': get('Región'),
                'comuna': get('Comuna'),
            }
    return None


def catalog_suggestions(items):
    """Frases de búsqueda derivadas de los giros, para confirmar con el usuario, nunca automáticas."""
    suggestions = []
    for item in items:
        text = item['descripcion'].lower()
        text = re.sub(r'\([^)]*\)', ' ', text)
        for phrase in GENERIC_PHRASES:
            text = text.replace(phrase, ' ')
        for part in re.split(r',| y | e ', text):
            part = ' '.join(part.split()).strip(' .;')
            if len(part) >= 4 and part not in suggestions:
                suggestions.append(part)
    return suggestions[:12]


def _safe(directory, kind, reader, archive, rut):
    """Una caché dañada o con otro formato se elimina para que la próxima consulta la descargue de nuevo."""
    try:
        return reader(archive, rut)
    except (zipfile.BadZipFile, EOFError):
        forget(directory, kind)
        raise SiiError(tr('sii.invalid_file')) from None
    except (KeyError, ValueError, OSError):
        # Formato inesperado o error de lectura: se conserva el archivo (son cientos de MB).
        raise SiiError(tr('sii.unexpected_format')) from None


def _source(kind, meta):
    published = (meta.get('publicado_utc') or '')[:10] or 'fecha no informada'
    label = 'Nómina de actividades económicas' if kind == 'actividades' else 'Nómina de empresas personas jurídicas'
    return f'SII, {label} (publicada {published}); {SOURCE_PAGE}'


def lookup(directory, rut, include_size=True, refresh=False, opener=None, now=None, output=None):
    """Busca giros y tamaño del perfil y los guarda como hechos documentados con su fuente."""
    data = base.load(directory, rut)
    if data.get('tipo_perfil') == 'persona_natural':
        raise SiiError(tr('sii.natural_person'))
    now = now or datetime.now(timezone.utc)
    stamp = base.utc_iso(now)
    archive, meta = ensure_file(directory, 'actividades', refresh, opener, now, output)
    found = _safe(directory, 'actividades', activities, archive, rut)
    result = {'rut': data['rut'], 'actividades': found, 'empresa': None,
              'fuente_actividades': _source('actividades', meta)}
    if include_size:
        archive, size_meta = ensure_file(directory, 'empresas', refresh, opener, now, output)
        result['empresa'] = _safe(directory, 'empresas', company, archive, rut)
        result['fuente_empresa'] = _source('empresas', size_meta)
    if not found and not result['empresa']:
        result['estado'] = 'no_encontrado'
        return result
    if found:
        data['hechos'].append({
            'campo': 'actividades_sii', 'valor': [{'codigo': item['codigo'], 'descripcion': item['descripcion'], 'desde': item['desde']} for item in found],
            'estado': 'documentado', 'fuente': result['fuente_actividades'], 'consultado_en': stamp,
        })
    info = result['empresa']
    from viabilidad import latest_facts
    declared = latest_facts(data).get('tamano_empresa')
    known = isinstance(declared, dict) and declared.get('emt') is not None
    if info and info['tramo_ventas'] and (info['tramo_ventas']['emt'] is not None or not known):
        data['hechos'].append({
            'campo': 'tamano_empresa', 'valor': dict(info['tramo_ventas'], anio_comercial=info['anio_comercial'], trabajadores=info['trabajadores']),
            'estado': 'documentado', 'fuente': result['fuente_empresa'], 'consultado_en': stamp,
        })
    if info and (info['region'] or info['comuna']):
        data['hechos'].append({
            'campo': 'domicilio_sii', 'valor': {'region': info['region'], 'comuna': info['comuna'], 'anio_comercial': info['anio_comercial']},
            'estado': 'documentado', 'fuente': result['fuente_empresa'], 'consultado_en': stamp,
        })
    base.save(directory, data, reason='giros y tamaño desde nóminas del SII')
    result.update({
        'estado': 'encontrado', 'revision': data['_version']['id'],
        'sugerencias_catalogo': catalog_suggestions(found),
        'razon_social_sii': info['razon_social'] if info else None,
    })
    return result
