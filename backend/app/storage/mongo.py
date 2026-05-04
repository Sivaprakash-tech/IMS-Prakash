from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

SIGNALS_COLLECTION = "raw_signals"


def init_client() -> AsyncIOMotorClient:
    global _client, _db
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)
        _db = _client[settings.mongo_db]
    return _client


async def close_client() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


def signals() -> AsyncIOMotorCollection:
    if _db is None:
        init_client()
    assert _db is not None
    return _db[SIGNALS_COLLECTION]


async def ensure_indexes() -> None:
    coll = signals()
    await coll.create_index("component_id")
    await coll.create_index("timestamp")
    await coll.create_index("work_item_id")


async def insert_signal(doc: dict[str, Any]) -> str:
    result = await signals().insert_one(doc)
    return str(result.inserted_id)


async def find_signals_by_work_item(work_item_id: int, limit: int = 500) -> list[dict[str, Any]]:
    cursor = signals().find({"work_item_id": work_item_id}).sort("timestamp", -1).limit(limit)
    docs: list[dict[str, Any]] = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


async def ping() -> bool:
    if _client is None:
        init_client()
    assert _client is not None
    result = await _client.admin.command("ping")
    return bool(result.get("ok"))
