"""Los datos personales del cliente no llegan al modelo (seudonimización).

Antes de enviar la pregunta a Groq, cada RUT, correo, teléfono o patente se cambia por
un marcador ([RUT_1], [CORREO_1]...). El valor real queda en el servidor, en la bóveda
de esa conversación. Cuando el agente responde con el marcador, se le muestra al cliente
el valor real. Así el proveedor del modelo nunca recibe esos datos.

Excepción: los números de tarjeta NO se guardan. Se borran para siempre ([TARJETA_REDACTADO]):
este chat no los necesita y no debe almacenarlos.

Dónde vive:
  - Boveda()             en memoria (pruebas): se pierde al reiniciar.
  - Boveda(ruta=...)     en SQLite (data/boveda.db, fuera de git): sobrevive al reinicio,
                         igual que la conversación.

Como la memoria de la conversación solo guarda marcadores, la bóveda es el ÚNICO lugar con
los datos reales de una conversación. purgar(dias) la borra pasado el plazo de retención:
desde ahí la conversación queda anónima (las solicitudes registradas siguen en la bandeja).
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from backend.seguridad.guardrails import buscar_pii

_MARCADOR = re.compile(r"\[(RUT|CORREO|TELEFONO|PATENTE)_(\d+)\]")
NO_SE_GUARDAN = {"TARJETA"}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS boveda (
    thread_id TEXT NOT NULL,
    marcador  TEXT NOT NULL,
    valor     TEXT NOT NULL,
    creada    TEXT NOT NULL,
    PRIMARY KEY (thread_id, marcador)
)
"""


class Boveda:
    def __init__(self, ruta: Path | None = None) -> None:
        self._por_hilo: dict[str, dict[str, str]] = {}  # caché: marcador -> valor
        self._ruta = ruta
        self._lock = Lock()
        if ruta:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._conectar()) as conexion, conexion:
                conexion.execute(_ESQUEMA)

    def _conectar(self) -> sqlite3.Connection:
        return sqlite3.connect(self._ruta)

    def _valores(self, thread_id: str) -> dict[str, str]:
        """Marcadores de la conversación (se leen de la base la primera vez). Llamar con el lock."""
        if thread_id not in self._por_hilo:
            valores: dict[str, str] = {}
            if self._ruta:
                with closing(self._conectar()) as conexion:
                    filas = conexion.execute(
                        "SELECT marcador, valor FROM boveda WHERE thread_id = ?", (thread_id,)
                    ).fetchall()
                valores = dict(filas)
            self._por_hilo[thread_id] = valores
        return self._por_hilo[thread_id]

    def seudonimizar(self, thread_id: str, texto: str) -> str:
        with self._lock:
            valores = self._valores(thread_id)
            inverso = {v: k for k, v in valores.items()}
            nuevos: list[tuple[str, str]] = []
            for tipo, valor in buscar_pii(texto):
                if tipo in NO_SE_GUARDAN:
                    texto = texto.replace(valor, f"[{tipo}_REDACTADO]")
                    continue
                marcador = inverso.get(valor)
                if marcador is None:
                    n = sum(1 for m in valores if m.startswith(f"[{tipo}_")) + 1
                    marcador = f"[{tipo}_{n}]"
                    valores[marcador] = inverso[valor] = valor
                    nuevos.append((marcador, valor))
                texto = texto.replace(valor, marcador)
            if nuevos and self._ruta:
                ahora = datetime.now().isoformat(timespec="seconds")
                with closing(self._conectar()) as conexion, conexion:
                    conexion.executemany(
                        "INSERT OR IGNORE INTO boveda VALUES (?, ?, ?, ?)",
                        [(thread_id, m, v, ahora) for m, v in nuevos],
                    )
        return texto

    def revelar(self, thread_id: str, texto: str) -> str:
        with self._lock:
            valores = self._valores(thread_id)
        return _MARCADOR.sub(lambda m: valores.get(m.group(0), m.group(0)), texto)

    def olvidar(self, thread_id: str) -> None:
        with self._lock:
            self._por_hilo.pop(thread_id, None)
            if self._ruta:
                with closing(self._conectar()) as conexion, conexion:
                    conexion.execute("DELETE FROM boveda WHERE thread_id = ?", (thread_id,))

    def purgar(self, dias: int, ahora: datetime | None = None) -> int:
        """Borra las conversaciones cuyo primer dato tiene más de `dias`. Devuelve cuántas."""
        if not self._ruta:
            return 0
        limite = ((ahora or datetime.now()) - timedelta(days=dias)).isoformat(timespec="seconds")
        with self._lock, closing(self._conectar()) as conexion, conexion:
            viejas = [f[0] for f in conexion.execute(
                "SELECT thread_id FROM boveda GROUP BY thread_id HAVING MIN(creada) < ?", (limite,)
            )]
            conexion.executemany("DELETE FROM boveda WHERE thread_id = ?", [(h,) for h in viejas])
            for hilo in viejas:
                self._por_hilo.pop(hilo, None)
        return len(viejas)
