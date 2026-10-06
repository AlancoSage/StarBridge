import tempfile
import unittest
import uuid
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from starbridge.app import STATE, create_app
from starbridge.catalog import Catalog
from starbridge.storage import Store
from tests.test_players import STEVE, record
from tests.test_starbridge import config


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = config()
        self.cfg['servers'].append({'id': 'creative', 'name': '创造服', 'token': 'd' * 32, 'groups': ['102'], 'commands': {}})
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()
        self.state = self.client.app[STATE]
        self.admin = {'Authorization': 'Bearer ' + self.cfg['app']['admin_token']}

    async def asyncTearDown(self):
        await self.client.close()

    async def request(self, method, path='', data=None):
        return await self.client.request(method, '/api/player-profiles' + path, headers=self.admin, json=data)

    async def add(self, **extra):
        response = await self.request('POST', data={'name': 'Steve', 'uuid': str(uuid.uuid4()), **extra})
        self.assertEqual(response.status, 201)
        return await response.json()

    async def tick(self, sid='survival', records=None, events=None):
        records = records if records is not None else [{**record(), 'ip': '127.0.0.1'}]
        server = self.state['bot'].servers[sid]
        response = await self.client.post('/bridge/' + sid + '/tick', headers={'Authorization': 'Bearer ' + server['token']}, json={'players': [r['name'] for r in records if r['online']], 'player_records': records, 'capabilities': ['player_management'], 'max_players': 20, 'events': events or [], 'results': []})
        self.assertEqual(response.status, 200)

    async def test_auth_validation_duplicates_and_pagination(self):
        self.assertEqual((await self.client.get('/api/player-profiles')).status, 401)
        for fields in ({'name':'bad name','uuid':STEVE}, {'name':'Steve','uuid':'bad'}, {'name':'Steve','uuid':STEVE,'ip':'example.com'}, {'name':'Steve','uuid':STEVE,'notes':'x'*1001}):
            self.assertEqual((await self.request('POST',data=fields)).status, 400)
        p = await self.add(uuid=STEVE)
        self.assertEqual((await self.request('POST',data={'name':'Alex','uuid':STEVE})).status,409)
        for i in range(12):
            await self.add(name='User_' + str(i))
        page = await (await self.request('GET','?page_size=10&page=2')).json()
        self.assertEqual((page['total'],page['page'],len(page['items'])),(13,2,3))
        for query in ('?page=0','?page_size=11','?binding=bad','?status=bad'):
            self.assertEqual((await self.request('GET',query)).status,400)
        escaped = await (await self.request('GET','?name=%25')).json()
        self.assertEqual(escaped['total'],0)
        by_uuid = await (await self.request('GET','?uuid='+STEVE)).json()
        self.assertEqual(by_uuid['items'][0]['id'],p['id'])

    async def test_edit_conflict_scoped_binding_and_filters(self):
        p = await self.add(uuid=STEVE,ip='127.0.0.1')
        path = '/' + str(p['id'])
        payload = {'region':'上海 / 电信','notes':'老玩家','revision':p['revision']}
        response = await self.request('PATCH',path,payload)
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['region'],'上海 / 电信')
        self.assertEqual((await self.request('PATCH',path,payload)).status,409)
        for sid in ('survival','creative'):
            self.assertEqual((await self.request('POST',path+'/bind',{'server':sid,'qq':'123456'})).status,200)
        self.assertEqual((await self.request('POST',path+'/bind',{'server':'survival','qq':'99999'})).status,409)
        for query in ('?binding=bound','?server=creative','?ip=127.0','?region=上海','?name=123456'):
            self.assertEqual((await (await self.request('GET',query)).json())['total'],1)
        self.assertEqual((await (await self.request('GET','?binding=unbound')).json())['total'],0)
        response = await self.request('POST','/bulk',{'ids':[p['id']], 'action':'unbind','server':'survival'})
        self.assertEqual((await response.json())['bindings_removed'],1)
        updated = await (await self.request('GET',path)).json()
        self.assertEqual([b['server'] for b in updated['bindings']],['creative'])

    async def test_uuid_merges_servers_ip_change_and_disconnected_history(self):
        await self.tick()
        await self.tick('creative')
        items = await (await self.request('GET')).json()
        self.assertEqual(items['total'],1)
        p=items['items'][0]
        self.assertEqual(len(p['servers']),2)
        await self.request('PATCH','/'+str(p['id']),{'region':'旧地址','revision':p['revision']})
        await self.tick(records=[{**record(),'ip':'192.168.1.2'}])
        p=await (await self.request('GET','/'+str(p['id']))).json()
        self.assertEqual((p['ip'],p['region']),('192.168.1.2',''))
        self.state['bot'].snapshots.clear()
        del self.state['bot'].servers['creative']
        p=await (await self.request('GET','/'+str(p['id']))).json()
        self.assertEqual(p['status'],'unknown')
        self.assertTrue(next(v for v in p['servers'] if v['server']=='creative')['historical'])

    async def test_bulk_atomic_delete_and_fresh_join_restore(self):
        event={'id':'join-original','kind':'join','uuid':STEVE,'player':'Steve','ip':'127.0.0.1'}
        await self.tick(events=[event])
        p=(await (await self.request('GET')).json())['items'][0]
        await self.request('POST','/'+str(p['id'])+'/bind',{'server':'survival','qq':'12345'})
        response=await self.request('POST','/bulk',{'ids':[p['id'],999999],'action':'delete'})
        self.assertEqual(response.status,409)
        self.assertEqual((await self.request('GET','/'+str(p['id']))).status,200)
        for ids in ([],[True],[p['id'],p['id']]):
            self.assertEqual((await self.request('POST','/bulk',{'ids':ids,'action':'delete'})).status,400)
        self.assertEqual((await self.request('POST','/bulk',{'ids':[p['id']],'action':'delete'})).status,200)
        self.assertEqual(self.state['store'].bindings(),[])
        await self.tick(events=[event])
        self.assertEqual((await (await self.request('GET')).json())['total'],0)
        await self.tick(events=[{**event,'id':'join-new'}])
        restored=(await (await self.request('GET')).json())['items'][0]
        self.assertEqual(restored['id'],p['id'])
        self.assertEqual(restored['bindings'],[])

    async def test_catalog_persists_on_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profiles.db'
            store=Store(path)
            catalog=Catalog(store)
            pid=catalog.create({'name':'Steve','uuid':STEVE,'ip':'127.0.0.1','region':'本地','notes':'持久记录'})
            catalog.bind(pid,'survival','12345')
            store.close()
            store=Store(path)
            try:
                catalog=Catalog(store)
                p=catalog.get(pid,self.state)
                self.assertEqual((p['notes'],p['ip']),('持久记录','127.0.0.1'))
                self.assertEqual(p['bindings'][0]['qq'],'12345')
            finally:
                store.close()
