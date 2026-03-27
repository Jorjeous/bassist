from __future__ import annotations

from src.memory.store import MemoryStore


class NotesTodoTool:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def create_note(self, user_id: str, title: str, content: str) -> str:
        note = self._store.add_note(user_id=user_id, title=title, content=content)
        return f"Saved note #{note.id}: {note.title}"

    def list_notes(self, user_id: str) -> str:
        notes = self._store.list_notes(user_id=user_id)
        if not notes:
            return "No notes saved yet."
        return "\n".join(f"{note.id}. {note.title} - {note.created_at}" for note in notes)

    def add_todo(self, user_id: str, text: str) -> str:
        todo = self._store.add_todo(user_id=user_id, text=text)
        return f"Added todo #{todo.id}: {todo.text}"

    def list_todos(self, user_id: str, include_done: bool = True) -> str:
        todos = self._store.list_todos(user_id=user_id, include_done=include_done)
        if not todos:
            return "No todo items yet."
        lines = []
        for todo in todos:
            status = "done" if todo.done else "open"
            lines.append(f"{todo.id}. [{status}] {todo.text}")
        return "\n".join(lines)

    def complete_todo(self, todo_id: int) -> str:
        todo = self._store.complete_todo(todo_id)
        return f"Completed todo #{todo.id}: {todo.text}"

    def remember(self, user_id: str, fact: str) -> str:
        memory = self._store.remember(user_id=user_id, fact=fact)
        return f"Remembered item #{memory.id}: {memory.fact}"

    def list_memories(self, user_id: str) -> str:
        memories = self._store.list_memories(user_id=user_id)
        if not memories:
            return "No long-term memories recorded yet."
        return "\n".join(f"{memory.id}. {memory.fact}" for memory in memories)
