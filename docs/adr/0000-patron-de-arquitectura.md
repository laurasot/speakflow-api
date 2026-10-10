# ADR-0 — Patrón de arquitectura: monolito modular hexagonal con pipeline de streaming por sesión

Fecha: 2026-10-07 · Estado: **Propuesto** (pendiente de aceptación) · Reemplaza: ninguna

## 1. Contexto

### Situación actual (verificada contra el código)

`speakflow-api` recibe audio PCM de dos fuentes por WebSocket (`/v1/stt/stream`), lo envía a un
proveedor de transcripción (STT) por fuente, y cuando una transcripción final dispara una regla de
silencio, pregunta a un LLM por una sugerencia. Hoy está organizado en capas informales
(`routers → services → providers`) sin una decisión de patrón documentada.

Esa organización ya muestra síntomas concretos:

| Síntoma | Dónde |
|---|---|
| `SuggestionService` construye su cadena LangChain en el constructor, llamando a un factory global que lee `settings`. No se puede instanciar sin proveedor real. | `services/suggestion_service.py` |
| `TranscriptProcessor` crea un `ChatOpenAI` con modelo y prompt fijos, y se activa solo por la presencia de `OPENAI_API_KEY`. Una decisión de infraestructura vive dentro de un servicio. | `services/transcript_processor.py` |
| El contrato `LLMProvider` expone `BaseChatModel` de LangChain: el detalle de un framework cruza la frontera. | `providers/llm/base.py` |
| El router implementa el protocolo de mensajes (inicio, audio, parada) además de enrutar. | `routers/v1/websocket_stt.py` |
| `SuggestionTrigger` depende del reloj real (`time.monotonic`, `loop.call_later`), así que probar una regla de 6 s exige esperar 6 s o parchear el módulo. | `services/suggestion_trigger.py` |

### Fuerzas que condicionan la decisión

Atributos de calidad, en orden de importancia para este sistema: (1) latencia baja y predecible en
el flujo de audio, con chunks de 500 ms; (2) aislamiento total entre sesiones; (3) proveedores
intercambiables, dado que ya hay 4 de STT y 3 de LLM y se comparan entre sí; (4) costo de LLM
controlado (solo se invoca cuando la regla lo justifica); (5) testabilidad; (6) simplicidad
operativa para un equipo pequeño. Restricción adicional: la conexión es un WebSocket de larga
duración con estado por sesión.

## 2. Alternativas consideradas

| Alternativa | Qué aporta | Por qué no |
|---|---|---|
| **Capas informales (hoy)** | Cero costo de cambio. | Es lo que produce los síntomas de la tabla anterior: nada impide que un servicio importe un SDK o lea `settings`. Una capa no protege el núcleo de la infraestructura. |
| **Clean Architecture (completa)** | Reglas de dependencia estrictas, casos de uso explícitos. | Exige DTOs y modelos en cada frontera. Para un servicio de un único flujo, la ceremonia supera el beneficio sobre hexagonal. |
| **Vertical Slice** | Cohesión por funcionalidad. | Hay una sola funcionalidad (transcribir y sugerir); no hay slices que aislar. Los componentes costosos (STT, LLM, métricas) son transversales. |
| **Microservicios** (por ejemplo, gateway de audio separado del servicio de sugerencias) | Escala independiente. | Agrega un salto de red a un flujo cuya latencia es el atributo principal, y un costo de operación que el equipo no justifica con la carga actual (no medida; ver §5). |
| **Dirigido por eventos con broker** (SQS/Kafka entre STT y LLM) | Absorbe picos, desacopla. | La interacción es síncrona desde la perspectiva del usuario: una sugerencia que llega tarde no sirve. El semántico "al menos una vez" de un broker no aporta valor al audio en vivo, que tolera pérdida. |
| **Orquestador de grafo (LangGraph)** | Útil en turnos request/response con ramificación. | El flujo aquí es continuo, con temporizadores, no turnos discretos. La decisión de cuándo sugerir es una regla determinista, no un grafo de nodos LLM. |

## 3. Decisión

Se adopta **arquitectura hexagonal (puertos y adaptadores, Cockburn 2005) dentro de un monolito
modular**, y para el comportamiento en ejecución un **pipeline de streaming por sesión dentro del
mismo proceso** (estilo *pipes and filters*, con colas `asyncio` acotadas).

Estructura objetivo:

