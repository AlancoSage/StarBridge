import asyncio
from copy import deepcopy
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import STATE, create_app
from starbridge.backups import (BackupError, apply_pending_restore, finish_restore, rollback_restore,
                                unpack_archive, MAX_ARCHIVE)
from starbridge.config import load
from starbridge.extensions import atomic_json
from starbridge.settings import ConfigFile, serialize
from test_settings import full_config


class BackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.path = self.base / "config.toml"; self.cfg = full_config()
        self.path.write_text(serialize(self.cfg), encoding="utf-8")
        self.client = TestClient(TestServer(create_app(load(self.path), config_path=self.path, restart_event=asyncio.Event())))
        await self.client.start_server(); self.state = self.client.app[STATE]
        self.admin = {"Authorization": "Bearer " + self.cfg["app"]["admin_token"]}
        self.player = str(uuid.uuid4()); self.account = str(uuid.uuid4())
        self.state["catalog"].create({"uuid": self.player, "name": "Steve", "ip": "127.0.0.1", "region": "手动归属地", "notes": "备份档案"})
        code = self.state["store"].issue_code("survival", self.player, "Steve")
        self.state["store"].bind("survival", "123456789", code)
        with self.state["store"].db:
            self.state["store"].db.execute("INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)", (self.account,"Steve","steve","123456789@qq.com","123456789",time.time()))
            self.state["store"].db.execute("INSERT INTO account_passwords VALUES(?,?,?)", (self.account,"test-hash-preserved",time.time()))
            self.state["store"].db.execute("INSERT INTO account_game_links VALUES(?,?,?)", (self.account,"survival",self.player))

    async def asyncTearDown(self):
        await self.client.close(); self.tmp.cleanup()

    async def backup(self):
        response = await self.client.post("/api/backups", headers=self.admin)
        self.assertEqual(response.status, 200, await response.text()); entry = await response.json()
        response = await self.client.get("/api/backups/" + entry["id"], headers=self.admin)
        self.assertEqual(response.status, 200); return entry, await response.read()

    async def preview(self, payload, status=200):
        response = await self.client.post("/api/backups/preview", headers={**self.admin,"Content-Type":"application/zip"}, data=payload)
        self.assertEqual(response.status, status, await response.text()); return await response.json()

    async def schedule(self, preview):
        response = await self.client.post("/api/backups/restore", headers=self.admin, json={"preview_id":preview["preview_id"]})
        self.assertEqual(response.status, 200, await response.text()); return await response.json()

    def mutate(self):
        with self.state["store"].db:
            self.state["store"].db.execute("DELETE FROM bindings")
            self.state["store"].db.execute("UPDATE player_profiles SET notes='恢复前的数据'")
        file = ConfigFile(self.path); cfg, revision = file.read(); cfg["servers"][0]["name"] = "恢复前服务器"
        file.save(cfg, revision)
        atomic_json(self.base / "data/plugin-state.json", {"keyword_replies":{"enabled":False,"settings":{"replies":{"新回复":"恢复前"}}}})

    async def test_website_settings_restore_and_preview_fence(self):
        service=self.state['website'];value=service.config_response()
        value['settings'].update(title='备份中的官网',public_players=False,website_url='https://www.example.com/community/',
                                 api_public_url='https://bridge.example.com/api/v1',connection_enabled=True,website_mode='provided')
        await service.save(value['settings'],value['revision'])
        _,payload=await self.backup()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(json.loads(archive.read('data/website-settings.json'))['title'],'备份中的官网')
        preview=await self.preview(payload)
        value=service.config_response();value['settings']['title']='恢复前官网'
        await service.save(value['settings'],value['revision'])
        response=await self.client.post('/api/backups/restore',headers=self.admin,json={'preview_id':preview['preview_id']})
        self.assertEqual(response.status,409)
        preview=await self.preview(payload);await self.schedule(preview)
        await self.client.close()
        self.assertTrue(await asyncio.to_thread(apply_pending_restore,self.path))
        from starbridge.website import Website
        restored=Website(self.base,{})
        self.assertEqual(restored.settings['title'],'备份中的官网');self.assertFalse(restored.settings['public_players'])
        self.assertEqual(restored.settings['website_url'],'https://www.example.com/community/')
        self.assertEqual(restored.settings['api_public_url'],'https://bridge.example.com/api/v1');self.assertTrue(restored.settings['connection_enabled'])
        self.assertEqual(restored.settings['website_mode'],'provided')

    async def test_retention_keeps_manual_safety_and_newest_scheduled_backup(self):
        manager=self.state['backups'];runtime=self.state['runtime']
        manual=await manager.create('manual');safety=await manager.create('before_restore')
        older=await manager.create('scheduled');second=await manager.create('scheduled');newest=await manager.create('scheduled')
        policy=runtime.config('backup_policy');runtime.save('backup_policy',policy['settings']|{'keep_count':1,'keep_days':365},policy['revision'])
        self.assertEqual((await manager.cleanup_policy())['removed'],0)
        result=await manager.cleanup_policy(manual=True);self.assertEqual(result['removed'],2)
        for entry in (manual,safety,newest):self.assertTrue(manager.path(entry['id']).exists())
        remaining=manager.listing();self.assertGreater(remaining['total_bytes'],0)
        self.assertNotIn(older['id'],[item['id'] for item in remaining['backups']]);self.assertNotIn(second['id'],[item['id'] for item in remaining['backups']])

    async def test_restore_preview_reports_difference_and_revokes_admin_sessions(self):
        from starbridge.admin_accounts import PRESETS
        await self.state['admin_accounts'].save({'username':'Observer','password':'Secure-manager-2026','permissions':PRESETS['observer']})
        token=await self.state['admin_accounts'].login({'username':'Observer','password':'Secure-manager-2026'},'test')
        _,payload=await self.backup()
        with self.state['store'].db:self.state['store'].db.execute('DELETE FROM bindings')
        preview=await self.preview(payload)
        self.assertEqual(preview['differences']['bindings'],{'current':0,'incoming':1,'delta':1})
        await self.schedule(preview);await self.client.close()
        self.assertTrue(await asyncio.to_thread(apply_pending_restore,self.path))
        with closing(sqlite3.connect(self.state['config']['app']['database'])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM admin_sessions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM admin_users').fetchone()[0],1)

    async def test_online_snapshot_preview_preserves_wal_data_and_hides_credentials(self):
        entry, payload = await self.backup()
        self.assertIn("StarBridge-", (await self.client.get("/api/backups/"+entry["id"],headers=self.admin)).headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertIn("database.sqlite3", archive.namelist())
            self.assertFalse(any(name.endswith(('-wal','-shm')) or 'backups/' in name for name in archive.namelist()))
        preview = await self.preview(payload)
        self.assertEqual(preview["counts"], {"players":1,"accounts":1,"bindings":1,"servers":1,"plugins":0})
        for secret in (self.cfg["app"]["admin_token"], self.cfg["onebot"]["token"], "test-hash-preserved"):
            self.assertNotIn(secret, json.dumps(preview))
        listing = await (await self.client.get("/api/backups", headers=self.admin)).json()
        self.assertEqual(listing["backups"][0]["id"], entry["id"])

    async def test_full_restore_preserves_local_app_and_revokes_transient_authority(self):
        with self.state["store"].db:
            self.state["store"].db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",("old-job","survival",'{}',time.time(),time.time()+999,0))
            self.state["store"].db.execute("INSERT INTO registration_sessions VALUES(?,?,?)",("old-session",self.account,time.time()+999))
        _, payload = await self.backup(); self.mutate()
        preview = await self.preview(payload); result = await self.schedule(preview)
        self.assertTrue(self.state["maintenance"])
        blocked = await self.client.post("/api/backups", headers=self.admin); self.assertEqual(blocked.status,503)
        await self.client.close()
        self.assertTrue(await asyncio.to_thread(apply_pending_restore, self.path))
        cfg, _ = ConfigFile(self.path).read(); self.assertEqual(cfg["app"], self.cfg["app"])
        self.assertEqual(cfg["servers"][0]["name"], self.cfg["servers"][0]["name"])
        db = sqlite3.connect(load(self.path)["app"]["database"])
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM bindings").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT notes FROM player_profiles").fetchone()[0],"备份档案")
            self.assertEqual(db.execute("SELECT password_hash FROM account_passwords").fetchone()[0],"test-hash-preserved")
            self.assertEqual(db.execute("SELECT count(*) FROM account_game_links").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM registration_sessions").fetchone()[0],0)
        finally: db.close()
        finish_restore(self.path)
        self.assertFalse((self.base / "data/restore-job.json").exists())
        status = json.loads((self.base / "data/last-restore.json").read_text(encoding="utf-8"))
        self.assertEqual(status["status"],"success"); self.assertEqual(status["safety_backup"],result["safety_backup"])
        safety = self.base / "data/backups" / (result["safety_backup"]+".zip")
        _, safety_counts = unpack_archive(safety,self.base / "safety-check")
        self.assertEqual(safety_counts["bindings"],0)

    async def test_interrupted_restore_rolls_back_files_and_database_on_next_boot(self):
        _, payload = await self.backup(); self.mutate()
        preview = await self.preview(payload); await self.schedule(preview); await self.client.close()
        self.assertTrue(apply_pending_restore(self.path))
        self.assertFalse(apply_pending_restore(self.path))  # Crash before startup was confirmed.
        cfg,_ = ConfigFile(self.path).read(); self.assertEqual(cfg["servers"][0]["name"],"恢复前服务器")
        with sqlite3.connect(load(self.path)["app"]["database"]) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM bindings").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT notes FROM player_profiles").fetchone()[0],"恢复前的数据")
        db.close()
        self.assertEqual(json.loads((self.base / "data/last-restore.json").read_text(encoding="utf-8"))["status"],"rolled_back")

    async def test_apply_write_failure_rolls_back_without_losing_pre_restore_data(self):
        _, payload = await self.backup(); self.mutate()
        preview = await self.preview(payload); await self.schedule(preview); await self.client.close()
        import starbridge.backups as module
        real_write = module.write_file; failed = False
        def fail_once(path, content):
            nonlocal failed
            if path == self.path and not failed:
                failed=True; raise OSError("simulated disk failure")
            real_write(path,content)
        with patch("starbridge.backups.write_file", side_effect=fail_once):
            self.assertFalse(apply_pending_restore(self.path))
        self.assertEqual(ConfigFile(self.path).read()[0]["servers"][0]["name"],"恢复前服务器")
        with sqlite3.connect(load(self.path)["app"]["database"]) as db:
            self.assertEqual(db.execute("SELECT notes FROM player_profiles").fetchone()[0],"恢复前的数据")
        db.close()

    async def test_stale_expired_or_changed_preview_does_not_restore(self):
        _, payload = await self.backup(); preview = await self.preview(payload); self.mutate()
        response=await self.client.post("/api/backups/restore",headers=self.admin,json={"preview_id":preview["preview_id"]});self.assertEqual(response.status,409)
        preview = await self.preview(payload)
        folder=self.base/'data/backups/staging'/preview['preview_id']; meta=json.loads((folder/'preview.json').read_text());meta['expires']=0;atomic_json(folder/'preview.json',meta)
        response=await self.client.post("/api/backups/restore",headers=self.admin,json={"preview_id":preview["preview_id"]});self.assertEqual(response.status,410)
        self.assertFalse((self.base/'data/restore-job.json').exists())
        self.assertFalse(self.state.get('maintenance'))

    async def test_unauthorized_upload_download_restore_and_delete_are_rejected(self):
        entry, payload = await self.backup()
        for method, url in (("get","/api/backups"),("post","/api/backups"),("post","/api/backups/preview"),("post","/api/backups/restore"),
                            ("get","/api/backups/"+entry['id']),("delete","/api/backups/"+entry['id'])):
            self.assertEqual((await getattr(self.client,method)(url)).status,401)
        response=await self.client.post('/api/backups/preview',headers=self.admin,data=payload);self.assertEqual(response.status,415)
        self.assertEqual((await self.client.get('/api/backups/..%5Cconfig.toml',headers=self.admin)).status,400)
        self.assertEqual((await self.client.delete('/api/backups/'+entry['id'],headers=self.admin)).status,200)
        self.assertEqual((await self.client.get('/api/backups/'+entry['id'],headers=self.admin)).status,404)

    async def test_bad_zip_paths_duplicates_corruption_and_schema_are_rejected(self):
        _, original = await self.backup()
        await self.preview(b"not zip",400)
        for unsafe in ("../outside.txt","/absolute.txt","plugins/../../outside.txt","plugins/code.py"):
            stream=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(original)) as source,zipfile.ZipFile(stream,'w') as target:
                for entry in source.infolist():target.writestr(entry,source.read(entry))
                target.writestr(unsafe,b"bad")
            await self.preview(stream.getvalue(),400)
        stream=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source,zipfile.ZipFile(stream,'w') as target:
            for entry in source.infolist():target.writestr(entry,source.read(entry)+(b"bad" if entry.filename=='config.toml' else b""))
        await self.preview(stream.getvalue(),400)
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            values={entry.filename:source.read(entry) for entry in source.infolist()}
        bad_db=self.base/'bad.db';bad_db.write_bytes(values['database.sqlite3'])
        with sqlite3.connect(bad_db) as db:db.execute('CREATE TRIGGER unwanted AFTER INSERT ON bindings BEGIN DELETE FROM bindings; END')
        db.close();values['database.sqlite3']=bad_db.read_bytes()
        manifest=json.loads(values['manifest.json']);manifest['files']['database.sqlite3']={'size':len(values['database.sqlite3']),'sha256':hashlib.sha256(values['database.sqlite3']).hexdigest()};values['manifest.json']=json.dumps(manifest).encode()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as target:
            for name,content in values.items():target.writestr(name,content)
        await self.preview(stream.getvalue(),400)
        self.assertFalse((self.base.parent/'outside.txt').exists())

    async def test_busy_and_disk_error_do_not_leave_operation_locked(self):
        manager=self.state['backups'];manager.busy=True
        self.assertEqual((await self.client.post('/api/backups',headers=self.admin)).status,409)
        manager.busy=False
        with patch('starbridge.backups.copy_database',side_effect=OSError('disk full')):
            self.assertEqual((await self.client.post('/api/backups',headers=self.admin)).status,400)
        self.assertFalse(manager.busy)
        await self.backup()

    async def test_restore_plugin_definitions_settings_and_other_machine_config(self):
        plugin=json.loads((Path(__file__).resolve().parent.parent/'examples/community_helper.json').read_text(encoding='utf-8'))
        (self.base/'plugins').mkdir(exist_ok=True)
        atomic_json(self.base/'plugins'/f"{plugin['id']}.json",plugin)
        atomic_json(self.base/'data/registration-settings.json',self.state['registration'].settings)
        atomic_json(self.base/'data/authentication-settings.json',self.state['authentication'].settings)
        _,payload=await self.backup()
        with zipfile.ZipFile(io.BytesIO(payload)) as source:values={entry.filename:source.read(entry) for entry in source.infolist()}
        remote=deepcopy(self.cfg);remote['app'].update(host='0.0.0.0',port=54321,database='../must-not-write.db',admin_token='A'*32)
        values['config.toml']=serialize(remote).encode();manifest=json.loads(values['manifest.json'])
        manifest['files']['config.toml']={'size':len(values['config.toml']),'sha256':hashlib.sha256(values['config.toml']).hexdigest()};values['manifest.json']=json.dumps(manifest).encode()
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as target:
            for name,content in values.items():target.writestr(name,content)
        extra=deepcopy(plugin);extra['id']='added_after_backup'
        atomic_json(self.base/'plugins/added_after_backup.json',extra)
        atomic_json(self.base/'data/authentication-settings.json',{**self.state['authentication'].settings,'login_seconds':300})
        preview=await self.preview(output.getvalue());self.assertEqual(preview['counts']['plugins'],1)
        await self.schedule(preview);await self.client.close();self.assertTrue(apply_pending_restore(self.path));finish_restore(self.path)
        self.assertEqual(ConfigFile(self.path).read()[0]['app'],self.cfg['app'])
        self.assertFalse((self.base.parent/'must-not-write.db').exists())
        self.assertTrue((self.base/'plugins'/f"{plugin['id']}.json").exists())
        self.assertFalse((self.base/'plugins/added_after_backup.json').exists())
        self.assertEqual(json.loads((self.base/'data/authentication-settings.json').read_text(encoding='utf-8'))['login_seconds'],120)

    async def test_large_streaming_upload_bypasses_small_json_limit_but_has_own_limit(self):
        import secrets
        with self.state['store'].db:
            self.state['store'].db.executemany('INSERT INTO audit(time,kind,detail) VALUES(?,?,?)',[(time.time(),'test',secrets.token_hex(500)) for _ in range(1000)])
        _,payload=await self.backup();self.assertGreater(len(payload),256*1024)
        await self.preview(payload)
        with patch('starbridge.backups.MAX_ARCHIVE',len(payload)-1):await self.preview(payload,413)

    async def test_restore_slot_prevents_double_confirmation_during_hashing(self):
        _,payload=await self.backup();preview=await self.preview(payload)
        manager=self.state['backups'];original=manager.work;entered=asyncio.Event();release=asyncio.Event()
        async def slow_work(function,*args):
            if function.__name__=='hash_file':entered.set();await release.wait()
            return await original(function,*args)
        with patch.object(manager,'work',side_effect=slow_work):
            first=asyncio.create_task(manager.restore(preview['preview_id']));await entered.wait()
            with self.assertRaises(BackupError):await manager.restore(preview['preview_id'])
            release.set();await first
        self.assertTrue(self.state['maintenance']);self.assertFalse(manager.busy)

    async def test_restored_service_startup_failure_rolls_back_and_serves_original_data(self):
        import aiohttp
        import starbridge.__main__ as main
        with socket.socket() as socket_handle:
            socket_handle.bind(('127.0.0.1',0));port=socket_handle.getsockname()[1]
        file=ConfigFile(self.path);cfg,revision=file.read();cfg['app']['port']=port;file.save(cfg,revision)
        self.state['config']['app']['port']=port
        _,payload=await self.backup();self.mutate();preview=await self.preview(payload);await self.schedule(preview);await self.client.close()
        original=main.create_app;calls=0
        def fail_first_start(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:raise OSError('Simulated restored service startup failure')
            return original(*args,**kwargs)
        task=None
        try:
            with patch.object(main,'create_app',side_effect=fail_first_start):
                task=asyncio.create_task(main.serve(self.path))
                async with aiohttp.ClientSession() as session:
                    deadline=time.monotonic()+10
                    while True:
                        try:
                            async with session.get(f'http://127.0.0.1:{port}/api/backups',headers=self.admin) as response:
                                result=await response.json();break
                        except aiohttp.ClientError:
                            if time.monotonic()>deadline:raise
                            await asyncio.sleep(.03)
                self.assertEqual(result['last_restore']['status'],'rolled_back')
                self.assertGreaterEqual(calls,2)
                self.assertEqual(ConfigFile(self.path).read()[0]['servers'][0]['name'],'恢复前服务器')
                with sqlite3.connect(load(self.path)['app']['database']) as db:
                    self.assertEqual(db.execute('SELECT notes FROM player_profiles').fetchone()[0],'恢复前的数据')
                db.close()
        finally:
            if task:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
