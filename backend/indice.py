"""Índice de búsqueda de los documentos de cada seguro.

Cada seguro tiene su propio índice, construido SOLO con los PDF de su carpeta
`documentos/`. Así, el agente de Hogar no puede encontrar texto de la póliza de Pyme.

La búsqueda es híbrida, porque cada método falla donde el otro acierta:
- Por palabras (BM25): encuentra términos exactos, como "deducible" o "CAD 120130880".
- Semántica (embeddings locales): entiende cómo habla el cliente; "me chocaron" queda
  cerca de "colisión" aunque no compartan palabras.
Los dos rankings se combinan con Reciprocal Rank Fusion (RRF).

El índice se guarda en `.indices/<corredor>/<seguro>/` y se reconstruye solo cuando
cambia un PDF o la ficha.

Uso (construye por adelantado los índices de todos los seguros de un corredor):
  uv run python -m backend.indice
  uv run python -m backend.indice --corredor demo
"""
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.catalogo import Documento, Ficha
from backend.config import EMBEDDING_MODEL, INDICES_DIR, busqueda_semantica_activa

VERSION_INDICE = 2  # súbelo si cambia la forma de leer o cortar los PDF
LARGO_FRAGMENTO = 700  # caracteres; MiniLM solo lee ~128 tokens, más largo se pierde
SOLAPE = 150  # caracteres que se repiten entre fragmentos seguidos
MIN_PARA_CORTAR_EN_ARTICULO = 250  # un artículo nuevo abre fragmento si el actual ya tiene esto
RRF_K = 60
CANDIDATOS_POR_METODO = 30


@dataclass(frozen=True)
class Fragmento:
    archivo: str
    titulo: str
    aseguradora: str
    pagina: int
    pagina_final: int
    seccion: str
    codigo: str  # último código CMF (POL/CAD) mencionado antes del fragmento
    particulares: bool  # True: condiciones particulares de un cliente puntual
    texto: str

    def cita(self) -> str:
        paginas = f"pág. {self.pagina}" if self.pagina == self.pagina_final else f"págs. {self.pagina}-{self.pagina_final}"
        partes = [self.archivo, paginas]
        partes.append(
            "condiciones particulares de una póliza de ejemplo" if self.particulares else "condiciones generales"
        )
        if self.seccion:
            partes.append(self.seccion)
        if self.codigo:
            partes.append(self.codigo)
        return " · ".join(partes)


# --- Lectura y limpieza de los PDF ---

_RE_ESPACIOS = re.compile(r"\s+")
_RE_SOLO_NUMERO = re.compile(r"^\d{1,3}$")  # número de página
_RE_PAGINA_DE = re.compile(r"^\d{1,3}\s*-\s*\d{1,3}$")  # "2 - 33"
_RE_ARTICULO = re.compile(r"^(ART[IÍ]CULO|Art[ií]culo|T[IÍ]TULO|CL[AÁ]USULA)\s*[\dIVXLC]+", re.UNICODE)
_RE_SECCION_NUMERADA = re.compile(r"^\d{1,2}\.\s*[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,/()\-]{4,}$")
_RE_CODIGO = re.compile(r"\b(POL|CAD)\s?(\d{9})\b")


def _limpiar_linea(linea: str) -> str:
    return _RE_ESPACIOS.sub(" ", linea).strip()


def _leer_paginas(ruta: Path) -> list[list[str]]:
    import pymupdf

    with pymupdf.open(ruta) as pdf:
        return [[_limpiar_linea(l) for l in pagina.get_text().splitlines()] for pagina in pdf]


def _quitar_encabezados(paginas: list[list[str]]) -> list[list[str]]:
    """Quita lo que se repite en casi todas las páginas (encabezados y pies),
    los números de página y las líneas sin letras ni números."""
    frecuencia = Counter(l for lineas in paginas for l in set(lineas) if l)
    minimo = max(3, 0.4 * len(paginas))
    repetidas = {l for l, n in frecuencia.items() if n >= minimo and len(l) < 150}
    return [
        [
            l
            for l in lineas
            if l
            and l not in repetidas
            and not _RE_SOLO_NUMERO.match(l)
            and not _RE_PAGINA_DE.match(l)
            and any(c.isalnum() for c in l)
        ]
        for lineas in paginas
    ]


