from __future__ import annotations

import asyncio
import logging
import time
from time import monotonic
from pathlib import Path
from tempfile import NamedTemporaryFile

import discord
from discord import app_commands
from discord.ext import commands

from src.core.assistant import AssistantCore
from src.memory.store import ReminderRecord

LOGGER = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".webm", ".mp4"}

_LAST_CONNECT_FILE = Path(__file__).resolve().parent.parent.parent / ".last_discord_connect"
_MIN_RESTART_GAP_SECONDS = 30


class DiscordAssistantBot(commands.Bot):
    def __init__(self, token: str, prefix: str, assistant: AssistantCore) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=prefix, intents=intents)
        self._token = token
        self._assistant = assistant
        self._settings = assistant._settings
        self._require_mention_in_guilds = self._settings.discord_require_mention_in_guilds
        self._reply_mode = self._settings.discord_reply_mode
        self._send_lock = asyncio.Lock()
        self._last_send_at = 0.0
        self._processed_message_ids: dict[int, float] = {}
        self._reminder_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        @self.tree.command(name="note", description="Create a note with 'title | content'")
        @app_commands.describe(payload="Use the format: title | content")
        async def note_slash(interaction: discord.Interaction, payload: str) -> None:
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/note {payload}",
            )
            await interaction.response.send_message(response.text)

        @self.tree.command(name="notes", description="List your saved notes")
        async def notes_slash(interaction: discord.Interaction) -> None:
            response = await self._assistant.handle_text(str(interaction.user.id), "/notes")
            await interaction.response.send_message(response.text)

        @self.tree.command(name="todo_add", description="Add a todo item")
        async def todo_add_slash(interaction: discord.Interaction, text: str) -> None:
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/todo add {text}",
            )
            await interaction.response.send_message(response.text)

        @self.tree.command(name="todo_list", description="List your todo items")
        async def todo_list_slash(interaction: discord.Interaction) -> None:
            response = await self._assistant.handle_text(str(interaction.user.id), "/todo list")
            await interaction.response.send_message(response.text)

        @self.tree.command(name="remember", description="Store a long-term memory fact")
        async def remember_slash(interaction: discord.Interaction, fact: str) -> None:
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/remember {fact}",
            )
            await interaction.response.send_message(response.text)

        @self.tree.command(name="web", description="Search the web")
        async def web_slash(interaction: discord.Interaction, query: str) -> None:
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/web {query}",
                transport="discord",
                destination_id=str(interaction.channel_id),
            )
            await interaction.response.send_message(response.text[:2000])

        @self.tree.command(name="remind", description="Set a reminder")
        async def remind_slash(interaction: discord.Interaction, delay: str, text: str) -> None:
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/remind {delay} | {text}",
                transport="discord",
                destination_id=str(interaction.channel_id),
            )
            await interaction.response.send_message(response.text)

        @self.command(name="note")
        async def note_command(ctx: commands.Context, *, payload: str) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/note {payload}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.command(name="notes")
        async def notes_command(ctx: commands.Context) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                "/notes",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.command(name="todo")
        async def todo_command(ctx: commands.Context, *, payload: str) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/todo {payload}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.command(name="remember")
        async def remember_command(ctx: commands.Context, *, fact: str) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/remember {fact}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.command(name="web")
        async def web_command(ctx: commands.Context, *, query: str) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/web {query}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.command(name="remind")
        async def remind_command(ctx: commands.Context, *, payload: str) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/remind {payload}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.tree.command(name="memory", description="View memory summary for a period")
        @app_commands.describe(period="day, week, or month", ref_date="Optional date (YYYY-MM-DD)")
        async def memory_slash(
            interaction: discord.Interaction, period: str, ref_date: str | None = None,
        ) -> None:
            payload = period if ref_date is None else f"{period} {ref_date}"
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/memory {payload}",
            )
            await interaction.response.send_message(response.text[:2000])

        @self.tree.command(name="weather", description="Check weather for a city")
        @app_commands.describe(city="City name")
        async def weather_slash(interaction: discord.Interaction, city: str) -> None:
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/weather {city}",
            )
            await interaction.response.send_message(response.text[:2000])

        @self.command(name="memory")
        async def memory_command(ctx: commands.Context, *, payload: str = "day") -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/memory {payload}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.command(name="weather")
        async def weather_command(ctx: commands.Context, *, city: str) -> None:
            response = await self._assistant.handle_text(
                str(ctx.author.id),
                f"/weather {city}",
                transport="discord",
                destination_id=str(ctx.channel.id),
            )
            await self._send_context_response(ctx, response.text)

        @self.tree.command(name="smartsearch", description="Deep web search with reliability assessment")
        @app_commands.describe(query="What to search for")
        async def smartsearch_slash(interaction: discord.Interaction, query: str) -> None:
            await interaction.response.defer()
            ctx_info = self._interaction_context(interaction)
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/smartsearch {query}",
                transport="discord",
                destination_id=str(interaction.channel_id),
                **ctx_info,
            )
            for chunk in self._split_message(response.text):
                await interaction.followup.send(chunk)

        @self.command(name="smartsearch")
        async def smartsearch_command(ctx: commands.Context, *, query: str) -> None:
            async with ctx.channel.typing():
                response = await self._assistant.handle_text(
                    str(ctx.author.id),
                    f"/smartsearch {query}",
                    transport="discord",
                    destination_id=str(ctx.channel.id),
                )
            await self._send_context_response(ctx, response.text)

        @self.tree.command(name="travel", description="Search multi-modal travel routes")
        @app_commands.describe(
            origin="Origin city",
            destination="Destination city",
            date="Travel date (DD/MM/YYYY, optional)",
        )
        async def travel_slash(
            interaction: discord.Interaction,
            origin: str,
            destination: str,
            date: str | None = None,
        ) -> None:
            await interaction.response.defer()
            ctx_info = self._interaction_context(interaction)
            date_part = f" {date}" if date else ""
            response = await self._assistant.handle_text(
                str(interaction.user.id),
                f"/travel {origin} to {destination}{date_part}",
                transport="discord",
                destination_id=str(interaction.channel_id),
                **ctx_info,
            )
            for chunk in self._split_message(response.text):
                await interaction.followup.send(chunk)

        @self.command(name="travel")
        async def travel_command(ctx: commands.Context, *, payload: str) -> None:
            async with ctx.channel.typing():
                response = await self._assistant.handle_text(
                    str(ctx.author.id),
                    f"/travel {payload}",
                    transport="discord",
                    destination_id=str(ctx.channel.id),
                )
            await self._send_context_response(ctx, response.text)

        @self.tree.command(name="history", description="Fetch and summarize recent channel messages")
        @app_commands.describe(
            count="Number of messages to fetch (default 50, max 200)",
            summarize="Summarize via LLM instead of raw text (default true)",
        )
        async def history_slash(
            interaction: discord.Interaction,
            count: int = 50,
            summarize: bool = True,
        ) -> None:
            await interaction.response.defer()
            text = await self._fetch_channel_history(
                interaction.channel, count, str(interaction.user.id), summarize,
            )
            for chunk in self._split_message(text):
                await interaction.followup.send(chunk)

        @self.command(name="history")
        async def history_command(ctx: commands.Context, count: int = 50) -> None:
            async with ctx.channel.typing():
                text = await self._fetch_channel_history(
                    ctx.channel, count, str(ctx.author.id), summarize=True,
                )
            await self._send_context_response(ctx, text)

        await self.tree.sync()
        self._reminder_task = asyncio.create_task(self._reminder_loop())

    async def on_ready(self) -> None:
        LOGGER.info("Discord bot logged in as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        try:
            if message.author.bot:
                return

            self._expire_processed_messages()
            if message.id in self._processed_message_ids:
                return
            self._processed_message_ids[message.id] = monotonic()

            await self.process_commands(message)
            if message.content.startswith(self.command_prefix):
                return

            user_id = str(message.author.id)
            username = message.author.display_name or message.author.name
            channel_name = getattr(message.channel, "name", "DM") or "DM"

            if self._mentions_other_user(message):
                self._assistant.log_observation(
                    user_id=user_id,
                    text=message.clean_content.strip(),
                    username=username,
                    channel_name=channel_name,
                )
                return

            if message.guild and not self._should_auto_reply(message):
                return

            async with message.channel.typing():
                if message.attachments:
                    handled = await self._handle_attachments(message, user_id)
                    if handled:
                        return

                prompt = message.clean_content.strip() or message.content
                if self.user:
                    bot_mention = f"@{self.user.display_name}"
                    prompt = prompt.replace(bot_mention, "").strip()
                response = await self._assistant.handle_text(
                    user_id=user_id,
                    text=prompt,
                    transport="discord",
                    destination_id=str(message.channel.id),
                    username=username,
                    channel_name=channel_name,
                )
                await self._send_message_response(message, response.text)
        except Exception:
            LOGGER.exception("Unhandled error processing message %s", message.id)

    @staticmethod
    def _interaction_context(interaction: discord.Interaction) -> dict[str, str]:
        """Extract username and channel_name from a slash-command interaction."""
        user = interaction.user
        ch = interaction.channel
        return {
            "username": getattr(user, "display_name", None) or user.name,
            "channel_name": getattr(ch, "name", "DM") or "DM",
        }

    def _should_auto_reply(self, message: discord.Message) -> bool:
        if self.user in message.mentions or message.attachments:
            return True

        if not self._require_mention_in_guilds:
            return True

        channel_members = getattr(message.channel, "members", None)
        if channel_members is None:
            return False

        human_members = [member for member in channel_members if not member.bot]
        return len(human_members) == 1

    def _mentions_other_user(self, message: discord.Message) -> bool:
        """True if the message @mentions a human (not the bot). Means user-to-user talk."""
        if not message.mentions:
            return False
        for mentioned in message.mentions:
            if mentioned.bot:
                continue
            if self.user and mentioned.id == self.user.id:
                continue
            return True
        return False

    async def _handle_attachments(self, message: discord.Message, user_id: str) -> bool:
        for attachment in message.attachments:
            extension = Path(attachment.filename).suffix.lower()

            if extension in IMAGE_EXTENSIONS:
                image_bytes = await attachment.read()
                prompt = message.clean_content.strip() or "Describe this image and answer anything useful."
                response = await self._assistant.handle_image(
                    user_id=user_id,
                    prompt=prompt,
                    image_bytes=image_bytes,
                )
                await self._send_message_response(message, response.text)
                return True

            if extension in AUDIO_EXTENSIONS:
                with NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                    tmp_file.write(await attachment.read())
                try:
                    response = await self._assistant.handle_audio(
                        user_id=user_id,
                        audio_path=tmp_path,
                        transport="discord",
                        destination_id=str(message.channel.id),
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)

                text = response.text
                if response.transcript:
                    text = f"Transcript: {response.transcript}\n\n{text}"
                await self._send_message_response(message, text)
                return True

        return False

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        LOGGER.exception("Command error in %s: %s", ctx.command, error)
        try:
            await ctx.send("Something went wrong processing that command.")
        except discord.HTTPException:
            pass

    async def _fetch_channel_history(
        self,
        channel: discord.abc.Messageable,
        count: int,
        user_id: str,
        summarize: bool,
    ) -> str:
        count = max(1, min(count, 200))
        messages: list[discord.Message] = []
        async for msg in channel.history(limit=count):
            messages.append(msg)
        messages.reverse()

        if not messages:
            return "No messages found in this channel."

        lines: list[str] = []
        for msg in messages:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
            author = msg.author.display_name
            content = msg.clean_content or "(attachment/embed)"
            lines.append(f"[{ts}] {author}: {content}")
        raw_history = "\n".join(lines)

        if not summarize:
            return f"Channel history ({len(messages)} messages):\n\n{raw_history}"

        response = await self._assistant.handle_text(
            user_id=user_id,
            text=f"/summarize_history\n{raw_history}",
            transport="discord",
            destination_id=str(getattr(channel, "id", "")),
        )
        return response.text

    async def _reminder_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                reminders = self._assistant.get_due_reminders("discord")
                for reminder in reminders:
                    delivered = await self._deliver_reminder(reminder)
                    if delivered:
                        self._assistant.mark_reminder_delivered(reminder.id)
            except Exception:
                LOGGER.exception("Error in reminder loop iteration")
            await asyncio.sleep(self._settings.reminder_poll_interval_seconds)

    async def _deliver_reminder(self, reminder: ReminderRecord) -> bool:
        channel = self.get_channel(int(reminder.destination_id))
        if channel is None:
            try:
                channel = await self.fetch_channel(int(reminder.destination_id))
            except discord.DiscordException:
                LOGGER.warning("Could not resolve reminder channel %s", reminder.destination_id)
                return False

        return await self._send_payload(channel, f"Reminder: {reminder.text}", reference=None)

    async def _send_context_response(self, ctx: commands.Context, text: str) -> None:
        ref = ctx.message if self._reply_mode == "reply" else None
        for chunk in self._split_message(text):
            await self._send_payload(ctx.channel, chunk, reference=ref)
            ref = None

    async def _send_message_response(self, message: discord.Message, text: str) -> None:
        ref = message if self._reply_mode == "reply" else None
        for chunk in self._split_message(text):
            await self._send_payload(message.channel, chunk, reference=ref)
            ref = None

    @staticmethod
    def _split_message(text: str, max_len: int = 1900) -> list[str]:
        if len(text) <= max_len:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_at = text.rfind("\n\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind(" ", 0, max_len)
            if split_at == -1:
                split_at = max_len
            chunks.append(text[:split_at].rstrip())
            text = text[split_at:].lstrip()
        return chunks

    async def _send_payload(
        self,
        channel: discord.abc.Messageable,
        text: str,
        *,
        reference: discord.Message | None,
    ) -> bool:
        if not text.strip():
            return False

        async with self._send_lock:
            wait_seconds = self._settings.discord_min_seconds_between_messages - (
                monotonic() - self._last_send_at
            )
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            try:
                await channel.send(
                    text,
                    reference=reference,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                self._last_send_at = monotonic()
                return True
            except discord.HTTPException as exc:
                LOGGER.warning("Discord send failed with status %s", getattr(exc, "status", "unknown"))
                return False

    def _expire_processed_messages(self) -> None:
        cutoff = monotonic() - self._settings.discord_message_dedupe_window_seconds
        stale_ids = [
            message_id
            for message_id, processed_at in self._processed_message_ids.items()
            if processed_at < cutoff
        ]
        for message_id in stale_ids:
            self._processed_message_ids.pop(message_id, None)

    async def run_bot(self) -> None:
        self._enforce_startup_cooldown()
        try:
            await self.start(self._token)
        finally:
            if self._reminder_task is not None:
                self._reminder_task.cancel()

    @staticmethod
    def _enforce_startup_cooldown() -> None:
        now = time.time()
        if _LAST_CONNECT_FILE.exists():
            try:
                last = float(_LAST_CONNECT_FILE.read_text().strip())
                elapsed = now - last
                if elapsed < _MIN_RESTART_GAP_SECONDS:
                    wait = _MIN_RESTART_GAP_SECONDS - elapsed
                    LOGGER.warning(
                        "Last Discord connect was %.0fs ago. "
                        "Waiting %.0fs to avoid rate-limit...",
                        elapsed, wait,
                    )
                    time.sleep(wait)
            except (ValueError, OSError):
                pass
        _LAST_CONNECT_FILE.write_text(str(now))
