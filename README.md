# Proyecto Seguros

Agentes de IA para corredores de seguros, conectados a un frontend.

Todos los seguros usan **un mismo agente base y las mismas herramientas**. Lo que cambia es la ficha y los documentos de cada seguro, así que agregar un seguro no requiere programar.

## Cómo funciona

```
Cliente elige "Hogar"
        │
        ▼
Agente base + ficha de Hogar (instrucciones + lista de documentos)
        │  buscar_documentos("plazo denuncia robo")
        ▼
Índice de Hogar (.indices/demo/hogar/) ← solo los PDF de corredores/demo/seguros/hogar/documentos/
        │  búsqueda por palabras (BM25) + semántica (embeddings locales), combinadas con RRF
        ▼
Fragmentos con su cita [archivo · página · condiciones particulares/generales · artículo · código CMF]
        │
        ▼
Respuesta al cliente, citando documento y página
```

- **Aislamiento:** el corredor y el seguro los fija el servidor (contexto), no el modelo. El agente de Hogar no puede leer las pólizas de Pyme.
- **Condiciones particulares vs. generales:** cada póliza de ejemplo trae primero el plan de un cliente puntual (montos, deducibles) y luego las condiciones generales. La ficha indica hasta qué página van las particulares (`paginas_particulares`), y el agente avisa que esos montos dependen del plan.

## Seguros cargados (corredor `demo`)

| Seguro (carpeta) | Documentos | Aseguradora |
|---|---|---|
| `vehiculo` | Auto particular + vehículo comercial (comparten POL 120130744) | Sura |
| `hogar` | Hogar Pro (Protección Familiar) | Sura |
| `pyme` | Pyme (Misceláneo Comercial) | Sura |
| `responsabilidad_civil` | RC general + RC empresas y servicios | Sura |
| `transporte` | Transporte terrestre cabotaje | Sura |
| `salud` | Complementario de salud colectivo + dental | Vida Cámara |

## Estructura

| Carpeta / archivo | Qué va ahí |
|---|---|
| `corredores/` | Ficha y documentos de cada seguro, por corredor |
| `backend/catalogo.py` | Lee las fichas |
| `backend/indice.py` | Lee los PDF, los corta en fragmentos y los busca |
| `backend/agentes/cliente.py` | Agente base para clientes (LangChain + Groq) |
| `backend/agentes/etapas.py` | Memoria del caso y plan por etapas (consulta → recopilando → confirmando → registrada) |
| `backend/herramientas/` | Acciones compartidas por los agentes |
| `backend/chat.py` | Chat local en la consola |
| `backend/observabilidad/` | Trazas por pregunta (`.trazas/*.jsonl`) y reporte de métricas |
| `backend/config.py` | Modelos y rutas (lee `.env`) |
| `backend/endpoints/` | API: lista de seguros, chat, estado de la conversación, `/metricas`, y `/api/health`, `/api/chat`, `/api/metrics` con el formato del deploy del curso |
| `backend/seguridad/` | Filtros de entrada y salida, bóveda de datos personales, límite por minuto, cupos público/dueño, link del dueño, freno de inundación y mapa OWASP 2026 ejecutable |
| `usuarios/` | **Microservicio de usuarios**: registro, login (token firmado), perfil y roles; su propia base `usuarios.db` (el correo no se repite) |
| `backend/almacen.py` | Solicitudes y derivaciones en SQLite (`data/seguros.db`, no se sube a git) |
| `backend/servicio.py` | Camino único de cada pregunta: seguridad → agente → traza (lo usan el chat y la API); memoria en `data/` |
| `frontend/` | Chat del cliente (`index.html` + `chat.js`) y panel de métricas (`panel.html` + `panel.js`), servidos por la API |
| `backend/evaluacion/` | Set de preguntas con respuesta conocida (`preguntas.yaml`) y evaluador de precisión, latencia y consistencia |
| `tests/` | Pruebas |
| `docs/` | Contexto y pendientes con el cliente |
| `docs/informe/` | Material del informe EFT: figuras, tablas de resultados, guion de la defensa |
| `docs/seguridad/` | Mapa OWASP 2026 (20 ítems) y checklist de seguridad y despliegue, como los del curso |
| `deploy/` | Docker (app + Caddy HTTPS) para AWS Academy Learner Lab; guía paso a paso en `deploy/README.md` |
| `entrega/` | Generadores del notebook de entrega, diagramas y tablas |

## Estado

