"""Lectura de PDF, índice de búsqueda y aislamiento entre seguros (sin llamar a Groq)."""
import pymupdf
import pytest

from backend.agentes.cliente import construir_instrucciones
from backend.catalogo import Documento, cargar_catalogo
from backend.herramientas.contexto import Contexto
from backend.herramientas.documentos import buscar_documentos
from backend.indice import _quitar_encabezados, cargar_indice, fragmentar, tokens


@pytest.fixture(autouse=True)
def solo_palabras(monkeypatch, tmp_path):
    # Sin embeddings: los tests no cargan el modelo y corren en segundos.
    monkeypatch.setenv("BUSQUEDA_SEMANTICA", "false")
    # Los índices de prueba van a una carpeta temporal, no a .indices/ del proyecto.
    monkeypatch.setattr("backend.indice.INDICES_DIR", tmp_path / "indices_por_defecto")


def crear_pdf(ruta, paginas: list[str]) -> None:
    pdf = pymupdf.open()
    for texto in paginas:
        pdf.new_page().insert_text((50, 72), texto, fontsize=10)
    pdf.save(ruta)
    pdf.close()


def crear_seguro(raiz, corredor, seguro, paginas, particulares=0):
    carpeta = raiz / corredor / "seguros" / seguro
    (carpeta / "documentos").mkdir(parents=True)
    crear_pdf(carpeta / "documentos" / "poliza.pdf", paginas)
    (carpeta / "ficha.yaml").write_text(
        f"nombre: Seguro {seguro}\n"
        "documentos:\n"
        f"  - {{archivo: poliza.pdf, titulo: Póliza {seguro}, paginas_particulares: {particulares}}}\n",
        encoding="utf-8",
    )
    return carpeta


ENCABEZADO = "POLIZA : 09999999 - SEGURO DE PRUEBA"
# Relleno para que cada artículo supere el mínimo que abre un fragmento nuevo.
def relleno(pagina: int) -> str:
    # Distinto en cada página: si se repitiera, se borraría como encabezado.
    return "\n".join(
        f"Linea {i} de la pagina {pagina}, relleno para que el articulo sea largo." for i in range(5)
    )


TEXTO_PYME = "ARTICULO 1°: COBERTURA\nSe cubre la mercaderia del local comercial."


@pytest.fixture
def catalogo(tmp_path):
    crear_seguro(
        tmp_path / "corredores",
        "c",
        "hogar",
        [
            f"{ENCABEZADO}\n2\nCONDICIONES PARTICULARES\nDeducible del plan: 3 UF.\n{relleno(1)}",
            f"{ENCABEZADO}\nARTICULO 5°: DENUNCIA DE SINIESTRO\nPOL 120130172\n"
            f"El asegurado debe dar aviso del robo dentro de 30 dias corridos.\n{relleno(2)}",
            f"{ENCABEZADO}\nARTICULO 6°: EXCLUSIONES\nNo se cubren los danos por guerra.\n{relleno(3)}",
        ],
        particulares=1,
    )
    pyme = crear_seguro(tmp_path / "corredores", "c", "pyme", [TEXTO_PYME])
    # Un segundo PDF idéntico, que no está en la ficha (como auto particular y comercial,
    # que comparten condiciones generales). Igual se lee: basta dejarlo en la carpeta.
    crear_pdf(pyme / "documentos" / "copia.pdf", [TEXTO_PYME])
    return cargar_catalogo(tmp_path / "corredores")


def test_se_quitan_encabezados_repetidos_y_numeros_de_pagina():
    paginas = [[ENCABEZADO, "2", "texto uno"], [ENCABEZADO, "3", "texto dos"], [ENCABEZADO, "4 - 33", "tres"]]
    assert _quitar_encabezados(paginas) == [["texto uno"], ["texto dos"], ["tres"]]


