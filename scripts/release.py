"""Build and publish complete private Releases; never replace published versions."""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


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


def build(root=ROOT):
    version = code_version((root/'starbridge/__init__.py').read_text(encoding='utf-8-sig'))
    dist = root/'dist'; dist.mkdir(exist_ok=True)
    # Require the matching bridge build, instead of silently publishing an incomplete ZIP.
    import xml.etree.ElementTree as ET
    bridge_version = ET.parse(root/'bridge/pom.xml').getroot().find('{http://maven.apache.org/POM/4.0.0}version').text
    bridge = root/f'bridge/target/StarBridge-{bridge_version}.jar'
    if not bridge.is_file(): raise ValueError('请先构建 Minecraft 端 JAR：bridge/build.ps1 或 mvn package')
    with zipfile.ZipFile(bridge) as archive:
        if not re.search(r'^version:\s*[\'"]?' + re.escape(bridge_version) + r'[\'"]?\s*$', archive.read('plugin.yml').decode('utf-8'), re.M):
            raise ValueError('游戏 JAR 版本与源码不一致')
    website = dist/'StarBridge-website.zip'
    subprocess.run([sys.executable,str(root/'starbridge-website/build.py'),'--output',str(website)],check=True,cwd=root)
    # 0.5.x predates the supervised update protocol and is deliberately marked manual.
    automatic = (root/'scripts/update_runtime.py').is_file()
    bot = dist/f'StarBridge-{"Windows" if automatic else "Bot"}-{version}.zip'
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
    # Forge became available in 0.6.2; historical releases keep their original assets.
    if (root/'bridge-forge/gradle.properties').is_file():
        match = re.search(r'^mod_version=(\d+\.\d+\.\d+)\s*$', (root/'bridge-forge/gradle.properties').read_text(encoding='utf-8'), re.M)
        if not match: raise ValueError('Forge 版本缺失')
        forge_version = match.group(1)
        forge = root/f'bridge/target/StarBridge-Forge-1.20.1-{forge_version}.jar'
        if not forge.is_file(): raise ValueError('请先构建 Forge 模组：bridge-forge/build.ps1')
        with zipfile.ZipFile(forge) as archive:
            metadata = archive.read('META-INF/mods.toml').decode('utf-8')
            if f'version="{forge_version}"' not in metadata: raise ValueError('Forge JAR 版本与源码不一致')
        assets.append(forge)
    checksums = dist/'SHA256SUMS.txt'
    checksums.write_text(''.join(f'{digest(p)}  {p.name}\n' for p in assets),encoding='utf-8')
    return version,[*assets,checksums]


def publish(version,assets,repo,commit,notes,latest=True):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repo) or not re.fullmatch(r'[0-9a-f]{40}',commit): raise ValueError('仓库名或提交 SHA 错误')
    metadata = json.loads(gh('api','repos/'+repo).stdout)
    if not metadata.get('private'): raise ValueError('发布目标必须保持为私有仓库')
    source = json.loads(gh('api',f'repos/{repo}/contents/starbridge/__init__.py?ref={commit}').stdout)
    if code_version(base64.b64decode(source['content']).decode('utf-8-sig')) != version: raise ValueError('远程提交版本与发布包不一致')
    tag = 'v'+version
    existing = gh('api',f'repos/{repo}/releases/tags/{tag}',check=False)
    if existing.returncode == 0:
        release = json.loads(existing.stdout)
        if not release.get('draft'): raise ValueError('该版本已正式发布，不能覆盖；请增加版本号')
    else:
        payload = {'tag_name':tag,'target_commitish':commit,'name':'StarBridge '+version,'body':notes,'draft':True,'prerelease':False,'make_latest':'false'}
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
    print(json.dumps({'version':version,'private':True,'url':f'https://github.com/{repo}/releases/tag/{tag}','assets':[p.name for p in assets]}))


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
