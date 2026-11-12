import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

with patch("zoneinfo.ZoneInfo", return_value=timezone.utc):
    import api_whatsapp


class WhatsappHistoryTests(unittest.IsolatedAsyncioTestCase):
    @patch("api_whatsapp.requests.post")
    async def test_fetches_a_paginated_evolution_message_window(self, post):
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "messages": {
                "pages": 3,
                "records": [{"key": {"id": "message-1"}}],
            }
        }
        post.return_value = response
        since = datetime(2026, 11, 1, tzinfo=timezone.utc)
        through = datetime(2026, 11, 2, tzinfo=timezone.utc)

        records, pages = await api_whatsapp._fetch_evolution_message_page(
            "http://evolution:8080",
            "secret",
            "support",
            since,
            through,
            page=2,
            page_size=100,
        )

        self.assertEqual(records, [{"key": {"id": "message-1"}}])
        self.assertEqual(pages, 3)
        self.assertEqual(post.call_args.args[0], "http://evolution:8080/chat/findMessages/support")
        self.assertEqual(post.call_args.kwargs["headers"]["apikey"], "secret")
        self.assertEqual(post.call_args.kwargs["json"]["page"], 2)
        self.assertEqual(post.call_args.kwargs["json"]["offset"], 100)
        self.assertEqual(
            post.call_args.kwargs["json"]["where"]["messageTimestamp"],
            {"gte": since.isoformat(), "lte": through.isoformat()},
        )

    def test_parses_evolution_epoch_timestamps_as_utc(self):
        self.assertEqual(
            api_whatsapp._whatsapp_message_datetime("1793577600"),
            datetime(2026, 11, 2, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
