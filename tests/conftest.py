"""Configuración común de las pruebas."""
import os

# El freno de inundación (seguridad/flujo.py) cuenta todas las peticiones de la app por
# IP, y en las pruebas todas vienen de "testclient": se sube el límite para que no corte
# pruebas que no tienen que ver con él. Su prueba propia usa una app aparte.
os.environ.setdefault("LIMITE_PETICIONES_MIN", "1000000")

# El chat pide sesión (microservicio de usuarios). Las pruebas antiguas prueban el chat
# en sí y corren sin login; tests/test_usuarios.py lo enciende y prueba el flujo completo.
os.environ.setdefault("EXIGIR_LOGIN", "false")

# Las pruebas nunca envían nada a LangSmith, aunque el .env local lo tenga encendido.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
