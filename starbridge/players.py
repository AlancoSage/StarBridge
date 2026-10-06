import math
import re
import uuid
from .catalog import address


PLAYER_ACTIONS = {"kick", "ban", "unban", "whitelist_add", "whitelist_remove"}


def player_records(data):
    records = data.get("player_records", [])
    if not isinstance(records, list) or len(records) > 500:
        raise ValueError("玩家记录超过限制")
    output, identities = [], set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("玩家记录格式错误")
        name, identity = item.get("name"), str(uuid.UUID(item.get("uuid")))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name) or identity in identities:
            raise ValueError("玩家名称或 UUID 错误")
        row = {"name": name, "uuid": identity}
        if "ip" in item:
            row["ip"] = address(item["ip"])
        for flag in ("online", "banned", "whitelisted", "op"):
            if type(item.get(flag)) is not bool:
                raise ValueError("玩家状态格式错误")
            row[flag] = item[flag]
        last_played = item.get("last_played", 0)
        if type(last_played) is not int or not 0 <= last_played <= 2**53:
            raise ValueError("玩家时间格式错误")
        row["last_played"] = last_played
        if row["online"]:
            world, mode = item.get("world", ""), item.get("game_mode", "")
            health, ping = item.get("health", 0), item.get("ping", 0)
            if (not isinstance(world, str) or len(world) > 80
                or mode not in {"SURVIVAL", "CREATIVE", "ADVENTURE", "SPECTATOR"}
                or type(health) not in (int, float) or not math.isfinite(health) or not 0 <= health <= 2048
                or type(ping) is not int or not 0 <= ping <= 600000):
                raise ValueError("玩家详情格式错误")
            row.update(world=world, game_mode=mode, health=health, ping=ping)
        identities.add(identity)
        output.append(row)
    return output


def management_state(state):
    bot, store = state["bot"], state["store"]
    bindings = {(b["server"], b["uuid"]): b for b in store.bindings()}
    players, servers = [], []
    for sid, server in bot.servers.items():
        snap = bot.snapshots.get(sid, {})
        online = bot.online(sid)
        capable = "player_management" in snap.get("capabilities", [])
        servers.append({"id": sid, "name": server["name"], "online": online,
                        "supported": capable, "truncated": snap.get("players_truncated", False),
                        "whitelist_enabled": snap.get("whitelist_enabled"), "last_seen": snap.get("last_seen")})
        records = {p["uuid"]: dict(p) for p in snap.get("player_records", [])}
        names = {p["name"].lower() for p in records.values()}
        for name in snap.get("players", []):
            if name.lower() not in names:
                records["name:" + name] = {"name": name, "uuid": None, "online": True}
                names.add(name.lower())
        for (scope, identity), bound in bindings.items():
            if scope == sid and identity not in records and bound["name"].lower() not in names:
                records[identity] = {"name": bound["name"], "uuid": identity, "online": False}
                names.add(bound["name"].lower())
        reported = {p["uuid"] for p in snap.get("player_records", [])}
        for player in records.values():
            bound = bindings.get((sid, player.get("uuid")))
            if bound is None and not player.get("uuid"):
                bound = next((b for (scope, _), b in bindings.items() if scope == sid and b["name"].lower() == player["name"].lower()), None)
            known = player.get("uuid") in reported
            player.update(server=sid, server_name=server["name"], qq=bound["qq"] if bound else None,
                          status=("online" if player.get("online") else "offline") if online and (known or player.get("online")) else "unknown",
                          manageable=online and capable and known)
            players.append(player)
    players.sort(key=lambda p: (p["status"] != "online", p["server_name"], p["name"].lower()))
    return {"players": players, "player_servers": servers, "player_actions": store.player_actions()}
