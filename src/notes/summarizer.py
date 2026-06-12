"""LLM-powered meeting summarizer — turns transcripts into structured notes."""
import json
import time
from dataclasses import dataclass, field
from typing import List

from openai import OpenAI, APITimeoutError, APIConnectionError, RateLimitError
from src.audio.transcriber import TranscriptionSegment
from src.config import settings, RunMode

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]
_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError)


@dataclass
class MeetingSummary:
    title: str
    date: str
    duration_minutes: int
    participants: List[str]
    key_topics: List[str]
    decisions: List[str]
    action_items: List[dict]
    full_transcript: str
    summary: str


SYSTEM_PROMPT = """You are a meeting notes assistant. Given a meeting transcript, produce a structured JSON summary with these fields:
- "title": short meeting title
- "key_topics": list of topics discussed
- "decisions": list of decisions made
- "action_items": list of objects with "assignee", "task", "deadline"
- "summary": 2-3 paragraph executive summary

Respond with ONLY valid JSON, no markdown fences or commentary."""


class Summarizer:
    """Summarizes meeting transcripts using an LLM via the OpenAI-compatible API."""

    def __init__(self):
        llm_config = settings.get_llm_config()
        self._client = OpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config["base_url"],
        )
        self._model = llm_config["model"]
        self._transcript_buffer: List[TranscriptionSegment] = []

    def add_segments(self, segments: List[TranscriptionSegment]) -> None:
        self._transcript_buffer.extend(segments)

    def build_raw_transcript(self) -> str:
        if not self._transcript_buffer:
            return ""
        lines = []
        for seg in self._transcript_buffer:
            m, s = divmod(int(seg.start), 60)
            lines.append(f"[{m:02d}:{s:02d}] {seg.text}")
        return "\n".join(lines)

    def generate_summary(self) -> MeetingSummary:
        transcript = self.build_raw_transcript()

        if settings.mode == RunMode.TRANSCRIPT_ONLY:
            return MeetingSummary(
                title="Meeting Transcript",
                date="",
                duration_minutes=0,
                participants=[],
                key_topics=[],
                decisions=[],
                action_items=[],
                full_transcript=transcript,
                summary="[Transcript-only mode — no LLM summary generated]",
            )

        prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{transcript}"

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    temperature=settings.llm_temperature,
                    timeout=120,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                )
                break
            except _RETRYABLE as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    print(f"LLM request failed ({e}), retrying in {wait}s...")
                    time.sleep(wait)
        else:
            print(f"LLM request failed after {MAX_RETRIES} attempts: {last_error}")
            return MeetingSummary(
                title="Untitled Meeting",
                date="",
                duration_minutes=0,
                participants=[],
                key_topics=[],
                decisions=[],
                action_items=[],
                full_transcript=transcript if settings.mode != RunMode.SUMMARY_ONLY else "",
                summary=f"LLM summarization failed: {last_error}",
            )

        content = response.choices[0].message.content or ""

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return MeetingSummary(
                title="Untitled Meeting",
                date="",
                duration_minutes=0,
                participants=[],
                key_topics=[],
                decisions=[],
                action_items=[],
                full_transcript=transcript if settings.mode != RunMode.SUMMARY_ONLY else "",
                summary=content or "Failed to parse summary",
            )

        return MeetingSummary(
            title=data.get("title", "Untitled Meeting"),
            date="",
            duration_minutes=0,
            participants=data.get("participants", []),
            key_topics=data.get("key_topics", []),
            decisions=data.get("decisions", []),
            action_items=data.get("action_items", []),
            full_transcript=transcript if settings.mode != RunMode.SUMMARY_ONLY else "",
            summary=data.get("summary", ""),
        )
