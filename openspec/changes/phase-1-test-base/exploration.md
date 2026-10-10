# Exploración: phase-1-test-base (speakflow-api)

Fecha: 2026-10-09. Fuente: exploración de solo lectura hecha por el agente sdd-explore, más la
línea base revisada por el orquestador (87 tests pasan; `ruff check app tests` reporta 51
hallazgos, 33 corregibles automáticamente; `mypy app` falla por los stubs (archivos de tipos) de
numpy con `python_version = "3.11"`).
Las rutas son relativas a `speakflow-api/`. Los hallazgos #1..#10 vienen de `../PLAN-MEJORAS.md`.

## 1. Inventario y brechas

| Capa | Lo que existe | Brecha |
|---|---|---|
| Unitaria | `tests/unit/`: session_manager, audio_backpressure, suggestion_trigger, providers, api_key_verifier, embedding_service | El endpoint de health no tiene test |
| Integración | `tests/integration/`: websocket_auth, websocket_reconnect, websocket_concurrent. `TestClient` + provider MagicMock (objeto simulado) parcheado en `app.services.session_manager.create_provider` | El cliente real de Deepgram nunca se ejecuta; no hay stub (servidor falso) en loopback (la propia máquina); no hay test con dos usuarios |
| Contrato/golden (archivo de referencia con la salida aceptada) | ninguna | No se capturan los mensajes WebSocket ni la URL/headers de Deepgram |
| e2e / artefacto real | ninguna: no hay Dockerfile, ni `.github`, ni `docs/PROTOCOL.md` | El e2e con Docker corresponde a la Fase 6 |
| xfail strict (fallo esperado que debe fallar de verdad) | ninguna | `xfail_strict` no está activado (`pyproject.toml:56-58`) |
| Aislamiento del entorno | `conftest.py:16-22` solo define `auth_api_key_hashes` | `.env` se carga al importar (`config.py:8,71`); `get_speech_service` (`dependencies.py:23`) es un singleton (instancia única compartida) con `lru_cache` que construye `SuggestionService` y `TranscriptProcessor` con las claves que tenga `.env`, así que un `.env` local puede activar llamadas reales al LLM en los tests de WebSocket |
| Independencia del orden | no hay pytest-randomly | `speech_service._triggers` (`speech_service.py:23`) y el `metrics_collector` global; `test_providers.py:13` registra `__test_provider__` en `_REGISTRY` y nunca lo quita; `test_suggestion_trigger.py:12-27` define `mock_embedding_service` dos veces |

## 2. Puntos de apoyo por hallazgo (no hace falta código de producción; las aserciones describen el comportamiento posterior a la corrección)

- **#1 Takeover, toma de una sesión ajena (confirmado).** `session_manager.py:62` compara solo
  `existing.owner == owner`; `user_id` nunca se compara. `route_audio` (`:157-200`) no verifica
  el dueño y el router (`websocket_stt.py:133-134`) usa el `pending_metadata.session_id` que
  controla el cliente.
  Punto de apoyo: test de integración con dos claves (monkeypatch de `settings.auth_api_key_hashes`,
  limpiar `get_token_verifier`), dos `TestClient.websocket_connect`, un provider mock por cada
  llamada a `create_provider`. B inicia el `session_id` de A; verificar que el `disconnect` del
  provider de A no se llamó y que los bytes de B nunca llegan al `send_audio` de A. Esperar al
  consumidor con un `threading.Event` (como en `test_websocket_reconnect.py:32`).
- **#2 Tamaño del frame y tope de sesiones (confirmado).** Nada compara `len(pcm_bytes)` con
  `size` (`websocket_stt.py:123-137`). Test: metadata con `size=10` y un frame de 1000 bytes,
  verificar que el provider no lo recibió. El tope de sesiones todavía no existe: el test
  necesita un límite escrito a mano (se sugiere 50); el límite real es una decisión de la Fase 2.