def _es_titulo(linea: str) -> bool:
    if _RE_ARTICULO.match(linea) or _RE_SECCION_NUMERADA.match(linea):
        return True
    letras = sum(c.isalpha() for c in linea)
    return (
        8 <= len(linea) <= 90
        and letras >= 6
        and linea == linea.upper()
        and sum(c.isdigit() for c in linea) <= 4
        and not linea.endswith(",")
    )


def _unir(lineas: list[str]) -> str:
    """Une las líneas cortadas por el PDF y conserva los saltos entre párrafos."""
    texto = ""
    for linea in lineas:
        if not texto:
            texto = linea
        elif texto.endswith((".", ":", ";")) or _es_titulo(linea) or linea[:1] in "-•·*":
            texto += "\n" + linea
        else:
            texto += " " + linea
    return texto


def fragmentar(documento: Documento, paginas: list[list[str]]) -> list[Fragmento]:
    """Corta un documento en fragmentos de ~LARGO_FRAGMENTO caracteres.

    Un artículo nuevo abre un fragmento nuevo, para que cada uno hable de un solo tema.
    Cada fragmento recuerda su página, la sección y el código CMF vigentes.
    """
    fragmentos: list[Fragmento] = []
    actual: list[tuple[int, str]] = []
    seccion = codigo = ""
    seccion_inicio = codigo_inicio = ""
    completar_titulo = False

    def emitir() -> None:
        if not actual:
            return
        pagina, pagina_final = actual[0][0], actual[-1][0]
        fragmentos.append(
            Fragmento(
                archivo=documento.archivo,
                titulo=documento.titulo,
                aseguradora=documento.aseguradora,
                pagina=pagina,
                pagina_final=pagina_final,
                seccion=seccion_inicio,
                codigo=codigo_inicio,
                particulares=pagina <= documento.paginas_particulares,
                texto=_unir([l for _, l in actual]),
            )
        )

    for numero, lineas in enumerate(paginas, start=1):
        for linea in lineas:
            es_articulo = bool(_RE_ARTICULO.match(linea) or _RE_SECCION_NUMERADA.match(linea))
            largo = sum(len(l) + 1 for _, l in actual)
            if es_articulo and largo >= MIN_PARA_CORTAR_EN_ARTICULO:
                emitir()
                actual = []

            # "TITULO VI" o "ARTICULO 10°:" suelen traer el nombre en la línea siguiente
            if es_articulo:
                seccion = linea[:120]
                completar_titulo = linea.endswith(":") or len(linea) < 25
            elif _es_titulo(linea):
                seccion = f"{seccion} {linea}"[:120] if completar_titulo else linea[:120]
                completar_titulo = False
            elif completar_titulo and len(linea) <= 60:
                seccion = f"{seccion} {linea}"[:120]
                completar_titulo = False
            else:
                completar_titulo = False
            if codigos := _RE_CODIGO.findall(linea):
                tipo, numero_codigo = codigos[-1]
                codigo = f"{tipo} {numero_codigo}"

            actual.append((numero, linea))
            # Mientras el fragmento solo tenga títulos, su sección es el último de ellos.
            if all(_es_titulo(l) for _, l in actual) or len(actual) == 1:
                seccion_inicio = seccion
            # El código CMF suele venir justo debajo del título del artículo.
            if len(actual) <= 3:
                codigo_inicio = codigo

            if sum(len(l) + 1 for _, l in actual) >= LARGO_FRAGMENTO:
                emitir()
                solape: list[tuple[int, str]] = []
                for item in reversed(actual):
                    if sum(len(l) for _, l in solape) >= SOLAPE:
                        break
                    solape.insert(0, item)
                actual = solape
                seccion_inicio, codigo_inicio = seccion, codigo
    emitir()
    return fragmentos


