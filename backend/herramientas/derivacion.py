"""Traspaso de la conversación a una persona del corredor."""
from __future__ import annotations

from backend import almacen
from backend.herramientas.contexto import Contexto

URGENCIAS = ("normal", "alta")


def derivar_a_persona(contexto: Contexto, motivo: str, urgencia: str = "normal", contacto: str = "") -> str:
    """Deja un aviso en la bandeja del corredor y devuelve su número.

    Simulado: el corredor aún no define el canal (correo, WhatsApp, CRM). La
    conversación completa se puede revisar con el thread_id en las trazas.
    """
    urgencia = urgencia if urgencia in URGENCIAS else "normal"
    return almacen.guardar_derivacion(
        contexto.ficha.corredor,
        contexto.ficha.seguro,
        contexto.thread_id,
        motivo.strip()[:500],
        urgencia,
        contexto.revelar(contacto.strip())[:200],
    )
