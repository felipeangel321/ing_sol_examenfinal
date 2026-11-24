"""Límite de pedidos por ventana de tiempo, por clave (una IP, una conversación, "total").

Se usa para el límite por minuto (evita que una persona o un script agote la cuota del
modelo: Groq gratuito da 8.000 tokens por minuto) y para los cupos diarios (cupos.py).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class LimitadorTasa:
    def __init__(self, maximo: int = 8, ventana_s: float = 60.0, reloj=time.monotonic) -> None:
        self.maximo = maximo
        self.ventana_s = ventana_s
        self._reloj = reloj
        self._pedidos: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _vigentes(self, clave: str, ahora: float) -> int:
        """Pedidos dentro de la ventana. Una clave sin pedidos se olvida: muchas IPs
        distintas no dejan la memoria llena de colas vacías."""
        pedidos = self._pedidos.get(clave)
        if pedidos is None:
            return 0
        while pedidos and ahora - pedidos[0] >= self.ventana_s:
            pedidos.popleft()
        if not pedidos:
            del self._pedidos[clave]
        return len(pedidos)

    def permitir(self, clave: str) -> bool:
        """Cuenta un pedido si hay espacio. False si la clave ya llegó al máximo."""
        ahora = self._reloj()
        with self._lock:
            if self._vigentes(clave, ahora) >= self.maximo:
                return False
            self._pedidos[clave].append(ahora)
            return True

    def queda(self, clave: str) -> bool:
        """¿Hay espacio? Mira sin contar (para revisar varios cupos antes de gastar uno)."""
        with self._lock:
            return self._vigentes(clave, self._reloj()) < self.maximo
