from __future__ import annotations

import argparse
import asyncio
import logging

from src.config import get_settings
from src.core.assistant import AssistantCore
from src.core.models import OllamaGateway
from src.memory.store import MemoryStore
from src.speech.transcribe import SpeechToTextService
from src.transport.discord_bot import DiscordAssistantBot
from src.transport.telegram_bot import TelegramAssistantBot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the personal assistant.")
    parser.add_argument(
        "--transport",
        choices=["discord", "telegram", "cli"],
        default=None,
        help="Select which bot adapter to run.",
    )
    return parser.parse_args()


async def main() -> None:
    settings = get_settings()
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    store = MemoryStore(settings.sqlite_path)
    model_gateway = OllamaGateway(settings)
    speech_service = SpeechToTextService(settings)
    assistant = AssistantCore(
        settings=settings,
        store=store,
        model_gateway=model_gateway,
        speech_service=speech_service,
    )

    transport = args.transport or settings.default_transport
    try:
        if transport == "cli":
            await run_cli(assistant, settings)
            return

        if transport == "discord":
            if not settings.discord_token:
                raise RuntimeError("Set DISCORD_TOKEN in the environment or .env file.")
            bot = DiscordAssistantBot(
                token=settings.discord_token,
                prefix=settings.discord_command_prefix,
                assistant=assistant,
            )
            await bot.run_bot()
            return

        if transport == "telegram":
            if not settings.telegram_token:
                raise RuntimeError("Set TELEGRAM_TOKEN in the environment or .env file.")
            bot = TelegramAssistantBot(token=settings.telegram_token, assistant=assistant)
            await bot.run_bot()
            return

        raise RuntimeError(f"Unsupported transport: {transport}")
    finally:
        await model_gateway.close()


async def run_cli(assistant: AssistantCore, settings) -> None:
    """Interactive terminal REPL -- like a local Codex-style assistant."""
    import os
    import sys
    import time
    import threading

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if sys.platform == "win32":
        os.system("")  # enable ANSI escape codes on Windows 10+

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    DIM = "\033[2m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"

    user_id = "cli_user"
    username = os.environ.get("USERNAME") or os.environ.get("USER") or "user"

    def out(text: str) -> None:
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            print(text.encode("utf-8", errors="replace").decode("ascii", errors="replace"), flush=True)

    def banner() -> None:
        out(f"\n{BOLD}{CYAN}{'=' * 56}{RESET}")
        out(f"{BOLD}{CYAN}  My Assistant  --  Local Terminal Mode{RESET}")
        out(f"{BOLD}{CYAN}{'=' * 56}{RESET}")
        out(f"{DIM}  Model    : {settings.text_model}{RESET}")
        out(f"{DIM}  Ollama   : {settings.ollama_base_url}{RESET}")
        out(f"{DIM}  User     : {username}{RESET}")
        out(f"{DIM}  English fix: {'on' if settings.english_fix_mode else 'off'}{RESET}")
        out("")
        out(f"{DIM}  Commands:{RESET}")
        out(f"{DIM}    /help            show all commands{RESET}")
        out(f"{DIM}    /smartsearch Q   deep web search{RESET}")
        out(f"{DIM}    /travel A to B   multi-modal travel{RESET}")
        out(f"{DIM}    /quit            exit{RESET}")
        out(f"{DIM}  Or just type naturally to chat.{RESET}")
        out("")

    def show_help() -> None:
        cmds = [
            ("/note title | body", "Create a note"),
            ("/notes", "List notes"),
            ("/todo add <text>", "Add a todo"),
            ("/todo list", "List todos"),
            ("/remember <fact>", "Store personal memory"),
            ("/remember_shared <fact>", "Store shared memory"),
            ("/memories", "List memories"),
            ("/web <query>", "Quick web search"),
            ("/smartsearch <query>", "Deep search + reliability"),
            ("/travel A to B [date]", "Multi-modal travel search"),
            ("/weather [city]", "Weather lookup"),
            ("/english on|off", "Toggle English correction"),
            ("/reminders", "Show pending reminders"),
            ("/quit", "Exit"),
        ]
        out(f"\n{BOLD}Available commands:{RESET}")
        for cmd, desc in cmds:
            out(f"  {GREEN}{cmd:<28}{RESET} {DIM}{desc}{RESET}")
        out("")

    class Spinner:
        _FRAMES = ["-", "\\", "|", "/"]

        def __init__(self) -> None:
            self._running = False
            self._thread: threading.Thread | None = None

        def start(self, label: str = "Thinking") -> None:
            self._running = True
            def _spin() -> None:
                i = 0
                while self._running:
                    frame = self._FRAMES[i % len(self._FRAMES)]
                    try:
                        print(f"\r{DIM}{frame} {label}...{RESET}  ", end="", flush=True)
                    except (UnicodeEncodeError, OSError):
                        pass
                    time.sleep(0.1)
                    i += 1
                try:
                    print("\r" + " " * 40 + "\r", end="", flush=True)
                except (UnicodeEncodeError, OSError):
                    pass
            self._thread = threading.Thread(target=_spin, daemon=True)
            self._thread.start()

        def stop(self) -> None:
            self._running = False
            if self._thread:
                self._thread.join(timeout=1)

    spinner = Spinner()
    reminder_running = True

    async def reminder_checker() -> None:
        while reminder_running:
            due = assistant.get_due_reminders("cli")
            for r in due:
                out(f"\n{YELLOW}  [REMINDER] {r.text}{RESET}")
                assistant.mark_reminder_delivered(r.id)
            await asyncio.sleep(settings.reminder_poll_interval_seconds)

    banner()
    reminder_task = asyncio.create_task(reminder_checker())

    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                line = await loop.run_in_executor(
                    None, lambda: input(f"{GREEN}{username}{RESET} {BOLD}>{RESET} "),
                )
            except (EOFError, KeyboardInterrupt):
                out(f"\n{DIM}Goodbye.{RESET}")
                break

            line = line.strip()
            if not line:
                continue
            if line.lower() in {"/quit", "/exit", "quit", "exit"}:
                out(f"{DIM}Goodbye.{RESET}")
                break
            if line.lower() in {"/help", "help", "?"}:
                show_help()
                continue
            if line.lower() == "/reminders":
                with assistant._store._connect() as conn:
                    rows = conn.execute(
                        "SELECT id, text, due_at, delivered FROM reminders "
                        "WHERE transport='cli' ORDER BY due_at"
                    ).fetchall()
                if not rows:
                    out(f"  {DIM}No CLI reminders.{RESET}")
                else:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc).isoformat()
                    for row in rows:
                        if row[3]:
                            tag = f"{DIM}delivered{RESET}"
                        elif row[2] <= now:
                            tag = f"{YELLOW}due{RESET}"
                        else:
                            tag = f"{CYAN}pending{RESET}"
                        out(f"  [{tag}] #{row[0]}: {row[1]} (due: {row[2]})")
                continue

            spinner.start()
            try:
                response = await assistant.handle_text(
                    user_id=user_id,
                    text=line,
                    transport="cli",
                    destination_id="terminal",
                    username=username,
                    channel_name="terminal",
                )
            finally:
                spinner.stop()

            out(f"\n{CYAN}assistant{RESET} {BOLD}>{RESET} {response.text}\n")
    finally:
        reminder_running = False
        reminder_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
