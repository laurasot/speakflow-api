# Especificación delta: xfail-bug-catalog (catálogo de bugs con xfail)

> Palabras clave (RFC 2119): DEBE = obligatorio (MUST/SHALL); NO DEBE = prohibido (MUST NOT); DEBERÍA = recomendado (SHOULD); PUEDE = opcional (MAY).

## Propósito

Siete hallazgos confirmados (#1, #2, #3, #4, #5, #6, #10) DEBEN demostrarse cada uno con una prueba `xfail(strict=True)` (xfail: prueba que se espera que falle mientras el bug siga abierto) que afirme el comportamiento correcto después de la corrección. No se cambia código de producción. El conjunto de xfail DEBE ser exactamente estos siete; cada uno DEBE verificarse con `pytest --runxfail` fallando por la razón afirmada, y el texto de `reason=` DEBE nombrar el hallazgo.

## Requisitos

### REQ-01 #1 Toma de sesión ajena
Motivo (`reason=`): `"#1 session takeover: user_id not compared (session_manager.py:62)"` (toma de sesión: no se compara el user_id). Punto de prueba (seam): prueba de integración, dos api keys (monkeypatch de `settings.auth_api_key_hashes`, limpiar `get_token_verifier`), dos `TestClient.websocket_connect`, instancias de `FakeSpeechProvider`; esperar con `threading.Event`.
- Dado que el usuario A tiene una sesión activa, Cuando el usuario B inicia con el `session_id` de A, Entonces no se llama al `disconnect` del proveedor de A y B es rechazado o recibe una sesión nueva.
- Caso límite: B envía audio con el id de A; Entonces ningún byte de B llega al `send_audio` de A.

### REQ-02 #2 Tamaño de frame y tope de sesiones
Motivo (`reason=`): `"#2 frame size/session cap not validated (websocket_stt.py:123-137)"` (no se validan el tamaño del frame ni el tope de sesiones). Punto de prueba: prueba de integración con `FakeSpeechProvider`.
- Dada la metadata `size=10`, Cuando llega un frame de 1000 bytes, Entonces el proveedor no lo recibe (error o descarte).
- Dado un usuario, Cuando se abren 51 sesiones (tope fijo de 50; el límite real es de la Fase 2), Entonces la sesión 51 es rechazada.
- Caso límite: un frame cuya longitud es igual a `size` DEBE seguir reenviándose (evita rechazar de más).

### REQ-03 #3 La caída del proveedor se informa
Motivo (`reason=`): `"#3 provider drop not surfaced to client (deepgram/provider.py:144-148)"` (la caída del proveedor no se informa al cliente). Punto de prueba principal: `DeepgramProvider` real contra el stub loopback que cierra de forma abrupta; secundario: `FakeSpeechProvider.drop()`.
- Dada una sesión activa, Cuando se cae la conexión del proveedor, Entonces el cliente recibe al menos un mensaje `error` (el código no se fija; es de la Fase 3).
- Caso límite: tras la caída la prueba envía `stop_session` y drena hasta `session_ended`; NO DEBE quedarse colgada.

### REQ-04 #4 El procesador no bloquea el bucle de recepción
Motivo (`reason=`): `"#4 TranscriptProcessor awaited inline blocks receive loop (speech_service.py:40-54)"` (esperar al TranscriptProcessor en línea bloquea el bucle de recepción). Punto de prueba: prueba unitaria, `SpeechService(TranscriptProcessor(chain=BlockingChain))` donde `ainvoke` espera un `asyncio.Event`; sin `OPENAI_API_KEY`.
- Dado que la cadena (chain) está bloqueada, Cuando llega una transcripción, Entonces `send_to_client` se ejecuta en unos ~0.1 s.
- Caso límite: la prueba DEBE liberar el evento en el teardown para que no quede ninguna tarea colgada.

### REQ-05 #5 `_is_question` y límites de palabra
Motivo (`reason=`): `"#5 _is_question uses startswith (suggestion_trigger.py:259-260)"` (`_is_question` usa startswith). Punto de prueba: parametrizar el fixture `trigger` que ya existe en `tests/unit/test_suggestion_trigger.py`.
- Dados "dos horas", "domingo", "island", "candidate", Cuando corre `_is_question`, Entonces devuelve False.
- Caso límite: las preguntas verdaderas ("do you know", "dónde está") DEBEN seguir dando True; son controles que no son xfail.

### REQ-06 #6 Un turno por intervención
Motivo (`reason=`): `"#6 only is_final read, speech_final ignored (deepgram/provider.py:131)"` (solo se lee is_final y se ignora speech_final). Punto de prueba: `DeepgramProvider` real + stub loopback que envía `is_final=true,speech_final=false` y luego `true,true`; `SuggestionService.generate` falso; `monkeypatch.setattr` sobre `suggestion_silence_threshold` (se salta la restricción `ge=1.0`).
- Dados dos frames `Results` de una misma intervención, Cuando se procesan, Entonces el contexto que se pasa a `generate` contiene un turno.
- Caso límite: dos frames separados por `speech_final=true` DEBEN producir dos turnos. El supuesto sobre cómo funciona Deepgram DEBE quedar escrito en el docstring de la prueba.

### REQ-07 #10 Tiempo límite del LLM
Motivo (`reason=`): `"#10 provider_response_timeout unused (openai/provider.py:28, suggestion_service.py:83)"` (provider_response_timeout no se usa). Punto de prueba: prueba unitaria, `llm_provider="openai"`, clave falsa, stub HTTP loopback que nunca responde (alternativa: un `RunnableLambda` que se queda colgado en `service._chain`), tiempo límite ~0.5.
- Dado un LLM que no responde, Cuando se llama a `generate`, Entonces devuelve `None` en ~2 s.
- Caso límite: con un stub que sí responde, `generate` DEBE seguir devolviendo una sugerencia (es un control, no xfail). Si `OPENAI_BASE_URL` no está soportado, DEBE usarse el punto de prueba alternativo y anotarse en el `reason`.
