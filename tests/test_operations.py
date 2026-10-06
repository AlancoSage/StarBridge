import asyncio
from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, PropertyMock, patch
import uuid
import zipfile
import hashlib

from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import STATE, create_app
from starbridge.backups import apply_pending_restore, finish_restore
from starbridge.config import load
from starbridge.extensions import permission_value, SCHEDULES_ID, atomic_json
from starbridge.operations import CHINA, OperationError, next_run, task_definition
from starbridge.settings import serialize
from test_settings import full_config
from test_extensions import example


def task(action="game_message", enabled=False):
    return {"name":"测试任务", "enabled":enabled, "schedule":"interval", "interval_minutes":60,
            "clock":"08:00", "weekdays":[1,2,3,4,5,6,7], "action":action,
            "server":"survival", "group":"101", "message":"请文明游戏", "command":"在线检查"}


class OperationValidationTests(unittest.TestCase):
    def test_weekday_timezone_and_interval_deadlines(self):
        now = datetime(2026,10,5,8,0,tzinfo=CHINA).timestamp()
        d=task();self.assertEqual(next_run(d,now),now+3600)
        d.update(schedule="daily",weekdays=[1])
        self.assertEqual(datetime.fromtimestamp(next_run(d,now),CHINA),datetime(2026,10,12,8,0,tzinfo=CHINA))
        d["weekdays"]=[2,3]
        self.assertEqual(datetime.fromtimestamp(next_run(d,now),CHINA).weekday(),1)

    def test_reject_bad_task_and_policy_values(self):
        for change in ({"enabled":1},{"clock":"24:00"},{"weekdays":[]},{"weekdays":[1,1]},
                       {"interval_minutes":True},{"action":"shell"},{"name":"bad\nname"},{"message":"x"*2001},{"message":"x"*601}):
            with self.subTest(change=change), self.assertRaises(OperationError):task_definition(task()|change)
        for value in ({"user_mode":[]},{"groups":["../bad"]},{"servers":["x","x"]},{"read_bindings":1},{"exec":True}):
            with self.subTest(policy=value),self.assertRaises(ValueError):permission_value(value)


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.path=self.base/"config.toml";self.cfg=full_config();self.path.write_text(serialize(self.cfg),encoding="utf-8")
        self.client=TestClient(TestServer(create_app(load(self.path),config_path=self.path,restart_event=asyncio.Event())))
        await self.client.start_server();self.state=self.client.app[STATE];self.service=self.state["operations"];self.db=self.state["store"].db
        self.headers={"Authorization":"Bearer "+self.cfg["app"]["admin_token"]}
        self.bot=self.state["bot"];self.bot.snapshots["survival"]={"last_seen":time.time(),"players":[],"player_records":[],"capabilities":["whitelist_application"]}
        self.state["onebot"].send_group=AsyncMock()
        manager=self.state['plugins']
        await manager.update(SCHEDULES_ID,{'revision':manager.revision,'enabled':True})

    async def asyncTearDown(self):
        if self.client is not None:await self.client.close()
        self.tmp.cleanup()

    def open_applications(self, **settings):
        config=self.service.config();self.service.save_config(config["settings"]|{"enabled":True}|settings,config["revision"])

    async def test_admin_routes_and_optimistic_revisions(self):
        for path in ("/api/schedules","/api/whitelist","/api/whitelist/settings","/api/operations/guide"):
            response=await self.client.get(path);self.assertEqual(response.status,401)
            response=await self.client.get(path,headers={"Authorization":"Bearer "+self.cfg["servers"][0]["token"]});self.assertEqual(response.status,401)
        response=await self.client.post("/api/schedules",headers=self.headers,json={"definition":task()})
        self.assertEqual(response.status,200);row=await response.json()
        changed=self.service.save_task(task(),row["id"],row["revision"])
        response=await self.client.delete("/api/schedules/"+row["id"],headers=self.headers,json={"revision":row["revision"]})
        self.assertEqual(response.status,409)
        response=await self.client.delete("/api/schedules/"+row["id"],headers=self.headers,json={"revision":changed["revision"]})
        self.assertEqual(response.status,200)
        cfg=self.service.config();self.service.save_config(cfg["settings"],cfg["revision"])
        with self.assertRaises(OperationError):self.service.save_config(cfg["settings"],cfg["revision"])

    async def test_plugin_pause_blocks_manual_and_due_tasks_without_deleting_data(self):
        manager=self.state['plugins'];row=self.service.save_task(task('command',True))
        await manager.update(SCHEDULES_ID,{'revision':manager.revision,'enabled':False})
        with self.db:self.db.execute('UPDATE scheduled_tasks SET next_run=? WHERE id=?',(time.time()-1,row['id']))
        await self.service.tick_due()
        response=await self.client.post('/api/schedules/'+row['id']+'/run',headers=self.headers,json={'revision':row['revision']})
        self.assertEqual(response.status,403)
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(len(self.service.tasks()['runs']),0)
        self.assertTrue(self.service.task(row['id'])['definition']['enabled'])
        await manager.update(SCHEDULES_ID,{'revision':manager.revision,'enabled':True})
        self.assertGreater(self.service.task(row['id'])['next_run'],time.time())
        await self.service.tick_due();self.assertEqual(len(self.service.tasks()['runs']),0)

    async def test_plugin_action_permissions_and_targets_cover_every_execution(self):
        manager=self.state['plugins']
        for action,capability in [('qq_message','send_group'),('game_message','send_game'),('command','execute_commands'),('backup','create_backups')]:
            with self.subTest(action=action):
                policy=permission_value({capability:False})
                await manager.update(SCHEDULES_ID,{'revision':manager.revision,'permissions':policy})
                row=self.service.save_task(task(action))
                result=await self.service.run_task(row['id'],True,row['revision'])
                self.assertEqual(result['status'],'failed');self.assertIn('未获授权',result['detail'])
        for action,policy in [('command',{'servers':['other']}),('qq_message',{'groups':['999']})]:
            await manager.update(SCHEDULES_ID,{'revision':manager.revision,'permissions':permission_value(policy)})
            row=self.service.save_task(task(action));result=await self.service.run_task(row['id'],True,row['revision'])
            self.assertEqual(result['status'],'failed');self.assertIn('授权范围',result['detail'])
        self.state['onebot'].send_group.assert_not_awaited()
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.assertFalse(list((self.base/'data/backups').glob('*.zip')))

    async def test_first_migration_inherits_enabled_tasks_and_never_reenables_after_stop(self):
        manager=self.state['plugins'];row=self.service.save_task(task('game_message',True))
        manager.saved.pop(SCHEDULES_ID);atomic_json(manager.state_path,manager.saved)
        await manager.start();self.assertTrue(self.service.scheduler_enabled())
        await manager.update(SCHEDULES_ID,{'revision':manager.revision,'enabled':False})
        await manager.start();self.assertFalse(self.service.scheduler_enabled())
        self.assertTrue(self.service.task(row['id'])['definition']['enabled'])
        app=create_app({**self.cfg,'app':{**self.cfg['app'],'database':':memory:'}})
        async with TestClient(TestServer(app)):
            self.assertFalse(app[STATE]['operations'].scheduler_enabled())

    async def test_failed_plugin_resume_keeps_paused_state_and_deadlines(self):
        manager=self.state['plugins'];row=self.service.save_task(task('command',True))
        await manager.update(SCHEDULES_ID,{'revision':manager.revision,'enabled':False})
        deadline=time.time()-1
        with self.db:self.db.execute('UPDATE scheduled_tasks SET next_run=? WHERE id=?',(deadline,row['id']))
        with patch('starbridge.extensions.atomic_json',side_effect=OSError('test disk failure')),self.assertRaises(OSError):
            await manager.update(SCHEDULES_ID,{'revision':manager.revision,'enabled':True})
        self.assertFalse(self.service.scheduler_enabled());self.assertEqual(self.service.task(row['id'])['next_run'],deadline)

    async def test_schedule_only_account_controls_plugin_without_access_to_other_plugins(self):
        data={'username':'Scheduler','password':'Scheduler-password-2026','permissions':['status.read','schedules.manage']}
        response=await self.client.post('/api/admin-users',headers=self.headers,json=data);self.assertEqual(response.status,200)
        login=await(await self.client.post('/api/admin-auth/login',json={'username':data['username'],'password':data['password']})).json()
        headers={'Authorization':'Bearer '+login['access_token']}
        result=await(await self.client.get('/api/schedules',headers=headers)).json()
        self.assertIn('servers',result);self.assertNotIn('token',json.dumps(result['servers']))
        response=await self.client.put('/api/schedules/plugin',headers=headers,json={'revision':result['plugin_revision'],'enabled':False})
        self.assertEqual(response.status,200);self.assertFalse((await response.json())['plugin']['enabled'])
        self.assertEqual((await self.client.get('/api/extensions',headers=headers)).status,403)
        self.assertEqual((await self.client.get('/api/operations/guide',headers=headers)).status,200)
        self.assertEqual((await self.client.put('/api/schedules/plugin',headers=headers,json={'revision':result['plugin_revision'],'enabled':True})).status,409)
        self.assertEqual((await self.client.put('/api/schedules/plugin',headers=headers,json={'enabled':True,'permissions':{}})).status,400)

    async def test_game_command_submitted_then_confirmed_once(self):
        row=self.service.save_task(task("command"));run=await self.service.run_task(row["id"],True,row["revision"])
        self.assertEqual(run["status"],"submitted")
        job=self.state["store"].job("survival",run["job"]);self.assertEqual(job["command"],"list")
        with self.assertRaises(OperationError):await self.service.run_task(row["id"],True,row["revision"])
        response=await self.client.post("/bridge/survival/tick",headers={"Authorization":"Bearer "+self.cfg["servers"][0]["token"]},json={"players":[],"results":[{"id":run["job"],"ok":True,"detail":"已执行"}]})
        self.assertEqual(response.status,200)
        self.assertEqual(self.service.tasks()["runs"][0]["status"],"success")
        self.state["onebot"].send_group.assert_not_awaited()
        self.assertIsNone(self.state["store"].job("survival",run["job"]))

    async def test_runtime_revalidates_removed_command_and_offline_game(self):
        row=self.service.save_task(task("command"));self.bot.servers["survival"]["commands"].clear()
        result=await self.service.run_task(row["id"],True,row["revision"]);self.assertEqual(result["status"],"failed")
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0],0)
        row=self.service.save_task(task("game_message"));self.bot.snapshots.clear()
        result=await self.service.run_task(row["id"],True,row["revision"]);self.assertEqual(result["status"],"failed")
        self.assertIn("离线",result["detail"])

    async def test_qq_announcement_online_and_disabled_manual_run(self):
        row=self.service.save_task(task("qq_message"))
        with patch('starbridge.onebot.OneBot.connected',new_callable=PropertyMock,return_value=True):
            result=await self.service.run_task(row["id"],True,row["revision"])
        self.assertEqual(result["status"],"success");self.state["onebot"].send_group.assert_awaited_once_with("101","请文明游戏")
        self.assertFalse(self.service.task(row["id"])["definition"]["enabled"])

    async def test_due_task_claim_backlog_skip_and_maintenance(self):
        row=self.service.save_task(task("game_message",True))
        with self.db:self.db.execute("UPDATE scheduled_tasks SET next_run=? WHERE id=?",(time.time()-300,row["id"]))
        await self.service.tick_due();self.assertEqual(self.service.task(row["id"])["status"],"skipped")
        self.assertEqual(len(self.service.tasks()["runs"]),0)
        with self.db:self.db.execute("UPDATE scheduled_tasks SET next_run=? WHERE id=?",(time.time()-1,row["id"]))
        self.state["maintenance"]=True;await self.service.tick_due();self.assertEqual(len(self.service.tasks()["runs"]),0)
        self.state["maintenance"]=False;await self.service.tick_due();await self.service.tick_due()
        self.assertEqual(len(self.service.tasks()["runs"]),1)
        self.assertGreater(self.service.task(row["id"])["next_run"],time.time())

    async def test_backup_task_exports_archive_without_download(self):
        row=self.service.save_task(task("backup"));run=await self.service.run_task(row["id"],True,row["revision"])
        self.assertEqual(run["status"],"success");self.assertEqual(len(list((self.base/"data/backups").glob("*.zip"))),1)
        self.state["onebot"].send_group.assert_not_awaited()
        row=self.service.save_task(task("backup",True),row["id"],row["revision"])
        with self.db:self.db.execute("UPDATE scheduled_tasks SET next_run=? WHERE id=?",(time.time()-1,row["id"]))
        await self.service.tick_due()
        entries=self.state["backups"].listing()["backups"]
        self.assertEqual(len(entries),2)
        scheduled=next(item for item in entries if item["reason"]=="scheduled")
        payload=(self.base/"data/backups"/(scheduled["id"]+".zip")).read_bytes()
        response=await self.client.post("/api/backups/preview",headers=self.headers|{"Content-Type":"application/zip"},data=payload)
        self.assertEqual(response.status,200,await response.text())

    async def test_task_queue_expiration_is_not_success(self):
        row=self.service.save_task(task());run=await self.service.run_task(row["id"],True,row["revision"])
        with self.db:self.db.execute("UPDATE schedule_runs SET started=? WHERE id=?",(time.time()-100,run["id"]))
        self.service.expire();self.assertEqual(self.service.tasks()["runs"][0]["status"],"unconfirmed")

    async def test_group_application_sender_scope_and_duplicate_protection(self):
        self.open_applications()
        for mid,text_value in ((1,"/白名单 NewPlayer 我想加入"),(2,"/白名单状态")):
            await self.bot.handle_event({"post_type":"message","message_type":"group","group_id":101,"user_id":202,"self_id":100,"message_id":mid,"message":text_value})
        rows=self.service.applications()["applications"];self.assertEqual(len(rows),1);self.assertEqual(rows[0]["qq"],"202");self.assertEqual(rows[0]["status"],"pending")
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0],0)
        with self.assertRaises(OperationError):self.service.apply("survival","newplayer","203","101")
        with self.assertRaises(OperationError):self.service.apply("survival","Other","202","101")
        await self.bot.handle_event({"post_type":"message","message_type":"group","group_id":999,"user_id":203,"self_id":100,"message_id":3,"message":"/白名单 Alex"})
        self.assertEqual(len(self.service.applications()["applications"]),1)

    async def test_registration_and_binding_requirements(self):
        self.open_applications(require_registered=True)
        with self.assertRaises(OperationError):self.service.apply("survival","Steve","202","101")
        with self.db:self.db.execute("INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),"Steve","steve","202@qq.com","202",time.time()))
        self.open_applications(require_bound=True)
        with self.assertRaises(OperationError):self.service.apply("survival","Steve","202","101")
        code=self.state["store"].issue_code("survival",str(uuid.uuid4()),"Steve");self.state["store"].bind("survival","202",code)
        self.assertEqual(self.service.apply("survival","Steve","202","101")["status"],"pending")

    async def test_closed_applications_rejection_cooldown_and_injection(self):
        with self.assertRaises(OperationError):self.service.apply("survival","Steve","202","101")
        self.open_applications()
        for name in ("Steve;op x","../x","Steve\nstop"):
            with self.assertRaises(OperationError):self.service.apply("survival",name,"202","101")
        app=self.service.apply("survival","Steve","202","101")
        row=self.service.review(app["id"],"reject",app["revision"],"不符合要求");self.assertEqual(row["status"],"rejected")
        with self.assertRaises(OperationError):self.service.apply("survival","Alex","202","101")
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0],0)

    async def test_whitelist_approval_ack_and_stale_repeated_review(self):
        self.open_applications();app=self.service.apply("survival","NewPlayer","202","101")
        row=self.service.review(app["id"],"approve",app["revision"],"欢迎加入")
        self.assertEqual(row["status"],"submitted");self.assertEqual(row["review_note"],"欢迎加入")
        with self.assertRaises(OperationError):self.service.review(app["id"],"approve",app["revision"])
        job=self.state["store"].job("survival",row["job"]);self.assertEqual(job["kind"],"whitelist_application")
        response=await self.client.post("/bridge/survival/tick",headers={"Authorization":"Bearer "+self.cfg["servers"][0]["token"]},json={"players":[],"results":[{"id":row["job"],"ok":True,"detail":"已加入白名单"}]})
        self.assertEqual(response.status,200);await self.state["game_events"].join()
        self.assertEqual(self.service.application(app["id"])["status"],"success")
        self.state["onebot"].send_group.assert_awaited_once()

    async def test_offline_approval_and_capability_upgrade_retry(self):
        app=self.service.apply("survival","Steve","202",admin=True);self.bot.snapshots.clear()
        row=self.service.review(app["id"],"approve",app["revision"]);self.assertEqual(row["status"],"approved")
        self.bot.snapshots["survival"]={"last_seen":time.time(),"capabilities":["player_management"]}
        row=self.service.review(row["id"],"retry",row["revision"]);self.assertEqual(row["status"],"approved");self.assertIn("0.5.0",row["review"])
        self.bot.snapshots["survival"]["capabilities"]=["whitelist_application"]
        identity=str(uuid.uuid4());row=self.service.review(row["id"],"retry",row["revision"],identity=identity)
        self.assertEqual(row["status"],"submitted");self.assertEqual(self.state["store"].job("survival",row["job"])["uuid"],identity)

    async def test_whitelist_failure_expiration_and_retry_revision(self):
        app=self.service.apply("survival","Steve","202",admin=True);row=self.service.review(app["id"],"approve",app["revision"])
        with self.db:self.db.execute("UPDATE whitelist_applications SET updated=? WHERE id=?",(time.time()-100,row["id"]))
        self.service.expire();expired=self.service.application(row["id"]);self.assertEqual(expired["status"],"unconfirmed")
        with self.assertRaises(OperationError):self.service.review(row["id"],"retry",row["revision"])
        retried=self.service.review(row["id"],"retry",expired["revision"])
        payload=self.state["store"].job("survival",row["job"])
        self.service.complete("survival",row["job"],payload,{"ok":True,"detail":"旧结果"})
        self.assertEqual(self.service.application(row["id"])["job"],retried["job"])
        self.assertEqual(self.service.application(row["id"])["status"],"submitted")

    async def test_plugin_permissions_restrict_context_and_persist(self):
        manager=self.state["plugins"];await manager.install(example(),manager.revision)
        await manager.update("test_helper",{"revision":manager.revision,"enabled":True,"permissions":{"read_bindings":False,"read_server":False,"user_mode":"admins","deny_users":["202"]}})
        await manager.group_message(self.bot.servers["survival"],"101","202","问候 hi")
        self.state["onebot"].send_group.assert_not_awaited()
        await manager.group_message(self.bot.servers["survival"],"101","201","问候 hi")
        self.state["onebot"].send_group.assert_awaited_once()
        policy=manager.entries["test_helper"]["permissions"]
        await manager.reload("test_helper",manager.revision);self.assertEqual(manager.entries["test_helper"]["permissions"],policy)
        entry=manager.entries["test_helper"]
        reply=manager.template(entry,{"reply":"{players} {online_count} {online}"},self.bot.servers["survival"])
        self.assertEqual(reply,"未授权 未授权 未授权")

    async def test_keyword_and_game_event_scope_permissions(self):
        manager=self.state["plugins"]
        await manager.update("keyword_replies",{"revision":manager.revision,"enabled":True,"permissions":{"groups":["999"]}})
        self.assertTrue(await manager.group_message(self.bot.servers["survival"],"101","202","官网"))
        self.state["onebot"].send_group.assert_not_awaited()
        await manager.install(example(),manager.revision)
        await manager.update("test_helper",{"revision":manager.revision,"enabled":True,"settings":{"welcome":True},"permissions":{"game_events":False}})
        await manager.game_event(self.bot.servers["survival"],{"kind":"join","player":"Steve"})
        self.state["onebot"].send_group.assert_not_awaited()
        await manager.update("test_helper",{"revision":manager.revision,"permissions":{"game_events":True,"groups":["101"]}})
        await manager.game_event(self.bot.servers["survival"],{"kind":"join","player":"Alex"})
        self.state["onebot"].send_group.assert_awaited_once()

    async def test_restore_preserves_permissions_and_pauses_automation(self):
        task_row=self.service.save_task(task("backup",True));app=self.service.apply("survival","Steve","202",admin=True)
        app=self.service.review(app["id"],"approve",app["revision"])
        manager=self.state["plugins"];await manager.update("keyword_replies",{"revision":manager.revision,"permissions":{"user_mode":"admins"}})
        entry=await self.state["backups"].create();payload=(self.base/"data/backups"/(entry["id"]+".zip")).read_bytes()
        response=await self.client.post("/api/backups/preview",headers=self.headers|{"Content-Type":"application/zip"},data=payload);self.assertEqual(response.status,200,await response.text())
        preview=await response.json();await self.state["backups"].restore(preview["preview_id"])
        await self.client.close();self.client=None
        self.assertTrue(apply_pending_restore(self.path))
        rebuilt=create_app(load(self.path),config_path=self.path,restart_event=asyncio.Event());client=TestClient(TestServer(rebuilt));await client.start_server()
        try:
            state=rebuilt[STATE];self.assertFalse(state["operations"].task(task_row["id"])["definition"]["enabled"])
            self.assertEqual(state["operations"].application(app["id"])["status"],"cancelled")
            self.assertEqual(state["plugins"].entries["keyword_replies"]["permissions"]["user_mode"],"admins")
            finish_restore(self.path)
        finally:await client.close()

    async def test_previous_version_backup_schema_is_accepted(self):
        entry=await self.state["backups"].create();source=self.base/"data/backups"/(entry["id"]+".zip")
        import sqlite3
        with zipfile.ZipFile(source) as archive:parts={name:archive.read(name) for name in archive.namelist()}
        db_path=self.base/"old.sqlite";db_path.write_bytes(parts["database.sqlite3"])
        db=sqlite3.connect(db_path)
        with db:
            for table in ("operations_settings","scheduled_tasks","schedule_runs","whitelist_applications"):db.execute("DROP TABLE "+table)
        db.close();parts["database.sqlite3"]=db_path.read_bytes()
        manifest=json.loads(parts["manifest.json"]);manifest["app_version"]="0.4.0";manifest["files"]["database.sqlite3"]={"size":len(parts["database.sqlite3"]),"sha256":hashlib.sha256(parts["database.sqlite3"]).hexdigest()};parts["manifest.json"]=json.dumps(manifest).encode()
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,value in parts.items():archive.writestr(name,value)
        response=await self.client.post("/api/backups/preview",headers=self.headers|{"Content-Type":"application/zip"},data=output.getvalue())
        self.assertEqual(response.status,200,await response.text())

    async def test_restore_preview_detects_task_or_whitelist_settings_change(self):
        entry=await self.state["backups"].create();payload=(self.base/"data/backups"/(entry["id"]+".zip")).read_bytes()
        async def preview():
            response=await self.client.post("/api/backups/preview",headers=self.headers|{"Content-Type":"application/zip"},data=payload)
            self.assertEqual(response.status,200,await response.text());return await response.json()
        for change in (lambda:self.service.save_task(task("backup")),lambda:self.open_applications()):
            current=await preview();change()
            response=await self.client.post("/api/backups/restore",headers=self.headers,json={"preview_id":current["preview_id"]})
            self.assertEqual(response.status,409,await response.text())
            self.assertFalse(self.state.get("maintenance",False))
