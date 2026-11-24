import pytest
from fastapi.testclient import TestClient

from backend.agentes.cliente import construir_instrucciones
from backend.app import app
from backend.catalogo import cargar_catalogo, obtener_catalogo
from backend.endpoints.seguros import obtener_asistente
from backend.herramientas import HERRAMIENTAS_CLIENTE
from backend.herramientas.contexto import Contexto
from backend.herramientas.solicitudes import ver_campos_solicitud
from backend.servicio import Asistente
from tests.test_observabilidad import ModeloFalso


def crear_seguro(raiz, corredor, seguro, contenido="nombre: Seguro X\n"):
    carpeta = raiz / corredor / "seguros" / seguro
    carpeta.mkdir(parents=True)
    (carpeta / "ficha.yaml").write_text(contenido, encoding="utf-8")


@pytest.fixture
def cliente(tmp_path):
    crear_seguro(tmp_path, "corredor_a", "auto", "nombre: Auto de A\n")
    crear_seguro(tmp_path, "corredor_b", "vida", "nombre: Vida de B\n")
    catalogo = cargar_catalogo(tmp_path)
    app.dependency_overrides[obtener_catalogo] = lambda: catalogo
    # Nunca la memoria real de data/ ni Groq: un modelo falso que falla si se llama.
    falso = Asistente(llm=ModeloFalso(messages=iter([])), carpeta_trazas=tmp_path / "trazas")
    app.dependency_overrides[obtener_asistente] = lambda: falso
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_el_catalogo_real_carga_los_seguros_de_demo():
    catalogo = cargar_catalogo()
    assert set(catalogo["demo"]) == {
        "vehiculo", "hogar", "pyme", "responsabilidad_civil", "transporte", "salud"
    }
    assert catalogo["demo"]["vehiculo"].nombre == "Seguro de Vehículos"
    assert [d.archivo for d in catalogo["demo"]["vehiculo"].documentos] == [
        "auto_particular.pdf", "vehiculo_comercial.pdf"
    ]


def test_un_seguro_nuevo_solo_necesita_su_carpeta(tmp_path):
    crear_seguro(tmp_path, "c", "mascotas", "nombre: Mascotas\n")
    ficha = cargar_catalogo(tmp_path)["c"]["mascotas"]
    assert construir_instrucciones(ficha).startswith("Eres el asistente de Mascotas")


def test_una_ficha_con_un_error_avisa_donde_esta(tmp_path):
    crear_seguro(tmp_path, "c", "malo", "nombre: X\ncampo_mal_escrito: 1\n")
    with pytest.raises(ValueError, match="malo"):
        cargar_catalogo(tmp_path)


def test_cada_corredor_ve_solo_sus_seguros(cliente):
    respuesta = cliente.get("/corredores/corredor_a/seguros")
    assert respuesta.status_code == 200
    assert respuesta.json() == [{"id": "auto", "nombre": "Auto de A", "descripcion": ""}]


def test_no_se_llega_al_seguro_de_otro_corredor(cliente):
    r = cliente.post("/corredores/corredor_a/seguros/vida/chat", json={"mensaje": "hola"})
    assert r.status_code == 404


@pytest.mark.parametrize("corredor", ["no_existe", "..", "..%2F..", "%2e%2e"])
def test_corredores_invalidos_no_entregan_datos(cliente, corredor):
    assert cliente.get(f"/corredores/{corredor}/seguros").status_code == 404


def test_el_chat_rechaza_un_mensaje_vacio(cliente):
    r = cliente.post("/corredores/corredor_a/seguros/auto/chat", json={"mensaje": ""})
    assert r.status_code == 422


def test_las_herramientas_son_compartidas_y_usan_la_ficha(tmp_path):
    crear_seguro(
        tmp_path,
        "c",
        "auto",
        "nombre: Auto\ncampos_solicitud:\n  - {id: patente, etiqueta: Patente, obligatorio: true}\n",
    )
    ficha = cargar_catalogo(tmp_path)["c"]["auto"]
    assert ver_campos_solicitud(Contexto(ficha))[0].id == "patente"
    assert ver_campos_solicitud in HERRAMIENTAS_CLIENTE
    assert len(HERRAMIENTAS_CLIENTE) == 7