# --- Búsqueda por palabras (BM25) ---

_PALABRAS_VACIAS = {
    "de", "la", "el", "en", "y", "a", "los", "las", "del", "se", "que", "por", "con", "un", "una",
    "para", "al", "lo", "su", "sus", "o", "no", "es", "como", "mas", "este", "esta", "estos", "estas",
    "ser", "sera", "sin", "sobre", "entre", "cuando", "dentro", "desde", "hasta", "cual", "cuales",
    "donde", "le", "les", "ha", "han", "hay", "si", "ya", "muy", "otro", "otros", "otra", "otras",
    "todo", "todos", "toda", "todas", "mismo", "misma", "me", "mi", "mis", "yo", "tu", "que", "esto",
    "eso", "ese", "esa", "pero", "tiene", "tengo", "puedo", "seguro", "poliza",
}


def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes).strip()


def tokens(texto: str) -> list[str]:
    """Palabras normalizadas y recortadas a 6 letras, para que "inundación" e
    "inundaciones" cuenten como la misma. Los números (códigos CMF) quedan enteros."""
    resultado = []
    for palabra in normalizar(texto).split():
        if palabra in _PALABRAS_VACIAS or (len(palabra) < 3 and not palabra.isdigit()):
            continue
        resultado.append(palabra if palabra.isdigit() else palabra[:6])
    return resultado


class BM25:
    def __init__(self, textos: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.largos = [len(tokens(t)) for t in textos]
        self.promedio = (sum(self.largos) / len(self.largos)) if self.largos else 0
        self.invertido: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, texto in enumerate(textos):
            for termino, frecuencia in Counter(tokens(texto)).items():
                self.invertido[termino].append((i, frecuencia))
        self.n = len(textos)

    def puntajes(self, consulta: str) -> dict[int, float]:
        resultado: dict[int, float] = defaultdict(float)
        for termino in set(tokens(consulta)):
            apariciones = self.invertido.get(termino, [])
            if not apariciones:
                continue
            idf = math.log(1 + (self.n - len(apariciones) + 0.5) / (len(apariciones) + 0.5))
            for i, tf in apariciones:
                norma = 1 - self.b + self.b * self.largos[i] / (self.promedio or 1)
                resultado[i] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norma)
        return resultado


# --- Embeddings ---


@lru_cache
def _modelo_embeddings():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def _vectorizar(textos: list[str], progreso: bool = False) -> np.ndarray:
    vectores = _modelo_embeddings().encode(
        textos, batch_size=64, normalize_embeddings=True, show_progress_bar=progreso
    )
    return np.asarray(vectores, dtype=np.float32)


def _texto_para_buscar(f: Fragmento) -> str:
    return f"{f.titulo} — {f.seccion}\n{f.texto}"


# --- Índice de un seguro ---


