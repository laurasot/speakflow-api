# SpeakFlow API

## Context

SpeakFlow solves a specific problem: being lost in conversations where you don't fully understand what's being asked or how to respond — especially during interviews, meetings in a second language, or technical discussions where you freeze up.

The API receives real-time audio from two separate sources (the user's microphone and system audio capturing the meeting/call), transcribes both streams independently, and when it detects that the user has gone silent, it suggests what they could say next using an LLM that understands the conversation context.

This is not a generic transcription API. The core value is in *when* to call the LLM (not on every word, which would be expensive and noisy) and *how* to isolate concurrent user sessions so their audio never mixes.

It pairs with **[SpeakFlow Desktop](https://github.com/laurasot/speakflow-desktop)**, the Electron app that captures dual audio and streams PCM chunks to this backend.

## Architecture

The backend is designed around session isolation and provider abstraction. Every user gets their own session, and within each session, the two audio sources (microphone + system) run through independent queues and provider connections. This ensures that if ten users are using SpeakFlow simultaneously, their audio never crosses paths.

The flow is:

1. Client connects via WebSocket and sends a `start_session` message
2. `SessionManager` creates two isolated `asyncio.Queue` instances: one for `microphone`, one for `system`
3. Client streams audio as **JSON metadata + raw PCM binary frames** (not base64, to save bandwidth)
4. Each queue feeds into a persistent WebSocket connection to the configured STT provider (Deepgram, AssemblyAI, AWS Transcribe, or local Whisper)
5. Transcripts come back, get normalized to a common schema, and are forwarded to the client
6. When a transcript is marked as `final`, `SuggestionTrigger` evaluates whether to start a silence timer
7. If the expected party (User or Speaker) doesn't respond within ~6 seconds, the LLM is called with recent conversation context and returns a suggestion

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

The architecture deliberately keeps the WebSocket router thin. All session logic lives in `SessionManager`, all STT provider complexity is hidden behind a `SpeechProvider` protocol, and all LLM interaction is encapsulated in `SuggestionService`. This makes it easy to swap providers, test components in isolation, and add new STT vendors without touching the WebSocket handler.

### Key Components

**SessionManager**

Manages the lifecycle of user sessions. Each session has a unique ID and contains two isolated audio queues (one per source). The manager ensures that audio chunks are routed to the correct queue and that provider connections are established/torn down cleanly. It's the component that enforces the golden rule: audio from one user must never mix with another.

**SuggestionTrigger**

Decides *when* to invoke the LLM. This is critical for cost control. Instead of calling the LLM on every final transcript (which would be expensive and generate useless suggestions for every utterance), it uses a timer-based approach: when the Speaker says something, start a timer waiting for the User to respond. If the User stays silent, call the LLM. If the User responds, cancel the timer. The trigger also handles edge cases like repeated questions (detected via semantic similarity) and filler words ("um", "uh", "mmm") which indicate the User is struggling to respond.

**EmbeddingService**

Detects when the Speaker repeats a question or statement. Instead of basic text matching (`difflib`), it uses the `BAAI/bge-small-en-v1.5` embedding model to compute semantic similarity. This catches paraphrases: *"What's your experience?"* and *"Tell me about your background"* are semantically similar even if the words differ. Crucially, this system does **not** use a vector database — it generates two embeddings on-the-fly (current turn vs. previous turn), compares them via cosine similarity, and discards them. This is much faster than a vector DB for the use case of comparing 1–2 recent turns.

**Provider Abstraction (STT + LLM)**

Both STT and LLM providers are hidden behind Python protocols (`SpeechProvider`, `LLMProvider`). Each provider lives in its own folder with a factory that instantiates the correct implementation based on environment variables. This means you can switch from Deepgram to AssemblyAI or from OpenAI to Groq by changing a single line in `.env` — no code changes. It also makes testing trivial: mock the protocol, not the vendor SDK.

## Run It

**Prerequisites:**

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 0.4+
- API key for your STT provider (e.g. [Deepgram](https://console.deepgram.com/))

**Install:**

```bash
git clone https://github.com/laurasot/speakflow-api.git
cd speakflow-api
uv sync
```

**Configure:**

```bash
cp .env.example .env
```

Minimum for Deepgram:

```env
SPEECH_PROVIDER=deepgram
DEEPGRAM_API_KEY=your_api_key_here
LOG_LEVEL=INFO
```

**Run:**

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/v1/health
# {"status":"ok","active_sessions":0}
```

WebSocket endpoint: `ws://localhost:8000/v1/stt/stream`

Clients authenticate with `Authorization: Bearer <api-key>` on the WebSocket handshake; without a valid key the connection is rejected with code `1008`. The user identity is derived from the key, never from client input: a `start_session` whose `user_id` does not match the key's user gets an `error` with code `user_mismatch`.

API keys are configured as SHA-256 hashes in `AUTH_API_KEY_HASHES` (JSON, hash → user_id); see `.env.example`. With no keys configured, every connection is rejected.

## Decisions

**Binary PCM frames instead of base64**

WebSocket supports binary frames natively, so we send raw PCM16 audio instead of base64-encoding it. This saves ~25% bandwidth and removes the encode/decode overhead on both client and server. Each audio chunk arrives as two frames: a JSON text frame with metadata (`session_id`, `source`, `timestamp`, `size`), immediately followed by a binary frame with the raw audio bytes.

**Two audio sources (microphone + system) in one session**

The user's mic and the meeting audio need to be transcribed separately so the backend can attribute who said what. The alternative would be to merge both sources client-side and rely on diarization, but diarization is expensive, error-prone, and adds latency. By keeping sources separate, the backend can cleanly distinguish "User said X" from "Speaker said Y" without any ML guesswork.

**Silence-based LLM trigger, not every final transcript**

Calling the LLM on every final transcript would cost too much and generate noise. Most utterances don't need a suggestion ("yeah", "okay", "I agree"). The trigger waits for the *absence* of a response: if the Speaker says something and the User doesn't reply within 6 seconds, *then* call the LLM. This reduces LLM invocations by ~90% while still catching the cases where the user is actually stuck.

**Provider protocol abstraction**

Hardcoding one STT vendor makes it impossible to benchmark alternatives. The protocol pattern lets us swap Deepgram for AssemblyAI for AWS Transcribe with zero code changes. This is useful for comparing latency, accuracy, cost, and language support. Same for LLMs: we can test OpenAI vs Groq vs Anthropic without touching the suggestion logic.

**Lock-free hot path**

Session creation and teardown use a lock (to avoid race conditions when two threads try to create the same session), but the audio routing path (`route_audio`) is entirely lock-free. This is critical for concurrency: if ten users are streaming audio simultaneously, they don't block each other. Each session has its own queue, and queues are thread-safe by design.

**Semantic similarity with ephemeral embeddings**

Repeated questions are a strong signal that the user didn't understand or answer correctly. Detecting repetition with basic text matching misses paraphrases. Semantic embeddings solve this, but using a vector database (Pinecone, Weaviate, etc.) would be overkill: we're only comparing the current turn with the previous turn, not searching across thousands of documents. So we generate two embeddings on-the-fly, compute cosine similarity, and discard them. This is faster than a DB roundtrip and avoids the operational cost of running a vector store.

**Any Speaker turn starts a silence timer**

Initially, the trigger only fired when the Speaker asked an explicit question (ending in `?`). But in real conversations, many prompts are implicit: *"Tell me about your last project"*, *"Go ahead"*, *"I'm listening"*. These don't end in `?`, but the user still needs to respond. So we start a timer after *any* final turn from the Speaker, not just questions. This catches more cases where the user freezes without requiring perfect question detection.

## If I Had to Start Over

**What I'd keep:**

- **Provider abstraction.** Being able to swap STT and LLM vendors without code changes is invaluable. It enabled fast benchmarking and eliminated vendor lock-in.
- **Binary PCM frames.** The bandwidth savings are real, and the protocol is cleaner than base64.
- **Silence-based trigger.** The LLM cost savings justify the complexity. Calling the LLM on every final would have been prohibitively expensive.
- **Separate mic/system sources.** This decision made diarization unnecessary and simplified the entire pipeline.

**What I'd change:**

- **Semantic similarity from day one.** I started with `difflib` text matching because it was simple, but it missed too many paraphrased questions. The embedding model should have been the default, with `difflib` as the fallback.
- **More aggressive timeouts on provider connections.** I initially set timeouts too high, which meant hung connections took too long to fail. Tighter timeouts (10s connect, 30s response) would have surfaced provider issues faster during development.
- **Structured session metadata.** Right now, session context (user_id, sources, config) lives in memory inside `SessionManager`. If the server restarts, all sessions are lost. For a production system, I'd persist session state to Redis or similar so restarts don't drop users.

**What I learned:**

- **Async audio routing is surprisingly simple.** I expected concurrency bugs, but using `asyncio.Queue` per stream made isolation almost trivial. The hard part was not the concurrency model — it was debugging WebSocket edge cases (clients disconnecting mid-chunk, providers rejecting audio format, etc.).
- **LLM cost control is a first-class requirement, not an optimization.** I initially underestimated how expensive it would be to call the LLM frequently. The trigger logic became the most complex part of the system, but it was necessary to make the project viable.
- **Provider SDKs are unreliable.** Deepgram's and AssemblyAI's SDKs both had issues (missing attributes, import errors, unclear error messages). I ended up writing raw WebSocket clients for both and bypassing their SDKs entirely. This was more work upfront but eliminated dependency fragility.

## Decisions That Required More Analysis

**Embedding model: Store vectors in a DB, or generate on-the-fly?**

Options considered:

1. **Vector database (Pinecone, Weaviate, Chroma):** Store every Speaker turn as an embedding, then query for similar past turns.
2. **On-the-fly generation:** Generate embeddings only for the current and previous turn, compare them, discard.

**Why on-the-fly won:**

- **Small context window:** We only care about the last 1–2 Speaker turns, not the entire conversation history.
- **Session lifespan:** Sessions are short (minutes to an hour). There's no value in persisting embeddings across restarts.
- **Latency:** Generating two embeddings (~50ms) is faster than a DB roundtrip for this use case.
- **Operational simplicity:** No need to run and maintain a vector database.

**Trade-off:** If we later want features like "find similar questions from past sessions" or "detect recurring confusion patterns across users", we'd need a DB. For now, on-the-fly is sufficient.

---

**When to call the LLM: Timer-based vs. model-based?**

Options considered:

1. **Timer-based:** Start a timer when the Speaker finishes. If the User doesn't respond by timeout, call the LLM.
2. **Model-based:** Train a classifier to predict "User is stuck" from features like pause duration, filler words, transcript confidence, etc.

**Why timer-based won:**

- **Simplicity:** A timer is trivial to implement and test. A classifier requires labeled training data (which we don't have) and constant tuning.
- **Deterministic:** Timers are predictable. Users can understand "if I'm silent for 6 seconds, I get a suggestion." A model is a black box.
- **Good enough:** The timer approach works well in practice. Adding filler word detection and repeated question logic (which are rule-based, not ML) covered most edge cases.

**Trade-off:** A model could be smarter (e.g. detecting hesitation from audio features like pitch/prosody), but the engineering cost and operational complexity weren't justified.

---

**STT provider switching: Config-based vs. runtime-based?**

Options considered:

1. **Config-based (current approach):** Set `SPEECH_PROVIDER` in `.env`, restart the server.
2. **Runtime-based:** Let the client specify which provider to use per session (e.g. `"stt_provider": "deepgram"` in `start_session`).

**Why config-based won:**

- **Simpler for the initial use case:** SpeakFlow Desktop doesn't need per-session provider control.
- **Easier cost tracking:** All sessions use the same provider, so billing is straightforward.
- **Less attack surface:** Letting clients choose providers opens up abuse vectors (e.g. routing expensive requests to the most costly vendor).

**Trade-off:** If we later offer a hosted SaaS version where users can pick their own STT provider (BYOK — bring your own key), we'd need runtime switching. For now, config-based is sufficient.

## Notes

**WebSocket protocol summary:**

- **Client → Server:** `start_session`, `audio_chunk` (JSON + binary PCM), `stop_session`
- **Server → Client:** `session_started`, `transcript`, `suggestion`, `session_ended`, `error`
- **Auth:** `Authorization: Bearer <api-key>` required on the handshake (rejected with `1008` otherwise); identity comes from the key

**Suggestion trigger reasons:**

- `silence`: Speaker spoke, User didn't respond in time
- `repeated_question`: Speaker repeated a similar turn (detected via embeddings)
- `filler_words`: User said "um", "uh", "mmm" while timer was running
- `user_question`: User asked a question, Speaker didn't respond

**Configuration knobs:**

- `SUGGESTION_SILENCE_THRESHOLD`: Seconds before calling LLM (default `6.0`)
- `SUGGESTION_SIMILARITY_THRESHOLD`: Cosine similarity threshold for repetition (default `0.6`)
- `SUGGESTION_CONTEXT_SIZE`: Number of recent turns sent to LLM (default `5`)
- `ENABLE_SEMANTIC_SIMILARITY`: Use embeddings instead of text matching (default `false`)

**Switching STT providers:**

Change one line in `.env`:

```env
SPEECH_PROVIDER=deepgram        # or assemblyai, aws_transcribe, whisper_local
```

**Testing:**

```bash
uv run pytest tests/ -v
```

Critical coverage: concurrent sessions don't mix audio, WebSocket rejects missing headers, provider errors are handled gracefully.

**Tech stack:**

FastAPI + Pydantic v2 + asyncio + websockets. STT providers: Deepgram, AssemblyAI, AWS Transcribe, Whisper. LLM providers: OpenAI, Groq, Anthropic. Package manager: `uv`. Tests: `pytest` + `pytest-asyncio`. Linting: `ruff`, `mypy`.

**Related project:**

**[SpeakFlow Desktop](https://github.com/laurasot/speakflow-desktop)** — the Electron app that captures mic + system audio and streams to this API.

**License:**

**[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/)** — free for personal/learning/research, commercial use requires separate license. See [LICENSE](./LICENSE).
