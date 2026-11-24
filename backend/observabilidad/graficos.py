"""Gráficos de métricas para el notebook y el informe (matplotlib).

Usan los mismos datos que el panel web: las trazas de .trazas/ y los resultados de
.evaluaciones/. Un solo tono de azul (el del panel); el gris marca referencias (p95).

  uv run --group notebook python -m backend.observabilidad.graficos docs/informe/figuras
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt

from backend.observabilidad.reporte import _percentil, resumen

AZUL = "#2a78d6"
GRIS = "#6b7280"
TINTA = "#1f2937"
REJILLA = "#e5e7eb"

NOMBRES = {
    "modelo": "Modelo (Groq)",
    "buscar_documentos": "Buscar en pólizas",
    "convertir_uf": "Valor UF",
    "ver_campos_solicitud": "Ver campos",
    "preparar_solicitud": "Preparar solicitud",
    "registrar_solicitud": "Registrar solicitud",
    "consultar_solicitud": "Consultar solicitud",
    "derivar_a_persona": "Derivar a persona",
    "validacion_entrada": "Filtro de entrada",
    "seudonimizacion": "Seudonimización",
    "validacion_salida": "Filtro de salida",
    "hibrida": "Híbrida (BM25 + embeddings)",
    "palabras": "Solo palabras (BM25)",
    "semantica": "Solo embeddings",
    "cobertura": "Cobertura", "exclusion": "Exclusión", "monto": "Monto o tope", "plazo": "Plazo",
    "limite": "Límite (precio)", "fuera_de_alcance": "Otro seguro",
}


def estilo() -> None:
    plt.rcParams.update({
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": REJILLA, "axes.labelcolor": TINTA, "axes.titlecolor": TINTA,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.grid": True, "grid.color": REJILLA, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "xtick.color": GRIS, "ytick.color": GRIS, "font.size": 9.5,
        "figure.dpi": 110, "savefig.dpi": 200, "savefig.bbox": "tight",
    })


def latencia(trazas: list[dict[str, Any]], ax=None):
    """Segundos de cada pregunta respondida, en orden, con la línea del p95.
    Círculo vacío = la pregunta tuvo reintentos por el límite de Groq."""
    ax = ax or plt.subplots(figsize=(8, 3.2))[1]
    filas = [t for t in sorted(trazas, key=lambda t: t["fecha"]) if t["estado"] != "bloqueado"]
    x = list(range(1, len(filas) + 1))
    y = [t["duracion_ms"] / 1000 for t in filas]
    reintento = [any(s["etapa"] == "modelo" and s["estado"] == "error" for s in t["spans"]) for t in filas]
    ax.plot(x, y, color=AZUL, linewidth=2)
    ax.scatter([a for a, r in zip(x, reintento) if not r], [b for b, r in zip(y, reintento) if not r],
               s=22, color=AZUL, zorder=3, label="sin reintentos")
    ax.scatter([a for a, r in zip(x, reintento) if r], [b for b, r in zip(y, reintento) if r],
               s=34, facecolor="white", edgecolor=AZUL, linewidth=1.6, zorder=4, label="con reintentos (429)")
    if y:
        p95 = _percentil(y, 0.95)
        ax.axhline(p95, color=GRIS, linestyle="--", linewidth=1)
        ax.annotate(f"p95 {p95:.0f} s", (x[-1], p95), xytext=(4, 3), textcoords="offset points",
                    color=GRIS, fontsize=8.5, ha="right", va="bottom")
    ax.set(title="Latencia por pregunta", xlabel="Pregunta (orden de llegada)", ylabel="Segundos")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, loc="upper left", fontsize=8.5)
    return ax


def _barras(ax, etiquetas: list[str], valores: list[float], formato: str, titulo: str, xlabel: str,
            maximo: float | None = None):
    pos = list(range(len(etiquetas)))[::-1]
    ax.barh(pos, valores, color=AZUL, height=0.6)
    ax.set_yticks(pos, etiquetas)
    ax.grid(axis="y", visible=False)
    tope = maximo or (max(valores) if valores else 1) or 1
    for p, v in zip(pos, valores):
        ax.annotate(formato.format(v).replace(".", ","), (v, p), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=TINTA)
    ax.set_xlim(0, tope * 1.15)
    ax.set(title=titulo, xlabel=xlabel)
    return ax


def tiempo_por_etapa(trazas: list[dict[str, Any]], ax=None):
    """Dónde se va el tiempo: suma de segundos por etapa en todas las trazas."""
    ax = ax or plt.subplots(figsize=(6, 3.2))[1]
    tiempos = resumen(trazas).get("tiempo_por_etapa_s", {})
    total = sum(tiempos.values()) or 1
    # Las etapas de menos de 0,5% (filtros, herramientas locales) se suman en "Resto".
    visibles = {e: v for e, v in tiempos.items() if v / total >= 0.005}
    orden = sorted(visibles, key=visibles.get, reverse=True)
    etiquetas, valores = [NOMBRES.get(e, e) for e in orden], [visibles[e] / total * 100 for e in orden]
    if resto := total - sum(visibles.values()):
        etiquetas.append("Resto (filtros y herramientas locales)")
        valores.append(resto / total * 100)
    return _barras(ax, etiquetas, valores,
                   "{:.1f}%", "Dónde se va el tiempo", "% del tiempo total", maximo=100)


def uso_herramientas(trazas: list[dict[str, Any]], ax=None):
    ax = ax or plt.subplots(figsize=(6, 3.2))[1]
    uso = resumen(trazas).get("uso_herramientas", {})
    orden = sorted(uso, key=uso.get, reverse=True)
    return _barras(ax, [NOMBRES.get(h, h) for h in orden], [uso[h] for h in orden],
                   "{:.0f}", "Uso de herramientas", "Llamadas")


def recuperacion(resumen_rec: dict[str, dict[str, float]], k: int = 4, ax=None):
    """Acierto@k de cada método de búsqueda sobre el set de evaluación."""
    ax = ax or plt.subplots(figsize=(6, 2.6))[1]
    metodos = list(resumen_rec)
    return _barras(ax, [NOMBRES.get(m, m) for m in metodos],
                   [resumen_rec[m]["acierto_k"] * 100 for m in metodos],
                   "{:.0f}%", f"Recuperación: evidencia entre los {k} fragmentos", "% de preguntas", maximo=100)


def precision_por_tipo(resumen_resp: dict[str, Any], ax=None):
    ax = ax or plt.subplots(figsize=(6, 3))[1]
    tipos = resumen_resp.get("precision_por_tipo", {})
    orden = sorted(tipos, key=tipos.get, reverse=True)
    return _barras(ax, [NOMBRES.get(t, t) for t in orden], [tipos[t] * 100 for t in orden], "{:.0f}%",
                   "Respuestas correctas por tipo de pregunta", "% correctas", maximo=100)


def guardar_figuras(carpeta: Path, trazas: list[dict[str, Any]] | None = None) -> list[Path]:
    """Genera las figuras del informe con los datos actuales."""
    from backend.evaluacion.evaluar import ultimo
    from backend.observabilidad import leer_trazas

    estilo()
    trazas = leer_trazas() if trazas is None else trazas
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []

    def guardar(nombre: str, dibujar, *datos) -> None:
        fig, ax = plt.subplots(figsize=(7.5, 3.2))
        dibujar(*datos, ax=ax)
        ruta = carpeta / f"{nombre}.png"
        fig.savefig(ruta)
        plt.close(fig)
        rutas.append(ruta)

    if trazas:
        guardar("latencia", latencia, trazas)
        guardar("tiempo_por_etapa", tiempo_por_etapa, trazas)
        guardar("uso_herramientas", uso_herramientas, trazas)
    if rec := ultimo("recuperacion"):
        guardar("recuperacion", recuperacion, rec["resumen"], rec["k"])
    if resp := ultimo("respuestas"):
        guardar("precision_por_tipo", precision_por_tipo, resp["resumen"])
    return rutas


if __name__ == "__main__":
    matplotlib.use("Agg")  # sin ventanas: solo guarda los archivos
    sys.stdout.reconfigure(encoding="utf-8")
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/informe/figuras")
    for r in guardar_figuras(destino):
        print("Figura:", r)
