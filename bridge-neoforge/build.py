"""Build six server-only NeoForge adapters with pinned native declarations."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
FABRIC_ROOT = ROOT.parent / 'bridge-fabric'
VERSION = '0.1.0'
VERSIONS = {
    '1.20.4': ('20.4.251', 17),
    '1.21.4': ('21.4.158', 21),
    '1.21.8': ('21.8.54', 21),
    '1.21.11': ('21.11.45', 21),
    '26.1.2': ('26.1.2.114', 25),
    '26.2': ('26.2.0.88', 25),
}
LOADER_API = {
    '1.20.4': ('2.0.17', 'fdb7c4ffd3b03ce5dba32d453a5335630416b4c820ce54eada5cba96e36be625', 'cff49582bb17944fd30b4cd1272578fe2b6c9e7f79fdd92f1ac502b19ca436a3'),
    '1.21.4': ('6.0.18', '572929b4299529a32566071e2c3641cdcef9dcb0644441d58c6ded183276acac', '45b37b9f255b02e18c1ef9dc42ae5d4fb2a6a8c2b503b72c8cd1131f0e299143'),
    '1.21.8': ('9.0.18', '1528c2a0ee90ca236d7810aaa271386498366d8e53555ee0fd4fb259d267c4c8', '45b37b9f255b02e18c1ef9dc42ae5d4fb2a6a8c2b503b72c8cd1131f0e299143'),
    '1.21.11': ('10.0.36', '5711bb95b45b421ada6e5f0f4600ac441c3509446178da5de927135f8bd6b0c9', '285798e18a26bdb04f64c850bc6606a44b65e331fc8f40e5911a608a5470b0f1'),
    '26.1.2': ('11.0.15', 'dad0947efdfbc1b09f52c7779c86c3660ed6d385fd5c07b3b649332f6f75a429', 'a3935d67cb08085f42b642a80fd3a0056968c75116433cfd6209ff9e57692b18'),
    '26.2': ('11.0.16', '73a5cc860b452e80cf0a9789f32ae08a43be180221819b7d339b84391e1e5a97', 'a3935d67cb08085f42b642a80fd3a0056968c75116433cfd6209ff9e57692b18'),
}
CORE = ('Native', 'Host', 'Runtime', 'PacketGate')
MIXINS = ('ServerMixin', 'ConnectionMixin', 'CommandsMixin', 'CommandsExecuteMixin',
          'DamageMixin', 'PickupMixin', 'PlayerJoinMixin', 'PlayerManagerChatMixin')


def fabric_builder():
    """Reuse our existing generator, without changing Fabric's published adapter."""
    if str(FABRIC_ROOT) not in sys.path:
        sys.path.insert(0, str(FABRIC_ROOT))
    spec = importlib.util.spec_from_file_location('starbridge_fabric_builder', FABRIC_ROOT / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(name, url, expected, cache, helper):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if target.is_file() and digest(target) == expected:
        return target
    for directory in (ROOT.parent / '.tools/neoforge-new', ROOT.parent / '.tools/neoforge-new/loader-api',
                      FABRIC_ROOT / 'build/dependencies'):
        source = directory / name
        if source.is_file() and digest(source) == expected:
            shutil.copyfile(source, target)
            return target
    return helper.fetch(name, url, expected, cache)


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Shared adapter template changed; review NeoForge generation before building')
    return source.replace(old, new)


def rename(source):
    return source.replace('cn.starbridge.fabric', 'cn.starbridge.neoforge').replace(
        'starbridge-fabric', 'starbridge-neoforge').replace('Fabric', 'NeoForge')


def adapter_sources():
    """Keep the proven packet/session implementation in one reviewed source template."""
    result = {}
    source_root = FABRIC_ROOT / 'common/src/main/java/cn/starbridge/fabric'
    for name in CORE:
        source = (source_root / ('Fabric' + name + '.java')).read_text(encoding='utf-8')
        source = replace_once(source, 'import net.fabricmc.loader.api.FabricLoader;\n', '') if name != 'PacketGate' else source
        if name == 'Native':
            source = replace_once(source, 'import net.fabricmc.loader.api.MappingResolver;\n', '')
            source = replace_once(source, '    private final MappingResolver resolver;\n', '')
            source = replace_once(source, '        resolver=FabricLoader.getInstance().getMappingResolver();\n', '')
            source = replace_once(source, 'if(!namespace.equals("intermediary")&&!namespace.equals("official"))', 'if(!namespace.equals("official"))')
            source = replace_once(source, 'officialNamespace?binding:resolver.mapClassName("intermediary",binding)', 'binding')
            source = replace_once(source, 'officialNamespace?name:resolver.mapMethodName("intermediary",owner,name,descriptor)', 'name')
            source = replace_once(source, 'officialNamespace?name:resolver.mapFieldName("intermediary",owner,name,descriptor)', 'name')
        if name == 'Host':
            source = replace_once(source,
                'String loader=FabricLoader.getInstance().getModContainer("fabricloader").get().getMetadata().getVersion().getFriendlyString();',
                'String loader=FabricRuntime.loaderVersion();')
        if name == 'Runtime':
            source = replace_once(source, '    private FabricRuntime(){}', '''    private FabricRuntime(){}
    public static String loaderVersion() {
        String owner=version.equals("1.20.4")||version.equals("1.21.4")||version.equals("1.21.8")
            ? "net.neoforged.neoforge.internal.versions.neoforge.NeoForgeVersion"
            : "net.neoforged.neoforge.common.NeoForgeVersion";
        return (String)nativeApi.direct(null,owner,"getVersion","()Ljava/lang/String;");
    }''')
        source = rename(source)
        if any(word in source for word in ('net.fabricmc', 'MappingResolver', 'FabricLoader', 'starbridge-fabric')):
            raise ValueError('NeoForge must not link against Fabric Loader')
        result['NeoForge' + name] = source
    result['StarBridgeNeoForge'] = '''package cn.starbridge.neoforge;
import net.neoforged.fml.common.Mod;
/** Server-only entry; no registries, payload channels or client classes. */
@Mod("starbridge")
public final class StarBridgeNeoForge {
    public StarBridgeNeoForge() { NeoForgeRuntime.initialize(); }
}
'''
    return result


def mixin_sources(document, helper):
    """Join arity follows the exact descriptor, including Java17 Minecraft1.20.4."""
    mc = document['mcVersion']
    target = helper.member(document, 'net.minecraft.server.PlayerManager', 'onPlayerConnect')
    parameters = re.findall(r'\[*L[^;]+;|\[*[ZBCSIJFD]', target.split('(', 1)[1].split(')', 1)[0])
    if len(parameters) not in (2, 3):
        raise ValueError('Native player join declaration has unsupported arity')
    helper.VERSIONS = {**helper.VERSIONS, mc: 21 if len(parameters) == 3 else 17}
    generated = {name: rename(source) for name, source in helper.mixin_sources(document).items()}
    if set(generated) != set(MIXINS):
        raise ValueError('Native NeoForge requires every lifecycle and authentication hook')
    return generated


def annotation_stub(mc, cache, helper):
    """Verify the official annotation; compile its used surface without shipping it."""
    from classfile import declarations
    version, expected, annotation_digest = LOADER_API[mc]
    filename = 'loader-' + version + '.jar'
    url = 'https://maven.neoforged.net/releases/net/neoforged/fancymodloader/loader/' + version + '/' + filename
    path = fetch(filename, url, expected, cache, helper)
    with zipfile.ZipFile(path) as archive:
        data = archive.read('net/neoforged/fml/common/Mod.class')
    declaration = declarations(data)
    if (hashlib.sha256(data).hexdigest() != annotation_digest
        or declaration['name'] != 'net.neoforged.fml.common.Mod'
        or not declaration['access'] & 0x2000
        or sum(row['name'] == 'value' and row['descriptor'] == '()Ljava/lang/String;' for row in declaration['methods']) != 1):
        raise ValueError('Official NeoForge Mod annotation API changed')
    return '''package net.neoforged.fml.common;
import java.lang.annotation.*;
@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.TYPE)
public @interface Mod { String value(); }
'''


def mod_metadata(mc):
    loader, java = VERSIONS[mc]
    dependency_flag = 'mandatory=true' if mc == '1.20.4' else 'type="required"'
    return f'''modLoader="javafml"
loaderVersion="[1,)"
license="All Rights Reserved"
[[mods]]
modId="starbridge"
version="{VERSION}"
displayName="星桥 · NeoForge 游戏桥接"
authors="AlancoSage"
displayTest="IGNORE_SERVER_VERSION"
description=''' + "'''星桥服务端桥接：QQ 联动、玩家管理、白名单、密码登录及 QQ 确认。'''\n" + f'''[[dependencies.starbridge]]
modId="neoforge"
{dependency_flag}
versionRange="[{loader},)"
ordering="NONE"
side="SERVER"
[[dependencies.starbridge]]
modId="minecraft"
{dependency_flag}
versionRange="[{mc}]"
ordering="NONE"
side="SERVER"
[features.starbridge]
javaVersion="[{java},)"
[[mixins]]
config="starbridge-neoforge.mixins.json"
'''


def build(mc, jdk, cache):
    helper = fabric_builder()
    from native_bindings import native_bindings, read_specification
    specification = read_specification(ROOT / 'bindings' / (mc + '.json'), mc)
    server = specification['server']
    bundled = fetch('server-' + mc + '.jar', server['url'], server['sha256'], cache, helper)
    mapping = None
    if 'mappings' in specification:
        info = specification['mappings']
        mapping = fetch('server-' + mc + '-mappings.txt', info['url'], info['sha256'], cache, helper)
    document = native_bindings(specification, bundled, mapping)
    document['neoForgeVersion'] = VERSIONS[mc][0]
    generated = mixin_sources(document, helper)
    javac = jdk / 'bin' / ('javac.exe' if os.name == 'nt' else 'javac')
    if not javac.is_file():
        raise ValueError('Use --java-home with a JDK17 or newer compiler')
    libraries = [fetch(name, url, expected, cache, helper) for name, (url, expected) in helper.DEPENDENCIES.items()
                 if not name.startswith('fabric-loader')]
    stub = annotation_stub(mc, cache, helper)
    directory = ROOT / 'build' / mc
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='compile-', dir=directory) as temporary:
        staging = Path(temporary)
        output = staging / 'classes'
        output.mkdir()
        sources = []
        for name, content in {**adapter_sources(), **generated, 'Mod': stub}.items():
            path = staging / (name + '.java')
            path.write_text(content, encoding='utf-8')
            sources.append(path)
        shared = ROOT.parent / 'bridge-mods/common/src/main/java/cn/starbridge/mods'
        sources += [shared / (name + '.java') for name in helper.SHARED_SOURCES]
        subprocess.run([str(javac), '-J-Duser.language=en', '--release', '8', '-proc:none', '-encoding', 'UTF-8',
                        '-cp', os.pathsep.join(map(str, libraries)), '-d', str(output), *map(str, sources)], check=True)
        files = {path.relative_to(output).as_posix(): path.read_bytes() for path in sorted(output.rglob('*.class'))
                 if path.relative_to(output).as_posix().startswith('cn/starbridge/')}
        for name, data in files.items():
            if data[:4] != b'\xca\xfe\xba\xbe' or int.from_bytes(data[6:8], 'big') != 52:
                raise ValueError('NeoForge adapter must target Java8: ' + name)
            if b'net/fabricmc/' in data:
                raise ValueError('NeoForge adapter must not reference Fabric Loader: ' + name)
        files['META-INF/MANIFEST.MF'] = b'Manifest-Version: 1.0\r\nFMLModType: MOD\r\n\r\n'
        metadata_name = 'mods.toml' if mc == '1.20.4' else 'neoforge.mods.toml'
        files['META-INF/' + metadata_name] = mod_metadata(mc).encode('utf-8')
        resources = {'starbridge-neoforge-mappings.json': document,
                     'starbridge-neoforge.mixins.json': {'required': True, 'minVersion': '0.8',
                         'package': 'cn.starbridge.neoforge.mixin', 'compatibilityLevel': 'JAVA_8',
                         'mixins': list(generated), 'injectors': {'defaultRequire': 1}}}
        files.update({name: json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
                      for name, data in resources.items()})
        target = ROOT.parent / 'bridge/target' / f'StarBridge-NeoForge-{mc}-{VERSION}.jar'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_jar = target.with_suffix('.jar.building')
        with zipfile.ZipFile(temporary_jar, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        temporary_jar.replace(target)
    print('Built NeoForge ' + mc + ': ' + target.name, flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', type=Path, default=Path(os.environ.get('JAVA_HOME', '')))
    parser.add_argument('--version', choices=VERSIONS, help='Omit to build all six new versions; 1.21.1 keeps its Gradle build.')
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/dependencies')
    args = parser.parse_args()
    for mc in [args.version] if args.version else VERSIONS:
        build(mc, args.java_home, args.cache)


if __name__ == '__main__':
    main()
