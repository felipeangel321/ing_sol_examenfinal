"""Cupos diarios de preguntas al modelo: uno para el público y otro reservado al dueño.

Problema: Groq gratuito da 200.000 tokens al día (~25 preguntas de este agente). Con la
URL pública, cualquiera (o un agente atacante) puede gastarlos con preguntas normales
("hola" × 25: no son un ataque, el filtro las deja pasar) y dejar la demo sin servicio.

  Público ─ cupo chico: N por IP al día, M en total al día y como mucho 1 pregunta
            cada X segundos sumando a todos (Groq: 8.000 tokens/min ≈ 1 pregunta/min).
  Dueño ─── cupo propio (link secreto, acceso.py) que el público no puede gastar.

Solo gastan cupo las preguntas que pasaron los filtros: un ataque bloqueado no llega al
modelo y no cuesta nada. Los cupos viven en memoria (se reinician con la app); el
límite por minuto por IP (limitador.py) sigue aplicando a todos.

OJO: en una red compartida (el WiFi del Duoc) todo el curso sale con la misma IP
pública, así que "por IP" se comporta como "por sala". Por eso el dueño no depende de
la IP sino de la cookie.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from threading import Lock

from backend.seguridad.limitador import LimitadorTasa

DIA_S = 24 * 3600


def _entero(nombre: str, por_defecto: int) -> int:
    try:
        return int(os.getenv(nombre, "") or por_defecto)
    except ValueError:
        return por_defecto


@dataclass
class Cupos:
    publico_dia: int = 15
    por_ip_dia: int = 5
    publico_cada_s: float = 120.0
    dueno_dia: int = 10
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._publico = LimitadorTasa(self.publico_dia, DIA_S)
        self._por_ip = LimitadorTasa(self.por_ip_dia, DIA_S)
        self._espacio = LimitadorTasa(1, self.publico_cada_s)
        self._dueno = LimitadorTasa(self.dueno_dia, DIA_S)

    @classmethod
    def desde_entorno(cls) -> Cupos:
        return cls(
            publico_dia=_entero("CUPO_PUBLICO_DIA", 15),
            por_ip_dia=_entero("CUPO_IP_DIA", 5),
            publico_cada_s=_entero("CUPO_PUBLICO_CADA_S", 120),
            dueno_dia=_entero("CUPO_DUENO_DIA", 10),
        )

    def consumir(self, dueno: bool, ip: str) -> str:
        """Gasta un cupo. Devuelve "" si hay, o la categoría del bloqueo si no."""
        if dueno:
            return "" if self._dueno.permitir("dueno") else "tope_diario"
        # Se revisan los tres antes de gastar: si falla uno, no se gasta ninguno.
        with self._lock:
            if not self._publico.queda("total"):
                return "tope_diario"
            if not self._por_ip.queda(ip):
                return "cupo_ip"
            if not self._espacio.queda("total"):
                return "espera_publico"
            self._publico.permitir("total")
            self._por_ip.permitir(ip)
            self._espacio.permitir("total")
            return ""
