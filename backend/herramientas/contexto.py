"""Datos que el servidor entrega a cada herramienta."""
from __future__ import annotations

from dataclasses import dataclass

from backend.catalogo import Ficha
from backend.seguridad.boveda import Boveda


@dataclass(frozen=True)
class Contexto:
    """Corredor, seguro y conversación.

    Lo fija el servidor según la URL y el modelo no puede cambiarlo. Por eso un
    agente no puede consultar documentos ni solicitudes de otro corredor, aunque
    un mensaje intente convencerlo.

    boveda: guarda los datos personales reales de la conversación. El modelo solo
    ve marcadores ([RUT_1]); las herramientas que escriben los cambian por el dato
    real justo antes de guardarlo.
    """

    ficha: Ficha
    thread_id: str = ""
    boveda: Boveda | None = None

    def revelar(self, texto: str) -> str:
        return self.boveda.revelar(self.thread_id, texto) if self.boveda else texto
