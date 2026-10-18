"""Private billing command boundaries, durable confirmation and payment delivery."""
import asyncio
from base64 import b64decode
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from PIL import Image

from starbridge.billing import Billing
from starbridge.billing_client import BillingAPIError
from starbridge.bot import Bot


QQ = "123456789"
OTHER_QQ = "987654321"
SECRET = "api-secret-must-never-be-replied-123"
SETTINGS = {"enabled": True, "timeout": 15,
            "providers": {"demo": {"name": "Demo", "base_url": "https://example.com"}}}


class FakeStore:
    def __init__(self):
        self.events = set()
        self.audits = []
        self.jobs = []

    def seen(self, key):
        seen = key in self.events
        self.events.add(key)
        return seen

    def audit(self, kind, detail):
        self.audits.append((kind, detail))

    def binding(self, server, qq):
        return None

    def enqueue(self, server, payload):
        self.jobs.append((server, deepcopy(payload)))


class FakeOneBot:
    self_id = "10000"
    provider = "onebot"

    def __init__(self):
        self.private = []
        self.groups = []
        self.calls = []

    async def send_private(self, qq, text):
        self.private.append((str(qq), text))

    async def send_group(self, group, text):
        self.groups.append((str(group), text))

    async def call(self, action, params):
        self.calls.append((action, deepcopy(params)))


class FakeBot:
    def __init__(self):
        self.store = FakeStore()
        self.onebot = FakeOneBot()

    def allow(self, key, count, period):
        return True


class FakeClientFactory:
    def __init__(self):
        self.calls = []
        self.instances = []
        self.total = "10.00"
        self.currency = {"code": "CNY"}
        self.login_error = None
        self.order_error = None
        self.pay_error = None
        self.login_id = "7"
        self.payment = {"_pay_html": {"type": "url", "data": "https://pay.example.com/x"}}
        self.invoice_status = "Unpaid"
        self.quote_started = None
        self.quote_release = None

    def __call__(self, provider, credentials, timeout):
        self.instances.append((deepcopy(provider), deepcopy(credentials), timeout))
        return FakeClient(self)

    def count(self, method):
        return sum(call[0] == method for call in self.calls)


class FakeClient:
    def __init__(self, factory):
        self.factory = factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def login(self):
        self.factory.calls.append(("login",))
        if self.factory.login_error:
            raise self.factory.login_error
        return {"id": self.factory.login_id}

    async def products(self, **filters):
        self.factory.calls.append(("products", filters))
        if getattr(self.factory, "catalog_data", None) is not None:
            return deepcopy(self.factory.catalog_data)
        return {"first_group": [{"id": 1, "name": "云计算", "group": [
            {"id": 2, "name": "云服务器", "product": [{"id": 3, "name": "入门主机", "sale_price": "10.00"}]}]}]}

    async def detail(self, product_id):
        self.factory.calls.append(("detail", product_id))
        return {"product": {"id": product_id, "name": "入门主机", "description": "<p>2 核 2G</p>",
                            "cycle": [{"billingcycle": "monthly", "saleprice": "10.00", "setup_fee": "0"}],
                            "configoptions": [{"id": 4, "option_name": "内存", "sub": [{"id": 5, "name": "2G"}]}],
                            "customfields": [{"id": 6, "fieldname": "用途"}]}}

    async def gateways(self):
        self.factory.calls.append(("gateways",))
        return [{"name": "alipay", "title": "支付宝"}]

    async def quote(self, product):
        self.factory.calls.append(("quote", deepcopy(product)))
        if self.factory.quote_started is not None:
            self.factory.quote_started.set()
            await self.factory.quote_release.wait()
        return {"total": self.factory.total, "currency": deepcopy(self.factory.currency)}

    async def create_order(self, product, payment):
        self.factory.calls.append(("create_order", deepcopy(product), payment))
        if self.factory.order_error:
            raise self.factory.order_error
        return {"invoiceid": "9", "orderid": "8"}

    async def invoice(self, invoice_id):
        self.factory.calls.append(("invoice", str(invoice_id)))
        return {"invoices": {"id": str(invoice_id), "status": self.factory.invoice_status, "total": "10.00"},
                "gateways": [{"name": "alipay", "title": "支付宝"}]}

    async def pay(self, invoice_id, payment):
        self.factory.calls.append(("pay", str(invoice_id), payment))
        if self.factory.pay_error:
            raise self.factory.pay_error
        return deepcopy(self.factory.payment)


class BillingCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        workspace_temp = Path(__file__).resolve().parents[1] / ".tools"
        workspace_temp.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="billing-commands-", dir=workspace_temp)
        self.base = Path(self.temp.name)
        self.bot = FakeBot()
        self.factory = FakeClientFactory()
        self.billing = Billing(self.base, self.bot, config=deepcopy(SETTINGS), client_factory=self.factory)
        self.message_id = 0

    async def asyncTearDown(self):
        await self.billing.close()
        self.temp.cleanup()

    def event(self, text, *, qq=QQ, group=False, message_id=None):
        self.message_id += 1
        return {"post_type": "message", "message_type": "group" if group else "private", "user_id": int(qq),
                "self_id": 10000, "message_id": self.message_id if message_id is None else message_id,
                "message": [{"type": "text", "data": {"text": text}}], **({"group_id": 20000} if group else {})}

    async def command(self, text, **kwargs):
        return await self.billing.handle_event(self.event(text, **kwargs))

    def replies(self):
        return "\n".join(text for _, text in self.bot.onebot.private)

    async def bind(self, qq=QQ):
        await self.command(f"/财务绑定 demo account@example.com {SECRET}", qq=qq)
        self.assertIsNotNone(self.billing.repository.get_binding(qq, "demo"))

    async def prepare(self, qq=QQ, extra=""):
        await self.command("/财务下单 demo 3 monthly alipay 1" + extra, qq=qq)
        match = re.search(r"/财务确认 demo ([A-Za-z0-9_-]+)", self.bot.onebot.private[-1][1])
        self.assertIsNotNone(match, self.bot.onebot.private[-1][1])
        return match.group(1)

    async def order(self):
        token = await self.prepare()
        await self.command(f"/财务确认 demo {token}")
        orders = self.billing.repository.list_orders(QQ, "demo")
        self.assertEqual(len(orders), 1)
        return orders[0]

    async def test_unbound_business_commands_never_construct_api_client(self):
        for command in ("账号", "分组", "商品 demo 2", "详情 demo 3", "支付方式", "下单 demo 3 monthly alipay",
                        "确认 demo stolen", "订单 demo unknown", "付款 demo unknown alipay", "解绑"):
            text = "/财务" + command
            if " " not in command:
                text += " demo"
            await self.command(text)
        self.assertEqual(self.factory.instances, [])
        self.assertIn("请先私聊绑定", self.replies())
        self.assertEqual(self.billing.repository.list_orders(QQ, "demo"), [])

    async def test_documented_frontend_shapes_filter_children_and_render_product_configuration(self):
        await self.bind()
        self.factory.catalog_data = {"first_groups": [{"id": 1, "name": "云计算"}],
                                     "product_groups": [{"id": 2, "gid": 1, "name": "本组商品"},
                                                        {"id": 3, "gid": 9, "name": "其他分组"}],
                                     "products": [{"id": 100, "name": "官方形状商品"}]}
        await self.command("/财务分组 demo 1")
        self.assertIn("2 · 本组商品", self.bot.onebot.private[-1][1])
        self.assertNotIn("其他分组", self.bot.onebot.private[-1][1])
        await self.command("/财务商品 demo 2")
        self.assertIn("100 · 官方形状商品", self.bot.onebot.private[-1][1])
        detail = Billing.detail_text({"products": {"id": 100, "name": "商品详情"},
                                      "product_pricings": [{"code": "CNY", "monthly": "9.90", "annually": "-1"}],
                                      "config_groups": [{"options": [{"id": 12, "name": "内存", "sub": [
                                          {"id": 34, "option_name": "2 GB"}]}]}],
                                      "customfields": [{"id": 5, "fieldname": "用途"}]}, "demo", "100")
        self.assertIn("monthly · 9.90", detail)
        self.assertNotIn("annually · -1", detail)
        self.assertIn("配置 12 · 内存", detail)
        self.assertIn("34 · 2 GB", detail)
        self.assertIn("自定义字段 5 · 用途", detail)

    async def test_group_binding_does_not_login_reply_credentials_or_forward_privately(self):
        event = self.event(f"/财务绑定 demo account@example.com {SECRET}", group=True)
        self.assertTrue(await self.billing.handle_event(event))
        self.assertEqual(self.factory.instances, [])
        self.assertEqual(self.bot.onebot.private, [])
        self.assertEqual(len(self.bot.onebot.groups), 1)
        self.assertNotIn(SECRET, str(self.bot.onebot.groups))
        self.assertNotIn("account@example.com", str(self.bot.onebot.groups))
        self.assertIsNone(self.billing.repository.get_binding(QQ, "demo"))
        self.assertNotIn(SECRET, str(self.bot.store.audits))

    async def test_private_binding_verifies_login_before_persisting_and_never_echoes_key(self):
        self.factory.login_error = BillingAPIError("服务商 API 认证失败")
        await self.command(f"/财务绑定 demo account@example.com {SECRET}")
        self.assertIsNone(self.billing.repository.get_binding(QQ, "demo"))
        self.factory.login_error = None
        await self.bind()
        binding = self.billing.repository.get_binding(QQ, "demo")
        self.assertEqual(binding["account"], "7")
        self.assertEqual(binding["credentials"]["account"], "account@example.com")
        self.assertEqual(binding["credentials"]["api_key"], SECRET)
        self.assertEqual(self.factory.count("login"), 2)
        self.assertNotIn(SECRET, self.replies())
        self.assertNotIn(SECRET, str(self.bot.store.audits))
        self.assertNotIn(SECRET, "\n".join(self.billing.repository.db.iterdump()))

    async def test_first_second_groups_products_details_and_gateway_queries(self):
        await self.bind()
        for command, expected in (("分组 demo", "1 · 云计算"), ("分组 demo 1", "2 · 云服务器"),
                                  ("商品 demo 2", "3 · 入门主机 · 10.00"),
                                  ("详情 demo 3", "自定义字段 6 · 用途"), ("支付方式 demo", "alipay · 支付宝")):
            await self.command("/财务" + command)
            self.assertIn(expected, self.bot.onebot.private[-1][1])
        self.assertIn(("products", {"first_gid": 1}), self.factory.calls)
        self.assertIn(("products", {"gid": 2}), self.factory.calls)
        self.assertIn(("detail", 3), self.factory.calls)

    async def test_quote_requires_confirmation_and_repeat_confirmation_or_event_is_submit_once(self):
        await self.bind()
        token = await self.prepare()
        self.assertEqual(self.factory.count("quote"), 1)
        self.assertEqual(self.factory.count("create_order"), 0)
        event = self.event(f"/财务确认 demo {token}")
        await self.billing.handle_event(event)
        await self.billing.handle_event(event)
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 1)
        self.assertEqual(self.factory.count("quote"), 2)
        self.assertEqual(self.factory.count("pay"), 1)
        self.assertEqual(len(self.billing.repository.list_orders(QQ, "demo")), 1)

    async def test_cross_user_token_cannot_create_order_and_owner_can_still_confirm(self):
        await self.bind()
        await self.bind(OTHER_QQ)
        token = await self.prepare()
        await self.command(f"/财务确认 demo {token}", qq=OTHER_QQ)
        self.assertEqual(self.factory.count("create_order"), 0)
        self.assertIn("下单确认不存在", self.bot.onebot.private[-1][1])
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 1)

    async def test_concurrent_confirmations_claim_durable_token_before_awaiting_quote(self):
        await self.bind()
        token = await self.prepare()
        self.factory.quote_started = asyncio.Event()
        self.factory.quote_release = asyncio.Event()
        first = asyncio.create_task(self.command(f"/财务确认 demo {token}"))
        try:
            await asyncio.wait_for(self.factory.quote_started.wait(), 2)
            await self.command(f"/财务确认 demo {token}")
            self.assertEqual(self.factory.count("create_order"), 0)
            self.assertIn("确认已使用、处理中或已过期", self.bot.onebot.private[-1][1])
        finally:
            self.factory.quote_release.set()
            await first
        self.assertEqual(self.factory.count("create_order"), 1)
        self.assertEqual(self.factory.count("quote"), 2)

    async def test_price_change_invalidates_confirmation_without_submitting_order(self):
        await self.bind()
        token = await self.prepare()
        self.factory.total = "11.00"
        await self.command(f"/财务确认 demo {token}")
        self.assertIn("价格已变化", self.bot.onebot.private[-1][1])
        self.factory.total = "10.00"
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 0)
        self.assertEqual(self.factory.count("quote"), 2)

    async def test_currency_change_invalidates_same_amount_confirmation_without_submitting(self):
        await self.bind()
        token = await self.prepare()
        self.factory.currency = {"code": "USD"}
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 0)
        self.assertEqual(self.factory.count("quote"), 2)
        self.assertRegex(self.bot.onebot.private[-1][1], "币种|报价|价格")
        self.factory.currency = {"code": "CNY"}
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 0)

    async def test_provider_address_change_never_sends_bound_credentials_to_new_server(self):
        await self.bind()
        binding = self.billing.repository.get_binding(QQ, "demo")
        self.assertEqual(binding["credentials"]["base_url"], "https://example.com")
        before = len(self.factory.instances)
        self.billing.settings["providers"]["demo"]["base_url"] = "https://other.example.com"
        await self.command("/财务分组 demo")
        self.assertEqual(len(self.factory.instances), before)
        self.assertEqual(self.factory.count("products"), 0)
        self.assertIn("重新绑定", self.bot.onebot.private[-1][1])
        self.assertNotIn(SECRET, self.replies())

    async def test_uncertain_upstream_order_is_not_retried_even_after_restart(self):
        await self.bind()
        token = await self.prepare()
        self.factory.order_error = BillingAPIError("连接超时", uncertain=True)
        await self.command(f"/财务确认 demo {token}")
        self.assertIn("下单结果未确定", self.bot.onebot.private[-1][1])
        await self.billing.close()
        self.billing = Billing(self.base, self.bot, config=deepcopy(SETTINGS), client_factory=self.factory)
        self.factory.order_error = None
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 1)
        self.assertEqual(self.billing.repository.list_orders(QQ, "demo"), [])

    async def test_created_order_survives_payment_failure_and_can_be_paid_later(self):
        await self.bind()
        self.factory.pay_error = BillingAPIError("支付插件暂不可用")
        order = await self.order()
        self.assertEqual(order["invoice_id"], "9")
        self.assertIn("订单已保留", self.replies())
        self.factory.pay_error = None
        await self.command(f"/财务付款 demo {order['id']} alipay")
        self.assertEqual(self.factory.count("create_order"), 1)
        self.assertEqual(self.factory.count("pay"), 2)
        self.assertEqual(len(self.bot.onebot.calls), 1)

    async def test_other_user_cannot_query_or_pay_an_owned_order(self):
        await self.bind()
        await self.bind(OTHER_QQ)
        order = await self.order()
        baseline = (self.factory.count("invoice"), self.factory.count("pay"))
        for text in (f"/财务订单 demo {order['id']}", f"/财务付款 demo {order['id']} alipay"):
            await self.command(text, qq=OTHER_QQ)
            self.assertIn("找不到属于当前绑定账号的订单", self.bot.onebot.private[-1][1])
        self.assertEqual((self.factory.count("invoice"), self.factory.count("pay")), baseline)

    async def test_url_payment_sends_actual_png_in_typed_onebot_message(self):
        await self.bind()
        self.factory.payment = {"pay_html": {"type": "url", "data": "https://pay.example.com/x"}}
        await self.order()
        action, params = self.bot.onebot.calls[-1]
        self.assertEqual(action, "send_private_msg")
        self.assertEqual(params["user_id"], int(QQ))
        segments = params["message"]
        image = next(segment for segment in segments if segment["type"] == "image")
        self.assertTrue(image["data"]["file"].startswith("base64://"))
        png = b64decode(image["data"]["file"][len("base64://"):], validate=True)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as rendered:
            self.assertEqual(rendered.format, "PNG")
            self.assertGreater(rendered.width, 100)
            rendered.verify()
        text = "\n".join(segment["data"]["text"] for segment in segments if segment["type"] == "text")
        self.assertIn("https://pay.example.com/x", text)

    async def test_jump_insert_and_html_return_safe_payment_links(self):
        await self.bind()
        order = await self.order()
        self.bot.onebot.calls.clear()
        cases = (
            ("jump", "https://pay.example.com/jump", "https://pay.example.com/jump"),
            ("insert", "https://pay.example.com/qr.png", "https://pay.example.com/qr.png"),
            ("html", '<script>steal("private-secret")</script>', "https://example.com/viewbilling?id=9"),
            ("insert", '<img src="http://127.0.0.1/" onerror="steal()">', "https://example.com/viewbilling?id=9"),
        )
        for field in ("_pay_html", "pay_html"):
            for kind, data, expected in cases:
                with self.subTest(field=field, kind=kind, data=data):
                    self.factory.payment = {field: {"type": kind, "data": data}}
                    await self.command(f"/财务付款 demo {order['id']} alipay")
                    self.assertIn(expected, self.bot.onebot.private[-1][1])
                    self.assertNotIn("private-secret", self.bot.onebot.private[-1][1])
                    self.assertNotIn("onerror", self.bot.onebot.private[-1][1])
        self.assertEqual(self.bot.onebot.calls, [])

    async def test_oversized_qr_falls_back_to_invoice_link_without_replaying_order(self):
        await self.bind()
        self.factory.payment = {"pay_html": {"type": "url", "data": "https://pay.example.com/?q=" + "x" * 6000}}
        order = await self.order()
        self.assertIn("https://example.com/viewbilling?id=9", self.bot.onebot.private[-1][1])
        self.assertEqual(self.factory.count("create_order"), 1)
        self.assertEqual(self.billing.repository.get_order(QQ, "demo", order["id"])["invoice_id"], "9")
        self.assertEqual(self.bot.onebot.calls, [])

    def real_bot(self):
        server = {"id": "mc", "name": "Minecraft", "groups": ["20000"]}
        bot = Bot({"servers": [server], "features": {"qq_to_mc": True}}, self.bot.store, self.bot.onebot)
        bot.plugins = SimpleNamespace(group_message=AsyncMock(return_value=False))
        bot.snapshots["mc"] = {"last_seen": time.time()}
        bot.billing = self.billing
        self.billing.bot = bot
        return bot

    async def test_real_bot_handles_unassociated_private_binding_and_intercepts_group_secrets(self):
        bot = self.real_bot()
        await bot.handle_event(self.event(f"/财务绑定 demo account@example.com {SECRET}"))
        self.assertIsNotNone(self.billing.repository.get_binding(QQ, "demo"))
        baseline = self.factory.count("login")
        await bot.handle_event(self.event(f"/财务绑定 demo account@example.com {SECRET}", group=True))
        self.assertEqual(self.factory.count("login"), baseline)
        bot.plugins.group_message.assert_not_awaited()
        self.assertEqual(self.bot.store.jobs, [])
        self.assertNotIn(SECRET, str(self.bot.onebot.groups))
        self.assertNotIn(SECRET, self.replies())

    async def test_real_bot_intercepts_disabled_billing_before_plugins_and_minecraft_relay(self):
        await self.billing.close()
        self.billing = Billing(self.base, self.bot, config={"enabled": False, "providers": {}},
                               client_factory=self.factory)
        bot = self.real_bot()
        # Establish that this is an associated, online group whose ordinary text
        # reaches both the plugin hook and Minecraft relay.
        await bot.handle_event(self.event("普通聊天", group=True))
        bot.plugins.group_message.assert_awaited_once()
        self.assertEqual(len(self.bot.store.jobs), 1)
        bot.plugins.group_message.reset_mock()
        self.bot.store.jobs.clear()
        for group in (False, True):
            await bot.handle_event(self.event(f"/财务绑定 demo account@example.com {SECRET}", group=group))
        self.assertEqual(self.factory.instances, [])
        bot.plugins.group_message.assert_not_awaited()
        self.assertEqual(self.bot.store.jobs, [])
        self.assertNotIn(SECRET, str(self.bot.onebot.groups))
        self.assertNotIn(SECRET, self.replies())
        self.assertIn("尚未启用", self.replies())

    async def test_identity_change_or_unbind_blocks_prepared_checkout(self):
        await self.bind()
        token = await self.prepare()
        self.factory.login_id = "8"
        await self.command(f"/财务确认 demo {token}")
        self.assertIn("账号身份已变化", self.bot.onebot.private[-1][1])
        self.factory.login_id = "7"
        await self.command("/财务解绑 demo")
        await self.bind()
        await self.command(f"/财务确认 demo {token}")
        self.assertEqual(self.factory.count("create_order"), 0)

    async def test_malformed_or_untrusted_events_never_touch_api(self):
        for alteration in ({"self_id": 99999}, {"user_id": 10000}, {"user_id": "abc"},
                           {"anonymous": {"id": 1}}, {"message_id": True}, {"post_type": "notice"}):
            event = self.event(f"/财务绑定 demo account@example.com {SECRET}")
            event.update(alteration)
            await self.billing.handle_event(event)
        self.assertEqual(self.factory.instances, [])
        self.assertEqual(self.bot.onebot.private, [])


if __name__ == "__main__":
    unittest.main()