def test_cada_fragmento_sabe_su_pagina_seccion_codigo_y_tipo():
    documento = Documento(archivo="p.pdf", titulo="P", paginas_particulares=1)
    paginas = [
        ["Monto asegurado 2.877 UF.", *relleno(1).splitlines()],
        ["ARTICULO 13°: DENUNCIA", "POL 120130744", "Dentro de los 10 dias habiles siguientes."],
    ]
    primero, segundo = fragmentar(documento, paginas)
    assert primero.particulares and primero.pagina == 1
    assert not segundo.particulares and segundo.pagina == 2
    assert segundo.seccion.startswith("ARTICULO 13°: DENUNCIA")
    assert segundo.codigo == "POL 120130744"
    assert "condiciones generales" in segundo.cita() and "pág. 2" in segundo.cita()


def test_las_palabras_se_comparan_sin_tildes_ni_plurales():
    assert tokens("Inundación") == tokens("inundaciones")
    assert tokens("CAD 120130880") == ["cad", "120130880"]


def test_la_busqueda_encuentra_el_articulo_y_lo_cita(catalogo, tmp_path):
    ficha = catalogo["c"]["hogar"]
    resultados = buscar_documentos(Contexto(ficha), "plazo para avisar un robo")
    assert "30 dias corridos" in resultados[0]
    assert "pág. 2" in resultados[0] and "DENUNCIA DE SINIESTRO" in resultados[0]


def test_un_seguro_no_encuentra_texto_de_otro(catalogo):
    hogar = buscar_documentos(Contexto(catalogo["c"]["hogar"]), "mercaderia del local comercial")
    assert not any("mercaderia" in r for r in hogar)


def test_los_textos_repetidos_se_entregan_una_sola_vez(catalogo):
    indice = cargar_indice(catalogo["c"]["pyme"])
    assert {f.archivo for f in indice.fragmentos} == {"poliza.pdf", "copia.pdf"}
    assert len(indice.buscar("mercaderia local", k=5)) == 1


def test_el_indice_se_guarda_y_se_reconstruye_si_cambia_el_pdf(catalogo, tmp_path):
    from backend import indice as modulo

    ficha = catalogo["c"]["hogar"]
    raiz = tmp_path / "indices"
    cargar_indice(ficha, raiz=raiz)
    assert (raiz / "c" / "hogar" / "fragmentos.json").is_file()

    modulo._EN_MEMORIA.clear()
    crear_pdf(ficha.carpeta_documentos / "poliza.pdf", ["ARTICULO 1°: NUEVO\nTexto completamente nuevo."])
    assert "nuevo" in cargar_indice(ficha, raiz=raiz).fragmentos[0].texto.lower()


def test_un_pdf_que_falta_avisa_cual_es(tmp_path):
    carpeta = crear_seguro(tmp_path, "c", "auto", ["texto"])
    (carpeta / "documentos" / "poliza.pdf").unlink()
    with pytest.raises(FileNotFoundError, match="poliza.pdf"):
        cargar_indice(cargar_catalogo(tmp_path)["c"]["auto"], raiz=tmp_path / "indices")


@pytest.mark.parametrize("archivo", ["../otro/poliza.pdf", "..\\\\otro.pdf", ".oculto.pdf", "notas.txt"])
def test_la_ficha_solo_acepta_pdf_de_su_carpeta(tmp_path, archivo):
    carpeta = tmp_path / "c" / "seguros" / "auto"
    carpeta.mkdir(parents=True)
    (carpeta / "ficha.yaml").write_text(
        f'nombre: Auto\ndocumentos:\n  - {{archivo: "{archivo}", titulo: X}}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="auto"):
        cargar_catalogo(tmp_path)


def test_las_instrucciones_nombran_los_documentos_del_seguro(catalogo):
    instrucciones = construir_instrucciones(catalogo["c"]["hogar"])
    assert "poliza.pdf: Póliza hogar" in instrucciones
    assert "buscar_documentos" in instrucciones
