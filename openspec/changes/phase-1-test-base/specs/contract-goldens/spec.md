# Especificación delta: contract-goldens (contratos golden)

> Palabras clave (RFC 2119): DEBE = obligatorio (MUST/SHALL); NO DEBE = prohibido (MUST NOT); DEBERÍA = recomendado (SHOULD); PUEDE = opcional (MAY).

## Propósito

Capturar los contratos externos actuales (mensajes de WebSocket, URL y cabeceras de Deepgram) como archivos golden (archivos de referencia con la salida aceptada como correcta, contra los que se compara), más un flujo e2e (de punta a punta) dentro del mismo proceso y una prueba de salud, para que las fases siguientes detecten cambios accidentales del protocolo.

## Requisitos

### REQ-01 Normalizador de goldens
Un ayudante (helper) en `tests/helpers` DEBE convertir los UUID en `<uuid-N>` según el orden de primera aparición (mismo UUID, mismo N) y las marcas de tiempo en `<ts>`, de forma recursiva sobre el JSON. Los goldens viven en `tests/golden/*.json`; `UPDATE_GOLDEN=1` DEBE regenerarlos; si no está activo, una diferencia DEBE hacer fallar la prueba con un diff legible. El normalizador DEBE tener sus propias pruebas unitarias.

- Dados dos mensajes que comparten un UUID y un segundo UUID distinto, Entonces la salida tiene `<uuid-1>`, `<uuid-1>`, `<uuid-2>`.
- Dado un archivo golden que falta y sin `UPDATE_GOLDEN`, Entonces la prueba falla (nunca lo crea en silencio).
- Dado un texto que solo se parece a un UUID pero está mal formado, Entonces se deja sin cambios.

### REQ-02 Goldens de mensajes de WebSocket
Los goldens DEBEN cubrir cada tipo de mensaje que el servidor emite en una sesión (`session_started`, transcripción, `suggestion`, `error`, `session_ended`), grabados con `FakeSpeechProvider` y el helper de drenaje. El orden de las claves NO DEBE importar; los nombres de campo y los tipos de valor SÍ. Como el aislamiento del entorno deja las sugerencias desactivadas (LLM sin clave), el golden de `suggestion` DEBE inyectar un `SuggestionService` falso en el `SpeechService` de la prueba (sin llamadas al LLM) y bajar `suggestion_silence_threshold` con `monkeypatch.setattr`.

- Dada una sesión normal, Cuando se normalizan los mensajes, Entonces son iguales a los goldens.
- Dado un campo renombrado o eliminado, Entonces la prueba golden falla.
- Dado un orden de ejecución aleatorio, Entonces los goldens siguen coincidiendo (sin depender de tiempos más allá del drenaje).

### REQ-03 Golden de URL y cabeceras de Deepgram
Usando el stub loopback (servidor simulado en la propia máquina), un golden DEBE capturar la ruta de la petición, la query (`model`, `language`, `encoding`, `sample_rate`, `channels`, `interim_results`, `smart_format`, `utterance_end_ms`) y la forma de la cabecera `Authorization`. La clave real DEBE reemplazarse por la clave de prueba y NO DEBE aparecer en el archivo golden.

- Dado `DeepgramProvider.connect`, Entonces la petición registrada coincide con el golden.
- Dado un parámetro de query cambiado, Entonces la prueba falla.
- Dado el archivo golden, Entonces no contiene ningún secreto aparte del marcador fijo de la clave de prueba.

### REQ-04 Flujo e2e dentro del proceso
Una prueba marcada `e2e` DEBE ejecutar el flujo completo dentro del mismo proceso (TestClient, proveedor falso): autenticarse, iniciar sesión, enviar audio, recibir transcripción, detener, `session_ended`. NO DEBE necesitar Docker ni red.

- Dadas credenciales válidas, Cuando corre el flujo, Entonces los mensajes llegan en el orden del protocolo y la sesión queda limpiada.
- Dada una clave inválida, Entonces la conexión es rechazada antes de que exista ninguna sesión.

### REQ-05 Prueba de salud (health)
Una prueba unitaria o de integración DEBE verificar que `GET /v1/health` devuelve 200 y el cuerpo `{"status": "ok", "active_sessions": <entero>}` (modelo `HealthResponse` de `app/routers/v1/health.py`).

- Dada la app sin sesiones, Cuando se hace `GET /v1/health`, Entonces responde 200 con `{"status": "ok", "active_sessions": 0}`.
- Dada una sesión activa, Entonces `active_sessions` vale 1.
- Dado un `.env` desactualizado, Entonces la respuesta no cambia (aplica el aislamiento del entorno).
