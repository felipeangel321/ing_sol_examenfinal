"""Memoria del caso, etapas y confirmación del cliente (sin Groq)."""
from datetime import datetime, timedelta

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend import almacen
from backend.agentes.cliente import HERRAMIENTAS_ACTIVAS
from backend.agentes.etapas import EtapasMiddleware, es_confirmacion, plan_del_caso, puede_registrar
from backend.observabilidad import leer_trazas
from backend.seguridad import Boveda
from backend.servicio import Asistente
from tests.test_herramientas_escritura import _ficha
from tests.test_observabilidad import ModeloFalso, _uso


@pytest.fixture(autouse=True)
def base_temporal(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSQUEDA_SEMANTICA", "false")
    monkeypatch.setattr("backend.indice.INDICES_DIR", tmp_path / "indices")
    monkeypatch.setattr(almacen, "BASE_DATOS", tmp_path / "data" / "seguros.db")


@pytest.fixture
def ficha(tmp_path):
    return _ficha(tmp_path)


def _llamar(nombre: str, args: dict | None = None, id_: str = "1") -> dict:
    return {"name": nombre, "args": args or {}, "id": id_}


DATOS = {"nombre": "Ana Pérez", "rut": "[RUT_1]", "patente": "[PATENTE_1]"}
PRIMER_MENSAJE = "Quiero cotizar. Soy Ana Pérez, RUT 12.345.678-5, patente GTVJ39"


def _turno_con_borrador(*, intenta_registrar: bool = False) -> list[AIMessage]:
    """El modelo anota los datos y muestra el resumen (y, si se pide, intenta saltarse la confirmación)."""
    llamadas = [_llamar("preparar_solicitud", {"datos": DATOS})]
    mensajes = [AIMessage("", tool_calls=llamadas, usage_metadata=_uso(100, 20))]
    if intenta_registrar:
        mensajes.append(AIMessage("", tool_calls=[_llamar("registrar_solicitud", id_="2")],
                                  usage_metadata=_uso(100, 5)))
    mensajes.append(AIMessage("Resumen: Ana Pérez, [RUT_1], [PATENTE_1]. ¿Está correcto?",
                              usage_metadata=_uso(150, 20)))
    return mensajes


# --- Confirmación -------------------------------------------------------------------------

@pytest.mark.parametrize("texto", ["Sí", "si, está todo correcto", "Correcto", "ok dale", "Confirmo",
                                   "Sí, regístrala", "Perfecto, así es"])
def test_reconoce_una_confirmacion(texto):
    assert es_confirmacion(texto)


@pytest.mark.parametrize("texto", ["Sí, pero el correo es otro", "No", "¿Cuánto cuesta?",
                                   "sí, cambia la patente", "Espera, falta el teléfono", "La patente está mal"])
def test_no_confunde_una_correccion_con_una_confirmacion(texto):
    assert not es_confirmacion(texto)


def test_registrar_exige_borrador_completo_y_una_respuesta_posterior_del_cliente():
    base = {"etapa": "confirmando", "borrador": DATOS, "borrador_turno": 1}
    assert "borrador" in puede_registrar({"etapa": "recopilando", "messages": []})
    assert "no ha visto" in puede_registrar({**base, "messages": [HumanMessage("datos")]})
    assert "no es una confirmación" in puede_registrar(
        {**base, "messages": [HumanMessage("datos"), HumanMessage("¿y el deducible?")]})
    assert puede_registrar({**base, "messages": [HumanMessage("datos"), HumanMessage("sí")]}) is None


# --- Plan y herramientas por etapa -----------------------------------------------------------

def _herramientas_ofrecidas(ficha, estado: dict) -> tuple[list[str], str]:
    capturado = {}

    def handler(request):
        capturado["tools"] = [t.name for t in request.tools]
        capturado["sistema"] = request.system_message.text
        return AIMessage("ok")

    request = ModelRequest(model=None, messages=[], system_message=SystemMessage("Reglas base."),
                           tools=list(HERRAMIENTAS_ACTIVAS), state={"messages": [], **estado})
    EtapasMiddleware(ficha).wrap_model_call(request, handler)
    return capturado["tools"], capturado["sistema"]


def test_registrar_solo_se_ofrece_con_el_borrador_listo(ficha):
    herramientas, sistema = _herramientas_ofrecidas(ficha, {})
    assert "registrar_solicitud" not in herramientas and "preparar_solicitud" in herramientas
    assert sistema.startswith("Reglas base.") and "etapa consulta" in sistema

    herramientas, _ = _herramientas_ofrecidas(ficha, {"etapa": "confirmando", "borrador": DATOS})
    assert "registrar_solicitud" in herramientas


def test_el_plan_dice_que_falta(ficha):
    plan = plan_del_caso(ficha, {"etapa": "recopilando", "borrador": {"nombre": "Ana"}})
    assert "Faltan (obligatorios): RUT, Patente" in plan
    assert "Opcionales (pregúntalos una vez, no los exijas): Teléfono" in plan


# --- Flujo completo en el servicio -------------------------------------------------------------

def test_el_modelo_no_puede_registrar_sin_que_el_cliente_vea_el_resumen(ficha, tmp_path):
    modelo = ModeloFalso(messages=iter([
        *_turno_con_borrador(intenta_registrar=True),
        # Turno 2: el cliente confirma.
        AIMessage("", tool_calls=[_llamar("registrar_solicitud", id_="3")], usage_metadata=_uso(200, 5)),
        AIMessage("Listo, quedó registrada.", usage_metadata=_uso(220, 10)),
    ]))
    asistente = Asistente(llm=modelo, carpeta_trazas=tmp_path / "trazas")

    r1 = asistente.responder(ficha, "h1", PRIMER_MENSAJE)
    assert r1.etapa == "confirmando"
    assert almacen.listar("solicitudes") == []  # el intento de saltarse la confirmación no registró

    r2 = asistente.responder(ficha, "h1", "Sí, está todo correcto")
    assert r2.etapa == "registrada"
    (fila,) = almacen.listar("solicitudes")
    assert fila["datos"] == {"nombre": "Ana Pérez", "rut": "12.345.678-5", "patente": "GTVJ39"}
    assert asistente.estado_caso(ficha, "h1")["numero"] == fila["numero"]

    primera, segunda = leer_trazas(tmp_path / "trazas")
    bloqueo = [s for s in primera["spans"] if s["nombre"] == "registrar_solicitud"][0]
    assert bloqueo["detalle"]["registrada"] is False and "no ha visto" in bloqueo["detalle"]["bloqueo"]
    assert primera["etapa"] == "confirmando" and segunda["etapa"] == "registrada"
    # La traza no guarda el RUT. Las herramientas guardan solo los nombres de los campos
    # (el nombre "Ana Pérez" sí aparece en la pregunta: un regex no detecta nombres).
    assert "12.345.678-5" not in str(primera)
    herramientas = [s for s in primera["spans"] if s["etapa"] == "herramienta"]
    assert "Ana Pérez" not in str(herramientas)
    preparar = [s for s in primera["spans"] if s["nombre"] == "preparar_solicitud"][0]
    assert preparar["detalle"]["campos"] == ["nombre", "patente", "rut"]
    assert preparar["detalle"]["etapa_nueva"] == "confirmando"


def test_si_el_cliente_corrige_no_se_registra(ficha, tmp_path):
    modelo = ModeloFalso(messages=iter([
        *_turno_con_borrador(),
        AIMessage("", tool_calls=[_llamar("registrar_solicitud", id_="3")], usage_metadata=_uso(200, 5)),
        AIMessage("Entendido, ¿cuál es la patente correcta?", usage_metadata=_uso(220, 10)),
    ]))
    asistente = Asistente(llm=modelo, carpeta_trazas=tmp_path / "trazas")
    asistente.responder(ficha, "h1", PRIMER_MENSAJE)
    asistente.responder(ficha, "h1", "Sí, pero la patente está mal")
    assert almacen.listar("solicitudes") == []


def test_registra_una_sola_vez_aunque_el_modelo_lo_pida_dos_veces(ficha, tmp_path):
    modelo = ModeloFalso(messages=iter([
        *_turno_con_borrador(),
        AIMessage("", tool_calls=[_llamar("registrar_solicitud", id_="3"), _llamar("registrar_solicitud", id_="4")],
                  usage_metadata=_uso(200, 5)),
        AIMessage("Listo.", usage_metadata=_uso(220, 10)),
    ]))
    asistente = Asistente(llm=modelo, carpeta_trazas=tmp_path / "trazas")
    asistente.responder(ficha, "h1", PRIMER_MENSAJE)
    asistente.responder(ficha, "h1", "Sí")
    assert len(almacen.listar("solicitudes")) == 1


def test_preparar_recuerda_los_datos_anteriores_y_avisa_lo_que_falta(ficha, tmp_path):
    modelo = ModeloFalso(messages=iter([
        AIMessage("", tool_calls=[_llamar("preparar_solicitud", {"datos": {"nombre": "Ana", "telefono": "pendiente"}})],
                  usage_metadata=_uso(100, 5)),
        AIMessage("¿Me das tu RUT y patente?", usage_metadata=_uso(100, 5)),
        # Turno 2: solo manda lo nuevo; el nombre lo recuerda el estado del caso.
        AIMessage("", tool_calls=[_llamar("preparar_solicitud", {"datos": {"rut": "[RUT_1]", "patente": "[PATENTE_1]"}}, "2")],
                  usage_metadata=_uso(100, 5)),
        AIMessage("Resumen... ¿Está correcto?", usage_metadata=_uso(100, 5)),
    ]))
    asistente = Asistente(llm=modelo, carpeta_trazas=tmp_path / "trazas")
    assert asistente.responder(ficha, "h1", "Soy Ana, quiero cotizar").etapa == "recopilando"
    assert asistente.estado_caso(ficha, "h1")["borrador"] == {"nombre": "Ana"}

    assert asistente.responder(ficha, "h1", "RUT 12.345.678-5, patente GTVJ39").etapa == "confirmando"
    # Al cliente se le muestran sus datos reales; el estado guardado solo tiene marcadores.
    assert asistente.estado_caso(ficha, "h1")["borrador"] == {
        "nombre": "Ana", "rut": "12.345.678-5", "patente": "GTVJ39"}


# --- Memoria persistente --------------------------------------------------------------------

def test_la_conversacion_sobrevive_al_reinicio_y_la_memoria_no_guarda_datos_reales(ficha, tmp_path):
    datos = tmp_path / "data"
    antes = Asistente.persistente(datos, llm=ModeloFalso(messages=iter(_turno_con_borrador())),
                                  carpeta_trazas=tmp_path / "trazas")
    antes.responder(ficha, "h1", PRIMER_MENSAJE)

    # "Reinicio": otro Asistente que lee las mismas bases.
    despues = Asistente.persistente(datos, llm=ModeloFalso(messages=iter([])))
    caso = despues.estado_caso(ficha, "h1")
    assert caso["etapa"] == "confirmando" and caso["mensajes"] > 0
    assert caso["borrador"]["rut"] == "12.345.678-5"  # la bóveda también persistió

    assert b"12.345.678-5" not in (datos / "conversaciones.db").read_bytes()
    assert b"12.345.678-5" in (datos / "boveda.db").read_bytes()


def test_el_mismo_thread_id_en_otro_seguro_empieza_de_cero(ficha, tmp_path):
    asistente = Asistente(llm=ModeloFalso(messages=iter(_turno_con_borrador())), carpeta_trazas=tmp_path / "trazas")
    asistente.responder(ficha, "h1", PRIMER_MENSAJE)
    otro_seguro = ficha.model_copy(update={"seguro": "hogar"})
    assert asistente.estado_caso(otro_seguro, "h1") == {
        "etapa": "consulta", "borrador": {}, "numero": "", "derivacion": "", "mensajes": 0}


def test_la_boveda_se_purga_pasado_el_plazo(tmp_path):
    boveda = Boveda(ruta=tmp_path / "boveda.db")
    boveda.seudonimizar("h1", "RUT 12.345.678-5")
    assert boveda.purgar(30) == 0
    assert boveda.purgar(30, ahora=datetime.now() + timedelta(days=31)) == 1
    # Otra instancia (reinicio) tampoco lo encuentra: la conversación quedó anónima.
    assert Boveda(ruta=tmp_path / "boveda.db").revelar("h1", "[RUT_1]") == "[RUT_1]"
