# Plan de Ejecución — speakflow-api

---

## ¿Qué vamos a construir?

Un backend que recibe audio en tiempo real desde múltiples usuarios al mismo tiempo,
lo envía a un servicio de transcripción (como Deepgram o AssemblyAI), y devuelve
el texto transcrito. El proveedor de transcripción se puede cambiar con una sola
variable de entorno, sin tocar el código.

La regla de oro: **el audio de un usuario jamás puede mezclarse con el de otro.**

---

## Estructura de carpetas que vamos a crear

```
speakflow-api/
├── pyproject.toml              ← dependencias y configuración del proyecto
├── .env.example                ← variables de entorno de ejemplo (sin secretos)
├── Dockerfile                  ← imagen Docker lista para producción
├── app/
│   ├── main.py                 ← punto de entrada, registra todos los routers
│   ├── routers/
│   │   └── v1/
│   │       ├── health.py       ← ruta /v1/health para saber si el servidor está vivo
│   │       └── websocket_stt.py← conexión WebSocket /v1/stt/stream que recibe el audio
│   ├── core/
│   │   ├── config.py           ← lee las variables de entorno
│   │   ├── logging.py          ← logs en formato JSON
│   │   └── dependencies.py     ← objetos compartidos entre rutas
│   ├── schemas/
│   │   ├── audio.py            ← forma esperada del mensaje de entrada
│   │   └── transcript.py       ← forma estándar de la transcripción de salida
│   ├── services/
│   │   ├── session_manager.py  ← maneja sesiones activas, aísla el audio por usuario
│   │   ├── speech_service.py   ← orquesta el envío de audio al proveedor
│   │   └── transcript_processor.py ← normaliza la respuesta del proveedor
│   ├── providers/
│   │   ├── base.py             ← contrato que todos los proveedores deben cumplir
│   │   ├── factory.py          ← elige el proveedor según la variable de entorno
│   │   ├── deepgram/
│   │   ├── assemblyai/
│   │   ├── aws_transcribe/
│   │   └── whisper_local/
│   └── infrastructure/
│       └── metrics.py          ← guarda datos para comparar proveedores
└── tests/
    ├── unit/                   ← pruebas de piezas individuales
    └── integration/            ← pruebas del sistema completo
```

---

## Protocolo WebSocket

### Autenticación (al conectar)

El cliente envía el `user_id` como header HTTP en el handshake inicial:

```
GET /v1/stt/stream HTTP/1.1
X-User-Id: user123
```

---

### Mensajes de Cliente → Servidor

**1. `start_session` — iniciar sesión**

Primer mensaje que se envía. Abre las conexiones con el proveedor para cada fuente.

```json
{
  "type": "start_session",
  "session_id": "uuid",
  "user_id": "user123",
  "sources": ["microphone", "system"],
  "audio_config": {
    "sample_rate": 16000,
    "channels": 1,
    "encoding": "pcm16le"
  }
}
```

---

**2. `audio_chunk` — enviar audio**

Cada chunk de audio se envía en **2 frames WebSocket consecutivos**:

Frame 1 — metadata (texto JSON):
```json
{
  "type": "audio_chunk",
  "session_id": "uuid",
  "source": "microphone",
  "timestamp": 1717000000123,
  "size": 16000
}
```

Frame 2 — audio crudo (binario, inmediatamente después):
```
<bytes PCM: signed 16-bit, little-endian, mono, 16 000 Hz>
Tamaño típico: 16 000 bytes = ~500 ms de audio
```

> Un chunk = 2 frames. El backend lee primero el JSON y luego los bytes, y los asocia.

**Ritmo esperado:** ~4 JSON + ~4 binarios por segundo = 8 frames WebSocket/s  
(2 chunks de mic + 2 chunks de system por segundo)

---

**3. `stop_session` — terminar sesión**

```json
{
  "type": "stop_session",
  "session_id": "uuid"
}
```

---

### Mensajes de Servidor → Cliente

**1. `session_started` — confirmación de inicio**
```json
{
  "type": "session_started",
  "session_id": "uuid"
}
```

