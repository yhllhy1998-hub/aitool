from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_PROBE = REPO_ROOT / ".agent" / "scripts" / "website_probe.py"


def load_module():
    spec = importlib.util.spec_from_file_location("website_probe", WEBSITE_PROBE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WebsiteProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_parse_proxy_supports_plain_host_port(self) -> None:
        proxy = self.module.parse_proxy("127.0.0.1:7897")
        self.assertEqual(proxy.host, "127.0.0.1")
        self.assertEqual(proxy.port, 7897)

    def test_parse_proxy_supports_http_url(self) -> None:
        proxy = self.module.parse_proxy("http://127.0.0.1:7897")
        self.assertEqual(proxy.host, "127.0.0.1")
        self.assertEqual(proxy.port, 7897)

    def test_parse_proxy_server_setting_handles_windows_map(self) -> None:
        proxies = self.module.parse_proxy_server_setting("http=127.0.0.1:7897;https=127.0.0.1:7897")
        self.assertEqual([proxy.display for proxy in proxies], ["127.0.0.1:7897"])

    def test_build_routes_defaults_to_direct_without_proxy(self) -> None:
        routes = self.module.build_routes([], include_direct=False)
        self.assertEqual([route.name for route in routes], ["direct"])

    def test_build_routes_keeps_direct_when_requested(self) -> None:
        routes = self.module.build_routes(["127.0.0.1:7897"], include_direct=True)
        self.assertEqual([route.name for route in routes], ["direct", "proxy_127_0_0_1_7897"])

    def test_parse_https_check_preserves_query(self) -> None:
        check = self.module.parse_https_check(
            "https://chatgpt.com/backend-api/ps/plugins/list?scope=GLOBAL&limit=1",
            index=1,
            method="GET",
            headers=(),
            body_text="",
        )
        self.assertEqual(check.host, "chatgpt.com")
        self.assertEqual(check.path, "/backend-api/ps/plugins/list?scope=GLOBAL&limit=1")
        self.assertEqual(check.method, "GET")

    def test_parse_wss_check_requires_wss_scheme(self) -> None:
        with self.assertRaises(ValueError):
            self.module.parse_wss_check("https://chatgpt.com/backend-api/codex/responses", index=1)

    def test_build_codex_suite_contains_expected_checks(self) -> None:
        checks = self.module.build_codex_suite("chatgpt.com", 443)
        names = [check.name for check in checks]
        self.assertEqual(
            names,
            [
                "root_head",
                "ps_plugins_list",
                "ps_plugins_installed",
                "ps_plugins_installed_workspace",
                "ps_mcp",
                "codex_responses_head",
                "codex_responses_wss",
            ],
        )

    def test_classify_result_marks_http_response_as_reachable(self) -> None:
        outcome = self.module.classify_result({"kind": "http", "response_line": "HTTP/1.1 451 Unavailable For Legal Reasons"})
        self.assertEqual(outcome, "reachable")

    def test_classify_result_marks_tls_failure_as_error(self) -> None:
        outcome = self.module.classify_result({"kind": "wss", "tls_error": "SSLEOFError"})
        self.assertEqual(outcome, "error")


if __name__ == "__main__":
    unittest.main()
