"""Trazas y métricas del agente, con un modelo falso (sin llamar a Groq)."""
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from backend.agentes.cliente import crear_agente
from backend.catalogo import cargar_catalogo
from backend.herramientas.contexto import Contexto
from backend.observabilidad import iniciar_traza, leer_trazas
from backend.observabilidad.reporte import resumen
from tests.test_documentos import crear_seguro


class ModeloFalso(GenericFakeChatModel):
    """Responde mensajes ya escritos; acepta herramientas como el modelo real."""

    def bind_tools(self, tools, **kwargs):
        return self


def _uso(entrada, salida):
    return {"input_tokens": entrada, "output_tokens": salida, "total_tokens": entrada + salida}


@pytest.fixture(autouse=True)
def solo_palabras(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSQUEDA_SEMANTICA", "false")
    monkeypatch.setattr("backend.indice.INDICES_DIR", tmp_path / "indices")


@pytest.fixture
def ficha(tmp_path):
    crear_seguro(tmp_path / "corredores", "demo", "hogar", ["Artículo 5: el robo se denuncia en 48 horas."])
    return cargar_catalogo(tmp_path / "corredores")["demo"]["hogar"]


def _preguntar(ficha, modelo, carpeta, pregunta="¿Plazo para denunciar un robo?"):
    agente = crear_agente(ficha, llm=modelo)
    with iniciar_traza("hilo-1", ficha, pregunta, carpeta=carpeta) as traza:
        resultado = agente.invoke(
            {"messages": [{"role": "user", "content": pregunta}]}, context=Contexto(ficha)
        )
        traza.respuesta = resultado["messages"][-1].content
    return traza


def test_la_traza_registra_modelo_herramienta_y_tokens(ficha, tmp_path):
    modelo = ModeloFalso(messages=iter([
        AIMessage("", tool_calls=[{"name": "buscar_documentos", "args": {"consulta": "denuncia robo"}, "id": "1"}],
                  usage_metadata=_uso(900, 40)),
        AIMessage("Se denuncia en 48 horas (poliza.pdf, pág. 1).", usage_metadata=_uso(1500, 60)),
    ]))
    traza = _preguntar(ficha, modelo, tmp_path / "trazas")

    assert [s.etapa for s in traza.spans] == ["modelo", "herramienta", "modelo"]
    assert traza.spans[0].detalle["decision"] == "usar buscar_documentos"
    assert traza.spans[1].detalle["argumentos"] == {"consulta": "denuncia robo"}
    assert traza.spans[2].detalle["decision"] == "responder"
    assert (traza.tokens_entrada, traza.tokens_salida) == (2400, 100)
    assert traza.estado == "ok" and "48 horas" in traza.respuesta


def test_las_trazas_se_guardan_y_el_reporte_las_resume(ficha, tmp_path):
    carpeta = tmp_path / "trazas"
    for _ in range(2):
        modelo = ModeloFalso(messages=iter([AIMessage("Hola", usage_metadata=_uso(500, 10))]))
        _preguntar(ficha, modelo, carpeta)

    trazas = leer_trazas(carpeta)
    r = resumen(trazas)
    assert r["preguntas"] == 2 and r["conversaciones"] == 1
    assert r["tasa_error"] == 0 and r["llamadas_modelo_prom"] == 1
    assert r["tokens_entrada_prom"] == 500


def test_una_pregunta_que_falla_queda_como_error(ficha, tmp_path):
    carpeta = tmp_path / "trazas"
    with pytest.raises(RuntimeError):
        with iniciar_traza("hilo-2", ficha, "hola", carpeta=carpeta):
            raise RuntimeError("429 cuota")
    (traza,) = leer_trazas(carpeta)
    assert traza["estado"] == "error" and "429" in traza["error"]
    assert resumen([traza])["tasa_error"] == 1