**2. `transcript` — transcripción disponible**
```json
{
  "type": "transcript",
  "session_id": "uuid",
  "source": "microphone",
  "text": "Hola, ¿cómo estás?",
  "is_final": false,
  "timestamp": 1717000001234
}
```

**3. `session_ended` — confirmación de cierre**
```json
{
  "type": "session_ended",
  "session_id": "uuid"
}
```

**4. `error` — algo falló**
```json
{
  "type": "error",
  "code": "provider_unavailable",
  "message": "Deepgram connection lost",
  "session_id": "uuid"
}
```

---

---

## Schemas y contratos de código

### `app/schemas/audio.py` — mensajes de entrada

```python
from typing import Literal
from pydantic import BaseModel, Field, UUID4


class AudioConfig(BaseModel):
    sample_rate: int = Field(default=16000)
    channels: int = Field(default=1)
    encoding: Literal["pcm16le"] = "pcm16le"


class StartSessionMessage(BaseModel):
    type: Literal["start_session"]
    session_id: UUID4
    user_id: str
    sources: list[Literal["microphone", "system"]]
    audio_config: AudioConfig


class AudioChunkMetadata(BaseModel):
    type: Literal["audio_chunk"]
    session_id: UUID4
    source: Literal["microphone", "system"]
    timestamp: int = Field(..., description="Unix timestamp en milisegundos")
    size: int = Field(..., description="Tamaño en bytes del frame binario que sigue")


class StopSessionMessage(BaseModel):
    type: Literal["stop_session"]
    session_id: UUID4


# Unión discriminada — para parsear cualquier mensaje de entrada
IncomingMessage = StartSessionMessage | AudioChunkMetadata | StopSessionMessage
```

---

### `app/schemas/transcript.py` — mensajes de salida

```python
from typing import Literal
from pydantic import BaseModel, UUID4


class SessionStartedMessage(BaseModel):
    type: Literal["session_started"] = "session_started"
    session_id: UUID4


class TranscriptMessage(BaseModel):
    type: Literal["transcript"] = "transcript"
    session_id: UUID4
    source: Literal["microphone", "system"]
    text: str
    is_final: bool
    timestamp: int = Field(..., description="Unix timestamp en milisegundos")
    provider: str
    language: str
    start_time: float
    end_time: float


class SessionEndedMessage(BaseModel):
    type: Literal["session_ended"] = "session_ended"
    session_id: UUID4


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    session_id: UUID4 | None = None


# Unión discriminada — para serializar cualquier respuesta del servidor
OutgoingMessage = SessionStartedMessage | TranscriptMessage | SessionEndedMessage | ErrorMessage
```

---

### `app/providers/base.py` — contrato de proveedores

Todo proveedor debe implementar exactamente esta interfaz. Si no la cumple, el sistema no lo acepta.

```python
from typing import Protocol, Callable, Awaitable
from app.schemas.transcript import TranscriptMessage


class SpeechProvider(Protocol):
    provider_name: str

    async def connect(
        self,
        session_id: str,
        source: str,
        audio_config: AudioConfig,
    ) -> None:
        """Abre una conexión persistente con el proveedor para esta fuente."""
        ...

    async def disconnect(self) -> None:
        """Cierra la conexión limpiamente y libera recursos."""
        ...

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Envía un chunk de audio PCM crudo al proveedor."""
        ...

    def on_transcript(
        self,
        callback: Callable[[TranscriptMessage], Awaitable[None]],
    ) -> None:
        """Registra el callback que se llama cuando llega una transcripción."""
        ...
```

---

### `app/providers/factory.py` — registro de proveedores

```python
from app.core.config import settings
from app.providers.base import SpeechProvider

PROVIDER_REGISTRY: dict[str, type[SpeechProvider]] = {}


def register_provider(name: str):
    """Decorador para registrar un proveedor en el registry."""
    def decorator(cls: type[SpeechProvider]):
        PROVIDER_REGISTRY[name] = cls
        return cls
    return decorator


def create_provider() -> SpeechProvider:
    """Crea una instancia del proveedor configurado en SPEECH_PROVIDER."""
    provider_class = PROVIDER_REGISTRY.get(settings.speech_provider)
    if not provider_class:
        raise ValueError(f"Proveedor desconocido: {settings.speech_provider}")
    return provider_class()
```

