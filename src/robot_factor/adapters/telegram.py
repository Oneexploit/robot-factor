from __future__ import annotations

from pathlib import Path
from typing import Any

from robot_factor.adapters.base import HttpAdapter, PlatformApiError
from robot_factor.transport import IncomingEvent, OutboundMessage


class TelegramAdapter(HttpAdapter):
    platform = "telegram"

    @property
    def api_base(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def parse_events(
        self, payload: dict[str, Any], *, event_kind: str = "update"
    ) -> list[IncomingEvent]:
        update_id = str(payload.get("update_id", "missing"))
        if callback := payload.get("callback_query"):
            message = callback.get("message") or {}
            chat = message.get("chat") or {}
            sender = callback.get("from") or {}
            if "id" not in chat or "id" not in sender:
                return []
            return [
                IncomingEvent(
                    platform=self.platform,
                    update_id=update_id,
                    chat_id=str(chat["id"]),
                    user_id=str(sender["id"]),
                    text=str(callback.get("data") or ""),
                    callback_data=str(callback.get("data") or ""),
                    callback_query_id=str(callback.get("id") or ""),
                    raw=payload,
                )
            ]

        message = payload.get("message") or payload.get("edited_message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if "id" not in chat or "id" not in sender:
            return []
        text = message.get("text") or message.get("caption") or ""
        return [
            IncomingEvent(
                platform=self.platform,
                update_id=update_id,
                chat_id=str(chat["id"]),
                user_id=str(sender["id"]),
                text=str(text),
                raw=payload,
            )
        ]

    async def send(self, chat_id: str, message: OutboundMessage) -> None:
        if message.document_path:
            await self._send_document(chat_id, message.document_path, message.text)
            return
        payload: dict[str, Any] = {"chat_id": chat_id, "text": message.text}
        if message.buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": button.text, "callback_data": button.data} for button in row]
                    for row in message.buttons
                ]
            }
        await self._post("sendMessage", json=payload)

    async def acknowledge(self, event: IncomingEvent) -> None:
        if event.callback_query_id:
            await self._post(
                "answerCallbackQuery",
                json={"callback_query_id": event.callback_query_id},
            )

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self._post(
            "setWebhook",
            json={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
        )

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict[str, Any]]:
        data: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            data["offset"] = offset
        result = await self._post("getUpdates", json=data)
        return result if isinstance(result, list) else []

    async def _send_document(self, chat_id: str, path: Path, caption: str) -> None:
        with path.open("rb") as document:
            response = await self.client.post(
                f"{self.api_base}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (path.name, document, "application/pdf")},
            )
        self._validate_http(response)

    async def _post(self, method: str, **kwargs: Any) -> Any:
        response = await self.client.post(f"{self.api_base}/{method}", **kwargs)
        self._validate_http(response)
        return self.unwrap_response(response.json())

    @staticmethod
    def _validate_http(response: Any) -> None:
        try:
            response.raise_for_status()
        except Exception as error:
            body = response.text[:1000]
            raise PlatformApiError(f"Telegram API request failed: {body}") from error
