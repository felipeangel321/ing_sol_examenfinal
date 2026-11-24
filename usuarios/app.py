"""API del microservicio de usuarios.

En el servidor corre solo, en su contenedor:  uvicorn usuarios.app:app --port 8001
(Caddy le manda todo lo que empieza con /usuarios/). En local, la app del asistente
incluye este mismo router para no tener que levantar dos procesos (backend/app.py).

Seguridad (OWASP: identificación y autenticación):
- La contraseña se guarda como hash scrypt con sal; nunca en texto plano ni en los logs.
- El correo no se repite: UNIQUE en la base (almacen.py) → 409.
- Login con error genérico ("correo o contraseña incorrectos"): no delata qué correos
  existen, y tarda lo mismo exista o no el correo (HASH_FALSO).
- Límites: registros por IP y por día; intentos de login por IP y por IP+correo (contra
  fuerza bruta y contra el costo de scrypt). Superarlos responde 429.
- La sesión va en una cookie HttpOnly (JavaScript no la lee), Secure por HTTPS y
  SameSite=Lax (otro sitio no puede mandar peticiones con ella). Los clientes de API
  pueden usar el token en "Authorization: Bearer ...".
"""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from usuarios import almacen, contrasenas
from usuarios.limites import FrenoInundacion, Limitador
from usuarios.tokens import DURACION_S, crear_token, verificar_token

COOKIE = "sesion"
CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,100}\.[a-z]{2,24}$")

registros_ip = Limitador(maximo=5, ventana_s=3600)       # 5 cuentas por hora por IP
registros_dia = Limitador(maximo=200, ventana_s=24 * 3600)  # y 200 en total al día
intentos_ip = Limitador(maximo=20, ventana_s=900)         # 20 logins cada 15 min por IP
fallos_cuenta = Limitador(maximo=5, ventana_s=900)        # 5 fallos por IP+correo

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


class Registro(BaseModel):
    correo: str = Field(..., max_length=170)
    nombre: str = Field(..., min_length=1, max_length=80)
    contrasena: str = Field(..., min_length=8, max_length=128)


class Login(BaseModel):
    correo: str = Field(..., max_length=170)
    contrasena: str = Field(..., min_length=1, max_length=128)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _normalizar(correo: str) -> str:
    return correo.strip().lower()


def token_de(request: Request) -> str | None:
    """Cookie de sesión (navegador) o cabecera Authorization: Bearer (clientes de API)."""
    cabecera = request.headers.get("authorization", "")
    if cabecera.lower().startswith("bearer "):
        return cabecera[7:].strip()
    return request.cookies.get(COOKIE)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "servicio": "usuarios"}


@router.post("/registro", status_code=201)
def registrar(cuerpo: Registro, request: Request) -> dict:
    correo, nombre = _normalizar(cuerpo.correo), " ".join(cuerpo.nombre.split())
    if not CORREO.fullmatch(correo):
        raise HTTPException(status_code=422, detail="El correo no tiene un formato válido.")
    if not nombre or any(ord(c) < 32 for c in nombre):
        raise HTTPException(status_code=422, detail="El nombre no es válido.")
    if not registros_ip.permitir(_ip(request)) or not registros_dia.permitir("total"):
        raise HTTPException(status_code=429, detail="Demasiados registros. Intenta más tarde.")
    usuario = almacen.crear(correo, nombre, contrasenas.hashear(cuerpo.contrasena))
    if usuario is None:
        raise HTTPException(status_code=409, detail="Ese correo ya tiene cuenta. Inicia sesión.")
    return usuario.publico()


@router.post("/login")
def iniciar_sesion(cuerpo: Login, request: Request, respuesta: Response) -> dict:
    correo, ip = _normalizar(cuerpo.correo), _ip(request)
    if not intentos_ip.permitir(ip) or not fallos_cuenta.queda(f"{ip}|{correo}"):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos.")
    usuario = almacen.por_correo(correo)
    valida = contrasenas.verificar(cuerpo.contrasena, usuario.hash if usuario else contrasenas.HASH_FALSO)
    if not (usuario and valida):
        fallos_cuenta.permitir(f"{ip}|{correo}")
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
    token = crear_token(usuario.id, usuario.correo, usuario.rol)
    respuesta.set_cookie(COOKIE, token, max_age=DURACION_S, httponly=True,
                         secure=request.url.scheme == "https", samesite="lax")
    return {"token": token, "tipo": "bearer", "expira_en_s": DURACION_S, "usuario": usuario.publico()}


@router.post("/logout")
def cerrar_sesion(respuesta: Response) -> dict:
    respuesta.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/yo")
def yo(request: Request) -> dict:
    datos = verificar_token(token_de(request))
    usuario = almacen.por_id(int(datos["sub"])) if datos else None
    if usuario is None:
        raise HTTPException(status_code=401, detail="Inicia sesión.")
    return usuario.publico()


def asegurar_corredor_desde_entorno() -> None:
    """La cuenta del corredor (rol con acceso al panel) sale de CORREDOR_CORREO y
    CORREDOR_CONTRASENA del .env, que iniciar.sh genera. Sin ellas, no hay corredor."""
    correo = _normalizar(os.getenv("CORREDOR_CORREO", ""))
    contrasena = os.getenv("CORREDOR_CONTRASENA", "")
    if CORREO.fullmatch(correo) and len(contrasena) >= 12:
        almacen.asegurar_corredor(correo, "Corredor", contrasenas.hashear(contrasena))


@asynccontextmanager
async def _ciclo(_app: FastAPI):
    asegurar_corredor_desde_entorno()
    yield


_docs = os.getenv("ENABLE_DOCS", "true").lower() != "false"
app = FastAPI(title="Servicio de usuarios", lifespan=_ciclo, docs_url="/usuarios/docs" if _docs else None,
              redoc_url=None, openapi_url="/usuarios/openapi.json" if _docs else None)
app.add_middleware(FrenoInundacion)
app.include_router(router)
