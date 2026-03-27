from __future__ import annotations

import platform
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_IS_WINDOWS = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "My Assist"
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    memories_dir: Path = Path("data/memories")
    tokens_dir: Path = Path("tokens")
    sqlite_path: Path = Path("data/assistant.sqlite3")

    default_transport: str = "discord"
    discord_token: str | None = None
    discord_command_prefix: str = "!"
    discord_require_mention_in_guilds: bool = False
    discord_reply_mode: Literal["reply", "send"] = "send"
    discord_min_seconds_between_messages: float = 1.5
    discord_message_dedupe_window_seconds: float = 20.0
    telegram_token: str | None = None

    ollama_base_url: str = "http://127.0.0.1:11434"
    text_model: str = "qwen3:8b"
    vision_model: str = "qwen2.5vl:7b"
    request_timeout_seconds: float = 120.0
    model_temperature: float = 0.3
    max_context_messages: int = 20
    reminder_poll_interval_seconds: float = 5.0
    english_fix_mode: bool = True

    whisper_model: str = "small"
    whisper_device: str = "mps" if _IS_MAC else "cuda"
    whisper_compute_type: str = "float16"

    web_region: str = "wt-wt"
    web_results_limit: int = 5

    travelpayouts_token: str | None = None

    google_credentials_file: Path = Path("tokens/google_credentials.json")
    google_token_file: Path = Path("tokens/google_token.json")
    google_oauth_scopes: list[str] = Field(
        default_factory=lambda: [
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
        ]
    )

    enable_local_commands: bool = False
    allowed_command_prefixes: list[str] = Field(
        default_factory=lambda: (
            ["dir", "Get-ChildItem", "python"]
            if _IS_WINDOWS
            else ["ls", "cat", "python3", "python"]
        )
    )

    system_prompt: str = (
        "You are a personal assistant running on a Discord server with multiple users. "
        "You HAVE and ACTIVELY USE these capabilities (never deny having them):\n"
        "- Set reminders for any time interval (the system parses and delivers them automatically)\n"
        "- Check current weather for any city (done automatically via web search)\n"
        "- Create and list notes, todo items, and long-term memories you persist across sessions\n"
        "- Search the web automatically for factual questions (deep search reads full pages)\n"
        "- Translate between Russian, English, and Armenian\n"
        "- Process and describe images\n"
        "- Store and recall memory summaries (day/week/month) of past conversations as persistent text files\n"
        "- Read your own memory files from disk (day, week, month summaries stored as .txt files)\n"
        "- Work with Google Docs and Drive\n"
        "- Search multi-modal travel routes (flights, buses, trains) with cost/time optimization\n\n"
        "MULTI-USER AWARENESS:\n"
        "- You serve multiple users on the same Discord server.\n"
        "- Each message is prefixed with the sender's username in [brackets].\n"
        "- You maintain SEPARATE memory and conversation history for each user.\n"
        "- You also have SHARED memory visible to all users (facts stored via /remember_shared).\n"
        "- When answering, address the specific user who asked. Use their name naturally.\n"
        "- You are aware of which Discord channel (#channel-name) you are in.\n"
        "- Messages from users talking to each other (not to you) are logged as observations; "
        "use them for context but do not reply to them.\n\n"
        "IMPORTANT RULES:\n"
        "- NEVER say you cannot do something that is listed above.\n"
        "- NEVER say you lack access to web, weather, memory, or reminders -- you have all of these.\n"
        "- NEVER say your memory is limited to the current session -- you store memories permanently.\n"
        "- When memory data, web search results, or weather data are provided in context, USE them directly.\n"
        "- When the user asks about memories, look at the 'Retrieved memory data' in context and cite it.\n"
        "- Be concise, calm, and professional.\n"
        "- Do NOT use emojis.\n"
        "- Avoid saccharine, overly enthusiastic, or chatty phrasing.\n"
        "- ABSOLUTELY FORBIDDEN: follow-up questions, offers to help, or prompts like:\n"
        "  'Would you like...', 'Let me know if...', 'Can I help with...', 'How can I assist...'\n"
        "  'Is there anything else...', 'Do you want me to...', 'Please specify...'\n"
        "  Just answer. Stop after the answer. Do not ask what to do next.\n"
        "- NEVER echo or repeat the user's message back. Do not start your reply with the user's question.\n"
        "- Do not use *italics* to restate what the user said.\n"
        "- Use the conversation history as context. Answer follow-up questions consistently."
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
