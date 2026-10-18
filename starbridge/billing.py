"""Private OneBot 11 commands for verified Mofang Finance customer accounts."""
from base64 import b64encode
from decimal import Decimal, InvalidOperation
from html import unescape
from io import BytesIO
import json
import re

import qrcode

from .billing_client import BillingAPIError, MofangClient
from .billing_config import load_config, parse_payment
from .billing_store import BillingStore, BillingStoreError
from .bot import plain_message


HELP = """VexBot · 魔方财务（私聊）
/财务服务商 — 查看已配置服务商
/财务绑定 服务商 账号 API密钥
/财务账号 服务商
/财务分组 服务商 [一级分组ID] [页码]
/财务商品 服务商 二级分组ID [页码]
/财务详情 服务商 商品ID
/财务支付方式 服务商
/财务下单 服务商 商品ID 周期 支付方式 [数量] [JSON配置]
/财务确认 服务商 确认码
/财务订单 服务商 [本地订单号]
/财务付款 服务商 本地订单号 支付方式
/财务解绑 服务商
请在服务商会员中心申请 API 密钥，并将机器人服务器 IP 加入 API 白名单。"""
COMMANDS = {"财务帮助", "财务服务商", "财务绑定", "财务账号", "财务分组", "财务商品", "财务详情",
            "财务支付方式", "财务下单", "财务确认", "财务订单", "财务付款", "财务解绑", "财务"}
CYCLES = {"free", "onetime", "ontrial", "hour", "day", "monthly", "quarterly", "semiannually",
          "annually", "biennially", "triennially"}
OPTIONS = {"configoption", "customfield", "host", "password", "os"}


def display(value, limit=250):
    value = re.sub(r"<[^>]*>", " ", str(value))
    return " ".join(unescape(value).split())[:limit]


def positive(value, maximum=2_147_483_647):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > maximum:
        raise ValueError("请输入有效的正整数 ID、页码或数量")
    return int(value)


def rows(data, key):
    result = data.get(key, data.get("_" + key, [])) if isinstance(data, dict) else []
    return [v for v in result if isinstance(v, dict)] if isinstance(result, list) else []


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise BillingAPIError("服务商未返回有效报价，本次未提交订单") from None


