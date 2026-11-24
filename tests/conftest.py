"""Configuración común de las pruebas."""
import os

# El freno de inundación (seguridad/flujo.py) cuenta todas las peticiones de la app por
# IP, y en las pruebas todas vienen de "testclient": se sube el límite para que no corte
# pruebas que no tienen que ver con él. Su prueba propia usa una app aparte.
os.environ.setdefault("LIMITE_PETICIONES_MIN", "1000000")
