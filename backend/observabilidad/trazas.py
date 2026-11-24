"""Trazas de cada pregunta al agente, guardadas en JSON (una línea por pregunta).

Sigue la idea de RA3 del curso:
  - trace_id  = una pregunta del cliente (una petición).
  - thread_id = la conversación completa (varias trazas comparten el mismo thread_id).
  - spans     = las etapas de esa pregunta: cada llamada al modelo y cada herramienta,
                con su duración, tokens y si terminó bien o con error.

Uso:
    with iniciar_traza(thread_id, ficha, pregunta) as traza:
        resultado = agente.invoke(...)
        traza.respuesta = ...

El middleware ObservadorMiddleware (que va dentro del agente) agrega los spans
a la traza activa sin que el resto del código tenga que pasarla de mano en mano.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from backend.config import RAIZ

TRAZAS_DIR = RAIZ / ".trazas"

_traza_actual: ContextVar["Traza | None"] = ContextVar("traza_actual", default=None)


def _ahora_ms() -> float:
    return time.perf_counter() * 1000


@dataclass
class Span:
    """Una etapa de la pregunta: una llamada al modelo o una herramienta."""

    etapa: str  # "modelo" | "herramienta" | "validacion_entrada" | ...
    nombre: str
    inicio_ms: float  # desde el inicio de la traza
    duracion_ms: float = 0.0
    estado: str = "ok"  # "ok" | "error" | "bloqueado"
    tokens_entrada: int = 0
    tokens_salida: int = 0
    detalle: dict[str, Any] = field(default_factory=dict)


@dataclass
class Traza:
    trace_id: str
    thread_id: str
    corredor: str
    seguro: str
    fecha: str
    pregunta: str
    respuesta: str = ""
    estado: str = "ok"
    error: str = ""
    etapa: str = ""  # etapa del caso al terminar la pregunta (consulta, recopilando...)
    duracion_ms: float = 0.0
    spans: list[Span] = field(default_factory=list)
    _inicio: float = field(default_factory=_ahora_ms, repr=False)

    def nuevo_span(self, etapa: str, nombre: str) -> Span:
        span = Span(etapa=etapa, nombre=nombre, inicio_ms=round(_ahora_ms() - self._inicio, 1))
        self.spans.append(span)
        return span

    @property
    def tokens_entrada(self) -> int:
        return sum(s.tokens_entrada for s in self.spans)

    @property
    def tokens_salida(self) -> int:
        return sum(s.tokens_salida for s in self.spans)

    def a_dict(self) -> dict[str, Any]:
        datos = asdict(self)
        datos.pop("_inicio")
        datos["tokens_entrada"] = self.tokens_entrada
        datos["tokens_salida"] = self.tokens_salida
        datos["llamadas_modelo"] = sum(1 for s in self.spans if s.etapa == "modelo")
        datos["herramientas"] = [s.nombre for s in self.spans if s.etapa == "herramienta"]
        return datos


def traza_actual() -> Traza | None:
    return _traza_actual.get()


def anotar_span_actual(**detalle: Any) -> None:
    """Agrega datos al span que está corriendo (por ejemplo, desde una herramienta)."""
    traza = traza_actual()
    if traza and traza.spans:
        traza.spans[-1].detalle.update(detalle)


@contextmanager
def iniciar_traza(thread_id: str, ficha, pregunta: str, carpeta: Path | None = None):
    """Abre una traza para una pregunta y la guarda al terminar, aunque falle."""
    traza = Traza(
        trace_id=uuid.uuid4().hex[:12],
        thread_id=thread_id,
        corredor=ficha.corredor,
        seguro=ficha.seguro,
        fecha=datetime.now().isoformat(timespec="seconds"),
        pregunta=pregunta,
    )
    token = _traza_actual.set(traza)
    try:
        yield traza
    except Exception as error:
        traza.estado = "error"
        traza.error = f"{type(error).__name__}: {error}"[:500]
        raise
    finally:
        traza.duracion_ms = round(_ahora_ms() - traza._inicio, 1)
        _traza_actual.reset(token)
        guardar_traza(traza, carpeta)


def guardar_traza(traza: Traza, carpeta: Path | None = None) -> Path:
    carpeta = carpeta or TRAZAS_DIR
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"{traza.fecha[:10]}.jsonl"
    with archivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps(traza.a_dict(), ensure_ascii=False) + "\n")
    return archivo


def leer_trazas(carpeta: Path | None = None) -> list[dict[str, Any]]:
    carpeta = carpeta or TRAZAS_DIR
    trazas = []
    for archivo in sorted(carpeta.glob("*.jsonl")):
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                trazas.append(json.loads(linea))
    return trazas


def _uso_de_tokens(mensaje: AIMessage) -> tuple[int, int]:
    uso = getattr(mensaje, "usage_metadata", None) or {}
    return int(uso.get("input_tokens", 0)), int(uso.get("output_tokens", 0))


class ObservadorMiddleware(AgentMiddleware):
    """Registra cada llamada al modelo y cada herramienta como un span de la traza activa.

    Va DESPUÉS de ModelRetryMiddleware en la lista, así cada reintento (429 de cuota,
    400 tool_use_failed) queda como un span con error y se ve en la traza.
    """

    def wrap_model_call(self, request, handler):
        traza = traza_actual()
        if traza is None:
            return handler(request)
        span = traza.nuevo_span("modelo", "llm")
        # En qué etapa del caso decidió el modelo (ver backend/agentes/etapas.py).
        if etapa := (request.state or {}).get("etapa"):
            span.detalle["etapa"] = etapa
        inicio = _ahora_ms()
        try:
            respuesta = handler(request)
        except Exception as error:
            span.estado = "error"
            span.detalle["error"] = f"{type(error).__name__}: {error}"[:300]
            raise
        finally:
            span.duracion_ms = round(_ahora_ms() - inicio, 1)
        mensajes = respuesta.result if hasattr(respuesta, "result") else [respuesta]
        for mensaje in mensajes:
            if isinstance(mensaje, AIMessage):
                span.tokens_entrada, span.tokens_salida = _uso_de_tokens(mensaje)
                pedidas = [llamada["name"] for llamada in mensaje.tool_calls]
                span.detalle["decision"] = f"usar {', '.join(pedidas)}" if pedidas else "responder"
        return respuesta

    def __init__(self, ocultar_argumentos: set[str] | frozenset[str] = frozenset()) -> None:
        super().__init__()
        # Herramientas cuyos argumentos son datos del cliente: se anota qué campos
        # llegaron, no sus valores (un nombre o una dirección no los detecta el regex).
        self.ocultar_argumentos = set(ocultar_argumentos)

    def wrap_tool_call(self, request, handler):
        traza = traza_actual()
        if traza is None:
            return handler(request)
        llamada = request.tool_call
        span = traza.nuevo_span("herramienta", llamada["name"])
        argumentos = llamada.get("args", {})
        if llamada["name"] in self.ocultar_argumentos:
            span.detalle["campos"] = sorted(
                k for k, v in argumentos.items() for k in (v.keys() if isinstance(v, dict) else [k])
            )
        else:
            span.detalle["argumentos"] = argumentos
        inicio = _ahora_ms()
        try:
            resultado = handler(request)
        except Exception as error:
            span.estado = "error"
            span.detalle["error"] = f"{type(error).__name__}: {error}"[:300]
            raise
        finally:
            span.duracion_ms = round(_ahora_ms() - inicio, 1)
        mensaje = resultado
        if isinstance(resultado, Command) and isinstance(resultado.update, dict):
            # La herramienta respondió y además cambió el estado del caso.
            mensaje = next((m for m in resultado.update.get("messages", []) if isinstance(m, ToolMessage)), None)
            if "etapa" in resultado.update:
                span.detalle["etapa_nueva"] = resultado.update["etapa"]
        if isinstance(mensaje, ToolMessage):
            texto = str(mensaje.content)
            span.detalle["caracteres_resultado"] = len(texto)
            if mensaje.status == "error":
                span.estado = "error"
                span.detalle["error"] = texto[:300]
        return resultado
