"""Fuente externa: valor de la UF del día (para convertir deducibles y topes a pesos).

Las pólizas expresan deducibles, topes y primas en UF (unidad de fomento, se reajusta
cada día según la inflación). El cliente piensa en pesos, así que el agente puede
convertir con el valor oficial del día, que publica el Banco Central y replican estas
APIs públicas (sin clave):

  1. findic.cl       (rápida, ~0,1 s)
  2. mindicador.cl   (alternativa; a veces tarda más de 15 s)
  3. data/indicadores.json   copia local del último valor obtenido (respaldo)

Cuidados:
  - Al modelo solo llega un NÚMERO validado (rango plausible y fecha reciente), nunca
    texto de la fuente: un sitio externo no puede colarle instrucciones (inyección indirecta).
  - La cuenta la hace el código, no el modelo (un LLM se equivoca multiplicando).
  - A las fuentes no se les envía ningún dato del cliente.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

from backend.config import RAIZ

FUENTES = (
    ("findic.cl", "https://findic.cl/api/uf"),
    ("mindicador.cl", "https://mindicador.cl/api/uf"),
)
CACHE = RAIZ / "data" / "indicadores.json"
SEGUNDOS_ESPERA = 5
RANGO_PLAUSIBLE = (20_000.0, 80_000.0)  # pesos por UF; fuera de esto, la fuente está mal
DIAS_MAXIMOS = 7  # un valor más antiguo no se acepta como "de hoy"


class SinValorUF(Exception):
    """Ninguna fuente respondió y no hay copia local."""


@dataclass(frozen=True)
class ValorUF:
    valor: float
    fecha: date
    fuente: str
    respaldo: bool = False  # True: las fuentes fallaron y se usó la copia local


def _obtener_json(url: str) -> Any:
    import httpx

    respuesta = httpx.get(url, timeout=SEGUNDOS_ESPERA, follow_redirects=True)
    respuesta.raise_for_status()
    return respuesta.json()


def _leer_serie(datos: Any, hoy: date) -> tuple[date, float]:
    """Valor de hoy (o el más reciente anterior) de una respuesta tipo {"serie": [...]}. Valida todo."""
    if not isinstance(datos, dict) or not isinstance(datos.get("serie"), list):
        raise ValueError("respuesta sin 'serie'")
    candidatos = []
    for punto in datos["serie"]:
        try:
            fecha = date.fromisoformat(str(punto["fecha"])[:10])
            valor = float(punto["valor"])
        except (KeyError, TypeError, ValueError):
            continue
        if fecha <= hoy:
            candidatos.append((fecha, valor))
    if not candidatos:
        raise ValueError("sin valores hasta hoy")
    fecha, valor = max(candidatos)
    if not RANGO_PLAUSIBLE[0] <= valor <= RANGO_PLAUSIBLE[1]:
        raise ValueError(f"valor fuera de rango: {valor}")
    if (hoy - fecha).days > DIAS_MAXIMOS:
        raise ValueError(f"valor demasiado antiguo: {fecha}")
    return fecha, valor


def _leer_cache(ruta: Path) -> ValorUF | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return ValorUF(float(datos["valor"]), date.fromisoformat(datos["fecha"]), datos["fuente"])
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _guardar_cache(ruta: Path, uf: ValorUF) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"valor": uf.valor, "fecha": uf.fecha.isoformat(), "fuente": uf.fuente}),
                    encoding="utf-8")


def valor_uf(hoy: date | None = None, obtener: Callable[[str], Any] | None = None,
             cache: Path | None = None) -> ValorUF:
    """Valor de la UF de hoy: copia local si ya se pidió hoy; si no, las fuentes en orden."""
    hoy = hoy or date.today()
    obtener = obtener or _obtener_json
    cache = cache or CACHE
    guardado = _leer_cache(cache)
    if guardado and guardado.fecha == hoy:
        return guardado
    for nombre, url in FUENTES:
        try:
            fecha, valor = _leer_serie(obtener(url), hoy)
        except Exception:  # caída, demora o respuesta inválida: se prueba la siguiente
            continue
        uf = ValorUF(valor, fecha, nombre)
        _guardar_cache(cache, uf)
        return uf
    if guardado:
        return replace(guardado, respaldo=True)
    raise SinValorUF("no se pudo obtener el valor de la UF")


def pesos(monto: float) -> str:
    """Formato chileno: $1.234.567"""
    return "$" + f"{round(monto):,}".replace(",", ".")


def numero_uf(monto: float) -> str:
    """Formato chileno con decimales: 41.350,42"""
    return f"{monto:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


@dataclass(frozen=True)
class Conversion:
    texto: str
    uf: ValorUF


def convertir(monto: float, hacia: Literal["pesos", "uf"] = "pesos", **opciones) -> Conversion:
    """Convierte UF → pesos (o pesos → UF) con el valor del día."""
    uf = valor_uf(**opciones)
    if hacia == "pesos":
        resultado = f"{numero_uf(monto).removesuffix(',00')} UF ≈ {pesos(monto * uf.valor)}"
    else:
        resultado = f"{pesos(monto)} ≈ {numero_uf(monto / uf.valor)} UF"
    fuente = f"valor UF del {uf.fecha:%d-%m-%Y}: ${numero_uf(uf.valor)}, fuente {uf.fuente}"
    if uf.respaldo:
        fuente += "; las fuentes no respondieron, es el último valor guardado"
    return Conversion(f"{resultado} ({fuente}). Es un monto referencial.", uf)
