# Tareas: phase-1-test-base (speakflow-api)

Entradas: `proposal.md`, `design.md`, `specs/*/spec.md`. Rutas relativas a `speakflow-api/`. Estrategia de entrega: `ask-on-risk`.

## 1. Resumen y orden de entrega

Reglas para todas las tareas: la prueba va ANTES que el código o la corrección que la satisface (TDD estricto). Las pruebas xfail se escriben primero y se revisan con `pytest <id> --runxfail`. El código de prueba va en inglés, solo con docstrings y sin comentarios (excepción: `# noqa: <regla>` puntual). Un commit por unidad de trabajo, con sus pruebas dentro, en Conventional Commits y SIN línea Co-Authored-By.

| PR | Unidades | Rama base | Inicio | Fin | Depende de | Seguimiento | Fuera de alcance |
|---|---|---|---|---|---|---|---|
| A (o A1 + A2) | 1, 3 (A1); 2 (A2) | `feat/api-key-auth` | punta de `feat/api-key-auth` | suite hermética, ruff y mypy limpios, helpers | ninguna | medir el diff de ruff antes de decidir el corte | corregir bugs de producción |
| B | 4, 5 | A (o A2) | PR A | xfails #5, #4, #10, #1, #2, #3a | A | `pytest -rx` lista solo esos xfails | stub de Deepgram, CI |
| C | 6, 7 | B | PR B | stub, goldens, xfails #3b y #6, e2e, health, CI, cobertura | B | cobertura base en `../PLAN-MEJORAS.md` | Docker, `docs/PROTOCOL.md`, cobertura 80% |

Orden: 1 -> 3 -> 2 si se divide (A1 = 1+3, A2 = 2); si no se divide, 1 -> 2 -> 3. Luego 4, 5, 6, 7.

Notas de la revisión de specs: el CI tiene CUATRO trabajos (ruff, mypy, `pytest -m "not e2e"`, `pytest -m e2e`). El cuerpo de salud exacto es `{"status": "ok", "active_sessions": N}`.

## 2. Unidad 1: herramientas y aislamiento del entorno (PR A)

- [ ] 1.1 Escribir primero `tests/unit/test_hermetic_env.py`: con `OPENAI_API_KEY` falso en el entorno, `settings.openai_api_key == ""`; tras un test que cambia `auth_api_key_hashes`, el siguiente ve verificador nuevo; `_REGISTRY` no conserva `__test_provider__`. (TI-01, TI-02). Verificar: `uv run pytest tests/unit/test_hermetic_env.py` (debe fallar antes de 1.3).
- [ ] 1.2 Editar `pyproject.toml`: agregar `pytest-cov>=5.0.0` y `pytest-randomly>=3.15.0` a `[project.optional-dependencies] dev` y a `[tool.uv] dev-dependencies`; `asyncio_mode`, `testpaths`, `markers` (integration, e2e), `addopts = "--strict-markers --cov=app --cov-report=term-missing"`, `xfail_strict = true`, `[tool.coverage.run] branch = true`. NO poner `fail_under` aún. (TI-03). Verificar: `uv sync && uv run pytest --markers` y un marker inventado debe dar error.
- [ ] 1.3 Editar `tests/conftest.py`: fixture autouse `hermetic_env` (bucle sobre `Settings.model_fields` con `get_default(call_default_factory=True)`, override de hashes/LLM, `cache_clear()` antes y después de los tres singletons, copia de `factory._REGISTRY`); reemplazar `configured_api_keys`. (TI-01, TI-02). Verificar: `uv run pytest` en verde.
- [ ] 1.4 Eliminar el `mock_embedding_service` duplicado en `tests/unit/test_suggestion_trigger.py` y la fuga del registro en `tests/unit/test_providers.py:13`. (TI-02). Verificar: `grep -c "def mock_embedding_service" tests/unit/test_suggestion_trigger.py` da 1.
- [ ] 1.5 Verificar con 3 semillas y con/sin `.env`: `uv run pytest -p randomly --randomly-seed=1`, `=2`, `=3`; repetir con un `.env` de prueba con datos; `grep -rn "\.env" tests` sin lecturas. (TI-01, TI-02).
- [ ] 1.6 Commit: `feat(tests): add hermetic env fixture, strict markers and random order`.

## 3. Unidad 3: helpers de prueba (PR A, parte A1)

