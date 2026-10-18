"""Safe HTTP boundaries and documented traditional billing API contracts."""
import asyncio
from http.cookies import SimpleCookie
import json
import unittest
from unittest.mock import MagicMock

import aiohttp
from yarl import URL

from starbridge.billing_client import BillingAPIError, MAX_RESPONSE, MofangClient


PROVIDER = {"name": "示例服务商", "base_url": "https://billing.example.com/subdir"}
SECRET = "Do-Not-Expose-Api-Password-763!"
CREDENTIALS = {"account": "client@example.com", "api_key": SECRET}


def response(data=None, status=200, **extra):
    return {"status": status, "data": {} if data is None else data, **extra}


class AdapterClient(MofangClient):
    def __init__(self, responses, *, cookies=False, authenticated=False, currency=None):
        super().__init__(PROVIDER, CREDENTIALS)
        self.responses, self.calls = list(responses), []
        self.cookies = cookies
        self._authenticated = authenticated
        self._currency_id = currency

    def _has_cookies(self):
        return self.cookies

    async def _transport(self, method, path, params=None, data=None):
        self.calls.append((method, path, params, data))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, tuple):
            return item
        return 200, json.dumps(item).encode()


class FakeResponse:
    def __init__(self, chunks, *, status=200, length=None):
        self.status, self.content_length = status, length
        self.chunks, self.reads = chunks, 0
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def iter_chunked(self, _):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk


class BillingHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_returns_original_envelope_and_strict_business_status(self):
        original = response({"product_groups": []}, status="200", jwt="jwt-value")
        client = AdapterClient([original])
        self.assertEqual(await client.request("GET", "/v1/products"), original)
        for status in (True, 200.0, "0200", 0, "success", None):
            with self.subTest(status=status), self.assertRaises(BillingAPIError):
                await AdapterClient([response(status=status)]).request("GET", "/v1/products")

    async def test_network_and_post_errors_are_safe_and_never_retried(self):
        for failure in (asyncio.TimeoutError(SECRET), aiohttp.ClientConnectionError(SECRET), OSError(SECRET),
                        (500, SECRET.encode()), (302, SECRET.encode()), (200, SECRET.encode()),
                        (200, b"[]"), response(status=400, msg=SECRET)):
            client = AdapterClient([failure])
            with self.subTest(failure=type(failure)), self.assertRaises(BillingAPIError) as caught:
                await client.request("POST", "/v1/pay", data={"password": SECRET})
            self.assertTrue(caught.exception.uncertain)
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertEqual(len(client.calls), 1)

    async def test_authentication_failure_never_echoes_error_response(self):
        for status in (401, 403):
            with self.subTest(status=status), self.assertRaises(BillingAPIError) as caught:
                await AdapterClient([(status, SECRET.encode())]).request("POST", "/v1/login_api")
            self.assertFalse(caught.exception.uncertain)
            self.assertNotIn(SECRET, str(caught.exception))

    async def test_arbitrary_hosts_query_paths_and_mutating_verbs_are_rejected(self):
        client = AdapterClient([])
        for method, path in (("DELETE", "/v1/pay"), ("GET", "https://other.com/v1/user"),
                             ("GET", "//other.com/v1/user"), ("GET", "/v1/../user"),
                             ("GET", "/v1/user?password=" + SECRET), ("GET", "/v1//user")):
            with self.subTest(method=method, path=path), self.assertRaises(BillingAPIError):
                await client.request(method, path)
        self.assertEqual(client.calls, [])

    async def test_transport_caps_header_and_streamed_response_lengths(self):
        for reply in (FakeResponse([], length=MAX_RESPONSE + 1),
                      FakeResponse([b"x" * MAX_RESPONSE, b"x"])):
            client = MofangClient(PROVIDER, CREDENTIALS)
            client.session = MagicMock()
            client.session.request.return_value = reply
            with self.subTest(length=reply.content_length), self.assertRaises(BillingAPIError) as caught:
                await client.request("POST", "/v1/pay")
            self.assertTrue(caught.exception.uncertain)
            self.assertLessEqual(reply.reads, 2)

    async def test_transport_disables_redirects_and_sends_jwt_only_to_provider(self):
        client = MofangClient(PROVIDER, CREDENTIALS)
        client.session = MagicMock()
        reply = FakeResponse([json.dumps(response()).encode()])
        client.session.request.return_value = reply
        client._jwt = "test-jwt"
        await client.request("GET", "/v1/user")
        args, kwargs = client.session.request.call_args
        self.assertEqual(args, ("GET", PROVIDER["base_url"] + "/v1/user"))
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(kwargs["headers"], {"Authorization": "JWT test-jwt"})
        redirect = FakeResponse([SECRET.encode()], status=302)
        client.session.request.return_value = redirect
        with self.assertRaises(BillingAPIError):
            await client.request("GET", "/v1/user")
        self.assertEqual(redirect.reads, 0)

    async def test_each_context_has_its_own_session_cookies_and_closed_resources(self):
        first, second = MofangClient(PROVIDER, CREDENTIALS), MofangClient(PROVIDER, CREDENTIALS)
        async with first, second:
            self.assertIsNot(first.session, second.session)
            self.assertIsNot(first.session.cookie_jar, second.session.cookie_jar)
            self.assertFalse(first.session.trust_env)
            self.assertEqual(first.session.timeout.total, 15)
            first.session.cookie_jar.update_cookies({"cart": "private-cookie"})
            self.assertFalse(second.session.cookie_jar.filter_cookies(URL(PROVIDER["base_url"])))
            session = first.session
        self.assertTrue(session.closed)
        self.assertIsNone(first.session)
        self.assertIsNone(first._resolver)

    async def test_cookie_authentication_respects_subdirectory_api_path(self):
        async with MofangClient(PROVIDER, CREDENTIALS) as client:
            cookie = SimpleCookie("session=private-session; Path=/subdir/; Secure")
            client.session.cookie_jar.update_cookies(cookie, response_url=URL(PROVIDER["base_url"] + "/zjmf_api_login"))
            self.assertTrue(client._has_cookies())
            client.session.cookie_jar.clear()
            wrong_path = SimpleCookie("session=unrelated-session; Path=/elsewhere/; Secure")
            client.session.cookie_jar.update_cookies(wrong_path, response_url=URL(PROVIDER["base_url"] + "/zjmf_api_login"))
            self.assertFalse(client._has_cookies())

    async def test_login_uses_documented_credentials_and_checks_remote_identity(self):
        client = AdapterClient([response(jwt="api-jwt"), response({"id": 42, "email": CREDENTIALS["account"]})])
        profile = await client.login()
        self.assertEqual(profile["id"], "42")
        self.assertEqual(client._jwt, "api-jwt")
        self.assertEqual(client.calls, [("POST", "/zjmf_api_login", None,
                                         {"username": CREDENTIALS["account"], "password": SECRET}),
                                        ("GET", "/user_info", None, None)])

    async def test_missing_jwt_and_invalid_remote_id_are_rejected_without_secrets(self):
        for replies in ([response(msg=SECRET)], [response(jwt="bad\n" + SECRET)],
                        [response(jwt="jwt"), response({"id": True})],
                        [response(jwt="jwt"), response({"id": "../" + SECRET})]):
            with self.subTest(count=len(replies)), self.assertRaises(BillingAPIError) as caught:
                await AdapterClient(replies).login()
            self.assertNotIn(SECRET, str(caught.exception))

    def test_amount_rejects_unbounded_exponent_expansion_and_invalid_values(self):
        for value in ("1e-999999999", "0e-999999999", "NaN", "Infinity", "-1", "1e1000", True, "1" * 129):
            with self.subTest(value=value), self.assertRaises(BillingAPIError):
                MofangClient._amount(value)
        self.assertEqual(MofangClient._amount("12.30"), "12.30")

    async def test_constructor_rejects_non_public_or_non_https_providers(self):
        for url in ("http://example.com", "https://127.0.0.1", "https://localhost", "https://example.com/v1"):
            with self.subTest(url=url), self.assertRaises(BillingAPIError):
                MofangClient({"base_url": url}, CREDENTIALS)

    async def test_login_cookie_session_requires_verified_email_or_phone_not_display_name(self):
        for info, expected in (({"email": "Client@Example.com"}, "email:client@example.com"),
                               ({"phonenumber": "+86 138-0013-8000"}, "phone:8613800138000"),
                               ({"uid": 43}, "43")):
            client = AdapterClient([response(), response(info)], cookies=True)
            self.assertEqual((await client.login())["id"], expected)
            self.assertTrue(client._authenticated)
        client = AdapterClient([response(), response({"username": "Display Name"})], cookies=True)
        with self.assertRaises(BillingAPIError):
            await client.login()
        self.assertFalse(client._authenticated)

    async def test_business_methods_require_verified_login(self):
        client = AdapterClient([])
        for operation in (client.products(), client.detail(12), client.quote({}), client.create_order({}, "alipay"),
                          client.gateways(), client.invoice(1), client.pay(1, "alipay")):
            with self.assertRaises(BillingAPIError):
                await operation
        self.assertEqual(client.calls, [])

    async def test_catalog_and_detail_preserve_documented_frontend_data_shapes(self):
        catalog = {"first_groups": [{"id": 1, "name": "云服务"}], "product_groups": [{"id": 2}], "products": [{"id": 12}]}
        detail = {"products": {"id": 12, "name": "云主机"}}
        client = AdapterClient([response(catalog), response(detail)], authenticated=True)
        self.assertEqual(await client.products(first_group_id=1, group_id=2), catalog)
        self.assertEqual(await client.detail(12), detail)
        self.assertEqual(client.calls, [("GET", "/cart/index", {"first_gid": "1", "gid": "2"}, None),
                                        ("GET", "/cart/get_product_config", {"pid": "12"}, None)])

    async def test_quote_encodes_only_whitelisted_fields_and_keeps_decimal_amount(self):
        client = AdapterClient([response({"total": "12.30", "currency": "CNY"})], authenticated=True)
        product = {"pid": 12, "billingcycle": "monthly", "qty": 2,
                   "configoption": {"3": "4"}, "customfield": {"5": "hostname"}, "os": {"6": "Ubuntu 22.04"}}
        self.assertEqual(await client.quote(product), {"total": "12.30", "currency": "CNY"})
        self.assertEqual(client.calls, [("POST", "/cart/get_total", None,
                                         {"pid": "12", "billingcycle": "monthly", "qty": "2",
                                          "configoption[3]": "4", "customfield[5]": "hostname", "os[6]": "Ubuntu 22.04"})])
        for malformed in ({**product, "checkout": "1"}, {**product, "qty": True},
                          {**product, "customfield": {"5]unsafe[": "x"}}, {**product, "os": "6"}):
            with self.assertRaises(BillingAPIError):
                await client.quote(malformed)
        self.assertEqual(len(client.calls), 1)

    async def test_frontend_top_level_catalog_and_price_shapes_are_supported(self):
        catalog = {"status": 200, "msg": SECRET, "first_groups": [{"id": 1}], "product_groups": [], "products": []}
        quote = {"status": 200, "currency": {"code": "CNY"}, "products": {"sale_total": "9.90", "total": "10.00"}}
        client = AdapterClient([catalog, quote], authenticated=True)
        self.assertEqual(await client.products(), {"first_groups": [{"id": 1}], "product_groups": [], "products": []})
        result = await client.quote({"pid": 12, "billingcycle": "monthly", "qty": 1})
        self.assertEqual(result["total"], "9.90")
        self.assertEqual(result["currency"], {"code": "CNY"})

    async def test_order_settles_only_the_position_just_added_without_clearing_cart(self):
        client = AdapterClient([response({"i": 0}), response({"invoiceid": 101, "orderid": 202})], authenticated=True, currency="1")
        product = {"pid": 12, "billingcycle": "monthly", "qty": 1}
        self.assertEqual(await client.create_order(product, "alipay"), {"invoiceid": "101", "orderid": "202"})
        self.assertEqual(client.calls, [("POST", "/cart/add_to_shop", None,
                                         {"pid": "12", "billingcycle": "monthly", "qty": "1", "checkout": "0", "currencyid": "1"}),
                                        ("POST", "/cart/settle", None, {"payment": "alipay", "pos[]": "0"})])

    async def test_missing_position_and_uncertain_checkout_response_never_retry(self):
        for replies in ([response({})], [response({"i": 0}), response({})],
                        [response({"i": 0}), response([])],
                        [response({"i": 0}), aiohttp.ClientConnectionError(SECRET)]):
            client = AdapterClient(replies, authenticated=True, currency="1")
            with self.subTest(count=len(replies)), self.assertRaises(BillingAPIError) as caught:
                await client.create_order({"pid": 12, "billingcycle": "monthly", "qty": 1}, "alipay")
            self.assertTrue(caught.exception.uncertain)
            self.assertLessEqual(len(client.calls), 2)
            self.assertNotIn(SECRET, str(caught.exception))

    async def test_gateways_invoice_and_payment_use_documented_endpoints(self):
        client = AdapterClient([response([{"id": 1, "name": "alipay", "title": "支付宝", "module": "x"}]),
                                response({"invoices": [{"id": 101, "status": "Unpaid", "subtotal": "12.30"}], "host": []}),
                                response({"pay_html": {"type": "url", "data": "https://qr.alipay.com/abc"}})], authenticated=True)
        self.assertEqual(await client.gateways(), [{"name": "alipay", "title": "支付宝"}])
        self.assertEqual((await client.invoice(101))["status"], "Unpaid")
        self.assertEqual((await client.pay(101, "alipay"))["_pay_html"],
                         {"type": "url", "data": "https://qr.alipay.com/abc"})
        self.assertEqual(client.calls, [("GET", "/get_gateways/gateways/", None, None),
                                        ("GET", "/invoices/101", None, None),
                                        ("POST", "/start_pay", None, {"invoiceid": "101", "payment": "alipay"})])

    async def test_invoice_never_accepts_another_returned_invoice(self):
        client = AdapterClient([response({"invoices": [{"id": 999, "status": "Paid"}]})], authenticated=True)
        with self.assertRaises(BillingAPIError):
            await client.invoice(101)

    async def test_currency_id_is_taken_from_verified_account_or_quote_never_guessed(self):
        client = AdapterClient([response(jwt="jwt"), response({"id": 42, "currency": {"id": 2}}),
                                response({"total": "9.90", "currency": {"id": 2, "code": "USD"}})])
        await client.login()
        await client.quote({"pid": 12, "billingcycle": "monthly", "qty": 1})
        self.assertEqual(client.calls[-1][-1]["currencyid"], "2")
        empty = AdapterClient([], authenticated=True)
        with self.assertRaises(BillingAPIError):
            await empty.create_order({"pid": 12, "billingcycle": "monthly", "qty": 1}, "alipay")
        self.assertEqual(empty.calls, [])
        quoted = AdapterClient([response({"total": "9.90", "currency": {"id": 3}})], authenticated=True)
        await quoted.quote({"pid": 12, "billingcycle": "monthly", "qty": 1})
        self.assertEqual(quoted._currency_id, "3")


if __name__ == "__main__":
    unittest.main()
