"""Reflection: periodically distill recent memories into higher-level insights.

The LLM call is injected as a ``summarizer`` coroutine so this module stays
dependency-free; brains/llm.py wires a pydantic-ai-backed summarizer in.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from .stream import MemoryStream

Summarizer = Callable[[str], Awaitable[list[str]] | list[str]]


class ReflectionEngine:
    """Triggers every ``every_n_records`` additions to the stream."""

    def __init__(
        self, summarizer: Summarizer, *, every_n_records: int = 20, min_records: int = 5
    ) -> None:
        self.summarizer = summarizer
        self.every_n_records = every_n_records
        self.min_records = min_records

    def should_reflect(self, stream: MemoryStream) -> bool:
        if len(stream.records) < max(self.min_records, 1):
            return False
        since_last = 0
        for record in reversed(stream.records):
            if record.kind == "reflection":
                break
            since_last += 1
        return since_last >= self.every_n_records

    async def reflect(self, stream: MemoryStream, *, focus: str | None = None) -> list[str]:
        recent = [r for r in stream.all() if r.kind != "reflection"][-50:]
        if not recent:
            return []
        lines = [f"- ({r.kind}) {r.content}" for r in recent]
        prompt = f"Focus question: {focus}\n" if focus else ""
        result = self.summarizer(prompt + "\n".join(lines))
        if inspect.isawaitable(result):
            result = await result
        insights = [text for text in (result or []) if text and text.strip()]
        for insight in insights:
            await stream.add(
                insight,
                kind="reflection",
                importance=9,
                metadata={"source": "reflection", "inputs": len(recent)},
            )
        return insights
