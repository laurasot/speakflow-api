# Especificación delta: test-infrastructure (infraestructura de pruebas)

> Palabras clave (RFC 2119): DEBE = obligatorio (MUST/SHALL); NO DEBE = prohibido (MUST NOT); DEBERÍA = recomendado (SHOULD); PUEDE = opcional (MAY).

## Propósito

La suite de pruebas DEBE ser hermética (aislada del exterior), independiente del orden y estricta con los markers (etiquetas de pytest) y los xfail (pruebas que se espera que fallen). Además DEBE ofrecer dobles de prueba compartidos (proveedor falso, ayudante de drenaje y stub de Deepgram, es decir, un servidor simulado) para que las pruebas futuras nunca usen la red ni el `.env` de quien desarrolla.

## Requisitos

### REQ-01 Aislamiento del entorno
Las pruebas NO DEBEN leer el `.env` de la máquina. Un fixture (preparación reutilizable de pytest) autouse en `tests/conftest.py` DEBE poner valores de prueba en cada clave de configuración que lee la app (claves de LLM, `speech_provider`, `auth_api_key_hashes`) y DEBE limpiar los singletons de `lru_cache` (`get_speech_service`, `get_session_manager`, `get_token_verifier`) antes y después de cada prueba.

- Dado un `.env` con un `OPENAI_API_KEY` real, Cuando corre cualquier prueba de WebSocket, Entonces `SuggestionService` y `TranscriptProcessor` se construyen con valores de prueba y no se hace ninguna llamada externa al LLM.
- Dada una prueba que modifica `settings.auth_api_key_hashes`, Cuando corre la siguiente prueba, Entonces el verificador y el servicio de voz se reconstruyen (no queda ningún singleton viejo).

### REQ-02 Independencia del orden
`pytest-randomly` DEBE estar instalado y activo; la suite DEBE pasar con al menos 3 semillas (seeds) distintas. El estado global (`factory._REGISTRY`, `speech_service._triggers`, `metrics_collector`) DEBE restaurarse después de cada prueba.

- Dado que `test_providers.py` registra `__test_provider__`, Cuando termina la prueba, Entonces `_REGISTRY` ya no lo contiene.
- Dadas las semillas 1, 2 y 3, Cuando corre la suite, Entonces todas pasan; un fallo con cualquier semilla es un defecto.
- Dado `test_suggestion_trigger.py`, Entonces `mock_embedding_service` está definido exactamente una vez.

### REQ-03 Markers y xfail estrictos
`[tool.pytest.ini_options]` DEBE definir `markers = ["integration", "e2e"]`, `--strict-markers` y `xfail_strict = true`. Tanto `pytest-cov` como `pytest-randomly` DEBEN declararse en `[project.optional-dependencies]` y en `[tool.uv]`.

- Dada una prueba que usa un marker no registrado, Cuando se recolecta, Entonces pytest da error.
- Dada una prueba `xfail` que pasa inesperadamente, Cuando se ejecuta, Entonces se reporta como FAILED (modo estricto).
- Dado `-m "not e2e"`, Entonces las pruebas marcadas e2e se excluyen.

### REQ-04 FakeSpeechProvider mediante el registro de la factory
`tests/helpers` DEBE ofrecer `FakeSpeechProvider` (proveedor de voz falso), registrado con `monkeypatch.setitem(factory._REGISTRY, "fake", FakeSpeechProvider)` y con `settings.speech_provider = "fake"`. DEBE guardar las instancias creadas y el audio recibido, y DEBE exponer `drop()` y `emit(transcript)`. Las pruebas nuevas NO DEBEN parchear `session_manager.create_provider`.

- Dadas dos sesiones, Cuando ambas arrancan, Entonces existen dos instancias distintas registradas.
- Dada una sesión activa, Cuando se llama a `drop()`, Entonces el bucle de recepción del proveedor termina igual que ante una desconexión real del proveedor.
- Dado el cierre (teardown) del fixture, Entonces `"fake"` ya no está en `_REGISTRY`.

### REQ-05 Ayudante de drenaje de WebSocket
Un ayudante (helper) DEBE leer mensajes de WebSocket hasta un tipo objetivo (por ejemplo `session_ended`) o hasta un tiempo límite, y devolver todos los mensajes vistos. Si se agota el tiempo DEBE lanzar un fallo que nombre los tipos recibidos; nunca DEBE quedarse colgado.

- Dada una sesión que termina con normalidad, Cuando se drena hasta `session_ended`, Entonces se devuelven en orden todos los mensajes intermedios.
- Dado un servidor que nunca envía `session_ended`, Cuando se cumple el tiempo límite, Entonces el helper lanza un error con los tipos recibidos.

### REQ-06 Stub de Deepgram por loopback
Un fixture DEBE levantar `websockets.serve` en `127.0.0.1:0` (loopback: solo la propia máquina), parchear `app.providers.stt.deepgram.provider._DEEPGRAM_WS_URL` y `_RETRY_DELAYS=[0]`, y registrar la ruta y la query de la petición, la cabecera `Authorization`, los frames binarios y `CloseStream`. DEBE poder programarse para enviar frames `Results` y para cerrar de forma abrupta. La señalización entre hilos con TestClient DEBE usar `threading.Event`.

- Dado que `DeepgramProvider` se conecta, Entonces el stub expone la query y `Authorization: Token <test key>` (la clave de prueba).
- Dado un cierre abrupto programado, Cuando el proveedor está conectado, Entonces el socket se cierra sin un `CloseStream`.
- Dado el cierre (teardown) del fixture, Entonces el puerto queda liberado y las constantes parcheadas se restauran.
