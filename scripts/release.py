"""Build and publish complete Releases; never replace published versions."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
GAME_LOADERS = {'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric'}
FABRIC_CORE = ('cn/starbridge/fabric/StarBridgeFabric.class', 'cn/starbridge/fabric/FabricRuntime.class',
               'cn/starbridge/fabric/FabricPacketGate.class', 'cn/starbridge/fabric/FabricHost.class',
               'cn/starbridge/fabric/FabricNative.class', 'cn/starbridge/mods/BridgeEngine.class')
FABRIC_RESOURCES = ('starbridge-fabric.mixins.json', 'starbridge-fabric-mappings.json')
FABRIC_MIXINS = ('ServerMixin', 'ConnectionMixin', 'CommandsMixin', 'CommandsExecuteMixin',
                 'DamageMixin', 'PickupMixin', 'PlayerJoinMixin')
NEOFORGE_CORE = ('cn/starbridge/neoforge/StarBridgeNeoForge.class', 'cn/starbridge/neoforge/NeoForgeRuntime.class',
                 'cn/starbridge/neoforge/NeoForgePacketGate.class', 'cn/starbridge/neoforge/NeoForgeHost.class',
                 'cn/starbridge/neoforge/NeoForgeNative.class', 'cn/starbridge/mods/BridgeEngine.class')
NEOFORGE_RESOURCES = ('starbridge-neoforge.mixins.json', 'starbridge-neoforge-mappings.json')
NEOFORGE_MIXINS = (*FABRIC_MIXINS, 'PlayerManagerChatMixin')


def gh(*args, check=True):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, encoding='utf-8')
    if check and result.returncode:
        # Command output can contain signed asset URLs; report only a generic failure.
        raise RuntimeError('GitHub 操作失败，请检查 gh 授权、仓库权限和网络')
    return result


def code_version(content):
    for item in ast.parse(content).body:
        if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in item.targets):
            value = ast.literal_eval(item.value)
            if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+', value): return value
    raise ValueError('版本文件缺少正式版本号')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_literal(path, name):
    """Read the release checkout itself, including older checkouts without Fabric."""
    for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f'发布源码缺少 {name}')


def artifact_prefix(root):
    """Use this checkout's brand while retaining historical release filenames."""
    branding = root / 'starbridge/branding.py'
    prefix = source_literal(branding, 'ARTIFACT_PREFIX') if branding.is_file() else 'StarBridge'
    if prefix not in ('StarBridge', 'AetherBot', 'Myrinbot', 'VexBot'):
        raise ValueError('发布产物名称错误')
    return prefix


