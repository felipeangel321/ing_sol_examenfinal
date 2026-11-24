# CLAUDE.md — Proyecto Seguros

Agentes de IA para corredores de seguros en Chile (un agente base + una ficha por seguro).
Es también el proyecto de la **EFT de ISY0101 (Ingeniería de Soluciones con IA)**, entrega la
semana del 2026-11-23: informe PDF + notebook Jupyter/Colab + defensa de 10 min con prototipo
y dashboard. Pauta: `EFT_ISY0101_Estudiante.pdf` (raíz).

## Reglas de trabajo con Felipe (obligatorias)

- **Commits y push los hace Felipe.** Nunca hacer commit/push ni agregar atribución de Claude.
- **No abrir ventanas** (navegador, VS Code, apps) sin preguntar: dar la ruta o la URL.
- **Avanzar de a una pieza** y esperar su aprobación ("sigue", "ok"). No adelantar piezas ni
  inventar servicios. Lo que depende del cliente real va a `docs/pendientes_cliente.md`.
- **Preguntar antes de tocar archivos ya entregados.** Si el pedido es ambiguo, explicar primero.
- Explicaciones en español, con piezas numeradas, tablas y diagramas ASCII.
- **Pauta de IA:** la IA NO redacta conclusiones, justificaciones técnicas, análisis ni la
  reflexión personal del informe. Se le entregan datos, evidencia y preguntas guía (recuadros
  ✍️ en `docs/informe/material_informe.md`); el texto lo escribe Felipe.
- Los datos personales de las pólizas de ejemplo no le preocupan: no insistir con eso.

## Comandos

```
uv sync                                                  # instalar
uv run pytest                                            # pruebas (sin Groq; testpaths = tests/)
uv run python -m backend.indice                          # construir índices (~3 min la 1.ª vez)
uv run python -m backend.chat --seguro hogar             # chat en consola
uv run uvicorn backend.app:app                           # web: / (chat) y /panel.html (métricas)
uv run python -m backend.observabilidad.reporte          # métricas desde .trazas/
uv run python -m backend.bandeja                         # solicitudes registradas
uv run python -m backend.seguridad.ejemplos_owasp         # OWASP 2026: 20 ítems con evidencia, sin Groq
uv run python -m backend.evaluacion.evaluar --recuperacion | --respuestas | --consistencia 3 | --recorregir
uv run --group notebook python entrega/generar_notebook.py --ejecutar   # NOTEBOOK_SIN_GROQ=1 para no llamar a Groq
uv run --group notebook python entrega/diagramas.py
uv run --group notebook python -m backend.observabilidad.graficos docs/informe/figuras
uv run python entrega/tablas_informe.py                  # → docs/informe/tablas_resultados.md
```

## Arquitectura (dónde está cada cosa)

| Ruta | Qué hace |
|---|---|
| `corredores/<c>/seguros/<s>/` | `ficha.yaml` (campos, documentos) + `documentos/*.pdf`. Agregar seguro = carpeta nueva |
| `backend/indice.py` | RAG: PDF → fragmentos con cita → BM25 + MiniLM, fusión RRF; índice por seguro en `.indices/` |
| `backend/agentes/cliente.py` | prompt, 7 herramientas, `create_agent` + middlewares (orden: tope 5 llamadas → ContextEditing → Etapas → ModelRetry → límites de escritura → Observador) |
| `backend/agentes/etapas.py` | estado del caso: consulta → recopilando → confirmando → registrada; registrar solo con "sí" posterior al resumen |
| `backend/herramientas/` | buscar, convertir_uf (findic.cl → mindicador.cl → caché), solicitudes, derivación (SQLite, SIMULADO) |
| `backend/seguridad/` | filtros de entrada (injection, fraude, datos de terceros) y de salida (fuga de instrucciones), bóveda de seudónimos, límite por minuto, `cupos.py` (público/dueño), `acceso.py` (link secreto `/entrar?clave=`, cookie HMAC), `flujo.py` (freno de inundación), `ejemplos_owasp.py` |
| `backend/servicio.py` | camino único de cada pregunta: filtros → bóveda → agente → salida → traza; memoria SQLite |
| `backend/observabilidad/` | trazas JSONL (`.trazas/`), reporte, gráficos |
| `backend/endpoints/`, `backend/app.py` | API FastAPI: chat, conversaciones, `/metricas`; `api.py` = `/api/health`, `/api/chat`, `/api/metrics` con el formato exacto del `deploy/` del curso (el profe ataca con un agente basado en su repo) |
| `frontend/` | `index.html`+`chat.js` (chat) y `panel.html`+`panel.js` (dashboard); JS en archivos aparte por la CSP `script-src 'self'` |
| `backend/evaluacion/` | `preguntas.yaml` (19 preguntas, respuestas esperadas = PROPUESTA) + `evaluar.py` |
| `entrega/` | generadores del notebook, diagramas y tablas; `documentos_demo.zip` para Colab |
| `docs/informe/` | material del informe, tablas, guion de defensa, figuras |
| `docs/seguridad/` | `mapa-owasp-2026.md` y `checklist-seguridad-despliegue.md` (mismo formato que RA3/IL3.5 del curso) |
| `deploy/` | Docker (app + Caddy HTTPS) para AWS Academy Learner Lab, basado en el `deploy/` del curso; guía en `deploy/README.md` |

