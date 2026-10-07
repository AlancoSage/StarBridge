import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import uuid

from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import STATE, create_app
from starbridge.backups import check_database
from starbridge.config import load
from starbridge.registration import RegistrationError
from starbridge.settings import ConfigFile, serialize
from test_settings import full_config
from test_players import record, STEVE


class CommunityDeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.path = self.base / 'config.toml'; self.cfg = full_config()
        self.cfg['servers'].append({'id':'creative','name':'创造服','token':'creative-'+ 'c'*32,'groups':[], 'commands':{}})
        self.path.write_text(serialize(self.cfg), encoding='utf-8')
        self.client=TestClient(TestServer(create_app(load(self.path),config_path=self.path,restart_event=asyncio.Event())))
        await self.client.start_server(); self.state=self.client.app[STATE]; self.db=self.state['store'].db
        self.owner={'Authorization':'Bearer '+self.cfg['app']['admin_token']}
        self.state['updates'].root=self.base;self.state['updates'].directory=self.base/'.runtime/updates'
        # These tests exercise enabled services; deployment defaults are tested separately.
        with self.db:
            self.db.execute("INSERT INTO operations_settings VALUES('tickets',?,0)", (json.dumps({'enabled':True,'max_open':5}),))
            self.db.execute("INSERT INTO operations_settings VALUES('sanctions',?,0)", (json.dumps({'enabled':True}),))

    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()

    def account(self,name='Steve',qq='123456789'):
        aid=uuid.uuid4().hex;token=uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)',(aid,name,name.lower(),qq+'@qq.com',qq,time.time()))
            self.db.execute('INSERT INTO registration_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),aid,time.time()+3600))
        return aid,{'Authorization':'Bearer '+token}

    async def tick(self,sid='survival',players=None,results=None):
        server=next(s for s in self.cfg['servers'] if s['id']==sid)
        response=await self.client.post('/bridge/'+sid+'/tick',headers={'Authorization':'Bearer '+server['token']},json={
            'players':['Steve'],'player_records':players if players is not None else [record()],
            'capabilities':['player_management','managed_sanctions'],'java_version':'1.8.0','server_software':'Spigot',
            'version':'1.8.8','events':[],'results':results or []})
        self.assertEqual(response.status,200,await response.text());return await response.json()

    async def test_optional_features_default_off_and_save_independently(self):
        with self.db:self.db.execute("DELETE FROM operations_settings WHERE key IN ('tickets','sanctions')")
        settings=await(await self.client.get('/api/community-features',headers=self.owner)).json()
        self.assertEqual({k:v['settings']['enabled'] for k,v in settings.items()}, {'whitelist':False,'tickets':False,'sanctions':False})
        aid,headers=self.account()
        self.assertEqual((await self.client.post('/api/v1/me/tickets',headers=headers,json={'title':'问题','body':'详情'})).status,403)
        self.assertEqual((await self.client.post('/api/sanctions',headers=self.owner,json={})).status,403)
        for key in ('whitelist','tickets','sanctions'):
            response=await self.client.put('/api/community-features',headers=self.owner,json={'feature':key,'enabled':True,'revision':0})
            self.assertEqual(response.status,200,await response.text())
            self.assertEqual((await response.json())[key]['revision'],1)
        stale=await self.client.put('/api/community-features',headers=self.owner,json={'feature':'tickets','enabled':False,'revision':0})
        self.assertEqual(stale.status,409)
        invalid=await self.client.put('/api/community-features',headers=self.owner,json={'feature':'tickets','enabled':'false','revision':1})
        self.assertEqual(invalid.status,400)
        status=await(await self.client.get('/api/status',headers=self.owner)).json()
        self.assertTrue(all(status['community_features'].values()))
        self.assertEqual(self.state['tickets'].config()['settings']['max_open'],5)
        check_database(Path(self.state['config']['app']['database']))

    async def test_disabled_sanctions_pause_jobs_but_allow_expiry_cleanup(self):
        await self.tick();service=self.state['sanctions']
        rule=service.create({'uuid':STEVE,'servers':['survival'],'reason':'测试','minutes':1},'服主')
        job=rule['targets'][0]['job']
        service.save({'settings':{'enabled':False},'revision':0})
        self.assertIsNone(self.state['store'].job('survival',job))
        self.assertEqual((await self.tick())['jobs'],[])
        with self.assertRaises(RegistrationError):service.create({'uuid':STEVE,'servers':['survival'],'reason':'新处罚'},'服主')
        # A previously leased command may have executed; expiry still issues guarded cleanup.
        await self.tick(players=[record()|{'banned':True}])
        with self.db:self.db.execute('UPDATE sanctions SET expires=? WHERE id=?',(time.time()-1,rule['id']))
        service.reconcile();expired=service.detail(rule['id'])
        self.assertEqual(expired['status'],'expired')
        unban=self.state['store'].job('survival',expired['targets'][0]['job'])
        self.assertEqual(unban['action'],'unban');self.assertIn('[SB:'+rule['id']+']',unban['expected_ban_reason'])
        service.save({'settings':{'enabled':True},'revision':1})
        self.assertEqual(service.detail(rule['id'])['status'],'expired')

    async def test_feature_switch_requires_owner_and_keeps_history(self):
        user=await self.state['admin_accounts'].save({'username':'Reviewer','password':'Review-password-2026','permissions':['status.read','tickets.manage']})
        login=await self.state['admin_accounts'].login({'username':'Reviewer','password':'Review-password-2026'},'127.0.0.1')
        reviewer={'Authorization':'Bearer '+login['access_token']}
        self.assertEqual((await self.client.get('/api/community-features',headers=reviewer)).status,200)
        self.assertEqual((await self.client.put('/api/community-features',headers=reviewer,json={'feature':'tickets','enabled':False,'revision':0})).status,403)
        aid,headers=self.account();ticket=self.state['tickets'].create({'id':aid,'player':'Steve','qq':'123456789'},{'title':'问题','body':'详情'})
        response=await self.client.put('/api/community-features',headers=self.owner,json={'feature':'tickets','enabled':False,'revision':0})
        self.assertEqual(response.status,200)
        self.assertEqual((await self.client.get('/api/v1/me/tickets/'+ticket['id'],headers=headers)).status,200)
        self.assertEqual(self.state['tickets'].listing()['total'],1)
        with self.db:self.db.execute("DELETE FROM operations_settings WHERE key='tickets'")
        self.assertTrue(self.state['tickets'].config()['settings']['enabled'])

    async def test_tickets_are_private_and_internal_notes_are_hidden(self):
        aid,headers=self.account();other,other_headers=self.account('Alex','987654321')
        response=await self.client.post('/api/v1/me/tickets',headers=headers,json={'title':'无法进入服务器','body':'连接时提示认证失败'})
        self.assertEqual(response.status,201,await response.text());ticket=await response.json()
        self.assertNotIn('account_id',ticket)
        self.assertEqual((await self.client.get('/api/v1/me/tickets/'+ticket['id'],headers=other_headers)).status,404)
        for data in ({'body':'伪造','revision':1,'status':'closed'},{'body':'私密','revision':1,'internal':True}):
            self.assertEqual((await self.client.post('/api/v1/me/tickets/'+ticket['id']+'/reply',headers=headers,json=data)).status,403)
        response=await self.client.post('/api/tickets/'+ticket['id']+'/reply',headers=self.owner,json={'body':'内部调查结果','internal':True,'status':'processing','revision':1})
        self.assertEqual(response.status,200,await response.text())
        public=await(await self.client.get('/api/v1/me/tickets/'+ticket['id'],headers=headers)).json()
        self.assertEqual(len(public['messages']),1);self.assertNotIn('内部调查',json.dumps(public,ensure_ascii=False))
        self.assertEqual((await self.client.post('/api/v1/me/tickets/'+ticket['id']+'/reply',headers=headers,json={'body':'补充','revision':1})).status,409)
        await self.client.post('/api/tickets/'+ticket['id']+'/reply',headers=self.owner,json={'body':'已处理','revision':2,'status':'resolved'})
        self.assertEqual((await self.client.post('/api/v1/me/tickets/'+ticket['id']+'/reply',headers=headers,json={'body':'再回复','revision':3})).status,403)
        own=await(await self.client.get('/api/v1/me/tickets',headers=other_headers)).json();self.assertEqual(own['total'],0)

    async def test_ticket_quota_settings_and_appeal_ownership(self):
        aid,headers=self.account();self.state['tickets'].save({'settings':{'enabled':True,'max_open':1},'revision':0})
        for status in (201,409):
            response=await self.client.post('/api/v1/me/tickets',headers=headers,json={'title':'问题','body':'详情'});self.assertEqual(response.status,status)
        self.state['tickets'].save({'settings':{'enabled':False,'max_open':1},'revision':1})
        self.assertEqual((await self.client.post('/api/v1/me/tickets',headers=headers,json={'title':'问题','body':'详情'})).status,403)
        self.state['tickets'].save({'settings':{'enabled':True,'max_open':5},'revision':2})
        await self.tick();r=self.state['sanctions'].create({'uuid':STEVE,'reason':'测试','servers':['survival']},'服主')
        data={'title':'处罚申诉','body':'请复核','kind':'appeal','penalty_id':r['id']}
        self.assertEqual((await self.client.post('/api/v1/me/tickets',headers=headers,json=data)).status,404)
        with self.db:self.db.execute('INSERT INTO account_game_links VALUES(?,?,?)',(aid,'survival',STEVE))
        self.assertEqual((await self.client.post('/api/v1/me/tickets',headers=headers,json=data)).status,201)
        services=await(await self.client.get('/api/v1/me/services',headers=headers)).json()
        self.assertEqual(services['shared_penalties'][0]['id'],r['id']);self.assertNotIn('[SB:',json.dumps(services))

    async def test_cross_server_ban_ack_and_guarded_expiry(self):
        await self.tick();await self.tick('creative',players=[record(identity=str(uuid.uuid4()))])
        service=self.state['sanctions'];rule=service.create({'uuid':STEVE,'servers':['survival','creative'],'reason':'违反规定','minutes':1},'服主')
        targets={t['server']:t for t in rule['targets']};self.assertEqual(targets['survival']['status'],'pending');self.assertEqual(targets['creative']['status'],'waiting')
        jid=targets['survival']['job'];job=self.state['store'].job('survival',jid)
        self.assertEqual(job['kick_reason'],'违反规定');self.assertIn('[SB:'+rule['id']+']',job['reason'])
        self.assertEqual((await self.tick(players=[record()|{'banned':True}],results=[{'id':jid,'ok':True,'detail':'完成'}]))['jobs'],[])
        self.assertEqual(service.detail(rule['id'])['targets'][1]['status'],'success')
        with self.db:self.db.execute('UPDATE sanctions SET expires=? WHERE id=?',(time.time()-1,rule['id']))
        service.reconcile();rule=service.detail(rule['id']);self.assertEqual(rule['status'],'expired')
        target=next(t for t in rule['targets'] if t['server']=='survival');unban=self.state['store'].job('survival',target['job'])
        self.assertEqual(unban['action'],'unban');self.assertEqual(unban['expected_ban_reason'],job['reason'])
        await self.tick(results=[{'id':target['job'],'ok':True,'detail':'解除'}]);self.assertEqual(service.detail(rule['id'])['targets'][1]['status'],'success')

    async def test_independent_bans_and_one_shot_kicks_are_preserved(self):
        await self.tick(players=[record()|{'banned':True}]);service=self.state['sanctions']
        rule=service.create({'uuid':STEVE,'servers':['survival'],'reason':'社区规则'},'服主')
        self.assertEqual(rule['targets'][0]['status'],'superseded')
        revoked=service.release(rule['id'],rule['revision']);self.assertEqual(revoked['targets'][0]['status'],'superseded');self.assertEqual(self.state['store'].poll('survival'),[])
        kick=service.create({'uuid':STEVE,'action':'kick','servers':['creative'],'reason':'临时踢出'},'服主')
        with self.db:self.db.execute('UPDATE sanctions SET expires=? WHERE id=?',(time.time()-1,kick['id']))
        service.reconcile();self.assertEqual(service.detail(kick['id'])['status'],'completed')
        self.assertEqual((await self.tick('creative'))['jobs'],[])

    async def test_new_independent_panel_ban_is_not_unbanned(self):
        await self.tick();service=self.state['sanctions'];rule=service.create({'uuid':STEVE,'servers':['survival'],'reason':'社区规则'},'服主')
        target=rule['targets'][0];await self.tick(players=[record()|{'banned':True}],results=[{'id':target['job'],'ok':True,'detail':'完成'}])
        action=uuid.uuid4().hex;self.state['store'].create_player_action(action,'survival',STEVE,'Steve','ban','单服处罚')
        self.state['store'].complete_player_action('survival',action,True,'完成');self.state['store'].ack('survival',[action])
        revoked=service.release(rule['id'],rule['revision']);self.assertEqual(revoked['targets'][0]['status'],'superseded')

    async def test_uncertain_ban_never_overwrites_a_native_ban_on_retry(self):
        await self.tick();service=self.state['sanctions'];rule=service.create({'uuid':STEVE,'servers':['survival'],'reason':'社区规则'},'服主')
        target=rule['targets'][0]
        await self.tick(players=[record()|{'banned':True}],results=[{'id':target['job'],'ok':False,'detail':'未确认'}])
        with self.db:self.db.execute('UPDATE sanction_targets SET next_try=0,attempts=0 WHERE sanction=?',(rule['id'],))
        service.reconcile()
        self.assertEqual(service.detail(rule['id'])['targets'][0]['status'],'waiting');self.assertEqual(self.state['store'].poll('survival'),[])
        revoked=service.release(rule['id'],rule['revision']);job=self.state['store'].job('survival',revoked['targets'][0]['job'])
        self.assertIn('[SB:'+rule['id']+']',job['expected_ban_reason'])

    async def test_maintenance_blocks_background_and_list_reconciliation(self):
        await self.tick();self.state['maintenance']=True
        try:
            rule=self.state['sanctions'].create({'uuid':STEVE,'servers':['survival'],'reason':'测试维护保护'},'服主')
            self.state['sanctions'].listing();self.assertEqual(rule['targets'][0]['status'],'waiting');self.assertEqual(self.state['store'].poll('survival'),[])
        finally:self.state['maintenance']=False

    async def test_export_redaction_import_preservation_and_revision_fence(self):
        exported=await(await self.client.get('/api/deployment/export',headers=self.owner)).json()
        raw=json.dumps(exported)
        for secret in [self.cfg['app']['admin_token'],self.cfg['onebot']['token'],*[s['token'] for s in self.cfg['servers']]]:self.assertNotIn(secret,raw)
        exported['config']['servers'][0]['name']='导入服务器';exported['config']['app']['port']=12345
        response=await self.client.post('/api/deployment/preview',headers=self.owner,json={'content':json.dumps(exported)})
        self.assertEqual(response.status,200,await response.text());preview=await response.json()
        response=await self.client.post('/api/deployment/apply',headers=self.owner,json={'preview_id':preview['preview_id']});self.assertEqual(response.status,200,await response.text())
        cfg,_=ConfigFile(self.path).read();self.assertEqual(cfg['app'],self.cfg['app']);self.assertEqual(cfg['servers'][0]['token'],self.cfg['servers'][0]['token']);self.assertEqual(cfg['servers'][0]['name'],'导入服务器')
        p=self.state['deployment'].preview({'template':'qq_login'});file=ConfigFile(self.path);cfg,rev=file.read();cfg['servers'][0]['name']='后来修改';file.save(cfg,rev)
        self.assertEqual((await self.client.post('/api/deployment/apply',headers=self.owner,json={'preview_id':p['preview_id']})).status,409)

    async def test_templates_apply_auth_policy_and_settings_backup_validates(self):
        preview=self.state['deployment'].preview({'template':'qq_login'})
        response=await self.client.post('/api/deployment/apply',headers=self.owner,json={'preview_id':preview['preview_id']});self.assertEqual(response.status,200,await response.text())
        self.assertFalse(self.state['authentication'].settings['password_login']);self.assertTrue(self.state['authentication'].settings['qq_login'])
        self.state['tickets'].save({'settings':{'enabled':True,'max_open':2},'revision':0})
        self.state['updates'].save({'settings':{'feed_url':'https://example.com/update.json'},'revision':0})
        self.assertEqual(check_database(Path(self.state['config']['app']['database']))['players'],0)

    async def test_github_update_token_is_write_only_preserved_and_clearable(self):
        token='github_pat_'+'x'*30
        response=await self.client.put('/api/updates',headers=self.owner,json={'settings':{'source':'github','github_repository':'AlancoSage/StarBridge','github_token':token},'revision':0})
        self.assertEqual(response.status,200,await response.text());data=await response.json()
        self.assertTrue(data['github_token_configured']);self.assertEqual(data['settings']['github_token'],'');self.assertNotIn(token,json.dumps(data))
        response=await self.client.put('/api/updates',headers=self.owner,json={'settings':{'source':'github','github_token':''},'revision':1})
        self.assertEqual(response.status,200,await response.text());self.assertEqual(self.state['updates'].config()['settings']['github_token'],token)
        check_database(Path(self.state['config']['app']['database']))
        response=await self.client.put('/api/updates',headers=self.owner,json={'settings':{'source':'github'},'clear_github_token':True,'revision':2})
        self.assertEqual(response.status,200);self.assertFalse((await response.json())['github_token_configured'])
        self.assertEqual((await self.client.put('/api/updates',headers=self.owner,json={'settings':{'github_token':token},'revision':0})).status,409)

    async def test_smtp_probe_only_authenticates_and_permissions_are_scoped(self):
        settings=self.state['registration'].settings;settings.update(smtp_host='mail.example.com',smtp_from='a@example.com',smtp_security='starttls',smtp_username='user',smtp_password='secret')
        smtp=MagicMock()
        with patch('starbridge.deployment.smtplib.SMTP',smtp):
            result=await self.state['deployment'].probe('smtp')
        self.assertEqual(result['status'],'ok');instance=smtp.return_value.__enter__.return_value
        instance.login.assert_called_once_with('user','secret');instance.sendmail.assert_not_called();instance.send_message.assert_not_called()
        response=await self.client.post('/api/admin-users',headers=self.owner,json={'username':'Support','password':'Strong-support-password','permissions':['status.read','tickets.manage','diagnostics.run']});self.assertEqual(response.status,200,await response.text())
        login=await(await self.client.post('/api/admin-auth/login',json={'username':'Support','password':'Strong-support-password'})).json();h={'Authorization':'Bearer '+login['access_token']}
        for endpoint,status in [('/api/tickets',200),('/api/diagnostics',200),('/api/sanctions',403),('/api/updates',403),('/api/deployment/export',403)]:
            self.assertEqual((await self.client.get(endpoint,headers=h)).status,status,endpoint)


if __name__=='__main__':unittest.main()
