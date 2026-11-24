"""Herramientas de escritura: registrar solicitud, consultar y derivar (sin Groq)."""
import pytest

from backend import almacen
from backend.catalogo import cargar_catalogo
from backend.herramientas.contexto import Contexto
from backend.herramientas.derivacion import derivar_a_persona
from backend.herramientas.solicitudes import consultar_solicitud, registrar_solicitud, rut_valido
from backend.seguridad import Boveda
from tests.test_documentos import crear_seguro

CAMPOS = """campos_solicitud:
  - {id: nombre, etiqueta: Nombre, obligatorio: true}
  - {id: rut, etiqueta: RUT, obligatorio: true, tipo: rut}
  - {id: patente, etiqueta: Patente, obligatorio: true, tipo: patente}
  - {id: telefono, etiqueta: Teléfono, tipo: telefono}
"""


@pytest.fixture(autouse=True)
def base_temporal(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSQUEDA_SEMANTICA", "false")
    monkeypatch.setattr("backend.indice.INDICES_DIR", tmp_path / "indices")
    monkeypatch.setattr(almacen, "BASE_DATOS", tmp_path / "data" / "seguros.db")


def _ficha(tmp_path, corredor="demo"):
    carpeta = crear_seguro(tmp_path / "corredores", corredor, "vehiculo", ["Artículo 1: daños propios."])
    ficha_yaml = carpeta / "ficha.yaml"
    ficha_yaml.write_text(ficha_yaml.read_text(encoding="utf-8") + CAMPOS, encoding="utf-8")
    return cargar_catalogo(tmp_path / "corredores")[corredor]["vehiculo"]


@pytest.fixture
def ficha(tmp_path):
    return _ficha(tmp_path)


@pytest.mark.parametrize("rut, valido", [
    ("12.345.678-5", True), ("12345678-5", True), ("11.111.111-1", True), ("10.000.013-K", True), ("10.000.013-k", True), ("10.000.013-1", False),
    ("12.345.678-9", False), ("abc", False),
])
def test_rut_con_digito_verificador(rut, valido):
    assert rut_valido(rut) is valido


def test_registra_con_los_datos_reales_y_descarta_lo_que_la_ficha_no_pide(ficha):
    boveda = Boveda()
    texto = boveda.seudonimizar("h1", "RUT 12.345.678-5, patente GTVJ39")
    assert "[RUT_1]" in texto and "[PATENTE_1]" in texto
    contexto = Contexto(ficha, "h1", boveda)

    resultado = registrar_solicitud(contexto, {
        "nombre": "Ana Pérez", "rut": "[RUT_1]", "patente": "[PATENTE_1]",
        "diagnostico": "diabetes",  # dato que la ficha no pide: no se guarda
    })

    assert resultado.registrada and resultado.numero.startswith("SOL-")
    assert resultado.descartados == ["diagnostico"]
    (fila,) = almacen.listar("solicitudes")
    assert fila["datos"] == {"nombre": "Ana Pérez", "rut": "12.345.678-5", "patente": "GTVJ39"}
    assert fila["thread_id"] == "h1"


def test_no_registra_si_falta_un_obligatorio_o_el_rut_es_invalido(ficha):
    resultado = registrar_solicitud(Contexto(ficha), {"nombre": "Ana", "rut": "12.345.678-9"})
    assert not resultado.registrada
    assert any("RUT" in p for p in resultado.problemas)
    assert any("Patente" in p for p in resultado.problemas)
    assert almacen.listar("solicitudes") == []


@pytest.mark.parametrize("relleno", ["pendiente", "N/A", "no tiene", "-", ""])
def test_un_opcional_sin_dato_no_bloquea_la_solicitud(ficha, relleno):
    # Error real con Groq: el modelo puso "pendiente" en el teléfono opcional.
    resultado = registrar_solicitud(Contexto(ficha), {
        "nombre": "Ana", "rut": "12.345.678-5", "patente": "GTVJ39", "telefono": relleno,
    })
    assert resultado.registrada, resultado.problemas
    assert "telefono" not in almacen.listar("solicitudes")[0]["datos"]


def test_un_marcador_de_otra_conversacion_no_se_acepta(ficha):
    boveda = Boveda()
    boveda.seudonimizar("otro-hilo", "RUT 12.345.678-5")
    resultado = registrar_solicitud(Contexto(ficha, "h1", boveda),
                                    {"nombre": "Ana", "rut": "[RUT_1]", "patente": "GTVJ39"})
    assert not resultado.registrada
    assert "no corresponde a esta conversación" in resultado.problemas[0]


def test_consultar_entrega_el_estado_sin_datos_y_solo_del_mismo_corredor(ficha, tmp_path):
    numero = registrar_solicitud(Contexto(ficha), {"nombre": "Ana", "rut": "12.345.678-5", "patente": "GTVJ39"}).numero
    registro = consultar_solicitud(Contexto(ficha), numero)
    assert registro.estado == "recibida" and not hasattr(registro, "datos")

    otro = _ficha(tmp_path, corredor="otro")
    assert consultar_solicitud(Contexto(otro), numero) is None


def test_derivar_deja_un_aviso_con_el_contacto_real(ficha):
    boveda = Boveda()
    boveda.seudonimizar("h1", "+56 9 1234 5678")
    numero = derivar_a_persona(Contexto(ficha, "h1", boveda), "Siniestro en curso", "alta", "[TELEFONO_1]")
    (fila,) = almacen.listar("derivaciones")
    assert numero.startswith("DER-") and fila["urgencia"] == "alta"
    assert fila["contacto"] == "+56 9 1234 5678"
