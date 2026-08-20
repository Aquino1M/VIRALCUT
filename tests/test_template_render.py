import unittest
from unittest.mock import patch

from starlette.requests import Request

from app import main


class TemplateRenderCompatibilityTest(unittest.TestCase):
    def test_render_uses_new_starlette_template_response_signature(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "session": {},
        }
        request = Request(scope)
        captured = {}

        def strict_template_response(*args, **kwargs):
            # Simulates Starlette versions where request/name must not use the
            # deprecated name-first positional call.
            if args:
                raise TypeError("TemplateResponse requires request/name keyword-safe signature")
            captured.update(kwargs)
            return kwargs

        with patch.object(main, "current_user", return_value=None), patch.object(
            main.templates, "TemplateResponse", side_effect=strict_template_response
        ):
            main.render(request, "landing.html", answer=42)

        self.assertIs(captured["request"], request)
        self.assertEqual(captured["name"], "landing.html")
        self.assertIs(captured["context"]["request"], request)
        self.assertEqual(captured["context"]["answer"], 42)


if __name__ == "__main__":
    unittest.main()
