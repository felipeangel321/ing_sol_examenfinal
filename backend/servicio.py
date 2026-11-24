"""Un solo camino para responder: lo usan el chat de consola y la API.

Cada pregunta pasa por estas etapas, y todas quedan en la traza:

  1. validacion_entrada  límite por minuto + filtro (injection, fraude, datos de terceros)
                         + historial del cliente (solo /api/chat) + tope diario (solo en el
                         servidor). Si se bloquea, el modelo NO se llama.
  2. seudonimizacion     RUT, correo, teléfono y patente se cambian por marcadores:
                         el modelo nunca recibe esos datos.
  3. agente              modelo + herramientas (spans "modelo" y "herramienta").
  4. validacion_salida   si la respuesta trae datos personales sueltos, se redactan.
  5. Se devuelven al cliente sus propios datos en lugar de los marcadores.

La traza guarda la pregunta y la respuesta con marcadores, nunca los datos reales.

Memoria (Asistente.persistente()):
  data/conversaciones.db   mensajes + estado del caso (etapa, borrador), por conversación.
                           Solo tiene marcadores: ningún dato personal real.
  data/boveda.db           los datos reales detrás de los marcadores. Se borran a los
                           DIAS_RETENCION días y la conversación queda anónima.
Una conversación se puede retomar después de reiniciar el programa con el mismo thread_id.
"""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from backend.agentes.cliente import crear_agente, instrucciones_fijas, normalizar_citas
from backend.agentes.etapas import etapa_de
from backend.catalogo import Ficha
from backend.config import RAIZ
from backend.herramientas.contexto import Contexto
from backend.observabilidad import envio_langsmith, iniciar_traza, leer_trazas
from backend.seguridad import (
    MENSAJES,
    Boveda,
    LimitadorTasa,
    redactar_pii,
    validar_entrada,
    validar_historial,
)
from backend.seguridad.acceso import clave_configurada
from backend.seguridad.cupos import Cupos
from backend.seguridad.guardrails import buscar_pii, hay_fuga_de_instrucciones

MENSAJES_RECIENTES = 3  # para detectar un ataque partido en varios mensajes
MAX_CONVERSACIONES_EN_MEMORIA = 2000  # para esa revisión; las más antiguas se olvidan
DATOS_DIR = RAIZ / "data"  # no se sube a git
DIAS_RETENCION = 30  # después, la bóveda se borra y la conversación queda anónima
_TOPE_DE_LLAMADAS = "Model call limits exceeded"  # texto de ModelCallLimitMiddleware
SIN_RESPUESTA = (
    "No encontré una respuesta clara en los documentos para esta pregunta. Puedes "
    "reformularla con otras palabras o, si prefieres, te derivo con una persona de la corredora."
)


@dataclass(frozen=True)
class Respuesta:
    texto: str
    trace_id: str
    estado: str  # ok | bloqueado
    categoria: str  # motivo del bloqueo, vacío si estado == ok
    etapa: str  # etapa del caso al terminar (consulta, recopilando, confirmando, registrada)
    duracion_ms: float
    tokens_entrada: int
    tokens_salida: int
    donde: str = ""  # si se bloqueó: mensaje | conversacion | historial


