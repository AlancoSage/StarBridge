"""Fixed native game-end catalog; query values never become arbitrary filesystem paths."""
from . import __forge_version__

GAME_BRIDGES = (
    {"platform": "forge", "version": "1.7.10", "loader_version": "10.13.4.1614", "java": 8, "config": "properties"},
    {"platform": "forge", "version": "1.12.2", "loader_version": "14.23.5.2859", "java": 8, "config": "properties"},
    {"platform": "forge", "version": "1.16.5", "loader_version": "36.2.34", "java": 8, "config": "properties"},
    {"platform": "forge", "version": "1.18.2", "loader_version": "40.3.0", "java": 17, "config": "toml"},
    {"platform": "forge", "version": "1.19.2", "loader_version": "43.5.0", "java": 17, "config": "toml"},
    {"platform": "forge", "version": "1.20.1", "loader_version": "47.4.10", "java": 17, "config": "toml"},
    {"platform": "neoforge", "version": "1.21.1", "loader_version": "21.1.256", "java": 21, "config": "toml"},
    {"platform": "fabric", "version": "1.16.5", "loader_version": "0.16.14", "java": 8, "config": "properties"},
    {"platform": "fabric", "version": "1.18.2", "loader_version": "0.16.14", "java": 17, "config": "properties"},
    {"platform": "fabric", "version": "1.19.2", "loader_version": "0.16.14", "java": 17, "config": "properties"},
    {"platform": "fabric", "version": "1.20.1", "loader_version": "0.16.14", "java": 17, "config": "properties"},
    {"platform": "fabric", "version": "1.21.1", "loader_version": "0.16.14", "java": 21, "config": "properties"},
)

LOADER_LABELS = {"forge": "Forge", "neoforge": "NeoForge", "fabric": "Fabric"}

def bridge_filename(platform: str, version: str) -> str:
    if not any(item["platform"] == platform and item["version"] == version for item in GAME_BRIDGES):
        raise ValueError("不支持的游戏端版本")
    loader = LOADER_LABELS[platform]
    return f"StarBridge-{loader}-{version}-{__forge_version__}.jar"

def bridge_catalog() -> list[dict]:
    return [{**item, "label": f'{LOADER_LABELS[item["platform"]]} {item["version"]}',
             "filename": bridge_filename(item["platform"], item["version"])} for item in GAME_BRIDGES]
