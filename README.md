# ULTRON P1

A local AI assistant with a heads-up display, running against Ollama for reasoning
and ElevenLabs for voice output.

## Architecture

Input flows through a fixed pipeline, and the security layers come *before* the model:

```
microphone -> /transcribe (local Whisper)  ─┐
                                            ├─> raw input
browser text box ───────────────────────────┘
  -> InputSanitizer   NFKC normalize, strip control/invisible chars, length caps
  -> memory commands  "remember: X" / "forget: X" handled directly
  -> ReflexRouter     exact token match -> deterministic Tier 0 tool (no LLM)
  -> PermissionGate   tool tier must be in settings.ALLOWED_TIERS
  -> Deep Core        Ollama fallback for anything unmatched
  -> ElevenLabs TTS   spoken reply
```

Every decision is appended to `logs/audit.jsonl` as one JSON object per line.

| Module | Role |
| --- | --- |
| `src/security/sanitizer.py` | Input normalization, output ANSI stripping |
| `src/security/audit.py` | JSONL audit trail |
| `src/core/router.py` | Exact-match intent routing |
| `src/core/history.py` | Conversation window + system-context injection |
| `src/core/memory.py` | SQLite fact store |
| `src/tools/registry.py` | Tool registry and tier-based permission gate |
| `src/tools/p1_tools.py` | Tier 0 tools (clock, telemetry) |
| `src/tools/tier1_tools.py` | Tier 1 tools (read-only filesystem) |
| `src/tools/fs_sandbox.py` | Path confinement for Tier 1 |
| `src/voice/stt.py` | Local speech-to-text (faster-whisper) |
| `src/server.py` | FastAPI HUD + STT + TTS |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Put your ElevenLabs credentials in `.env`. **`.env` is gitignored — never hardcode
keys in source.** Voice output is skipped automatically if the keys are absent;
everything else still works.

You also need [Ollama](https://ollama.com) running locally with the model pulled:

```bash
ollama pull llama3.2
```

## Running

HUD (browser at http://127.0.0.1:8000):

```bash
uvicorn src.server:app --reload
```

CLI only:

```bash
python -m src.main
```

## Tests

```bash
pytest tests -q
```

`tests/test_p1.py` covers components in isolation. `tests/test_integration.py`
covers the seams — full `process_input` round trips, memory isolation, and the
HTTP surface. Add new coverage at the integration level; that is where the real
bugs have shown up.

## Commands

Tier 0 is exact-match and instant. Tier 1 takes an argument and uses an
explicit `verb: argument` grammar, the same shape as the memory commands.

```
help / time / date / day / status / system status / cpu / ram

list: src/voice          contents of a directory
read: src/main.py        contents of a text file
find: *.py               filenames matching a glob
search: def process      find text inside project files
tree:                    project layout

remember: <fact>
forget: <keyword>
```

The colon is required. A bare leading verb stays conversational, so
"read me something" reaches Deep Core rather than being parsed as a file read
— routing is unambiguous rather than best-guess.

## Tier 1 filesystem access

Read-only, confined to `TOOL_ROOT` (the project directory by default). Nothing
writes, deletes, moves, or executes.

Every path goes through `fs_sandbox.resolve_path()`, which rejects absolute
paths, drive letters, UNC paths, traversal that escapes the root, and symlinks
or junctions pointing outside. Containment is enforced by resolving the path
and checking it against the root with a separator-aware, case-normalised
comparison — not by pattern-matching for `..`.

Denied even inside the root: `.env` and friends, `*.key`/`*.pem`, `*.db`,
`.git/`, `.venv/`, `node_modules/`. Reads are capped at 100KB and 300 lines,
and binary files are refused.

The threat model is not only the user. Deep Core sees stored memories and its
own prior turns, both attacker-influenceable, so tool arguments are treated as
hostile input regardless of where they came from.

To turn Tier 1 off entirely:

```
ALLOWED_TIERS=[0]
```

The permission gate, not the router, is the enforcement point — so that single
change disables every file tool at once.

## Voice input

Click **SPEAK** (or press **Ctrl+Space**) and talk. Recording stops automatically
about 1.5s after you stop speaking, or click STOP. The core animation is driven
by your real microphone level while listening.

Audio is captured by the browser, POSTed to `/transcribe`, and transcribed by
faster-whisper **on this machine**. Nothing is sent to a speech cloud service.

Device selection is automatic: GPU first (`distil-large-v3`, float16), falling
back to CPU (`base.en`, int8) if CUDA is unavailable. Override in `.env`:

```
STT_DEVICE=cpu          # auto | cuda | cpu
STT_MODEL_GPU=large-v3
STT_MODEL_CPU=small.en
```

The model downloads from HuggingFace on first use (~1.5GB for distil-large-v3)
and is cached in `~/.cache/huggingface`. It is warmed in a background thread at
server startup so the first utterance is not charged the load time.

### GPU notes

CTranslate2 needs cuBLAS and cuDNN. Those come from the `nvidia-cublas-cu12`
and `nvidia-cudnn-cu12` pip packages, whose DLLs are not on `PATH` —
`src/voice/stt.py` registers them with the Windows loader at load time. If GPU
init fails for any reason, transcription silently uses CPU rather than erroring.

## Security notes

- Tools are tiered. P1 policy allows Tier 0 only (read-only, no side effects).
  Anything that touches the filesystem, shell, or network must be Tier 1+ and
  will be denied by `PermissionGate` until the policy is deliberately widened.
- Stored memories are user-supplied data. They are injected into the **system**
  message inside explicit fences and marked as non-instructions, so a stored
  string cannot act as a persistent prompt injection.
- Static files are served by Starlette's `StaticFiles`, which confines paths.
  Do not replace it with a hand-rolled path handler.

- Speech audio is processed locally and never written to disk.

## Not built yet

- **Tier 2 tools.** Nothing writes, deletes, moves, or executes. Any such tool
  belongs at Tier 2 and must not be enabled by default.
- **Wake word.** Voice input is push-to-talk; there is no always-on listener.
