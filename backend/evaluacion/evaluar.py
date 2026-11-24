"""Evaluación del agente con un set de preguntas de respuesta conocida (IE9).

Mide los tres aspectos que pide IL3.1:
  precisión     ¿la búsqueda encuentra el fragmento correcto? (recuperación, sin modelo)
                ¿la respuesta dice lo que dice la póliza y lo cita? (respuesta, con Groq)
  latencia      segundos y tokens por pregunta (los mismos que guarda la traza)
  consistencia  la misma pregunta varias veces: ¿mismo veredicto, mismas palabras, misma cita?

Las preguntas y sus respuestas esperadas están en preguntas.yaml. Los resultados se
guardan en .evaluaciones/ (JSON), y cada pregunta deja además su traza en .trazas/,
así que también aparece en el panel de métricas.

Uso:
  uv run python -m backend.evaluacion.evaluar --recuperacion            # gratis, ~1 min
  uv run python -m backend.evaluacion.evaluar --respuestas              # usa Groq
  uv run python -m backend.evaluacion.evaluar --respuestas --solo veh-01,hog-01
  uv run python -m backend.evaluacion.evaluar --consistencia 3          # usa Groq
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from backend.catalogo import Catalogo, cargar_catalogo
from backend.config import RAIZ
from backend.indice import CANDIDATOS_POR_METODO, IndiceSeguro, _vectorizar, cargar_indice, normalizar, tokens

PREGUNTAS = Path(__file__).with_name("preguntas.yaml")
RESULTADOS_DIR = RAIZ / ".evaluaciones"
CORREDOR = "demo"
K = 4  # fragmentos que recibe el agente por búsqueda (FRAGMENTOS_POR_BUSQUEDA)
PAUSA_S = 20  # entre preguntas: el plan gratuito de Groq admite 8.000 tokens por minuto
_CITA = re.compile(r"\bpdf\b.*\bpag", re.S)  # "(hogar.pdf, pág. 10)" normalizado


@dataclass(frozen=True)
class Pregunta:
    id: str
    seguro: str
    tipo: str
    pregunta: str
    esperado: str
    fuente: str
    evidencia: tuple[str, ...] = ()
    debe_decir: tuple[tuple[str, ...], ...] = ()
    cita: bool = False
    bloqueo: str = ""


@dataclass
class SetEvaluacion:
    preguntas: list[Pregunta]
    consistencia: list[str] = field(default_factory=list)

    def por_id(self, ids: list[str]) -> list[Pregunta]:
        indice = {p.id: p for p in self.preguntas}
        faltan = [i for i in ids if i not in indice]
        if faltan:
            raise ValueError(f"No existen en preguntas.yaml: {', '.join(faltan)}")
        return [indice[i] for i in ids]


def cargar_preguntas(ruta: Path = PREGUNTAS) -> SetEvaluacion:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    preguntas = [
        Pregunta(
            **{k: v for k, v in p.items() if k not in ("evidencia", "debe_decir")},
            evidencia=tuple(p.get("evidencia") or ()),
            debe_decir=tuple(tuple(g) for g in p.get("debe_decir") or ()),
        )
        for p in datos["preguntas"]
    ]
    repetidos = [i for i, n in Counter(p.id for p in preguntas).items() if n > 1]
    if repetidos:
        raise ValueError(f"ids repetidos en preguntas.yaml: {repetidos}")
    return SetEvaluacion(preguntas, list(datos.get("consistencia") or []))


def contiene(texto: str, expresiones: tuple[str, ...] | list[str]) -> bool:
    """¿Aparece alguna de las expresiones en el texto? (ambos normalizados)."""
    normalizado = normalizar(texto)
    return any(re.search(e, normalizado) for e in expresiones)


def revisar_respuesta(p: Pregunta, texto: str) -> dict[str, Any]:
    """Qué grupos de debe_decir se cumplen y si la respuesta cita documento y página."""
    grupos = [contiene(texto, g) for g in p.debe_decir]
    cita = bool(_CITA.search(normalizar(texto)))
    return {
        "grupos": grupos,
        "cita": cita,
        "correcta": all(grupos) and (cita or not p.cita),
    }


# --- 1) Recuperación: sin modelo, compara los tres métodos de búsqueda -----------------

def _posicion(fragmentos, evidencia: tuple[str, ...]) -> int | None:
    for n, f in enumerate(fragmentos, 1):
        if contiene(f.texto, evidencia):
            return n
    return None


def rankings(indice: IndiceSeguro, consulta: str) -> dict[str, list]:
    """Los fragmentos en el orden en que los entrega cada método."""
    salida = {"hibrida": indice.buscar(consulta, k=CANDIDATOS_POR_METODO)}
    lexico = indice.bm25.puntajes(consulta)
    salida["palabras"] = [indice.fragmentos[i] for i in sorted(lexico, key=lexico.get, reverse=True)]
    if indice.vectores is not None and len(indice.vectores):
        similitud = indice.vectores @ _vectorizar([consulta])[0]
        salida["semantica"] = [indice.fragmentos[int(i)] for i in np.argsort(-similitud)]
    return {m: r[:CANDIDATOS_POR_METODO] for m, r in salida.items()}


def evaluar_recuperacion(preguntas: list[Pregunta], catalogo: Catalogo) -> list[dict[str, Any]]:
    resultados = []
    for p in preguntas:
        if not p.evidencia:
            continue
        indice = cargar_indice(catalogo[CORREDOR][p.seguro])
        fila: dict[str, Any] = {"id": p.id, "seguro": p.seguro, "tipo": p.tipo}
        for metodo, fragmentos in rankings(indice, p.pregunta).items():
            fila[metodo] = _posicion(fragmentos, p.evidencia)
        resultados.append(fila)
    return resultados


def resumen_recuperacion(resultados: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """acierto@K: la evidencia está entre los K fragmentos que recibe el agente.
    MRR: promedio de 1/posición (1 = siempre primero; 0 = nunca aparece)."""
    metodos = [m for m in ("hibrida", "palabras", "semantica") if any(m in r for r in resultados)]
    return {
        m: {
            "acierto_k": sum((r.get(m) or 99) <= K for r in resultados) / len(resultados),
            "mrr": statistics.mean(1 / r[m] if r.get(m) else 0 for r in resultados),
        }
        for m in metodos
    }


# --- 2) Respuestas: el agente completo (filtros + modelo + herramientas), con Groq ------

def _sin_secretos(texto: str) -> str:
    # El mensaje de un 429 de Groq trae el id de la organización.
    return re.sub(r"org_\w+", "org_[oculto]", texto)[:300]


def _herramientas_de(trace_id: str, carpeta: Path | None) -> list[str]:
    from backend.observabilidad import leer_trazas

    for t in reversed(leer_trazas(carpeta)):
        if t["trace_id"] == trace_id:
            return t["herramientas"]
    return []


def calificar(p: Pregunta, texto: str, estado: str) -> dict[str, Any]:
    revision = revisar_respuesta(p, texto) | {"cita_requerida": p.cita}
    if p.bloqueo:
        # Seguridad: vale que la detenga el filtro (sin modelo) o el agente (se niega).
        capa = "filtro" if estado == "bloqueado" else ("agente" if all(revision["grupos"]) else "ninguna")
        revision["correcta"] = capa != "ninguna"
        revision["detenida_por"] = capa
    return revision


def recorregir(datos: dict[str, Any], conjunto: SetEvaluacion) -> list[dict[str, Any]]:
    """Vuelve a calificar respuestas ya guardadas con los criterios actuales (sin Groq).
    Sirve cuando se corrige un criterio, no la respuesta: el texto evaluado es el mismo."""
    preguntas = {p.id: p for p in conjunto.preguntas}
    return [f if f.get("estado") == "error" else f | calificar(preguntas[f["id"]], f["respuesta"], f["estado"])
            for f in datos["filas"]]


def evaluar_respuesta(asistente, ficha, p: Pregunta, ronda: int = 0) -> dict[str, Any]:
    thread_id = f"eval-{p.id}-{ronda}-{uuid.uuid4().hex[:6]}"
    fila: dict[str, Any] = {"id": p.id, "seguro": p.seguro, "tipo": p.tipo, "ronda": ronda}
    try:
        r = asistente.responder(ficha, thread_id, p.pregunta)
    except Exception as error:
        return fila | {"estado": "error", "error": _sin_secretos(f"{type(error).__name__}: {error}"),
                       "correcta": False}
    return fila | calificar(p, r.texto, r.estado) | {
        "estado": r.estado,
        "categoria": r.categoria,
        "respuesta": r.texto,
        "trace_id": r.trace_id,
        "duracion_s": round(r.duracion_ms / 1000, 2),
        "tokens": r.tokens_entrada + r.tokens_salida,
        "herramientas": _herramientas_de(r.trace_id, asistente.carpeta_trazas),
    }


def _sin_cuota_diaria(fila: dict[str, Any]) -> bool:
    error = fila.get("error", "").lower()
    return "per day" in error or "tpd" in error


def correr(preguntas: list[Pregunta], catalogo: Catalogo, rondas: int = 1, pausa_s: float = PAUSA_S,
           asistente=None, mostrar=print) -> list[dict[str, Any]]:
    from backend.seguridad import LimitadorTasa
    from backend.servicio import Asistente

    # Sin límite por minuto propio: el set entero viene del mismo "cliente".
    asistente = asistente or Asistente(limitador=LimitadorTasa(maximo=10_000))
    resultados = []
    for ronda, p in itertools.product(range(rondas), preguntas):
        if resultados and pausa_s and resultados[-1].get("estado") != "bloqueado":
            time.sleep(pausa_s)
        fila = evaluar_respuesta(asistente, catalogo[CORREDOR][p.seguro], p, ronda)
        resultados.append(fila)
        marca = "OK " if fila["correcta"] else "MAL"
        mostrar(f"  [{marca}] {p.id} ronda {ronda}  {fila.get('estado')}  "
                f"{fila.get('duracion_s', '-')} s  {fila.get('tokens', '-')} tokens  {fila.get('error', '')}")
        if _sin_cuota_diaria(fila):
            mostrar("  Se acabó la cuota diaria de Groq: se guarda lo evaluado hasta aquí.")
            break
    return resultados


def _percentil(valores: list[float], p: float) -> float:
    from backend.observabilidad.reporte import _percentil as percentil

    return percentil(valores, p)


def resumen_respuestas(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    respondidas = [r for r in resultados if r.get("estado") == "ok"]
    contenido = [r for r in resultados if r["tipo"] != "seguridad"]
    seguridad = [r for r in resultados if r["tipo"] == "seguridad"]
    con_cita = [r for r in contenido if r.get("cita_requerida", True) and r.get("estado") == "ok"]
    por_tipo: dict[str, list[bool]] = defaultdict(list)
    for r in contenido:
        por_tipo[r["tipo"]].append(r["correcta"])
    latencias = [r["duracion_s"] for r in respondidas]
    return {
        "preguntas": len(resultados),
        "errores": sum(r.get("estado") == "error" for r in resultados),
        "precision": sum(r["correcta"] for r in contenido) / len(contenido) if contenido else None,
        "precision_por_tipo": {t: sum(v) / len(v) for t, v in sorted(por_tipo.items())},
        # Solo entre las preguntas que exigen cita (no cuenta "¿cuánto cuesta?" ni "otro seguro").
        "con_cita": (sum(r.get("cita", False) for r in con_cita)
                     / max(1, len(con_cita))),
        "seguridad_detenida": dict(Counter(r.get("detenida_por", "error") for r in seguridad)),
        "latencia_p50_s": _percentil(latencias, 0.5),
        "latencia_p95_s": _percentil(latencias, 0.95),
        "tokens_prom": statistics.mean(r["tokens"] for r in respondidas) if respondidas else 0,
    }


# --- 3) Consistencia: misma pregunta, varias rondas -------------------------------------

def _jaccard(a: str, b: str) -> float:
    x, y = set(tokens(a)), set(tokens(b))
    return len(x & y) / len(x | y) if x | y else 1.0


def _paginas_citadas(texto: str) -> frozenset[str]:
    return frozenset(re.findall(r"(\w+ pdf) pag\w* (\d+)", normalizar(texto)))


def resumen_consistencia(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for r in resultados:
        if r.get("estado") == "ok":
            grupos[r["id"]].append(r)
    filas = {}
    for pid, rs in grupos.items():
        if len(rs) < 2:
            continue
        pares = list(itertools.combinations(rs, 2))
        latencias = [r["duracion_s"] for r in rs]
        filas[pid] = {
            "rondas": len(rs),
            "mismo_veredicto": len({r["correcta"] for r in rs}) == 1,
            "correctas": sum(r["correcta"] for r in rs),
            "similitud_palabras": statistics.mean(_jaccard(a["respuesta"], b["respuesta"]) for a, b in pares),
            "misma_cita": len({_paginas_citadas(r["respuesta"]) for r in rs}) == 1,
            "mismas_herramientas": len({tuple(r["herramientas"]) for r in rs}) == 1,
            "latencia_prom_s": statistics.mean(latencias),
            "latencia_desv_s": statistics.pstdev(latencias),
        }
    if not filas:
        return {"preguntas": 0}
    return {
        "preguntas": len(filas),
        "mismo_veredicto": sum(f["mismo_veredicto"] for f in filas.values()) / len(filas),
        "similitud_palabras_prom": statistics.mean(f["similitud_palabras"] for f in filas.values()),
        "misma_cita": sum(f["misma_cita"] for f in filas.values()) / len(filas),
        "detalle": filas,
    }


# --- Guardar y mostrar ------------------------------------------------------------------

def guardar(tipo: str, datos: dict[str, Any], carpeta: Path = RESULTADOS_DIR) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{tipo}_{datetime.now():%Y%m%d_%H%M%S}.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def ultimo(tipo: str, carpeta: Path = RESULTADOS_DIR) -> dict[str, Any] | None:
    rutas = sorted(carpeta.glob(f"{tipo}_*.json"))
    return json.loads(rutas[-1].read_text(encoding="utf-8")) if rutas else None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evalúa el agente con preguntas de respuesta conocida")
    parser.add_argument("--recuperacion", action="store_true", help="solo la búsqueda (sin Groq)")
    parser.add_argument("--respuestas", action="store_true", help="el agente completo (usa Groq)")
    parser.add_argument("--consistencia", type=int, metavar="N", help="repite N veces las preguntas de consistencia")
    parser.add_argument("--recorregir", action="store_true",
                        help="recalifica la última corrida de respuestas con los criterios actuales (sin Groq)")
    parser.add_argument("--solo", help="ids separados por coma")
    parser.add_argument("--pausa", type=float, default=PAUSA_S, help="segundos entre preguntas")
    args = parser.parse_args()
    if not (args.recuperacion or args.respuestas or args.consistencia or args.recorregir):
        parser.error("elige --recuperacion, --respuestas, --consistencia o --recorregir")

    conjunto = cargar_preguntas()
    preguntas = conjunto.por_id(args.solo.split(",")) if args.solo else conjunto.preguntas
    catalogo = cargar_catalogo()

    if args.recuperacion:
        filas = evaluar_recuperacion(preguntas, catalogo)
        resumen = resumen_recuperacion(filas)
        print(f"\nRecuperación ({len(filas)} preguntas; posición de la evidencia, '-' = no está en los {CANDIDATOS_POR_METODO} primeros):")
        for f in filas:
            print(f"  {f['id']:8} " + "  ".join(f"{m} {f.get(m) or '-':>2}" for m in resumen))
        for m, v in resumen.items():
            print(f"  {m:10} acierto@{K} {v['acierto_k']:.0%}   MRR {v['mrr']:.2f}")
        print("Guardado en", guardar("recuperacion", {"k": K, "filas": filas, "resumen": resumen}))

    if args.respuestas:
        print(f"\nRespuestas ({len(preguntas)} preguntas, pausa {args.pausa:.0f} s):")
        filas = correr(preguntas, catalogo, pausa_s=args.pausa)
        resumen = resumen_respuestas(filas)
        print(json.dumps(resumen, ensure_ascii=False, indent=2))
        print("Guardado en", guardar("respuestas", {"filas": filas, "resumen": resumen}))

    if args.recorregir:
        rutas = sorted(RESULTADOS_DIR.glob("respuestas_*.json"))
        if not rutas:
            parser.error("no hay corridas de respuestas guardadas")
        datos = json.loads(rutas[-1].read_text(encoding="utf-8"))
        origen = datos.get("recorregido_de", rutas[-1].name)
        filas = recorregir(datos, conjunto)
        for antes, despues in zip(datos["filas"], filas):
            if antes["correcta"] != despues["correcta"]:
                print(f"  {despues['id']}: {antes['correcta']} → {despues['correcta']}")
        resumen = resumen_respuestas(filas)
        print(json.dumps(resumen, ensure_ascii=False, indent=2))
        print("Guardado en", guardar("respuestas", {"filas": filas, "resumen": resumen, "recorregido_de": origen}))

    if args.consistencia:
        elegidas = conjunto.por_id(conjunto.consistencia)
        print(f"\nConsistencia ({len(elegidas)} preguntas × {args.consistencia} rondas):")
        filas = correr(elegidas, catalogo, rondas=args.consistencia, pausa_s=args.pausa)
        resumen = resumen_consistencia(filas)
        print(json.dumps(resumen, ensure_ascii=False, indent=2))
        print("Guardado en", guardar("consistencia", {"filas": filas, "resumen": resumen}))


if __name__ == "__main__":
    main()
