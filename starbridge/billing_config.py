"""Configuration and untrusted payment response boundaries for billing providers."""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import socket
import tomllib
from urllib.parse import unquote, urlsplit, urlunsplit

from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver


_SLUG = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_BASE_PATH = re.compile(r"(?:/[A-Za-z0-9._~-]+)*/?\Z")
_FORBIDDEN_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".invalid", ".test", ".example", ".onion")
DEFAULT_INVOICE_PATH = "/viewbilling?id={invoiceid}"


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return _public_address(str(address.ipv4_mapped))
    return address.is_global and not any((address.is_multicast, address.is_reserved,
                                           address.is_loopback, address.is_link_local))


def _public_host(host: str | None) -> bool:
    if not host or len(host) > 253 or not host.isascii() or host.endswith("."):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        lowered = host.lower()
        if lowered == "localhost" or lowered.endswith(_FORBIDDEN_SUFFIXES):
            return False
        labels = lowered.split(".")
        # Numeric/non-canonical IP spellings such as 2130706433 or 127.1 must
        # never be accepted as domains by the HTTP library's address parser.
        return (len(labels) >= 2 and not labels[-1].isdigit()
                and all(_LABEL.fullmatch(label) for label in labels))
    return _public_address(host)


def _url(value: object, *, https_only: bool, base: bool = False) -> str:
    """Validate without resolving or fetching an untrusted URL; omit it in errors."""
    if (not isinstance(value, str) or not value or len(value) > 8192
            or any(ord(character) <= 32 or ord(character) == 127 for character in value)
            or any(character in value for character in '\\<>"\'`')):
        raise ValueError("服务商地址或支付地址格式无效")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        valid = (parsed.scheme in (("https",) if https_only else ("http", "https"))
                 and parsed.username is None and parsed.password is None
                 and _public_host(parsed.hostname)
                 and (port is None or 1 <= port <= 65535))
    except (ValueError, UnicodeError):
        raise ValueError("服务商地址或支付地址格式无效") from None
    if not valid:
        raise ValueError("服务商地址或支付地址必须使用公网主机")
    if base:
        if ("?" in value or "#" in value or not _BASE_PATH.fullmatch(parsed.path)
                or any(segment in (".", "..") for segment in parsed.path.split("/"))
                or parsed.path.rstrip("/").lower().endswith("/v1")):
            raise ValueError("服务商根地址不能包含查询、片段、相对路径或末尾 /v1")
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))
    return value


def _invoice_path(value: object, base_url: str) -> str:
    if (not isinstance(value, str) or len(value) > 1024
            or not value.startswith("/") or value.startswith("//")
            or value.count("{invoiceid}") != 1):
        raise ValueError("账单页面模板必须为同站相对路径且只包含一次 {invoiceid}")
    candidate = value.replace("{invoiceid}", "1")
    decoded = candidate
    for _ in range(5):
        previous, decoded = decoded, unquote(decoded)
        if previous == decoded:
            break
    if (any(character in decoded for character in "{}\\#") or decoded.startswith("//")
            or any(ord(character) <= 32 or ord(character) == 127 for character in decoded)
            or any(segment in (".", "..") for segment in urlsplit(decoded).path.split("/"))):
        raise ValueError("账单页面模板不能包含路径遍历、控制字符、片段或额外占位符")
    # Reuse the URL boundary after substitution, without ever resolving or
    # fetching a custom template or permitting another origin.
    target = _url(base_url + candidate, https_only=True)
    if urlsplit(target).netloc != urlsplit(base_url).netloc:
        raise ValueError("账单页面模板必须使用当前服务商域名")
    return value


