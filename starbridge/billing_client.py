"""Isolated, bounded HTTPS access to traditional 智简魔方财务 APIs."""
import asyncio
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re

import aiohttp
from yarl import URL

from .billing_config import PublicResolver, _url


MAX_RESPONSE = 2 * 1024 * 1024
_PATH = re.compile(r"/[A-Za-z0-9_/-]+\Z")
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")


class BillingAPIError(ValueError):
    """A safe message with an explicit signal for an unknown remote outcome."""
    def __init__(self, message="服务商请求未完成，请稍后到用户中心核对", *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class MofangClient:
    def __init__(self, provider, credentials, timeout=15):
        try:
            self.base_url = _url(provider["base_url"], https_only=True, base=True)
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
                raise ValueError()
            if not isinstance(credentials, dict):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise BillingAPIError("财务服务商配置无效") from None
        self.credentials = deepcopy(credentials)
        self.timeout = timeout
        self.session = None
        self._resolver = None
        self._jwt = None
        self._authenticated = False
        self._currency_id = None

    async def __aenter__(self):
        if self.session is not None:
            raise BillingAPIError("财务客户端会话已启动")
        self._resolver = PublicResolver()
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=self._resolver, ttl_dns_cache=0),
            cookie_jar=aiohttp.CookieJar(), timeout=aiohttp.ClientTimeout(total=self.timeout),
            trust_env=False, headers={"Accept": "application/json", "User-Agent": "VexBot"})
        return self

    async def __aexit__(self, kind, value, traceback):
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self._resolver is not None:
            await self._resolver.close()
            self._resolver = None
        self._jwt = None
        self._authenticated = False
        self._currency_id = None
        return False

    async def _transport(self, method, path, params=None, data=None):
        """The protected transport boundary is replaceable by offline test adapters."""
        if self.session is None:
            raise BillingAPIError("请先启动财务客户端会话")
        headers = {"Authorization": "JWT " + self._jwt} if self._jwt else {}
        async with self.session.request(method, self.base_url + path, params=params, data=data,
                                        headers=headers, allow_redirects=False) as response:
            # Inspect status before reading redirects or HTML error bodies.
            if not 200 <= response.status < 300:
                return response.status, b""
            if response.content_length is not None and response.content_length > MAX_RESPONSE:
                raise BillingAPIError("服务商响应过大，已停止处理", uncertain=method == "POST")
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise BillingAPIError("服务商响应过大，已停止处理", uncertain=method == "POST")
                chunks.append(chunk)
            return response.status, b"".join(chunks)

    async def request(self, method, path, params=None, data=None):
        method = str(method).upper()
        if (method not in ("GET", "POST") or not isinstance(path, str) or not _PATH.fullmatch(path)
                or any(part in (".", "..", "") for part in path.rstrip("/").split("/")[1:])):
            raise BillingAPIError("财务接口请求无效")
        try:
            status, body = await self._transport(method, path, params=params, data=data)
        except BillingAPIError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, UnicodeError, ValueError):
            raise BillingAPIError("服务商连接失败，请到用户中心核对后重试", uncertain=True) from None
        if status in (401, 403):
            raise BillingAPIError("服务商 API 认证失败，请检查 API 信息并重新绑定")
        if not 200 <= status < 300:
            raise BillingAPIError("服务商请求失败，请到用户中心核对", uncertain=method == "POST")
        try:
            if len(body) > MAX_RESPONSE:
                raise ValueError()
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError()
            business_status = result.get("status")
            if not ((type(business_status) is int and business_status == 200)
                    or (isinstance(business_status, str) and business_status == "200")):
                raise BillingAPIError("服务商未接受本次请求，请检查账号权限或商品设置", uncertain=method == "POST")
        except BillingAPIError:
            raise
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise BillingAPIError("服务商响应格式无效，请到用户中心核对", uncertain=method == "POST") from None
        return result

    @staticmethod
    def _data(response, *, uncertain=False):
        value = response.get("data")
        if isinstance(value, dict):
            return value
        if "data" not in response:
            # Traditional frontend releases also return their business fields
            # alongside status instead of wrapping them in a data object.
            value = {key: item for key, item in response.items()
                     if key not in ("status", "msg", "message", "jwt", "token")}
            if value:
                return value
        raise BillingAPIError("服务商响应缺少有效数据", uncertain=uncertain)

    @staticmethod
    def _id(value):
        if isinstance(value, bool) or not _ID.fullmatch(str(value)):
            raise BillingAPIError("服务商返回的编号无效")
        return str(value)

    @staticmethod
    def _amount(value):
        try:
            if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
                raise ValueError()
            number = Decimal(str(value))
            if not number.is_finite() or number < 0 or number > Decimal("1000000000000"):
                raise ValueError()
            return format(number, "f")
        except (ValueError, InvalidOperation):
            raise BillingAPIError("服务商返回的商品金额无效") from None

    async def login(self):
        account, api_key = self.credentials.get("account"), self.credentials.get("api_key")
        if (not isinstance(account, str) or not account or len(account) > 256
                or not isinstance(api_key, str) or not api_key or len(api_key) > 4096
                or any(ord(value) < 32 for value in account + api_key)):
            raise BillingAPIError("请提供有效的服务商账号和 API 密钥")
        self._jwt, self._authenticated, self._currency_id = None, False, None
        response = await self.request("POST", "/zjmf_api_login", data={"username": account, "password": api_key})
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        token = response.get("jwt") or response.get("token") or data.get("jwt") or data.get("token")
        if token is not None:
            if (not isinstance(token, str) or not token or len(token) > 16384
                    or any(ord(value) <= 32 or ord(value) == 127 for value in token)):
                raise BillingAPIError("服务商 API 登录响应中的认证信息无效")
            self._jwt = token
        if not self._jwt and not self._has_cookies():
            raise BillingAPIError("服务商 API 登录响应缺少有效认证会话")
        profile = dict(self._data(await self.request("GET", "/user_info")))
        raw_id = profile.get("id", profile.get("uid"))
        if raw_id is not None:
            identity = self._id(raw_id)
        else:
            email, phone = profile.get("email"), profile.get("phonenumber")
            if isinstance(email, str) and len(email) <= 254 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                identity = "email:" + email.casefold()
            elif isinstance(phone, str) and re.fullmatch(r"\+?[0-9 ()-]{6,32}", phone):
                digits = re.sub(r"[^0-9]", "", phone)
                if not 6 <= len(digits) <= 20:
                    raise BillingAPIError("服务商账号缺少可验证的唯一身份")
                identity = "phone:" + digits
            else:
                raise BillingAPIError("服务商账号缺少可验证的唯一身份")
        profile["id"] = identity
        self._capture_currency(profile.get("currency", profile.get("currencyid")))
        self._authenticated = True
        return profile

    def _capture_currency(self, value):
        if isinstance(value, dict):
            value = value.get("id", value.get("currencyid"))
        try:
            self._currency_id = self._id(value)
        except BillingAPIError:
            pass

    def _has_cookies(self):
        return self.session is not None and bool(self.session.cookie_jar.filter_cookies(URL(self.base_url + "/user_info")))

    def _require_auth(self):
        if not self._authenticated:
            raise BillingAPIError("请先通过服务商 API 验证账号")

    @staticmethod
    def _product(product):
        allowed = {"pid", "billingcycle", "qty", "configoption", "customfield", "host", "password", "os"}
        if not isinstance(product, dict) or set(product) - allowed:
            raise BillingAPIError("商品下单参数无效")
        fields = {"pid": MofangClient._id(product.get("pid"))}
        cycle, qty = product.get("billingcycle"), product.get("qty", 1)
        if (not isinstance(cycle, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", cycle)
                or isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 100):
            raise BillingAPIError("商品周期或数量无效")
        fields.update(billingcycle=cycle, qty=str(qty))
        for name in ("configoption", "customfield"):
            options = product.get(name, {})
            if not isinstance(options, dict) or len(options) > 100:
                raise BillingAPIError("商品配置参数无效")
            for key, value in options.items():
                option_id = MofangClient._id(key)
                if (not isinstance(value, (str, int)) or isinstance(value, bool) or len(str(value)) > 4096
                        or any(ord(char) < 32 for char in str(value))):
                    raise BillingAPIError("商品配置参数无效")
                fields[f"{name}[{option_id}]"] = str(value)
        for name in ("host", "password"):
            if name in product:
                value = product[name]
                if (not isinstance(value, str) or len(value) > 4096
                        or any(ord(char) < 32 for char in value)):
                    raise BillingAPIError("商品主机参数无效")
                fields[name] = value
        if "os" in product:
            operating_system = product["os"]
            if not isinstance(operating_system, dict) or len(operating_system) != 1:
                raise BillingAPIError("系统配置需使用系统 ID 到系统名称的对象")
            for key, name in operating_system.items():
                os_id = MofangClient._id(key)
                if (not isinstance(name, str) or not name or len(name) > 256
                        or any(ord(char) < 32 for char in name)):
                    raise BillingAPIError("系统配置名称无效")
                fields[f"os[{os_id}]"] = name
        return fields

    @staticmethod
    def _payment(payment):
        if not isinstance(payment, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", payment):
            raise BillingAPIError("支付方式无效")
        return payment

    async def products(self, **filters):
        self._require_auth()
        for alias, target in (("first_group_id", "first_gid"), ("group_id", "gid")):
            if alias in filters:
                if target in filters:
                    raise BillingAPIError("商品分组查询参数重复")
                filters[target] = filters.pop(alias)
        if set(filters) - {"first_gid", "gid", "currencyid", "keywords"}:
            raise BillingAPIError("商品分组查询参数无效")
        query = {}
        for key, value in filters.items():
            if key == "keywords":
                if not isinstance(value, str) or len(value) > 200 or any(ord(char) < 32 for char in value):
                    raise BillingAPIError("商品搜索参数无效")
                query[key] = value
            elif str(value) == "0":
                query[key] = "0"
            else:
                query[key] = self._id(value)
        return self._data(await self.request("GET", "/cart/index", params=query or None))

    async def detail(self, pid):
        self._require_auth()
        return self._data(await self.request("GET", "/cart/get_product_config", params={"pid": self._id(pid)}))

    async def quote(self, product):
        self._require_auth()
        fields = self._product(product)
        if self._currency_id:
            fields["currencyid"] = self._currency_id
        result = dict(self._data(await self.request("POST", "/cart/get_total", data=fields)))
        self._capture_currency(result.get("currency", result.get("currencyid")))
        total = result.get("total")
        if total is None and isinstance(result.get("products"), dict):
            prices = result["products"]
            total = prices.get("sale_total", prices.get("total"))
        result["total"] = self._amount(total)
        return result

    async def create_order(self, product, payment):
        self._require_auth()
        fields = self._product(product)
        fields["checkout"] = "0"
        gateway = self._payment(payment)
        if self._currency_id is None:
            raise BillingAPIError("服务商未返回有效币种编号，请到用户中心核对币种设置")
        fields["currencyid"] = self._currency_id
        cart = self._data(await self.request("POST", "/cart/add_to_shop", data=fields), uncertain=True)
        position = cart.get("i")
        # This API returns a zero-based cart position, not a product identifier.
        if isinstance(position, bool) or not re.fullmatch(r"[0-9]{1,9}", str(position)):
            raise BillingAPIError("服务商购物车响应缺少本次商品位置，请到用户中心核对", uncertain=True)
        order = dict(self._data(await self.request("POST", "/cart/settle",
                                                   data={"payment": gateway, "pos[]": str(position)}), uncertain=True))
        try:
            order["invoiceid"] = self._id(order.get("invoiceid"))
            if order.get("orderid") is not None:
                order["orderid"] = self._id(order["orderid"])
        except BillingAPIError:
            raise BillingAPIError("服务商下单响应缺少有效账单，请到用户中心核对", uncertain=True) from None
        return order

    async def gateways(self):
        self._require_auth()
        envelope = await self.request("GET", "/get_gateways/gateways/")
        values = envelope.get("data")
        if isinstance(values, dict):
            values = values.get("gateways")
        if not isinstance(values, list):
            raise BillingAPIError("服务商支付方式响应格式无效")
        result = []
        for gateway in values:
            if not isinstance(gateway, dict):
                raise BillingAPIError("服务商支付方式响应格式无效")
            name = self._payment(gateway.get("name"))
            title = gateway.get("title", name)
            if (not isinstance(title, str) or not title or len(title) > 200
                    or any(ord(char) < 32 for char in title)):
                raise BillingAPIError("服务商支付方式响应格式无效")
            result.append({"name": name, "title": title})
        return result

    async def invoice(self, invoice_id):
        self._require_auth()
        target = self._id(invoice_id)
        data = self._data(await self.request("GET", "/invoices/" + target))
        invoices = data.get("invoices")
        if not isinstance(invoices, list):
            raise BillingAPIError("服务商账单响应格式无效")
        for invoice in invoices:
            if isinstance(invoice, dict) and str(invoice.get("id")) == target:
                return {**data, **invoice, "id": target}
        raise BillingAPIError("服务商未返回本次账单，请到用户中心核对")

    async def pay(self, invoice_id, payment):
        self._require_auth()
        target, gateway = self._id(invoice_id), self._payment(payment)
        data = dict(self._data(await self.request("POST", "/start_pay", data={"invoiceid": target, "payment": gateway}), uncertain=True))
        data["invoiceid"] = target
        # The presentation layer accepts this stable name and never executes HTML.
        data["_pay_html"] = data.get("pay_html")
        return data
