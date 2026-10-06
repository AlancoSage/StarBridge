from pathlib import Path
import secrets
import tomllib
from .settings import runtime_config, validate


def initialize(path: Path):
    if path.exists():
        raise ValueError(f"配置已存在，未覆盖：{path}")
    template = Path(__file__).resolve().parent.parent / "config.example.toml"
    text = template.read_text(encoding="utf-8")
    for role in ("admin", "onebot", "bridge"):
        text = text.replace(f"CHANGE-ME-{role}", secrets.token_urlsafe(32))
    path.write_text(text, encoding="utf-8")


def load(path: Path):
    return runtime_config(validate(tomllib.loads(path.read_text(encoding="utf-8"))), path)