- [ ] 3.1 Escribir primero `tests/unit/test_helpers.py`: pruebas del normalizador (mismo UUID -> mismo `<uuid-N>`, dos distintos -> dos, texto mal formado intacto, `timestamp` -> `<ts>`), de `assert_golden` (archivo faltante falla sin `UPDATE_GOLDEN`; dict incorrecto lanza error), de `drain` (devuelve mensajes en orden; sin `session_ended` lanza `AssertionError` con los tipos) y del fake (`instances`, `audio`, `drop`, teardown del registro). (CG-01, TI-04, TI-05). Verificar: `uv run pytest tests/unit/test_helpers.py` (rojo antes de 3.2-3.4).
- [ ] 3.2 Crear `tests/helpers/__init__.py` y `tests/helpers/fake_provider.py` (`FakeSpeechProvider` con `instances`, `audio`, `audio_received`, `disconnected_event`, `emit`, `drop`). Agregar el fixture `fake_provider` en `tests/conftest.py` (registro `"fake"`, `speech_provider="fake"`). (TI-04). Verificar: `uv run pytest tests/unit/test_helpers.py -k fake`.
- [ ] 3.3 Crear `tests/helpers/ws.py` con `drain(ws, until="session_ended", limit=50)` y `start_message(...)` (extraído de `test_websocket_reconnect.py`). (TI-05). Verificar: `uv run pytest tests/unit/test_helpers.py -k drain`.
- [ ] 3.4 Crear `tests/helpers/golden.py` con `normalize` y `assert_golden` (`UPDATE_GOLDEN=1`, claves ordenadas, indent 2, diff legible) y el fixture `golden` en `tests/conftest.py`. (CG-01). Verificar: `uv run pytest tests/unit/test_helpers.py -k golden`.
- [ ] 3.5 Commit: `test: add fake provider, drain and golden helpers`.

## 4. Unidad 2: limpieza de ruff y mypy (PR A, parte A2)

- [ ] 4.0 Verificación previa (a) mypy y numpy: ejecutar `uv run mypy app` y confirmar que el fallo viene de los stubs de numpy; probar `[[tool.mypy.overrides]] module = "numpy.*"` con `follow_imports = "skip"`; si persisten errores, usar `python_version = "3.12"` solo en `[tool.mypy]` y anotar el motivo en `pyproject.toml`. (CI-02). Verificar: `uv run mypy app` con 0 errores.
- [ ] 2.1 Registrar línea base: `uv run ruff check app tests --statistics`, `uv run mypy app`, `uv run pytest` (87 pruebas). Medir el diff de `--fix` con `uv run ruff check app tests --fix --diff | wc -l` ANTES de decidir el corte A1/A2. (CI-01).
- [ ] 2.2 Ejecutar `uv run ruff check --fix app tests`; correr `uv run pytest` (mismo resultado que 2.1). Commit: `chore: apply ruff autofixes`. (CI-01).
- [ ] 2.3 Corregir a mano los ~18 hallazgos restantes sin cambiar comportamiento (si cambiara, `# noqa: <regla>` y el motivo en el commit); suite en verde tras cada corrección. Verificar: `uv run ruff check app tests` con código 0. Commit: `chore: fix remaining ruff findings`. (CI-01).
- [ ] 2.4 Aplicar el override (o la alternativa) de 2.0 y las ediciones mínimas de tipado. Verificar: `uv run mypy app` con 0 errores y `uv run pytest` en verde. Commit: `chore: make mypy pass with numpy stubs override`. (CI-02).

(El ID 4.0 se ejecuta como primer paso de esta unidad; se numera aquí por orden de documento.)

## 5. Unidad 4: xfails #5, #4, #10 (PR B)

- [ ] 5.0 Verificación previa (b) `OPENAI_BASE_URL` con langchain-openai: probar en un script en el directorio temporal que `ChatOpenAI` respete `OPENAI_BASE_URL` contra un servidor HTTP loopback que nunca responde. Si no funciona, usar `RunnableLambda` colgado en `service._chain` y anotarlo en el `reason`. (XF-07).
- [ ] 5.1 Crear en `tests/unit/test_suggestion_trigger.py` el xfail parametrizado #5 (`dos horas`, `domingo`, `island`, `candidate`) y los controles no xfail (`do you know`, `dónde está`). (XF-05). Verificar: `uv run pytest tests/unit/test_suggestion_trigger.py -k is_question` y `--runxfail` falla con `assert True is False`.
- [ ] 5.2 Crear `tests/unit/test_speech_service_blocking.py` con el xfail #4 (`BlockingChain`, espía en `send_to_client`, `wait_for` de 0.1 s, cancelar/liberar en `finally`). (XF-04). Verificar: `uv run pytest tests/unit/test_speech_service_blocking.py --runxfail` falla con `TimeoutError`.
- [ ] 5.3 Crear `tests/unit/test_suggestion_timeout.py` con el xfail #10 y su control con stub que responde (usa el resultado de 5.0). (XF-07). Verificar: `--runxfail` falla por el `wait_for` externo.
- [ ] 5.4 Verificar `uv run pytest -rx` (solo estos xfails) y commit: `test: add xfail tests for findings 4, 5 and 10`.

