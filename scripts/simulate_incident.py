"""Generate safe local load against the deliberately slow detailed orders route."""
import asyncio
import sys

import httpx


async def hit(client: httpx.AsyncClient, base: str) -> None:
    await client.get(f"{base.rstrip('/')}/orders?include_customer_profile=true")


async def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
    async with httpx.AsyncClient(timeout=8) as client:
        results = await asyncio.gather(*(hit(client, base) for _ in range(12)), return_exceptions=True)
    print(f"Completed {len(results)} local requests. Now click 'Check metrics & diagnose' in Sentinel.")


if __name__ == "__main__":
    asyncio.run(main())
