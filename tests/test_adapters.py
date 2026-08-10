from robot_factor.adapters.rubika import RubikaAdapter
from robot_factor.adapters.telegram import TelegramAdapter


def test_parses_telegram_callback() -> None:
    adapter = TelegramAdapter("token")
    events = adapter.parse_events(
        {
            "update_id": 10,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 1001},
                "message": {"chat": {"id": 1001}},
                "data": "new:invoice",
            },
        }
    )
    assert len(events) == 1
    assert events[0].callback_data == "new:invoice"
    assert events[0].user_id == "1001"


def test_parses_rubika_inline_message() -> None:
    adapter = RubikaAdapter("token")
    events = adapter.parse_events(
        {
            "inline_message": {
                "sender_id": "u-test",
                "chat_id": "chat-test",
                "message_id": "m-1",
                "aux_data": {"button_id": "finalize"},
            }
        },
        event_kind="inline",
    )
    assert len(events) == 1
    assert events[0].callback_data == "finalize"
    assert events[0].update_id == "inline:m-1:finalize"
