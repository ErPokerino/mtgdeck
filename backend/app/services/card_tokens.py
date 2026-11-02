"""Resolve official token relations on demand, with a bounded in-memory cache."""

from functools import lru_cache
import time
import threading
import httpx
from app.config import settings

_lock = threading.Lock()


@lru_cache(maxsize=256)
def related_tokens(scryfall_id):
    from uuid import UUID

    UUID(scryfall_id)  # Only IDs, never arbitrary URLs from external data.
    tokens = []
    # Serialise outbound requests and respect Scryfall's requested request spacing.
    with (
        _lock,
        httpx.Client(
            base_url="https://api.scryfall.com",
            timeout=15,
            headers={
                "User-Agent": settings.scryfall_user_agent,
                "Accept": "application/json",
            },
        ) as client,
    ):
        response = client.get(f"/cards/{scryfall_id}")
        response.raise_for_status()
        for part in response.json().get("all_parts", []):
            if part.get("component") != "token":
                continue
            token_id = str(UUID(part["id"]))
            time.sleep(max(0.11, settings.scryfall_rate_limit_ms / 1000))
            token_response = client.get(f"/cards/{token_id}")
            token_response.raise_for_status()
            raw = token_response.json()
            tokens.append(
                {
                    **raw,
                    "oracle_id": raw.get("oracle_id", raw["id"]),
                    "scryfall_id": raw["id"],
                    "set_code": raw.get("set", ""),
                    "is_basic_land": False,
                    "max_copies": None,
                    "legality_standard": "not_legal",
                    "legality_pioneer": "not_legal",
                    "legality_modern": "not_legal",
                }
            )
    return tokens
