"""Separate official OpenIDs from traditional QQ identities and other apps."""
import re

OFFICIAL_DEFAULTS = {"enabled": False, "app_id": "", "client_secret": "", "admins": [], "allow_active": False}
NUMERIC = re.compile(r"[1-9][0-9]{0,19}")
OFFICIAL = re.compile(r"(qg|qug|qup):([1-9][0-9]{0,19}):([A-Za-z0-9_-]{1,128})")


def official_id(kind, app_id, openid):
    if not isinstance(kind, str) or not isinstance(app_id, str) or not isinstance(openid, str):
        raise ValueError("官机身份格式错误")
    value = f"{kind}:{app_id}:{openid}"
    if not OFFICIAL.fullmatch(value):
        raise ValueError("官机身份格式错误")
    return value


def official_parts(value, kinds):
    match = OFFICIAL.fullmatch(value) if isinstance(value, str) else None
    if not match or match[1] not in kinds:
        return None
    return match[1], match[2], match[3]


def user_id(value):
    return isinstance(value, str) and bool(NUMERIC.fullmatch(value) or official_parts(value, ("qug", "qup")))


def group_id(value):
    return isinstance(value, str) and bool(NUMERIC.fullmatch(value) or official_parts(value, ("qg",)))
