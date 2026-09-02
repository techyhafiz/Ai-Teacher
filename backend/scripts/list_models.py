"""List models available to this API key (embeddings + live-capable)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.gemini import client  # noqa: E402


async def main():
    c = client()
    res = await c.aio.models.list()
    for m in res:
        name = m.name or ""
        if any(k in name.lower() for k in ("flash-lite", "flash-la", "3.5-flash")):
            print(name)


asyncio.run(main())
