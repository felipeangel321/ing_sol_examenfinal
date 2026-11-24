"""Lee las fichas de `corredores/` y las deja disponibles para el resto del sistema."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

RAIZ_CORREDORES = Path(__file__).resolve().parent.parent / "corredores"


class Campo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    etiqueta: str
    obligatorio: bool = False
    # Para validar el formato antes de registrar (el RUT, con su dígito verificador).
    tipo: Literal["texto", "rut", "correo", "telefono", "patente", "numero"] = "texto"


class Documento(BaseModel):
    """Un PDF de la carpeta `documentos/` del seguro."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    archivo: str
    titulo: str
    aseguradora: str = ""
    # Hasta esta página van las condiciones particulares: el plan de un cliente
    # puntual (montos, deducibles, primas). Desde la siguiente, condiciones generales.
    paginas_particulares: int = 0

    @field_validator("archivo")
    @classmethod
    def _solo_nombre_de_archivo(cls, valor: str) -> str:
        # Solo un nombre, sin carpetas: el agente nunca lee fuera de documentos/.
        if Path(valor).name != valor or valor.startswith(".") or not valor.lower().endswith(".pdf"):
            raise ValueError(f"'{valor}' debe ser el nombre de un PDF dentro de documentos/")
        return valor


class Ficha(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corredor: str
    seguro: str
    nombre: str
    descripcion: str = ""
    campos_solicitud: tuple[Campo, ...] = ()
    documentos: tuple[Documento, ...] = ()
    carpeta_documentos: Path


Catalogo = dict[str, dict[str, Ficha]]


def _subcarpetas(ruta: Path) -> list[Path]:
    if not ruta.is_dir():
        return []
    return sorted(p for p in ruta.iterdir() if p.is_dir() and p.name[0] not in "._")


def _cargar_ficha(corredor: str, carpeta: Path) -> Ficha:
    ruta = carpeta / "ficha.yaml"
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        return Ficha(
            **datos,
            corredor=corredor,
            seguro=carpeta.name,
            carpeta_documentos=carpeta / "documentos",
        )
    except Exception as error:
        raise ValueError(f"Ficha inválida en {ruta}: {error}") from error


def cargar_catalogo(raiz: Path = RAIZ_CORREDORES) -> Catalogo:
    """Recorre las carpetas y devuelve {corredor: {seguro: ficha}}.

    Los identificadores que llegan por la URL solo se buscan en este diccionario,
    nunca se usan para armar rutas de archivos. Así, nadie puede salir de su
    carpeta ni leer la de otro corredor.
    """
    return {
        corredor.name: {
            seguro.name: _cargar_ficha(corredor.name, seguro)
            for seguro in _subcarpetas(corredor / "seguros")
        }
        for corredor in _subcarpetas(raiz)
    }


@lru_cache
def obtener_catalogo() -> Catalogo:
    return cargar_catalogo()
