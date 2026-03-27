from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class NoteRecord:
    id: int
    user_id: str
    title: str
    content: str
    created_at: str


@dataclass(slots=True)
class TodoRecord:
    id: int
    user_id: str
    text: str
    done: bool
    created_at: str


@dataclass(slots=True)
class MemoryRecord:
    id: int
    user_id: str
    fact: str
    created_at: str


@dataclass(slots=True)
class ReminderRecord:
    id: int
    user_id: str
    transport: str
    destination_id: str
    text: str
    due_at: str
    delivered: bool
    created_at: str


@dataclass(slots=True)
class MemorySummaryRecord:
    id: int
    user_id: str
    period: str
    period_start: str
    period_end: str
    summary: str
    created_at: str


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS memory_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def add_note(self, user_id: str, title: str, content: str) -> NoteRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO notes (user_id, title, content) VALUES (?, ?, ?)",
                (user_id, title.strip(), content.strip()),
            )
            note_id = int(cursor.lastrowid)
        return self.get_note(note_id)

    def get_note(self, note_id: int) -> NoteRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, user_id, title, content, created_at FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown note id: {note_id}")
        return NoteRecord(**dict(row))

    def list_notes(self, user_id: str, limit: int = 10) -> list[NoteRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, content, created_at
                FROM notes
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [NoteRecord(**dict(row)) for row in rows]

    def add_todo(self, user_id: str, text: str) -> TodoRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO todos (user_id, text) VALUES (?, ?)",
                (user_id, text.strip()),
            )
            todo_id = int(cursor.lastrowid)
        return self.get_todo(todo_id)

    def get_todo(self, todo_id: int) -> TodoRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, user_id, text, done, created_at FROM todos WHERE id = ?",
                (todo_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown todo id: {todo_id}")
        data = dict(row)
        data["done"] = bool(data["done"])
        return TodoRecord(**data)

    def list_todos(self, user_id: str, include_done: bool = True, limit: int = 20) -> list[TodoRecord]:
        query = """
            SELECT id, user_id, text, done, created_at
            FROM todos
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if not include_done:
            query += " AND done = 0"
        query += " ORDER BY done ASC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        todos: list[TodoRecord] = []
        for row in rows:
            data = dict(row)
            data["done"] = bool(data["done"])
            todos.append(TodoRecord(**data))
        return todos

    def complete_todo(self, todo_id: int) -> TodoRecord:
        with self._connect() as connection:
            connection.execute(
                "UPDATE todos SET done = 1 WHERE id = ?",
                (todo_id,),
            )
        return self.get_todo(todo_id)

    def remember(self, user_id: str, fact: str) -> MemoryRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO memories (user_id, fact) VALUES (?, ?)",
                (user_id, fact.strip()),
            )
            memory_id = int(cursor.lastrowid)
        return self.get_memory(memory_id)

    def get_memory(self, memory_id: int) -> MemoryRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, user_id, fact, created_at FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown memory id: {memory_id}")
        return MemoryRecord(**dict(row))

    def list_memories(self, user_id: str, limit: int = 10) -> list[MemoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, fact, created_at
                FROM memories
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [MemoryRecord(**dict(row)) for row in rows]

    def add_interaction(self, user_id: str, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO interactions (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content.strip()),
            )

    def get_recent_interactions(self, user_id: str, limit: int = 12) -> list[tuple[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM interactions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result = [(str(row["role"]), str(row["content"])) for row in reversed(rows)]
        return result

    def add_reminder(
        self,
        user_id: str,
        transport: str,
        destination_id: str,
        text: str,
        due_in_seconds: int,
    ) -> ReminderRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reminders (user_id, transport, destination_id, text, due_at)
                VALUES (?, ?, ?, ?, datetime('now', ?))
                """,
                (
                    user_id,
                    transport.strip(),
                    destination_id.strip(),
                    text.strip(),
                    f"+{int(due_in_seconds)} seconds",
                ),
            )
            reminder_id = int(cursor.lastrowid)
        return self.get_reminder(reminder_id)

    def get_reminder(self, reminder_id: int) -> ReminderRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, transport, destination_id, text, due_at, delivered, created_at
                FROM reminders
                WHERE id = ?
                """,
                (reminder_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown reminder id: {reminder_id}")
        data = dict(row)
        data["delivered"] = bool(data["delivered"])
        return ReminderRecord(**data)

    def get_due_reminders(self, transport: str, limit: int = 20) -> list[ReminderRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, transport, destination_id, text, due_at, delivered, created_at
                FROM reminders
                WHERE transport = ? AND delivered = 0 AND due_at <= CURRENT_TIMESTAMP
                ORDER BY due_at ASC, id ASC
                LIMIT ?
                """,
                (transport, limit),
            ).fetchall()
        reminders: list[ReminderRecord] = []
        for row in rows:
            data = dict(row)
            data["delivered"] = bool(data["delivered"])
            reminders.append(ReminderRecord(**data))
        return reminders

    def mark_reminder_delivered(self, reminder_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE reminders SET delivered = 1 WHERE id = ?",
                (reminder_id,),
            )

    # --- memory summaries ---

    def get_interactions_for_date_range(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
    ) -> list[tuple[str, str, str]]:
        """Return (role, content, created_at) for interactions in [start_date, end_date)."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at
                FROM interactions
                WHERE user_id = ? AND created_at >= ? AND created_at < ?
                ORDER BY id ASC
                """,
                (user_id, start_date, end_date),
            ).fetchall()
        return [(str(r["role"]), str(r["content"]), str(r["created_at"])) for r in rows]

    def add_memory_summary(
        self,
        user_id: str,
        period: str,
        period_start: str,
        period_end: str,
        summary: str,
    ) -> MemorySummaryRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memory_summaries (user_id, period, period_start, period_end, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, period, period_start, period_end, summary.strip()),
            )
            row_id = int(cursor.lastrowid)
        return self.get_memory_summary(row_id)

    def get_memory_summary(self, summary_id: int) -> MemorySummaryRecord:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, period, period_start, period_end, summary, created_at
                FROM memory_summaries WHERE id = ?
                """,
                (summary_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown memory summary id: {summary_id}")
        return MemorySummaryRecord(**dict(row))

    def find_memory_summary(
        self, user_id: str, period: str, period_start: str
    ) -> MemorySummaryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, period, period_start, period_end, summary, created_at
                FROM memory_summaries
                WHERE user_id = ? AND period = ? AND period_start = ?
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, period, period_start),
            ).fetchone()
        if row is None:
            return None
        return MemorySummaryRecord(**dict(row))

    def list_memory_summaries(
        self, user_id: str, period: str, start_gte: str, start_lt: str
    ) -> list[MemorySummaryRecord]:
        """Return summaries of a given period whose period_start falls in [start_gte, start_lt)."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, period, period_start, period_end, summary, created_at
                FROM memory_summaries
                WHERE user_id = ? AND period = ? AND period_start >= ? AND period_start < ?
                ORDER BY period_start ASC
                """,
                (user_id, period, start_gte, start_lt),
            ).fetchall()
        return [MemorySummaryRecord(**dict(r)) for r in rows]

    def get_distinct_interaction_users(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT user_id FROM interactions"
            ).fetchall()
        return [str(r["user_id"]) for r in rows]
