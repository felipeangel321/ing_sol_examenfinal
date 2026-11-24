"""Base de datos del microservicio de usuarios (SQLite, archivo propio: usuarios.db).

El correo es la identidad y NO se puede repetir: lo garantiza la base misma con UNIQUE
(y COLLATE NOCASE: "Ana@Duoc.cl" y "ana@duoc.cl" son el mismo usuario). Aunque dos
registros con el mismo correo lleguen al mismo tiempo, la base rechaza el segundo.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ROLES = ("cliente", "corredor")
_lock = threading.Lock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    correo  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nombre  TEXT NOT NULL,
    hash    TEXT NOT NULL,
    rol     TEXT NOT NULL DEFAULT 'cliente' CHECK (rol IN ('cliente', 'corredor')),
    creado  TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class Usuario:
    id: int
    correo: str
    nombre: str
    rol: str
    hash: str = ""

    def publico(self) -> dict:
        return {"id": self.id, "correo": self.correo, "nombre": self.nombre, "rol": self.rol}


def ruta_base() -> Path:
    return Path(os.getenv("USUARIOS_DB", str(RAIZ / "data" / "usuarios.db")))


def _conectar() -> sqlite3.Connection:
    ruta = ruta_base()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta, timeout=10)
    conexion.execute(ESQUEMA)
    return conexion


@contextmanager
def _sesion():
    """Una conexión por operación: se confirma (commit) y se cierra siempre."""
    with _lock:
        conexion = _conectar()
        try:
            with conexion:
                yield conexion
        finally:
            conexion.close()


def _fila(f) -> Usuario | None:
    return Usuario(id=f[0], correo=f[1], nombre=f[2], rol=f[4], hash=f[3]) if f else None


def crear(correo: str, nombre: str, hash_: str, rol: str = "cliente") -> Usuario | None:
    """El usuario creado, o None si el correo ya existe (lo rechaza la restricción UNIQUE)."""
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _sesion() as c:
        try:
            cursor = c.execute(
                "INSERT INTO usuarios (correo, nombre, hash, rol, creado) VALUES (?, ?, ?, ?, ?)",
                (correo, nombre, hash_, rol, ahora),
            )
        except sqlite3.IntegrityError:
            return None
        return Usuario(id=cursor.lastrowid, correo=correo, nombre=nombre, rol=rol, hash=hash_)


def por_correo(correo: str) -> Usuario | None:
    with _sesion() as c:
        return _fila(c.execute("SELECT id, correo, nombre, hash, rol FROM usuarios WHERE correo = ?",
                               (correo,)).fetchone())


def por_id(usuario_id: int) -> Usuario | None:
    with _sesion() as c:
        return _fila(c.execute("SELECT id, correo, nombre, hash, rol FROM usuarios WHERE id = ?",
                               (usuario_id,)).fetchone())


def asegurar_corredor(correo: str, nombre: str, hash_: str) -> None:
    """Crea (o actualiza) la cuenta del corredor que administra la demo."""
    with _sesion() as c:
        c.execute(
            "INSERT INTO usuarios (correo, nombre, hash, rol, creado) VALUES (?, ?, ?, 'corredor', ?) "
            "ON CONFLICT(correo) DO UPDATE SET hash = excluded.hash, rol = 'corredor'",
            (correo, nombre, hash_, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def contar() -> int:
    with _sesion() as c:
        return c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