- **#3 El provider se cae a mitad de sesión (confirmado).** El protocolo (`stt/base.py:13-29`)
  no tiene callback de error ni de desconexión; `DeepgramProvider._receive_loop` termina en
  silencio o solo registra un log (`deepgram/provider.py:144-148`). Puntos de apoyo: (a) un
  provider Fake con `drop()`; (b) el `DeepgramProvider` real contra un stub que cierra el socket
  (test principal preferido). Después de la caída se envía `stop_session` y se lee hasta
  `session_ended` para evitar bloqueos; verificar que llegó al menos un `error`. No fijar el
  código de error (Fase 3).
- **#4 TranscriptProcessor bloquea el loop (confirmado).** `_receive_loop` hace `await` de
  `on_transcript` en línea (`deepgram/provider.py:126`), que a su vez hace `await` de
  `processor.process` antes de `send_to_client` (`speech_service.py:40-54`). Punto de apoyo:
  test unitario con `SpeechService(TranscriptProcessor(chain=BlockingChain))`, donde
  `BlockingChain.ainvoke` espera un `asyncio.Event`; verificar que `send_to_client` se ejecutó
  en ~0.1 s mientras la chain está bloqueada. No se necesita `OPENAI_API_KEY`.
- **#5 `_is_question` (confirmado).** `suggestion_trigger.py:259-260` usa `startswith`: "dos
  horas", "domingo", "island", "candidate" devuelven True. Parametrizar el fixture (preparación
  reutilizable de un test) `trigger` existente (`test_suggestion_trigger.py:69`).
- **#6 Varios `is_final` por frase (confirmado en el código, no con audio real).** El provider
  solo mapea `is_final` (`deepgram/provider.py:131`); `speech_final` nunca se lee. Necesita el
  provider real contra el stub enviando dos frames `Results` (`is_final=true,
  speech_final=false`, luego `true,true`); verificar que el contexto pasado a un
  `SuggestionService.generate` falso contiene un solo turno. Usar `monkeypatch.setattr` sobre
  `suggestion_silence_threshold` (evita el `ge=1.0`). Depende de la semántica de Deepgram, que
  no está verificada.
- **#10 Timeout del LLM (confirmado).** `provider_response_timeout` (`config.py:45`) no se usa
  en ninguna parte de `app`; ni `ChatOpenAI(...)` (`openai/provider.py:28`) ni
  `self._chain.ainvoke` (`suggestion_service.py:83`) definen un timeout. Punto de apoyo
  preferido: `llm_provider="openai"`, clave falsa, stub HTTP en loopback que nunca responde,
  timeout ~0.5, verificar que `generate` devuelve `None` en ~2 s. `OPENAI_BASE_URL` con
  langchain-openai no está verificado; la alternativa es un `RunnableLambda` que se queda
  colgado, asignado a `service._chain` (toca un atributo privado).

## 3. Opciones de diseño y recomendación

- **(a) Provider Fake.** Se registra mediante la factory: `monkeypatch.setitem(factory._REGISTRY,
  "fake", FakeSpeechProvider)` más `settings.speech_provider = "fake"`. El Fake guarda las
  instancias creadas y expone `drop()` y `emit(transcript)`. Los tests nuevos dejan de parchar
  `session_manager.create_provider`; los existentes se quedan como están.
- **(b) Golden.** Normalizador hecho a mano (~20 líneas) en `tests/helpers`: los UUID pasan a
  `<uuid-N>` según el orden de aparición, y los timestamps a `<ts>`. Archivos JSON en
  `tests/golden`, con el interruptor `UPDATE_GOLDEN=1`. Reconsiderar syrupy solo si los goldens
  se multiplican.
- **(c) Stub en loopback.** `websockets.serve` en `127.0.0.1:0` dentro de un fixture async;
  `monkeypatch.setattr("app.providers.stt.deepgram.provider._DEEPGRAM_WS_URL", ...)` (constante
  que se lee dentro de `_establish_connection`, `provider.py:81-82`); poner
  `_RETRY_DELAYS=[0]`, una clave de prueba y el timeout de conexión. El stub registra path y
  query (model, language, encoding, sample_rate, channels, interim_results, smart_format,
  utterance_end_ms), `Authorization: Token ...`, los frames binarios y el `CloseStream` final;
  y reproduce frames `Results` y un cierre abrupto según un guion.
