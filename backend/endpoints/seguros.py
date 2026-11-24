"""Endpoints del frontend de clientes: lista de seguros, chat y estado de la conversación."""
from __future__ import annotations

import re
import uuid
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.catalogo import Catalogo, Ficha, obtener_catalogo
from backend.seguridad.acceso import es_dueno
from backend.seguridad.sesion import clave_de, es_corredor, exigir_usuario
from backend.servicio import Asistente, Respuesta

router = APIRouter(prefix="/corredores/{corredor}/seguros", tags=["clientes"])

# El id de la conversación lo crea el servidor (uuid, imposible de adivinar). Con él se
# recupera el caso, que trae datos del cliente: funciona como la llave de la conversación.
_ID_CONVERSACION = re.compile(r"[A-Za-z0-9_-]{8,64}")


@lru_cache
def obtener_asistente() -> Asistente:
    """Un solo Asistente para toda la API, con la memoria en data/."""
    return Asistente.persistente()


# Superar el límite por minuto o el tope diario responde 429 (Too Many Requests), como
# el deploy del curso. La pregunta igual queda en la traza y cuenta como bloqueada.
LIMITES = {"limite_tasa", "tope_diario", "cupo_ip", "espera_publico"}


def revisar_limites(r: Respuesta) -> None:
    if r.categoria in LIMITES:
        raise HTTPException(status_code=429, detail=r.texto)


class SeguroResumen(BaseModel):
    id: str
    nombre: str
    descripcion: str


class MensajeChat(BaseModel):
    mensaje: str = Field(..., min_length=1, max_length=2000)
    conversacion: str | None = Field(None, description="vacío para empezar una conversación nueva")


class RespuestaChat(BaseModel):
    respuesta: str
    conversacion: str
    trace_id: str
    estado: str  # ok | bloqueado
    categoria: str  # motivo del bloqueo
    etapa: str
    numero: str  # última solicitud registrada, si hay
    duracion_s: float
    tokens: int


class EstadoConversacion(BaseModel):
    conversacion: str
    etapa: str
    numero: str
    derivacion: str
    mensajes: list[dict[str, str]]


def _seguros_del_corredor(corredor: str, catalogo: Catalogo) -> dict[str, Ficha]:
    if corredor not in catalogo:
        raise HTTPException(status_code=404, detail="Corredor no encontrado")
    return catalogo[corredor]


def _ficha(corredor: str, seguro: str, catalogo: Catalogo) -> Ficha:
    seguros = _seguros_del_corredor(corredor, catalogo)
    if seguro not in seguros:
        raise HTTPException(status_code=404, detail="Seguro no encontrado")
    return seguros[seguro]


def _validar_id(conversacion: str) -> str:
    if not _ID_CONVERSACION.fullmatch(conversacion):
        raise HTTPException(status_code=422, detail="Id de conversación no válido")
    return conversacion


@router.get("", response_model=list[SeguroResumen])
def listar_seguros(corredor: str, catalogo: Catalogo = Depends(obtener_catalogo)):
    return [
        SeguroResumen(id=ficha.seguro, nombre=ficha.nombre, descripcion=ficha.descripcion)
        for ficha in _seguros_del_corredor(corredor, catalogo).values()
    ]


@router.post("/{seguro}/chat", response_model=RespuestaChat)
def chatear(
    corredor: str,
    seguro: str,
    cuerpo: MensajeChat,
    request: Request,
    catalogo: Catalogo = Depends(obtener_catalogo),
    asistente: Asistente = Depends(obtener_asistente),
    usuario: dict | None = Depends(exigir_usuario),
):
    # Función normal (no async): FastAPI la corre en otro hilo y el agente no bloquea al resto.
    ficha = _ficha(corredor, seguro, catalogo)
    conversacion = _validar_id(cuerpo.conversacion) if cuerpo.conversacion else uuid.uuid4().hex
    # El límite por minuto se cuenta por IP: abrir conversaciones nuevas no lo evita.
    ip = request.client.host if request.client else "desconocida"
    try:
        r = asistente.responder(ficha, conversacion, cuerpo.mensaje, clave_limite=clave_de(usuario, ip),
                                dueno=es_dueno(request) or es_corredor(usuario),
                                usuario=usuario["correo"] if usuario else None)
    except Exception as error:  # Groq caído o cuota agotada tras los reintentos
        raise HTTPException(
            status_code=503,
            detail="El asistente no está disponible en este momento. Intenta de nuevo en un minuto.",
        ) from error
    revisar_limites(r)
    caso =asistente.estado_caso(ficha, conversacion)  # también si la pregunta se bloqueó
    return RespuestaChat(
        respuesta=r.texto,
        conversacion=conversacion,
        trace_id=r.trace_id,
        estado=r.estado,
        categoria=r.categoria,
        etapa=caso["etapa"],
        numero=caso["numero"],
        duracion_s=round(r.duracion_ms / 1000, 2),
        tokens=r.tokens_entrada + r.tokens_salida,
    )


@router.get("/{seguro}/conversaciones/{conversacion}", response_model=EstadoConversacion)
def ver_conversacion(
    corredor: str,
    seguro: str,
    conversacion: str,
    catalogo: Catalogo = Depends(obtener_catalogo),
    asistente: Asistente = Depends(obtener_asistente),
    _usuario: dict | None = Depends(exigir_usuario),
):
    """Para retomar la conversación al recargar la página."""
    ficha = _ficha(corredor, seguro, catalogo)
    caso = asistente.estado_caso(ficha, _validar_id(conversacion))
    return EstadoConversacion(
        conversacion=conversacion,
        etapa=caso["etapa"],
        numero=caso["numero"],
        derivacion=caso["derivacion"],
        mensajes=asistente.historial(ficha, conversacion),
    )
