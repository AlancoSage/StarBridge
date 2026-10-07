"""Read private GitHub Releases without forwarding credentials to asset storage."""
from contextlib import asynccontextmanager
import json
import re
from urllib.parse import urlsplit

import aiohttp
from .registration import RegistrationError

DEFAULT_REPOSITORY = 'AlancoSage/StarBridge'
MAX_PACKAGE = 64 * 1024 * 1024
DEFAULT_SETTINGS = {'source': 'github', 'feed_url': '', 'github_repository': DEFAULT_REPOSITORY, 'github_token': ''}


def update_settings(value):
    if not isinstance(value, dict) or value.keys() not in (DEFAULT_SETTINGS.keys(), {'feed_url'}):
        raise RegistrationError('更新设置格式错误')
    # Preserve existing HTTPS feeds and old backups.
    settings = {**DEFAULT_SETTINGS, **value}
    if 'source' not in value and value.get('feed_url'): settings['source'] = 'https'
    if settings['source'] not in ('github', 'https'): raise RegistrationError('更新源类型错误')
    if not isinstance(settings['feed_url'], str): raise RegistrationError('更新源地址错误')
    if settings['feed_url']:
        from .updates import https_url
        https_url(settings['feed_url'])
    repo = settings['github_repository']
    if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repo) or repo.split('/')[1] in ('.', '..'):
        raise RegistrationError('GitHub 仓库格式为 用户名/仓库名')
    token = settings['github_token']
    if not isinstance(token, str) or token and not re.fullmatch(r'[A-Za-z0-9_]{20,255}', token):
        raise RegistrationError('GitHub 令牌格式错误')
    return settings


def version_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d{1,6}\.\d{1,6}\.\d{1,6}', value):
        raise RegistrationError('仅支持正式版本号，例如 v0.6.1')
    return tuple(int(part) for part in value.removeprefix('v').split('.'))


class GitHubReleases:
    def __init__(self, settings):
        self.repository = settings['github_repository']
        self.headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'StarBridge-Updater'}
        if settings['github_token']: self.headers['Authorization'] = 'Bearer ' + settings['github_token']
        self.base = 'https://api.github.com/repos/' + self.repository

    @staticmethod
    def status(code):
        if code == 401: raise RegistrationError('GitHub 令牌无效或已过期，请重新设置', 400)
        if code in (403, 429): raise RegistrationError('GitHub 权限不足或请求限流，请检查令牌的 Contents 读取权限后稍后重试', 400)
        if code == 404: raise RegistrationError('GitHub 仓库或版本不可访问；私有仓库需要有读取权限的令牌', 400)
        if code != 200: raise RegistrationError('GitHub 返回异常，请稍后重试', 400)

    async def metadata(self, client, path):
        async with client.get(self.base + path, headers=self.headers, allow_redirects=False) as response:
            self.status(response.status)
            raw = await response.content.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024: raise RegistrationError('GitHub 版本信息超出大小限制')
            try: return json.loads(raw)
            except (ValueError, UnicodeError): raise RegistrationError('GitHub 没有返回有效版本信息') from None

    @asynccontextmanager
    async def asset(self, client, asset_id):
        if type(asset_id) is not int or asset_id < 1: raise RegistrationError('GitHub 附件编号错误')
        url = self.base + '/releases/assets/' + str(asset_id)
        headers = {**self.headers, 'Accept': 'application/octet-stream'}
        for attempt in range(4):
            async with client.get(url, headers=headers, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location', '')
                    parts = urlsplit(location)
                    if parts.scheme != 'https' or parts.hostname not in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'github-releases.githubusercontent.com') or parts.username or parts.password or parts.port not in (None, 443) or parts.fragment:
                        raise RegistrationError('GitHub 附件跳转地址不受信任，下载已停止')
                    url = location
                    # Never send a PAT to signed asset URLs, including subsequent redirects.
                    headers = {'Accept': 'application/octet-stream', 'User-Agent': 'StarBridge-Updater'}
                    continue
                self.status(response.status)
                yield response
                return
        raise RegistrationError('GitHub 附件跳转次数过多')

    async def releases(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20, connect=5)) as client:
            rows = await self.metadata(client, '/releases?per_page=100')
        if not isinstance(rows, list): raise RegistrationError('GitHub 版本列表格式错误')
        result = []
        for row in rows:
            if not isinstance(row, dict) or row.get('draft') or row.get('prerelease'): continue
            try: number = version_number(row.get('tag_name'))
            except RegistrationError: continue
            version = '.'.join(map(str, number))
            assets = row.get('assets', [])
            updatable = isinstance(assets, list) and any(a.get('name') == f'StarBridge-Windows-{version}.zip' for a in assets if isinstance(a, dict))
            result.append({'tag': row['tag_name'], 'version': version, 'name': str(row.get('name') or row['tag_name'])[:200],
                           'notes': str(row.get('body') or '')[:3000], 'url': 'https://github.com/' + self.repository + '/releases/tag/' + row['tag_name'],
                           'updatable': updatable, 'published_at': row.get('published_at', '')})
        return sorted(result, key=lambda item: version_number(item['version']), reverse=True)

    async def check(self, current, tag=''):
        if not tag:
            releases = await self.releases()
            compatible = [r for r in releases if r['updatable']]
            if not compatible: return {'available': False, 'message': '仓库尚无支持面板更新的正式部署包'}
            tag = compatible[0]['tag']
        number = version_number(tag); version = '.'.join(map(str, number))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, connect=5)) as client:
            release = await self.metadata(client, '/releases/tags/' + tag)
            if not isinstance(release, dict) or release.get('draft') or release.get('prerelease') or release.get('tag_name') != tag:
                raise RegistrationError('请选择已发布的正式版本')
            name = f'StarBridge-Windows-{version}.zip'
            assets = release.get('assets', [])
            if not isinstance(assets, list): raise RegistrationError('GitHub 附件列表错误')
            package = next((a for a in assets if isinstance(a, dict) and a.get('name') == name and a.get('state') == 'uploaded'), None)
            if not package: raise RegistrationError('该历史版本只支持手动安装，没有面板升级包')
            size = package.get('size')
            if type(size) is not int or not 1 <= size <= MAX_PACKAGE: raise RegistrationError('GitHub 部署包大小错误或超过 64 MiB')
            digest = package.get('digest', '') or ''
            sha = digest[7:] if isinstance(digest, str) and digest.startswith('sha256:') else ''
            if not re.fullmatch(r'[a-f0-9]{64}', sha):
                sums = next((a for a in assets if isinstance(a, dict) and a.get('name') == 'SHA256SUMS.txt'), None)
                if not sums: raise RegistrationError('GitHub 版本缺少 SHA256 校验信息')
                async with self.asset(client, sums['id']) as response:
                    raw = await response.content.read(16385)
                if len(raw) > 16384: raise RegistrationError('版本校验清单过大')
                try: lines = raw.decode('utf-8').splitlines()
                except UnicodeError: raise RegistrationError('版本校验清单格式错误') from None
                matches = [line.split()[0] for line in lines if len(line.split()) == 2 and line.split()[1].lstrip('*') == name and re.fullmatch(r'[a-f0-9]{64}', line.split()[0])]
                if len(matches) != 1: raise RegistrationError('版本校验清单缺少唯一的部署包校验值')
                sha = matches[0]
        if type(package.get('id')) is not int or package['id'] < 1: raise RegistrationError('GitHub 部署包附件编号错误')
        return {'version': version, 'tag': tag, 'asset_id': package['id'], 'size': size, 'sha256': sha,
                'notes': str(release.get('body') or '')[:3000], 'available': number > version_number(current)}
