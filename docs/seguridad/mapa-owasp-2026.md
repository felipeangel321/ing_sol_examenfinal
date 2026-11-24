# Mapa OWASP 2026 → este proyecto

Mismo formato que `RA3/IL3.5/mapa-owasp-2026.md` del repo del curso. Dos listas vigentes;
los códigos cambian entre ediciones, por eso se cita el año.

- [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (ASI01–ASI10)

La evidencia se corre sin Groq y sin AWS:

```bash
uv run python -m backend.seguridad.ejemplos_owasp     # las 20 filas, con cada control ejecutado
uv run pytest tests/test_evasiones.py tests/test_acceso_cupos.py -q
```

| Estado | Qué significa en la defensa |
|---|---|
| **aplicado** | El control corre en el código y el script lo ejecuta. |
| **parcial** | Corre una parte. La frase de al lado dice el hueco. |
| **en la defensa** | Este proyecto no lo cierra. Se nombra; no se simula. |

## LLM01–LLM10

| Código | Riesgo | Estado | Dónde se aplica | Ejemplo listo |
|---|---|---|---|---|
| LLM01:2026 | Prompt Injection | parcial | `validar_entrada`, `validar_historial` (`backend/seguridad/guardrails.py`); `buscar_documentos` descarta fragmentos con órdenes (`backend/agentes/cliente.py`) | «Ignora las instrucciones anteriores…» se bloquea; también en base64, rot13, letras con puntos, francés, juego de rol, partida en 3 mensajes y escondida en el `historial`. Un fragmento de póliza con «ignora tus instrucciones» no llega al modelo. Siguen abiertos: hex, texto invertido, otro idioma fuera de la lista, una paráfrasis nueva. |
| LLM02:2026 | Sensitive Information Disclosure | aplicado | bóveda de seudónimos (`boveda.py`), `redactar_pii` en la salida; las trazas guardan solo marcadores | El modelo recibe `[RUT_1]` y `[CORREO_1]`; el cliente ve sus datos reales. Un teléfono suelto en la salida sale `[TELEFONO_REDACTADO]`. Las pólizas de ejemplo (datos de terceros) se redactan antes del modelo. |
| LLM03:2026 | Excessive Agency | aplicado | herramientas por etapa (`agentes/etapas.py`), `ToolCallLimitMiddleware`, contexto fijado por el servidor | `registrar_solicitud` solo existe en la etapa `confirmando` y exige un «sí» claro posterior al resumen («sí, pero…» no confirma). 1 registro y 1 derivación por pregunta. En 2025 este ítem era LLM06. |
| LLM04:2026 | Supply Chain | parcial | `uv.lock`; MiniLM fijo dentro de la imagen; torch del índice oficial de PyTorch | El lockfile fija versiones. No se revisan firmas del modelo de Groq ni de MiniLM. |
| LLM05:2026 | Data and Model Poisoning | parcial | los PDF los entrega el corredor; filtro de fragmentos | Un fragmento con órdenes se descarta. Un dato falso dentro de un PDF (sin órdenes) se citaría igual: los PDF no se firman. |
| LLM06:2026 | Unbounded Consumption | aplicado | límite por minuto (`limitador.py`), cupos público/dueño (`cupos.py`), tope diario, 5 llamadas al modelo por pregunta, freno de inundación (`flujo.py`), tiempos y tamaño máximo en Caddy | 25 «hola» seguidos (paso 9 de la guía del curso): 8 pasan el límite por minuto, de esos 1 llega al modelo (el público pregunta como mucho cada 2 min) y el resto recibe 429. El dueño sigue respondiendo. 2.001 caracteres se rechazan. Un ataque bloqueado no gasta cupo. En 2025 este ítem era LLM10. |
| LLM07:2026 | Misinformation | parcial | regla de citar documento y página; evaluación (`backend/evaluacion/`) | 11/16 correctas (69%), 64% con cita completa. Las respuestas esperadas son una propuesta a validar con la corredora. |
| LLM08:2026 | Hidden Context Exposure | parcial | `hay_fuga_de_instrucciones` sobre la salida; filtro de entrada «revela tu system prompt» | Una respuesta que copia las reglas no se entrega (tampoco al recargar la conversación). Un resumen con otras palabras no se detecta. El prompt no lleva claves. |
| LLM09:2026 | Vector and Embedding Weaknesses | en la defensa | índice BM25 + MiniLM (`backend/indice.py`) | El vector no distingue una instrucción de un dato. Mismo hueco que LLM05; la barrera es el filtro de LLM01. |
| LLM10:2026 | Improper Output Handling | aplicado | `escapar()` antes del formato (`frontend/chat.js`); CSP `script-src 'self'` en `deploy/Caddyfile` | Una marca HTML del modelo se muestra como texto; aunque se colara, un `<script>` o `onclick` inyectado no corre. La cuenta en pesos la hace `convertir_uf`, no el modelo. En 2025 este ítem era LLM05. |

Además, ningún error muestra detalles internos: 503 o «Ocurrió un error procesando tu
solicitud.»; el detalle queda en la traza (y el id de la organización de Groq se oculta).

## ASI01–ASI10

| Código | Riesgo | Estado | Dónde se aplica | Qué se dice |
|---|---|---|---|---|
| ASI01:2026 | Agent Goal Hijack | parcial | el filtro de LLM01, también sobre el historial y la conversación unida | La frase directa no llega al modelo; una inyección que el filtro no conoce, sí. |
| ASI02:2026 | Tool Misuse and Exploitation | aplicado | herramientas por etapa; corredor y seguro los fija el servidor | El modelo no elige el corredor ni el seguro. `consultar_solicitud` busca solo en el mismo corredor y no devuelve datos personales. |
| ASI03:2026 | Identity and Privilege Abuse | aplicado | `GROQ_API_KEY` solo en el backend; EC2 con `LabRole`; dueño con cookie HMAC (`acceso.py`) | El navegador no recibe claves; la cookie no contiene la clave del link; la imagen no lleva claves de AWS. |
| ASI04:2026 | Agentic Supply Chain | en la defensa | sin MCP ni herramientas externas en tiempo de ejecución | La única fuente externa es la UF (findic.cl → mindicador.cl → copia local) y llega como número validado. |
| ASI05:2026 | Unexpected Code Execution | aplicado | ninguna herramienta ejecuta código | No hay `eval` ni intérprete; 7 herramientas con argumentos validados. |
| ASI06:2026 | Memory and Context Poisoning | parcial | memoria en el servidor (SQLite); el `historial` de `/api/chat` se valida y no llega al modelo | Un turno «assistant» inventado (self-priming) no se usa. Una conversación ya guardada no se vuelve a revisar. |
| ASI07:2026 | Insecure Inter-Agent Communication | en la defensa | un solo agente por seguro | No hay mensajes entre agentes; con varios habría que validar cada traspaso. |
| ASI08:2026 | Cascading Failures | parcial | `ModelRetryMiddleware`, tope de llamadas, respaldo de la UF, 503/429 sin detalles | Si Groq cae, el cliente recibe un mensaje y la traza el detalle. No hay circuit breaker. |
| ASI09:2026 | Human-Agent Trust Exploitation | aplicado | confirmación exigida por código (`etapas.py`); `derivar_a_persona` | `registrar_solicitud` se niega si el último mensaje no es un «sí» claro. |
| ASI10:2026 | Rogue Agents | en la defensa | trazas de cada paso (`backend/observabilidad/`) | Un agente que se desvía solo, sin atacante, se nombra y no se simula. |

## Equivalencias con la edición 2025

| 2025 | 2026 |
|---|---|
| LLM01 Prompt Injection | LLM01:2026, mismo nombre |
| LLM02 Sensitive Information Disclosure | LLM02:2026, mismo nombre |
| LLM06 Excessive Agency | **LLM03:2026** |
| LLM10 Unbounded Consumption | **LLM06:2026** |
| LLM05 Improper Output Handling | **LLM10:2026** |
| LLM07 System Prompt Leakage | **LLM08:2026** Hidden Context Exposure |
