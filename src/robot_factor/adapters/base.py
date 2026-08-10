from __future__ import annotations

from typing import Any

import httpx


class PlatformApiError(RuntimeError):
    pass


class HttpAdapter:
    def __init__(self, token: str, *, timeout: float = 30.0) -> None:
        self.token = token
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    @staticmethod
    def unwrap_response(payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload
        if payload.get("ok") is False or payload.get("status") == "ERROR":
            raise PlatformApiError(str(payload.get("description") or payload))
        for key in ("data", "result"):
            if key in payload:
                return payload[key]
        return payload