class IndiceSeguro:
    def __init__(self, fragmentos: list[Fragmento], vectores: np.ndarray | None):
        self.fragmentos = fragmentos
        self.vectores = vectores
        self.bm25 = BM25([_texto_para_buscar(f) for f in fragmentos])

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        if not self.fragmentos or not consulta.strip():
            return []
        rankings = []
        lexico = self.bm25.puntajes(consulta)
        rankings.append(sorted(lexico, key=lexico.get, reverse=True)[:CANDIDATOS_POR_METODO])
        if self.vectores is not None and len(self.vectores):
            similitud = self.vectores @ _vectorizar([consulta])[0]
            rankings.append(list(np.argsort(-similitud)[:CANDIDATOS_POR_METODO]))
        fusion: dict[int, float] = defaultdict(float)
        for ranking in rankings:
            for posicion, i in enumerate(ranking):
                fusion[int(i)] += 1 / (RRF_K + posicion + 1)
        # Las condiciones generales se repiten entre pólizas (auto particular y comercial
        # comparten la POL 120130744): un texto ya elegido no se entrega dos veces.
        elegidos, vistos = [], set()
        for i in sorted(fusion, key=fusion.get, reverse=True):
            huella = normalizar(self.fragmentos[i].texto)[:400]
            if huella in vistos:
                continue
            vistos.add(huella)
            elegidos.append(self.fragmentos[i])
            if len(elegidos) == k:
                break
        return elegidos

    def buscar_con_contexto(
        self, consulta: str, k: int = 5, vecinos: int = 1, margen: int = 300
    ) -> list[Fragmento]:
        """Como buscar(), pero cada resultado trae también el final del fragmento anterior
        y el inicio del siguiente (`margen` caracteres) del mismo documento. Un fragmento
        suelto puede cortar la frase que le da sentido ("Se exceptúan los gastos
        ópticos..." es una excepción a otra regla, no una exclusión). El margen es corto
        para no pasarse del límite de tokens por minuto de Groq."""
        posicion = {id(f): i for i, f in enumerate(self.fragmentos)}
        tramos: list[tuple[int, int]] = []
        encontrados: set[int] = set()
        for f in self.buscar(consulta, k=k):
            i = posicion[id(f)]
            encontrados.add(i)
            inicio, fin = i, i
            while inicio > i - vecinos and inicio > 0 and self.fragmentos[inicio - 1].archivo == f.archivo:
                inicio -= 1
            while fin < i + vecinos and fin + 1 < len(self.fragmentos) and self.fragmentos[fin + 1].archivo == f.archivo:
                fin += 1
            # Si se cruza con un tramo ya elegido, se juntan en uno solo.
            for j, (a, b) in enumerate(tramos):
                if inicio <= b + 1 and fin >= a - 1:
                    tramos[j] = (min(a, inicio), max(b, fin))
                    break
            else:
                tramos.append((inicio, fin))
        return [self._unir_tramo(a, b, encontrados, margen) for a, b in tramos]

    def _unir_tramo(self, inicio: int, fin: int, encontrados: set[int], margen: int) -> Fragmento:
        textos = []
        for i in range(inicio, fin + 1):
            texto = self.fragmentos[i].texto
            if i not in encontrados and i == inicio:
                texto = "…" + texto[-margen:]
            elif i not in encontrados and i == fin:
                texto = texto[:margen] + "…"
            textos.append(texto)
        unido = textos[0]
        for siguiente in textos[1:]:
            unido += "\n" + _sin_solape(unido, siguiente)
        # La cita es la de los fragmentos que encontró la búsqueda, no la de los
        # vecinos: así la página citada es donde está la respuesta.
        hallados = [i for i in encontrados if inicio <= i <= fin]
        return replace(
            self.fragmentos[min(hallados)],
            pagina_final=self.fragmentos[max(hallados)].pagina_final,
            texto=unido,
        )


def _sin_solape(anterior: str, siguiente: str, maximo: int = 400) -> str:
    """Quita del inicio de `siguiente` el texto que ya estaba al final de `anterior`."""
    for largo in range(min(maximo, len(anterior), len(siguiente)), 20, -1):
        if anterior.endswith(siguiente[:largo]):
            return siguiente[largo:].lstrip()
    return siguiente


def documentos_del_seguro(ficha: Ficha) -> list[Documento]:
    """Los documentos declarados en la ficha, más cualquier otro PDF de la carpeta
    (así, dejar un PDF nuevo en documentos/ basta para que el agente lo lea)."""
    declarados = list(ficha.documentos)
    nombres = {d.archivo for d in declarados}
    if ficha.carpeta_documentos.is_dir():
        for ruta in sorted(ficha.carpeta_documentos.glob("*.pdf")):
            if ruta.name not in nombres and not ruta.name.startswith("."):
                declarados.append(Documento(archivo=ruta.name, titulo=ruta.stem))
    return declarados