def validate_config(config: dict) -> dict:
    """Return a new, normalized configuration; reject typos and unsafe endpoints."""
    if not isinstance(config, dict) or set(config) - {"enabled", "timeout", "providers"}:
        raise ValueError("billing.toml 包含未知配置项")
    enabled = config.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("billing.enabled 必须为布尔值")
    timeout = config.get("timeout", 15)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 5 <= timeout <= 60:
        raise ValueError("billing.timeout 必须为 5 至 60 秒")
    providers = config.get("providers", {})
    if not isinstance(providers, dict) or len(providers) > 20:
        raise ValueError("billing.providers 必须为配置表且最多包含 20 家服务商")
    normalized = {}
    for slug, provider in providers.items():
        if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
            raise ValueError("服务商标识需以小写字母开头，最多 32 位，仅包含字母、数字、下划线或连字符")
        if (not isinstance(provider, dict) or not {"name", "base_url"} <= set(provider)
                or set(provider) - {"name", "base_url", "invoice_path"}):
            raise ValueError("服务商配置必须包含 name 和 base_url，可选 invoice_path")
        name = provider["name"]
        if (not isinstance(name, str) or not name.strip() or len(name) > 80
                or any(ord(character) < 32 or ord(character) == 127 for character in name)):
            raise ValueError("服务商名称必须为 1 至 80 个可见字符")
        normalized[slug] = {"name": name.strip(), "base_url": _url(provider["base_url"], https_only=True, base=True)}
        if "invoice_path" in provider:
            normalized[slug]["invoice_path"] = _invoice_path(provider["invoice_path"], normalized[slug]["base_url"])
    if enabled and not normalized:
        raise ValueError("启用财务服务至少需要配置一家服务商")
    return {"enabled": enabled, "timeout": timeout, "providers": normalized}


def load_config(base: Path) -> dict:
    """Read billing.toml beside config.toml, with the integration disabled by default."""
    base = Path(base)
    path = (base.parent if base.suffix == ".toml" else base) / "billing.toml"
    if not path.exists():
        return {"enabled": False, "providers": {}}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        # TOML parse errors can quote the offending line, including a secret.
        raise ValueError("billing.toml 无法读取或 TOML 格式无效") from None
    return validate_config(data)


class PublicResolver(AbstractResolver):
    """Resolve once per connection and pass only public DNS answers to aiohttp."""

    def __init__(self, resolver: AbstractResolver | None = None):
        self._resolver = resolver if resolver is not None else DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if not _public_host(host):
            raise OSError("服务商地址必须为公网主机")
        try:
            answers = await self._resolver.resolve(host, port, family=family)
        except (OSError, ValueError):
            raise OSError("服务商域名解析失败") from None
        if not answers or any(not _public_address(answer.get("host", "")) for answer in answers):
            raise OSError("服务商域名含有非公网地址，已拒绝连接")
        return answers

    async def close(self):
        await self._resolver.close()


def _qr_uri(value: object) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("支付二维码内容无效")
    if value.startswith(("http://", "https://")):
        return _url(value, https_only=False)
    if (any(ord(character) <= 32 or ord(character) == 127 for character in value)
            or any(character in value for character in '\\<>"\'`')):
        raise ValueError("支付二维码内容无效")
    try:
        parsed = urlsplit(value)
        valid = (parsed.username is None and parsed.password is None and parsed.port is None
                 and not parsed.fragment and bool(parsed.query)
                 and ((parsed.scheme == "weixin" and parsed.netloc == "wxpay" and parsed.path == "/bizpayurl")
                      or (parsed.scheme in ("alipay", "alipays") and parsed.netloc == "platformapi"
                          and parsed.path == "/startapp")))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("支付二维码内容不是受支持的支付地址")
    return value


def _checkout(data: dict, base_url: str, invoice_path: str) -> dict:
    invoice = data.get("invoiceid", data.get("invoice_id"))
    if isinstance(invoice, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(invoice)):
        raise ValueError("支付响应缺少有效账单编号，请到服务商用户中心支付")
    return {"kind": "checkout", "value": _url(base_url + invoice_path.replace("{invoiceid}", str(invoice)), https_only=True)}


def parse_payment(data: dict, base_url: str, invoice_path: str = DEFAULT_INVOICE_PATH) -> dict:
    """Convert provider payment data into display-only content; never execute HTML."""
    base_url = _url(base_url, https_only=True, base=True)
    invoice_path = _invoice_path(invoice_path, base_url)
    if not isinstance(data, dict):
        raise ValueError("服务商支付响应格式无效")
    payment = data.get("pay_html", data.get("_pay_html"))
    if not isinstance(payment, dict):
        return _checkout(data, base_url, invoice_path)
    kind, value = payment.get("type"), payment.get("data")
    if kind == "url":
        return {"kind": "qr", "value": _qr_uri(value)}
    if kind == "jump":
        return {"kind": "link", "value": _url(value, https_only=False)}
    if kind == "insert":
        # Plugins may return executable HTML here. Only a plain HTTPS image
        # address can be displayed; all snippets use the native checkout page.
        if isinstance(value, str) and value.startswith("https://"):
            return {"kind": "image", "value": _url(value, https_only=True)}
        return _checkout(data, base_url, invoice_path)
    return _checkout(data, base_url, invoice_path)