Los proveedores se registran con el decorador:

```python
# app/providers/deepgram/provider.py
@register_provider("deepgram")
class DeepgramProvider:
    provider_name = "deepgram"
    ...
```

---

### `app/services/session_manager.py` — estructura interna de sesiones

```python
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from app.providers.base import SpeechProvider


@dataclass
class AudioStream:
    source: Literal["microphone", "system"]
    queue: asyncio.Queue[bytes]
    provider: SpeechProvider
    task: asyncio.Task          # tarea que consume la cola y envía al proveedor


@dataclass
class Session:
    session_id: str
    user_id: str
    streams: dict[str, AudioStream]   # clave: "microphone" o "system"
    created_at: datetime = field(default_factory=datetime.utcnow)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()   # solo para crear/borrar sesiones

    async def create_session(self, msg: StartSessionMessage) -> None:
        """Crea la sesión y abre una conexión al proveedor por cada fuente."""
        ...

    async def route_audio(self, session_id: str, source: str, pcm_bytes: bytes) -> None:
        """Mete el audio en la cola de la fuente correcta. Sin lock — aislamiento por diseño."""
        session = self._sessions[session_id]
        await session.streams[source].queue.put(pcm_bytes)

    async def close_session(self, session_id: str) -> None:
        """Cancela las tareas, desconecta proveedores y borra la sesión."""
        ...
```

**Garantía de aislamiento:** después de crear la sesión, `route_audio` no necesita ningún lock porque cada sesión tiene sus propias colas. Dos usuarios nunca comparten ningún objeto.

---

## Pasos de implementación

### Paso 1 — Base del proyecto
Crear `pyproject.toml` con todas las dependencias, la estructura de carpetas y
la configuración de herramientas (linter, tests, tipos).

**Archivos que se crean:**
- `pyproject.toml`
- `.env.example`
- Todas las carpetas con sus `__init__.py`

---

### Paso 2 — Esquemas de datos
Definir todos los tipos de mensajes del protocolo WebSocket (ver sección anterior).

**Mensajes de entrada (`app/schemas/audio.py`):**
- `StartSessionMessage` — inicio de sesión con configuración de audio
- `AudioChunkMetadata` — metadata del chunk (el audio viene como binario en el frame siguiente)
- `StopSessionMessage` — cierre de sesión

**Mensajes de salida (`app/schemas/transcript.py`):**
- `SessionStartedMessage` — confirmación de inicio
- `TranscriptMessage` — transcripción parcial o final
- `SessionEndedMessage` — confirmación de cierre
- `ErrorMessage` — errores con código y descripción

**Nota:** el audio viaja como bytes PCM crudos, no en base64.

**Archivos que se crean:**
- `app/schemas/audio.py`
- `app/schemas/transcript.py`

---

### Paso 3 — Configuración y logs
Leer las variables de entorno y configurar los logs en formato JSON.
Desde acá en adelante, todo loguea con contexto (session_id, request_id).

**Variables de entorno principales:**
```
SPEECH_PROVIDER=deepgram
DEEPGRAM_API_KEY=...
LOG_LEVEL=INFO
```

**Archivos que se crean:**
- `app/core/config.py`
- `app/core/logging.py`
- `app/core/dependencies.py`

---

### Paso 4 — Contrato de proveedores
Definir la interfaz que todos los proveedores deben implementar.
Si un proveedor no tiene estos métodos, no funciona.

**Métodos obligatorios:**
- `connect()` — abre la conexión persistente
- `disconnect()` — cierra limpiamente
- `send_audio()` — envía un chunk de audio
- `on_transcript()` — recibe la transcripción cuando llega

**Archivos que se crean:**
- `app/providers/base.py`
- `app/providers/factory.py`

---

