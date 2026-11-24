"""Memoria del caso y planificación por etapas.

Además de los mensajes, cada conversación guarda un estado estructurado (el "caso"):

  etapa      consulta → recopilando → confirmando → registrada
  borrador   datos de la solicitud ya revisados (con marcadores, nunca datos reales)
  numero     última solicitud registrada (SOL-...) o derivación (DER-...)

Este estado lo guarda el checkpointer junto con los mensajes, así que sobrevive a un
reinicio y no se pierde cuando se recorta el historial para cuidar los tokens.

Antes de cada llamada al modelo, EtapasMiddleware:
  1. Le agrega al prompt el estado del caso y el próximo paso (el plan).
  2. Le ofrece solo las herramientas de esa etapa: registrar_solicitud aparece
     únicamente cuando hay un borrador completo.

  ┌──────────┐ quiere cotizar ┌─────────────┐ datos completos ┌─────────────┐ "sí" ┌────────────┐
  │ consulta │ ─────────────▶ │ recopilando │ ──────────────▶ │ confirmando │ ───▶ │ registrada │
  └──────────┘                └─────────────┘ ◀────────────── └─────────────┘      └────────────┘
                                               el cliente corrige

La confirmación del cliente no queda en manos del modelo: registrar_solicitud revisa en
código que el cliente haya respondido DESPUÉS de ver el resumen y que su respuesta sea un sí.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import OmitFromInput
from langchain_core.messages import HumanMessage, SystemMessage
from typing_extensions import NotRequired

from backend.catalogo import Ficha

Etapa = Literal["consulta", "recopilando", "confirmando", "registrada"]
ETAPAS: tuple[Etapa, ...] = ("consulta", "recopilando", "confirmando", "registrada")

# Herramientas que solo se ofrecen en ciertas etapas.
HERRAMIENTAS_POR_ETAPA = {"registrar_solicitud": {"confirmando"}}


class EstadoCaso(AgentState):
    etapa: Annotated[NotRequired[str], OmitFromInput]
    borrador: Annotated[NotRequired[dict[str, str]], OmitFromInput]
    # Mensajes del cliente cuando se armó el borrador: confirmar exige uno posterior.
    borrador_turno: Annotated[NotRequired[int], OmitFromInput]
    numero: Annotated[NotRequired[str], OmitFromInput]
    derivacion: Annotated[NotRequired[str], OmitFromInput]


def etapa_de(estado: dict[str, Any]) -> str:
    return estado.get("etapa") or "consulta"


def mensajes_del_cliente(estado: dict[str, Any]) -> list[str]:
    return [str(m.content) for m in estado.get("messages", []) if isinstance(m, HumanMessage)]


# --- ¿El cliente confirmó? -------------------------------------------------------------

_SI = re.compile(
    r"^\W*(s[ií]+|sip|ok(ey|ay)?|dale|correcto|confirm[oa]|de acuerdo|perfecto|exacto|"
    r"as[ií] es|todo (bien|ok|correcto)|est[aá] (todo )?(bien|correcto)|adelante|regístr|registr|listo)\b",
    re.IGNORECASE,
)
_PERO = re.compile(
    r"\b(pero|aunque|cambi|corrig|correcci|modific|no es|no son|no está|no esta|mal|error|"
    r"equivoc|falta|en vez|en lugar|espera)",
    re.IGNORECASE,
)


def es_confirmacion(texto: str) -> bool:
    """Un "sí" claro y sin correcciones ("sí, pero el correo es otro" NO confirma)."""
    return bool(_SI.search(texto)) and not _PERO.search(texto)


def puede_registrar(estado: dict[str, Any]) -> str | None:
    """None si se puede registrar; si no, el motivo (para el agente)."""
    if etapa_de(estado) != "confirmando" or not estado.get("borrador"):
        return "Aún no hay un borrador completo: anota los datos con preparar_solicitud."
    cliente = mensajes_del_cliente(estado)
    if len(cliente) <= estado.get("borrador_turno", 0):
        return ("El cliente todavía no ha visto el resumen. Muéstraselo y espera a que "
                "responda antes de registrar.")
    if not es_confirmacion(cliente[-1]):
        return ("El último mensaje del cliente no es una confirmación clara. Si corrigió "
                "algo, usa preparar_solicitud con el cambio y vuelve a mostrar el resumen; "
                "si tienes dudas, pregúntale si confirma.")
    return None


# --- Plan: qué le toca hacer al agente según la etapa ----------------------------------

def plan_del_caso(ficha: Ficha, estado: dict[str, Any]) -> str:
    etapa = etapa_de(estado)
    borrador = estado.get("borrador", {})
    lineas = [f"Estado del caso (lo lleva el sistema): etapa {etapa}."]
    if etapa == "consulta":
        lineas.append("Próximo paso: resolver dudas con buscar_documentos. Si el cliente "
                      "quiere cotizar o contratar, usa ver_campos_solicitud.")
    elif etapa in ("recopilando", "confirmando"):
        etiquetas = {c.id: c.etiqueta for c in ficha.campos_solicitud}
        anotados = ", ".join(f"{etiquetas.get(k, k)}={v}" for k, v in borrador.items()) or "ninguno"
        lineas.append(f"Datos anotados: {anotados}.")
        if etapa == "recopilando":
            faltan = [c.etiqueta for c in ficha.campos_solicitud if c.obligatorio and c.id not in borrador]
            opcionales = [c.etiqueta for c in ficha.campos_solicitud if not c.obligatorio and c.id not in borrador]
            if faltan:
                lineas.append(f"Faltan (obligatorios): {', '.join(faltan)}.")
            if opcionales:
                lineas.append(f"Opcionales (pregúntalos una vez, no los exijas): {', '.join(opcionales)}.")
            lineas.append("Próximo paso: pide lo que falta. Cada vez que el cliente entregue "
                          "datos, anótalos con preparar_solicitud (solo los nuevos o corregidos).")
        else:
            lineas.append("Próximo paso: el cliente debe confirmar el resumen. Si confirma sin "
                          "cambios, usa registrar_solicitud. Si corrige algo, usa "
                          "preparar_solicitud con el cambio y muestra el resumen de nuevo.")
    elif etapa == "registrada":
        lineas.append(f"Solicitud registrada: {estado.get('numero', '')}. Próximo paso: resolver "
                      "dudas. Si quiere otra solicitud, empieza con ver_campos_solicitud.")
    if estado.get("derivacion"):
        lineas.append(f"Ya se derivó a una persona ({estado['derivacion']}): no lo derives de nuevo "
                      "por el mismo motivo.")
    return "\n".join(lineas)


def _nombre(herramienta: Any) -> str:
    return herramienta.get("name", "") if isinstance(herramienta, dict) else getattr(herramienta, "name", "")


class EtapasMiddleware(AgentMiddleware):
    """Pone el plan del caso en el prompt y ofrece solo las herramientas de la etapa."""

    state_schema = EstadoCaso

    def __init__(self, ficha: Ficha) -> None:
        super().__init__()
        self.ficha = ficha

    def wrap_model_call(self, request, handler):
        etapa = etapa_de(request.state)
        herramientas = [
            h for h in request.tools
            if etapa in HERRAMIENTAS_POR_ETAPA.get(_nombre(h), {etapa})
        ]
        base = request.system_message.text if request.system_message else ""
        sistema = SystemMessage(f"{base}\n\n{plan_del_caso(self.ficha, request.state)}")
        return handler(request.override(system_message=sistema, tools=herramientas))
