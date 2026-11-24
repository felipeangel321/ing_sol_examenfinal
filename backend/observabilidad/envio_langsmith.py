"""LangSmith (opcional): ver en smith.langchain.com qué hace cada usuario con el agente.

Se enciende con LANGSMITH_TRACING=true y LANGSMITH_API_KEY en el .env (como en el curso,
RA1/IL1.4 y RA3/IL3.1). Sin eso no se envía nada y todo funciona igual: las trazas
propias (.trazas/ y el panel) no dependen de LangSmith.

Qué llega a LangSmith:
- Cada pregunta que pasa los filtros: LangChain traza solo la corrida del agente (modelo,
  herramientas, tokens, tiempo). Se le agregan metadatos para filtrar: usuario (correo
  de la cuenta), seguro, conversación y el trace_id de la traza propia.
- Cada pregunta BLOQUEADA por un filtro (injection, fraude, datos de terceros, fuga de
  instrucciones...): no llega al agente, así que se registra aparte como una corrida
  "bloqueada", con la categoría. Así se ve quién intentó atacar y cómo.
- Los rechazos por límite o cupo (429) NO se envían: bajo una inundación serían miles de
  llamadas a un servicio externo; esos ya se cuentan en el panel.

Privacidad: a LangSmith va la pregunta CON MARCADORES ([RUT_1], [CORREO_1]...), nunca los
datos personales reales del cliente. El correo de la cuenta sí va, como metadato.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("uvicorn.error")

NO_SE_ENVIAN = {"limite_tasa", "tope_diario", "cupo_ip", "espera_publico"}


def activo() -> bool:
    encendido = os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"
    return encendido and bool(os.getenv("LANGSMITH_API_KEY", "").strip())


def metadatos(ficha, thread_id: str, trace_id: str, quien: str | None) -> dict:
    return {
        "usuario": quien or "sin sesión",
        "corredor": ficha.corredor,
        "seguro": ficha.seguro,
        "conversacion": thread_id,
        "trace_id": trace_id,
    }


def registrar_bloqueo(pregunta_segura: str, categoria: str, donde: str, respuesta: str, datos: dict) -> None:
    """Una corrida "bloqueada" en LangSmith. Nunca rompe el chat si LangSmith falla."""
    if not activo() or categoria in NO_SE_ENVIAN:
        return
    try:
        from langsmith import trace

        with trace(name="pregunta bloqueada", run_type="chain", inputs={"pregunta": pregunta_segura},
                   tags=["bloqueado", categoria, datos.get("seguro", "")],
                   metadata={**datos, "categoria": categoria, "donde": donde or "mensaje"}) as corrida:
            corrida.end(outputs={"respuesta": respuesta, "categoria": categoria})
    except Exception as error:  # LangSmith caído o clave inválida: el chat sigue
        log.warning("No se pudo enviar el bloqueo a LangSmith: %s", type(error).__name__)
