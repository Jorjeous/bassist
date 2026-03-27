from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re

from src.config import Settings
from src.core.models import ImageInput, MessagePart, ModelRequest, OllamaGateway
from src.memory.consolidator import MemoryConsolidator
from src.memory.store import MemoryStore, ReminderRecord
from src.speech.transcribe import SpeechToTextService
from src.tools.commands import CommandTool
from src.tools.file_reader import FileReaderTool
from src.tools.google_docs import GoogleDocsTool
from src.tools.google_drive import GoogleDriveTool
from src.tools.notes import NotesTodoTool
from src.tools.travel import TravelTool, format_verified_routes, google_flights_url, omio_url
from src.tools.weather import WeatherTool
from src.tools.web import WebSearchTool


@dataclass(slots=True)
class AssistantResponse:
    text: str
    transcript: str | None = None


class AssistantCore:

    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        model_gateway: OllamaGateway,
        speech_service: SpeechToTextService,
    ) -> None:
        self._settings = settings
        self._store = store
        self._model_gateway = model_gateway
        self._speech_service = speech_service
        self._notes_tool = NotesTodoTool(store)
        self._web_tool = WebSearchTool(
            region=settings.web_region,
            max_results=settings.web_results_limit,
        )
        self._travel_tool = TravelTool(token=settings.travelpayouts_token)
        self._docs_tool = GoogleDocsTool(settings)
        self._drive_tool = GoogleDriveTool(settings)
        self._command_tool = CommandTool(settings)
        self._weather_tool = WeatherTool(region=settings.web_region)
        self._file_reader = FileReaderTool(allowed_dirs=[settings.memories_dir, settings.data_dir])
        self._consolidator = MemoryConsolidator(store, model_gateway, settings.memories_dir)

    def log_observation(
        self,
        user_id: str,
        text: str,
        *,
        username: str = "",
        channel_name: str = "",
    ) -> None:
        """Record a message the assistant should be aware of but NOT reply to."""
        prefix = f"[{username}]" if username else f"[user:{user_id}]"
        if channel_name:
            prefix = f"[#{channel_name}] {prefix}"
        self._store.add_interaction(user_id, "user", f"{prefix} {text}")

    async def handle_text(
        self,
        user_id: str,
        text: str,
        *,
        transport: str | None = None,
        destination_id: str | None = None,
        username: str = "",
        channel_name: str = "",
    ) -> AssistantResponse:
        cleaned = text.strip()
        if not cleaned:
            return AssistantResponse(text="Please send a message with some text.")

        try:
            tool_result = await self._handle_tool_command(
                user_id=user_id,
                text=cleaned,
                transport=transport,
                destination_id=destination_id,
            )
            if tool_result is not None:
                self._store.add_interaction(user_id, "user", cleaned)
                self._store.add_interaction(user_id, "assistant", tool_result)
                return AssistantResponse(text=tool_result)
        except Exception as exc:
            return AssistantResponse(text=f"Tool request failed: {exc}")

        await self._consolidator.maybe_consolidate(user_id)

        memories = self._notes_tool.list_memories(user_id)
        history = self._store.get_recent_interactions(
            user_id=user_id,
            limit=self._settings.max_context_messages,
        )

        recalled = self._consolidator.recall_for_query(user_id, cleaned)
        today_summary = self._consolidator.get_today_summary(user_id)
        extra_parts: list[str] = []
        if today_summary:
            extra_parts.append(f"Today's context so far:\n{today_summary}")
        if recalled:
            extra_parts.append(recalled)

        memory_data = self._maybe_retrieve_memories(user_id, cleaned)
        if memory_data:
            extra_parts.append(memory_data)

        weather_city = await self._parse_weather_request(cleaned)
        if weather_city:
            weather_data = self._weather_tool.lookup(weather_city)
            answer = weather_data
            if self._settings.english_fix_mode:
                correction = await self._correct_english(cleaned)
                if correction:
                    answer = f"*{correction}*\n\n{answer}"
            self._store.add_interaction(user_id, "user", cleaned)
            self._store.add_interaction(user_id, "assistant", answer)
            return AssistantResponse(text=answer)

        travel_request = await self._parse_travel_request(cleaned)
        if travel_request:
            origin, destination, travel_date = travel_request
            answer = await self._handle_travel_search(origin, destination, travel_date or None)
            if self._settings.english_fix_mode:
                correction = await self._correct_english(cleaned)
                if correction:
                    answer = f"*{correction}*\n\n{answer}"
            self._store.add_interaction(user_id, "user", cleaned)
            self._store.add_interaction(user_id, "assistant", answer)
            return AssistantResponse(text=answer)

        web_results = await self._maybe_web_search(cleaned)
        if web_results:
            extra_parts.append(f"Web search results (use these to answer):\n{web_results}")

        extra_context = "\n\n".join(extra_parts)

        messages = [MessagePart(role="system", content=self._build_system_prompt(
            memories, extra_context, user_id, username=username, channel_name=channel_name,
        ))]
        for role, content in history:
            messages.append(MessagePart(role=role, content=content))
        user_prefix = f"[{username}] " if username else ""
        messages.append(MessagePart(role="user", content=f"{user_prefix}{cleaned}"))

        answer = await self._model_gateway.generate_text(ModelRequest(messages=messages))
        answer = self._strip_echo(answer, cleaned)
        answer = self._strip_followup(answer)

        if self._settings.english_fix_mode:
            correction = await self._correct_english(cleaned)
            if correction:
                answer = f"*{correction}*\n\n{answer}"

        self._store.add_interaction(user_id, "user", cleaned)
        self._store.add_interaction(user_id, "assistant", answer)
        return AssistantResponse(text=answer)

    async def handle_audio(
        self,
        user_id: str,
        audio_path: Path,
        *,
        transport: str | None = None,
        destination_id: str | None = None,
    ) -> AssistantResponse:
        transcript = self._speech_service.transcribe(audio_path)
        response = await self.handle_text(
            user_id=user_id,
            text=transcript,
            transport=transport,
            destination_id=destination_id,
        )
        response.transcript = transcript
        return response

    async def handle_image(self, user_id: str, prompt: str, image_bytes: bytes) -> AssistantResponse:
        memories = self._notes_tool.list_memories(user_id)
        request = ModelRequest(
            messages=[
                MessagePart(role="system", content=self._build_system_prompt(memories, user_id=user_id)),
                MessagePart(role="user", content=prompt),
            ],
            images=[ImageInput(data=image_bytes)],
        )
        answer = await self._model_gateway.generate_vision(request)
        self._store.add_interaction(user_id, "user", prompt)
        self._store.add_interaction(user_id, "assistant", answer)
        return AssistantResponse(text=answer)

    async def _handle_tool_command(
        self,
        user_id: str,
        text: str,
        *,
        transport: str | None,
        destination_id: str | None,
    ) -> str | None:
        lowered = text.lower()

        if lowered in {"/english on", "/english fix on"}:
            self._settings.english_fix_mode = True
            return "English fix mode: ON. I will show corrected versions of your messages."
        if lowered in {"/english off", "/english fix off"}:
            self._settings.english_fix_mode = False
            return "English fix mode: OFF."

        reminder_request = await self._parse_reminder_request(text=text)
        if reminder_request is not None:
            reminder_text, due_in_seconds = reminder_request
            if not transport or not destination_id:
                raise ValueError("Reminders require an active chat destination.")
            reminder = self._store.add_reminder(
                user_id=user_id,
                transport=transport,
                destination_id=destination_id,
                text=reminder_text,
                due_in_seconds=due_in_seconds,
            )
            return self._format_reminder_confirmation(reminder, due_in_seconds)

        if text.startswith("/note "):
            payload = text.removeprefix("/note ").strip()
            title, content = self._split_title_body(payload)
            return self._notes_tool.create_note(user_id, title, content)

        if lowered == "/notes":
            return self._notes_tool.list_notes(user_id)

        if text.startswith("/todo add "):
            return self._notes_tool.add_todo(user_id, text.removeprefix("/todo add ").strip())

        if lowered in {"/todo list", "/todos"}:
            return self._notes_tool.list_todos(user_id)

        if text.startswith("/todo done "):
            todo_id = int(text.removeprefix("/todo done ").strip())
            return self._notes_tool.complete_todo(todo_id)

        if text.startswith("/remember_shared "):
            fact = text.removeprefix("/remember_shared ").strip()
            return self._notes_tool.remember("__shared__", fact)

        if text.startswith("/remember "):
            fact = text.removeprefix("/remember ").strip()
            return self._notes_tool.remember(user_id, fact)

        if lowered == "/memories":
            return self._notes_tool.list_memories(user_id)

        if text.startswith("/web "):
            query = text.removeprefix("/web ").strip()
            return self._web_tool.search(query)

        if text.startswith("/smartsearch "):
            query = text.removeprefix("/smartsearch ").strip()
            return await self._smart_search(query)

        if text.startswith("/translate "):
            return await self._translate_request(text.removeprefix("/translate ").strip())

        if text.startswith("/travel "):
            return await self._handle_travel_command(text.removeprefix("/travel ").strip())

        if text.startswith("/doc "):
            payload = text.removeprefix("/doc ").strip()
            if payload.startswith("read "):
                document_id = payload.removeprefix("read ").strip()
                content = self._docs_tool.read_document(document_id)
                return content or "The Google Doc is empty."
            title, content = self._split_title_body(payload)
            document = self._docs_tool.create_document(title=title, content=content)
            return f"Created Google Doc: {document['title']}\n{document['url']}"

        if text.startswith("/drive list"):
            query = text.removeprefix("/drive list").strip() or None
            files = self._drive_tool.list_files(query=query)
            if not files:
                return "No matching Drive files."
            return "\n".join(
                f"{item['name']} ({item['mimeType']})\n{item.get('webViewLink', '')}"
                for item in files
            )

        if text.startswith("/drive upload "):
            path = Path(text.removeprefix("/drive upload ").strip())
            upload = self._drive_tool.upload_file(path=path)
            return f"Uploaded to Drive: {upload['name']}\n{upload.get('webViewLink', '')}"

        if text.startswith("/memory "):
            return self._handle_memory_command(user_id, text.removeprefix("/memory ").strip())

        if lowered == "/memory files" or lowered == "/memfiles":
            files = self._consolidator.list_memory_files(user_id)
            if not files:
                return "No memory files yet."
            return "Memory files:\n" + "\n".join(files)

        if text.startswith("/readfile "):
            path = text.removeprefix("/readfile ").strip()
            return self._file_reader.read_file(path)

        if text.startswith("/listfiles"):
            path = text.removeprefix("/listfiles").strip()
            if not path:
                path = str(self._settings.memories_dir)
            return self._file_reader.list_files(path)

        if text.startswith("/summarize_history\n"):
            history_text = text.removeprefix("/summarize_history\n")
            return await self._summarize_history(history_text)

        if text.startswith("/command "):
            result = await self._command_tool.run(text.removeprefix("/command ").strip())
            body = result.stdout or result.stderr or "(no output)"
            return f"Exit code: {result.return_code}\n{body}"

        return None

    def _handle_memory_command(self, user_id: str, payload: str) -> str:
        parts = payload.split(maxsplit=1)
        period = parts[0].lower() if parts else "day"
        if period not in {"day", "week", "month"}:
            return "Usage: /memory day|week|month [YYYY-MM-DD]"

        ref = date.today()
        if len(parts) > 1:
            try:
                ref = date.fromisoformat(parts[1].strip())
            except ValueError:
                return "Invalid date. Use YYYY-MM-DD format."

        rec = self._consolidator.get_summary_for_period(user_id, period, ref)
        if rec is None:
            return f"No {period} memory summary found for {ref.isoformat()}."
        return f"{period.capitalize()} memory ({rec.period_start} - {rec.period_end}):\n\n{rec.summary}"

    async def _summarize_history(self, history_text: str) -> str:
        prompt = (
            "Summarize the following Discord channel conversation. "
            "Highlight the main topics discussed, any decisions made, "
            "questions asked, and action items. Be concise."
        )
        result = await self._model_gateway.generate_text(
            ModelRequest(messages=[
                MessagePart(role="system", content=prompt),
                MessagePart(role="user", content=history_text),
            ])
        )
        return result

    async def _handle_travel_command(self, payload: str) -> str:
        """Parse '/travel origin to destination [date]' and run search."""
        import json as _json
        parts = re.split(r"\s+to\s+", payload, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) < 2:
            return "Usage: /travel <origin> to <destination> [DD/MM/YYYY]"
        origin = parts[0].strip()
        rest = parts[1].strip().split(maxsplit=1)
        destination = rest[0].strip()
        travel_date = rest[1].strip() if len(rest) > 1 else None
        return await self._handle_travel_search(origin, destination, travel_date)

    async def _handle_travel_search(
        self, origin: str, destination: str, travel_date: str | None = None,
    ) -> str:
        """LLM proposes routes, flight legs verified via Travelpayouts API,
        bus/train legs verified via web search + LLM fact extraction."""
        import json as _json

        route_prompt = self._TRAVEL_ROUTE_PROMPT.format(origin=origin, destination=destination)
        raw = await self._model_gateway.generate_text(ModelRequest(messages=[
            MessagePart(role="system", content=route_prompt),
            MessagePart(role="user", content=f"From {origin} to {destination}"),
        ]))
        cleaned = raw.strip()
        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]") + 1
        if arr_start < 0 or arr_end <= arr_start:
            return f"Could not generate route proposals for {origin} -> {destination}."

        try:
            candidate_routes = _json.loads(cleaned[arr_start:arr_end])
        except _json.JSONDecodeError:
            return f"Could not parse route proposals for {origin} -> {destination}."

        verified_routes: list[dict] = []

        for route_legs in candidate_routes[:5]:
            verified_legs: list[dict] = []
            all_verified = True

            for leg in route_legs:
                leg_from = leg.get("from", "")
                leg_to = leg.get("to", "")
                transport = leg.get("transport", "flight").lower()

                if transport == "flight":
                    ok = self._verify_flight_leg(
                        leg_from, leg_to, travel_date, verified_legs,
                    )
                else:
                    ok = await self._verify_ground_leg(
                        leg_from, leg_to, transport, travel_date, verified_legs,
                    )

                if not ok:
                    all_verified = False
                    break

            if all_verified and verified_legs:
                cities = [verified_legs[0]["from"]]
                cities.extend(vl["to"] for vl in verified_legs)
                summary = " -> ".join(cities)

                price_tokens = [
                    vl["details"].split(",")[0].strip()
                    for vl in verified_legs
                    if vl.get("details") and vl["details"] != "see link"
                ]
                total_estimate = " + ".join(price_tokens) if price_tokens else ""

                verified_routes.append({
                    "summary": summary,
                    "total_estimate": total_estimate,
                    "legs": verified_legs,
                })

        if not verified_routes:
            return f"No verified routes found from {origin} to {destination}. Try a different route or date."

        routes_text = format_verified_routes(verified_routes)

        rank_prompt = self._TRAVEL_RANK_PROMPT.format(routes=routes_text)
        ranked = await self._model_gateway.generate_text(ModelRequest(messages=[
            MessagePart(role="system", content=rank_prompt),
            MessagePart(role="user", content=f"From {origin} to {destination}"),
        ]))

        return f"Travel: {origin} -> {destination}\n\n{routes_text}\n\n--- Recommendation ---\n{ranked}"

    def _verify_flight_leg(
        self,
        origin: str,
        destination: str,
        travel_date: str | None,
        out: list[dict],
    ) -> bool:
        """Check a flight leg against Travelpayouts API. Appends to out if found."""
        if not self._travel_tool.available:
            return False
        results = self._travel_tool.search_flights(
            origin, destination, departure_date=travel_date, limit=3,
        )
        if not results:
            return False
        best = results[0]
        dur_h = best["duration_min"] // 60 if best["duration_min"] else 0
        dur_m = best["duration_min"] % 60 if best["duration_min"] else 0
        stops = "direct" if best["transfers"] == 0 else f"{best['transfers']} stop(s)"
        details = (
            f"{best['currency']} {best['price']}, "
            f"{dur_h}h {dur_m:02d}m, {stops}, "
            f"{best['airline']} {best.get('flight_number', '')}"
        )
        out.append({
            "from": origin,
            "to": destination,
            "transport": "Flight",
            "details": details,
            "link": best.get("link", google_flights_url(origin, destination, travel_date)),
        })
        return True

    async def _verify_ground_leg(
        self,
        origin: str,
        destination: str,
        transport: str,
        travel_date: str | None,
        out: list[dict],
    ) -> bool:
        """Verify a bus/train leg via web search + LLM fact extraction."""
        import json as _json

        query = f"{transport} from {origin} to {destination} price duration"
        if travel_date:
            query += f" {travel_date}"
        web_data = self._web_tool.search(query)
        if not web_data:
            return False

        verify_raw = await self._model_gateway.generate_text(ModelRequest(messages=[
            MessagePart(role="system", content=self._TRAVEL_VERIFY_PROMPT),
            MessagePart(
                role="user",
                content=f"Leg: {transport} from {origin} to {destination}\n\nSearch results:\n{web_data}",
            ),
        ]))

        try:
            vstart = verify_raw.find("{")
            vend = verify_raw.rfind("}") + 1
            if vstart < 0 or vend <= vstart:
                return False
            verification = _json.loads(verify_raw[vstart:vend])
        except _json.JSONDecodeError:
            return False

        if not verification.get("exists"):
            return False

        parts = []
        for key in ("price_range", "duration", "carriers"):
            val = verification.get(key, "unknown")
            if val and val != "unknown":
                parts.append(val)

        out.append({
            "from": origin,
            "to": destination,
            "transport": transport.capitalize(),
            "details": ", ".join(parts) if parts else "see link",
            "link": omio_url(origin, destination),
        })
        return True

    def get_due_reminders(self, transport: str) -> list[ReminderRecord]:
        return self._store.get_due_reminders(transport=transport)

    def mark_reminder_delivered(self, reminder_id: int) -> None:
        self._store.mark_reminder_delivered(reminder_id)

    async def _translate_request(self, payload: str) -> str:
        if ":" not in payload or "->" not in payload:
            raise ValueError("Usage: /translate SRC->DST: text")
        route, content = payload.split(":", maxsplit=1)
        source_lang, target_lang = [part.strip() for part in route.split("->", maxsplit=1)]
        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            "Return only the translated text.\n\n"
            f"{content.strip()}"
        )
        response = await self._model_gateway.generate_text(
            ModelRequest(
                messages=[
                    MessagePart(role="system", content="You are a precise translator."),
                    MessagePart(role="user", content=prompt),
                ]
            )
        )
        return response

    _FOLLOWUP_RE = re.compile(
        r"\s*("
        r"Would you like.*\?|"
        r"Let me know if.*\.|"
        r"Can I help.*\?|"
        r"How can I assist.*\?|"
        r"Is there anything else.*\?|"
        r"Do you want me to.*\?|"
        r"Do you need.*\?|"
        r"Please specify.*\.|"
        r"Shall I.*\?|"
        r"Want me to.*\?"
        r")\s*$",
        re.IGNORECASE,
    )

    _ITALIC_LINE_RE = re.compile(r"^\*[^*]+\*$")

    @classmethod
    def _strip_echo(cls, answer: str, user_text: str) -> str:
        """Remove LLM's habit of echoing/narrating in *italics* at the top."""
        lines = answer.split("\n")
        cleaned: list[str] = []
        _norm = lambda s: re.sub(r"[^\w\s]", "", s.lower()).split()
        user_words = set(_norm(user_text))
        for line in lines:
            stripped = line.strip()
            if not cleaned and cls._ITALIC_LINE_RE.match(stripped):
                inner_words = set(_norm(stripped[1:-1]))
                if inner_words & user_words or any(
                    kw in stripped.lower()
                    for kw in ("processing", "command", "retriev", "checking")
                ):
                    continue
            cleaned.append(line)
        result = "\n".join(cleaned).strip()
        return result if result else answer

    @classmethod
    def _strip_followup(cls, answer: str) -> str:
        """Remove trailing follow-up questions the LLM adds despite instructions."""
        return cls._FOLLOWUP_RE.sub("", answer).rstrip()

    def _build_system_prompt(
        self,
        memories: str,
        extra_context: str = "",
        user_id: str | None = None,
        username: str = "",
        channel_name: str = "",
    ) -> str:
        now = datetime.now()
        time_line = f"Current date/time: {now:%A, %B %d %Y, %H:%M}."
        parts = [time_line, self._settings.system_prompt]

        session_context: list[str] = []
        if username:
            session_context.append(f"You are talking to: {username} (user_id: {user_id})")
        if channel_name:
            session_context.append(f"Current channel: #{channel_name}")
        if session_context:
            parts.append("Session context:\n" + "\n".join(session_context))

        if memories != "No long-term memories recorded yet.":
            parts.append(f"Long-term memory (this user):\n{memories}")

        shared_memories = self._notes_tool.list_memories("__shared__")
        if shared_memories != "No long-term memories recorded yet.":
            parts.append(f"Shared memory (all users):\n{shared_memories}")

        if user_id:
            mem_files = self._consolidator.list_memory_files(user_id)
            if mem_files:
                parts.append(
                    "Available memory files (user can request with /memory command):\n"
                    + "\n".join(mem_files)
                )
        if extra_context:
            parts.append(extra_context)
        return "\n\n".join(parts)

    _ENGLISH_FIX_PROMPT = (
        "You are an English grammar and spelling corrector.\n"
        "Given the user's message, return ONLY the corrected version.\n"
        "Rules:\n"
        "- Fix only grammar, spelling, and punctuation mistakes.\n"
        "- Do NOT change the meaning, add words, remove words, or rephrase.\n"
        "- Do NOT add commands, tags, slashes, or any markup (no /think, no <think>, nothing).\n"
        "- If the message is already correct, casual slang, or a short phrase, return exactly: OK\n"
        "- Return ONLY the corrected text or OK. Nothing else."
    )

    _SMART_SEARCH_PROMPT = (
        "You are a research analyst. You have been given a user's query and the full text "
        "content fetched from multiple web pages. Your task:\n\n"
        "1. ANSWER the query using information from the sources.\n"
        "2. For each key claim, note which source(s) support it.\n"
        "3. RELIABILITY ASSESSMENT -- at the end, provide a reliability rating:\n"
        "   - HIGH: multiple independent sources agree, sources are reputable\n"
        "   - MEDIUM: some sources agree but data may be outdated or from less authoritative sites\n"
        "   - LOW: sources contradict each other, or only one unverified source\n"
        "   - UNVERIFIABLE: not enough information in the sources to answer reliably\n\n"
        "Rules:\n"
        "- Only use facts explicitly stated in the provided sources\n"
        "- If sources contradict, note the contradiction\n"
        "- Be concise and structured\n"
        "- Do NOT invent information beyond what the sources say"
    )

    _SEARCH_CLASSIFY_PROMPT = (
        "You are a strict JSON-only intent classifier. "
        "Determine if the user message is a FACTUAL question about the external world that requires "
        "up-to-date information from the internet (e.g. specific facts, statistics, current events, "
        "how-to guides, prices, scientific data, historical facts, technical specifications).\n"
        "ALWAYS return search=false for:\n"
        "- Greetings, chitchat, small talk\n"
        "- Questions about the conversation itself ('what did I say', 'what can you do')\n"
        "- Questions about the user's data, memories, reminders, notes, todos\n"
        "- Requests to set reminders, translate, create notes\n"
        "- Weather requests\n"
        "- Travel, flight, route, or transportation requests\n"
        "- Follow-up questions or clarifications about previous messages\n"
        "- Opinions, advice, or creative tasks\n"
        "- Messages that are statements, not questions\n"
        "If YES (factual external question), respond with EXACTLY:\n"
        '{"search": true, "query": "<concise search query>"}\n'
        "If NO, respond with EXACTLY:\n"
        '{"search": false}\n'
        "Only return JSON, nothing else."
    )

    _WEATHER_CLASSIFY_PROMPT = (
        "You are a JSON-only intent classifier. "
        "Determine if the user message is asking about weather, temperature, or forecast. "
        "If YES, respond with EXACTLY this JSON (no other text):\n"
        '{"weather": true, "city": "<city name>"}\n'
        "If the user does not specify a city, default to Yerevan. "
        "If NO weather request, respond with EXACTLY:\n"
        '{"weather": false}\n'
        "Handle any language, typos, abbreviations. Only return JSON."
    )

    _TRAVEL_CLASSIFY_PROMPT = (
        "You are a JSON-only intent classifier. "
        "Determine if the user message is asking about travel, getting from one place to another, "
        "flights, routes, transportation, or trip planning between cities/countries. "
        "If YES, respond with EXACTLY this JSON (no other text):\n"
        '{"travel": true, "origin": "<origin city>", "destination": "<destination city>", '
        '"date": "<DD/MM/YYYY or empty string if not specified>"}\n'
        "If NO travel request, respond with EXACTLY:\n"
        '{"travel": false}\n'
        "Handle any language, typos, abbreviations. Only return JSON."
    )

    _TRAVEL_ROUTE_PROMPT = (
        "You are a travel route planner with expert knowledge of international transport hubs. "
        "Given origin and destination, suggest 3-5 REALISTIC multi-modal routes combining "
        "flights, buses, and trains. ONLY suggest routes that actually exist -- real airlines, "
        "real bus companies, real train lines. Include budget options through nearby hub cities.\n\n"
        "Origin: {origin}\nDestination: {destination}\n\n"
        "Return ONLY a JSON array. Each route is a list of legs:\n"
        '[{{"from": "city1", "to": "city2", "transport": "flight|bus|train"}}, ...]\n'
        "Rules:\n"
        "- Only suggest transport connections that actually exist\n"
        "- For flights: only real airline routes (e.g. Pegasus flies EVN-IST, not EVN-GVA)\n"
        "- For buses: only routes where bus companies operate (e.g. FlixBus in Europe)\n"
        "- Think about hub airports: Istanbul, Vienna, Moscow, Dubai, Athens, Warsaw\n"
        "Only return the JSON array, nothing else."
    )

    _TRAVEL_VERIFY_PROMPT = (
        "You are a strict fact extractor. Given web search results about a travel leg, "
        "extract ONLY information that is explicitly stated in the search results.\n"
        "Return EXACTLY this JSON:\n"
        '{{"exists": true/false, "price_range": "e.g. $50-$150 or unknown", '
        '"duration": "e.g. 2h 30m or unknown", "carriers": "e.g. Pegasus, Turkish Airlines or unknown"}}\n'
        "Rules:\n"
        "- Set exists=true ONLY if the search results confirm this specific route exists\n"
        "- If the search results don't mention this route, set exists=false\n"
        "- NEVER guess or infer prices -- only use numbers from the search results\n"
        "- Only return JSON, nothing else."
    )

    _TRAVEL_RANK_PROMPT = (
        "You are a travel advisor. Below are VERIFIED route options with real data from web searches. "
        "Rank them by the best balance of cost and travel time. For each route, briefly note "
        "the pros and cons. Recommend the best option. Be concise and structured. "
        "Do NOT invent any information -- only use what is provided.\n\n"
        "Routes:\n{routes}\n\n"
        "Provide a clear ranking with a short recommendation."
    )

    _REMINDER_CLASSIFY_PROMPT = (
        "You are a JSON-only intent classifier. "
        "Determine if the user message is asking to set a reminder or be notified/alerted about something after a delay. "
        "If YES, respond with EXACTLY this JSON (no other text):\n"
        '{"reminder": true, "text": "<what to remind about>", "seconds": <total delay in seconds as integer>}\n'
        "If NO, respond with EXACTLY:\n"
        '{"reminder": false}\n'
        "Rules:\n"
        "- Convert all time expressions to total seconds (1.5 minutes = 90, 1 hour 30 min = 5400)\n"
        "- The 'text' field should be a clean, concise reminder message\n"
        "- Handle any language, typos, slang\n"
        "- Only return JSON, nothing else"
    )

    _MEMORY_KEYWORDS = re.compile(
        r"\b(memor|remember|recall|what do you know|"
        r"this week|last week|today.s summary|yesterday|"
        r"what happened|conversation history|past conversations|"
        r"что помнишь|что знаешь)\b",
        re.IGNORECASE,
    )

    def _maybe_retrieve_memories(self, user_id: str, text: str) -> str | None:
        """If the user is asking about memories, auto-retrieve and inject them."""
        if not self._MEMORY_KEYWORDS.search(text):
            return None

        parts: list[str] = []

        mem_files = self._consolidator.list_memory_files(user_id)
        if mem_files:
            parts.append(f"Your memory files: {', '.join(mem_files)}")
            for fname in mem_files[-5:]:
                filepath = self._settings.memories_dir / user_id / fname
                content = self._file_reader.read_file(str(filepath))
                if content and not content.startswith("Error"):
                    label = fname.replace("/", " / ").replace(".txt", "")
                    parts.append(f"--- {label} ---\n{content}")

        user_memories = self._notes_tool.list_memories(user_id)
        if user_memories and user_memories != "No long-term memories recorded yet.":
            parts.append(f"Stored facts:\n{user_memories}")

        if not parts:
            return "No memory summaries found yet. Memories are created automatically over time as you chat."

        return "Retrieved memory data:\n\n" + "\n\n".join(parts)

    async def _correct_english(self, text: str) -> str | None:
        if len(text.split()) < 3 or text.startswith("/"):
            return None
        try:
            from src.core.models import _THINK_RE
            raw = await self._model_gateway.generate_text(ModelRequest(messages=[
                MessagePart(role="system", content=self._ENGLISH_FIX_PROMPT),
                MessagePart(role="user", content=text),
            ]))
            corrected = _THINK_RE.sub("", raw).strip().strip('"').strip()
            if corrected.upper() == "OK":
                return None
            if "/" in corrected or "<" in corrected:
                return None
            _words = lambda s: re.sub(r"[^\w\s]", "", s.lower()).split()
            orig_words = _words(text)
            corr_words = _words(corrected)
            if corr_words == orig_words:
                return None
            if len(corrected) < 3:
                return None
            if len(corr_words) > len(orig_words) + 2:
                return None
            overlap = len(set(orig_words) & set(corr_words))
            if overlap < len(orig_words) * 0.5:
                return None
            return corrected
        except Exception:
            return None

    async def _parse_reminder_request(self, text: str) -> tuple[str, int] | None:
        cmd = re.match(r"^/remind\s+(.+?)\s*\|\s*(.+)$", text, re.IGNORECASE)
        if cmd:
            return cmd.group(2).strip(), self._parse_duration_to_seconds(cmd.group(1))

        try:
            import json
            raw = await self._model_gateway.generate_text(ModelRequest(messages=[
                MessagePart(role="system", content=self._REMINDER_CLASSIFY_PROMPT),
                MessagePart(role="user", content=text),
            ]))
            cleaned = raw.strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            data = json.loads(cleaned[start:end])
            if not data.get("reminder"):
                return None
            reminder_text = data.get("text", "").strip()
            seconds = int(data.get("seconds", 0))
            if not reminder_text or seconds <= 0:
                return None
            return reminder_text, seconds
        except Exception:
            return None

    async def _maybe_web_search(self, text: str) -> str | None:
        try:
            import json
            raw = await self._model_gateway.generate_text(ModelRequest(messages=[
                MessagePart(role="system", content=self._SEARCH_CLASSIFY_PROMPT),
                MessagePart(role="user", content=text),
            ]))
            cleaned = raw.strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            data = json.loads(cleaned[start:end])
            if not data.get("search"):
                return None
            query = data.get("query", "").strip()
            if not query:
                return None
            pages = self._web_tool.deep_search(query, max_pages=3)
            if pages:
                return self._web_tool.format_deep_results(pages)
            return self._web_tool.search(query)
        except Exception:
            return None

    async def _smart_search(self, query: str) -> str:
        """Deep search: fetch top pages, read content, summarize with reliability assessment."""
        pages = self._web_tool.deep_search(query, max_pages=5)
        if not pages:
            return "No results found for this query."

        formatted = self._web_tool.format_deep_results(pages)
        fetched_count = sum(1 for p in pages if p["fetched"])

        result = await self._model_gateway.generate_text(ModelRequest(messages=[
            MessagePart(role="system", content=self._SMART_SEARCH_PROMPT),
            MessagePart(
                role="user",
                content=f"Query: {query}\n\n{formatted}",
            ),
        ]))

        sources = "\n".join(
            f"  [{i}] {p['title']} - {p['url']}"
            for i, p in enumerate(pages, 1)
            if p["fetched"]
        )
        return f"{result}\n\nSources ({fetched_count} pages read):\n{sources}"

    async def _parse_travel_request(self, text: str) -> tuple[str, str, str] | None:
        try:
            import json
            raw = await self._model_gateway.generate_text(ModelRequest(messages=[
                MessagePart(role="system", content=self._TRAVEL_CLASSIFY_PROMPT),
                MessagePart(role="user", content=text),
            ]))
            cleaned = raw.strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            data = json.loads(cleaned[start:end])
            if not data.get("travel"):
                return None
            origin = data.get("origin", "").strip()
            destination = data.get("destination", "").strip()
            travel_date = data.get("date", "").strip()
            if not origin or not destination:
                return None
            return origin, destination, travel_date
        except Exception:
            return None

    async def _parse_weather_request(self, text: str) -> str | None:
        try:
            import json
            raw = await self._model_gateway.generate_text(ModelRequest(messages=[
                MessagePart(role="system", content=self._WEATHER_CLASSIFY_PROMPT),
                MessagePart(role="user", content=text),
            ]))
            cleaned = raw.strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            data = json.loads(cleaned[start:end])
            if not data.get("weather"):
                return None
            city = data.get("city", "").strip()
            return city if city else None
        except Exception:
            return None

    def _parse_duration_to_seconds(self, text: str) -> int:
        match = re.fullmatch(r"\s*(\d+)\s*([smhSMH]?)\s*", text)
        if match is None:
            raise ValueError("Reminder delay must look like 30s, 10m, or 2h.")
        amount = int(match.group(1))
        unit = (match.group(2) or "m").lower()
        if unit == "h":
            return amount * 3600
        if unit == "m":
            return amount * 60
        return amount

    @staticmethod
    def _format_reminder_confirmation(reminder: ReminderRecord, due_in_seconds: int) -> str:
        parts: list[str] = []
        remaining = due_in_seconds
        if remaining >= 3600:
            h = remaining // 3600
            parts.append(f"{h} hour{'s' if h > 1 else ''}")
            remaining %= 3600
        if remaining >= 60:
            m = remaining // 60
            parts.append(f"{m} minute{'s' if m > 1 else ''}")
            remaining %= 60
        if remaining > 0:
            parts.append(f"{remaining} second{'s' if remaining > 1 else ''}")
        delay_text = " ".join(parts) if parts else "0 seconds"
        return f"Reminder set for {delay_text}: {reminder.text}"

    @staticmethod
    def _split_title_body(payload: str) -> tuple[str, str]:
        if "|" not in payload:
            raise ValueError("Expected 'title | content'.")
        title, content = [part.strip() for part in payload.split("|", maxsplit=1)]
        if not title or not content:
            raise ValueError("Both title and content are required.")
        return title, content
