"""Datos y registro de las solicitudes del cliente."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend import almacen
from backend.catalogo import Campo
from backend.herramientas.contexto import Contexto


def ver_campos_solicitud(contexto: Contexto) -> tuple[Campo, ...]:
    """Devuelve los datos que pide este seguro para una solicitud."""
    return contexto.ficha.campos_solicitud


def rut_valido(rut: str) -> bool:
    """Revisa el dígito verificador (módulo 11)."""
    limpio = re.sub(r"[.\s-]", "", rut).upper()
    if not re.fullmatch(r"\d{7,8}[\dK]", limpio):
        return False
    cuerpo, dv = limpio[:-1], limpio[-1]
    suma = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(cuerpo)))
    esperado = {11: "0", 10: "K"}.get(11 - suma % 11, str(11 - suma % 11))
    return dv == esperado


_FORMATOS = {
    "correo": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "telefono": re.compile(r"(?:\+?56)?\s?9?\s?\d{4}\s?\d{4}"),
    "patente": re.compile(r"[A-Za-z]{2}[.\-·]?[A-Za-z]{2}[.\-·]?\d{2}(?:-\d)?|[A-Za-z]{2}[.\-·]?\d{2}[.\-·]?\d{2}"),
    "numero": re.compile(r"\d+(?:[.,]\d+)?"),
}


def _problema_de_formato(campo: Campo, valor: str) -> str | None:
    if campo.tipo == "rut":
        return None if rut_valido(valor) else f"{campo.etiqueta}: el RUT no es válido (revisa el dígito verificador)"
    patron = _FORMATOS.get(campo.tipo)
    if patron and not patron.fullmatch(valor.strip().replace(".", "") if campo.tipo == "numero" else valor.strip()):
        return f"{campo.etiqueta}: el formato no es válido"
    return None


_SIN_DATO = re.compile(
    r"|-+|n/?a|none|null|no|pendiente|no aplica|no informad[oa]|sin (?:dato|telefono|teléfono|informacion|información)"
    r"|no tiene|no indica|no entregad[oa]|desconocid[oa]"
)


_MARCADOR = re.compile(r"\[(RUT|CORREO|TELEFONO|PATENTE)_\d+\]")


def es_sin_dato(valor: str) -> bool:
    """ "", "pendiente", "N/A", "no tiene"...: el cliente no entregó ese dato."""
    return bool(_SIN_DATO.fullmatch(str(valor).strip().lower()))


@dataclass
class Revision:
    """Resultado de revisar los datos de una solicitud contra la ficha, SIN guardar nada."""

    validos: dict[str, str] = field(default_factory=dict)  # con marcadores: lo que ve el modelo
    reales: dict[str, str] = field(default_factory=dict)  # con los datos reales: lo que se guarda
    problemas: list[str] = field(default_factory=list)  # formato inválido (nombra el campo, no el valor)
    faltantes: list[str] = field(default_factory=list)  # obligatorios sin dato
    descartados: list[str] = field(default_factory=list)  # campos que la ficha no pide

    @property
    def completa(self) -> bool:
        return not self.problemas and not self.faltantes


def revisar_datos(contexto: Contexto, datos: dict[str, str]) -> Revision:
    """Valida los datos contra la ficha: obligatorios, formato y RUT.

    - Solo cuentan los campos que la ficha pide (minimización de datos): si el modelo
      juntó algo de más, se descarta.
    - Los marcadores ([RUT_1]) se cambian por el dato real solo para validarlo.
    """
    campos = {c.id: c for c in contexto.ficha.campos_solicitud}
    revision = Revision(descartados=[k for k in datos if k not in campos])
    if not campos:
        revision.problemas.append("este seguro aún no tiene definidos los datos de la solicitud")
    for campo in campos.values():
        marcado = str(datos.get(campo.id, "")).strip()
        real = contexto.revelar(marcado)
        # Encontrado en la prueba con Groq: el modelo llenaba el teléfono opcional con
        # "pendiente" y eso bloqueaba toda la solicitud por "formato no válido".
        if es_sin_dato(real):
            if campo.obligatorio:
                revision.faltantes.append(campo.etiqueta)
            continue
        if _MARCADOR.search(real):
            revision.problemas.append(f"{campo.etiqueta}: el dato no corresponde a esta conversación")
            continue
        if problema := _problema_de_formato(campo, real):
            revision.problemas.append(problema)
            continue
        revision.validos[campo.id] = marcado
        revision.reales[campo.id] = real
    return revision


@dataclass
class ResultadoSolicitud:
    numero: str = ""
    problemas: list[str] = field(default_factory=list)
    descartados: list[str] = field(default_factory=list)  # campos que la ficha no pide

    @property
    def registrada(self) -> bool:
        return bool(self.numero)


def registrar_solicitud(contexto: Contexto, datos: dict[str, str]) -> ResultadoSolicitud:
    """Revisa los datos y, si están completos y válidos, registra la solicitud.

    Si falta un obligatorio o un formato no es válido, no se registra nada y se
    devuelven los problemas para que el agente se los pida al cliente.
    """
    revision = revisar_datos(contexto, datos)
    resultado = ResultadoSolicitud(
        problemas=revision.problemas + [f"falta {f}" for f in revision.faltantes],
        descartados=revision.descartados,
    )
    if resultado.problemas:
        return resultado
    resultado.numero = almacen.guardar_solicitud(
        contexto.ficha.corredor, contexto.ficha.seguro, contexto.thread_id, revision.reales
    )
    return resultado


def consultar_solicitud(contexto: Contexto, numero: str) -> almacen.Registro | None:
    """Estado de una solicitud o derivación del MISMO corredor, sin datos personales."""
    return almacen.buscar_registro(numero, contexto.ficha.corredor)
