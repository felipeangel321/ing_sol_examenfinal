"""Chat local con los agentes de cliente, en la consola.

El cliente elige el seguro que le interesa y conversa con el agente de ese seguro,
que solo consulta las pólizas de esa carpeta. La conversación se guarda en data/
(mensajes + etapa del caso), así que se puede retomar después de cerrar el chat.

Uso:
  uv run python -m backend.chat                    # muestra el menú de seguros
  uv run python -m backend.chat --seguro hogar     # entra directo a un seguro
  uv run python -m backend.chat --seguro hogar --conversacion demo-hogar-1a2b3c4d   # retoma una

Dentro del chat: "menu" vuelve a elegir seguro y "salir" termina.
"""
import argparse
import os
import sys
import uuid

# El modelo de embeddings ya está en la caché local: no hace falta consultar internet.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from backend.catalogo import Ficha, cargar_catalogo  # noqa: E402
from backend.config import hay_groq  # noqa: E402
from backend.indice import cargar_indice  # noqa: E402
from backend.servicio import Asistente  # noqa: E402

SALIR = {"salir", "exit", "chao"}
MENU = {"menu", "menú", "cambiar"}


def elegir_seguro(seguros: dict[str, Ficha]) -> Ficha | None:
    fichas = list(seguros.values())
    print("\n¿Sobre qué seguro quieres consultar?")
    for i, ficha in enumerate(fichas, start=1):
        print(f"  {i}. {ficha.nombre}")
    while True:
        opcion = input("Elige un número (o 'salir'): ").strip().lower()
        if opcion in SALIR or not opcion:
            return None
        if opcion.isdigit() and 1 <= int(opcion) <= len(fichas):
            return fichas[int(opcion) - 1]
        if opcion in seguros:
            return seguros[opcion]
        print("No encontré esa opción.")


def conversar(ficha: Ficha, asistente: Asistente, thread_id: str | None = None) -> bool:
    """Conversa con el agente del seguro. Devuelve True si el usuario pidió el menú."""
    print(f"\nPreparando los documentos de {ficha.nombre}...", flush=True)
    cargar_indice(ficha, progreso=True)  # la primera vez construye el índice
    if thread_id:
        caso = asistente.estado_caso(ficha, thread_id)
        print(f"\nRetomando la conversación {thread_id}: {caso['mensajes']} mensajes guardados, "
              f"etapa '{caso['etapa']}'" + (f", {caso['numero']}" if caso["numero"] else ""))
    else:
        thread_id = f"{ficha.corredor}-{ficha.seguro}-{uuid.uuid4().hex[:8]}"
    print(f"(Para retomarla después: --seguro {ficha.seguro} --conversacion {thread_id})")
    print(f"\nAsistente de {ficha.nombre}. Escribe tu pregunta ('menu' para cambiar de seguro, 'salir' para terminar).\n")
    while True:
        pregunta = input("Tú: ").strip()
        if not pregunta:
            continue
        if pregunta.lower() in SALIR:
            return False
        if pregunta.lower() in MENU:
            return True
        try:
            # Seguridad + agente + traza en .trazas/ (ver backend/servicio.py).
            r = asistente.responder(ficha, thread_id, pregunta)
        except Exception as error:  # 429 de cuota o 400 tool_use_failed de Groq tras los reintentos
            print(f"\n(No pude responder: {type(error).__name__}: {error}. Reformula o espera un minuto.)\n")
            continue
        print(f"\nAsistente: {r.texto}\n")
        estado = f" · BLOQUEADA ({r.categoria})" if r.estado == "bloqueado" else f" · etapa {r.etapa}"
        print(
            f"  [traza {r.trace_id} · {r.duracion_ms / 1000:.1f} s"
            f" · {r.tokens_entrada}+{r.tokens_salida} tokens{estado}]\n"
        )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Chat local con los agentes de seguros.")
    parser.add_argument("--corredor", default="demo")
    parser.add_argument("--seguro", help="id del seguro (carpeta), por ejemplo: hogar")
    parser.add_argument("--conversacion", help="retoma una conversación guardada (requiere --seguro)")
    args = parser.parse_args()

    if not hay_groq():
        sys.exit("Falta GROQ_API_KEY en el archivo .env (copia .env.example como .env).")
    seguros = cargar_catalogo().get(args.corredor)
    if not seguros:
        sys.exit(f"No existe el corredor '{args.corredor}' en corredores/")
    if args.seguro and args.seguro not in seguros:
        sys.exit(f"'{args.seguro}' no es un seguro de {args.corredor}. Opciones: {', '.join(seguros)}")

    if args.conversacion and not args.seguro:
        sys.exit("Para retomar una conversación indica también --seguro.")

    asistente = Asistente.persistente()  # memoria en data/ (sobrevive al reinicio)
    ficha = seguros[args.seguro] if args.seguro else elegir_seguro(seguros)
    retomar = args.conversacion
    while ficha and conversar(ficha, asistente, retomar):
        retomar = None
        ficha = elegir_seguro(seguros)
    print("¡Hasta luego!")


if __name__ == "__main__":
    main()
