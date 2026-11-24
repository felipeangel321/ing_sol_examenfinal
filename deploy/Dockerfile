# Imagen del asistente de seguros: API FastAPI + chat + panel en un solo contenedor.
# Se construye desde la raíz del repo:  docker build -f deploy/Dockerfile .
# (docker-compose.prod.yml ya lo hace así).
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HOME=/opt/hf \
    PATH="/opt/venv/bin:$PATH"

# uv, la misma versión que se usa en local.
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

WORKDIR /app

# 1) Dependencias primero: esta capa se reutiliza mientras no cambie uv.lock.
#    En Linux, torch viene del índice CPU (ver [tool.uv.sources] en pyproject.toml):
#    sin eso se instalarían varios GB de CUDA que una EC2 sin GPU no usa.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Modelo de embeddings (~470 MB) dentro de la imagen. La app corre con
#    HF_HUB_OFFLINE=1, así que en el servidor no podría descargarlo después.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# 3) Código, frontend y pólizas.
COPY backend ./backend
# La app verifica los tokens del microservicio de usuarios (usuarios/tokens.py);
# la base de usuarios NO entra aquí: vive en el contenedor usuarios.
COPY usuarios ./usuarios
COPY frontend ./frontend
COPY corredores ./corredores

# Los PDF no están en git: si faltan, el build se detiene con un mensaje claro
# en vez de levantar un asistente que no encuentra nada.
RUN if [ -z "$(find corredores -name '*.pdf' | head -n 1)" ]; then \
      echo "ERROR: faltan las pólizas (PDF) en corredores/. Descomprime"; \
      echo "entrega/documentos_demo.zip en la raíz del repo (ver deploy/README.md)."; \
      exit 1; \
    fi

# 4) Índices de búsqueda listos de fábrica: el primer cliente no espera ~3 min.
RUN HF_HUB_OFFLINE=1 python -m backend.indice

# Usuario sin privilegios (como en el deploy del curso). data/ y .trazas/ son
# volúmenes: se crean aquí con el dueño correcto para que Docker lo herede.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p data .trazas \
 && chown -R appuser /app/data /app/.trazas /app/.indices
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health'); sys.exit(0)" || exit 1

# Solo se acepta X-Forwarded-For del proxy de confianza (Caddy, IP fija en el compose).
# Sin --proxy-headers, request.client.host sería siempre la IP de Caddy y el límite
# por minuto sería un solo cupo compartido por todos los clientes.
# Por defecto solo localhost: valor seguro si alguien corre esta imagen suelta.
ENV FORWARDED_ALLOW_IPS=127.0.0.1

# Un solo proceso a propósito: los límites (por minuto y diario) viven en memoria y
# SQLite no se lleva bien con varios procesos escribiendo a la vez.
# `exec` deja a uvicorn como PID 1 para que reciba las señales de docker stop.
CMD ["sh", "-c", "exec uvicorn backend.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
