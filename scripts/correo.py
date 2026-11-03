"""Correo local de solo lectura: OAuth PKCE, filtros, MIME y cola para análisis IA."""
import base64
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets as random_secrets
import sys
import unicodedata
from urllib import error as urlerror
from urllib import parse, request
import webbrowser

import base_empresa as base
import estado
import secretos
import version_store
from i18n import tr

PROVIDERS = {
    'gmail': {
        'authorize': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'scope': 'https://www.googleapis.com/auth/gmail.readonly',
        'api': 'https://gmail.googleapis.com',
        'client_env': 'BUTAKE_GMAIL_CLIENT_ID',
        # Google exige el «client secret» incluso en clientes de escritorio; para ese tipo de
        # aplicación no es confidencial, pero igual se guarda solo en el almacén seguro.
        'secret_env': 'BUTAKE_GMAIL_CLIENT_SECRET',
    },
    'microsoft': {
        'authorize': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        'token': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        'scope': 'offline_access https://graph.microsoft.com/Mail.Read',
        'api': 'https://graph.microsoft.com',
        'client_env': 'BUTAKE_MICROSOFT_CLIENT_ID',
    },
}
DEFAULT_KEYWORDS = ['licitación', 'licitaciones', 'mercado público', 'compra ágil', 'orden de compra', 'adjudicación', 'bases']
ALLOWED_ATTACHMENTS = {'.pdf', '.txt', '.csv', '.json', '.xml', '.html', '.png', '.jpg', '.jpeg', '.xlsx', '.docx'}
MAX_EMAIL_BYTES = 25 * 1024 * 1024
MAX_RESPONSE_BYTES = 36 * 1024 * 1024
MAX_BODY_CHARS = 500000
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


class MailError(ValueError):
    pass


def config_path(directory):
    return Path(directory).expanduser().resolve() / 'correo.json'


def validate_account(account):
    if not isinstance(account, dict):
        raise MailError(tr('mail.invalid_config'))
    allowed = {'proveedor', 'correo', 'client_id', 'palabras', 'remitentes', 'dias_iniciales', 'max_mensajes', 'conectado_utc'}
    if set(account) - allowed:
        raise MailError(tr('mail.invalid_config'))
    provider = account.get('proveedor')
    if provider not in PROVIDERS:
        raise MailError(tr('mail.invalid_provider'))
    try:
        secretos.account_name(provider, account.get('correo'))
    except secretos.SecretError as error:
        raise MailError(str(error)) from None
    email = account['correo']
    if email.count('@') != 1 or email.startswith('@') or email.endswith('@'):
        raise MailError(tr('mail.invalid_account'))
    client_id = account.get('client_id')
    if not isinstance(client_id, str) or not 1 <= len(client_id) <= 500 or any(c.isspace() for c in client_id):
        raise MailError(tr('mail.client_id_required'))
    for key in ['palabras', 'remitentes']:
        values = account.get(key, [])
        if not isinstance(values, list) or len(values) > 50 or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in values):
            raise MailError(tr('mail.invalid_filters'))
    if not account.get('palabras') and not account.get('remitentes'):
        raise MailError(tr('mail.filters_required'))
    if type(account.get('dias_iniciales', 30)) is not int or not 1 <= account.get('dias_iniciales', 30) <= 365:
        raise MailError(tr('mail.invalid_config'))
    if type(account.get('max_mensajes', 50)) is not int or not 1 <= account.get('max_mensajes', 50) <= 100:
        raise MailError(tr('mail.invalid_config'))
    if account.get('conectado_utc'):
        base.moment(account['conectado_utc'])
    return account


def load_config(directory):
    path = config_path(directory)
    if not path.exists():
        return {'schema_version': 1, 'cuentas': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'schema_version', 'cuentas'} or data.get('schema_version') != 1 or not isinstance(data['cuentas'], list):
        raise MailError(tr('mail.invalid_config'))
    for account in data['cuentas']:
        validate_account(account)
    return data