def page_text(lines, page, footer):
    count = max(1, (len(lines) + 11) // 12)
    if page > count:
        raise ValueError("页码超出范围")
    return "\n".join(lines[(page - 1) * 12:page * 12] or ["暂无数据"]) + f"\n第 {page}/{count} 页\n" + footer


def invoice_record(data):
    if not isinstance(data, dict):
        raise BillingAPIError("服务商账单数据格式不正确")
    invoice = data.get("invoices", data.get("_invoices"))
    if isinstance(invoice, dict):
        return invoice
    if isinstance(data.get("status"), str):
        return data
    raise BillingAPIError("服务商账单数据格式不正确")


def quote_currency(quote):
    value = quote.get("currency", "")
    if isinstance(value, dict):
        return display(value.get("code", value.get("id", "")), 32)
    return display(value, 32)


class Billing:
    def __init__(self, base, bot, config=None, client_factory=MofangClient):
        self.bot = bot
        self.settings = load_config(base) if config is None else config
        self.repository = BillingStore(bot.store, base) if self.settings["enabled"] else None
        self.client_factory = client_factory

    async def close(self):
        if self.repository is not None:
            self.repository.close()
            self.repository = None

    async def send(self, qq, text):
        # Split only at line boundaries; OneBot's text transport truncates at 3500.
        chunk = ""
        for line in text.splitlines():
            line = line[:3000]
            if len(chunk) + len(line) + 1 > 3300:
                await self.bot.onebot.send_private(qq, chunk)
                chunk = ""
            chunk += ("\n" if chunk else "") + line
        if chunk:
            await self.bot.onebot.send_private(qq, chunk)

    async def handle_event(self, event):
        text = plain_message(event.get("message", ""))
        command = text.split(maxsplit=1)[0].lstrip("/") if text else ""
        if not command.startswith("财务"):
            return False
        qq = str(event.get("user_id", ""))
        mid = event.get("message_id")
        if (event.get("post_type") != "message" or event.get("message_type") not in ("private", "group")
                or event.get("anonymous") or not re.fullmatch(r"[1-9][0-9]{0,18}", qq)
                or qq == str(event.get("self_id")) or str(event.get("self_id")) != self.bot.onebot.self_id
                or not isinstance(mid, (str, int)) or isinstance(mid, bool)):
            return True
        if (getattr(self.bot.onebot, "provider", "onebot") != "onebot"
                or self.bot.store.seen(f"billing:{event['self_id']}:{event.get('group_id', '')}:{qq}:{mid}")
                or not self.bot.allow(("billing", qq), count=8, period=30)):
            return True
        if event["message_type"] == "group":
            group = str(event.get("group_id", ""))
            if group.isdigit():
                await self.bot.onebot.send_group(group, "魔方财务操作请私聊 VexBot；账号、API 密钥与付款信息请勿发到群里。")
            return True
        if not self.settings["enabled"]:
            await self.send(qq, "魔方财务功能尚未启用，请联系管理员配置 billing.toml。")
            return True
        try:
            if len(text) > 6000:
                raise ValueError("财务指令过长")
            await self.dispatch(qq, command, text)
        except (BillingAPIError, BillingStoreError, ValueError) as error:
            await self.send(qq, str(error))
        except (ConnectionError, RuntimeError, TimeoutError):
            # Delivery may have succeeded; do not replay an order or payment.
            self.bot.store.audit("billing", "财务回复投递结果未确定；未自动重试")
        except Exception as error:
            self.bot.store.audit("billing", "财务处理失败：" + type(error).__name__)
            await self.send(qq, "财务服务暂时不可用，请稍后查询订单；本次操作未自动重试。")
        return True

    def provider(self, key):
        value = self.settings["providers"].get(key)
        if value is None:
            raise ValueError("未配置此服务商，请先发送 /财务服务商")
        return value

    async def dispatch(self, qq, command, text):
        parts = text.split()
        if command not in COMMANDS:
            raise ValueError("未知财务指令，请发送 /财务帮助")
        if command in ("财务", "财务帮助"):
            return await self.send(qq, HELP)
        if command == "财务服务商":
            return await self.send(qq, "已配置服务商：\n" + "\n".join(
                f"{key} · {display(value['name'], 60)}" for key, value in self.settings["providers"].items()))
        if len(parts) < 2:
            raise ValueError("请在指令后填写服务商标识，格式见 /财务帮助")
        key, args = parts[1], parts[2:]
        provider = self.provider(key)
        if command == "财务绑定":
            if len(args) != 2 or any(len(v) > 512 or any(ord(c) < 33 for c in v) for v in args):
                raise ValueError("绑定格式：/财务绑定 服务商 账号 API密钥（使用 API 密钥）")
            credentials = {"account": args[0], "api_key": args[1], "base_url": provider["base_url"]}
            async with self.client_factory(provider, credentials, timeout=self.settings["timeout"]) as client:
                profile = await client.login()
                self.repository.bind(qq, key, str(profile["id"]), credentials)
            return await self.send(qq, "账号 API 验证成功，已绑定。现在可以查询商品和下单。")
        binding = self.repository.get_binding(qq, key)
        if binding is None:
            raise ValueError(f"请先私聊绑定账号：/财务绑定 {key} 账号 API密钥")
        if command == "财务解绑":
            if args:
                raise ValueError("解绑格式：/财务解绑 服务商")
            self.repository.unbind(qq, key)
            return await self.send(qq, "已删除此服务商的账号凭据，未提交的下单确认已失效。")
        if binding["credentials"].get("base_url") != provider["base_url"]:
            raise ValueError("服务商地址已变化，请核对地址并重新绑定；原凭据未发送")
        async with self.client_factory(provider, binding["credentials"], timeout=self.settings["timeout"]) as client:
            profile = await client.login()
            if str(profile["id"]) != binding["account"]:
                raise ValueError("服务商账号身份已变化，请重新绑定")
            if command == "财务账号":
                return await self.send(qq, f"{display(provider['name'])} · API 身份验证有效")
            if command in ("财务分组", "财务商品"):
                return await self.catalog(qq, key, command, args, client)
            if command == "财务详情":
                if len(args) != 1:
                    raise ValueError("详情格式：/财务详情 服务商 商品ID")
                data = await client.detail(positive(args[0]))
                return await self.send(qq, self.detail_text(data, key, args[0]))
            if command == "财务支付方式":
                gateways = await client.gateways()
                return await self.send(qq, "可用支付方式：\n" + "\n".join(
                    f"{display(v.get('name', ''), 64)} · {display(v.get('title', ''))}" for v in gateways))
            if command == "财务下单":
                return await self.prepare(qq, key, binding, text, client)
            if command == "财务确认":
                if len(args) != 1:
                    raise ValueError("确认格式：/财务确认 服务商 确认码")
                return await self.confirm(qq, key, provider, binding, args[0], client)
            if command == "财务订单":
                if len(args) > 1:
                    raise ValueError("订单格式：/财务订单 服务商 [本地订单号]")
                if not args:
                    orders = self.repository.list_orders(qq, key)
                    return await self.send(qq, "最近订单：\n" + ("\n".join(
                        f"{v['id']} · {display(v['status'])} · {display(v['summary'], 120)}" for v in orders) or "暂无订单"))
                order = self.owned_order(qq, key, args[0])
                data = await client.invoice(order["invoice_id"])
                invoice = invoice_record(data)
                status = display(invoice.get("status", "未知"))
                self.repository.set_order_status(qq, key, order["id"], status)
                return await self.send(qq, f"订单：{order['id']}\n账单：{order['invoice_id']}\n状态：{status}\n金额：{display(invoice.get('total', invoice.get('subtotal', '未知')))}")
            if command == "财务付款":
                if len(args) != 2:
                    raise ValueError("付款格式：/财务付款 服务商 本地订单号 支付方式")
                return await self.payment(qq, key, provider, self.owned_order(qq, key, args[0]), args[1], client)

    async def catalog(self, qq, key, command, args, client):
        if command == "财务分组":
            if len(args) > 2:
                raise ValueError("分组格式：/财务分组 服务商 [一级分组ID] [页码]")
            first = positive(args[0]) if args else None
            page = positive(args[1]) if len(args) == 2 else 1
            data = await client.products(**({"first_gid": first} if first else {}))
            lines = []
            if "first_groups" in data or "product_groups" in data:
                groups = rows(data, "product_groups" if first else "first_groups")
                if first:
                    groups = [v for v in groups if v.get("gid") is None or str(v["gid"]) == str(first)]
                lines = [f"{display(v.get('id'))} · {display(v.get('name', v.get('groupname', '')))}" for v in groups]
            else:
                for top in rows(data, "first_group"):
                    if first and str(top.get("id")) != str(first):
                        continue
                    if first:
                        lines.extend(f"{display(v.get('id'))} · {display(v.get('name'))}" for v in rows(top, "group"))
                    else:
                        lines.append(f"{display(top.get('id'))} · {display(top.get('name'))}")
            footer = f"/财务商品 {key} 二级分组ID" if first else f"/财务分组 {key} 一级分组ID"
        else:
            if not 1 <= len(args) <= 2:
                raise ValueError("商品格式：/财务商品 服务商 二级分组ID [页码]")
            group, page = positive(args[0]), positive(args[1]) if len(args) == 2 else 1
            data = await client.products(gid=group)
            products = rows(data, "products")
            if "products" not in data:
                for top in rows(data, "first_group"):
                    for second in rows(top, "group"):
                        if str(second.get("id")) == str(group):
                            products.extend(rows(second, "product"))
            lines = [f"{display(v.get('id'))} · {display(v.get('name'), 90)} · {display(v.get('sale_price', v.get('product_price', '待报价')))}" for v in products]
            footer = f"/财务详情 {key} 商品ID"
        await self.send(qq, page_text(lines, page, footer))

    @staticmethod
    def detail_text(data, key, pid):
        product = data.get("products", data.get("product", data.get("_product", data)))
        if isinstance(product, list) and len(product) == 1:
            product = product[0]
        if not isinstance(product, dict):
            raise BillingAPIError("服务商商品详情格式不正确")
        lines = [f"{display(product.get('name', product.get('product_name', pid)))} · 商品 {pid}",
                 display(product.get("description", ""), 1000)]
        cycles = rows(product, "cycle") or rows(data, "cycle")
        for cycle in cycles:
            lines.append(f"{display(cycle.get('billingcycle'))} · {display(cycle.get('saleprice', cycle.get('product_price', '待报价')))} + 初装费 {display(cycle.get('setup_fee', 0))}")
        if not cycles:
            for pricing in rows(data, "product_pricings"):
                lines.append("币种：" + display(pricing.get("code", pricing.get("currency", "以报价为准"))))
                for cycle in sorted(CYCLES):
                    price = pricing.get(cycle)
                    if price is not None and str(price) != "-1":
                        lines.append(f"{cycle} · {display(price)}")
        options = rows(product, "configoptions") or rows(data, "configoptions")
        for group in rows(data, "config_groups"):
            options.extend(rows(group, "options"))
        for option in options:
            lines.append(f"配置 {display(option.get('id'))} · {display(option.get('option_name', option.get('name', '')))} · 类型 {display(option.get('option_type', option.get('type', '')))}")
            for sub in rows(option, "sub"):
                lines.append(f"  {display(sub.get('id'))} · {display(sub.get('option_name', sub.get('name', '')))}")
        for field in rows(product, "customfields") or rows(data, "customfields") or rows(data, "custom_fields"):
            lines.append(f"自定义字段 {display(field.get('id'))} · {display(field.get('fieldname', field.get('name', '')))}")
        lines += [f"/财务下单 {key} {pid} monthly 支付方式 1", "可选 JSON 配置格式见部署文档；最终价格以下单前报价为准。"]
        return "\n".join(lines)

    async def prepare(self, qq, key, binding, text, client):
        parts = text.split(maxsplit=6)
        if len(parts) < 5:
            raise ValueError("下单格式：/财务下单 服务商 商品ID 周期 支付方式 [数量] [JSON配置]")
        product = {"pid": positive(parts[2]), "billingcycle": parts[3], "qty": positive(parts[5], 100) if len(parts) >= 6 else 1}
        payment = parts[4]
        if product["billingcycle"] not in CYCLES:
            raise ValueError("周期不受支持，请使用商品详情中的周期标识")
        if len(parts) >= 7:
            # Rejoin the tail exactly enough for JSON with spaces in string values.
            raw = text.split(maxsplit=6)[6]
            try:
                extra = json.loads(raw)
            except (ValueError, RecursionError):
                raise ValueError("JSON 配置格式错误") from None
            if not isinstance(extra, dict) or extra.keys() - OPTIONS:
                raise ValueError("JSON 配置仅支持 configoption/customfield/host/password/os")
            for name, value in extra.items():
                if name in ("configoption", "customfield", "os"):
                    if not isinstance(value, dict) or len(value) > 50 or any(
                        not re.fullmatch(r"[1-9][0-9]{0,9}", str(k)) or not isinstance(v, (str, int)) or isinstance(v, bool)
                        or len(str(v)) > 500 for k, v in value.items()):
                        raise ValueError("配置项必须为 ID 到文本或数字的 JSON 对象")
                elif not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 for c in value):
                    raise ValueError("主机与密码配置必须为单行文本")
            product.update(extra)
        available = await client.gateways()
        if payment not in {v.get("name") for v in available}:
            raise ValueError("支付方式不可用，请先查询 /财务支付方式 " + key)
        quote = await client.quote(product)
        total = str(money(quote.get("total")))
        currency = quote_currency(quote)
        summary = f"商品 {product['pid']} · {product['billingcycle']} × {product['qty']} · 应付 {currency} {total}"
        payload = {"product": product, "payment": payment, "total": total, "currency": currency}
        token = self.repository.save_checkout(qq, key, binding["generation"], payload, summary)
        await self.send(qq, f"{summary}\n支付方式：{display(payment)}\n5 分钟内确认创建订单：\n/财务确认 {key} {token}")

    def owned_order(self, qq, key, local_id):
        order = self.repository.get_order(qq, key, local_id)
        if order is None:
            raise ValueError("找不到属于当前绑定账号的订单")
        return order

    async def confirm(self, qq, key, provider, binding, token, client):
        checkout = self.repository.get_checkout(qq, key, binding["generation"], token)
        if checkout is None:
            raise ValueError("下单确认不存在或账号绑定已变化")
        if checkout["status"] == "complete":
            return await self.send(qq, "该确认已创建订单：" + checkout["local_order_id"] + "；请使用 /财务付款 获取付款入口。")
        payload = self.repository.claim_checkout(qq, key, binding["generation"], token)
        if payload is None:
            raise ValueError("确认已使用、处理中或已过期，请查询服务商订单后再操作")
        try:
            quote = await client.quote(payload["product"])
            if money(quote.get("total")) != money(payload["total"]) or quote_currency(quote) != payload.get("currency", ""):
                raise ValueError("商品价格已变化，当前确认已失效，请重新发送下单指令获取报价")
            result = await client.create_order(payload["product"], payload["payment"])
            invoice = result.get("invoiceid", result.get("invoice_id"))
            if isinstance(invoice, bool) or not str(invoice).isdigit() or int(invoice) < 1:
                raise BillingAPIError("服务商未返回有效账单号，请到官网核对订单；本次未自动重试", uncertain=True)
            local_id = self.repository.create_order(qq, key, binding["account"], binding["generation"], str(invoice),
                                                    str(result.get("orderid", result.get("order_id", ""))), checkout["summary"])
            self.repository.finish_checkout(token, local_id)
        except BillingAPIError as error:
            if error.uncertain:
                raise BillingAPIError("下单结果未确定，请先到服务商官网核对订单；此确认不会重复提交", uncertain=True) from None
            raise
        order = self.owned_order(qq, key, local_id)
        await self.send(qq, f"订单已创建：{local_id}\n账单：{invoice}\n{checkout['summary']}")
        try:
            await self.payment(qq, key, provider, order, payload["payment"], client)
        except (BillingAPIError, ValueError):
            await self.send(qq, f"订单已保留，付款入口暂不可用。可重试：\n/财务付款 {key} {local_id} {payload['payment']}")

    async def payment(self, qq, key, provider, order, payment, client):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{0,63}", payment):
            raise ValueError("支付方式标识格式错误")
        data = await client.invoice(order["invoice_id"])
        invoice = invoice_record(data)
        if invoice.get("status") != "Unpaid":
            raise ValueError("账单已支付或当前不可付款，请查询订单状态")
        gateways = rows(data, "gateways") or await client.gateways()
        if payment not in {v.get("name") for v in gateways}:
            raise ValueError("此账单不支持所选支付方式")
        data = await client.pay(order["invoice_id"], payment)
        data = {**data, "invoiceid": order["invoice_id"]}
        target = parse_payment(data, provider["base_url"], provider.get("invoice_path", "/viewbilling?id={invoiceid}"))
        header = f"订单：{order['id']}\n付款金额：{display(data.get('total_desc', data.get('total', invoice.get('total', '以支付页面为准'))))}"
        if target["kind"] == "qr":
            output = BytesIO()
            try:
                qrcode.make(target["value"]).save(output, format="PNG")
            except (ValueError, OverflowError, qrcode.exceptions.DataOverflowError):
                fallback = parse_payment({"invoiceid": order["invoice_id"]}, provider["base_url"], provider.get("invoice_path", "/viewbilling?id={invoiceid}"))
                return await self.send(qq, header + "\n付款链接：" + fallback["value"])
            segments = [{"type": "text", "data": {"text": header + "\n请扫描付款二维码，付款后查询订单状态。"}},
                        {"type": "image", "data": {"file": "base64://" + b64encode(output.getvalue()).decode("ascii")}}]
            if target["value"].startswith(("https://", "http://")):
                segments.append({"type": "text", "data": {"text": "\n付款链接：" + target["value"]}})
            try:
                await self.bot.onebot.call("send_private_msg", {"user_id": int(qq), "message": segments})
            except (ConnectionError, RuntimeError, TimeoutError):
                # Only the payment reply is affected; the order is never replayed.
                await self.send(qq, header + "\n如未收到二维码，请查询订单或重新获取付款入口。")
        else:
            label = "二维码图片链接" if target["kind"] == "image" else "付款链接"
            await self.send(qq, header + f"\n{label}：" + target["value"])
