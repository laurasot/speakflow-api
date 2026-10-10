# Diseño: phase-1-test-base (speakflow-api)

Fecha: 2026-10-09. Entradas: `proposal.md`, `exploration.md`, `technical-guidelines/testing-guidelines.md`. Las rutas son relativas a `speakflow-api/`.

## Resumen de decisiones

Arnés de pruebas por capas, solo de tests (sin cambios en producción): un fixture (pieza reutilizable de preparación de pruebas) autouse neutraliza `Settings` y limpia los singletons (instancias únicas compartidas), un proveedor falso registrado a través de la factory atiende los tests de WebSocket, y el `DeepgramProvider` real corre contra un stub (servidor falso simple) loopback con `websockets.serve` **alojado en un hilo daemon con su propio event loop** para los tests a nivel de TestClient, y dentro del mismo proceso para los tests puramente async. Los golden (archivos de referencia con la salida esperada ya aprobada) usan un normalizador de 20 líneas. ruff, mypy y pytest bloquean el CI.

## 1. Arquitectura de tests

```
tests/
  conftest.py            autouse hermetic_env; auth_headers; golden fixture
  helpers/{fake_provider,ws,golden,deepgram_stub}.py
  golden/*.json
  unit/ integration/     markers: integration (WS/loopback), e2e (excluded from fast run)
```

`hermetic_env` (autouse, reemplaza a `configured_api_keys`; "hermetic" significa aislado del entorno de la máquina, sin depender de nada externo), en orden:

| Paso | Qué | Por qué |
|---|---|---|
| 1 | for each name in `Settings.model_fields`: `monkeypatch.setattr(settings, name, default)` (`field.get_default(call_default_factory=True)`) | `.env` se lee al importar (`config.py:8,71`); dejar cada clave en su valor por defecto declarado hace inalcanzable un `.env` local. Las claves nuevas quedan cubiertas automáticamente |
| 2 | override: `auth_api_key_hashes={sha256(TEST_API_KEY): "user1"}`, `llm_provider="openai"`, `openai_api_key=""` | no puede existir una clave real de LLM; no hay red |
| 3 | `cache_clear()` antes y después en `get_token_verifier`, `get_session_manager`, `get_speech_service` | singletons de `lru_cache` (`dependencies.py:13-26`); `get_speech_service` construye el processor y `SuggestionService` a partir de la configuración |
| 4 | `monkeypatch.setattr(factory, "_REGISTRY", dict(factory._REGISTRY))` | copia por test, para que `__test_provider__` en `test_providers.py:13` y `fake` no se filtren a otros tests |

`metrics_collector` solo escribe logs (`metrics.py:67`, sin estado), así que no hay nada que limpiar. `SpeechService._triggers` desaparece cuando `get_speech_service` se limpia. El fixture duplicado `mock_embedding_service` (un mock, es decir un objeto de imitación) en `test_suggestion_trigger.py` se elimina en la unidad 1. Los tests existentes siguen parcheando `app.services.session_manager.create_provider`.

## 2. FakeSpeechProvider y helper de drenado

`tests/helpers/fake_provider.py`, cumple con `SpeechProvider`:

