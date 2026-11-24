"""Tablas de resultados del informe (Markdown) con los datos reales de .trazas/ y .evaluaciones/.

  uv run python entrega/tablas_informe.py     → docs/informe/tablas_resultados.md

Se pueden copiar al informe tal cual. Solo trae DATOS: la interpretación la escribe el equipo.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from backend.evaluacion.evaluar import K, cargar_preguntas, ultimo  # noqa: E402
from backend.observabilidad import leer_trazas  # noqa: E402
from backend.observabilidad.reporte import resumen  # noqa: E402

SALIDA = RAIZ / "docs" / "informe" / "tablas_resultados.md"
NOMBRES = {"hibrida": "Híbrida (BM25 + embeddings, RRF)", "palabras": "Solo palabras (BM25)",
           "semantica": "Solo embeddings (MiniLM)"}


def n(valor: float, decimales: int = 1) -> str:
    return f"{valor:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def pct(valor: float | None) -> str:
    return "—" if valor is None else f"{n(valor * 100, 0)}%"


def tabla(encabezado: list[str], filas: list[list]) -> str:
    lineas = ["| " + " | ".join(encabezado) + " |", "|" + "|".join("---" for _ in encabezado) + "|"]
    lineas += ["| " + " | ".join(str(c) for c in f) + " |" for f in filas]
    return "\n".join(lineas)


def operacion(trazas) -> str:
    r = resumen(trazas)
    tiempos = r["tiempo_por_etapa_s"]
    total = sum(tiempos.values()) or 1
    eval_ = [t for t in trazas if t["thread_id"].startswith("eval-")]
    filas = [
        ["Preguntas registradas", r["preguntas"], f"{r['conversaciones']} conversaciones; {len(eval_)} de la evaluación"],
        ["Latencia p50 / p95 / máx.", f"{n(r['latencia_p50_s'])} / {n(r['latencia_p95_s'])} / {n(r['latencia_max_s'])} s", "pregunta completa"],
        ["Tokens por pregunta (prom.)", f"{n(r['tokens_entrada_prom'], 0)} entrada + {n(r['tokens_salida_prom'], 0)} salida", ""],
        ["Llamadas al modelo por pregunta", n(r["llamadas_modelo_prom"]), "tope configurado: 5"],
        ["Reintentos del modelo (429)", r["reintentos_modelo"], "visibles desde max_retries=0"],
        ["Tasa de error", pct(r["tasa_error"]), "los bloqueos no cuentan como error"],
        ["Sin respuesta (vacía o tope de 5 llamadas)", r["sin_respuesta"], "contadas desde que se agregó el control"],
        ["Bloqueadas por seguridad", r["bloqueadas"], ", ".join(f"{k}: {v}" for k, v in r["bloqueos_por_categoria"].items())],
        ["Tiempo en el modelo (Groq)", pct(tiempos.get("modelo", 0) / total), "del tiempo total de las etapas"],
        ["Tiempo en buscar_documentos", pct(tiempos.get("buscar_documentos", 0) / total), "incluye la carga en frío"],
        ["Embudo de etapas", " → ".join(f"{e} {v}" for e, v in r["embudo"].items()), "conversaciones que llegaron"],
    ]
    return tabla(["Métrica", "Valor", "Nota"], filas)


def recuperacion() -> str:
    rec = ultimo("recuperacion")
    if not rec:
        return "_Sin resultados de recuperación._"
    metodos = list(rec["resumen"])
    filas = [[f["id"], f["tipo"], *[f.get(m) or "—" for m in metodos]] for f in rec["filas"]]
    detalle = tabla(["Pregunta", "Tipo", *[f"Posición: {NOMBRES[m].split(' (')[0]}" for m in metodos]], filas)
    resumen_m = tabla(["Método", f"Acierto@{K}", "MRR"],
                      [[NOMBRES[m], pct(v["acierto_k"]), n(v["mrr"], 2)] for m, v in rec["resumen"].items()])
    return (f"{resumen_m}\n\nDetalle: posición del primer fragmento que contiene la evidencia "
            f"(— = no aparece entre los 30 primeros).\n\n{detalle}")


def respuestas() -> str:
    resp = ultimo("respuestas")
    if not resp:
        return "_Sin resultados de respuestas._"
    r, filas = resp["resumen"], resp["filas"]
    nota = (f"_Recalificada sin Groq desde `{resp['recorregido_de']}` tras corregir un criterio del "
            "corrector (las respuestas son las mismas)._\n\n" if resp.get("recorregido_de") else "")
    general = tabla(["Métrica", "Valor"], [
        ["Preguntas evaluadas", r["preguntas"]],
        ["Errores (sin respuesta)", r["errores"]],
        ["Precisión (respuestas de contenido correctas)", pct(r["precision"])],
        ["Respuestas de contenido que citan documento y página", pct(r["con_cita"])],
        ["Preguntas de seguridad detenidas", ", ".join(f"{k}: {v}" for k, v in r["seguridad_detenida"].items())],
        ["Latencia p50 / p95", f"{n(r['latencia_p50_s'])} / {n(r['latencia_p95_s'])} s"],
        ["Tokens por pregunta (prom.)", n(r["tokens_prom"], 0)],
    ])
    por_tipo = tabla(["Tipo de pregunta", "Correctas"], [[t, pct(v)] for t, v in r["precision_por_tipo"].items()])
    trazas = {t["trace_id"]: t for t in leer_trazas()}
    detalle = []
    for f in filas:
        t = trazas.get(f.get("trace_id", ""), {})
        reintentos = sum(s["etapa"] == "modelo" and s["estado"] == "error" for s in t.get("spans", []))
        herramientas = Counter(f.get("herramientas", []))
        detalle.append([
            f["id"], f["tipo"], "sí" if f["correcta"] else "**no**",
            "sí" if f.get("cita") else "no", f.get("detenida_por", ""),
            n(f.get("duracion_s", 0)), f.get("tokens", "—"), reintentos,
            ", ".join(f"{h}×{c}" if c > 1 else h for h, c in herramientas.items()) or "—",
        ])
    detalle_t = tabla(["Pregunta", "Tipo", "Correcta", "Cita", "Detenida por", "s", "Tokens", "Reintentos", "Herramientas"], detalle)
    return f"{nota}{general}\n\n{por_tipo}\n\n{detalle_t}"


def consistencia() -> str:
    cons = ultimo("consistencia")
    if not cons or not cons["resumen"].get("preguntas"):
        return "_Sin resultados de consistencia._"
    r = cons["resumen"]
    filas = [[pid, d["rondas"], d["correctas"], "sí" if d["mismo_veredicto"] else "**no**",
              "sí" if d["misma_cita"] else "no", n(d["similitud_palabras"], 2),
              "sí" if d["mismas_herramientas"] else "no", f"{n(d['latencia_prom_s'])} ± {n(d['latencia_desv_s'])} s"]
             for pid, d in r["detalle"].items()]
    return (tabla(["Métrica", "Valor"], [["Mismo veredicto en todas las rondas", pct(r["mismo_veredicto"])],
                                          ["Misma cita (archivo y página)", pct(r["misma_cita"])],
                                          ["Similitud de palabras entre rondas (Jaccard prom.)", n(r["similitud_palabras_prom"], 2)]])
            + "\n\n" + tabla(["Pregunta", "Rondas", "Correctas", "Mismo veredicto", "Misma cita", "Similitud",
                               "Mismas herramientas", "Latencia"], filas))


def set_preguntas() -> str:
    filas = [[p.id, p.seguro, p.tipo, p.pregunta, p.esperado, p.fuente] for p in cargar_preguntas().preguntas]
    return tabla(["Id", "Seguro", "Tipo", "Pregunta", "Respuesta esperada", "Fuente"], filas)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    trazas = leer_trazas()
    partes = [
        "# Tablas de resultados (datos medidos)",
        f"Generado el {datetime.now():%d-%m-%Y %H:%M} con `uv run python entrega/tablas_informe.py`. "
        "Solo datos: la interpretación va en el informe, escrita por el equipo.",
        "## Tabla 1. Métricas de operación (todas las trazas)", operacion(trazas),
        "## Tabla 2. Precisión de la recuperación (sin modelo)", recuperacion(),
        "## Tabla 3. Precisión y latencia de las respuestas (agente completo con Groq)", respuestas(),
        "## Tabla 4. Consistencia (misma pregunta repetida)", consistencia(),
        "## Anexo. Set de evaluación", set_preguntas(),
    ]
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text("\n\n".join(partes) + "\n", encoding="utf-8")
    print("Tablas:", SALIDA)


if __name__ == "__main__":
    main()