def _firma(ficha: Ficha, documentos: list[Documento]) -> str:
    datos = {
        "version": VERSION_INDICE,
        "largo": LARGO_FRAGMENTO,
        "solape": SOLAPE,
        "documentos": [d.model_dump() for d in documentos],
        "archivos": [],
    }
    for d in documentos:
        ruta = ficha.carpeta_documentos / d.archivo
        if not ruta.is_file():
            raise FileNotFoundError(
                f"La ficha de '{ficha.seguro}' nombra '{d.archivo}', pero no está en {ficha.carpeta_documentos}"
            )
        estado = ruta.stat()
        datos["archivos"].append([d.archivo, estado.st_size, estado.st_mtime_ns])
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()


def construir_fragmentos(ficha: Ficha, documentos: list[Documento]) -> list[Fragmento]:
    fragmentos = []
    for d in documentos:
        paginas = _quitar_encabezados(_leer_paginas(ficha.carpeta_documentos / d.archivo))
        fragmentos += fragmentar(d, paginas)
    return fragmentos


_EN_MEMORIA: dict[tuple[Path, str], tuple[str, bool, IndiceSeguro]] = {}


def cargar_indice(ficha: Ficha, raiz: Path | None = None, progreso: bool = False) -> IndiceSeguro:
    """Devuelve el índice del seguro: de memoria, de disco o recién construido."""
    raiz = raiz or INDICES_DIR
    semantica = busqueda_semantica_activa()
    documentos = documentos_del_seguro(ficha)
    firma = _firma(ficha, documentos)
    clave = (ficha.carpeta_documentos, str(raiz))
    if clave in _EN_MEMORIA and _EN_MEMORIA[clave][:2] == (firma, semantica):
        return _EN_MEMORIA[clave][2]

    carpeta = raiz / ficha.corredor / ficha.seguro
    ruta_meta, ruta_fragmentos, ruta_vectores = (
        carpeta / "meta.json",
        carpeta / "fragmentos.json",
        carpeta / "embeddings.npy",
    )
    meta = json.loads(ruta_meta.read_text(encoding="utf-8")) if ruta_meta.is_file() else {}
    vigente = meta.get("firma") == firma and ruta_fragmentos.is_file()

    if vigente:
        fragmentos = [Fragmento(**f) for f in json.loads(ruta_fragmentos.read_text(encoding="utf-8"))]
    else:
        fragmentos = construir_fragmentos(ficha, documentos)
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_vectores.unlink(missing_ok=True)
        ruta_fragmentos.write_text(
            json.dumps([asdict(f) for f in fragmentos], ensure_ascii=False), encoding="utf-8"
        )

    vectores = None
    if semantica and fragmentos:
        # Los vectores se guardan como .npy (sin pickle): solo números.
        if vigente and meta.get("embeddings") == EMBEDDING_MODEL and ruta_vectores.is_file():
            vectores = np.load(ruta_vectores, allow_pickle=False)
        else:
            vectores = _vectorizar([_texto_para_buscar(f) for f in fragmentos], progreso=progreso)
            np.save(ruta_vectores, vectores, allow_pickle=False)
            meta["embeddings"] = EMBEDDING_MODEL
    meta["firma"] = firma
    meta["fragmentos"] = len(fragmentos)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    indice = IndiceSeguro(fragmentos, vectores)
    _EN_MEMORIA[clave] = (firma, semantica, indice)
    return indice


def _main() -> None:
    import argparse

    from backend.catalogo import cargar_catalogo

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Construye los índices de búsqueda de los seguros.")
    parser.add_argument("--corredor", default="demo")
    args = parser.parse_args()
    seguros = cargar_catalogo().get(args.corredor)
    if not seguros:
        sys.exit(f"No existe el corredor '{args.corredor}' en corredores/")
    for ficha in seguros.values():
        print(f"- {ficha.nombre}...", flush=True)
        indice = cargar_indice(ficha, progreso=True)
        print(f"  {len(indice.fragmentos)} fragmentos")


if __name__ == "__main__":
    _main()
