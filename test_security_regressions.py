#!/usr/bin/env python3
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class SecurityRegressionTest(unittest.TestCase):
    def test_restart_command_requires_admin_permission(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        match = re.search(
            r"(?P<decorators>(?:\s*@filter\.[^\n]+\n)+)\s*async def Hermes重启指令",
            source,
        )
        self.assertIsNotNone(match)
        self.assertIn("permission_type", match.group("decorators"))
        self.assertIn("PermissionType.ADMIN", match.group("decorators"))

    def test_command_server_rejects_empty_token_on_public_bind(self):
        source = (ROOT / "http_server.py").read_text(encoding="utf-8")

        self.assertIn("_is_loopback_host", source)
        self.assertIn("空 token", source)
        self.assertNotIn("if not token:\n            return True", source)


if __name__ == "__main__":
    unittest.main()