class Asistente:
    def __init__(self, llm=None, checkpointer=None, limitador: LimitadorTasa | None = None,
                 carpeta_trazas: Path | None = None, boveda: Boveda | None = None,
                 tope_diario: int | None = None, cupos: Cupos | None = None) -> None:
        self._llm = llm
        self.checkpointer = checkpointer or InMemorySaver()
        self.limitador = limitador or LimitadorTasa()
        # Tope de preguntas que llegan al modelo en 24 h, sumando a todos los usuarios.
        # En un despliegue público protege la cuota diaria de Groq (200.000 tokens):
        # sin él, cualquiera con la URL la agota. None = sin tope (uso local).
        self.tope_diario = (
            LimitadorTasa(maximo=tope_diario, ventana_s=24 * 3600) if tope_diario else None
        )
        # Cupo del público y cupo reservado del dueño (cupos.py). None = sin cupos (local).
        self.cupos = cupos
        self.boveda = boveda or Boveda()
        self.carpeta_trazas = carpeta_trazas
        self._agentes: dict[tuple[str, str], object] = {}
        self._recientes: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=MENSAJES_RECIENTES))
        # Los tres números de /api/metrics (como el deploy del curso). Viven en memoria:
        # leer todas las trazas en cada consulta sería un blanco fácil para un ataque.
        self._contadores = {"total_requests": 0, "bloqueados": 0, "errores": 0}
        self._lock_contadores = Lock()

    def _contar(self, **sumas: int) -> None:
        with self._lock_contadores:
            for clave, n in sumas.items():
                self._contadores[clave] += n

    def contadores(self) -> dict[str, int]:
        with self._lock_contadores:
            return dict(self._contadores)

    @classmethod
    def persistente(cls, carpeta: Path = DATOS_DIR, **opciones) -> Asistente:
        """Memoria en SQLite: las conversaciones sobreviven a un reinicio."""
        carpeta.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: la API atiende cada pedido en otro hilo (SqliteSaver usa su propio lock).
        conexion = sqlite3.connect(carpeta / "conversaciones.db", check_same_thread=False)
        boveda = Boveda(ruta=carpeta / "boveda.db")
        boveda.purgar(DIAS_RETENCION)
        # En el servidor, docker-compose fija TOPE_DIARIO_PREGUNTAS; en local no hay tope.
        opciones.setdefault("tope_diario", int(os.getenv("TOPE_DIARIO_PREGUNTAS", "0") or 0) or None)
        # Con CLAVE_ACCESO (solo en el servidor) hay dueño, y con él, cupos separados.
        if clave_configurada():
            opciones.setdefault("cupos", Cupos.desde_entorno())
        asistente = cls(checkpointer=SqliteSaver(conexion), boveda=boveda, **opciones)
        # Los contadores parten desde las trazas guardadas: sobreviven a un reinicio.
        trazas = leer_trazas(asistente.carpeta_trazas)
        asistente._contar(
            total_requests=len(trazas),
            bloqueados=sum(t["estado"] == "bloqueado" for t in trazas),
            errores=sum(t["estado"] == "error" for t in trazas),
        )
        return asistente

    @staticmethod
    def _config(ficha: Ficha, thread_id: str) -> dict:
        # La memoria se separa por corredor y seguro: el mismo thread_id en otro seguro
        # empieza de cero y no ve el caso de este.
        return {"configurable": {"thread_id": f"{ficha.corredor}/{ficha.seguro}/{thread_id}"}}

    def estado_caso(self, ficha: Ficha, thread_id: str) -> dict[str, Any]:
        """Etapa, borrador (con los datos reales para mostrárselos al cliente) y mensajes guardados."""
        valores = self._agente(ficha).get_state(self._config(ficha, thread_id)).values
        return {
            "etapa": etapa_de(valores),
            "borrador": {k: self.boveda.revelar(thread_id, v) for k, v in valores.get("borrador", {}).items()},
            "numero": valores.get("numero", ""),
            "derivacion": valores.get("derivacion", ""),
            "mensajes": len(valores.get("messages", [])),
        }

    def historial(self, ficha: Ficha, thread_id: str) -> list[dict[str, str]]:
        """Mensajes del cliente y respuestas finales del agente (sin pasos internos), con
        los datos reales del cliente: es lo que el frontend muestra al recargar la página."""
        valores = self._agente(ficha).get_state(self._config(ficha, thread_id)).values
        mensajes = []
        for m in valores.get("messages", []):
            if isinstance(m, HumanMessage):
                rol = "cliente"
            elif isinstance(m, AIMessage) and not m.tool_calls and m.text:
                rol = "asistente"
            else:
                continue  # llamadas y resultados de herramientas
            texto = m.text if rol == "cliente" else redactar_pii(normalizar_citas(m.text))
            if rol == "asistente" and texto.startswith(_TOPE_DE_LLAMADAS):
                texto = SIN_RESPUESTA
            elif rol == "asistente" and hay_fuga_de_instrucciones(texto, instrucciones_fijas(ficha)):
                texto = MENSAJES["fuga_instrucciones"]  # tampoco se muestra al recargar
            mensajes.append({"rol": rol, "texto": self.boveda.revelar(thread_id, texto)})
        return mensajes

    def _recordar(self, thread_id: str, pregunta: str) -> None:
        self._recientes[thread_id].append(pregunta)
        # Un script que abre una conversación nueva en cada mensaje no llena la memoria:
        # se olvidan las más antiguas (el diccionario guarda el orden de llegada).
        while len(self._recientes) > MAX_CONVERSACIONES_EN_MEMORIA:
            del self._recientes[next(iter(self._recientes))]

    def _agente(self, ficha: Ficha):
        clave = (ficha.corredor, ficha.seguro)
        if clave not in self._agentes:
            self._agentes[clave] = crear_agente(ficha, llm=self._llm, checkpointer=self.checkpointer)
        return self._agentes[clave]

    def responder(self, ficha: Ficha, thread_id: str, pregunta: str, clave_limite: str | None = None,
                  historial: list[str] | None = None, dueno: bool = False,
                  usuario: str | None = None) -> Respuesta:
        """clave_limite: a quién se le cuenta el límite por minuto y el cupo (la IP en la API).

        dueno: la pregunta viene del navegador del dueño (cookie del link secreto): usa su
        cupo reservado y su propio límite por minuto, aunque comparta IP con el público.

        usuario: correo de la cuenta (microservicio de usuarios), solo como metadato para
        LangSmith (observabilidad/envio_langsmith.py).

        historial: turnos anteriores que manda el cliente (/api/chat, formato del curso).
        Se validan, pero NO se le pasan al modelo: la memoria real es la del servidor.
        Así un turno "assistant" inventado por el cliente nunca llega al modelo."""
        self._contar(total_requests=1)
        try:
            r = self._responder(ficha, thread_id, pregunta, clave_limite, historial or [], dueno, usuario)
        except Exception:
            self._contar(errores=1)
            raise
        if r.estado == "bloqueado":
            self._contar(bloqueados=1)
        return r

    def _responder(self, ficha: Ficha, thread_id: str, pregunta: str, clave_limite: str | None,
                   historial: list[str], dueno: bool, usuario: str | None) -> Respuesta:
        quien = clave_limite or thread_id
        pregunta_segura = self.boveda.seudonimizar(thread_id, pregunta)
        categoria = donde = ""
        with iniciar_traza(thread_id, ficha, pregunta_segura, carpeta=self.carpeta_trazas) as traza:
            span = traza.nuevo_span("validacion_entrada", "guardrails")
            if not self.limitador.permitir("dueno" if dueno else quien):
                categoria = "limite_tasa"
            else:
                validacion = validar_historial(historial, pregunta)
                if validacion.permitido:
                    # .get: leer no crea la conversación en memoria (solo _recordar lo hace).
                    anteriores = self._recientes.get(thread_id, ())
                    validacion = validar_entrada(pregunta, [*historial, *anteriores])
                categoria = "" if validacion.permitido else validacion.categoria
                donde = "" if validacion.permitido else validacion.donde
                # Solo se recuerdan los mensajes que pasaron: si se guardara uno bloqueado,
                # contaminaría (y bloquearía) las preguntas legítimas que vienen después.
                if validacion.permitido:
                    self._recordar(thread_id, pregunta)
                    # Cupos y tope diario cuentan solo las preguntas que irían al modelo:
                    # un ataque bloqueado por el filtro no gasta cuota de Groq.
                    if self.cupos:
                        categoria = self.cupos.consumir(dueno, quien)
                    if not categoria and self.tope_diario and not self.tope_diario.permitir("total"):
                        categoria = "tope_diario"
            if categoria:
                span.estado = traza.estado = "bloqueado"
                span.detalle["categoria"] = categoria
                if donde and donde != "mensaje":
                    span.detalle["donde"] = donde
                texto = traza.respuesta = MENSAJES[categoria]
            else:
                ocultos = [tipo for tipo, _ in buscar_pii(pregunta)]
                traza.nuevo_span("seudonimizacion", "boveda").detalle["datos_ocultos"] = ocultos
                # Metadatos y etiquetas para LangSmith (si está encendido; si no, se ignoran).
                config = {**self._config(ficha, thread_id), "run_name": f"asistente {ficha.seguro}",
                          "tags": [ficha.seguro],
                          "metadata": envio_langsmith.metadatos(ficha, thread_id, traza.trace_id, usuario)}
                resultado = self._agente(ficha).invoke(
                    {"messages": [{"role": "user", "content": pregunta_segura}]},
                    config,
                    context=Contexto(ficha, thread_id, self.boveda),
                )
                traza.etapa = etapa_de(resultado)
                crudo = normalizar_citas(resultado["messages"][-1].content)
                salida = traza.nuevo_span("validacion_salida", "redaccion_pii")
                # Hallazgo de la evaluación: con el tope de llamadas, LangChain devuelve su
                # mensaje interno en inglés; y a veces gpt-oss responde vacío.
                if not crudo.strip() or crudo.startswith(_TOPE_DE_LLAMADAS):
                    salida.detalle["sin_respuesta"] = "vacia" if not crudo.strip() else "tope_llamadas"
                    crudo = SIN_RESPUESTA
                limpio = redactar_pii(crudo)
                salida.detalle["redacciones"] = limpio.count("_REDACTADO]") - crudo.count("_REDACTADO]")
                # LLM08: si la respuesta copia las reglas del prompt, no se entrega.
                if hay_fuga_de_instrucciones(limpio, instrucciones_fijas(ficha)):
                    salida.estado = traza.estado = "bloqueado"
                    salida.detalle["fuga_instrucciones"] = True
                    categoria = "fuga_instrucciones"
                    limpio = MENSAJES[categoria]
                traza.respuesta = limpio
                texto = self.boveda.revelar(thread_id, limpio)
        if categoria:  # el agente no lo vio: a LangSmith va como corrida "bloqueada"
            envio_langsmith.registrar_bloqueo(
                pregunta_segura, categoria, donde, traza.respuesta,
                envio_langsmith.metadatos(ficha, thread_id, traza.trace_id, usuario))
        return Respuesta(
            texto=texto,
            trace_id=traza.trace_id,
            estado=traza.estado,
            categoria=categoria,
            etapa=traza.etapa,
            duracion_ms=traza.duracion_ms,
            tokens_entrada=traza.tokens_entrada,
            tokens_salida=traza.tokens_salida,
            donde=donde,
        )
