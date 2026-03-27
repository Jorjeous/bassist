# Bassist (personal assistant)

Personal assistant that uses an **LLM** (today wired through **Ollama**), **SQLite** memory, optional **local speech-to-text**, and **chat transports** (Discord, Telegram, or a local terminal). Pieces are **loosely coupled**: you can run the model elsewhere, enable only the transports you need, and leave optional APIs unset.

## Modular layout

| Area | Role |
|------|------|
| **`src/app.py`** | Entry point: wires settings, store, model gateway, speech, and picks a transport. |
| **`src/config.py`** | Environment-backed settings (`pydantic-settings`); paths, model URLs, tokens, persona. |
| **`src/core/`** | `AssistantCore` orchestrates tools, memory, reminders, and LLM calls; `OllamaGateway` talks to `/api/chat` (any Ollama-compatible endpoint). |
| **`src/memory/`** | SQLite store (`store.py`) and consolidation (`consolidator.py`) for notes, todos, interactions, summaries, reminders. |
| **`src/speech/`** | `faster-whisper` transcription for voice (optional per transport). |
| **`src/tools/`** | Web search, weather, travel (Travelpayouts), notes, Google Docs/Drive, safe file read, shell commands (when enabled). |
| **`src/transport/`** | `DiscordAssistantBot`, `TelegramAssistantBot`, or CLI REPL in `app.run_cli`. |

**Model:** Configure `OLLAMA_BASE_URL` and model names in `.env`. That can be a **local** Ollama process or another host on your network that exposes the same HTTP API—no code change required, only configuration.

**Transports:** Each of Discord, Telegram, and CLI is selected at startup (`--transport` or `DEFAULT_TRANSPORT`). You only need the token/env vars for the transport you run; the others can stay empty.

**Optional integrations:** Google OAuth files under `tokens/`, `TRAVELPAYOUTS_TOKEN`, `ENABLE_LOCAL_COMMANDS`, etc. are all optional; the assistant skips or degrades gracefully when they are missing.

## Requirements

- Python **3.11+**
- **[Ollama](https://ollama.com)** (or compatible server) and pulled models matching `.env` (e.g. text + vision models)
- For Discord: bot token and intents as required by `discord.py`
- For Telegram: bot token from BotFather
- For voice: GPU-friendly setup recommended for `faster-whisper` (see `WHISPER_DEVICE` in `.env.example`)

## Quick start

1. **Clone** the repo and enter the project directory.

2. **Create a virtual environment** and install dependencies:

   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\pip install -e .
   # macOS/Linux:
   .venv/bin/pip install -e .
   ```

3. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Edit `.env`: set at least `OLLAMA_BASE_URL`, model names, and the token(s) for the transport you use. Never commit `.env`.

4. **Start Ollama** and pull models (example):

   ```bash
   ollama pull qwen3:8b
   ollama pull qwen2.5vl:7b
   ```

5. **Run**

   - **Local terminal (good for debugging):**

     ```bash
     python -m src.app --transport cli
     ```

   - **Discord:**

     ```bash
     python -m src.app --transport discord
     ```

   - **Telegram:**

     ```bash
     python -m src.app --transport telegram
     ```

   `DEFAULT_TRANSPORT` in `.env` is used if you omit `--transport`.

**Convenience scripts:** `start.bat` (Windows), `start.sh` (macOS/Linux), and `run_assistant.ps1` can create/use `.venv` and launch the app (see script headers for arguments).

## Data and secrets

- Runtime data lives under **`data/`** (ignored by git), including SQLite and generated memory files.
- **`tokens/`** holds Google OAuth client material; keep it out of version control.
- See **CONTRIBUTING.md** for how we keep the public repo free of credentials.

## Contributing

See **CONTRIBUTING.md** for signing commits, local testing expectations, and style checks.
