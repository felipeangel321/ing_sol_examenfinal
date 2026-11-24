"""API con el mismo formato que el deploy del curso (`deploy/backend/app.py`, RA3 / IL3.5).

Mismas rutas, campos y códigos que la app de referencia, para que la guía de despliegue
del curso (pasos 8 y 9) y sus pruebas funcionen igual contra este proyecto:

  GET  /api/health    {"status": "ok", "modo_demo": false}
  POST /api/chat      {"mensaje", "historial"?}  →  {"respuesta", "bloqueado", "motivo"}
                      un ataque responde 200 con "bloqueado": true y el motivo;
                      pasarse del límite por minuto (o del tope diario) responde 429.
  GET  /api/metrics   {"total_requests", "bloqueados", "errores"}: solo números.

Campos extra, opcionales: "seguro" (por defecto vehiculo) y "conversacion" (para seguir
una conversación; la respuesta trae su id).

Diferencia a propósito con el curso: el historial que manda el cliente se valida (cada
turno, el tamaño total y todo unido con el mensaje), pero no se le pasa al modelo. La
memoria vive en el servidor (SQLite) y el cliente solo manda el id de la conversación.
Así un turno "assistant" inventado (self-priming) no llega al modelo: es el hueco que el
propio deploy del curso deja anotado en su HistorialItem.

Pasa por el mismo camino que el chat del frontend (`Asistente.responder`): filtros,
bóveda, agente, redacción de la salida y traza. Lo que se bloquea aquí también se ve en
el panel.
"""
from __future__ import annotations

import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.catalogo import Catalogo, obtener_catalogo
from backend.config import hay_groq
from backend.endpoints.seguros import _ficha, _validar_id, obtener_asistente, revisar_limites
from backend.seguridad.acceso import es_dueno
from backend.seguridad.guardrails import LARGO_MAXIMO
from backend.servicio import Asistente

router = APIRouter(prefix="/api", tags=["api del curso"])

MAX_HISTORIAL_ITEMS = 20
CORREDOR = os.getenv("API_CORREDOR", "demo")
SEGURO = os.getenv("API_SEGURO", "vehiculo")

MOTIVOS = {
    "vacia": "Mensaje vacío.",
    "muy_larga": "El mensaje o la conversación supera el largo permitido.",
    "injection": "Posible prompt injection.",
    "fraude": "Pide ayuda para un fraude al seguro.",
    "datos_terceros": "Pide datos personales de otra persona.",
    "fuga_instrucciones": "La respuesta filtraba las instrucciones del sistema.",  # texto del curso
}
DONDE = {"historial": "Historial inválido", "conversacion": "Conversación completa"}
ERROR = "Ocurrió un error procesando tu solicitud."  # mismo texto que el deploy del curso


class HistorialItem(BaseModel):
    # Solo turnos de usuario o asistente: el cliente no puede mandar un turno "system".
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=LARGO_MAXIMO)


class ChatRequest(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=LARGO_MAXIMO)
    historial: list[HistorialItem] = Field(default_factory=list, max_length=MAX_HISTORIAL_ITEMS)
    seguro: str | None = Field(None, description=f"por defecto {SEGURO}")
    conversacion: str | None = Field(None, description="vacío para empezar una conversación nueva")


class ChatResponse(BaseModel):
    respuesta: str
    bloqueado: bool = False
    motivo: str | None = None
    conversacion: str | None = None


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "modo_demo": not hay_groq()}


@router.get("/metrics")
def metrics(asistente: Asistente = Depends(obtener_asistente)) -> dict[str, int]:
    # Público a propósito, como en el curso: solo tres contadores, ninguna pregunta ni
    # respuesta. El panel con el detalle es /panel.html.
    return asistente.contadores()


@router.post("/chat", response_model=ChatResponse)
def chat(
    cuerpo: ChatRequest,
    request: Request,
    catalogo: Catalogo = Depends(obtener_catalogo),
    asistente: Asistente = Depends(obtener_asistente),
):
    ficha = _ficha(CORREDOR, cuerpo.seguro or SEGURO, catalogo)
    conversacion = _validar_id(cuerpo.conversacion) if cuerpo.conversacion else uuid.uuid4().hex
    ip = request.client.host if request.client else "desconocida"
    try:
        r = asistente.responder(ficha, conversacion, cuerpo.mensaje, clave_limite=ip,
                                historial=[t.content for t in cuerpo.historial],
                                dueno=es_dueno(request))
    except Exception:  # el detalle queda en la traza; al cliente, un texto genérico
        return ChatResponse(respuesta=ERROR, conversacion=conversacion)
    revisar_limites(r)
    if r.estado == "bloqueado":
        motivo = MOTIVOS.get(r.categoria, r.categoria)
        if r.donde in DONDE:
            motivo = f"{DONDE[r.donde]}: {motivo}"
        return ChatResponse(respuesta=r.texto, bloqueado=True, motivo=motivo, conversacion=conversacion)
    return ChatResponse(respuesta=r.texto, conversacion=conversacion)
