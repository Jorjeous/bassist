from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel

from src.config import Settings


class SpeechToTextService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self._settings.whisper_model,
                device=self._settings.whisper_device,
                compute_type=self._settings.whisper_compute_type,
            )
        return self._model

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        model = self._get_model()
        segments, _ = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        return transcript or "I could not detect speech in the audio."