## Detalles que importan

- **Groq gratis:** 8.000 tokens/min y **200.000 tokens/día** (gpt-oss-20b). ~2.200 tokens por
  llamada; la evaluación completa gasta ~140.000. `ChatGroq(max_retries=0)` a propósito: los
  reintentos los hace ModelRetryMiddleware para que queden en la traza.
- Los errores 429 de Groq traen el id de la organización: no mostrar trazas crudas; el notebook
  y la evaluación lo ocultan (`org_[oculto]`).
- `.env`, `data/`, `.trazas/`, `.indices/`, `.evaluaciones/`, `*.pdf` y `entrega/*.zip` están en
  `.gitignore`.
- Las pruebas usan `ModeloFalso` (`tests/test_observabilidad.py`) y `BUSQUEDA_SEMANTICA=false`.
- Windows + Git Bash: los heredocs rompen los `\n` y `\s` dentro de código Python; para editar
  código usar la herramienta Edit o un script escrito con Write.
- Código, comentarios y textos en español de Chile.
- **Despliegue (2026-11-24):** en Linux torch sale del índice CPU (`[tool.uv.sources]`); la
  imagen trae MiniLM e índices; `TOPE_DIARIO_PREGUNTAS` (solo servidor, 25) protege la cuota
  de Groq; `ENABLE_DOCS=false` apaga /docs. En el Learner Lab la IP cambia por sesión:
  `deploy/iniciar.sh` (y el servicio systemd) la reescribe en `deploy/.env`. No hay Docker
  en el PC de Felipe: la imagen nunca se construyó en local, se construye en la EC2.
- `uv sync` a secas quita el grupo `notebook` del .venv: usar `uv sync --group notebook`.
- **Referencia del profe para revisar:** `Desktop/Ing sol/Ingenier-a-de-Soluciones-con-Inteligencia-Artificial`
  (`RA3/IL3.5/`: guía AWS, checklist, mapa OWASP 2026; `deploy/`). Límite por minuto y tope
  diario responden **429**; el historial de `/api/chat` se valida pero no llega al modelo.

## Estado (2026-11-24)

Despliegue y ciberseguridad listos para AWS (sin commit; Felipe hace commit/push). 236 pruebas
OK, notebook regenerado (236 passed, 0 errores, sin Groq). Probado en local con Caddy real +
modelo falso: injection/historial/partido → 200 bloqueado; 25 "hola" → 1×200 + 24×429; XFF
falso no evita el límite; panel 403 sin link; http→https 308; CSP; cuerpo 200 KB → 413;
inundación → 429 sin trazas. El profe atacará con un agente basado en SU repo: no cambiar el
formato de `/api/*`.

## Estado anterior (2026-11-17)

Piezas listas: observabilidad, seguridad, herramientas de escritura, memoria + etapas, fuente
externa UF, API + frontend + panel, evaluación, notebook y material del informe. 166 pruebas OK.

Resultados medidos: recuperación híbrida 79% (BM25 79%, embeddings 36%); respuestas 11/16 (69%),
64% con cita completa; seguridad 3/3; p50 16,6 s, p95 113 s. Detalle en
`docs/informe/tablas_resultados.md` y bitácora de hallazgos en `material_informe.md`.

**Pendiente (necesita cuota de Groq):**
1. `evaluar --consistencia 3` (Tabla 4 vacía).
2. Re-ejecutar el notebook con Groq (sección 6 y 7 salen "omitido").
3. Regenerar tablas y figuras después de 1 y 2.
4. Probar el notebook en Colab real (solo se probó en local).
5. Felipe revisa chat, panel y material; escribe las secciones ✍️ del informe.