| Pieza | Estado |
|---|---|
| Lectura de fichas y lista de seguros | Lista |
| `buscar_documentos` (índice híbrido por seguro) | Lista |
| Agente de cliente + chat local (`backend.chat`) | Funciona con Groq |
| Chat por API (`POST .../chat`) y retomar (`GET .../conversaciones/{id}`) | Listo; límite por minuto por IP (429) |
| API con el formato del curso (`/api/health`, `/api/chat` con `historial`, `/api/metrics`) | Lista |
| Frontend del chat + panel de métricas (`/metricas`, sin preguntas ni respuestas) | Listo; en el servidor, el panel es solo para el dueño (link secreto) |
| `ver_campos_solicitud` | Lista; los campos de las 6 fichas son una PROPUESTA por confirmar con el corredor |
| `registrar_solicitud`, `consultar_solicitud`, `derivar_a_persona` | Funcionan en modo SIMULADO (SQLite en `data/`); el canal real se define con el cliente |
| Bandeja del corredor (`uv run python -m backend.bandeja`) | Lista |
| Trazas y métricas (`backend.observabilidad.reporte`) | Listas |
| Seguridad (filtros de entrada y salida, bóveda, límite por minuto, cupos, freno de inundación) | Lista; mapa en `docs/seguridad/mapa-owasp-2026.md` |
| Microservicio de usuarios (`usuarios/`): el chat pide sesión; cupo por cuenta | Listo |
| Despliegue en AWS Academy (`deploy/`) | Listo para desplegar; probado en local con Caddy y un modelo falso |
| Memoria persistente (`data/conversaciones.db` + `data/boveda.db`, retención 30 días) | Lista; se retoma con `--conversacion` |
| Etapas del caso y confirmación obligatoria antes de registrar | Lista |
| `convertir_uf`: valor de la UF del día (findic.cl → mindicador.cl → copia local en `data/`) | Lista |
| Evaluación (`backend.evaluacion.evaluar`): recuperación, respuestas y consistencia | Lista; las respuestas esperadas son una PROPUESTA a validar con la corredora |
| Notebook de entrega (`entrega/EFT_ISY0101_proyecto_seguros.ipynb`) | Se genera desde el código real |

## Ejecutar

1. Instalar y configurar:
   ```
   uv sync
   copy .env.example .env      # y completar GROQ_API_KEY
   ```
2. Construir los índices (la primera vez tarda ~3 minutos; después se reutilizan):
   ```
   uv run python -m backend.indice
   ```
3. Conversar con los agentes:
   ```
   uv run python -m backend.chat                  # menú de seguros
   uv run python -m backend.chat --seguro hogar   # directo a un seguro
   ```
   Dentro del chat: `menu` cambia de seguro y `salir` termina. Al empezar, el chat muestra
   el id de la conversación; para retomarla después:
   ```
   uv run python -m backend.chat --seguro vehiculo --conversacion demo-vehiculo-1a2b3c4d
   ```
4. Levantar la página web (chat + panel):
   ```
   uv run uvicorn backend.app:app
   ```
   Chat: http://127.0.0.1:8000 · Panel: http://127.0.0.1:8000/panel.html · API: http://127.0.0.1:8000/docs.
   Al arrancar precarga los índices en segundo plano (~15 s) para que la primera pregunta no espere.
5. Pruebas y evidencia de seguridad (no llaman a Groq):
   ```
   uv run pytest
   uv run python -m backend.seguridad.ejemplos_owasp     # OWASP 2026: los 20 ítems con su evidencia
   ```
6. Evaluación del agente (resultados en `.evaluaciones/`):
   ```
   uv run python -m backend.evaluacion.evaluar --recuperacion     # sin Groq, ~15 s
   uv run python -m backend.evaluacion.evaluar --respuestas       # con Groq, ~15 min
   uv run python -m backend.evaluacion.evaluar --consistencia 3   # con Groq
   uv run python -m backend.evaluacion.evaluar --recorregir       # recalifica la última corrida si cambia un criterio
   ```
7. Material de la entrega (notebook, diagramas, gráficos y tablas):
   ```
   uv run --group notebook python entrega/generar_notebook.py --ejecutar
   uv run --group notebook python entrega/diagramas.py
   uv run --group notebook python -m backend.observabilidad.graficos docs/informe/figuras
   uv run python entrega/tablas_informe.py
   ```
   El notebook incluye TODO el código (una celda `%%writefile` por archivo). En Colab se sube
   junto con `entrega/documentos_demo.zip` (las pólizas) y la API key va en *Secretos*.

**Para agregar un documento:** déjalo en `documentos/` del seguro y, si quieres, descríbelo en `ficha.yaml` (título, aseguradora y `paginas_particulares`). El índice se reconstruye solo.

**Límite de Groq gratuito:** 8.000 tokens por minuto, y cada llamada al modelo usa ~2.200 (sobre todo instrucciones y herramientas). Con 2 llamadas por pregunta, la cuota se acaba a la 3.ª o 4.ª pregunta del mismo minuto: el agente espera y reintenta solo (15 s, 30 s, 60 s), y cada reintento queda en la traza. Por eso cada búsqueda devuelve ~4 fragmentos y el agente borra de la memoria los resultados de búsquedas antiguas.
