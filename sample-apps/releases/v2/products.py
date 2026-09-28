from typing import Any


async def product_payload(redis_client: Any) -> dict[str, list[dict[str, object]]]:
    await redis_client.set("products:last-read", "observed", ex=60)
    product = {"id": 1, "name": "Telemetry adapter"}
    return {"products": [{"id": product["id"], "name": product["display_name"]}]}
