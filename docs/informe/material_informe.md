# Material para el informe EFT ISY0101

> **Cómo usar este archivo.** Para cada apartado de la pauta (Ítem I) tienes:
> **qué pide**, **la evidencia del proyecto** (archivos, figuras, tablas y datos medidos) y
> **✍️ lo que escribes tú**. La pauta prohíbe usar IA para redactar las **conclusiones**, las
> **justificaciones técnicas** y la **reflexión personal**: este material NO las incluye. En los
> recuadros ✍️ hay preguntas para orientarte, no respuestas.
>
> - Figuras: `docs/informe/figuras/` (diagramas `diagrama_*.png` y gráficos de métricas).
> - Tablas con datos medidos: `docs/informe/tablas_resultados.md` (se regeneran con
>   `uv run python entrega/tablas_informe.py`).
> - Código: `entrega/EFT_ISY0101_proyecto_seguros.ipynb` + `entrega/documentos_demo.zip`.

---

## Estructura sugerida del informe

| N.° | Sección | IE | Figuras / tablas |
|---|---|---|---|
| — | Portada, resumen, índice | — | — |
| 1 | Análisis del caso organizacional | IE4, IE8 | — |
| 2.a | Formulación de prompts | IE1 | extracto del prompt |
| 2.b | Pipeline RAG (interno + externo) | IE2 | `diagrama_rag.png`, Tabla 2 |
| 2.c | Arquitectura | IE3 | `diagrama_arquitectura.png` |
| 2.d | Justificación de decisiones y modelos | IE4 | ✍️ solo tú |
| 3.a | Herramientas de consulta, escritura y razonamiento | IE5 | tabla de herramientas |
| 3.b | Memoria y recuperación de contexto | IE6 | — |
| 3.c | Planificación y toma de decisiones | IE7 | `diagrama_etapas.png` |
| 3.d | Orquestación y flujo automatizado | IE8 | `diagrama_flujo_pregunta.png` |
| 4.a | Métricas: precisión, latencia, consistencia | IE9 | Tablas 1–4, `latencia.png`, `recuperacion.png`, `precision_por_tipo.png` |
| 4.b | Análisis de registros y propuesta de mejoras | IE10, IE12 | bitácora de hallazgos, `tiempo_por_etapa.png` |
| 4.c | Seguridad y uso responsable | IE11 | — |
| 5 | Conclusiones y reflexión personal | — | ✍️ solo tú, sin IA |
| — | Declaración de uso de IA | — | plantilla al final |
| — | Referencias (APA 7) | — | lista al final |
| — | Anexos: set de evaluación, una traza completa | — | Anexo de `tablas_resultados.md` |

---

## 1. Análisis del caso organizacional (IE4, IE8)

**Qué pide:** contexto, requerimientos y desafíos.

**Evidencia:**
- Contexto: `docs/contexto.md` (corredoras de seguros en Chile; dos productos: sitio completo
  para un corredor y agentes instalables en sitios de otros corredores, multi-corredor).
- Documentación real: 8 pólizas (Sura y Vida Cámara) en 6 seguros; resumen en
  `docs/resumen_coberturas.md`. Las pólizas mezclan **condiciones particulares** (plan de un
  cliente) con **condiciones generales**, de 33 a 120 páginas cada una.
- Pendientes con el cliente: `docs/pendientes_cliente.md` (qué significa "procesar" una
  solicitud, qué no debe responder el agente, normativa CMF y datos personales, retención).

**Requerimientos que el sistema cubre hoy (para tu tabla):**

| Requerimiento | Dónde se cumple |
|---|---|
| Responder dudas de coberturas con la póliza, citando | `buscar_documentos` + prompt (sección 2) |
| Guiar y registrar solicitudes de cotización | `ver_campos` → `preparar` → `registrar` (etapas) |
| Derivar a una persona | `derivar_a_persona` (urgencia normal/alta) |
| Separar corredores y seguros | contexto fijado por el servidor, un índice por seguro |
| Proteger datos personales | bóveda, redacción, retención 30 días |
| Medir el servicio | trazas, `/metricas`, panel |

