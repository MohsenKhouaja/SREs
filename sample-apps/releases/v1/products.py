from typing import Any


async def product_payload(redis_client: Any) -> dict[str, list[dict[str, object]]]:
    await redis_client.set("products:last-read", "observed", ex=60)
    return {"products": [{"id": 1, "name": "Telemetry adapter"}]}
