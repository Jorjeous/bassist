from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.core.assistant import AssistantCore

LOGGER = logging.getLogger(__name__)


class TelegramAssistantBot:
    def __init__(self, token: str, assistant: AssistantCore) -> None:
        self._assistant = assistant
        self._application = Application.builder().token(token).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self._application.add_handler(CommandHandler("notes", self._notes))
        self._application.add_handler(CommandHandler("memories", self._memories))
        self._application.add_handler(MessageHandler(filters.PHOTO, self._photo))
        self._application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._audio))
        self._application.add_handler(MessageHandler(filters.COMMAND, self._command_text))
        self._application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._text))

    async def _notes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None:
            return
        response = await self._assistant.handle_text(str(update.effective_user.id), "/notes")
        await update.message.reply_text(response.text)

    async def _memories(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None:
            return
        response = await self._assistant.handle_text(str(update.effective_user.id), "/memories")
        await update.message.reply_text(response.text)

    async def _text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None or not update.message.text:
            return
        response = await self._assistant.handle_text(
            user_id=str(update.effective_user.id),
            text=update.message.text,
        )
        await update.message.reply_text(response.text)

    async def _command_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None or not update.message.text:
            return
        response = await self._assistant.handle_text(
            user_id=str(update.effective_user.id),
            text=update.message.text,
        )
        await update.message.reply_text(response.text)

    async def _photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None or not update.message.photo:
            return
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        prompt = update.message.caption or "Describe this image."
        response = await self._assistant.handle_image(
            user_id=str(update.effective_user.id),
            prompt=prompt,
            image_bytes=bytes(image_bytes),
        )
        await update.message.reply_text(response.text)

    async def _audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user is None or update.message is None:
            return
        media = update.message.voice or update.message.audio
        if media is None:
            return

        telegram_file = await context.bot.get_file(media.file_id)
        suffix = Path(telegram_file.file_path or "audio.ogg").suffix or ".ogg"

        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_path = Path(tmp_file.name)
        try:
            await telegram_file.download_to_drive(custom_path=str(tmp_path))
            response = await self._assistant.handle_audio(str(update.effective_user.id), tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        text = response.text
        if response.transcript:
            text = f"Transcript: {response.transcript}\n\n{text}"
        await update.message.reply_text(text)

    async def run_bot(self) -> None:
        LOGGER.info("Starting Telegram bot")
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()
        await asyncio.Event().wait()