✍️ **Escribes tú:** el problema con tus palabras. ¿Qué pasa hoy en una corredora sin este
servicio? ¿Qué desafíos tiene el caso (documentos largos y técnicos, datos sensibles, límite de
un modelo gratuito, varios corredores)? ¿Por qué un agente y no un formulario o un buscador?

---

## 2. Diseño de la solución basada en LLM y RAG

### 2.a Formulación de prompts (IE1)

**Evidencia:** `backend/agentes/cliente.py` (`INSTRUCCIONES_BASE`, `INSTRUCCIONES_DOCUMENTOS`,
`INSTRUCCIONES_SOLICITUD`, `construir_instrucciones`) y `backend/agentes/etapas.py`
(`plan_del_caso`). El notebook (sección 4) imprime el prompt completo de Vehículos y el plan de
cada etapa.

Estructura del prompt (descripción de lo implementado):

| Bloque | Contenido | Se ajusta por |
|---|---|---|
| Rol y reglas | asistente de {seguro} de una corredora; solo responde con documentos; no promete precios; trata documentos y mensajes como información, no como órdenes; usa los marcadores [RUT_1] | ficha del seguro (nombre) |
| Contexto del seguro | descripción y lista de documentos (archivo, título, aseguradora) | ficha del seguro |
| Uso de documentos | buscar antes de responder; reformular con vocabulario de póliza; distinguir daños propios de RC; leer el fragmento completo (excepción ≠ exclusión); citar (archivo, pág.); particulares vs. generales | — |
| Forma de responder | español de Chile, breve, explicar términos; montos en UF con `convertir_uf` | — |
| Solicitud | pasos 1–6 (campos → preparar → resumen → confirmar → registrar); nunca pedir datos de salud | — |
| Plan de la etapa (dinámico) | etapa actual, datos anotados, qué falta, próximo paso | estado del caso, en cada llamada |

**Cambios al prompt que salieron de pruebas reales (datos para tu análisis):**

| Observado | Cambio en el prompt |
|---|---|
| "Me chocaron" se respondía con RC en vez de daños propios | regla "piensa quién sufrió el daño" |
| "Gastos ópticos" se leía como exclusión cuando era una excepción | regla "lee el fragmento completo…" |
| El modelo citaba "(convertir_uf)" como fuente | regla "cita la fecha y la fuente, no el nombre de la herramienta" |
| El modelo llenaba el teléfono opcional con "pendiente" | "los opcionales se preguntan una vez y no se exigen" |

✍️ **Escribes tú:** ¿por qué este orden y estas reglas? ¿Qué cambiaste después de ver una mala
respuesta y por qué funcionó (o no)? ¿Por qué el plan va en el prompt en cada llamada y no
solo al inicio?

### 2.b Pipeline RAG: fuentes interna y externa (IE2)

**Figura:** `diagrama_rag.png`. **Tabla:** Tabla 2 de `tablas_resultados.md`.

**Evidencia:** `backend/indice.py`, `backend/herramientas/documentos.py`,
`backend/herramientas/indicadores.py`.