## 6. Unidad 5: xfails #1, #2, #3a (PR B)

- [ ] 6.1 Crear `tests/integration/__init__.py` y `tests/integration/conftest.py` con el fixture de dos usuarios (dos claves, dos `TestClient`, limpiar `get_token_verifier`). (XF-01).
- [ ] 6.2 Crear `tests/integration/test_session_takeover.py` con el xfail #1 (y caso del audio de B). (XF-01). Verificar: `uv run pytest tests/integration/test_session_takeover.py --runxfail` falla con `AssertionError` por audio de B en A.
- [ ] 6.3 Crear `tests/integration/test_frame_and_cap.py` con los xfails #2a (`size=10`, frame de 1000 bytes), #2b (51 sesiones) y el control de frame igual a `size`. (XF-02). Verificar: `--runxfail` y leer el traceback.
- [ ] 6.4 Crear `tests/integration/test_provider_drop.py` con el xfail #3a (`drop()`, `stop_session`, `drain` sin colgarse). (XF-03). Verificar: `--runxfail` falla por falta de `error` en los tipos drenados.
- [ ] 6.5 Verificar `uv run pytest -rx` y 3 semillas; commit: `test: add xfail tests for findings 1, 2 and 3a`.

## 7. Unidad 6: stub de Deepgram, golden de Deepgram, xfails #3b y #6 (PR C)

- [ ] 7.0 Verificación previa (c) orden de apagado del hilo del stub: en un test de humo comprobar que se cierra el servidor, se detiene el loop y se hace `join` con timeout, y que el puerto queda libre y las constantes parcheadas se restauran. (TI-06). Verificar: `uv run pytest tests/integration/test_deepgram_stub.py -k teardown`.
- [ ] 7.1 Escribir primero `tests/integration/test_deepgram_stub.py` (query y `Authorization: Token test-key`, cierre abrupto sin `CloseStream`, teardown). (TI-06).
- [ ] 7.2 Crear `tests/helpers/deepgram_stub.py` (`DeepgramStub`, `start_in_thread()` y `__aenter__`) y el fixture `deepgram_stub` en `tests/conftest.py`. (TI-06). Verificar: `uv run pytest tests/integration/test_deepgram_stub.py`.
- [ ] 7.3 Crear `tests/integration/test_deepgram_contract.py` y `tests/golden/deepgram_request.json` (ruta, query, `Authorization` con la clave reemplazada). Probar que falla mutando `language=es` y revertir. (CG-03). Verificar: `uv run pytest tests/integration/test_deepgram_contract.py`.
- [ ] 7.4 Agregar xfail #3b a `tests/integration/test_provider_drop.py` (stub en hilo, `close_sent`) y su control. (XF-03). Verificar: `--runxfail`.
- [ ] 7.5 Crear `tests/integration/test_turn_semantics.py` con el xfail #6 (`speech_final`, `SuggestionService.generate` falso, docstring con el supuesto de Deepgram) y el control de dos turnos con `speech_final=true`. (XF-06). Verificar: `--runxfail` falla con longitud 2.
- [ ] 7.6 Commit: `test: add deepgram stub, request golden and xfails 3b and 6`.

## 8. Unidad 7: goldens de WebSocket, e2e, health, CI y cobertura (PR C)

