"""Estado operativo SQLite: recordatorios, cursores, deduplicación, equipo y salida de correo, sin secretos."""
import json
import os
from pathlib import Path
import sqlite3

import base_empresa as base


SCHEMA = '''
CREATE TABLE IF NOT EXISTS recordatorios (
    id TEXT PRIMARY KEY,
    rut TEXT NOT NULL,
    proceso TEXT,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    vence_utc TEXT NOT NULL,
    disponible_utc TEXT NOT NULL,
    creado_utc TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    enviado_utc TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    UNIQUE(rut, proceso, tipo, vence_utc)
);
CREATE INDEX IF NOT EXISTS idx_recordatorios_pendientes
    ON recordatorios(estado, disponible_utc, vence_utc);
CREATE TABLE IF NOT EXISTS cursores (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    actualizado_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS correo_eventos (
    proveedor TEXT NOT NULL,
    mensaje_id TEXT NOT NULL,
    rut TEXT,
    recibido_utc TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    estado TEXT NOT NULL,
    archivo TEXT NOT NULL,
    creado_utc TEXT NOT NULL,
    PRIMARY KEY(proveedor, mensaje_id)
);
CREATE TABLE IF NOT EXISTS equipo (
    id TEXT PRIMARY KEY,
    rut TEXT NOT NULL,
    nombre TEXT NOT NULL,
    correo TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'equipo',
    avisos TEXT NOT NULL DEFAULT '["recordatorios","resumen"]',
    activo INTEGER NOT NULL DEFAULT 1,
    creado_utc TEXT NOT NULL,
    actualizado_utc TEXT NOT NULL,
    UNIQUE(rut, correo)
);
CREATE TABLE IF NOT EXISTS correo_salida (
    id TEXT PRIMARY KEY,
    rut TEXT NOT NULL,
    origen TEXT NOT NULL UNIQUE,
    para TEXT NOT NULL,
    asunto TEXT NOT NULL,
    cuerpo TEXT NOT NULL,
    automatico INTEGER NOT NULL DEFAULT 0,
    creado_utc TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    resuelto_utc TEXT,
    referencia TEXT
);
CREATE INDEX IF NOT EXISTS idx_correo_salida_pendientes
    ON correo_salida(estado, rut, creado_utc);
'''


def database_path(directory):
    return Path(directory).expanduser().resolve() / 'estado.sqlite3'


def connect(directory):
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = database_path(directory)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA journal_mode = WAL')
    connection.execute('PRAGMA busy_timeout = 30000')
    connection.executescript(SCHEMA)
    connection.execute('PRAGMA user_version = 1')
    os.chmod(path, 0o600)
    return connection


def get_cursor(connection, key):
    row = connection.execute('SELECT valor FROM cursores WHERE clave = ?', (key,)).fetchone()
    return row['valor'] if row else None


def set_cursor(connection, key, value):
    connection.execute(
        'INSERT INTO cursores(clave, valor, actualizado_utc) VALUES(?, ?, ?) '
        'ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, actualizado_utc = excluded.actualizado_utc',
        (key, value, base.utc_now()),
    )
    connection.commit()


def rows_dict(rows):
    return [dict(row) for row in rows]
