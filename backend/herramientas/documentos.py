"""Búsqueda en los documentos del seguro."""
from backend.herramientas.contexto import Contexto
from backend.indice import cargar_indice

# Cada búsqueda devuelve ~4.000 caracteres (~1.200 tokens): el plan gratuito de Groq
# admite 8.000 tokens por minuto, y una pregunta puede necesitar 2 o 3 búsquedas.
FRAGMENTOS_POR_BUSQUEDA = 4
VECINOS = 1  # se agrega el final del fragmento anterior y el inicio del siguiente
MARGEN_VECINOS = 300  # caracteres de cada vecino


def buscar_documentos(contexto: Contexto, consulta: str) -> list[str]:
    """Devuelve los fragmentos de los documentos del seguro que responden la consulta.

    Solo busca en el índice del seguro de la conversación (lo fija el servidor en el
    contexto), así que nunca entrega texto de otro seguro ni de otro corredor.
    Cada fragmento va con su cita: archivo, página, tipo de condición y sección.
    """
    fragmentos = cargar_indice(contexto.ficha).buscar_con_contexto(
        consulta, k=FRAGMENTOS_POR_BUSQUEDA, vecinos=VECINOS, margen=MARGEN_VECINOS
    )
    return [f"[{f.cita()}]\n{f.texto}" for f in fragmentos]