- [ ] 8.0 Verificación previa (d) `SuggestionService` falso: comprobar que el entorno aislado deja el LLM sin clave y que se puede inyectar un `SuggestionService` falso en el `SpeechService` de la prueba (sin llamadas al LLM) con `suggestion_silence_threshold` bajado por `monkeypatch.setattr`. (CG-02). Verificar: un test de humo recibe un mensaje `suggestion`.
- [ ] 8.1 Escribir primero `tests/integration/test_ws_goldens.py` y `tests/golden/ws_*.json` (`session_started`, transcripción, `suggestion`, `error`, `session_ended`); probar que fallan al renombrar un campo y revertir. (CG-02). Verificar: `uv run pytest tests/integration/test_ws_goldens.py`.
- [ ] 8.2 Crear `tests/integration/test_e2e_flow.py` con `@pytest.mark.e2e` (flujo completo y clave inválida rechazada). (CG-04). Verificar: `uv run pytest -m e2e`.
- [ ] 8.3 Crear `tests/unit/test_health.py`: `GET /v1/health` da 200 con `{"status": "ok", "active_sessions": 0}` y, con una sesión, `1`. (CG-05). Verificar: `uv run pytest tests/unit/test_health.py`.
- [ ] 8.4 Medir la cobertura base: `uv run pytest -m "not e2e"` (mismo comando del CI); anotarla en `../PLAN-MEJORAS.md`; fijar `fail_under` = base menos margen en `[tool.coverage.report]` de `pyproject.toml` (con `exclude_lines`). (CI-04). Verificar: la suite pasa y baja a fallar si se sube `fail_under` por encima de la base.
- [ ] 8.5 Crear `.github/workflows/ci.yml` (`pull_request` y push a `develop`; `ubuntu-latest`, Python 3.11, `setup-uv`, caché de `uv.lock`; cuatro trabajos: ruff, mypy, `pytest -m "not e2e"`, `pytest -m e2e`; sin `continue-on-error` ni secretos). (CI-03). Verificar: YAML válido y CI en verde en el PR.
- [ ] 8.6 Verificar 3 semillas, `ruff check app tests`, `mypy app`. Commit: `ci: add quality gate and coverage floor` (goldens y e2e en commit propio: `test: add websocket goldens, e2e flow and health test`).

## 9. Pronóstico de carga de revisión

| PR | Unidades | Líneas estimadas | Riesgo de superar 400 | Dividir |
|---|---|---|---|---|
| A | 1, 2, 3 | 290-460 | Medio-Alto | Sí, si el diff de `--fix` de 2.1 empuja a más de 400: A1 (1+3, ~210) y A2 (2, 80-250) |
| B | 4, 5 | ~270 | Bajo | No |
| C | 6, 7 | ~350-380 | Medio | Solo si 8.x supera 400 al medir |

- Chained PRs recommended: Yes (3 PRs encadenados A, B, C; A puede ser A1 + A2).
- 400-line budget risk: Medium (A es Medio-Alto, C Medio, B Bajo).
- Decision needed before apply: Yes. El diff real de `ruff --fix` y de los ~18 arreglos manuales aún no se mide. Antes de empezar la unidad 2 se corre el paso 2.1 (`ruff check app tests --fix --diff | wc -l`, más conteo de hallazgos manuales) y se decide A o A1/A2; la entrega por cadena ya fue aceptada, falta confirmar solo ese corte.

## 10. Trazabilidad requisito -> tarea

Prefijos: TI = test-infrastructure, XF = xfail-bug-catalog, CG = contract-goldens, CI = ci-quality-gate.

| Requisito | Tareas |
|---|---|
| TI-01 Aislamiento del entorno | 1.1, 1.3, 1.5 |
| TI-02 Independencia del orden | 1.1, 1.3, 1.4, 1.5 |
| TI-03 Markers y xfail estrictos | 1.2 |
| TI-04 FakeSpeechProvider | 3.1, 3.2 |
| TI-05 Helper de drenaje | 3.1, 3.3 |
| TI-06 Stub de Deepgram | 7.0, 7.1, 7.2 |
| XF-01 #1 | 6.1, 6.2 |
| XF-02 #2 | 6.3 |
| XF-03 #3 | 6.4, 7.4 |
| XF-04 #4 | 5.2 |
| XF-05 #5 | 5.1 |
| XF-06 #6 | 7.5 |
| XF-07 #10 | 5.0, 5.3 |
| CG-01 Normalizador | 3.1, 3.4 |
| CG-02 Goldens WebSocket | 8.0, 8.1 |
| CG-03 Golden Deepgram | 7.3 |
| CG-04 Flujo e2e | 8.2 |
| CG-05 Health | 8.3 |
| CI-01 Ruff limpio | 2.1, 2.2, 2.3 |
| CI-02 Mypy limpio | 4.0, 2.4 |
| CI-03 Workflow de CI | 8.5 |
| CI-04 Cobertura | 8.4 |
| CI-05 Entrega encadenada | 1 (resumen), 9, 8.6 |

Total de tareas: PR A = 16 (1.x: 6, 3.x: 5, unidad 2: 5), PR B = 10, PR C = 14.
