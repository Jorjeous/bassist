from __future__ import annotations

from pathlib import Path


class FileReaderTool:
    """Read files from a set of whitelisted directories with path traversal protection."""

    def __init__(self, allowed_dirs: list[Path]) -> None:
        self._allowed_dirs = [d.resolve() for d in allowed_dirs]

    def _check_allowed(self, path: Path) -> Path:
        resolved = path.resolve()
        for allowed in self._allowed_dirs:
            if resolved == allowed or allowed in resolved.parents:
                return resolved
        raise PermissionError(
            f"Access denied: {path} is not under any allowed directory."
        )

    def read_file(self, path: str) -> str:
        target = self._check_allowed(Path(path))
        if not target.exists():
            return f"File not found: {path}"
        if not target.is_file():
            return f"Not a file: {path}"
        try:
            return target.read_text(encoding="utf-8")
        except Exception as exc:
            return f"Error reading {path}: {exc}"

    def list_files(self, directory: str) -> str:
        target = self._check_allowed(Path(directory))
        if not target.exists():
            return f"Directory not found: {directory}"
        if not target.is_dir():
            return f"Not a directory: {directory}"
        entries: list[str] = []
        for item in sorted(target.iterdir()):
            suffix = "/" if item.is_dir() else ""
            entries.append(f"{item.name}{suffix}")
        if not entries:
            return "Directory is empty."
        return "\n".join(entries)
