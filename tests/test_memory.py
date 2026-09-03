"""MemoryStream, Retriever scoring, and ReflectionEngine."""

from __future__ import annotations

from simulatecraft.memory import (
    HashingEmbedding,
    MemoryStream,
    ReflectionEngine,
    RetrievedMemory,
    Retriever,
)


async def test_stream_appends_with_ids_and_defaults() -> None:
    stream = MemoryStream()
    record = await stream.add("saw a fountain", kind="observation", sim_tick=3)
    assert record.id == "m1"
    assert record.importance == 3
    assert record.sim_tick == 3
    assert len(stream) == 1


async def test_stream_custom_scorer() -> None:
    def score(content: str, kind: str) -> int:
        return 10 if "fire" in content else 2

    stream = MemoryStream(scorer=score)
    assert (await stream.add("there is a fire")).importance == 10
    assert (await stream.add("all quiet")).importance == 2


async def test_stream_async_scorer() -> None:
    async def score(content: str, kind: str) -> int:
        return 7

    stream = MemoryStream(scorer=score)
    assert (await stream.add("anything")).importance == 7


async def test_importance_clamped_to_1_10() -> None:
    stream = MemoryStream()
    assert (await stream.add("x", importance=99)).importance == 10
    assert (await stream.add("y", importance=-5)).importance == 1


async def test_retriever_prefers_relevant_and_important() -> None:
    stream = MemoryStream()
    for i in range(6):
        await stream.add(f"chat about the bakery ovens {i}", kind="chat")
    await stream.add(
        "the mayor announced a festival at the fountain", kind="observation", importance=9
    )
    retriever = Retriever(stream, HashingEmbedding())
    hits = retriever.retrieve("what happened at the fountain?", top_k=2)
    assert hits
    assert isinstance(hits[0], RetrievedMemory)
    assert "fountain" in hits[0].record.content
    assert hits[0].score > hits[0].relevance


async def test_retriever_recency_weighting() -> None:
    stream = MemoryStream()
    await stream.add("old news about bread")
    await stream.add("fresh gossip about the fountain")
    retriever = Retriever(
        stream, HashingEmbedding(), w_relevance=0.0, w_importance=0.0, w_recency=1.0
    )
    hits = retriever.retrieve("whatever", top_k=2)
    assert hits[0].record.content.startswith("fresh")


async def test_reflection_triggers_and_stores_insights() -> None:
    async def summarizer(text: str) -> list[str]:
        return ["The agent keeps visiting the fountain."]

    engine = ReflectionEngine(summarizer, every_n_records=3, min_records=1)
    stream = MemoryStream()
    for i in range(3):
        await stream.add(f"event {i}")
    insights = await engine.reflect(stream)
    assert insights == ["The agent keeps visiting the fountain."]
    reflections = [r for r in stream.all() if r.kind == "reflection"]
    assert len(reflections) == 1
    assert reflections[0].importance == 9


async def test_should_respect_period() -> None:
    async def summarizer(text: str) -> list[str]:
        return []

    engine = ReflectionEngine(summarizer, every_n_records=4, min_records=1)
    stream = MemoryStream()
    for i in range(3):
        await stream.add(f"event {i}")
    assert not engine.should_reflect(stream)
    await stream.add("one more event")
    assert engine.should_reflect(stream)
