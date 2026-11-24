"""Set de evaluación y su corrección automática (sin Groq)."""
import pytest
from langchain_core.messages import AIMessage

from backend.catalogo import cargar_catalogo
from backend.evaluacion import evaluar
from backend.evaluacion.evaluar import (
    Pregunta,
    cargar_preguntas,
    contiene,
    resumen_consistencia,
    resumen_respuestas,
    revisar_respuesta,
)
from backend.indice import cargar_indice
from backend.seguridad import LimitadorTasa, validar_entrada
from backend.servicio import Asistente
from tests.test_observabilidad import ModeloFalso, _uso


@pytest.fixture(autouse=True)
def solo_palabras(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSQUEDA_SEMANTICA", "false")
    monkeypatch.setattr("backend.indice.INDICES_DIR", tmp_path / "indices")


CONJUNTO = cargar_preguntas()


def test_el_set_es_valido_y_cada_pregunta_es_de_un_seguro_existente():
    seguros = cargar_catalogo()["demo"]
    assert len(CONJUNTO.preguntas) >= 15
    assert all(p.seguro in seguros for p in CONJUNTO.preguntas)
    assert all(p.debe_decir for p in CONJUNTO.preguntas)
    assert CONJUNTO.por_id(CONJUNTO.consistencia)  # las de consistencia existen


@pytest.mark.parametrize("pregunta", [p for p in CONJUNTO.preguntas if p.evidencia], ids=lambda p: p.id)
def test_la_evidencia_esperada_existe_en_las_polizas(pregunta):
    # Si la evidencia no estuviera en ningún fragmento, la pregunta sería imposible.
    indice = cargar_indice(cargar_catalogo()["demo"][pregunta.seguro])
    assert any(contiene(f.texto, pregunta.evidencia) for f in indice.fragmentos)


def test_los_filtros_no_bloquean_el_texto_de_las_polizas():
    # Falsos positivos: un fragmento real de póliza no debe parecer ataque, fraude ni pedido de
    # datos de terceros ("infligir daño" caía en el patrón de "inflar" hasta que se corrigió).
    for ficha in cargar_catalogo()["demo"].values():
        for f in cargar_indice(ficha).fragmentos:
            assert validar_entrada(f.texto[:2000]).permitido, (ficha.seguro, f.pagina, f.texto[:120])


def test_la_correccion_acepta_sinonimos_y_exige_la_cita():
    p = CONJUNTO.por_id(["hog-01"])[0]
    assert revisar_respuesta(p, "Tienes treinta días corridos (hogar.pdf, pág. 10).")["correcta"]
    assert not revisar_respuesta(p, "Tienes 30 días corridos.")["correcta"]  # sin cita
    assert not revisar_respuesta(p, "Tienes 10 días (hogar.pdf, pág. 10).")["correcta"]


def test_una_exclusion_se_reconoce_aunque_se_diga_de_otra_forma():
    p = CONJUNTO.por_id(["veh-02"])[0]
    for texto in ["No, no está cubierto si manejas en estado de ebriedad (auto_particular.pdf, pág. 21).",
                  "Es una exclusión: conducir bajo la influencia del alcohol (auto_particular.pdf, pág. 21)."]:
        assert revisar_respuesta(p, texto)["correcta"], texto


def test_la_inyeccion_del_set_la_bloquea_el_filtro():
    p = CONJUNTO.por_id(["seg-01"])[0]
    assert validar_entrada(p.pregunta).categoria == p.bloqueo


def test_correr_el_set_con_un_modelo_falso(tmp_path):
    preguntas = CONJUNTO.por_id(["hog-01", "seg-01"])
    modelo = ModeloFalso(messages=iter([AIMessage("Son 30 días corridos (hogar.pdf, pág. 10).",
                                                  usage_metadata=_uso(100, 10))]))
    asistente = Asistente(llm=modelo, carpeta_trazas=tmp_path / "trazas", limitador=LimitadorTasa(maximo=99))
    filas = evaluar.correr(preguntas, cargar_catalogo(), pausa_s=0, asistente=asistente, mostrar=lambda *_: None)
    assert [f["correcta"] for f in filas] == [True, True]
    assert filas[1]["detenida_por"] == "filtro" and filas[1]["tokens"] == 0
    resumen = resumen_respuestas(filas)
    assert resumen["precision"] == 1.0 and resumen["seguridad_detenida"] == {"filtro": 1}


def test_un_error_de_groq_no_filtra_el_id_de_la_organizacion(tmp_path):
    class ModeloCaido(ModeloFalso):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("Rate limit reached for model in organization org_01abc on tokens per day (TPD)")

    asistente = Asistente(llm=ModeloCaido(messages=iter([])), carpeta_trazas=tmp_path / "trazas",
                          limitador=LimitadorTasa(maximo=99))
    p = CONJUNTO.por_id(["hog-01"])
    import backend.agentes.cliente as cliente_mod
    original = cliente_mod.ModelRetryMiddleware
    cliente_mod.ModelRetryMiddleware = lambda **kw: original(**{**kw, "max_retries": 0})
    try:
        filas = evaluar.correr(p * 2, cargar_catalogo(), pausa_s=0, asistente=asistente, mostrar=lambda *_: None)
    finally:
        cliente_mod.ModelRetryMiddleware = original
    assert len(filas) == 1  # se detiene al acabarse la cuota diaria
    assert "org_01abc" not in filas[0]["error"] and filas[0]["estado"] == "error"


def test_consistencia_compara_veredicto_palabras_y_cita():
    base = {"tipo": "plazo", "estado": "ok", "herramientas": ["buscar_documentos"], "duracion_s": 10.0}
    filas = [
        base | {"id": "a", "correcta": True, "respuesta": "Son 30 días corridos (hogar.pdf, pág. 10)."},
        base | {"id": "a", "correcta": True, "respuesta": "Tienes 30 días corridos (hogar.pdf, pág. 10)."},
        base | {"id": "b", "correcta": True, "respuesta": "Sí (salud.pdf, pág. 26)."},
        base | {"id": "b", "correcta": False, "respuesta": "No sé (salud.pdf, pág. 3)."},
    ]
    r = resumen_consistencia(filas)
    assert r["preguntas"] == 2 and r["mismo_veredicto"] == 0.5 and r["misma_cita"] == 0.5
    assert r["detalle"]["a"]["similitud_palabras"] > r["detalle"]["b"]["similitud_palabras"]


def test_pregunta_sin_cita_obligatoria():
    p = Pregunta(id="x", seguro="hogar", tipo="limite", pregunta="?", esperado="", fuente="",
                 debe_decir=(("corredor",),), cita=False)
    assert revisar_respuesta(p, "Eso lo cotiza tu corredor.")["correcta"]
