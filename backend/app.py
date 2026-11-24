"""Arranca la API, conecta sus endpoints y sirve el frontend.

  uv run uvicorn backend.app:app            → http://127.0.0.1:8000
    /             chat del cliente   (frontend/index.html)
    /panel.html   dashboard de métricas (en el servidor, solo con el link /entrar?clave=...)
    /api/...      health, chat y metrics con el formato del deploy del curso (endpoints/api.py)
    /usuarios/... registro, login y perfil (microservicio usuarios/; en local va incluido)
    /docs         documentación de la API
"""
import logging
import os
import threading
from contextlib import asynccontextmanager

# Los modelos de embeddings ya están en la caché local: no hace falta consultar internet.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from backend.config import RAIZ  # noqa: E402
from backend.endpoints import api, panel, seguros  # noqa: E402
from backend.seguridad.flujo import FrenoInundacion  # noqa: E402

log = logging.getLogger("uvicorn.error")


def calentar() -> None:
    """Carga los índices y el modelo de embeddings antes de la primera pregunta.

    En frío, la primera búsqueda tardaba ~14 s (traza de la pieza 3). Se hace en
    segundo plano: la API responde mientras tanto.
    """
    from backend.catalogo import cargar_catalogo
    from backend.herramientas.contexto import Contexto
    from backend.herramientas.documentos import buscar_documentos

    try:
        for fichas in cargar_catalogo().values():
            for ficha in fichas.values():
                buscar_documentos(Contexto(ficha), "deducible")
        log.info("Índices y embeddings listos.")
    except Exception as error:  # no impide que la API funcione
        log.warning("No se pudieron precargar los índices: %s", error)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    if os.getenv("PRECARGAR_INDICES", "true").lower() != "false":
        threading.Thread(target=calentar, daemon=True).start()
    yield


# /docs, /redoc y /openapi.json: en el servidor público se apagan (docker-compose fija
# ENABLE_DOCS=false), como en el deploy del curso. En local siguen disponibles.
_docs = os.getenv("ENABLE_DOCS", "true").lower() != "false"
app = FastAPI(
    title="Proyecto Seguros",
    lifespan=ciclo_de_vida,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)
# Primera capa: corta a una IP que inunda el servidor antes de que llegue a la app.
app.add_middleware(FrenoInundacion)
app.include_router(seguros.router)
app.include_router(panel.router)
app.include_router(api.router)

# Microservicio de usuarios: en el servidor corre en su propio contenedor y Caddy le manda
# /usuarios/* (docker-compose fija USUARIOS_EMBEBIDO=false). En local se incluye aquí
# mismo para no levantar dos procesos; el código y la base (data/usuarios.db) son los suyos.
if os.getenv("USUARIOS_EMBEBIDO", "true").strip().lower() != "false":
    from usuarios.app import asegurar_corredor_desde_entorno, router as usuarios_router

    app.include_router(usuarios_router)
    asegurar_corredor_desde_entorno()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Al final: lo que no es de la API es el frontend (html=True sirve index.html en "/").
app.mount("/", StaticFiles(directory=RAIZ / "frontend", html=True), name="frontend")
