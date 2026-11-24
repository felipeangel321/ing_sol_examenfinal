"""Reporte de métricas a partir de las trazas guardadas en .trazas/.

Responde la pregunta de IL3.1: ¿la llamada al agente está sana?
  - latencia (p50, p95, máxima) de cada pregunta completa
  - tokens de entrada y salida por pregunta
  - tasa de error y reintentos del modelo (429 / tool_use_failed)
  - cuántas veces llama al modelo y a cada herramienta
  - qué etapa se lleva más tiempo (para saber qué optimizar)

Uso:
  uv run python -m backend.observabilidad.reporte
  uv run python -m backend.observabilidad.reporte --seguro hogar
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from typing import Any

from backend.agentes.etapas import ETAPAS
from backend.observabilidad.trazas import leer_trazas


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicion = (len(ordenados) - 1) * p
    abajo = int(posicion)
    arriba = min(abajo + 1, len(ordenados) - 1)
    return ordenados[abajo] + (ordenados[arriba] - ordenados[abajo]) * (posicion - abajo)


def resumen(trazas: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas agregadas de un grupo de trazas."""
    if not trazas:
        return {"preguntas": 0}
    latencias = [t["duracion_ms"] for t in trazas]
    spans = [s for t in trazas for s in t["spans"]]
    spans_modelo = [s for s in spans if s["etapa"] == "modelo"]
    tiempo_por_etapa: dict[str, float] = defaultdict(float)
    for s in spans:
        clave = s["nombre"] if s["etapa"] == "herramienta" else s["etapa"]
        tiempo_por_etapa[clave] += s["duracion_ms"]
    etapa_lenta = max(tiempo_por_etapa, key=tiempo_por_etapa.get) if tiempo_por_etapa else "-"
    # Embudo: hasta qué etapa del caso llegó cada conversación (consulta → ... → registrada).
    alcanzada: dict[str, int] = {}
    for t in trazas:
        if t.get("etapa") in ETAPAS:
            alcanzada[t["thread_id"]] = max(alcanzada.get(t["thread_id"], 0), ETAPAS.index(t["etapa"]))
    embudo = {e: sum(n >= i for n in alcanzada.values()) for i, e in enumerate(ETAPAS)}
    return {
        "preguntas": len(trazas),
        "conversaciones": len({t["thread_id"] for t in trazas}),
        # Un bloqueo de seguridad NO es un error: el sistema hizo lo que debía.
        "tasa_error": sum(t["estado"] == "error" for t in trazas) / len(trazas),
        "bloqueadas": sum(t["estado"] == "bloqueado" for t in trazas),
        "latencia_p50_s": _percentil(latencias, 0.5) / 1000,
        "latencia_p95_s": _percentil(latencias, 0.95) / 1000,
        "latencia_max_s": max(latencias) / 1000,
        "tokens_entrada_prom": statistics.mean(t["tokens_entrada"] for t in trazas),
        "tokens_salida_prom": statistics.mean(t["tokens_salida"] for t in trazas),
        "llamadas_modelo_prom": statistics.mean(t["llamadas_modelo"] for t in trazas),
        "reintentos_modelo": sum(s["estado"] == "error" for s in spans_modelo),
        # Respuestas reemplazadas por el mensaje de "no encontré respuesta" (vacía o tope de llamadas).
        "sin_respuesta": sum(bool(s["detalle"].get("sin_respuesta")) for s in spans),
        "uso_herramientas": dict(Counter(n for t in trazas for n in t["herramientas"])),
        "embudo": embudo,
        "bloqueos_por_categoria": dict(Counter(
            s["detalle"].get("categoria") for s in spans
            if s["etapa"] == "validacion_entrada" and s["estado"] == "bloqueado"
        )),
        "etapa_mas_lenta": etapa_lenta,
        "tiempo_por_etapa_s": {k: round(v / 1000, 2) for k, v in tiempo_por_etapa.items()},
    }


def panel(trazas: list[dict[str, Any]]) -> dict[str, Any]:
    """Datos del dashboard: totales, por seguro y una fila por pregunta.

    Las filas NO traen la pregunta ni la respuesta (pueden tener el nombre del cliente):
    el panel muestra solo números, etapas y nombres de herramientas.
    """
    por_seguro: dict[str, list] = defaultdict(list)
    for t in trazas:
        por_seguro[t["seguro"]].append(t)
    serie = [
        {
            "fecha": t["fecha"],
            "seguro": t["seguro"],
            "duracion_s": round(t["duracion_ms"] / 1000, 2),
            "tokens": t["tokens_entrada"] + t["tokens_salida"],
            "estado": t["estado"],
            "etapa": t.get("etapa", ""),
            "llamadas_modelo": t["llamadas_modelo"],
            "reintentos": sum(s["etapa"] == "modelo" and s["estado"] == "error" for s in t["spans"]),
            "herramientas": t["herramientas"],
        }
        for t in sorted(trazas, key=lambda t: t["fecha"])
    ]
    return {
        "total": resumen(trazas),
        "por_seguro": {s: resumen(g) for s, g in sorted(por_seguro.items())},
        "serie": serie,
    }


def imprimir(titulo: str, r: dict[str, Any]) -> None:
    print(f"\n== {titulo} ==")
    if not r["preguntas"]:
        print("  (sin trazas)")
        return
    print(f"  Preguntas: {r['preguntas']} en {r['conversaciones']} conversaciones")
    print(f"  Tasa de error: {r['tasa_error']:.0%}   Bloqueadas por seguridad: {r['bloqueadas']}")
    print(
        f"  Latencia: p50 {r['latencia_p50_s']:.1f} s · p95 {r['latencia_p95_s']:.1f} s"
        f" · máx {r['latencia_max_s']:.1f} s"
    )
    print(
        f"  Tokens por pregunta: {r['tokens_entrada_prom']:.0f} entrada"
        f" + {r['tokens_salida_prom']:.0f} salida"
    )
    print(
        f"  Llamadas al modelo por pregunta: {r['llamadas_modelo_prom']:.1f}"
        f"   Reintentos (429 / tool_use_failed): {r['reintentos_modelo']}"
        f"   Sin respuesta (vacía o tope): {r['sin_respuesta']}"
    )
    print(f"  Herramientas usadas: {r['uso_herramientas'] or '-'}")
    print("  Embudo (conversaciones que llegaron a cada etapa): "
          + " → ".join(f"{e} {n}" for e, n in r["embudo"].items()))
    print(f"  Etapa que más tiempo consume: {r['etapa_mas_lenta']}  {r['tiempo_por_etapa_s']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Métricas del agente a partir de .trazas/")
    parser.add_argument("--seguro", help="filtra por seguro (ej.: hogar)")
    args = parser.parse_args()

    trazas = leer_trazas()
    if args.seguro:
        trazas = [t for t in trazas if t["seguro"] == args.seguro]
    imprimir("Todos los seguros" if not args.seguro else args.seguro, resumen(trazas))
    if not args.seguro:
        por_seguro: dict[str, list] = defaultdict(list)
        for t in trazas:
            por_seguro[t["seguro"]].append(t)
        for seguro, grupo in sorted(por_seguro.items()):
            imprimir(seguro, resumen(grupo))


if __name__ == "__main__":
    main()