- **(d) Herramientas.** Agregar `pytest-cov` y `pytest-randomly` tanto en
  `[project.optional-dependencies]` como en `[tool.uv]`. En `[tool.pytest.ini_options]`:
  `markers = ["integration", "e2e"]`, `addopts = "--strict-markers"`, `xfail_strict = true`.
  CI rápido: `-m "not e2e"`. Cobertura: medir la línea base, poner `--cov-fail-under` en la
  línea base menos un margen, y apuntar a 80% más adelante.
  Ruff: `ruff check --fix` (33 hallazgos) como un commit mecánico aparte; los ~18 manuales en un
  commit posterior; mientras no esté limpio, CI ejecuta ruff y mypy con
  `continue-on-error: true` y bloquea solo por pytest. Stubs de numpy en mypy: probar
  `[[tool.mypy.overrides]] module = "numpy.*"` con `follow_imports = "skip"`; alternativa:
  `python_version = "3.12"` solo para mypy (ambas sin verificar).

## 4. Unidades de trabajo (líneas cambiadas estimadas)

| # | Unidad | Líneas est. |
|---|---|---|
| 1 | Herramientas: pyproject (dependencias, markers, strict) y fixtures de conftest para entorno/caché (neutralizar todas las claves de settings; limpiar `get_speech_service`, `get_session_manager`, el verifier); corregir el fixture duplicado | 80 |
| 2 | Commit mecánico de ruff `--fix` más el override de mypy | 60-150 |
| 3 | tests/helpers: FakeSpeechProvider, helper para leer mensajes del WebSocket (drain), normalizador de golden más sus tests | 130 |
| 4 | xfails unitarios #5, #4, #10 | 110 |
| 5 | xfails de WebSocket #1, #2, #3(a), preparación con dos usuarios | 160 |
| 6 | Stub de Deepgram en loopback, golden de URL/headers, integración, xfails #3(b), #6 | 200 |
| 7 | Goldens de mensajes WebSocket, un flujo e2e en el mismo proceso, workflow de CI, test de health, cobertura base en PLAN | 150 |

Total de unas 890 líneas (unas 1000 con el diff de ruff): supera el presupuesto de 400 líneas.
Cadena propuesta: PR A = unidades 1-3 (~270-360), PR B = unidades 4-5 (~270), PR C = unidades
6-7 (~350).

## 5. Riesgos y preguntas abiertas

- Fuga de LLM o red reales hasta que llegue la unidad 1: la unidad 1 debe ser el primer commit.
- xfails que fallan por la razón equivocada: ejecutar `pytest --runxfail` en cada uno. Los
  débiles: #3 (ausencia de un error), #2 sesiones (límite inventado), #6 (suposición sobre
  `speech_final`).
- `OPENAI_BASE_URL` con langchain-openai no está verificado.
- TestClient ejecuta la app en un hilo (portal): los eventos entre hilos necesitan
  `threading.Event`; los fixtures async del stub solo funcionan en tests puramente async.
  Decidir cómo alojan el stub los tests a nivel WebSocket (un hilo o uvicorn en el mismo
  proceso) antes de la unidad 6.
- pytest-randomly puede dejar al descubierto acoplamientos existentes (contaminación del
  registry, singletons, `metrics_collector`); esperar pequeñas correcciones en la unidad 1.
- Preguntas abiertas para la usuaria: (1) tres PRs encadenados o `size:exception`; (2) ruff/mypy
  bloqueantes o no en CI; (3) el tope que asume el test de #2 y si es un setting; (4) e2e con
  Docker diferido a la Fase 6; (5) si `docs/PROTOCOL.md` entra en el alcance.