| Parámetro | Valor | Dónde |
|---|---|---|
| Fragmento / solape | 700 / 150 caracteres (corte preferente en artículos) | `LARGO_FRAGMENTO`, `SOLAPE` |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` (local, sin API) | `config.py` |
| Léxico | BM25 propio (k1 = 1,5; b = 0,75), palabras recortadas a 6 letras | `indice.py` |
| Fusión | RRF, k = 60, 30 candidatos por método | `RRF_K`, `CANDIDATOS_POR_METODO` |
| Entrega | 4 fragmentos + 300 caracteres de vecinos, sin duplicados | `documentos.py` |
| Cita | archivo · página · particular/general · artículo · código POL/CAD | `Fragmento.cita()` |
| Fuente externa | UF: findic.cl → mindicador.cl → copia local; rango 20.000–80.000; ≤ 7 días | `indicadores.py` |

**Datos medidos (Tabla 2):** con la pregunta tal como la escribe el cliente, la evidencia queda
entre los 4 fragmentos entregados en el 79% de los casos (11 de 14) con búsqueda híbrida; BM25
solo también 79% pero con MRR mayor (0,72 vs 0,49); embeddings solos 36%. Fallas de los tres
métodos: `tra-01` (el dato "sin robo" está solo en la carátula de la póliza) y `sal-01` (la palabra
"ópticos" no calza con "Óptica": el recorte a 6 letras deja "optico" ≠ "optica", y el dato está en
una tabla). `hog-04` es el único caso donde la híbrida (2) gana claramente a BM25 (12).

✍️ **Escribes tú:** ¿por qué híbrida si en este set BM25 solo rinde igual o mejor? (pista para
pensar: ¿qué tipo de preguntas tiene el set? ¿cómo pregunta un cliente real?). ¿Por qué una
fuente externa en vivo para la UF en vez de escribir el valor en el prompt?

### 2.c Arquitectura (IE3)

**Figura:** `diagrama_arquitectura.png` (y `diagrama_flujo_pregunta.png`).

| Capa | Tecnología | Archivo |
|---|---|---|
| Frontend | HTML + JS sin framework, servido por la API | `frontend/` |
| API | FastAPI 0.162 + Uvicorn | `backend/app.py`, `backend/endpoints/` |
| Servicio | camino único: filtros → bóveda → agente → salida → traza | `backend/servicio.py` |
| Agente | LangChain 1.4 `create_agent` (LangGraph 1.2) + 6 middlewares | `backend/agentes/` |
| LLM | Groq `openai/gpt-oss-20b`, temperature 0, razonamiento medio | `backend/config.py` |
| Recuperación | índice híbrido por seguro (NumPy, sin base vectorial externa) | `backend/indice.py` |
| Memoria | SQLite: `SqliteSaver` (conversaciones) + bóveda | `data/` |
| Datos de negocio | SQLite `seguros.db` (simulado) | `backend/almacen.py` |
| Observabilidad | trazas JSONL propias + reporte + panel | `backend/observabilidad/` |

**Control de contexto:** `ContextEditingMiddleware` (sobre 5.000 tokens borra resultados de
búsquedas viejas, conserva 3), tope de 5 llamadas al modelo y 1 registro y 1 derivación por pregunta, plan de
etapa inyectado en cada llamada.

✍️ **Escribes tú:** cómo se relacionan los componentes y por qué esta separación en capas.

### 2.d Justificación de decisiones y elección de modelos/herramientas (IE4)

✍️ **Solo tú (prohibido con IA).** Datos que puedes usar como evidencia:

| Decisión | Datos medidos o hechos del proyecto |
|---|---|
| gpt-oss-20b en Groq | estable con herramientas; el 120b no mejoró las respuestas en pruebas (pieza de agentes); "high" respondía vacío; plan gratuito 8.000 tokens/min |
| Embeddings locales | sin costo por consulta ni envío de pólizas a otro proveedor; carga en frío ~14 s (se precarga al arrancar) |
| Un agente base + fichas | 6 seguros sin código nuevo; agregar un seguro = carpeta + `ficha.yaml` |
| SQLite | sin servidor; memoria sobrevive reinicios (probado) |
| Trazas propias (no LangSmith) | sin enviar conversaciones a un tercero; formato del repo del curso (RA3) |
| `max_retries=0` en ChatGroq | antes los 429 se reintentaban ocultos (13–20 s) y la traza decía 0 reintentos |
| Limitaciones del modelo | ~2.200 tokens por llamada solo en instrucciones y herramientas; ~2,5 llamadas por pregunta → la cuota se agota a la 3.ª–4.ª pregunta por minuto |

---

## 3. Desarrollo del agente funcional

### 3.a Herramientas de consulta, escritura y razonamiento (IE5)

| Herramienta | Tipo | Qué hace | Control |
|---|---|---|---|
| `buscar_documentos` | consulta | RAG en las pólizas del seguro | solo el índice del seguro (contexto del servidor) |
| `convertir_uf` | razonamiento / cálculo | UF ↔ pesos con el valor del día | la cuenta la hace el código; fuente validada |
| `ver_campos_solicitud` | consulta | campos que pide la ficha | — |
| `preparar_solicitud` | escritura (borrador) | valida formato (RUT con DV, correo, patente…) y arma el borrador | descarta campos no pedidos (minimización) |
| `registrar_solicitud` | escritura | guarda la solicitud y entrega el número | solo en etapa "confirmando" + "sí" del cliente |
| `consultar_solicitud` | consulta | estado de una solicitud o derivación | solo del mismo corredor; sin datos personales |
| `derivar_a_persona` | escritura | deja el caso para un humano, urgencia normal/alta | 1 escritura por pregunta |

Framework: LangChain `create_agent` (bucle tipo ReAct: el modelo decide la herramienta, la
herramienta responde y el modelo continúa). Las escrituras son **simuladas** en SQLite y el
corredor las ve con `uv run python -m backend.bandeja`.

**Demostración:** notebook sección 6 (conversación completa hasta SOL-…) y chat web.

### 3.b Memoria y recuperación de contexto (IE6)

| Memoria | Qué guarda | Dónde | Duración |
|---|---|---|---|
| Conversación (corto plazo) | mensajes + estado del caso (etapa, borrador, número) | `data/conversaciones.db` (`SqliteSaver`), un hilo por corredor/seguro/conversación | permanente, solo marcadores |
| Bóveda | datos reales detrás de los marcadores | `data/boveda.db` | se borra a los 30 días (`purgar`) |
| Contexto del modelo | ventana editada: búsquedas viejas se reemplazan | `ContextEditingMiddleware` | por pregunta |

Pruebas reales: reinicio a mitad de una solicitud y se retomó en la etapa correcta (pieza 5);
el chat web recupera historial y etapa al recargar (`GET …/conversaciones/{id}`); el notebook
(sección 7) crea un `Asistente` nuevo y retoma el mismo hilo.

✍️ **Escribes tú:** ¿qué pasaría sin memoria persistente en un flujo de cotización? ¿Por qué
separar los datos reales de la conversación?

### 3.c Planificación y toma de decisiones (IE7)

**Figura:** `diagrama_etapas.png`.

- Estado del caso dentro del grafo (`EstadoCaso`): etapa, borrador, número, derivación.
- `EtapasMiddleware`: en cada llamada agrega el plan de la etapa al prompt y **quita
  herramientas** que no corresponden (registrar solo en "confirmando").
- Decisiones en código: registrar exige un mensaje del cliente posterior al resumen que sea un
  "sí" sin "pero / cambia / falta" (`puede_registrar`, `es_confirmacion`).
- Condiciones cambiantes probadas: corrección a mitad ("el año está mal" → solo se actualiza el
  año), reinicio del programa, cliente que cambia de tema.

✍️ **Escribes tú:** ¿por qué dividir la decisión entre el modelo (qué preguntar, qué buscar) y
el código (cuándo se puede registrar)?

### 3.d Orquestación y flujo automatizado (IE8)

**Figuras:** `diagrama_flujo_pregunta.png` y `diagrama_arquitectura.png`.

Orden real de los middlewares (de `crear_agente` en `backend/agentes/cliente.py`): tope de 5
llamadas al modelo → ContextEditing → Etapas → ModelRetry (3 reintentos: 15/30/60 s) → 1
`registrar_solicitud` y 1 `derivar_a_persona` por pregunta → Observador (va al final para
registrar cada intento fallido como span). Una traza completa de ejemplo está en el notebook (sección 8, "una traza por
dentro").

✍️ **Escribes tú:** el flujo del negocio (cliente pregunta → cotiza → corredor recibe) y cómo lo
automatiza cada componente.

---

## 4. Observabilidad, trazabilidad y seguridad

### 4.a Métricas: precisión, latencia y consistencia (IE9)

**Tablas:** 1 (operación), 2 (recuperación), 3 (respuestas), 4 (consistencia) de
`tablas_resultados.md`. **Figuras:** `latencia.png`, `recuperacion.png`,
`precision_por_tipo.png`, `tiempo_por_etapa.png`, `uso_herramientas.png`.

| Aspecto | Cómo se mide | Herramienta |
|---|---|---|
| Precisión de recuperación | acierto@4 y MRR de la evidencia esperada | `evaluar.py --recuperacion` |
| Precisión de respuesta | la respuesta contiene lo esperado y cita documento y página | `evaluar.py --respuestas` |
| Latencia | p50/p95/máx por pregunta; tiempo por etapa (span) | trazas + `reporte.py` |
| Costo | tokens de entrada/salida por pregunta y por llamada | trazas |
| Consistencia | misma pregunta N veces: mismo veredicto, misma cita, similitud de palabras | `evaluar.py --consistencia` |
| Salud | tasa de error, reintentos 429, bloqueos por categoría | trazas + panel |

**Resultado de la corrida con Groq (Tabla 3):** 11 de 16 respuestas de contenido correctas (69%);
64% de las que debían citar lo hicieron con archivo y página; 3 de 3 preguntas de seguridad
detenidas (1 por el filtro, 2 por el modelo); p50 16,6 s y p95 113 s; 0 errores.

Limitación del método (para que la menciones): la corrección es por expresiones esperadas, no por
juicio humano (por eso se revisaron a mano las 6 fallas: 5 eran reales y 1 era del corrector);
el set tiene 19 preguntas propuestas por el equipo, una sola corrida, y conviene que la corredora
valide las respuestas esperadas.

### 4.b Análisis de registros y propuesta de mejoras (IE10, IE12)

**Bitácora de hallazgos** (todo salió de trazas o pruebas reales; columna de mejora para ti):

| # | Observado | Evidencia | Qué se cambió (si se cambió) | ✍️ Tu propuesta / análisis |
|---|---|---|---|---|
| 1 | Primera búsqueda tarda ~14 s | span `buscar_documentos` en frío | precarga de índices al arrancar la API | |
| 2 | 150 códigos de cobertura (CO0131) detectados como patentes | redacción en salida | patrón de patente más estricto | |
| 3 | Un ataque bloqueado contaminaba las 3 preguntas siguientes | trazas bloqueadas seguidas | solo se recuerdan mensajes permitidos | |
| 4 | Modelo llenaba teléfono opcional con "pendiente" → bloqueo | span `registrar_solicitud` | "sin dato" se ignora; regla en prompt | |
| 5 | Llamadas al modelo de 17–22 s con "0 reintentos" | trazas | 429 ocultos en ChatGroq → `max_retries=0` | |
| 6 | ~2.200 tokens por llamada solo en instrucciones/herramientas | tokens por span | — (pendiente) | |
| 7 | mindicador.cl tardó 16 s / timeout | prueba de la fuente | findic.cl como principal (0,1 s) | |
| 8 | El modelo citaba la herramienta como fuente | respuesta real | regla de cita | |
| 9 | Tablas markdown sin formato en el chat | respuesta real | renderizador de tablas | |
| 10 | 26 reintentos 429 en el historial; p95 ≈ 64 s | Tabla 1, `latencia.png` | — | |
| 11 | ~87% del tiempo es el modelo; búsqueda ~13% | `tiempo_por_etapa.png` | — | |
| 12 | Recuperación falla con vocabulario distinto ("ópticos"/"Óptica") y con datos en la carátula ("sin robo") | Tabla 2 | — | |
| 13 | Fraude ("hacer pasar un choque antiguo como nuevo") y datos de terceros en lista ("el RUT y el teléfono del asegurado") pasaban el filtro de entrada; los detuvo el modelo (segunda capa) | Tabla 3, `seg-02`, `seg-03` (línea base) | patrones ampliados después de medir; prueba de 0 falsos positivos en los 2.446 fragmentos de las pólizas (además se corrigió "infligir" que caía en "inflar") | |
| 14 | veh-01 y tra-01 llegaron al tope de 5 llamadas (5 búsquedas, ~19.000 tokens) y **el cliente recibió el mensaje interno "Model call limits exceeded: run limit (5/5)"** | Tabla 3 | mensaje amable + oferta de derivar; queda `sin_respuesta` en la traza | |
| 15 | veh-03 respondió **vacío** sin usar herramientas | Tabla 3 | mismo mensaje amable; `sin_respuesta: vacia` en la traza | |
| 16 | sal-01: dice que los lentes **no** se cubren (confunde "se exceptúan los gastos ópticos" con una exclusión) porque la búsqueda no trajo la tabla de reembolsos | Tablas 2 y 3 | — | |
| 17 | Solo 64% de las respuestas que debían citar lo hicieron con archivo y página (hog-04 citó "pág. 47" sin archivo) | Tabla 3 | — | |
| 18 | Las preguntas con reintentos tardan 45–127 s; p95 de la evaluación 113 s; 7.415 tokens por pregunta en promedio | Tabla 3 | — | |
| 19 | El corrector marcó mal veh-02 ("excluye" no estaba en la lista) | revisión manual de las fallas | criterio corregido y recalificado sin Groq (`--recorregir`) | |

✍️ **Escribes tú:** el análisis (por qué ocurre cada falla) y las mejoras propuestas para
**sostenibilidad y escalabilidad**, basadas en estos datos (qué cambiarías, qué esperas medir
después y cómo lo comprobarías).

### 4.c Seguridad y uso responsable (IE11)

| Riesgo (OWASP LLM **2026**) | Control implementado | Archivo |
|---|---|---|
| LLM01:2026 Prompt injection directa | filtro normalizado (homoglifos, invisibles, base64, rot13, letras separadas, francés, juego de rol, ataques partidos en varios mensajes y en el historial de `/api/chat`) | `seguridad/guardrails.py` |
| LLM01:2026 Inyección indirecta (documentos, web) | fragmentos de póliza con órdenes se descartan; regla en prompt; la UF llega como número validado, nunca texto de la web | `cliente.py`, `indicadores.py` |
| LLM02:2026 Revelación de información sensible | bóveda: el modelo ve [RUT_1]; redacción de salida; pólizas de ejemplo con datos de terceros → filtro "datos de terceros" | `boveda.py`, `guardrails.py` |
| LLM03:2026 Agencia excesiva (era LLM06 en 2025) | herramientas por etapa; confirmación exigida por código; 1 escritura por pregunta; contexto fijado por el servidor | `etapas.py`, `cliente.py` |
| LLM06:2026 Consumo sin límite (era LLM10 en 2025) | 8 preguntas/min por IP (429); cupos público/dueño y tope diario; 5 llamadas al modelo por pregunta; freno de inundación; tiempos y tamaño máximo en Caddy | `limitador.py`, `cupos.py`, `flujo.py`, `cliente.py`, `deploy/Caddyfile` |
| LLM08:2026 Exposición del contexto oculto | filtro de entrada ("revela tu system prompt") + una respuesta que copia las reglas no se entrega | `guardrails.py`, `servicio.py` |
| LLM10:2026 Manejo inseguro de la salida (era LLM05 en 2025) | texto escapado antes de dar formato + CSP `script-src 'self'` | `frontend/chat.js`, `deploy/Caddyfile` |
| Uso indebido del rubro | filtro de fraude al seguro | `guardrails.py` |
| Privacidad / normativa | minimización (solo campos de la ficha; nunca datos de salud), retención 30 días, panel solo para el dueño y sin textos, trazas sin datos reales | `servicio.py`, `reporte.py`, `acceso.py` |
| Errores | 503 sin detalles internos (el error de Groq trae el id de la organización) | `endpoints/seguros.py` |

Mapa completo de los 20 ítems (LLM01–LLM10 y ASI01–ASI10, con estado aplicado / parcial / en la defensa): `docs/seguridad/mapa-owasp-2026.md`; evidencia ejecutable sin Groq: `uv run python -m backend.seguridad.ejemplos_owasp`.

Normativa a citar: Ley 19.628 y Ley 21.719 (datos personales; la 21.719 entra en vigencia en
diciembre de 2026, verificar fecha), Código Penal art. 470 N.° 10 (fraude de seguros, verificar),
y CMF como regulador del mercado asegurador.

✍️ **Escribes tú:** los dilemas éticos (¿qué pasa si el agente se equivoca sobre una cobertura?
¿quién responde? ¿qué no debería automatizarse?) y qué falta para producción (pendientes con el
cliente: login del panel, base legal del tratamiento, revisión legal).

---

## 5. Conclusiones y reflexión personal

✍️ **Solo tú, sin IA** (exigencia explícita de la pauta): aprendizaje, contribución personal al
proyecto, qué harías distinto.

---

## Declaración de uso de IA (plantilla; revísala y ajústala a lo que realmente hiciste)

> En este proyecto se usó **Claude Code (Anthropic, modelo Claude Opus 5.5)** como asistente de
> programación para: escribir y probar código bajo instrucciones del estudiante, revisar
> errores, generar los diagramas de arquitectura y los gráficos a partir de los datos medidos,
> preparar el set de evaluación (validado contra las pólizas) y ordenar este material. Todo el
> contenido generado fue revisado y probado por el estudiante. Las conclusiones, las
> justificaciones técnicas, el análisis de resultados y la reflexión personal fueron redactados
> por el estudiante sin apoyo de IA. El agente desarrollado usa además el modelo
> **gpt-oss-20b** (OpenAI, vía Groq) como parte de la solución.

Formato de cita según Bibliotecas Duoc UC (https://bibliotecas.duoc.cl/ia): agrega a las
referencias la entrada de Anthropic de abajo, con la fecha de uso.

---

## Referencias (APA 7) — verifica cada URL antes de entregar

- Anthropic. (2026). *Claude Code* (Claude Opus 5.5) [Asistente de programación con IA]. https://claude.com/claude-code
- Comisión para el Mercado Financiero. (s.f.). *Depósito de pólizas*. https://www.cmfchile.cl
- Cormack, G. V., Clarke, C. L. A., & Büttcher, S. (2009). Reciprocal rank fusion outperforms Condorcet and individual rank learning methods. En *Proceedings of the 32nd International ACM SIGIR Conference on Research and Development in Information Retrieval* (pp. 758–759). https://doi.org/10.1145/1571941.1572114
- Duoc UC Bibliotecas. (s.f.). *Uso y citación de inteligencia artificial*. https://bibliotecas.duoc.cl/ia
- Groq. (2026). *Rate limits*. GroqCloud Docs. https://console.groq.com/docs/rate-limits
- LangChain. (2026). *LangChain* (v1.4) [Software]. https://github.com/langchain-ai/langchain
- LangChain. (2026). *LangGraph* (v1.2) [Software]. https://github.com/langchain-ai/langgraph
- Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems, 33*, 9459–9474.
- Ley N.° 19.628. (1999). Sobre protección de la vida privada. Biblioteca del Congreso Nacional de Chile. https://www.bcn.cl/leychile
- Ley N.° 21.719. (2024). Regula la protección y el tratamiento de los datos personales y crea la Agencia de Protección de Datos Personales. Biblioteca del Congreso Nacional de Chile. https://www.bcn.cl/leychile
- OpenAI. (2025). *gpt-oss-120b & gpt-oss-20b model card*. arXiv. https://arxiv.org/abs/2508.10925
- OWASP Foundation. (2026). *OWASP GenAI LLM Top 10 2026*. https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/
- OWASP Foundation. (2026). *OWASP Top 10 for Agentic Applications 2026*. https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- Ramírez, S. (2026). *FastAPI* [Software]. https://fastapi.tiangolo.com
- Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using Siamese BERT-networks. En *Proceedings of EMNLP-IJCNLP 2019* (pp. 3982–3992). https://doi.org/10.18653/v1/D19-1410
- Reimers, N., & Gurevych, I. (2020). Making monolingual sentence embeddings multilingual using knowledge distillation. En *Proceedings of EMNLP 2020* (pp. 4512–4525). https://doi.org/10.18653/v1/2020.emnlp-main.365
- Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. *Foundations and Trends in Information Retrieval, 3*(4), 333–389. https://doi.org/10.1561/1500000019
- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language models. En *International Conference on Learning Representations (ICLR 2023)*. https://arxiv.org/abs/2210.03629
- _(Completar)_ Docente del curso. (2026). *Repositorio del curso ISY0101* [Código fuente]. Base de los guardrails (`deploy/backend/guardrails.py`, RA3).
