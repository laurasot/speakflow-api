# Propuesta: phase-1-test-base (speakflow-api)

Rama base: `feat/api-key-auth` (PR #1 hacia `develop`). Fuentes: `exploration.md`, `../PLAN-MEJORAS.md` Fase 1, `openspec/config.yaml`.

## Intención

Construir la red de seguridad que necesitan todas las fases siguientes. La Fase 1 no corrige
ningún bug: demuestra 7 hallazgos (#1, #2, #3, #4, #5, #6, #10) como tests `xfail(strict=True)`
(fallo esperado que debe seguir fallando; si pasa, la suite se rompe) y logra que la suite sea
hermética (no depende de la máquina), independiente del orden, medida y controlada por CI
(pytest, ruff y mypy, todos bloqueantes).

## Alcance

| Dentro | Fuera |
|---|---|
| Herramientas: `pytest-cov`, `pytest-randomly`, markers `integration`/`e2e`, `--strict-markers`, `xfail_strict` | Corregir cualquier bug de producción (Fases 2-5) |
| Fixtures de aislamiento del entorno: ningún test lee el `.env` de la máquina; se limpian las cachés de singletons | Tope real de sesiones o su setting (Fase 2); el test de #2 fija a mano 50 sesiones por usuario |
| Limpiar los 51 hallazgos de ruff (33 automáticos, ~18 manuales) y mypy (stubs de numpy, python 3.11), sin cambiar el comportamiento | e2e con Docker, Dockerfile (Fase 6) |
| `tests/helpers`: `FakeSpeechProvider`, helper para leer mensajes del WebSocket (drain), normalizador de golden | `docs/PROTOCOL.md` |
| Tests xfail #1, #2, #3, #4, #5, #6, #10 | Tests del desktop (otro repo/fase) |
| Stub de Deepgram en loopback; goldens (archivos de referencia con la salida aceptada) de los mensajes WebSocket y de la URL/headers de Deepgram | Librerías de snapshots de terceros (syrupy) |
| Un flujo e2e en el mismo proceso, test de health, workflow de CI, línea base de cobertura registrada | Subir la cobertura al 80% (fases posteriores) |

## Enfoque

- **Provider Fake mediante el registry de la factory.** `monkeypatch.setitem(factory._REGISTRY, "fake", FakeSpeechProvider)` más `settings.speech_provider = "fake"`. Guarda las instancias creadas y expone `drop()` y `emit()`. Los tests existentes que parchan `create_provider` no se tocan.
- **Normalizador de golden hecho a mano** (~20 líneas): los UUID pasan a `<uuid-N>` según el orden de aparición y los timestamps a `<ts>`; archivos JSON en `tests/golden`, y `UPDATE_GOLDEN=1` para regenerarlos.
- **Stub en loopback (servidor falso en la propia máquina) para `DeepgramProvider`**: `websockets.serve` en `127.0.0.1:0`; se parchan `_DEEPGRAM_WS_URL` y `_RETRY_DELAYS=[0]`. Registra la query, el header `Authorization`, los frames binarios y `CloseStream`; reproduce frames `Results` y un cierre abrupto según un guion. Se usa para #3 (principal), #6 y #10 (stub del LLM).
- **Herramientas y control (gate).** Dependencias tanto en `[project.optional-dependencies]` como en `[tool.uv]`. CI bloquea por pytest (`-m "not e2e"`, orden aleatorio), `ruff check` y `mypy app`. Piso de cobertura = línea base medida menos un margen.
- **Limpieza de lint/tipos** en commits mecánicos propios: `ruff check --fix`, luego las correcciones manuales, luego la corrección de numpy en mypy (`[[tool.mypy.overrides]] numpy.*` con `follow_imports = "skip"`, alternativa `python_version = "3.12"` para mypy).
- **Entrega**: 3 PRs encadenados, commits por unidad de trabajo, con los tests en el mismo commit que el comportamiento que verifican; la unidad 1 es el primer commit (frena la fuga del `.env`).

## Capacidades (dominios de spec)

| Dominio | Qué cubre |
|---|---|
| `test-infrastructure` | aislamiento del entorno, limpieza de cachés, markers, xfail estricto, orden aleatorio, provider fake, helper drain, stub de Deepgram |
| `xfail-bug-catalog` | un escenario por cada hallazgo #1, #2, #3, #4, #5, #6, #10 con aserciones que describen el comportamiento posterior a la corrección |
| `contract-goldens` | normalizador, goldens de mensajes WebSocket, golden de URL/headers de Deepgram, flujo e2e en el mismo proceso, test de health |
| `ci-quality-gate` | ruff y mypy limpios, workflow de GitHub Actions, línea base y piso de cobertura |

## Áreas afectadas

`pyproject.toml`; `tests/conftest.py`; `tests/helpers/` (nuevo); `tests/golden/` (nuevo); `tests/unit/` (xfails nuevos, fixture duplicado en `test_suggestion_trigger.py`, limpieza del registry en `test_providers.py`); `tests/integration/` (nuevo); `.github/workflows/ci.yml` (nuevo); `app/**` y `tests/**` (solo ediciones mecánicas de ruff/mypy); `../PLAN-MEJORAS.md` (cobertura base).

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| xfails que fallan por la razón equivocada (débiles: #3 ausencia de error, #2 tope inventado, #6 suposición sobre `speech_final`) | Ejecutar `pytest --runxfail` en cada test, confirmar que el fallo es el comportamiento que se afirma; documentar cada razón |
| Un `.env` local activa llamadas reales al LLM o a la red | Unidad 1 primero; el fixture neutraliza todas las claves de settings y limpia los singletons con `lru_cache` |
| `pytest-randomly` deja al descubierto acoplamientos (`_REGISTRY`, `_triggers`, `metrics_collector`) | Pequeñas correcciones en la unidad 1; cambiar la semilla y repetir las ejecuciones antes de hacer merge |
| TestClient (hilo portal) frente a un stub async | Señalización entre hilos con `threading.Event`; alojar el stub en un hilo para los tests a nivel WebSocket; decidir antes de la unidad 6 |
| `OPENAI_BASE_URL` con langchain-openai sin verificar (#10) | Spike (prueba exploratoria corta) primero; alternativa: `RunnableLambda` colgado en `service._chain` |
| Override de mypy sin verificar | Probar el override, alternativa `python_version = "3.12"`; verificar con `mypy app` |
| La limpieza de lint esconde un cambio de comportamiento | Commits solo mecánicos, suite completa en verde antes y después de cada uno |
| Un CI bloqueante desde el primer día frena la cadena de PRs | La limpieza llega en el PR A antes de que el workflow llegue en el PR C |

## Plan de reversión

Cada PR se revierte de forma independiente según el orden de la cadena (C, luego B, luego A). La
Fase 1 no toca el comportamiento de producción: los commits de lint/mypy están aislados, así que
un `git revert` de esos commits restaura el código anterior. Si el gate de CI se comporta mal,
poner temporalmente `continue-on-error: true` en los pasos de ruff/mypy (cambio de una línea);
si `pytest-randomly` es inestable, fijar `-p no:randomly` en `addopts`.

## Criterios de éxito

- [ ] Suite en verde con orden aleatorio en 3 semillas distintas, en una máquina con y sin `.env`.
- [ ] La lista de xfail es exactamente la de los 7 hallazgos; cada uno verificado con `pytest --runxfail` fallando por la razón que se afirma.
- [ ] Cobertura base registrada en PLAN-MEJORAS.md; `--cov-fail-under` configurado.
- [ ] `ruff check app tests` y `mypy app` reportan 0 errores.
- [ ] Workflow de CI en verde en la cadena de PRs.

## Pronóstico de carga de revisión

Estrategia: PRs encadenados (la guarda `ask-on-risk` queda satisfecha por la decisión de la usuaria), todos desde `feat/api-key-auth`.

| PR | Unidades | Líneas cambiadas est. | Riesgo frente a 400 líneas |
|---|---|---|---|
| A | 1-3 (herramientas, limpieza de ruff+mypy, helpers) | ~290-460 (unidad 2 revisada a 80-250 porque ~18 hallazgos son manuales) | Medio-Alto |
| B | 4-5 (xfails unitarios y de WebSocket) | ~270 | Bajo |
| C | 6-7 (stub de Deepgram, goldens, e2e, CI, health, línea base) | ~350-380 | Medio |

Total ~910-1110. Si el PR A supera 400 después de medir la unidad 2, dividirlo: **A1** =
unidades 1+3 (herramientas, aislamiento del entorno, helpers, ~210) y **A2** = unidad 2
(limpieza de lint/mypy, diff mecánico). La cadena pasa entonces a ser A1, A2, B, C.

Pregunta abierta: ninguna más allá de las decisiones ya fijadas; los spikes de OPENAI_BASE_URL y del override de mypy se verifican durante la fase apply (implementación).
