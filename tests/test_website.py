import asyncio
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

from aiohttp.test_utils import TestClient, TestServer
from starbridge.app import STATE, create_app
from starbridge.extensions import atomic_json
from starbridge.passwords import hash_password
from starbridge.registration import RegistrationError
from starbridge.website import DEFAULTS, Website, api_base, validate_settings
from test_starbridge import config

PASSWORD = 'Test-password-2026'
DIGEST = hash_password(PASSWORD)


class WebsiteValidationTests(unittest.TestCase):
    def test_reject_invalid_settings_and_api_urls(self):
        for change in ({'public_players':1},{'title':''},{'title':'x'*61},{'description':'x'*1001},
                       {'group_url':'javascript:alert(1)'},{'group_url':'https://u:p@example.com'},
                       {'group_url':'https://example.com:bad'},{'title':'a\x00b'},{'secret':'x'},
                       {'accent_color':'red'},{'secondary_color':'#12345'}, {'accent_color':'url(https://example.com)'},
                       {'theme_mode':'video'},{'grid_background':1}, {'connection_enabled':1},
                       {'website_mode':'custom'}, {'website_mode':'provided'}, {'website_mode':'unknown'},
                       {'website_mode':None}, {'website_url':'javascript:alert(1)'},
                       {'website_url':'https://u:p@example.com/'},{'website_url':'https://example.com/?token=x'},
                       {'website_url':'https://example.com/#home'},{'website_url':'https://example.com:bad/'},
                       {'website_url':None},{'api_public_url':False},{'api_public_url':'https://example.com/not-api'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_settings(DEFAULTS | change)
        for value in ('/api/other','https://u:p@example.com/api/v1','https://example.com/api/v1?token=secret',
                      'https://example.com/api/v1#x','javascript:alert(1)',None,'https://example.com:bad/api/v1'):
            with self.subTest(url=value), self.assertRaises(ValueError):api_base(value)
        self.assertEqual(api_base('https://example.com/api/v1/'),'https://example.com/api/v1')
        self.assertEqual(validate_settings({'title':'旧版官网'})['accent_color'],'#54745d')
        self.assertEqual(validate_settings(DEFAULTS|{'accent_color':'#ABCDEF'})['accent_color'],'#abcdef')

    def test_mode_is_authoritative_and_old_connection_settings_migrate(self):
        self.assertEqual(validate_settings({})['website_mode'],'none')
        old=validate_settings({'connection_enabled':True,'website_url':'https://legacy.example.com/'})
        self.assertEqual(old['website_mode'],'custom');self.assertTrue(old['connection_enabled'])
        disabled=validate_settings(old|{'website_mode':'none'})
        self.assertFalse(disabled['connection_enabled']);self.assertEqual(disabled['website_url'],old['website_url'])
        for mode in ('provided','custom'):
            result=validate_settings(disabled|{'website_mode':mode})
            self.assertTrue(result['connection_enabled']);self.assertEqual(result['website_mode'],mode)

    def test_invalid_disk_settings_fail_closed_and_can_be_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data/website-settings.json'; path.parent.mkdir();path.write_text('{broken')
            service = Website(Path(folder), {})
            self.assertTrue(service.error)
            self.assertFalse(service.settings['public_players']);self.assertFalse(service.settings['login_enabled'])


class WebsiteApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.cfg = config(str(self.base/'test.db'))
        self.client=TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server();self.state=self.client.app[STATE];self.db=self.state['store'].db
        self.service=self.state['website'];self.reg=self.state['registration']
        self.admin={'Authorization':'Bearer '+self.cfg['app']['admin_token']}
        self.uid=str(uuid.uuid4());self.other=str(uuid.uuid4());self.same_name=str(uuid.uuid4());self.account_id=str(uuid.uuid4())
        for uid,name in ((self.uid,'MinecraftName'),(self.other,'Another'),(self.same_name,'Steve')):
            self.state['catalog'].create({'uuid':uid,'name':name,'ip':'8.8.8.8','region':'私人归属地','notes':'私人管理备注'})
        with self.db:
            self.db.execute('INSERT INTO registration_accounts VALUES(?,?,?,?,?,?)',(self.account_id,'Steve','steve','123456789@qq.com','123456789',time.time()))
            self.db.execute('INSERT INTO account_passwords VALUES(?,?,?)',(self.account_id,DIGEST,time.time()))
            self.db.execute('INSERT INTO account_game_links VALUES(?,?,?)',(self.account_id,'survival',self.uid))
            for uid in (self.uid,self.other,self.same_name):
                pid=self.db.execute('SELECT id FROM player_profiles WHERE uuid=?',(uid,)).fetchone()[0]
                self.db.execute('INSERT INTO player_visits(profile,server,server_name,first_seen,last_seen,ip,snapshot) VALUES(?,?,?,?,?,?,?)',(pid,'survival','生存服',time.time()-50,time.time(),'8.8.8.8','{"op":true}'))
        self.state['bot'].snapshots['survival']={'last_seen':time.time(),'players':['MinecraftName'],'max_players':20,'capabilities':['player_management'],
              'player_records':[{'uuid':self.uid,'name':'MinecraftName','online':True,'ip':'8.8.8.8','op':True}]}

    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()

    async def login(self,password=PASSWORD,player='Steve'):
        return await self.client.post('/api/v1/account/login',json={'player':player,'password':password})

    async def token(self):
        response=await self.login();self.assertEqual(response.status,200,await response.text());return (await response.json())['access_token']

    async def save(self, **changes):
        if 'connection_enabled' in changes and 'website_mode' not in changes:
            changes['website_mode']='custom' if changes['connection_enabled'] else 'none'
        value=self.service.config_response();value={key:value[key] for key in ('settings','revision')};value['settings'].update(changes)
        response=await self.client.put('/api/website/settings',headers=self.admin,json=value)
        self.assertEqual(response.status,200,await response.text());return await response.json()

    async def test_public_projection_has_only_authorized_fields_and_pagination(self):
        data=await (await self.client.get('/api/v1/players?page_size=2')).json()
        self.assertEqual(data['total'],3);self.assertEqual(len(data['players']),2)
        for player in data['players']:self.assertEqual(set(player),{'name','uuid','status'})
        response=await self.client.get('/api/v1/players/'+self.uid);data=await response.json()
        self.assertEqual(data['player']['status'],'online');self.assertEqual(set(data),{'player'})
        for forbidden in ('8.8.8.8','私人','123456789','op','email','notes'):self.assertNotIn(forbidden,json.dumps(data))
        self.assertEqual((await self.client.get('/api/v1/players/not-uuid')).status,400)
        self.assertEqual((await self.client.get('/api/v1/players/'+str(uuid.uuid4()))).status,404)
        for qs in ('page=0','page_size=51','page=abc','q='+('x'*65),'ip=8.8.8.8'):
            self.assertEqual((await self.client.get('/api/v1/players?'+qs)).status,400)
        self.assertEqual((await (await self.client.get('/api/v1/players?q=%')).json())['total'],0)

    async def test_stale_heartbeat_and_incomplete_snapshot_are_unknown(self):
        snap=self.state['bot'].snapshots['survival'];snap['last_seen']=time.time()-16
        self.assertEqual((await (await self.client.get('/api/v1/players/'+self.uid)).json())['player']['status'],'unknown')
        servers=await (await self.client.get('/api/v1/servers')).json()
        self.assertIsNone(servers['servers'][0]['online_count']);self.assertFalse(servers['servers'][0]['connected'])
        snap['last_seen']=time.time();snap['players_truncated']=True
        self.assertEqual((await (await self.client.get('/api/v1/players/'+self.other)).json())['player']['status'],'unknown')
        snap['players_truncated']=False
        self.assertEqual((await (await self.client.get('/api/v1/players/'+self.other)).json())['player']['status'],'offline')

    async def test_public_settings_redact_backend_config_and_server_secrets(self):
        info=await (await self.client.get('/api/v1/community/info')).json()
        self.assertEqual(info['title'],'星桥社区');self.assertFalse(info['registration_enabled'])
        self.assertTrue(info['login_enabled'])
        servers=await (await self.client.get('/api/v1/servers')).json()
        self.assertEqual(set(servers['servers'][0]),{'id','name','connected','online_count','max_players'})
        for name in ('api_token','smtp_password','allowed_origins','commands','groups','token','password_hash'):
            self.assertNotIn(name,json.dumps([info,servers]))

    async def test_own_profile_uses_uuid_links_not_same_names_and_hides_notes(self):
        token=await self.token();headers={'Authorization':'Bearer '+token}
        data=await (await self.client.get('/api/v1/me/profile',headers=headers)).json()
        self.assertEqual(data['account']['email'],'123456789@qq.com')
        self.assertEqual([p['uuid'] for p in data['game_profiles']],[self.uid])
        for field in ('ip','notes','op','password_hash'):self.assertNotIn('"'+field+'"',json.dumps(data))
        self.assertNotIn(self.same_name,json.dumps(data));self.assertNotIn(self.other,json.dumps(data))
        with self.db:self.db.execute('INSERT INTO bindings VALUES(?,?,?,?,?)',('another','123456789',self.other,'Another',time.time()))
        data=await (await self.client.get('/api/v1/me/profile',headers=headers)).json()
        self.assertEqual({p['uuid'] for p in data['game_profiles']},{self.uid,self.other})

    async def test_user_and_integration_authorities_are_separate(self):
        self.reg.settings['api_token']='website-'+('k'*40)
        user=await self.token();path='/api/v1/accounts/'+self.account_id+'/profile'
        for token in (user,self.cfg['app']['admin_token'],self.cfg['servers'][0]['token']):
            self.assertEqual((await self.client.get(path,headers={'Authorization':'Bearer '+token})).status,401)
        key={'Authorization':'Bearer '+self.reg.settings['api_token']}
        self.assertEqual((await self.client.get('/api/v1/me/profile',headers=key)).status,401)
        self.assertEqual((await self.client.get(path,headers=key)).status,200)
        self.assertEqual((await self.client.get('/api/v1/me/profile')).status,401)
        self.reg.settings['api_token']=''
        self.assertEqual((await self.client.get(path,headers=key)).status,401)

    async def test_privacy_switch_blocks_public_but_not_own_profile(self):
        user=await self.token();await self.save(public_players=False,public_servers=False)
        for url in ('/api/v1/players','/api/v1/players/'+self.uid,'/api/v1/servers'):
            self.assertEqual((await self.client.get(url)).status,403)
        self.assertEqual((await self.client.get('/api/v1/me/profile',headers={'Authorization':'Bearer '+user})).status,200)

    async def test_login_closed_registration_logout_and_expiry(self):
        self.assertFalse(self.reg.settings['enabled'])
        response=await self.login(player='sTEVe');self.assertEqual(response.status,200);data=await response.json()
        self.assertEqual(data['expires_in'],3600)
        token=data['access_token'];headers={'Authorization':'Bearer '+token}
        digest=hashlib.sha256(token.encode()).hexdigest()
        self.assertIsNotNone(self.db.execute('SELECT 1 FROM registration_sessions WHERE token_hash=?',(digest,)).fetchone())
        self.assertEqual((await self.client.post('/api/v1/account/logout',headers=headers,json={})).status,200)
        self.assertEqual((await self.client.get('/api/v1/me/profile',headers=headers)).status,401)
        token=await self.token();digest=hashlib.sha256(token.encode()).hexdigest()
        with self.db:self.db.execute('UPDATE registration_sessions SET expires=0 WHERE token_hash=?',(digest,))
        self.assertEqual((await self.client.get('/api/v1/me/profile',headers={'Authorization':'Bearer '+token})).status,401)
        await self.save(login_enabled=False)
        self.assertEqual((await self.login()).status,503)

    async def test_bad_credentials_generic_and_persistent_rate_limit(self):
        for player,password in (('Unknown',PASSWORD),('Steve','wrong-password'),('Steve','invalid\x00-password')):
            response=await self.login(password,player);self.assertEqual(response.status,401)
            self.assertEqual((await response.json())['code'],'credentials_invalid')
        for _ in range(8):self.reg.limit('website-login-name:blocked',8,300)
        self.assertEqual((await self.login(player='Blocked')).status,429)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM registration_sessions').fetchone()[0],0)

    async def test_password_reset_and_setting_changes_during_verification_cannot_issue_session(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def delayed(*args):entered.set();await release.wait();return True
        with patch.object(self.reg.password_work,'run',side_effect=delayed):
            pending=asyncio.create_task(self.login());await entered.wait()
            with self.db:self.db.execute('UPDATE account_passwords SET password_hash=? WHERE account_id=?',('changed',self.account_id))
            release.set();response=await pending
        self.assertEqual(response.status,401);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM registration_sessions').fetchone()[0],0)
        with self.db:self.db.execute('UPDATE account_passwords SET password_hash=? WHERE account_id=?',(DIGEST,self.account_id))
        entered.clear();release.clear()
        with patch.object(self.reg.password_work,'run',side_effect=delayed):
            pending=asyncio.create_task(self.login());await entered.wait();await self.save(login_enabled=False);release.set();response=await pending
        self.assertEqual(response.status,409);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM registration_sessions').fetchone()[0],0)

    async def test_exact_cors_for_public_login_and_profile(self):
        self.reg.settings['allowed_origins']=['https://www.example.com']
        headers={'Origin':'https://www.example.com'}
        response=await self.client.get('/api/v1/community/info',headers=headers)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'],headers['Origin'])
        response=await self.client.options('/api/v1/account/login',headers={**headers,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
        self.assertEqual(response.status,204);self.assertIn('Authorization',response.headers['Access-Control-Allow-Headers'])
        for origin in ('null','https://www.example.com.attacker','https://bad.example'):
            self.assertEqual((await self.client.get('/api/v1/players',headers={'Origin':origin})).status,403)
        result=await self.login();token=(await result.json())['access_token']
        response=await self.client.get('/api/v1/me/profile',headers={**headers,'Authorization':'Bearer '+token})
        self.assertEqual(response.status,200);self.assertEqual(response.headers['Cache-Control'],'no-store')

    async def test_settings_revision_authorization_and_durable_save(self):
        old=self.service.config_response();old={key:old[key] for key in ('settings','revision')}
        self.assertEqual((await self.client.put('/api/website/settings',json=old)).status,401)
        await self.save(title='新的社区',rules='<script>still plain text</script>',accent_color='#536e8c',theme_mode='dark',grid_background=False)
        self.assertEqual((await self.client.put('/api/website/settings',headers=self.admin,json=old)).status,409)
        self.assertEqual(json.loads(self.service.path.read_text(encoding='utf-8'))['title'],'新的社区')
        self.assertEqual(Website(self.service.path.parent.parent,self.state).settings['title'],'新的社区')
        public=await (await self.client.get('/api/v1/community/info')).json()
        self.assertEqual(public['accent_color'],'#536e8c');self.assertEqual(public['theme_mode'],'dark');self.assertFalse(public['grid_background'])

    async def test_bot_does_not_serve_website_assets_and_redirects_only_when_connected(self):
        self.assertEqual((await self.client.get('/community/')).status,404)
        await self.save(website_url='https://www.example.com/community/',api_public_url='https://bridge.example.com/api/v1',connection_enabled=True)
        response=await self.client.get('/community/',allow_redirects=False)
        self.assertEqual(response.status,302);self.assertEqual(response.headers['Location'],'https://www.example.com/community/')
        for path in ('/community/site.css','/community/site.js','/community/config.json','/community/config.toml'):
            self.assertEqual((await self.client.get(path)).status,404)
        self.assertEqual((await self.client.get('/website-panel.js')).status,200)
        await self.save(connection_enabled=False)
        self.assertEqual((await self.client.get('/community/',allow_redirects=False)).status,404)

    async def test_connection_controls_exact_cors_and_not_other_origins(self):
        await self.save(website_url='https://WWW.Example.com:443/sub/',connection_enabled=True)
        self.assertEqual(self.service.connected_origin,'https://www.example.com')
        headers={'Origin':'https://www.example.com'}
        for path in ('/api/v1/community/info','/api/v1/servers','/api/v1/registration/info'):
            response=await self.client.get(path,headers=headers)
            self.assertEqual(response.status,200);self.assertEqual(response.headers['Access-Control-Allow-Origin'],headers['Origin'])
        response=await self.client.options('/api/v1/account/login',headers={**headers,'Access-Control-Request-Method':'POST'})
        self.assertEqual(response.status,204)
        self.assertEqual((await self.client.get('/api/v1/servers',headers={'Origin':'https://www.example.com.attacker'})).status,403)
        self.reg.settings['allowed_origins']=['https://www.example.com','https://other.example.com']
        await self.save(connection_enabled=False)
        self.assertEqual((await self.client.get('/api/v1/servers',headers=headers)).status,403)
        self.assertEqual((await self.client.get('/api/v1/servers',headers={'Origin':'https://other.example.com'})).status,200)
        public=await(await self.client.get('/api/v1/community/info')).json()
        for field in ('website_url','api_public_url','connection_enabled','website_mode'):self.assertNotIn(field,public)

    async def test_each_website_mode_persists_and_controls_connection(self):
        for mode in ('provided','none','custom','none'):
            data=await self.save(website_mode=mode,website_url='https://website.example.com/')
            enabled=mode!='none'
            self.assertEqual(data['connection']['mode'],mode);self.assertEqual(data['connection']['enabled'],enabled)
            self.assertEqual(Website(self.base,self.state).settings['website_mode'],mode)
            response=await self.client.get('/api/v1/servers',headers={'Origin':'https://website.example.com'})
            self.assertEqual(response.status,200 if enabled else 403)
            response=await self.client.get('/community/',allow_redirects=False)
            self.assertEqual(response.status,302 if enabled else 404)
            self.assertEqual(self.service.settings['website_url'],'https://website.example.com/')
            self.assertEqual((await self.client.get('/api/v1/servers')).status,200)

    async def test_connection_config_download_and_optional_project(self):
        for path,method in (('/api/website/config','post'),('/api/website/project','get')):
            self.assertEqual((await getattr(self.client,method)(path)).status,401)
        await self.save(api_public_url='https://bridge.example.com/api/v1')
        response=await self.client.post('/api/website/config',headers=self.admin,json={})
        self.assertEqual(response.status,200);self.assertEqual(await response.json(),{'apiBase':'https://bridge.example.com/api/v1'})
        self.assertIn('config.json',response.headers['Content-Disposition'])
        self.assertEqual((await self.client.post('/api/website/config',headers=self.admin,json={'api_base':'https://u:p@example.com/api/v1'})).status,400)
        self.assertEqual((await self.client.post('/api/website/package',headers=self.admin,json={})).status,410)
        with patch('starbridge.website_api.ROOT',self.base):
            self.assertEqual((await self.client.get('/api/website/project',headers=self.admin)).status,404)
            file=self.base/'dist/StarBridge-website.zip';file.parent.mkdir();file.write_bytes(b'project-release')
            response=await self.client.get('/api/website/project',headers=self.admin)
            self.assertEqual(response.status,200);self.assertEqual(await response.read(),b'project-release')
            with file.open('wb') as stream:stream.truncate(4*1024*1024+1)
            self.assertEqual((await self.client.get('/api/website/project',headers=self.admin)).status,413)

    async def test_end_to_end_register_password_login_and_reset_revoke_sessions(self):
        settings=self.reg.config_response();settings['settings'].update(enabled=True,smtp_host='smtp.test.example',smtp_from='sender@example.com')
        await self.reg.save_settings(settings['settings'],settings['revision'])
        mail=[]
        with patch('starbridge.registration.send_verification',side_effect=lambda *args:mail.append(args)):
            response=await self.client.post('/api/v1/registration/request',json={'player':'NewPlayer','email':'987654321@qq.com'})
            self.assertEqual(response.status,202);challenge=(await response.json())['challenge_id']
            response=await self.client.post('/api/v1/registration/verify',json={'challenge_id':challenge,'code':mail[-1][3],'password':PASSWORD})
            self.assertEqual(response.status,201);registered=await response.json()
            response=await self.login(player='NewPlayer');self.assertEqual(response.status,200);logged_in=await response.json()
            response=await self.client.post('/api/v1/account/password/request',json={'player':'NewPlayer','email':'987654321@qq.com'})
            challenge=(await response.json())['challenge_id']
            response=await self.client.post('/api/v1/account/password/verify',json={'challenge_id':challenge,'code':mail[-1][3],'password':'New-password-2026'})
            self.assertEqual(response.status,200,await response.text())
        for token in (registered['access_token'],logged_in['access_token']):
            self.assertEqual((await self.client.get('/api/v1/me/profile',headers={'Authorization':'Bearer '+token})).status,401)
        self.assertEqual((await self.login(player='NewPlayer')).status,401)
        self.assertEqual((await self.login(player='NewPlayer',password='New-password-2026')).status,200)