def save_config(directory, config):
    load_config(directory) if config_path(directory).exists() else None
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise MailError(tr('mail.invalid_config'))
    for account in config.get('cuentas', []):
        validate_account(account)
    version_store.atomic_write(config_path(directory), (json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def _request(url, transport=None, headers=None, form=None, expect_json=True):
    headers = {'Accept': 'application/json' if expect_json else 'message/rfc822', **(headers or {})}
    data = parse.urlencode(form).encode('utf-8') if form is not None else None
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    if transport:
        result = transport(req, 30)
        if expect_json and isinstance(result, (bytes, str)):
            result = json.loads(result)
        return result
    try:
        with request.urlopen(req, timeout=30) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except urlerror.HTTPError as error:
        if error.code in {400, 401} and form is not None and form.get('grant_type') == 'refresh_token':
            raise MailError(tr('mail.reconnect_required')) from None
        raise MailError(tr('mail.http_error', codigo=error.code)) from None
    except (urlerror.URLError, TimeoutError, OSError, HTTPException):
        raise MailError(tr('mail.network_error')) from None
    if len(content) > MAX_RESPONSE_BYTES:
        raise MailError(tr('mail.message_too_large'))
    if expect_json:
        try:
            return json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MailError(tr('mail.invalid_response')) from None
    return content


def pkce_pair():
    verifier = random_secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
    return verifier, challenge


def authorization_url(provider, client_id, email, redirect_uri, state, challenge):
    settings = PROVIDERS[provider]
    params = {
        'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri,
        'scope': settings['scope'], 'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'login_hint': email, 'response_mode': 'query',
    }
    if provider == 'gmail':
        params.update(access_type='offline', prompt='consent')
    return settings['authorize'] + '?' + parse.urlencode(params)


def validate_callback(query, expected_state):
    params = parse.parse_qs(query, keep_blank_values=True, max_num_fields=20)
    if set(params) - {'code', 'state', 'error', 'error_description', 'session_state'}:
        raise MailError(tr('mail.oauth_callback'))
    if params.get('error'):
        raise MailError(tr('mail.oauth_denied'))
    code = params.get('code', [''])[0]
    state = params.get('state', [''])[0]
    if not code or len(code) > 8192 or not random_secrets.compare_digest(state, expected_state):
        raise MailError(tr('mail.oauth_state'))
    return code


def wait_for_callback(server, expected_state, timeout=120):
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            target = parse.urlsplit(self.path)
            try:
                if target.path != '/oauth/callback' or target.hostname or target.fragment:
                    raise MailError(tr('mail.oauth_callback'))
                result['code'] = validate_callback(target.query, expected_state)
                message = tr('mail.oauth_complete')
            except MailError as error:
                result['error'] = error
                message = tr('mail.oauth_failed')
            content = ('<!doctype html><html lang="es"><meta charset="utf-8"><title>Butake</title><body>' + message + '</body></html>').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server.RequestHandlerClass = Handler
    server.timeout = timeout
    server.handle_request()
    if 'code' not in result:
        if isinstance(result.get('error'), MailError):
            raise result['error']
        raise MailError(tr('mail.oauth_timeout'))
    return result['code']


def normalize_token(provider, payload, previous=None):
    if not isinstance(payload, dict) or not isinstance(payload.get('access_token'), str) or not payload['access_token']:
        raise MailError(tr('mail.invalid_response'))
    if type(payload.get('expires_in')) is not int or not 60 <= payload['expires_in'] <= 86400:
        raise MailError(tr('mail.invalid_response'))
    granted = set(str(payload.get('scope', '')).replace(',', ' ').split())
    required = PROVIDERS[provider]['scope'].split()
    if granted and not set(required).issubset(granted):
        raise MailError(tr('mail.scope_missing'))
    refresh = payload.get('refresh_token') or (previous or {}).get('refresh_token')
    if refresh is not None and (not isinstance(refresh, str) or not refresh):
        raise MailError(tr('mail.invalid_response'))
    token = {
        'access_token': payload['access_token'], 'refresh_token': refresh,
        'expira_utc': base.utc_iso(datetime.now(timezone.utc) + timedelta(seconds=payload['expires_in'])),
        'scope': sorted(granted) if granted else required,
    }
    return token


DEFAULT_OAUTH_PORT = 8765


def connect(directory, provider, email, client_id=None, opener=None, transport=None, store=None,
            open_browser=True, oauth_port=None, output=None, callback_timeout=None):
    if provider not in PROVIDERS:
        raise MailError(tr('mail.invalid_provider'))
    client_id = client_id or os.environ.get(PROVIDERS[provider]['client_env'], '')
    account = {
        'proveedor': provider, 'correo': email.strip().lower(), 'client_id': client_id,
        'palabras': DEFAULT_KEYWORDS.copy(), 'remitentes': [], 'dias_iniciales': 30,
        'max_mensajes': 50, 'conectado_utc': base.utc_now(),
    }
    validate_account(account)
    store = store or secretos.SecretStore(directory)
    if not store.status().get('disponible'):
        raise secretos.SecretError(tr('secrets.unavailable'))
    if oauth_port is not None and (type(oauth_port) is not int or not 1024 <= oauth_port <= 65535):
        raise MailError(tr('mail.oauth_port'))
    port = oauth_port if oauth_port is not None else (0 if open_browser else DEFAULT_OAUTH_PORT)
    verifier, challenge = pkce_pair()
    state = random_secrets.token_urlsafe(32)
    try:
        server = HTTPServer(('127.0.0.1', port), BaseHTTPRequestHandler)
    except OSError:
        raise MailError(tr('mail.oauth_listen', puerto=port)) from None
    try:
        host = '127.0.0.1' if provider == 'gmail' else 'localhost'
        redirect_uri = f'http://{host}:{server.server_port}/oauth/callback'
        url = authorization_url(provider, client_id, account['correo'], redirect_uri, state, challenge)
        if open_browser:
            opener = opener or webbrowser.open
            if opener(url) is False:
                raise MailError(tr('mail.browser_failed'))
        else:
            emit = output or (lambda message: print(message, file=sys.stderr, flush=True))
            emit(tr('mail.manual_intro'))
            emit(url)
            emit(tr('mail.manual_tunnel', puerto=server.server_port))
            emit(tr('mail.manual_wait', puerto=server.server_port))
        timeout = callback_timeout or (120 if open_browser else 600)
        code = wait_for_callback(server, state, timeout)
    finally:
        server.server_close()
    form = {
        'client_id': client_id, 'code': code, 'code_verifier': verifier,
        'redirect_uri': redirect_uri, 'grant_type': 'authorization_code',
    }
    client_secret = os.environ.get(PROVIDERS[provider].get('secret_env', ''), '').strip()
    if client_secret:
        form['client_secret'] = client_secret
    token = normalize_token(provider, _request(PROVIDERS[provider]['token'], transport, form=form))
    if client_secret:
        token['client_secret'] = client_secret
    name = secretos.account_name(provider, account['correo'])
    secretos.save_json(store, name, token)
    config = load_config(directory)
    config['cuentas'] = [item for item in config['cuentas'] if secretos.account_name(item['proveedor'], item['correo']) != name]
    config['cuentas'].append(account)
    save_config(directory, config)
    return {'proveedor': provider, 'correo': account['correo'], 'estado': 'conectado', 'almacen': store.status()['backend']}


def access_token(directory, account, store=None, transport=None):
    store = store or secretos.SecretStore(directory)
    name = secretos.account_name(account['proveedor'], account['correo'])
    token = secretos.load_json(store, name)
    try:
        expires = base.moment(token.get('expira_utc'))
    except base.DataError:
        raise MailError(tr('mail.reconnect')) from None
    if expires > datetime.now(timezone.utc) + timedelta(seconds=60) and isinstance(token.get('access_token'), str):
        return token['access_token']
    if not isinstance(token.get('refresh_token'), str) or not token['refresh_token']:
        raise MailError(tr('mail.reconnect'))
    provider = account['proveedor']
    form = {'client_id': account['client_id'], 'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'}
    client_secret = token.get('client_secret') or os.environ.get(PROVIDERS[provider].get('secret_env', ''), '').strip()
    if client_secret:
        form['client_secret'] = client_secret
    payload = _request(PROVIDERS[provider]['token'], transport, form=form)
    previous_secret = token.get('client_secret')
    token = normalize_token(provider, payload, token)
    if previous_secret or client_secret:
        token['client_secret'] = previous_secret or client_secret
    secretos.save_json(store, name, token)
    return token['access_token']


def disconnect(directory, provider, email, store=None):
    config = load_config(directory)
    name = secretos.account_name(provider, email)
    accounts = [item for item in config['cuentas'] if secretos.account_name(item['proveedor'], item['correo']) == name]
    if not accounts:
        raise MailError(tr('mail.not_connected'))
    store = store or secretos.SecretStore(directory)
    store.delete(name)
    config['cuentas'] = [item for item in config['cuentas'] if secretos.account_name(item['proveedor'], item['correo']) != name]
    save_config(directory, config)
    return {'estado': 'desconectado', 'proveedor': provider, 'correo': email.lower(), 'contenido_conservado': True}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored += 1
        elif tag in {'p', 'br', 'li', 'tr', 'div'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def html_text(content):
    parser = TextExtractor()
    parser.feed(content[:MAX_BODY_CHARS * 2])
    parser.close()
    return re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()


def safe_filename(value, index):
    value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    value = value.replace('\\', '/').split('/')[-1]
    value = re.sub(r'[^A-Za-z0-9._-]+', '-', value).strip('.-')[:120]
    return f'{index:02d}-' + (value or 'adjunto.bin')


def message_content(message):
    body = ''
    try:
        part = message.get_body(preferencelist=('plain', 'html'))
    except (AttributeError, LookupError):
        part = None
    if part is not None:
        try:
            content = part.get_content()
            if isinstance(content, bytes):
                content = content.decode(part.get_content_charset() or 'utf-8', errors='replace')
            body = html_text(content) if part.get_content_type() == 'text/html' else content
        except (LookupError, UnicodeError, ValueError):
            body = ''
    attachments = []
    for index, part in enumerate(message.iter_attachments(), 1):
        if index > 20:
            break
        filename = part.get_filename() or f'adjunto-{index}.bin'
        extension = Path(filename.replace('\\', '/')).suffix.lower()
        try:
            content = part.get_payload(decode=True) or b''
        except (ValueError, TypeError):
            content = b''
        if not content or len(content) > MAX_ATTACHMENT_BYTES or extension not in ALLOWED_ATTACHMENTS:
            attachments.append({'nombre': safe_filename(filename, index), 'estado': 'omitido', 'motivo': 'tipo_o_tamano'})
            continue
        attachments.append({
            'nombre': safe_filename(filename, index), 'estado': 'extraido', 'contenido': content,
            'tipo': part.get_content_type(), 'sha256': hashlib.sha256(content).hexdigest(),
        })
    return body[:MAX_BODY_CHARS], attachments


def received_time(message):
    try:
        value = parsedate_to_datetime(str(message.get('Date', '')))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return base.utc_iso(value)
    except (TypeError, ValueError, OverflowError):
        return base.utc_now()


def mentions_code(text, code):
    """Busca el código completo, sin aceptarlo como parte de otro más largo (p. ej. 1234-5-COT26)."""
    return re.search(r'(?<![A-Z0-9-])' + re.escape(code.upper()) + r'(?![A-Z0-9]|-[A-Z0-9])', text) is not None


def matching_processes(directory, text):
    text = text.upper()
    if '-' not in text:
        return None, []
    root = Path(directory).expanduser().resolve()
    matches = []
    for path in root.glob('*/base.json'):
        try:
            company = base.load(root, path.parent.name)
        except (base.DataError, OSError, ValueError):
            continue
        for item in company['oportunidades'].values():
            code = str(item.get('codigo', ''))
            if code and mentions_code(text, code):
                matches.append((company['rut'], item['codigo']))
    companies = {rut for rut, code in matches}
    return (matches[0][0] if len(companies) == 1 else None), [{'rut': rut, 'codigo': code} for rut, code in matches]


def ingest_bytes(directory, raw, provider, message_id=None, rut=None):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_EMAIL_BYTES:
        raise MailError(tr('mail.message_too_large'))
    if provider not in {'gmail', 'microsoft', 'eml'}:
        raise MailError(tr('mail.invalid_provider'))
    digest = hashlib.sha256(raw).hexdigest()
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
    except (ValueError, TypeError):
        raise MailError(tr('mail.invalid_message')) from None
    message_id = str(message_id or message.get('Message-ID') or ('local-' + digest)).strip()[:1000]
    if not message_id or any(ord(c) < 32 for c in message_id):
        raise MailError(tr('mail.invalid_message'))
    with estado.connect(directory) as connection:
        previous = connection.execute('SELECT sha256, estado, archivo FROM correo_eventos WHERE proveedor = ? AND mensaje_id = ?', (provider, message_id)).fetchone()
        if previous:
            if previous['sha256'] != digest:
                return {'estado': 'conflicto', 'mensaje_id': message_id, 'detalle': 'mismo_id_distinto_contenido'}
            return {'estado': 'duplicado', 'mensaje_id': message_id, 'archivo': previous['archivo']}
    body, attachments = message_content(message)
    rut = base.normalize_rut(rut) if rut else None
    if not rut:
        rut, processes = matching_processes(directory, str(message.get('Subject', '')) + '\n' + body)
    else:
        processes = []
    folder = Path(directory).expanduser().resolve() / 'correo' / (rut or 'sin_asignar') / digest[:24]
    manifest_path = folder / 'contenido.json'
    with estado.connect(directory) as connection:
        claimed = connection.execute(
            'INSERT INTO correo_eventos(proveedor, mensaje_id, rut, recibido_utc, sha256, estado, archivo, creado_utc) VALUES(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
            (provider, message_id, rut, received_time(message), digest, 'procesando', str(manifest_path), base.utc_now()),
        )
        connection.commit()
    if not claimed.rowcount:
        return {'estado': 'duplicado', 'mensaje_id': message_id}
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        version_store.atomic_write(folder / 'mensaje.eml', raw)
        saved_attachments = []
        for item in attachments:
            public = {key: value for key, value in item.items() if key != 'contenido'}
            if item.get('contenido') is not None:
                version_store.atomic_write(folder / item['nombre'], item['contenido'])
            saved_attachments.append(public)
        manifest = {
            'schema_version': 1, 'proveedor': provider, 'mensaje_id': message_id,
            'rut': rut, 'procesos_coincidentes': processes, 'recibido_utc': received_time(message),
            'remitente': str(message.get('From', ''))[:1000], 'destinatarios': str(message.get('To', ''))[:2000],
            'asunto': str(message.get('Subject', ''))[:2000], 'cuerpo': body,
            'adjuntos': saved_attachments, 'sha256': digest, 'estado': 'pendiente_analisis_ia',
            'advertencia': tr('mail.untrusted'),
            'importado_utc': base.utc_now(),
        }
        version_store.atomic_write(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
        with estado.connect(directory) as connection:
            connection.execute("UPDATE correo_eventos SET estado = 'pendiente_analisis_ia' WHERE proveedor = ? AND mensaje_id = ? AND sha256 = ?", (provider, message_id, digest))
            connection.commit()
    except Exception:
        with estado.connect(directory) as connection:
            connection.execute("DELETE FROM correo_eventos WHERE proveedor = ? AND mensaje_id = ? AND estado = 'procesando'", (provider, message_id))
            connection.commit()
        raise
    return {'estado': 'pendiente_analisis_ia', 'mensaje_id': message_id, 'rut': rut, 'archivo': str(manifest_path), 'procesos_coincidentes': processes}


def import_eml(directory, path, rut=None):
    source = Path(path).expanduser()
    if source.is_symlink() or source.suffix.lower() != '.eml':
        raise MailError(tr('mail.eml_required'))
    path = source.resolve()
    try:
        size = path.stat().st_size
        if size > MAX_EMAIL_BYTES:
            raise MailError(tr('mail.message_too_large'))
        raw = path.read_bytes()
    except FileNotFoundError:
        raise MailError(tr('error.not_found')) from None
    return ingest_bytes(directory, raw, 'eml', rut=rut)


def matches_filters(account, subject, sender):
    subject = str(subject or '').casefold()
    sender = str(sender or '').casefold()
    senders = [value.casefold() for value in account.get('remitentes', [])]
    if senders and not any(value in sender for value in senders):
        return False
    keywords = [value.casefold() for value in account.get('palabras', [])]
    return not keywords or any(value in subject for value in keywords)


def known_message(directory, provider, message_id):
    """Estado registrado del mensaje (incluido «filtrado»), o None si nunca se vio."""
    with estado.connect(directory) as connection:
        row = connection.execute('SELECT estado FROM correo_eventos WHERE proveedor = ? AND mensaje_id = ?', (provider, message_id)).fetchone()
    return row['estado'] if row else None


def record_filtered(directory, provider, message_id):
    """Recuerda mensajes fuera de los filtros para no volver a descargarlos en cada sincronización."""
    now = base.utc_now()
    with estado.connect(directory) as connection:
        connection.execute(
            "INSERT INTO correo_eventos(proveedor, mensaje_id, rut, recibido_utc, sha256, estado, archivo, creado_utc) "
            "VALUES(?, ?, NULL, ?, '', 'filtrado', '', ?) ON CONFLICT(proveedor, mensaje_id) DO NOTHING",
            (provider, message_id, now, now),
        )
        connection.commit()


def forget_filtered(directory, provider):
    """Al cambiar filtros, los mensajes descartados vuelven a evaluarse."""
    with estado.connect(directory) as connection:
        connection.execute("DELETE FROM correo_eventos WHERE proveedor = ? AND estado = 'filtrado'", (provider,))
        connection.commit()


def _save_sweep(directory, prefix, next_page, newest, later):
    """Guarda la página siguiente y el máximo visto en todo el barrido.

    Los listados vienen del más nuevo al más antiguo: el corte `despues` solo avanza al terminar
    el barrido y con el máximo de todas sus páginas, nunca con el de la última.
    """
    with estado.connect(directory) as connection:
        best = estado.get_cursor(connection, prefix + 'maximo') or ''
        if newest and later(newest, best):
            best = newest
        if next_page:
            estado.set_cursor(connection, prefix + 'pagina', next_page)
            estado.set_cursor(connection, prefix + 'maximo', best)
        else:
            estado.set_cursor(connection, prefix + 'pagina', '')
            estado.set_cursor(connection, prefix + 'maximo', '')
            if best:
                estado.set_cursor(connection, prefix + 'despues', best)


def safe_api_url(provider, value):
    target = parse.urlsplit(value)
    if target.scheme != 'https' or target.hostname != parse.urlsplit(PROVIDERS[provider]['api']).hostname or target.username or target.password or target.fragment:
        raise MailError(tr('mail.invalid_response'))
    return value


def sync_gmail(directory, account, store=None, transport=None):
    token = access_token(directory, account, store, transport)
    provider = 'gmail'
    prefix = 'correo:gmail:' + account['correo'] + ':'
    with estado.connect(directory) as connection:
        page = estado.get_cursor(connection, prefix + 'pagina')
        after = estado.get_cursor(connection, prefix + 'despues')
    query = '{' + ' '.join('"' + value.replace('"', '') + '"' for value in account['palabras']) + '}'
    if account.get('remitentes'):
        query += ' {' + ' '.join('from:"' + value.replace('"', '') + '"' for value in account['remitentes']) + '}'
    query += ' after:' + after if after else f" newer_than:{account['dias_iniciales']}d"
    params = {'q': query.strip(), 'maxResults': account['max_mensajes']}
    if page:
        params['pageToken'] = page
    url = PROVIDERS[provider]['api'] + '/gmail/v1/users/me/messages?' + parse.urlencode(params)
    listing = _request(url, transport, headers={'Authorization': 'Bearer ' + token})
    if not isinstance(listing, dict) or not isinstance(listing.get('messages', []), list):
        raise MailError(tr('mail.invalid_response'))
    imported, duplicates, ignored = 0, 0, 0
    newest = 0
    for entry in listing['messages'][:account['max_mensajes']]:
        identifier = entry.get('id') if isinstance(entry, dict) else None
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', identifier):
            raise MailError(tr('mail.invalid_response'))
        seen = known_message(directory, provider, identifier)
        if seen:
            ignored += seen == 'filtrado'
            duplicates += seen != 'filtrado'
            continue
        message_url = PROVIDERS[provider]['api'] + '/gmail/v1/users/me/messages/' + parse.quote(identifier, safe='')
        # Primero solo encabezados: un mensaje fuera de los filtros no se descarga completo.
        metadata = _request(message_url + '?' + parse.urlencode([('format', 'metadata'), ('metadataHeaders', 'Subject'), ('metadataHeaders', 'From')]),
                            transport, headers={'Authorization': 'Bearer ' + token})
        headers = {}
        if isinstance(metadata, dict) and isinstance((metadata.get('payload') or {}).get('headers'), list):
            headers = {str(item.get('name', '')).lower(): item.get('value') for item in metadata['payload']['headers'] if isinstance(item, dict)}
        try:
            newest = max(newest, int((metadata or {}).get('internalDate', '0')) // 1000)
        except (ValueError, TypeError, AttributeError):
            pass
        if headers and not matches_filters(account, headers.get('subject'), headers.get('from')):
            record_filtered(directory, provider, identifier)
            ignored += 1
            continue
        payload = _request(message_url + '?format=raw', transport, headers={'Authorization': 'Bearer ' + token})
        if not isinstance(payload, dict) or not isinstance(payload.get('raw'), str) or len(payload['raw']) > MAX_RESPONSE_BYTES:
            raise MailError(tr('mail.invalid_response'))
        try:
            raw = base64.b64decode(payload['raw'] + '=' * (-len(payload['raw']) % 4), altchars=b'-_', validate=True)
        except (ValueError, TypeError):
            raise MailError(tr('mail.invalid_response')) from None
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        if not matches_filters(account, parsed.get('Subject'), parsed.get('From')):
            record_filtered(directory, provider, identifier)
            ignored += 1
        else:
            result = ingest_bytes(directory, raw, provider, identifier)
            imported += result['estado'] == 'pendiente_analisis_ia'
            duplicates += result['estado'] == 'duplicado'
        try:
            newest = max(newest, int(payload.get('internalDate', '0')) // 1000)
        except (ValueError, TypeError):
            pass
    next_page = listing.get('nextPageToken')
    _save_sweep(directory, prefix, next_page if isinstance(next_page, str) else '', str(newest) if newest else '',
                lambda value, best: not best or int(value) > int(best))
    return {'proveedor': provider, 'correo': account['correo'], 'importados': imported, 'duplicados': duplicates, 'filtrados': ignored, 'pagina_pendiente': bool(listing.get('nextPageToken'))}


def sync_microsoft(directory, account, store=None, transport=None):
    token = access_token(directory, account, store, transport)
    provider = 'microsoft'
    prefix = 'correo:microsoft:' + account['correo'] + ':'
    with estado.connect(directory) as connection:
        page = estado.get_cursor(connection, prefix + 'pagina')
        after = estado.get_cursor(connection, prefix + 'despues')
    if not after:
        after = base.utc_iso(datetime.now(timezone.utc) - timedelta(days=account['dias_iniciales']))
    base.moment(after)
    if page:
        url = safe_api_url(provider, page)
    else:
        params = {
            '$top': account['max_mensajes'], '$select': 'id,subject,from,receivedDateTime,internetMessageId',
            '$filter': "receivedDateTime ge " + after, '$orderby': 'receivedDateTime desc',
        }
        url = PROVIDERS[provider]['api'] + '/v1.0/me/mailFolders/inbox/messages?' + parse.urlencode(params)
    listing = _request(url, transport, headers={'Authorization': 'Bearer ' + token})
    if not isinstance(listing, dict) or not isinstance(listing.get('value'), list):
        raise MailError(tr('mail.invalid_response'))
    imported, duplicates, ignored = 0, 0, 0
    newest = ''
    for item in listing['value'][:account['max_mensajes']]:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or len(item['id']) > 2000:
            raise MailError(tr('mail.invalid_response'))
        identifier = item['id']
        received = item.get('receivedDateTime')
        if received:
            newest = max(newest, base.utc_iso(base.moment(received)))
        seen = known_message(directory, provider, identifier)
        if seen:
            ignored += seen == 'filtrado'
            duplicates += seen != 'filtrado'
            continue
        sender = ((item.get('from') or {}).get('emailAddress') or {}).get('address', '')
        if not matches_filters(account, item.get('subject'), sender):
            record_filtered(directory, provider, identifier)
            ignored += 1
            continue
        url = PROVIDERS[provider]['api'] + '/v1.0/me/messages/' + parse.quote(identifier, safe='') + '/$value'
        raw = _request(url, transport, headers={'Authorization': 'Bearer ' + token}, expect_json=False)
        if not isinstance(raw, bytes):
            raise MailError(tr('mail.invalid_response'))
        result = ingest_bytes(directory, raw, provider, identifier)
        imported += result['estado'] == 'pendiente_analisis_ia'
        duplicates += result['estado'] == 'duplicado'
    next_page = listing.get('@odata.nextLink')
    if isinstance(next_page, str) and next_page:
        safe_api_url(provider, next_page)
    else:
        next_page = ''
    _save_sweep(directory, prefix, next_page, newest or after, lambda value, best: value > best)
    return {'proveedor': provider, 'correo': account['correo'], 'importados': imported, 'duplicados': duplicates, 'filtrados': ignored, 'pagina_pendiente': bool(listing.get('@odata.nextLink'))}


def sync_account(directory, account, store=None, transport=None):
    validate_account(account)
    return sync_gmail(directory, account, store, transport) if account['proveedor'] == 'gmail' else sync_microsoft(directory, account, store, transport)


def sync_configured(directory, store=None, transport=None):
    config = load_config(directory)
    if not config['cuentas']:
        return {'estado': 'sin_configurar', 'cuentas': []}
    results, errors = [], []
    for account in config['cuentas']:
        try:
            results.append(sync_account(directory, account, store, transport))
        except (MailError, secretos.SecretError, base.DataError, OSError) as error:
            errors.append({'proveedor': account['proveedor'], 'correo': account['correo'], 'error': str(error)[:500]})
    return {'estado': 'parcial' if errors else 'completado', 'cuentas': results, 'errores': errors}


def pending(directory, rut=None):
    query = "SELECT proveedor, mensaje_id, rut, recibido_utc, archivo FROM correo_eventos WHERE estado = 'pendiente_analisis_ia'"
    params = []
    if rut:
        query += ' AND rut = ?'
        params.append(base.normalize_rut(rut))
    query += ' ORDER BY recibido_utc, mensaje_id LIMIT 200'
    with estado.connect(directory) as connection:
        return estado.rows_dict(connection.execute(query, params).fetchall())


def read_message_for_review(directory, provider, message_id):
    if provider not in {'gmail', 'microsoft', 'eml'} or not isinstance(message_id, str) or len(message_id) > 1000:
        raise MailError(tr('error.not_found'))
    with estado.connect(directory) as connection:
        row = connection.execute('SELECT archivo FROM correo_eventos WHERE proveedor = ? AND mensaje_id = ?', (provider, message_id)).fetchone()
    if not row:
        raise MailError(tr('error.not_found'))
    path = Path(row['archivo'])
    root = (Path(directory).expanduser().resolve() / 'correo').resolve()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        raw = (resolved.parent / 'mensaje.eml').read_bytes()
    except (OSError, ValueError):
        raise MailError(tr('mail.invalid_message')) from None
    if path.is_symlink() or resolved.name != 'contenido.json':
        raise MailError(tr('mail.invalid_message'))
    manifest = json.loads(resolved.read_text(encoding='utf-8'))
    digest = hashlib.sha256(raw).hexdigest()
    if (manifest.get('sha256') != digest or resolved.parent.name != digest[:24]
            or manifest.get('proveedor') != provider or manifest.get('mensaje_id') != message_id):
        raise MailError(tr('mail.invalid_message'))
    manifest['_archivo'] = str(resolved)
    return manifest


def read_message(directory, provider, message_id):
    manifest = read_message_for_review(directory, provider, message_id)
    if manifest.get('estado') != 'pendiente_analisis_ia':
        raise MailError(tr('mail.already_reviewed'))
    manifest.pop('_archivo')
    return manifest


def mark_reviewed(directory, provider, message_id):
    manifest = read_message_for_review(directory, provider, message_id)
    if manifest.get('estado') != 'pendiente_analisis_ia':
        raise MailError(tr('mail.already_reviewed'))
    with estado.connect(directory) as connection:
        result = connection.execute("UPDATE correo_eventos SET estado = 'revisado' WHERE proveedor = ? AND mensaje_id = ? AND estado = 'pendiente_analisis_ia'", (provider, message_id))
        connection.commit()
    if not result.rowcount:
        raise MailError(tr('error.not_found'))
    manifest['estado'] = 'revisado'
    manifest['revisado_utc'] = base.utc_now()
    version_store.atomic_write(Path(manifest.pop('_archivo')), (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
    return {'estado': 'revisado', 'proveedor': provider, 'mensaje_id': message_id}
