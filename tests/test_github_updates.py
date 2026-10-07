import json
import unittest
from unittest.mock import patch

from starbridge.github_updates import DEFAULT_SETTINGS, GitHubReleases, update_settings, version_number
from starbridge.registration import RegistrationError


class Content:
    def __init__(self, raw): self.raw = raw
    async def read(self, count): return self.raw[:count]


class Response:
    def __init__(self, value=None, status=200, headers=None, raw=None):
        self.status=status;self.headers=headers or {};self.content=Content(raw if raw is not None else json.dumps(value).encode())
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass


class Client:
    def __init__(self, responses):self.responses=list(responses);self.calls=[]
    def get(self,url,**kwargs):self.calls.append((url,kwargs));return self.responses.pop(0)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass


class GitHubUpdateTests(unittest.IsolatedAsyncioTestCase):
    def service(self):return GitHubReleases({**DEFAULT_SETTINGS,'github_token':'github_pat_'+'x'*30})

    async def test_signed_redirect_strips_credentials_and_rejects_untrusted_hosts(self):
        for bad in ('https://example.com/steal','http://release-assets.githubusercontent.com/a','https://user@release-assets.githubusercontent.com/a','https://release-assets.githubusercontent.com:444/a'):
            client=Client([Response(status=302,headers={'Location':bad})])
            with self.subTest(url=bad),self.assertRaises(RegistrationError):
                async with self.service().asset(client,42):pass
            self.assertEqual(len(client.calls),1)
        client=Client([Response(status=302,headers={'Location':'https://release-assets.githubusercontent.com/a?signature=test'}),Response(raw=b'zip')])
        async with self.service().asset(client,42) as response:self.assertEqual(await response.content.read(100),b'zip')
        self.assertIn('Authorization',client.calls[0][1]['headers'])
        self.assertNotIn('Authorization',client.calls[1][1]['headers'])
        self.assertTrue(all(c[1]['allow_redirects'] is False for c in client.calls))

    async def test_release_selection_ignores_drafts_and_prereleases(self):
        rows=[{'tag_name':'v0.6.2','draft':True}, {'tag_name':'v0.7.0','prerelease':True}, {'tag_name':'malicious/path'},
              {'tag_name':'v0.5.0','assets':[]},{'tag_name':'v0.6.1','assets':[{'name':'StarBridge-Windows-0.6.1.zip'}]}]
        client=Client([Response(rows)])
        with patch('starbridge.github_updates.aiohttp.ClientSession',return_value=client):items=await self.service().releases()
        self.assertEqual([r['version'] for r in items],['0.6.1','0.5.0']);self.assertTrue(items[0]['updatable']);self.assertFalse(items[1]['updatable'])

    async def test_digest_and_checksum_fallback_and_numeric_version_order(self):
        asset={'name':'StarBridge-Windows-0.6.1.zip','id':42,'size':100,'state':'uploaded','digest':'sha256:'+'a'*64}
        release={'tag_name':'v0.6.1','assets':[asset]}
        client=Client([Response(release)])
        with patch('starbridge.github_updates.aiohttp.ClientSession',return_value=client):info=await self.service().check('0.6.0','v0.6.1')
        self.assertTrue(info['available']);self.assertEqual(info['sha256'],'a'*64)
        asset.pop('digest');release['assets'].append({'name':'SHA256SUMS.txt','id':43})
        client=Client([Response(release),Response(raw=('b'*64+'  StarBridge-Windows-0.6.1.zip\n').encode())])
        with patch('starbridge.github_updates.aiohttp.ClientSession',return_value=client):info=await self.service().check('0.10.0','v0.6.1')
        self.assertFalse(info['available']);self.assertEqual(info['sha256'],'b'*64)
        client=Client([Response(release),Response(raw=b'bad checksum')])
        with patch('starbridge.github_updates.aiohttp.ClientSession',return_value=client),self.assertRaises(RegistrationError):await self.service().check('0.6.0','v0.6.1')

    async def test_private_access_error_never_includes_server_body_or_token(self):
        for status in (401,403,404,429,500):
            client=Client([Response({'error':'signed-private-url-and-token'},status=status)])
            with self.subTest(status=status),patch('starbridge.github_updates.aiohttp.ClientSession',return_value=client),self.assertRaises(RegistrationError) as error:
                await self.service().releases()
            self.assertNotIn('signed-private',str(error.exception));self.assertNotIn('github_pat_',str(error.exception))

    def test_legacy_settings_and_strict_validation(self):
        self.assertEqual(update_settings({'feed_url':'https://example.com/feed.json'})['source'],'https')
        self.assertEqual(update_settings(DEFAULT_SETTINGS)['source'],'github')
        for bad in ({}, {'source':'github'}, {**DEFAULT_SETTINGS,'github_repository':'https://evil.example/x'}, {**DEFAULT_SETTINGS,'github_token':'token\nheader'}):
            with self.subTest(settings=bad),self.assertRaises(RegistrationError):update_settings(bad)
        self.assertGreater(version_number('0.10.0'),version_number('0.9.9'))