### Paso 5 — Gestor de sesiones (el corazón del sistema)
Este es el componente más crítico. Mantiene una sesión por usuario, con colas
de audio separadas por fuente (micrófono y audio del sistema).

**Garantías de aislamiento:**
- Cada par `(session_id, fuente)` tiene su propia cola de audio
- Cada cola tiene su propia conexión al proveedor
- Las sesiones no comparten nada entre sí después de ser creadas
- Se usa un lock solo para crear/borrar sesiones, no para enviar audio

**Archivos que se crean:**
- `app/services/session_manager.py`

---

### Paso 6 — Endpoint WebSocket
La puerta de entrada al sistema. Recibe el audio, lo valida y lo manda al
gestor de sesiones. No hace nada más.

**Flujo:**
1. Cliente conecta por WebSocket
2. Envía mensajes JSON con audio en base64
3. El endpoint valida el formato y pasa el audio a la sesión correspondiente
4. Las transcripciones llegan por la misma conexión WebSocket

**Archivos que se crean:**
- `app/routers/v1/websocket_stt.py`
- `app/routers/v1/health.py`
- `app/main.py`

---

### Paso 7 — Primer proveedor: Deepgram
Implementar Deepgram como el proveedor inicial con:
- Conexión persistente (una sola por sesión, no por chunk)
- Reconexión automática con reintentos progresivos (1s, 2s, 4s)
- Timeout si el proveedor no responde
- Cierre limpio cuando la sesión termina

**Archivos que se crean:**
- `app/providers/deepgram/provider.py`
- `app/providers/deepgram/__init__.py`
- `app/services/speech_service.py`
- `app/services/transcript_processor.py`

---

### Paso 8 — Métricas para comparar proveedores
Guardar datos que permitan después comparar Deepgram vs AssemblyAI vs otros.

**Qué se guarda por cada transcripción:**
- proveedor usado
- latencia (ms entre audio enviado y texto recibido)
- cantidad de caracteres
- si fue parcial o final
- errores

**Archivos que se crean:**
- `app/infrastructure/metrics.py`

---

### Paso 9 — Proveedores adicionales
Implementar los demás proveedores siguiendo exactamente el mismo contrato del Paso 4.

**Archivos que se crean:**
- `app/providers/assemblyai/provider.py`
- `app/providers/aws_transcribe/provider.py`
- `app/providers/whisper_local/provider.py`

---

### Paso 10 — LangChain (post-procesamiento)
Agregar el procesamiento con LangChain sobre las transcripciones finales.
Solo se activa cuando `is_final=True`. No bloquea el flujo de audio.

**Archivos que se modifican:**
- `app/services/transcript_processor.py`

---

### Paso 11 — Pruebas
Escribir pruebas para verificar que todo funciona, especialmente el aislamiento
entre usuarios concurrentes.

**Pruebas críticas:**
- Dos usuarios enviando audio al mismo tiempo no se mezclan
- Si un proveedor falla, el servidor no se cae
- La reconexión automática funciona
- Cada proveedor devuelve la forma estándar de transcripción

**Archivos que se crean:**
- `tests/unit/test_session_manager.py`
- `tests/unit/test_providers.py`
- `tests/integration/test_websocket_concurrent.py`

---

## Orden de revisión sugerido

Cuando quieras revisar avances, los archivos más importantes son estos, en este orden:

1. `app/schemas/` — para verificar los contratos de datos
2. `app/providers/base.py` — para ver el contrato de proveedores
3. `app/services/session_manager.py` — para verificar el aislamiento
4. `app/routers/v1/websocket_stt.py` — para ver el flujo completo
5. `tests/integration/test_websocket_concurrent.py` — para ver las pruebas de concurrencia

---

## Cómo cambiar de proveedor

Solo cambiar esta línea en el archivo `.env`:

```
SPEECH_PROVIDER=deepgram       ← para usar Deepgram
SPEECH_PROVIDER=assemblyai     ← para usar AssemblyAI
SPEECH_PROVIDER=aws_transcribe ← para usar AWS Transcribe
SPEECH_PROVIDER=whisper_local  ← para usar Whisper local
```

Sin tocar el código.
