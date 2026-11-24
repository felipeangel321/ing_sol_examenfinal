"""Configuración central: rutas y modelos (lee el archivo .env de la raíz)."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

# Índices de búsqueda de cada seguro. Se generan solos desde los PDF.
INDICES_DIR = RAIZ / ".indices"

# Groq: gpt-oss-20b es estable con herramientas (en Pampasur, el 120b inventó un
# nombre de herramienta). Se puede cambiar en .env sin tocar el código.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_REASONING = os.getenv("GROQ_REASONING", "medium")

# Embeddings locales: no usan API key; el modelo queda en la caché de Hugging Face.
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


def hay_groq() -> bool:
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def busqueda_semantica_activa() -> bool:
    """false: busca solo por palabras (más rápido, sin cargar el modelo de embeddings)."""
    return os.getenv("BUSQUEDA_SEMANTICA", "true").strip().lower() != "false"


def get_llm():
    from langchain_groq import ChatGroq

    # max_retries=0: el cliente de Groq reintentaba los 429 por dentro (13-20 s cada uno) y
    # la traza no lo veía (marcaba 0 reintentos). Ahora reintenta ModelRetryMiddleware,
    # y cada intento fallido queda como span "modelo" con estado error.
    return ChatGroq(model=GROQ_MODEL, temperature=0, reasoning_effort=GROQ_REASONING, max_retries=0)
