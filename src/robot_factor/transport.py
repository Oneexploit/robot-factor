from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Button:
    text: str
    data: str


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    platform: str
    update_id: str
    chat_id: str
    user_id: str
    text: str = ""
    callback_data: str | None = None
    callback_query_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    text: str = ""
    buttons: tuple[tuple[Button, ...], ...] = ()
    document_path: Path | None = None
    document_invoice_id: int | None = None


class PlatformAdapter(Protocol):
    platform: str

    def parse_events(
        self, payload: dict[str, Any], *, event_kind: str = "update"
    ) -> list[IncomingEvent]: ...

    async def send(self, chat_id: str, message: OutboundMessage) -> None: ...

    async def acknowledge(self, event: IncomingEvent) -> None: ...

    async def close(self) -> None: ...
