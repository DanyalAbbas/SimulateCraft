"""EventBus pub/sub correctness: ordering, isolation, inbound channel."""

from __future__ import annotations

import asyncio

from simulatecraft.core import (
    AgentActed,
    AgentSpoke,
    EventBus,
    HumanChat,
    HumanControl,
    SimulationStarted,
)


async def test_subscribe_receives_published_events(bus: EventBus) -> None:
    seen: list[object] = []
    bus.subscribe(seen.append)
    event = await bus.publish(SimulationStarted(agent_ids=["a"]))
    assert seen == [event]
    assert event.kind == "simulation.started"


async def test_events_get_sequential_seq_and_timestamp(bus: EventBus) -> None:
    bus.subscribe(lambda e: None)
    first = await bus.publish(SimulationStarted())
    second = await bus.publish(SimulationStarted())
    assert second.seq > first.seq
    assert first.timestamp > 0


async def test_unsubscribe_stops_delivery(bus: EventBus) -> None:
    seen: list[object] = []
    unsubscribe = bus.subscribe(seen.append)
    await bus.publish(SimulationStarted())
    unsubscribe()
    await bus.publish(SimulationStarted())
    assert len(seen) == 1


async def test_once_handler_fires_exactly_once(bus: EventBus) -> None:
    seen: list[object] = []
    bus.subscribe(seen.append, once=True)
    await bus.publish(SimulationStarted())
    await bus.publish(SimulationStarted())
    assert len(seen) == 1


async def test_handler_exception_does_not_break_other_subscribers(bus: EventBus) -> None:
    seen: list[object] = []

    def boom(event: object) -> None:
        raise RuntimeError("boom")

    bus.subscribe(boom)
    bus.subscribe(seen.append)
    await bus.publish(SimulationStarted())
    assert len(seen) == 1


async def test_async_handlers_are_awaited_in_order(bus: EventBus) -> None:
    order: list[str] = []

    async def slow(event: object) -> None:
        await asyncio.sleep(0.01)
        order.append("slow")

    def fast(event: object) -> None:
        order.append("fast")

    bus.subscribe(slow)
    bus.subscribe(fast)
    await bus.publish(SimulationStarted())
    assert order == ["slow", "fast"]


async def test_tick_stamp_applied_when_requested(bus: EventBus) -> None:
    seen: list[object] = []
    bus.subscribe(seen.append)
    await bus.publish(AgentActed(agent_id="a"), tick=7)
    assert seen[0].tick == 7


async def test_restamp_false_preserves_original_fields(bus: EventBus) -> None:
    original = await bus.publish(AgentSpoke(agent_id="a", text="hi"))
    seen: list[object] = []
    bus.subscribe(seen.append)
    replayed = await bus.publish(original, restamp=False)
    assert replayed.seq == original.seq
    assert replayed.timestamp == original.timestamp


async def test_inbound_queue_roundtrip(bus: EventBus) -> None:
    bus.publish_inbound(HumanChat(sender="v", target_agent_id="maya", text="hello"))
    bus.publish_inbound(HumanControl(command="pause"))
    events = await bus.drain_inbound()
    assert [type(e).__name__ for e in events] == ["HumanChat", "HumanControl"]
    assert await bus.drain_inbound() == []


def test_inbound_from_other_thread(bus: EventBus) -> None:
    import threading

    received: list[str] = []

    async def consume() -> None:
        while True:
            events = await bus.drain_inbound()
            if events:
                received.extend(e.text for e in events if isinstance(e, HumanChat))
                return
            await asyncio.sleep(0.01)

    async def main() -> None:
        task = asyncio.create_task(consume())
        thread = threading.Thread(target=bus.publish_inbound, args=(HumanChat(text="from-thread"),))
        thread.start()
        thread.join()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(main())
