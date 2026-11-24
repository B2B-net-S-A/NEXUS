"""Duża wiadomość przez prawdziwy LISTEN/NOTIFY: kawałki w jednej transakcji, sklejenie u odbiorcy."""
import asyncio
import os

os.environ["NEXUS_PROCESS_ROLE"] = "web"

from app.core import process_bus  # noqa: E402

got: list[dict] = []


async def handler(data: dict) -> None:
    got.append(data)


async def main() -> None:
    process_bus.subscribe("probe_big", handler)  # bez others_only: własna wiadomość też
    listener = asyncio.create_task(process_bus.process_bus_loop())
    await asyncio.sleep(2)
    content = "Zażółć gęślą jaźń. " * 600  # ok. 11 400 znaków, ok. 15 kB w UTF-8
    sent = await process_bus.publish("probe_big", {"content": content})
    for _ in range(50):
        if got:
            break
        await asyncio.sleep(0.1)
    parts = len(process_bus.notify_payloads(content) or [])
    print(f"wysłane: {sent}; kawałków ok. {parts}; doszło: {len(got)}; treść zgodna: {bool(got) and got[0]['content'] == content}")
    listener.cancel()


asyncio.run(main())
