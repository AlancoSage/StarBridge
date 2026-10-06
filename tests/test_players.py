import time
import unittest
import uuid

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from tests.test_starbridge import config


STEVE = "11111111-1111-4111-8111-111111111111"


def record(name="Steve", identity=STEVE, online=True):
    result = {"name": name, "uuid": identity, "online": online, "banned": False,
              "whitelisted": True, "op": False, "last_played": 1700000000000}
    if online:
        result.update(world="world", game_mode="SURVIVAL", health=20, ping=42)
    return result


class PlayerManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = config()
        self.cfg["servers"].append({"id": "creative", "name": "创造服", "token": "creative-" + "d" * 32,
                                    "groups": ["102"], "commands": {}})
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.admin = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.game = {"Authorization": "Bearer " + self.cfg["servers"][0]["token"]}

    async def asyncTearDown(self):
        await self.client.close()

    async def tick(self, **extra):
        payload = {"players": ["Steve"], "player_records": [record()], "capabilities": ["player_management"],
                   "max_players": 20, "whitelist_enabled": True, "events": [], "results": [], **extra}
        return await self.client.post("/bridge/survival/tick", headers=self.game, json=payload)

    def operation(self, **extra):
        return {"request_id": str(uuid.uuid4()), "server": "survival", "uuid": STEVE,
                "player": "Steve", "action": "kick", "reason": "违反群规", **extra}

    async def submit(self, payload):
        return await self.client.post("/api/player-actions", headers=self.admin, json=payload)

    async def status(self):
        return await (await self.client.get("/api/status", headers=self.admin)).json()

    async def test_auth_online_and_upgrade_checks(self):
        self.assertEqual((await self.client.post("/api/player-actions", json=self.operation())).status, 401)
        self.assertEqual((await self.client.post("/api/player-actions", headers=self.game, json=self.operation())).status, 401)
        self.assertEqual((await self.client.get("/api/plugin")).status, 401)
        self.assertEqual((await self.submit(self.operation())).status, 409)
        self.assertEqual((await self.tick(capabilities=[], player_records=[])).status, 200)
        self.assertEqual((await self.submit(self.operation())).status, 409)
        self.assertEqual(self.state["store"].poll("survival"), [])

    async def test_identity_and_input_validation(self):
        await self.tick()
        for extra in ({"player": "Steve\nstop"}, {"uuid": "bad"}, {"action": "op"}, {"reason": "a\nstop"}, {"reason": "x" * 121}, {"request_id": "bad"}):
            self.assertEqual((await self.submit(self.operation(**extra))).status, 400)
        self.assertEqual((await self.submit(self.operation(uuid=str(uuid.uuid4())))).status, 409)
        self.assertEqual((await self.submit(self.operation(player="Alex"))).status, 409)
        await self.tick(players=[], player_records=[record(online=False)])
        self.assertEqual((await self.submit(self.operation())).status, 409)
        self.assertEqual((await self.submit(self.operation(action="whitelist_add"))).status, 202)

    async def test_idempotent_submission_and_real_result(self):
        await self.tick()
        payload = self.operation()
        response = await self.submit(payload)
        self.assertEqual(response.status, 202)
        result = await response.json()
        self.assertEqual(result["status"], "pending")
        self.assertEqual((await self.submit(payload)).status, 200)
        self.assertEqual((await self.submit({**payload, "action": "ban"})).status, 409)
        jobs = await (await self.tick()).json()
        self.assertEqual(len(jobs["jobs"]), 1)
        job = jobs["jobs"][0]
        self.assertEqual(job["kind"], "player_action")
        self.assertEqual(job["uuid"], STEVE)
        self.assertNotIn("command", job)
        answer = {"id": job["id"], "ok": True, "detail": "已踢出 Steve"}
        wrong_game = {"Authorization": "Bearer " + self.cfg["servers"][1]["token"]}
        await self.client.post("/bridge/creative/tick", headers=wrong_game, json={"results": [answer]})
        self.assertEqual(self.state["store"].player_action(job["id"])["status"], "pending")
        await self.tick(results=[answer], players=[], player_records=[record(online=False)])
        await self.tick(results=[answer], players=[], player_records=[record(online=False)])
        data = await self.status()
        self.assertEqual(data["player_actions"][0]["status"], "success")
        self.assertEqual(data["player_actions"][0]["detail"], "已踢出 Steve")
        self.assertEqual(len([log for log in data["logs"] if log["kind"] == "player" and "完成" in log["detail"]]), 1)
        self.assertIsNone(self.state["store"].job("survival", job["id"]))

    async def test_failure_expiry_and_revocation(self):
        await self.tick()
        item = await (await self.submit(self.operation(action="ban"))).json()
        await self.tick(results=[{"id": item["id"], "ok": False, "detail": "插件执行失败"}])
        self.assertEqual(self.state["store"].player_action(item["id"])["status"], "failed")
        expired = await (await self.submit(self.operation())).json()
        with self.state["store"].db:
            self.state["store"].db.execute("UPDATE player_actions SET expires=0 WHERE id=?", (expired["id"],))
        data = await self.status()
        self.assertEqual(data["player_actions"][0]["status"], "expired")
        await self.tick(results=[{"id": expired["id"], "ok": True, "detail": "late result"}])
        self.assertEqual(self.state["store"].player_action(expired["id"])["status"], "expired")
        cancelled = await (await self.submit(self.operation(action="whitelist_remove"))).json()
        self.state["store"].cancel_player_actions("survival")
        self.assertEqual(self.state["store"].player_action(cancelled["id"])["status"], "cancelled")

    async def test_player_data_bindings_and_stale_state(self):
        code = self.state["store"].issue_code("survival", STEVE, "Steve")
        self.state["store"].bind("survival", "2001", code)
        await self.tick()
        data = await self.status()
        player = data["players"][0]
        self.assertEqual(player["qq"], "2001")
        self.assertEqual(player["ping"], 42)
        self.assertTrue(player["manageable"])
        self.assertEqual(player["status"], "online")
        self.state["bot"].snapshots["survival"]["last_seen"] = time.time() - 20
        stale = (await self.status())["players"][0]
        self.assertEqual(stale["status"], "unknown")
        self.assertFalse(stale["manageable"])
        await self.tick(player_records=[], capabilities=[])
        legacy = (await self.status())["players"]
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]["qq"], "2001")
        self.assertFalse(legacy[0]["manageable"])

    async def test_malformed_plugin_records_do_not_replace_snapshot(self):
        await self.tick()
        for change in ({"uuid": "bad"}, {"health": float("nan")}, {"ping": -1}, {"online": "yes"}, {"name": "Bad Name"}):
            self.assertEqual((await self.tick(player_records=[{**record(), **change}])).status, 400)
        self.assertEqual((await self.tick(player_records=[record()] * 501)).status, 400)
        self.assertEqual((await self.status())["players"][0]["name"], "Steve")


if __name__ == "__main__":
    unittest.main()
