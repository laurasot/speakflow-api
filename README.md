# SpeakFlow API

Backend service that receives real-time audio from multiple clients (microphone + system audio as separate streams), forwards it to a configurable Speech-to-Text provider, and returns normalized transcripts over WebSocket.

Designed to pair with **[SpeakFlow Desktop](https://github.com/laurasot/speakflow-desktop)** — the Electron app that captures dual audio and streams PCM chunks to this API.

## Features

- **Dual-stream sessions** — isolated `microphone` and `system` channels per session
- **Provider abstraction** — switch STT vendors via `SPEECH_PROVIDER` (no code changes)
- **Binary PCM protocol** — JSON metadata + raw PCM frames (not base64)
- **Session isolation** — concurrent users never share audio queues or provider connections
- **Persistent provider connections** — one WebSocket per `(session_id, source)`, not per chunk
- **Fault tolerance** — automatic reconnection with exponential backoff per provider
- **Normalized output** — same transcript schema regardless of Deepgram, AssemblyAI, AWS, or Whisper
- **Observability** — structured JSON logs + metrics for provider comparison
- **Optional LangChain** — post-processing on final transcripts (punctuation cleanup, etc.)

## Architecture

Every ~500ms, the client sends **2 WebSocket frames** per audio chunk:

1. **Text frame** — JSON metadata (`session_id`, `source`, `timestamp`, `size`)
2. **Binary frame** — raw PCM16 LE mono @ 16 kHz (~16 KB)

```
┌─────────────────┐     JSON + PCM      ┌──────────────────┐
│ SpeakFlow       │ ──────────────────► │ WebSocket        │
│ Desktop         │   /v1/stt/stream    │ (thin router)    │
└─────────────────┘                     └────────┬─────────┘
                                               │
                                               ▼
                                      ┌──────────────────┐
                                      │ SessionManager   │
                                      │  ├─ mic queue    │
                                      │  └─ system queue │
                                      └────────┬─────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
             ┌────────────┐           ┌────────────┐           ┌────────────┐
             │ Deepgram   │           │ AssemblyAI │           │ AWS / etc. │
             └────────────┘           └────────────┘           └────────────┘
                    │                          │                          │
                    └──────────────────────────┼──────────────────────────┘
                                               ▼
                                      ┌──────────────────┐
                                      │ Normalized       │
                                      │ transcript JSON  │
                                      └──────────────────┘
```

**Golden rule:** audio from one user/session must never mix with another. Each `(session_id, source)` gets its own `asyncio.Queue` and dedicated provider connection.

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI + Uvicorn |
| Validation | Pydantic v2 + pydantic-settings |
| Async I/O | asyncio, websockets |
| STT providers | Deepgram, AssemblyAI, AWS Transcribe, Whisper (local) |
| Post-processing | LangChain + LangChain OpenAI (optional) |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Tests | pytest + pytest-asyncio |
| Linting | ruff, mypy |

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.4+
- API key for your chosen STT provider (e.g. [Deepgram](https://console.deepgram.com/))

### Installation

```bash
git clone https://github.com/laurasot/speakflow-api.git
cd speakflow-api
uv sync
```

### Configure

Copy the example env file and fill in your secrets:

```bash
cp .env.example .env
```

Minimum for Deepgram:

```env
SPEECH_PROVIDER=deepgram
DEEPGRAM_API_KEY=your_api_key_here
LOG_LEVEL=INFO
```

Never commit `.env` — it is listed in `.gitignore`.

### Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| Endpoint | URL |
|----------|-----|
| Health | `http://localhost:8000/v1/health` |
| API docs | `http://localhost:8000/docs` |
| WebSocket STT | `ws://localhost:8000/v1/stt/stream` |

Quick health check:

```bash
curl http://localhost:8000/v1/health
```

Expected response:

```json
{"status":"ok","active_sessions":0}
```

### Connect from SpeakFlow Desktop

In Desktop **Settings**, set:

| Field | Value |
|-------|-------|
| User ID | your identifier |
| Backend WebSocket URL | `ws://localhost:8000/v1/stt/stream` |

The desktop app must send the header `X-User-Id` on the WebSocket handshake (same value as User ID).

## WebSocket Protocol (summary)

### Authentication

```
GET /v1/stt/stream HTTP/1.1
X-User-Id: user123
```

Connections without `X-User-Id` are rejected with code `1008`.

### Client → Server

| Message | Description |
|---------|-------------|
| `start_session` | Opens provider connections for each source |
| `audio_chunk` | Metadata JSON, then binary PCM in the **next** frame |
| `stop_session` | Graceful shutdown |

**`start_session` example:**

```json
{
  "type": "start_session",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user123",
  "sources": ["microphone", "system"],
  "audio_config": {
    "sample_rate": 16000,
    "channels": 1,
    "encoding": "pcm16le"
  }
}
```

**`audio_chunk` — two frames:**

```json
{
  "type": "audio_chunk",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "microphone",
  "timestamp": 1717000000123,
  "size": 16000
}
```

→ immediately followed by a **binary** frame with 16 000 bytes of PCM16 LE audio.

### Server → Client

| Message | Description |
|---------|-------------|
| `session_started` | Session and provider streams are ready |
| `transcript` | Partial or final transcription |
| `session_ended` | Clean close confirmed |
| `error` | Validation, provider, or session errors |

**`transcript` example:**

```json
{
  "type": "transcript",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "microphone",
  "text": "Hello, how are you?",
  "is_final": false,
  "timestamp": 1717000001234,
  "provider": "deepgram",
  "language": "es",
  "start_time": 0.0,
  "end_time": 0.5
}
```

## Switch STT Provider

Change one line in `.env` — no code changes:

```env
SPEECH_PROVIDER=deepgram        # default
SPEECH_PROVIDER=assemblyai
SPEECH_PROVIDER=aws_transcribe
SPEECH_PROVIDER=whisper_local   # requires: uv add openai-whisper
```

Restart the server after changing provider.

## Project Structure

```
speakflow-api/
├── app/
│   ├── main.py                    # FastAPI app, CORS, lifespan
│   ├── routers/v1/
│   │   ├── health.py              # GET /v1/health
│   │   └── websocket_stt.py       # WS  /v1/stt/stream
│   ├── core/
│   │   ├── config.py              # Environment settings
│   │   ├── logging.py             # Structured JSON logging
│   │   └── dependencies.py        # DI (SessionManager singleton)
│   ├── schemas/
│   │   ├── audio.py               # Incoming message models
│   │   └── transcript.py          # Outgoing message models
│   ├── services/
│   │   ├── session_manager.py     # Session + stream isolation
│   │   ├── speech_service.py      # Transcript pipeline
│   │   └── transcript_processor.py# LangChain post-processing
│   ├── providers/
│   │   ├── base.py                # SpeechProvider protocol
│   │   ├── factory.py             # Provider registry
│   │   ├── deepgram/
│   │   ├── assemblyai/
│   │   ├── aws_transcribe/
│   │   └── whisper_local/
│   └── infrastructure/
│       └── metrics.py             # Provider comparison metrics
├── tests/
│   ├── unit/
│   └── integration/
├── pyproject.toml
├── .env.example
└── README.md
```

## Tests

```bash
uv run pytest tests/ -v
```

Critical coverage:

- Concurrent sessions use separate provider instances
- Audio routing does not mix bytes between sessions
- WebSocket rejects missing `X-User-Id`
- Invalid messages return `error` without crashing the server

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Binary PCM, not base64 | ~25% less bandwidth; direct compatibility with STT streaming APIs |
| Two frames per chunk | WebSocket natively separates text vs binary; metadata stays JSON |
| Separate sources | Backend can attribute speech to user vs meeting without client-side diarization |
| Provider protocol | Swap vendors for quality, latency, cost, and language support benchmarks |
| Lock only on create/close | Hot-path `route_audio` has zero lock contention between sessions |
| LangChain on finals only | Avoids LLM latency on every partial transcript |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPEECH_PROVIDER` | `deepgram` | Active STT provider |
| `DEEPGRAM_API_KEY` | — | Deepgram API token |
| `ASSEMBLYAI_API_KEY` | — | AssemblyAI API key |
| `AWS_REGION` | `us-east-1` | AWS region for Transcribe |
| `AWS_ACCESS_KEY_ID` | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | — | AWS credentials |
| `OPENAI_API_KEY` | — | Optional LangChain post-processing |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed CORS origins |
| `PROVIDER_CONNECT_TIMEOUT` | `10` | Provider connect timeout (seconds) |
| `PROVIDER_RESPONSE_TIMEOUT` | `30` | Provider response timeout (seconds) |

## Contributing

```bash
git checkout -b feature/my-feature
# ... changes ...
uv run ruff check app tests
uv run pytest tests/
git commit -m "feat: description"
# Push + PR
```

## Related Projects

| Project | Role |
|---------|------|
| **SpeakFlow Desktop** | Captures mic + system audio, streams to this API |
