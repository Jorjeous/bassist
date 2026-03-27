from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.config import Settings

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.DOTALL)


@dataclass(slots=True)
class MessagePart:
    role: str
    content: str


@dataclass(slots=True)
class ImageInput:
    data: bytes
    mime_type: str = "image/png"

    def to_base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass(slots=True)
class ModelRequest:
    messages: list[MessagePart]
    images: list[ImageInput] = field(default_factory=list)
    temperature: float | None = None


class OllamaGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=settings.request_timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def generate_text(self, request: ModelRequest) -> str:
        return await self._chat(model=self._settings.text_model, request=request)

    async def generate_vision(self, request: ModelRequest) -> str:
        return await self._chat(model=self._settings.vision_model, request=request)

    async def healthcheck(self) -> dict[str, Any]:
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        return response.json()

    async def _chat(self, model: str, request: ModelRequest) -> str:
        payload = {
            "model": model,
            "stream": False,
            "options": {
                "temperature": (
                    request.temperature
                    if request.temperature is not None
                    else self._settings.model_temperature
                )
            },
            "messages": [],
        }

        for message in request.messages:
            entry: dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }
            if request.images and message.role == "user":
                entry["images"] = [image.to_base64() for image in request.images]
            payload["messages"].append(entry)

        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        raw = data.get("message", {}).get("content", "")
        return _THINK_RE.sub("", raw).strip()