| Miembro | Comportamiento |
|---|---|
| atributo de clase `instances: list` | lo reinicia el fixture `fake_provider` (lista nueva por test); cada `__init__` agrega `self` |
| `connect(session_id, source, audio_config, on_transcript)` | guarda los argumentos, `connected=True` |
| `send_audio(pcm)` | agrega a `audio: list[bytes]` y activa `audio_received: threading.Event` |
| `disconnect()` | `disconnected=True`, activa `disconnected_event: threading.Event` |
| `emit(transcript)` async | `await self.on_transcript(transcript)` (DEBE correr en el loop de la app) |
| `drop()` | simula la pérdida del proveedor: marca `dropped=True`, no cancela nada (no existe un hook en el protocolo; #3 verifica que la app reaccione) |

Los eventos son `threading.Event` porque TestClient corre la app en un hilo portal (patrón de `test_websocket_reconnect.py:27`). `emit` desde el hilo del test usa `client.portal.call(...)`; el fixture `fake_provider` hace `monkeypatch.setitem(factory._REGISTRY, "fake", FakeSpeechProvider)` y `monkeypatch.setattr(settings, "speech_provider", "fake")`. (`speech_provider` es un `Literal`; `setattr` sobre la instancia no valida, así que `"fake"` se acepta.)

`tests/helpers/ws.py::drain(ws, until="session_ended", limit=50)`: itera `ws.receive_json()` juntando mensajes hasta que `type == until` o se llega a `limit` mensajes (lanza `AssertionError` con los tipos recolectados, nunca se queda colgado). También `start_message(session_id, user_id="user1")`, extraído del test de reconexión.

## 3. El stub loopback y el problema TestClient contra asyncio

**Decisión: el stub corre en su propio hilo daemon con un event loop privado (`threading.Thread` + `asyncio.new_event_loop().run_until_complete(serve...)`), y expone `url`, listas de registro seguras entre hilos y `threading.Event`s.** Los tests puramente async (`DeepgramProvider` directo, #6 a nivel de proveedor, golden de URL/headers) usan la misma clase con `async with`, dentro del mismo proceso, en el loop del test.

| Opción | Veredicto |
|---|---|
| Hilo del stub, loop propio (elegida) | Funciona desde tests síncronos con TestClient; es independiente del loop del portal; el registro usa `list.append` y `threading.Event`, seguros bajo el GIL |
| `websockets.serve` en el loop del test | Imposible con `TestClient` síncrono: la función del test no corre dentro de un loop, y el `DeepgramProvider` de la app corre en el loop del portal |
| uvicorn real para la app | Más pesado, pierde las comodidades de `TestClient`; descartada |

Tests síncronos (TestClient): #3 con el fake, #1, #2, flujo e2e, golden de mensajes WS. El #3 a nivel WebSocket con Deepgram real usa el stub alojado en hilo. **Solo async**: #3(b) a nivel de proveedor, #6, golden de URL/headers de Deepgram, #4 (`SpeechService` directo), #10. La clase del stub tiene un solo núcleo (`DeepgramStub`) con dos puntos de entrada: `start_in_thread()` / `async __aenter__`. API del stub: `script(*frames)` envía JSON `Results`, `close_abruptly()`, `.requests` (ruta+query, `Authorization`), `.binary`, `.close_stream_seen`. El fixture `deepgram_stub` además fija `_DEEPGRAM_WS_URL` (`monkeypatch.setattr` sobre el módulo del proveedor), `_RETRY_DELAYS=[0]`, `deepgram_api_key="test-key"`, `provider_connect_timeout=2`. El puerto sale de `127.0.0.1:0` (`server.sockets[0].getsockname()`).

## 4. Normalizador de golden

`tests/helpers/golden.py::normalize(obj)`: recorre dicts/listas; los strings que coinciden por completo con una regex de UUID se convierten en `<uuid-N>` (N según la primera aparición, mismo valor, mismo N); el valor entero de la clave `timestamp` (epoch en ms) se convierte en `<ts>`. `assert_golden(name, obj)`: carga `tests/golden/<name>.json` (claves ordenadas, indent 2); si `UPDATE_GOLDEN=1` escribe y pasa, si no hace `assert normalize(obj) == expected` con un mensaje de diferencias; un archivo faltante sin la bandera falla (nunca lo crea en silencio).

**Prueba de que puede fallar** (se hace una vez por golden al aplicar, y se documenta en el commit): (1) test unitario del normalizador (dos UUID iguales se mapean a un solo placeholder, dos distintos a dos); (2) por cada golden, mutar el literal de producción (por ejemplo `language=es` a `en`, quitar un campo) y ver que el golden falle, luego revertir; (3) un auto-test: `assert_golden` sobre un dict deliberadamente incorrecto lanza error. El golden de Deepgram cubre la ruta, los parámetros de query y el header `Authorization` con la clave reemplazada por `Token <key>`.

## 5. Configuración de herramientas

```toml
[project.optional-dependencies] dev  += "pytest-cov>=5.0.0", "pytest-randomly>=3.15.0"
[tool.uv] dev-dependencies           += same two
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = ["integration: WebSocket/loopback tests", "e2e: full in-process flow, excluded from fast run"]
addopts = "--strict-markers --cov=app --cov-report=term-missing"
xfail_strict = true
[tool.coverage.run]    branch = true
[tool.coverage.report] fail_under = <baseline-margin, set in PR C>; exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:"]
```

`fail_under` vive en la configuración de coverage, no en `addopts`, para que las corridas parciales locales (`pytest tests/unit/x`) no queden bloqueadas: el CI aplica el mínimo de cobertura solo a través de la configuración del reporte, y solo en la corrida completa. Aleatorización: pytest-randomly viene activado por defecto; la semilla se imprime en el encabezado; el CI usa la semilla aleatoria por defecto y la registra; se reproduce con `--randomly-seed=N`.

**Limpieza de ruff/mypy (unidad 2, solo cambios mecánicos):**
1. Registrar la línea base: `ruff check app tests --statistics`, `mypy app`.
2. `ruff check --fix app tests`, correr la suite, commit. Luego los ~18 manuales en un segundo commit, con la suite en verde después de cada uno.
3. mypy y numpy: **verificar primero** con `mypy app` sobre la configuración actual (confirmar que el fallo está en los stubs de tipos de numpy, no en el código de la app). Probar el override `[[tool.mypy.overrides]] module = "numpy.*"`, `follow_imports = "skip"`; volver a correr. Si los errores persisten (stubs analizados por la cadena de imports con sintaxis de 3.11), alternativa: `python_version = "3.12"` solo en `[tool.mypy]` (el runtime sigue en `>=3.11`), y volver a correr. Los errores restantes de la app se corrigen con ediciones mínimas de tipado, sin cambiar el comportamiento.

## 6. Flujo de CI (solo diseño, `.github/workflows/ci.yml`, PR C)

Disparador: `pull_request`, `push` a `develop`. Un solo runner `ubuntu-latest`, Python 3.11, `astral-sh/setup-uv`, caché sobre `uv.lock`.

| Job / paso | Comando | Bloquea |
|---|---|---|
| lint | `uv run ruff check app tests` | sí |
| types | `uv run mypy app` | sí |
| test | `uv run pytest -m "not e2e"` (orden aleatorio, mínimo de cobertura desde la configuración) | sí |
| e2e (job separado) | `uv run pytest -m e2e` | sí (corre en el mismo proceso, es barato) |

Lint y types corren en paralelo con test. Sin Docker, sin secretos; `OPENAI_API_KEY` y similares quedan deliberadamente sin definir para reflejar los fixtures herméticos. Alternativa si resulta inestable: `continue-on-error: true` en lint/types, `-p no:randomly` en addopts.

## 7. Diseño de xfail

Todos son `@pytest.mark.xfail(strict=True, reason="...")` (xfail: test marcado como "fallo esperado" porque reproduce un bug conocido que todavía no se corrigió). Revisar cada uno con `pytest <id> --runxfail` y leer el traceback.

| # | Punto de prueba (seam) | Aserción (comportamiento tras la corrección) | Texto de reason | `--runxfail` debe fallar con |
|---|---|---|---|---|
| 1 | Dos claves, dos TestClients, proveedor fake; B envía el `session_id` de A | el `disconnected_event` de A no se activa; el audio de B nunca llega al `audio` de la instancia de A | `#1 session takeover: owner compared, user_id ignored` | `AssertionError` porque el audio de B llegó a A (o A se desconectó) |
| 2a | metadata `size=10`, frame de 1000 bytes, fake | `audio == []` en el proveedor | `#2 frame size not validated against metadata` | la lista de audio contiene el frame de 1000 bytes |
| 2b | 51 `start_session` con ids distintos para un mismo usuario | la sesión 51 recibe `error` (tope fijo de 50) | `#2 no per-user session cap (test assumes 50; real value Phase 2)` | no se recibió ningún `error` |
| 3a | `drop()` del fake después de iniciar, luego `stop_session`, `drain` | al menos un mensaje `error` en la lista drenada | `#3 provider loss not reported to client` | no hay `error` en los tipos drenados |
| 3b | `DeepgramProvider` real + `close_abruptly()` del stub (stub en hilo, TestClient) | igual | igual | igual; el stub confirma que el cierre ocurrió (evento `close_sent`), así que la ausencia no es un fallo de preparación |
| 4 | `SpeechService(TranscriptProcessor(BlockingChain))`, espía en `send_to_client`, la cadena espera un `asyncio.Event` | `send_to_client` se llama dentro de 0.1 s (`asyncio.wait_for`) | `#4 processor blocks the receive loop before send_to_client` | `TimeoutError`; el test cancela la tarea bloqueada en `finally` |
| 5 | parametrizar `_is_question` con `dos horas`, `domingo`, `island`, `candidate` | devuelve `False` | `#5 startswith misclassifies words as questions` | `assert True is False` por cada caso |
| 6 | proveedor real + stub: `is_final=true,speech_final=false` y luego `true,true`; el `SuggestionService.generate` falso registra el contexto | el contexto contiene un solo turno | `#6 each is_final treated as a turn; speech_final ignored (assumes Deepgram semantics)` | el contexto tiene longitud 2 |
| 10 | `llm_provider=openai`, clave falsa, HTTP loopback que nunca responde (probar `OPENAI_BASE_URL`), timeout 0.5 | `generate` devuelve `None` en menos de 2 s | `#10 provider_response_timeout unused in LLM call` | timeout del `wait_for` externo. Alternativa: un `RunnableLambda` colgado en `service._chain` |

Cada xfail basado en stub (3b, 6, 10) también tiene un test de control sin xfail, con el stub respondiendo con normalidad, que demuestra que la preparación funciona.

## 8. Unidades de trabajo y PRs

| Unidad | Contenido | Líneas | PR |
|---|---|---|---|
| 1 | dependencias de pyproject/markers/strict, `hermetic_env`, fixture duplicado eliminado, arreglo del registro. **Primer commit** | ~80 | A |
| 2 | ruff `--fix`, arreglos manuales, override o alternativa de mypy | 80-250 | A (o A2) |
| 3 | helpers: proveedor fake, `ws.py`, `golden.py` + sus tests | ~130 | A (o A1) |
| 4 | xfails #5, #4, #10 | ~110 | B |
| 5 | xfails #1, #2, #3a, preparación de dos usuarios | ~160 | B |
| 6 | `deepgram_stub`, golden de URL/headers, xfails #3b, #6 | ~200 | C |
| 7 | golden de WS, e2e, test de health, CI, línea base de cobertura en PLAN | ~150 | C |

Orden: la unidad 1 antes que todo (frena la filtración de `.env` y deja a la vista el acoplamiento bajo orden aleatorio); la unidad 2 antes de que exista el CI; la unidad 3 antes de 4-7. Dividir A en A1 (1+3) y A2 (2) si la unidad 2 supera las 190 líneas.

```
develop <- feat/api-key-auth
   A (unidades 1-3) -> B (4-5) -> C (6-7)
   📍 A: inicio = punta de feat/api-key-auth; fin = suite hermética + helpers; dependencias: ninguna
      B: inicio = A; fin = 7 xfails menos los de stub; dependencias: A
      C: inicio = B; fin = stub, golden, e2e, CI; dependencias: B
```

| Unidad | Verificación |
|---|---|
| 1 | suite en verde con 3 semillas, con y sin un `.env` con datos; `grep` no muestra ninguna lectura de `.env` en los tests |
| 2 | `ruff check app tests` y `mypy app` con 0 errores; suite en verde antes y después; diff revisado como no funcional |
| 3 | tests unitarios de los helpers; demostración de que el golden falla |
| 4-5 | `pytest -rx` lista exactamente esos xfails; `--runxfail` por test, el motivo coincide |
| 6 | los tests de control pasan; los xfails fallan por el motivo afirmado; los golden fallan tras mutar producción |
| 7 | CI en verde sobre la cadena de PRs; línea base de cobertura registrada; `fail_under` = línea base menos un margen |

## 9. Decisiones y pendientes

| Decisión | Alternativas | Justificación |
|---|---|---|
| Neutralizar con un bucle sobre `Settings.model_fields` | listar las claves a mano; `_env_file=None` | `settings` se construye al importar; el bucle cubre las claves futuras |
| Stub alojado en hilo para los tests con TestClient | uvicorn; solo async | es la única opción que funciona con `TestClient` síncrono |
| Fake vía `_REGISTRY` | parchear `create_provider` | ejercita la factory real; los tests viejos quedan intactos |
| Golden hechos a mano | syrupy | ~20 líneas, sin dependencia; reconsiderar si los golden se multiplican |
| Mínimo de cobertura en `[tool.coverage.report]` | bandera en `addopts` | las corridas parciales siguen siendo usables |
| `xfail_strict` global | solo por test | guía §3: un XPASS debe hacer fallar la suite |

Pendientes (se verifican durante la aplicación): `OPENAI_BASE_URL` con langchain-openai (#10); override de mypy para numpy contra la alternativa; semántica de `speech_final` en Deepgram para #6; orden de cierre del hilo del stub al terminar (cerrar el servidor, detener el loop, `join` con timeout); `Settings.get_default` para la factory de `auth_api_key_hashes`.