def native_filename(item, mod_version, prefix='StarBridge'):
    if prefix not in ('StarBridge', 'AetherBot', 'Myrinbot', 'VexBot'):
        raise ValueError('发布产物名称错误')
    loader = GAME_LOADERS.get(item.get('platform'))
    version = item.get('version')
    if not loader or not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('不支持的游戏端发布类型或版本')
    if not isinstance(mod_version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', mod_version):
        raise ValueError('游戏端发布版本错误')
    if type(item.get('java')) is not int or item['java'] not in (8, 17, 21, 25):
        raise ValueError('游戏端 Java 要求错误')
    return f'{prefix}-{loader}-{version}-{mod_version}.jar'


def validate_native_mod(path, item, mod_version, prefix='StarBridge'):
    expected_name = native_filename(item, mod_version, prefix)
    if path.name != expected_name:
        raise ValueError(f'游戏端文件名不一致：{path.name}')
    if not path.is_file():
        raise ValueError(f'缺少游戏端构建：{path.name}')
    legacy = item['platform'] == 'forge' and item['version'] in ('1.7.10', '1.12.2', '1.16.5')
    core = ('cn/starbridge/mods/BridgeEngine.class', 'cn/starbridge/mods/LegacyMod.class') if legacy else (
        'cn/starbridge/forge/StarBridge.class', 'cn/starbridge/forge/GameLogin.class')
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError(f'游戏端包含重复文件：{path.name}')
            if item['platform'] == 'fabric':
                metadata = json.loads(archive.read('fabric.mod.json'))
                if (not isinstance(metadata, dict) or metadata.get('id') != 'starbridge'
                    or metadata.get('version') != mod_version or metadata.get('environment') != 'server'
                    or not isinstance(metadata.get('depends'), dict)
                    or metadata['depends'].get('minecraft') != item['version']
                    or metadata['depends'].get('java') != '>=' + str(item['java'])
                    or (item.get('loader_version') and metadata['depends'].get('fabricloader') != '>=' + item['loader_version'])
                    or not isinstance(metadata.get('entrypoints'), dict)
                    or metadata['entrypoints'].get('main') != ['cn.starbridge.fabric.StarBridgeFabric']
                    or metadata.get('mixins') != ['starbridge-fabric.mixins.json']):
                    raise ValueError(f'游戏端元数据不一致：{path.name}')
                core = FABRIC_CORE
                if not all(name in names for name in FABRIC_RESOURCES):
                    raise ValueError(f'游戏端缺少必要资源：{path.name}')
                config = json.loads(archive.read('starbridge-fabric.mixins.json'))
                required_mixins = set(FABRIC_MIXINS)
                if item['version'] not in ('1.16.5', '1.18.2'):
                    required_mixins.add('PlayerManagerChatMixin')
                if (not isinstance(config, dict) or config.get('required') is not True
                    or config.get('package') != 'cn.starbridge.fabric.mixin'
                    or not isinstance(config.get('mixins'), list)
                    or not all(isinstance(name, str) for name in config['mixins'])
                    or not required_mixins.issubset(config['mixins'])
                    or not isinstance(config.get('injectors'), dict)
                    or config['injectors'].get('defaultRequire') != 1
                    or not all('cn/starbridge/fabric/mixin/' + name + '.class' in names for name in config['mixins'])):
                    raise ValueError(f'游戏端登录保护注入不完整：{path.name}')
                bindings = json.loads(archive.read('starbridge-fabric-mappings.json'))
                if not isinstance(bindings, dict) or bindings.get('mcVersion') != item['version']:
                    raise ValueError(f'游戏端映射版本不一致：{path.name}')
                expected_namespace = 'official' if item['version'].startswith('26.') else 'intermediary'
                if bindings.get('namespace', 'intermediary') != expected_namespace:
                    raise ValueError(f'游戏端映射命名空间不一致：{path.name}')
            else:
                metadata_name = 'mcmod.info' if item['version'] in ('1.7.10', '1.12.2') else 'META-INF/' + (
                    'neoforge.mods.toml' if item['platform'] == 'neoforge' and item['version'] != '1.20.4' else 'mods.toml')
                metadata = archive.read(metadata_name).decode('utf-8')
                if metadata_name == 'mcmod.info':
                    rows = json.loads(metadata)
                    if not isinstance(rows, list) or not any(isinstance(row, dict) and row.get('modid') == 'starbridge'
                        and row.get('version') == mod_version and row.get('mcversion') == item['version'] for row in rows):
                        raise ValueError(f'游戏端元数据不一致：{path.name}')
                else:
                    import tomllib
                    document = tomllib.loads(metadata)
                    mods = document.get('mods', [])
                    if not any(row.get('modId') == 'starbridge' and row.get('version') == mod_version for row in mods) or item['version'] not in metadata:
                        raise ValueError(f'游戏端元数据不一致：{path.name}')
                    if item['platform'] == 'neoforge' and item.get('config') == 'properties':
                        core = NEOFORGE_CORE
                        dependencies = document.get('dependencies', {}).get('starbridge', [])
                        expected = {'minecraft': '[' + item['version'] + ']',
                                    'neoforge': '[' + item.get('loader_version', '') + ',)'}
                        if (document.get('modLoader') != 'javafml' or document.get('loaderVersion') != '[1,)'
                            or document.get('features', {}).get('starbridge', {}).get('javaVersion') != '[' + str(item['java']) + ',)'
                            or not isinstance(dependencies, list)
                            or any(sum(isinstance(row, dict) and row.get('modId') == loader
                                and row.get('versionRange') == version_range and row.get('side') == 'SERVER'
                                and (row.get('mandatory') is True if item['version'] == '1.20.4' else row.get('type') == 'required')
                                for row in dependencies) != 1 for loader, version_range in expected.items())
                            or document.get('mixins') != [{'config': 'starbridge-neoforge.mixins.json'}]):
                            raise ValueError(f'游戏端元数据不一致：{path.name}')
                        if not all(name in names for name in NEOFORGE_RESOURCES):
                            raise ValueError(f'游戏端缺少必要资源：{path.name}')
                        config = json.loads(archive.read('starbridge-neoforge.mixins.json'))
                        if (not isinstance(config, dict) or config.get('required') is not True
                            or config.get('package') != 'cn.starbridge.neoforge.mixin'
                            or not isinstance(config.get('mixins'), list)
                            or not all(isinstance(name, str) for name in config['mixins'])
                            or not set(NEOFORGE_MIXINS).issubset(config['mixins'])
                            or not isinstance(config.get('injectors'), dict)
                            or config['injectors'].get('defaultRequire') != 1
                            or not all('cn/starbridge/neoforge/mixin/' + name + '.class' in names for name in config['mixins'])):
                            raise ValueError(f'游戏端登录保护注入不完整：{path.name}')
                        bindings = json.loads(archive.read('starbridge-neoforge-mappings.json'))
                        if (not isinstance(bindings, dict) or bindings.get('mcVersion') != item['version']
                            or bindings.get('neoForgeVersion') != item.get('loader_version')):
                            raise ValueError(f'游戏端映射版本不一致：{path.name}')
                        if bindings.get('namespace') != 'official':
                            raise ValueError(f'游戏端映射命名空间不一致：{path.name}')
            if not all(name in names for name in core):
                raise ValueError(f'游戏端缺少核心类：{path.name}')
            for name in names:
                if name.endswith('.class'):
                    content = archive.read(name)
                    if len(content) < 8 or content[:4] != b'\xca\xfe\xba\xbe':
                        raise ValueError(f'游戏端类文件无效：{path.name}')
                    if not 45 <= int.from_bytes(content[6:8], 'big') <= item['java'] + 44:
                        raise ValueError(f'游戏端 Java 要求不一致：{path.name}')
    except (KeyError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'游戏端元数据或 JAR 无效：{path.name}') from error


def proxy_assets(root):
    """Only releases declaring the proxy module require its separately deployable JAR."""
    source = root / 'starbridge/__init__.py'
    try:
        version = source_literal(source, '__velocity_version__')
    except ValueError:
        return []
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Velocity 插件版本错误')
    path = root / 'bridge/target' / f'{artifact_prefix(root)}-Velocity-{version}.jar'
    if not path.is_file():
        raise ValueError('请先构建 Velocity 密码找回插件：bridge-velocity/build.py')
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            metadata = json.loads(archive.read('velocity-plugin.json'))
            if (len(names) != len(set(names)) or archive.testzip() is not None
                    or metadata.get('id') != 'myrinbot-velocity' or metadata.get('version') != version
                    or metadata.get('main') != 'cn.starbridge.velocity.MyrinbotVelocity'
                    or not all('cn/starbridge/velocity/' + name + '.class' in names for name in (
                        'MyrinbotVelocity', 'BridgeHttp', 'BridgeConfig', 'NativeAuth',
                        'LimboAuthAdapter', 'LibreLoginAuth', 'Ownership'))
                    or 'config.properties' not in names):
                raise ValueError('Velocity 插件元数据或内容不一致')
            for name in names:
                if name.endswith('.class'):
                    content = archive.read(name)
                    if content[:4] != b'\xca\xfe\xba\xbe' or not 45 <= int.from_bytes(content[6:8], 'big') <= 61:
                        raise ValueError('Velocity 插件需要兼容 Java 17')
    except (KeyError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, AttributeError) as error:
        raise ValueError('Velocity 插件元数据或 JAR 无效') from error
    return [path]


def native_assets(root):
    """Return exactly the native assets declared by this release's source catalog."""
    catalog_file = root/'starbridge/game_bridges.py'
    prefix = artifact_prefix(root)
    if catalog_file.is_file():
        catalog = source_literal(catalog_file, 'GAME_BRIDGES')
        mod_version = source_literal(root/'starbridge/__init__.py', '__forge_version__')
        assets = []
        for item in catalog:
            mod = root/'bridge/target'/native_filename(item, mod_version, prefix)
            if mod in assets:
                raise ValueError('游戏端发布目录包含重复版本')
            validate_native_mod(mod, item, mod_version, prefix)
            assets.append(mod)
        return assets
    # Forge became available in 0.6.2; keep historical standalone assets intact.
    forge_source = root/'bridge-forge/gradle.properties'
    if forge_source.is_file():
        match = re.search(r'^mod_version=(\d+\.\d+\.\d+)\s*$', forge_source.read_text(encoding='utf-8'), re.M)
        if not match:
            raise ValueError('Forge 版本缺失')
        mod_version = match.group(1)
        item = {'platform': 'forge', 'version': '1.20.1', 'java': 17}
        mod = root/'bridge/target'/native_filename(item, mod_version, prefix)
        validate_native_mod(mod, item, mod_version, prefix)
        return [mod]
    return []


def build(root=ROOT):
    version = code_version((root/'starbridge/__init__.py').read_text(encoding='utf-8-sig'))
    prefix = artifact_prefix(root)
    dist = root/'dist'; dist.mkdir(exist_ok=True)
    # Require the matching bridge build, instead of silently publishing an incomplete ZIP.
    import xml.etree.ElementTree as ET
    bridge_version = ET.parse(root/'bridge/pom.xml').getroot().find('{http://maven.apache.org/POM/4.0.0}version').text
    bridge = root/f'bridge/target/{prefix}-{bridge_version}.jar'
    if not bridge.is_file(): raise ValueError('请先构建 Minecraft 端 JAR：bridge/build.ps1 或 mvn package')
    with zipfile.ZipFile(bridge) as archive:
        if not re.search(r'^version:\s*[\'"]?' + re.escape(bridge_version) + r'[\'"]?\s*$', archive.read('plugin.yml').decode('utf-8'), re.M):
            raise ValueError('游戏 JAR 版本与源码不一致')
    website = dist/f'{prefix}-website.zip'
    subprocess.run([sys.executable,str(root/'starbridge-website/build.py'),'--output',str(website)],check=True,cwd=root)
    # 0.5.x predates the supervised update protocol and is deliberately marked manual.
    automatic = (root/'scripts/update_runtime.py').is_file()
    bot = dist/f'{prefix}-{"Windows" if automatic else "Bot"}-{version}.zip'
    if automatic:
        subprocess.run([sys.executable,str(root/'scripts/build_windows.py'),'--output',str(bot)],check=True,cwd=root)
    else:
        names = ['README.md','config.example.toml','requirements.txt']
        for directory,suffixes in {'starbridge':{'.py','.js','.css','.html'},'docs':{'.md'},'examples':{'.js','.json'},'scripts':{'.py'}}.items():
            names.extend(p.relative_to(root).as_posix() for p in (root/directory).rglob('*') if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
        names += [bridge.relative_to(root).as_posix(), website.relative_to(root).as_posix()]
        for optional in ('星桥.bat','requirements.lock.txt'):
            if (root/optional).is_file(): names.append(optional)
        with zipfile.ZipFile(bot,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(set(names)):
                if (root/name).is_symlink(): raise ValueError('部署文件不能为符号链接')
                archive.write(root/name,'StarBridge/'+name)
    # Publish standalone website and bridge alongside the complete Bot archive.
    assets = [bot,website,bridge]
    # Read only this release's source catalog; historical checkouts stay complete.
    assets.extend(native_assets(root))
    assets.extend(proxy_assets(root))
    # Existing GitHub clients look for the old Windows asset name. Keep identical
    # aliases for every download so installed integrations can still find them.
    if prefix != 'StarBridge':
        aliases = []
        for path in assets:
            alias = path.with_name('StarBridge-' + path.name.removeprefix(prefix + '-'))
            if path.is_symlink() or alias.is_symlink():
                raise ValueError('发布附件不能为符号链接')
            shutil.copyfile(path, alias)
            aliases.append(alias)
        assets.extend(aliases)
    checksums = dist/'SHA256SUMS.txt'
    checksums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in assets),encoding='utf-8')
    return version,[*assets,checksums]


def publish(version,assets,repo,commit,notes,latest=True):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repo) or not re.fullmatch(r'[0-9a-f]{40}',commit): raise ValueError('仓库名或提交 SHA 错误')
    metadata = json.loads(gh('api','repos/'+repo).stdout)
    if (metadata.get('full_name', '').casefold() != repo.casefold()
        or type(metadata.get('private')) is not bool
        or metadata.get('archived') or metadata.get('disabled')):
        raise ValueError('发布目标仓库不匹配或不可写')
    source = json.loads(gh('api',f'repos/{repo}/contents/starbridge/__init__.py?ref={commit}').stdout)
    if code_version(base64.b64decode(source['content']).decode('utf-8-sig')) != version: raise ValueError('远程提交版本与发布包不一致')
    tag = 'v'+version
    existing = gh('api',f'repos/{repo}/releases/tags/{tag}',check=False)
    if existing.returncode == 0:
        release = json.loads(existing.stdout)
        if not release.get('draft'): raise ValueError('该版本已正式发布，不能覆盖；请增加版本号')
    else:
        title = next((name for name in ('VexBot', 'Myrinbot', 'AetherBot')
                      if any(path.name.startswith(name + '-') for path in assets)), 'StarBridge')
        payload = {'tag_name':tag,'target_commitish':commit,'name':title+' '+version,'body':notes,'draft':True,'prerelease':False,'make_latest':'false'}
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'release.json';file.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            release = json.loads(gh('api',f'repos/{repo}/releases','--method','POST','--input',str(file)).stdout)
    # Draft-only retries are safe; a published version is never changed.
    gh('release','upload',tag,*map(str,assets),'--repo',repo,'--clobber')
    remote = json.loads(gh('api',f'repos/{repo}/releases/{release["id"]}').stdout)
    for path in assets:
        item = next((a for a in remote['assets'] if a['name']==path.name),None)
        if not item or item['size']!=path.stat().st_size: raise ValueError('发布附件大小检查失败，保持草稿')
        if item.get('digest'):
            if item['digest']!='sha256:'+digest(path): raise ValueError('发布附件校验失败，保持草稿')
        else:
            with tempfile.TemporaryDirectory() as tmp:
                gh('release','download',tag,'--repo',repo,'--pattern',path.name,'--dir',tmp)
                if digest(Path(tmp)/path.name)!=digest(path): raise ValueError('发布附件下载校验失败，保持草稿')
    gh('release','edit',tag,'--repo',repo,'--draft=false','--latest='+str(latest).lower())
    print(json.dumps({'version':version,'private':metadata['private'],'url':f'https://github.com/{repo}/releases/tag/{tag}','assets':[p.name for p in assets]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish',action='store_true');parser.add_argument('--repo',default='AlancoSage/StarBridge')
    parser.add_argument('--commit');parser.add_argument('--notes',type=Path);parser.add_argument('--historical',action='store_true')
    args=parser.parse_args();version,assets=build()
    if args.publish:
        commit=args.commit or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        notes=args.notes or ROOT/f'releases/v{version}.md'
        if not notes.is_file(): parser.error('请提供本版本发布说明')
        publish(version,assets,args.repo,commit,notes.read_text(encoding='utf-8'),latest=not args.historical)
    else: print(json.dumps({'version':version,'assets':[str(p) for p in assets]}))


if __name__=='__main__': main()
