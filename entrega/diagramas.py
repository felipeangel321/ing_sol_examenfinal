"""Diagramas del informe (SVG + PNG), dibujados a mano para que reflejen el código real.

  uv run --group notebook python entrega/diagramas.py   → docs/informe/figuras/diagrama_*.svg / .png

Coordenadas en "píxeles" con el origen arriba a la izquierda (como en una página web).
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "docs" / "informe" / "figuras"

AZUL, AZUL_SUAVE, AZUL_BORDE = "#2a78d6", "#eaf2fc", "#9cc0ee"
GRIS, GRIS_SUAVE, GRIS_BORDE, TINTA = "#6b7280", "#f3f4f6", "#d1d5db", "#1f2937"
ROJO = "#c0392b"
ESCALA = 0.74  # tamaño de letra: "px" → puntos


class Lienzo:
    def __init__(self, ancho: int, alto: int, titulo: str):
        self.fig = plt.figure(figsize=(ancho / 100, alto / 100))
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(0, ancho)
        self.ax.set_ylim(alto, 0)
        self.ax.axis("off")
        self.texto(24, 22, titulo, tam=19, color=TINTA, negrita=True)

    def texto(self, x, y, texto, tam=11.5, color=GRIS, ancla="left", negrita=False, va="top"):
        self.ax.text(x, y, texto, fontsize=tam * ESCALA, color=color, ha=ancla, va=va,
                     fontweight="bold" if negrita else "normal", zorder=5)

    def caja(self, x, y, w, h, titulo="", lineas=(), fondo=AZUL_SUAVE, borde=AZUL_BORDE, tam=13,
             centrado=False, discontinuo=False, oscuro=False):
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=8",
                                         facecolor=fondo, edgecolor=borde, linewidth=1.2,
                                         linestyle=(0, (5, 4)) if discontinuo else "-", zorder=2))
        tx, ancla = (x + w / 2, "center") if centrado else (x + 12, "left")
        ty = y + 10 if lineas or not centrado else y + h / 2
        if titulo:
            self.texto(tx, ty, titulo, tam=tam, color="white" if oscuro else TINTA, ancla=ancla, negrita=True,
                       va="top" if lineas or not centrado else "center")
            ty += tam + 7
        for linea in lineas:
            self.texto(tx, ty, linea, tam=11.5, color="#dbe8fb" if oscuro else GRIS, ancla=ancla)
            ty += 16

    def flecha(self, puntos, color=GRIS, etiqueta="", ex=0, ey=-6, discontinua=False, doble=False,
               color_etiqueta=None):
        estilo = (0, (5, 4)) if discontinua else "-"
        for (x1, y1), (x2, y2) in zip(puntos[:-2], puntos[1:-1]):
            self.ax.plot([x1, x2], [y1, y2], color=color, linewidth=1.5, linestyle=estilo, zorder=3,
                         solid_capstyle="butt")
        punta = "<|-|>" if doble and len(puntos) == 2 else "-|>"
        self.ax.annotate("", xy=puntos[-1], xytext=puntos[-2], zorder=3,
                         arrowprops=dict(arrowstyle=punta, color=color, linewidth=1.5, linestyle=estilo,
                                         shrinkA=0, shrinkB=0, mutation_scale=12))
        if doble and len(puntos) > 2:
            self.ax.annotate("", xy=puntos[0], xytext=puntos[1], zorder=3,
                             arrowprops=dict(arrowstyle="-|>", color=color, linewidth=1.5, shrinkA=0,
                                             shrinkB=0, mutation_scale=12))
        if etiqueta:
            (x1, y1), (x2, y2) = puntos[0], puntos[1]
            self.texto((x1 + x2) / 2 + ex, (y1 + y2) / 2 + ey, etiqueta, tam=10.5,
                       color=color_etiqueta or GRIS, ancla="center", va="bottom")

    def guardar(self, nombre: str) -> list[Path]:
        DESTINO.mkdir(parents=True, exist_ok=True)
        rutas = [DESTINO / f"{nombre}.svg", DESTINO / f"{nombre}.png"]
        self.fig.savefig(rutas[0], facecolor="white")
        self.fig.savefig(rutas[1], dpi=200, facecolor="white")
        plt.close(self.fig)
        return rutas


def arquitectura() -> Lienzo:
    c = Lienzo(1400, 700, "Arquitectura de la solución")
    for x, rotulo in [(30, "USUARIOS"), (270, "API, MEMORIA Y MODELO"), (530, "SERVICIO (servicio.py): camino de cada pregunta"),
                      (900, "HERRAMIENTAS DEL AGENTE"), (1160, "DATOS Y FUENTES")]:
        c.texto(x, 62, rotulo, tam=11, negrita=True)

    c.caja(30, 82, 200, 62, "Cliente", ["chat web (index.html)"], fondo=GRIS_SUAVE, borde=GRIS_BORDE)
    c.caja(30, 160, 200, 62, "Corredor / equipo", ["panel (panel.html)", "bandeja (consola)"],
           fondo=GRIS_SUAVE, borde=GRIS_BORDE)

    c.caja(270, 82, 220, 140, "API (FastAPI)", ["POST …/{seguro}/chat", "GET …/conversaciones/{id}",
                                               "GET /metricas (sin textos)", "GET /corredores/{c}/seguros"])
    c.flecha([(230, 113), (270, 113)], doble=True)
    c.flecha([(230, 190), (270, 190)], doble=True)
    c.flecha([(490, 150), (530, 150)], doble=True)

    c.caja(270, 250, 220, 90, "Memoria persistente", ["conversaciones.db (SqliteSaver)", "boveda.db: datos reales,",
                                                      "se borran a los 30 días"], fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12)
    c.caja(270, 360, 220, 90, "Groq · gpt-oss-20b", ["temp. 0 · razonamiento medio", "gratis: 8.000 tokens/min", "recibe solo marcadores"],
           fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12)
    c.caja(270, 466, 220, 90, "Trazas (.trazas/*.jsonl)", ["1 por pregunta: spans, tokens,", "latencia, reintentos, etapa",
                                                           "→ /metricas → panel"], fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12)

    # Servicio
    c.caja(530, 82, 330, 560, fondo="white", borde=AZUL_BORDE, discontinuo=True)
    c.caja(546, 96, 298, 62, "1. Límite por minuto + filtro", ["injection · fraude · datos de terceros",
                                                               "si bloquea: responde sin llamar al modelo"], tam=12)
    c.caja(546, 172, 298, 46, "2. Seudonimización (bóveda)", ["RUT, correo, teléfono, patente → [RUT_1]"], tam=12)
    c.caja(546, 232, 298, 250, "3. Agente (LangChain create_agent)", [
        "prompt base + ficha del seguro", "estado del caso: etapa, borrador, número", "",
        "Middlewares, en orden:",
        " · Tope: 5 llamadas al modelo",
        " · ContextEditing (borra búsquedas viejas)",
        " · Etapas (plan + herramientas por etapa)",
        " · ModelRetry (15/30/60 s)",
        " · 1 registro y 1 derivación por pregunta",
        " · Observador (último: ve cada reintento)",
        "", "loop: modelo → herramienta → modelo",
    ], fondo=AZUL, borde=AZUL, tam=12, oscuro=True)
    c.caja(546, 496, 298, 46, "4. Filtro de salida", ["redacta datos personales sueltos"], tam=12)
    c.caja(546, 556, 298, 46, "5. Revelar datos del propio cliente", ["marcadores → datos reales"], tam=12)
    for y1, y2 in [(158, 172), (218, 232), (482, 496), (542, 556)]:
        c.flecha([(695, y1), (695, y2)])
    c.flecha([(546, 295), (490, 295)], doble=True, discontinua=True)
    c.flecha([(546, 405), (490, 405)], doble=True, color=AZUL)
    c.flecha([(530, 511), (490, 511)], discontinua=True)

    # Herramientas y datos
    filas = [
        ("buscar_documentos", "consulta (RAG interno)", 82, "Índice híbrido por seguro", ["BM25 + MiniLM, fusión RRF", "8 pólizas PDF, 6 seguros"]),
        ("convertir_uf", "razonamiento: cálculo en código", 182, "UF del día (externa)", ["findic.cl → mindicador.cl", "→ copia local, con aviso"]),
    ]
    for nombre, tipo, y, dato, lineas in filas:
        c.caja(900, y, 220, 70, nombre, [tipo], tam=12)
        c.caja(1160, y, 220, 70, dato, lineas, fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12)
        c.flecha([(1120, y + 35), (1160, y + 35)], discontinua=True)
    c.caja(900, 282, 220, 70, "ver_campos · preparar", ["escritura: arma el borrador", "· registrar (tras el \"sí\")"], tam=12)
    c.caja(900, 372, 220, 70, "consultar_solicitud", ["consulta", "· derivar_a_persona (escritura)"], tam=12)
    c.caja(1160, 282, 220, 160, "SQLite seguros.db", ["solicitudes y derivaciones", "", "modo SIMULADO: el canal real",
                                                      "(correo, CRM) se define", "con el cliente"],
           fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12)
    c.flecha([(1120, 317), (1160, 317)], discontinua=True, doble=True)
    c.flecha([(1120, 407), (1160, 407)], discontinua=True, doble=True)
    for y in (117, 217, 317, 407):
        c.flecha([(872, 357), (872, y), (900, y)])
    c.ax.plot([844, 872], [357, 357], color=GRIS, linewidth=1.5, zorder=3)
    c.caja(900, 470, 480, 74, "Aislamiento", ["corredor, seguro y conversación los fija el servidor (contexto),",
                                              "no el modelo: un agente no lee pólizas ni solicitudes de otro."],
           fondo="white", borde=GRIS_BORDE, tam=12)
    c.texto(24, 668, "Continuas: flujo de la pregunta. Discontinuas: lectura y escritura de datos. "
                     "Azul: lo único que sale hacia el proveedor del modelo.", tam=11)
    return c


def flujo_pregunta() -> Lienzo:
    c = Lienzo(1240, 620, "Flujo de una pregunta (un turno del chat)")
    columnas = [("Cliente", 90), ("API", 260), ("Filtros y bóveda", 450), ("Agente", 660), ("Groq", 860), ("Herramientas", 1060)]
    x = dict(columnas)
    for nombre, cx in columnas:
        c.caja(cx - 75, 54, 150, 36, nombre, centrado=True, tam=12.5)
        c.ax.plot([cx, cx], [90, 560], color=GRIS_BORDE, linewidth=1.1, linestyle=(0, (4, 4)), zorder=1)
    mensajes = [
        (120, "Cliente", "API", "mensaje + id de conversación", AZUL),
        (155, "API", "Filtros y bóveda", "límite por IP · filtro de entrada", GRIS),
        (190, "Filtros y bóveda", "API", "si es un ataque: mensaje fijo (0 tokens)", ROJO),
        (225, "Filtros y bóveda", "Agente", "texto con marcadores [RUT_1] + memoria del hilo", GRIS),
        (260, "Agente", "Groq", "prompt + plan de la etapa + herramientas", GRIS),
        (295, "Groq", "Agente", "decide: buscar_documentos(\"…\")", GRIS),
        (330, "Agente", "Herramientas", "solo en las pólizas de este seguro", GRIS),
        (365, "Herramientas", "Agente", "4 fragmentos con cita [archivo · pág.]", GRIS),
        (400, "Agente", "Groq", "fragmentos + pregunta", GRIS),
        (435, "Groq", "Agente", "respuesta con citas (429 → reintento)", GRIS),
        (470, "Agente", "Filtros y bóveda", "redactar sueltos · revelar los del cliente", GRIS),
        (505, "Filtros y bóveda", "API", "respuesta + etapa + id de traza", GRIS),
        (540, "API", "Cliente", "texto, etapa, número de solicitud", AZUL),
    ]
    for y, de, a, etiqueta, color in mensajes:
        c.flecha([(x[de], y), (x[a], y)], color=color, etiqueta=etiqueta, ey=-3, discontinua=color == ROJO,
                 color_etiqueta=color if color != GRIS else TINTA)
    c.caja(24, 566, 1192, 40, fondo=GRIS_SUAVE, borde=GRIS_BORDE)
    c.texto(40, 586, "Toda la pregunta deja UNA traza: un span por filtro, por cada llamada a Groq (tokens, decisión, error) "
                     "y por cada herramienta (argumentos sin datos personales).", tam=11.5, color=TINTA, va="center")
    return c


def etapas() -> Lienzo:
    c = Lienzo(1240, 430, "Planificación: etapas del caso (estado guardado en el grafo del agente)")
    c.texto(40, 62, "En cada llamada al modelo, el plan de la etapa se agrega al prompt: datos anotados, qué falta y próximo paso.",
            tam=11.5, color=TINTA)
    nodos = [("CONSULTA", 40, ["resuelve dudas con", "buscar_documentos"]),
             ("RECOPILANDO", 360, ["pide lo que falta;", "preparar_solicitud", "valida y recuerda"]),
             ("CONFIRMANDO", 680, ["muestra el resumen", "y espera respuesta"]),
             ("REGISTRADA", 1000, ["entrega el número", "SOL-AAAAMMDD-NNNN"])]
    for nombre, x, lineas in nodos:
        oscuro = nombre == "REGISTRADA"
        c.caja(x, 110, 200, 100, nombre, lineas, fondo=AZUL if oscuro else AZUL_SUAVE,
               borde=AZUL if oscuro else AZUL_BORDE, oscuro=oscuro)
    c.flecha([(240, 150), (360, 150)], etiqueta="quiere cotizar", ey=-4)
    c.texto(300, 158, "ver_campos", tam=10, ancla="center")
    c.flecha([(560, 150), (680, 150)], etiqueta="borrador completo", ey=-4)
    c.flecha([(880, 150), (1000, 150)], etiqueta="\"sí\" sin cambios", ey=-4)
    c.texto(940, 158, "registrar", tam=10, ancla="center")
    c.flecha([(780, 210), (780, 250), (460, 250), (460, 210)])
    c.texto(620, 254, "corrige o falta un dato", tam=10.5, ancla="center")
    c.flecha([(1100, 210), (1100, 290), (140, 290), (140, 210)])
    c.texto(620, 294, "nueva consulta u otra solicitud", tam=10.5, ancla="center")
    c.caja(40, 330, 1160, 78, "Lo que decide el CÓDIGO, no el modelo", [
        "· registrar_solicitud solo se le ofrece al modelo en la etapa CONFIRMANDO (EtapasMiddleware filtra las herramientas).",
        "· Además exige un mensaje del cliente POSTERIOR al resumen que sea un \"sí\" sin \"pero\", \"cambia\" ni \"falta\".",
    ], fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12.5)
    return c


def pipeline_rag() -> Lienzo:
    c = Lienzo(1240, 356, "RAG: fuente interna (pólizas) y fuente externa (UF)")
    pasos = [
        ("PDF de pólizas", ["corredores/<c>/seguros/<s>/", "documentos/"]),
        ("Lectura y limpieza", ["PyMuPDF; quita encabezados", "repetidos en cada página"]),
        ("Fragmentos con cita", ["700 caracteres, solape 150", "archivo · página · particular", "o general · artículo · POL/CAD"]),
        ("Búsqueda híbrida", ["BM25: palabras exactas", "MiniLM: significado", "fusión RRF (k = 60)"]),
        ("Entrega al agente", ["4 fragmentos sin duplicar", "+ 300 caracteres vecinos", "≈ 1.200 tokens"]),
    ]
    x = 24
    for i, (titulo, lineas) in enumerate(pasos):
        c.caja(x, 66, 220, 100, titulo, lineas, tam=12.5, fondo=AZUL if i == 3 else AZUL_SUAVE,
               borde=AZUL if i == 3 else AZUL_BORDE, oscuro=i == 3)
        if i:
            c.flecha([(x - 24, 116), (x, 116)])
        x += 244
    c.texto(24, 182, "Un índice por seguro (.indices/<corredor>/<seguro>/). Se reconstruye solo si cambia un PDF o la ficha. "
                     "El agente de Hogar no puede leer las pólizas de Pyme.", tam=11.5, color=TINTA)
    c.caja(24, 214, 580, 120, "Fuente externa: valor de la UF (convertir_uf)", [
        "findic.cl (principal) → mindicador.cl (alternativa) → copia local (avisa).",
        "Validación: número entre 20.000 y 80.000, con fecha de hace 7 días o menos.",
        "La cuenta UF ↔ pesos la hace el código, no el modelo.",
        "Al prompt llega solo el resultado: el texto de la fuente nunca entra",
        "(sin inyección indirecta).",
    ], tam=12.5)
    c.caja(628, 214, 588, 120, "Control de contexto", [
        "ContextEditing: sobre 5.000 tokens borra los resultados de búsquedas",
        "viejas (conserva las 3 últimas).",
        "Condiciones particulares vs. generales: el agente avisa que montos y",
        "deducibles son de un plan de ejemplo; en una póliza priman las particulares.",
    ], fondo=GRIS_SUAVE, borde=GRIS_BORDE, tam=12.5)
    return c


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    for nombre, dibujo in [("diagrama_arquitectura", arquitectura), ("diagrama_flujo_pregunta", flujo_pregunta),
                           ("diagrama_etapas", etapas), ("diagrama_rag", pipeline_rag)]:
        for ruta in dibujo().guardar(nombre):
            print(ruta)


if __name__ == "__main__":
    main()
