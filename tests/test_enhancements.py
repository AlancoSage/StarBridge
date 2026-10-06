import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import uuid
from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import STATE, create_app
from starbridge.admin_accounts import PRESETS
from starbridge.registration import RegistrationError
from starbridge.runtime_features import DEFAULTS, RuntimeFeatures, validate_setting
from test_starbridge import config
from test_extensions import example


class EnhancementValidationTests(unittest.TestCase):
    def test_runtime_setting_bounds(self):
        for key,change in [('monitoring',{'groups':['x']}),('monitoring',{'groups':[{}]}),('monitoring',{'notify_groups':True}),
                           ('monitoring',{'startup_grace_seconds':True}),('statistics',{'retention_days':91}),
                           ('backup_policy',{'keep_count':0}),('backup_policy',{'protect_manual':1})]:
            with self.subTest(key=key,change=change),self.assertRaises(ValueError):validate_setting(key,DEFAULTS[key]|change)


class EnhancementApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.cfg=config(str(self.base/'test.db'))
        self.client=TestClient(TestServer(create_app(self.cfg)));await self.client.start_server()
        self.state=self.client.app[STATE];self.db=self.state['store'].db;self.owner={'Authorization':'Bearer '+self.cfg['app']['admin_token']}

    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()

    async def admin(self,scope=PRESETS['observer']):
        response=await self.client.post('/api/admin-users',headers=self.owner,json={'username':'Observer','password':'Secure-manager-2026','permissions':scope})
        self.assertEqual(response.status,200,await response.text());user=(await response.json())['users'][0]
        response=await self.client.post('/api/admin-auth/login',json={'username':'Observer','password':'Secure-manager-2026'})
        self.assertEqual(response.status,200,await response.text());token=(await response.json())['access_token']
        return user,{'Authorization':'Bearer '+token}

    def user(self):
        aid=uuid.uuid4().hex;uid=str(uuid.uuid4());token='user-'+uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)',(aid,'Steve','steve','123456789@qq.com','123456789',time.time()))
            self.db.execute('INSERT INTO registration_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),aid,time.time()+3600))
        return aid,uid,{'Authorization':'Bearer '+token}

    async def test_observer_can_read_stats_but_cannot_manage_or_receive_secrets(self):
        user,headers=await self.admin()
        identity=await(await self.client.get('/api/session',headers=headers)).json();self.assertFalse(identity['owner'])
        for method,path in [('get','/api/config'),('get','/api/admin-users'),('post','/api/restart'),('post','/api/backups'),
                            ('get','/api/player-profiles'),('put','/api/statistics'),('get','/api/registration/settings'),('get','/api/monitoring')]:
            with self.subTest(path=path):self.assertEqual((await getattr(self.client,method)(path,headers=headers)).status,403)
        self.assertEqual((await self.client.get('/api/statistics',headers=headers)).status,200)
        uid=str(uuid.uuid4());self.state['bot'].snapshots['survival']={'last_seen':time.time(),'players':['Steve'],'player_records':[{'name':'Steve','uuid':uid,'online':True,'ip':'8.8.8.8'}]}
        result=await(await self.client.get('/api/status',headers=headers)).json()
        self.assertEqual(result['players'],[]);self.assertEqual(result['logs'],[]);self.assertNotIn('8.8.8.8',json.dumps(result))
        self.assertEqual((await self.client.post('/bridge/survival/tick',headers=headers,json={})).status,401)

    async def test_revision_changes_logout_and_disable_revoke_sessions(self):
        user,headers=await self.admin()
        response=await self.client.put('/api/admin-users/'+user['id'],headers=self.owner,json={'revision':user['revision'],'enabled':False})
        self.assertEqual(response.status,200);self.assertEqual((await self.client.get('/api/status',headers=headers)).status,401)
        self.assertEqual((await self.client.put('/api/admin-users/'+user['id'],headers=self.owner,json={'revision':user['revision'],'enabled':True})).status,409)
        latest=(await response.json())['users'][0]
        await self.client.put('/api/admin-users/'+user['id'],headers=self.owner,json={'revision':latest['revision'],'enabled':True})
        response=await self.client.post('/api/admin-auth/login',json={'username':'Observer','password':'Secure-manager-2026'})
        new={'Authorization':'Bearer '+(await response.json())['access_token']}
        await self.client.post('/api/admin-auth/logout',headers=new)
        self.assertEqual((await self.client.get('/api/session',headers=new)).status,401)

    async def test_reviewer_has_review_permission_but_not_settings_or_backups(self):
        _,headers=await self.admin(PRESETS['reviewer'])
        self.assertEqual((await self.client.get('/api/whitelist',headers=headers)).status,200)
        self.assertEqual((await self.client.put('/api/whitelist/settings',headers=headers,json={})).status,403)
        self.assertEqual((await self.client.get('/api/backups/something',headers=headers)).status,403)
        row=self.state['operations'].apply('survival','Steve','123456789',admin=True)
        response=await self.client.post('/api/whitelist/'+row['id']+'/review',headers=headers,json={'revision':row['revision'],'action':'reject','note':'检查完成'})
        self.assertEqual(response.status,200)

    async def test_admin_login_and_permissions_fail_closed(self):
        self.assertEqual((await self.client.post('/api/admin-auth/login',json={'username':'Missing','password':'Secure-manager-2026'})).status,401)
        for scope in (['owner'],[{}],['stats.read']):
            response=await self.client.post('/api/admin-users',headers=self.owner,json={'username':'Invalid','password':'Secure-manager-2026','permissions':scope})
            self.assertEqual(response.status,400)
        reg=self.state['registration']
        for _ in range(8):reg.limit('admin-login-name:blocked',8,300)
        self.assertEqual((await self.client.post('/api/admin-auth/login',json={'username':'Blocked','password':'Secure-manager-2026'})).status,429)

    async def test_alerts_deduplicate_acknowledge_and_resolve_and_notifications_are_opt_in(self):
        runtime=self.state['runtime'];runtime.started=time.time()-40
        sender=AsyncMock();self.state['onebot'].send_group=sender
        await runtime.check();await runtime.check()
        self.assertEqual(runtime.monitoring()['open_count'],2);sender.assert_not_awaited()
        first=runtime.monitoring()['alerts'][0];runtime.acknowledge(first['id'])
        self.assertEqual(runtime.monitoring()['open_count'],2)
        self.state['bot'].snapshots['survival']={'last_seen':time.time(),'players':[],'max_players':20}
        await runtime.check();self.assertEqual(runtime.monitoring()['open_count'],1)
        runtime.mail_result(False);self.assertEqual(runtime.monitoring()['open_count'],2)
        restarted=RuntimeFeatures(self.state);await restarted.check()
        self.assertTrue(restarted.mail_failed)
        self.assertTrue(any(row['source']=='smtp' and row['status']=='open' for row in restarted.monitoring()['alerts']))
        runtime.mail_result(True);self.assertEqual(runtime.monitoring()['open_count'],1)
        policy=runtime.config('monitoring');runtime.save('monitoring',policy['settings']|{'notify_groups':True,'groups':['123456']},policy['revision'])
        self.state['onebot'].ws=type('Connected',(),{'closed':False,'close':AsyncMock()})()
        runtime.alert('test','模拟异常',True);await runtime.check();await runtime.check();sender.assert_awaited_once()
        self.state['onebot'].ws=None

    async def test_statistics_deduplicate_daily_players_and_leave_offline_gaps(self):
        runtime=self.state['runtime'];now=time.time();uid=str(uuid.uuid4())
        self.state['bot'].servers['creative']={'id':'creative','name':'创造服','groups':[]}
        for sid in ('survival','creative'):
            self.state['bot'].snapshots[sid]={'last_seen':now,'players':['Steve'],'max_players':20,'player_records':[{'name':'Steve','uuid':uid,'online':True}]}
        runtime.sample(now);runtime.sample(now)
        self.assertEqual(self.db.execute('SELECT count(*) FROM server_samples').fetchone()[0],2)
        result=runtime.statistics(days=1);self.assertEqual(result['series'][-1]['online_count'],2)
        self.assertEqual(result['daily'][-1]['active_players'],1)
        self.state['bot'].snapshots.clear();runtime.sample(now+360)
        self.assertIsNone(runtime.statistics(days=1)['series'][-1]['online_count'])
        event={'id':'once','kind':'join','player':'Steve','uuid':uid};runtime.event('survival',event);runtime.event('survival',event)
        self.assertEqual(len(runtime.statistics()['activity']),1)
        with self.db:self.db.execute('INSERT INTO server_samples VALUES(?,?,?,?,?)',('survival',int(now-100*86400),1,2,20))
        runtime.prune_statistics(now);self.assertEqual(self.db.execute('SELECT count(*) FROM server_samples WHERE bucket<?',(now-90*86400,)).fetchone()[0],0)

    async def test_self_service_uses_verified_identity_and_hides_other_users_and_staff_notes(self):
        aid,uid,headers=self.user();other=str(uuid.uuid4())
        self.state['catalog'].create({'uuid':uid,'name':'Steve','notes':'私密管理备注','ip':'8.8.8.8','region':''})
        code=self.state['store'].issue_code('survival',uid,'Steve')
        response=await self.client.post('/api/v1/me/bind',headers=headers,json={'server':'survival','code':code})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual((await self.client.post('/api/v1/me/bind',headers=headers,json={'server':'survival','code':code,'qq':'999'})).status,400)
        operation=self.state['operations'];policy=operation.config();operation.save_config(policy['settings']|{'enabled':True},policy['revision'])
        response=await self.client.post('/api/v1/me/whitelist',headers=headers,json={'server':'survival','reason':'想加入社区'})
        self.assertEqual(response.status,201)
        with self.db:
            self.db.execute("UPDATE whitelist_applications SET review_note='审核内部备注'")
            self.db.execute('INSERT INTO player_actions VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,'survival',uid,'Steve','ban','破坏建筑','success','私密执行输出',time.time(),time.time()))
            self.db.execute('INSERT INTO player_actions VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,'survival',other,'Other','ban','他人处罚','success','',time.time(),time.time()))
        data=await(await self.client.get('/api/v1/me/services',headers=headers)).json()
        self.assertEqual(len(data['penalties']),1);self.assertEqual(len(data['applications']),1)
        for private in ('私密','内部','8.8.8.8','他人处罚'):self.assertNotIn(private,json.dumps(data,ensure_ascii=False))
        self.assertEqual((await self.client.get('/api/v1/me/services',headers=self.owner)).status,401)
        self.state['authentication'].sessions[('survival',uid)]={'uuid':uid,'player':'Steve'}
        await self.client.post('/api/v1/me/unbind',headers=headers,json={'server':'survival'})
        self.assertNotIn(('survival',uid),self.state['authentication'].sessions)
        self.assertFalse((await(await self.client.get('/api/v1/me/services',headers=headers)).json())['bindings'])

    async def test_self_service_binding_cannot_take_another_account_uuid(self):
        aid,uid,headers=self.user()
        with self.db:self.db.execute('INSERT INTO account_game_links VALUES(?,?,?)',('another-account','survival',uid))
        code=self.state['store'].issue_code('survival',uid,'Steve')
        self.assertEqual((await self.client.post('/api/v1/me/bind',headers=headers,json={'server':'survival','code':code})).status,409)
        self.assertIsNone(self.state['store'].binding('survival','123456789'))

    async def test_plugin_upgrade_rollback_and_history_bound(self):
        manager=self.state['plugins'];plugin=example()
        await manager.install(plugin,manager.revision)
        await manager.update(plugin['id'],{'revision':manager.revision,'enabled':True})
        newer=deepcopy(plugin);newer.update(version='2.0.0',changelog='新增问候内容')
        await manager.upgrade(newer,manager.revision)
        self.assertFalse(manager.entries[plugin['id']]['enabled']);self.assertEqual(manager.entries[plugin['id']]['definition']['version'],'2.0.0')
        history=manager.versions(plugin['id'])['versions'];self.assertEqual(history[0]['version'],'1.0.0')
        await manager.upgrade(plugin['id'],manager.revision,history[0]['id'])
        self.assertEqual(manager.entries[plugin['id']]['definition']['version'],'1.0.0');self.assertFalse(manager.entries[plugin['id']]['enabled'])
        for version in range(3,10):
            newer['version']=str(version)+'.0.0';await manager.upgrade(newer,manager.revision)
        self.assertEqual(len(manager.versions(plugin['id'])['versions']),5)

    async def test_plugin_write_failure_restores_definition_and_state(self):
        manager=self.state['plugins'];plugin=example();await manager.install(plugin,manager.revision)
        old=manager.entries[plugin['id']]['path'].read_bytes();revision=manager.revision
        newer=deepcopy(plugin);newer['version']='2.0.0'
        from starbridge.extensions import atomic_json
        count=0
        def fail_once(*args,**kwargs):
            nonlocal count;count+=1
            if count==2:raise OSError('test write failure')
            return atomic_json(*args,**kwargs)
        with patch('starbridge.extensions.atomic_json',side_effect=fail_once),self.assertRaises(OSError):await manager.upgrade(newer,revision)
        self.assertEqual(manager.entries[plugin['id']]['path'].read_bytes(),old)
        self.assertEqual(manager.revision,revision);self.assertFalse(manager.versions(plugin['id'])['versions'])
