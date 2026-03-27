from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.config import Settings


@dataclass(slots=True)
class CommandResult:
    command: str
    return_code: int
    stdout: str
    stderr: str


class CommandTool:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, command: str) -> CommandResult:
        if not self._settings.enable_local_commands:
            raise PermissionError("Local commands are disabled in configuration.")

        normalized = command.strip()
        if not normalized:
            raise ValueError("Command cannot be empty.")

        if not any(
            normalized.startswith(prefix)
            for prefix in self._settings.allowed_command_prefixes
        ):
            raise PermissionError("Command is not in the allowed prefix list.")

        process = await asyncio.create_subprocess_shell(
            normalized,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        return CommandResult(
            command=normalized,
            return_code=process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace").strip(),
            stderr=stderr_bytes.decode("utf-8", errors="replace").strip(),
        )
