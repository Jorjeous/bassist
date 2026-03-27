"""Lazy memory consolidation: day -> week -> month summaries via LLM."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from src.core.models import MessagePart, ModelRequest, OllamaGateway
from src.memory.store import MemoryStore, MemorySummaryRecord

LOGGER = logging.getLogger(__name__)

_DAY_SUMMARIZE_PROMPT = (
    "Summarize the following conversations from {date}. "
    "Include key facts, decisions, tasks, questions the user asked, "
    "and anything the user might want to recall later. "
    "Keep it concise but complete. Do not invent information."
)

_ROLL_UP_PROMPT = (
    "Below are {period} summaries covering {start} to {end}. "
    "Combine them into a single higher-level summary. "
    "Preserve important facts, decisions, and recurring themes. "
    "Be concise."
)


class MemoryConsolidator:
    def __init__(
        self, store: MemoryStore, model_gateway: OllamaGateway, memories_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._gateway = model_gateway
        self._memories_dir = memories_dir

    async def maybe_consolidate(self, user_id: str) -> None:
        """Run on each handle_text call. Generates missing summaries lazily."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        await self._ensure_day_summary(user_id, yesterday)

        week_start = today - timedelta(days=today.weekday())
        prev_week_start = week_start - timedelta(weeks=1)
        if today >= week_start and today.weekday() >= 1:
            await self._ensure_week_summary(user_id, prev_week_start)

        month_start = today.replace(day=1)
        if today.day >= 2:
            prev_month_end = month_start
            prev_month_start = (prev_month_end - timedelta(days=1)).replace(day=1)
            await self._ensure_month_summary(user_id, prev_month_start, prev_month_end)

    def _write_memory_file(
        self, user_id: str, period: str, filename: str, summary: str,
    ) -> None:
        if self._memories_dir is None:
            return
        target = self._memories_dir / user_id / period / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(summary, encoding="utf-8")
        LOGGER.info("Wrote memory file %s", target)

    def get_memory_file_path(
        self, user_id: str, period: str, ref_date: date,
    ) -> Path | None:
        if self._memories_dir is None:
            return None
        if period == "day":
            filename = f"{ref_date.isoformat()}.txt"
        elif period == "week":
            week_start = ref_date - timedelta(days=ref_date.weekday())
            week_end = week_start + timedelta(weeks=1)
            filename = f"{week_start.isoformat()}_{week_end.isoformat()}.txt"
        elif period == "month":
            filename = f"{ref_date.strftime('%Y-%m')}.txt"
        else:
            return None
        path = self._memories_dir / user_id / period / filename
        return path if path.exists() else None

    def list_memory_files(self, user_id: str) -> list[str]:
        if self._memories_dir is None:
            return []
        user_dir = self._memories_dir / user_id
        if not user_dir.exists():
            return []
        files: list[str] = []
        for period in ("day", "week", "month"):
            period_dir = user_dir / period
            if period_dir.exists():
                for f in sorted(period_dir.glob("*.txt")):
                    files.append(f"{period}/{f.name}")
        return files

    async def _ensure_day_summary(self, user_id: str, day: date) -> None:
        day_str = day.isoformat()
        existing = self._store.find_memory_summary(user_id, "day", day_str)
        if existing is not None:
            return

        next_day = (day + timedelta(days=1)).isoformat()
        interactions = self._store.get_interactions_for_date_range(
            user_id, day_str, next_day
        )
        if not interactions:
            return

        conversation = "\n".join(
            f"[{role}] {content}" for role, content, _ in interactions
        )
        prompt = _DAY_SUMMARIZE_PROMPT.format(date=day_str)
        summary = await self._gateway.generate_text(
            ModelRequest(messages=[
                MessagePart(role="system", content=prompt),
                MessagePart(role="user", content=conversation),
            ])
        )
        if summary.strip():
            self._store.add_memory_summary(
                user_id=user_id,
                period="day",
                period_start=day_str,
                period_end=next_day,
                summary=summary,
            )
            self._write_memory_file(user_id, "day", f"{day_str}.txt", summary)
            LOGGER.info("Consolidated day summary for user %s, date %s", user_id, day_str)

    async def _ensure_week_summary(self, user_id: str, week_start: date) -> None:
        ws = week_start.isoformat()
        existing = self._store.find_memory_summary(user_id, "week", ws)
        if existing is not None:
            return

        week_end = week_start + timedelta(weeks=1)
        day_summaries = self._store.list_memory_summaries(
            user_id, "day", ws, week_end.isoformat()
        )
        if not day_summaries:
            return

        combined = "\n\n".join(
            f"[{s.period_start}]\n{s.summary}" for s in day_summaries
        )
        prompt = _ROLL_UP_PROMPT.format(period="daily", start=ws, end=week_end.isoformat())
        summary = await self._gateway.generate_text(
            ModelRequest(messages=[
                MessagePart(role="system", content=prompt),
                MessagePart(role="user", content=combined),
            ])
        )
        if summary.strip():
            self._store.add_memory_summary(
                user_id=user_id,
                period="week",
                period_start=ws,
                period_end=week_end.isoformat(),
                summary=summary,
            )
            self._write_memory_file(
                user_id, "week", f"{ws}_{week_end.isoformat()}.txt", summary,
            )
            LOGGER.info("Consolidated week summary for user %s, week %s", user_id, ws)

    async def _ensure_month_summary(
        self, user_id: str, month_start: date, month_end: date
    ) -> None:
        ms = month_start.isoformat()
        existing = self._store.find_memory_summary(user_id, "month", ms)
        if existing is not None:
            return

        week_summaries = self._store.list_memory_summaries(
            user_id, "week", ms, month_end.isoformat()
        )
        if not week_summaries:
            day_summaries = self._store.list_memory_summaries(
                user_id, "day", ms, month_end.isoformat()
            )
            if not day_summaries:
                return
            combined = "\n\n".join(
                f"[{s.period_start}]\n{s.summary}" for s in day_summaries
            )
        else:
            combined = "\n\n".join(
                f"[{s.period_start} - {s.period_end}]\n{s.summary}" for s in week_summaries
            )

        prompt = _ROLL_UP_PROMPT.format(
            period="weekly" if week_summaries else "daily",
            start=ms,
            end=month_end.isoformat(),
        )
        summary = await self._gateway.generate_text(
            ModelRequest(messages=[
                MessagePart(role="system", content=prompt),
                MessagePart(role="user", content=combined),
            ])
        )
        if summary.strip():
            self._store.add_memory_summary(
                user_id=user_id,
                period="month",
                period_start=ms,
                period_end=month_end.isoformat(),
                summary=summary,
            )
            self._write_memory_file(
                user_id, "month", f"{month_start.strftime('%Y-%m')}.txt", summary,
            )
            LOGGER.info("Consolidated month summary for user %s, month %s", user_id, ms)

    def get_today_summary(self, user_id: str) -> str | None:
        today = date.today().isoformat()
        rec = self._store.find_memory_summary(user_id, "day", today)
        if rec:
            return rec.summary
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        rec = self._store.find_memory_summary(user_id, "day", yesterday)
        return rec.summary if rec else None

    def get_summary_for_period(
        self, user_id: str, period: str, ref_date: date
    ) -> MemorySummaryRecord | None:
        if period == "day":
            return self._store.find_memory_summary(user_id, "day", ref_date.isoformat())
        if period == "week":
            week_start = ref_date - timedelta(days=ref_date.weekday())
            return self._store.find_memory_summary(user_id, "week", week_start.isoformat())
        if period == "month":
            month_start = ref_date.replace(day=1)
            return self._store.find_memory_summary(user_id, "month", month_start.isoformat())
        return None

    def recall_for_query(self, user_id: str, text: str) -> str:
        """Detect temporal references and return relevant memory summaries."""
        lowered = text.lower()
        parts: list[str] = []
        today = date.today()

        if any(kw in lowered for kw in ("yesterday", "вчера")):
            rec = self.get_summary_for_period(user_id, "day", today - timedelta(days=1))
            if rec:
                parts.append(f"Yesterday ({rec.period_start}):\n{rec.summary}")

        if any(kw in lowered for kw in (
            "last week", "earlier this week", "на прошлой неделе", "на этой неделе",
        )):
            week_start = today - timedelta(days=today.weekday())
            prev_week_start = week_start - timedelta(weeks=1)
            rec = self.get_summary_for_period(user_id, "week", prev_week_start)
            if rec:
                parts.append(f"Last week ({rec.period_start} - {rec.period_end}):\n{rec.summary}")

        if any(kw in lowered for kw in ("last month", "в прошлом месяце")):
            first_of_month = today.replace(day=1)
            prev_month_date = first_of_month - timedelta(days=1)
            rec = self.get_summary_for_period(user_id, "month", prev_month_date)
            if rec:
                parts.append(f"Last month ({rec.period_start} - {rec.period_end}):\n{rec.summary}")

        if any(kw in lowered for kw in (
            "remember when", "what did i", "what did we", "do you remember",
            "помнишь", "что я",
        )):
            for offset in [1, 2, 3, 4, 5, 6, 7]:
                rec = self.get_summary_for_period(
                    user_id, "day", today - timedelta(days=offset)
                )
                if rec:
                    parts.append(f"Day {rec.period_start}:\n{rec.summary}")

        if not parts:
            return ""
        return "Recalled memory:\n\n" + "\n\n".join(parts)
