"""Bandeja del corredor: solicitudes y derivaciones que registran los agentes (SQLite).

Es un sistema SIMULADO para la demo: el corredor aún no define cómo procesa una
solicitud (correo, CRM, portal de la aseguradora). Cuando lo defina, solo cambia
este archivo; las herramientas del agente siguen igual.

La base queda en data/seguros.db, que no se sube a git (trae datos de clientes).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.config import RAIZ

BASE_DATOS = RAIZ / "data" / "seguros.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS solicitudes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    numero    TEXT UNIQUE,
    corredor  TEXT NOT NULL,
    seguro    TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    datos     TEXT NOT NULL,          -- JSON con los campos de la ficha
    estado    TEXT NOT NULL DEFAULT 'recibida',
    creada    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS derivaciones (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    numero    TEXT UNIQUE,
    corredor  TEXT NOT NULL,
    seguro    TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    motivo    TEXT NOT NULL,
    urgencia  TEXT NOT NULL,
    contacto  TEXT NOT NULL DEFAULT '',
    estado    TEXT NOT NULL DEFAULT 'pendiente',
    creada    TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Registro:
    numero: str
    corredor: str
    seguro: str
    estado: str
    creada: str


def _conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or BASE_DATOS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.executescript(_ESQUEMA)
    return conexion


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _insertar(tabla: str, prefijo: str, valores: dict, ruta: Path | None) -> str:
    with closing(_conectar(ruta)) as db, db:
        columnas = ", ".join(valores)
        marcas = ", ".join("?" for _ in valores)
        cursor = db.execute(f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})", tuple(valores.values()))
        numero = f"{prefijo}-{datetime.now():%Y%m%d}-{cursor.lastrowid:04d}"
        db.execute(f"UPDATE {tabla} SET numero = ? WHERE id = ?", (numero, cursor.lastrowid))
    return numero


def guardar_solicitud(corredor: str, seguro: str, thread_id: str, datos: dict[str, str],
                      ruta: Path | None = None) -> str:
    return _insertar("solicitudes", "SOL", {
        "corredor": corredor, "seguro": seguro, "thread_id": thread_id,
        "datos": json.dumps(datos, ensure_ascii=False), "creada": _ahora(),
    }, ruta)


def guardar_derivacion(corredor: str, seguro: str, thread_id: str, motivo: str, urgencia: str,
                       contacto: str = "", ruta: Path | None = None) -> str:
    return _insertar("derivaciones", "DER", {
        "corredor": corredor, "seguro": seguro, "thread_id": thread_id, "motivo": motivo,
        "urgencia": urgencia, "contacto": contacto, "creada": _ahora(),
    }, ruta)


def buscar_registro(numero: str, corredor: str, ruta: Path | None = None) -> Registro | None:
    """Estado de una solicitud o derivación. Nunca devuelve los datos del cliente."""
    tabla = {"SOL": "solicitudes", "DER": "derivaciones"}.get(numero.strip().upper()[:3])
    if not tabla:
        return None
    with closing(_conectar(ruta)) as db:
        fila = db.execute(
            f"SELECT numero, corredor, seguro, estado, creada FROM {tabla} WHERE numero = ? AND corredor = ?",
            (numero.strip().upper(), corredor),
        ).fetchone()
    return Registro(**dict(fila)) if fila else None


def listar(tabla: str, corredor: str | None = None, ruta: Path | None = None) -> list[dict]:
    if tabla not in {"solicitudes", "derivaciones"}:
        raise ValueError(tabla)
    with closing(_conectar(ruta)) as db:
        consulta = f"SELECT * FROM {tabla}" + (" WHERE corredor = ?" if corredor else "") + " ORDER BY id DESC"
        filas = db.execute(consulta, (corredor,) if corredor else ()).fetchall()
    resultado = [dict(f) for f in filas]
    for fila in resultado:
        if "datos" in fila:
            fila["datos"] = json.loads(fila["datos"])
    return resultado
