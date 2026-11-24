"""Herramientas compartidas por todos los agentes de cliente."""
from backend.herramientas.derivacion import derivar_a_persona
from backend.herramientas.documentos import buscar_documentos
from backend.herramientas.indicadores import convertir
from backend.herramientas.solicitudes import (
    consultar_solicitud,
    registrar_solicitud,
    revisar_datos,
    ver_campos_solicitud,
)

HERRAMIENTAS_CLIENTE = (
    buscar_documentos,
    ver_campos_solicitud,
    revisar_datos,  # preparar_solicitud: arma el borrador sin guardar
    registrar_solicitud,
    consultar_solicitud,
    convertir,  # convertir_uf: valor de la UF del día (fuente externa)
    derivar_a_persona,
)
