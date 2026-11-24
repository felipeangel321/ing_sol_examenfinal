"""Panel de métricas (lo ve el dueño de la demo o el corredor, no el cliente) y acceso.

/metricas solo entrega números, etapas y nombres de herramientas: ninguna pregunta ni
respuesta. En el servidor (con CLAVE_ACCESO) el panel y /metricas quedan solo para el
dueño, que entra una vez con el link secreto /entrar?clave=... (seguridad/acceso.py).
En local, sin clave, siguen abiertos como antes. Los tres contadores públicos, como en
el deploy del curso, están en /api/metrics.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from backend.config import RAIZ
from backend.observabilidad import leer_trazas
from backend.observabilidad.reporte import panel
from backend.seguridad.acceso import COOKIE, clave_correcta, clave_configurada, exigir_dueno, ficha_de

router = APIRouter(tags=["panel"])

TREINTA_DIAS_S = 30 * 24 * 3600


@router.get("/metricas", dependencies=[Depends(exigir_dueno)])
def metricas(seguro: str | None = None) -> dict:
    trazas = leer_trazas()
    if seguro:
        trazas = [t for t in trazas if t["seguro"] == seguro]
    return panel(trazas)


# Va antes que los archivos estáticos (app.py monta el frontend al final), así que
# /panel.html pasa por aquí y no se sirve directo.
@router.get("/panel.html", include_in_schema=False, dependencies=[Depends(exigir_dueno)])
def pagina_panel() -> FileResponse:
    return FileResponse(RAIZ / "frontend" / "panel.html")


@router.get("/entrar", include_in_schema=False)
def entrar(request: Request, clave: str = "") -> RedirectResponse:
    """Link secreto del dueño: deja la cookie y abre el panel."""
    if not clave_correcta(clave):
        raise HTTPException(status_code=403, detail="Acceso denegado.")
    respuesta = RedirectResponse("/panel.html", status_code=303)
    respuesta.set_cookie(
        COOKIE, ficha_de(clave_configurada()), max_age=TREINTA_DIAS_S, httponly=True,
        secure=request.url.scheme == "https", samesite="lax",
    )
    return respuesta
