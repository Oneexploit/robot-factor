from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from robot_factor.adapters.base import HttpAdapter, PlatformApiError
from robot_factor.transport import IncomingEvent, OutboundMessage


class RubikaAdapter(HttpAdapter):
    platform = "rubika"

    @property
    def api_base(self) -> str:
        return f"https://botapi.rubika.ir/v3/{self.token}"

    def parse_events(
        self, payload: dict[str, Any], *, event_kind: str = "update"
    ) -> list[IncomingEvent]:
        source = payload.get("inline_message") if event_kind == "inline" else payload.get("update")
        source = source or payload.get("inline_message") or payload.get("update") or payload
        if not isinstance(source, dict):
            return []

        message = source.get("new_message") or source.get("updated_message") or source
        if not isinstance(message, dict):
            return []
        chat_id = source.get("chat_id") or message.get("chat_id")
        user_id = source.get("sender_id") or message.get("sender_id")
        if not chat_id or not user_id:
            return []
        aux_data = source.get("aux_data") or message.get("aux_data") or {}
        callback_data = aux_data.get("button_id") if isinstance(aux_data, dict) else None
        message_id = source.get("message_id") or message.get("message_id")
        update_id = source.get("update_id") or message_id
        if not update_id:
            canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            update_id = hashlib.sha256(canonical).hexdigest()
        if event_kind == "inline":
            update_id = f"inline:{update_id}:{callback_data or ''}"
        return [
            IncomingEvent(
                platform=self.platform,
                update_id=str(update_id),
                chat_id=str(chat_id),
                user_id=str(user_id),
                text=str(source.get("text") or message.get("text") or callback_data or ""),
                callback_data=str(callback_data) if callback_data is not None else None,
                raw=payload,
            )
        ]

    async def send(self, chat_id: str, message: OutboundMessage) -> None:
        if message.document_path:
            await self._send_document(chat_id, message.document_path, message.text)
            return
        payload: dict[str, Any] = {"chat_id": chat_id, "text": message.text}
        if message.buttons:
            payload["inline_keypad"] = {
                "rows": [
                    {
                        "buttons": [
                            {"id": button.data, "type": "Simple", "button_text": button.text}
                            for button in row
                        ]
                    }
                    for row in message.buttons
                ]
            }
        await self._post("sendMessage", json=payload)

    async def acknowledge(self, event: IncomingEvent) -> None:
        # Rubika does not require a separate acknowledgement call for Simple buttons.
        return None

    async def set_webhooks(self, update_url: str, inline_url: str) -> None:
        await self._post("updateBotEndpoints", json={"url": update_url, "type": "ReceiveUpdate"})
        await self._post(
            "updateBotEndpoints",
            json={"url": inline_url, "type": "ReceiveInlineMessage"},
        )

    async def get_updates(self, start_id: str | None = None) -> list[dict[str, Any]]:
        data: dict[str, Any] = {"limit": 100}
        if start_id:
            data["start_id"] = start_id
        result = await self._post("getUpdates", json=data)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            updates = result.get("updates") or result.get("data") or []
            return updates if isinstance(updates, list) else []
        return []

    async def _send_document(self, chat_id: str, path: Path, caption: str) -> None:
        upload_request = await self._post("requestSendFile", json={"type": "File"})
        if not isinstance(upload_request, dict):
            raise PlatformApiError("Rubika requestSendFile returned an invalid response")
        upload_url = upload_request.get("upload_url")
        if not upload_url:
            raise PlatformApiError("Rubika requestSendFile did not return upload_url")
        with path.open("rb") as document:
            response = await self.client.post(
                str(upload_url), files={"file": (path.name, document, "application/pdf")}
            )
        self._validate_http(response)
        uploaded = self.unwrap_response(response.json())
        if not isinstance(uploaded, dict) or not uploaded.get("file_id"):
            raise PlatformApiError("Rubika upload did not return file_id")
        await self._post(
            "sendFile",
            json={"chat_id": chat_id, "file_id": uploaded["file_id"], "text": caption},
        )

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
            raise PlatformApiError(f"Rubika API request failed: {body}") from error