```text
domain/        reglas puras: SuggestionPolicy, turnos de conversación, eventos. Sin I/O, sin reloj propio.
application/   SessionPipeline: STT → post-proceso → política → LLM. Orquesta puertos.
adapters/      stt/*, llm/*, entrada WebSocket, almacenamiento opcional.
composition/   único lugar que decide qué adaptador se inyecta (build_deps).
```

Puertos previstos: `SpeechToTextPort` (ya existe como `SpeechProvider`), `SuggestionLLMPort`
(sin tipos de LangChain en el contrato), `Clock`, `TranscriptStore`, `MetricsPort`,
`TokenVerifier`.

Dos reglas de diseño que esta decisión implica: las colas de audio son **acotadas con descarte del
más antiguo** (la misma política que ya aplica el cliente de escritorio), y los temporizadores de
silencio usan un **`Clock` inyectable**.

## 4. Justificación

**Por qué hexagonal responde a las fuerzas, y no otro patrón.** El criterio que pesa más es el
atributo (3) junto con (5): el sistema ya cambia de proveedor como práctica normal, y hoy esa
variabilidad está resuelta en parte (registry, `Protocol`) pero se filtra por los costados
(LangChain en el contrato, `settings` leído desde servicios). Hexagonal hace de esa frontera una
regla verificable en lugar de una convención. Es, además, el patrón cuyo costo marginal es más
bajo aquí, porque el proyecto ya está alrededor de un 40 % del camino: los proveedores STT ya son
puertos, falta el resto.

**Por qué se verifica en CI y no solo se documenta.** Una regla de dependencias sostenida por
disciplina de revisión se erosiona. El proyecto hermano `flowyai-platform-backend` la convirtió en
un test con AST (`tests/test_layer_rules.py`) que falla el mismo día que alguien importa en
dirección prohibida; se replica el mecanismo.

**Por qué el pipeline va en proceso y no entre servicios.** La latencia de extremo a extremo es el
atributo principal. Una cola in-process acotada da backpressure sin salto de red; la sesión sigue
siendo la unidad de aislamiento, ya garantizada hoy por colas por fuente.

## 5. Consecuencias aceptadas

**Costos.** Hay una capa de indirección: seguir una ejecución exige pasar por puerto y adaptador.
El beneficio principal es la verificabilidad; si la migración no se acompaña de tests del núcleo
con dobles de los puertos, el retorno se reduce a orden estructural. La migración debe ser
incremental, nunca un rediseño en un solo paso.

**Lo que se sacrifica.** Escala independiente por componente: todo el pipeline de una sesión vive
en un proceso. Mientras una sesión no deba sobrevivir a la caída de su instancia, es aceptable;
si el audio debiera reanudarse en otra instancia, este ADR deja de ser suficiente.

**Disparadores de revisión** (marcan cuándo reabrir esta decisión, no son decisiones tomadas):

- Si la medición de carga (pendiente, ver abajo) muestra que el ancho de banda de entrada de audio
  satura una instancia antes que la CPU, evaluar separar un gateway de ingesta.
- Si se agrega procesamiento posterior a la sesión (resúmenes, persistencia pesada), evaluar
  dirigirlo por eventos **solo para esa parte**, con la idempotencia descrita en
  `technical-guidelines/concurrency-and-background-jobs.md`.
- Si se exige reanudar sesiones entre instancias, evaluar estado externo.

## 6. Pendientes de definición

| Pendiente | Disparador de revisión |
|---|---|
| Sesiones concurrentes máximas por instancia | Prueba de carga con proveedores simulados (aún no existe) |
| Si los transcripts se persisten, dónde y por cuánto tiempo | Decisión de producto y de privacidad |
| Mecanismo de autenticación (hoy se confía en el header `X-User-Id`) | Antes de exponer el servicio fuera de desarrollo |

## 7. Plan de adopción incremental

| Fase | Alcance | Por qué en este orden |
|---|---|---|
| 0 | Test que reproduce la carrera de reconexión por `session_id`; corregirla. Cola de audio acotada. | Riesgos de corrección y memoria, independientes del patrón. |
| 1 | `build_deps()` como punto de composición; quitar el `ChatOpenAI` oculto de `TranscriptProcessor`. | Hace instanciables los servicios sin infraestructura real. |
| 2 | Declarar `SuggestionLLMPort` y `Clock`; extraer `SuggestionPolicy` pura. | Permite probar la regla de silencio sin esperar. |
| 3 | Test de reglas de capas en CI. | Fija la frontera antes de que se erosione. |
| 4 | Router delgado: el protocolo pasa a `application/`. | Cierra la última mezcla de responsabilidades. |
