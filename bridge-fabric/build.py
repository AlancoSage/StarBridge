"""Build server-only Fabric adapters with pinned APIs and verified native bindings."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from bindings import native_bindings, read_specification

ROOT = Path(__file__).resolve().parent
VERSION = '0.1.0'
LOADER = '0.16.14'
NEW_LOADER = '0.19.5'
VERSIONS = {'1.16.5': 8, '1.18.2': 17, '1.19.2': 17, '1.20.1': 17, '1.21.1': 21,
            '1.21.8': 21, '1.21.11': 21, '26.1': 25, '26.2': 25, '26.3': 25}
YARN = {
    '1.16.5': ('10', '9a7263629e5870f2788cc947f932b3d8d8606c29145babe1377b4c49796da615'),
    '1.18.2': ('4', '707f6efcfa69446817a532fe5f90011bdcd991f3827978d04184e39c23a3774b'),
    '1.19.2': ('28', '116df44bc49704d9e0ac8f4e99eb0f7ae5550c6041ff7f2915461e776283301f'),
    '1.20.1': ('10', '5444b470f35b892862908bb27314c0b5b325369fd60896d8d809e635d5371bea'),
    '1.21.1': ('3', '4ec570889585cb958b7d3c9dd94ce4064b16ab797dffec152bc8486c59a4010b'),
    '1.21.8': ('1', 'af0be370862072ba1b2f30aed5473e52ae2e0f232d89090741319553895a6043'),
    '1.21.11': ('6', 'e8112359716235dc4fd7f0bd4a6162fd728e0d1067d9fa02f289edaaccd37718'),
}
DEPENDENCIES = {
    'fabric-loader-0.16.14.jar': ('https://maven.fabricmc.net/net/fabricmc/fabric-loader/0.16.14/fabric-loader-0.16.14.jar', '9ed7b7f4197153ad97d71b4b9cd9148989e8f0c600934b035ce45f3ef003efc0'),
    'sponge-mixin-0.15.5+mixin.0.8.7.jar': ('https://maven.fabricmc.net/net/fabricmc/sponge-mixin/0.15.5+mixin.0.8.7/sponge-mixin-0.15.5+mixin.0.8.7.jar', '01dd2b778ed5283bce6b6b07d9690d86d956b17a7103efafad47073db1599584'),
    'asm-9.8.jar': ('https://maven.fabricmc.net/org/ow2/asm/asm/9.8/asm-9.8.jar', '876eab6a83daecad5ca67eb9fcabb063c97b5aeb8cf1fca7a989ecde17522051'),
    'asm-analysis-9.8.jar': ('https://maven.fabricmc.net/org/ow2/asm/asm-analysis/9.8/asm-analysis-9.8.jar', 'e640732fbcd3c6271925a504f125e38384688f4dfbbf92c8622dfcee0d09edb9'),
    'asm-commons-9.8.jar': ('https://maven.fabricmc.net/org/ow2/asm/asm-commons/9.8/asm-commons-9.8.jar', '3301a1c1cb4c59fcc5292648dac1d7c5aed4c0f067dfbe88873b8cdfe77404f4'),
    'asm-tree-9.8.jar': ('https://maven.fabricmc.net/org/ow2/asm/asm-tree/9.8/asm-tree-9.8.jar', '14b7880cb7c85eed101e2710432fc3ffb83275532a6a894dc4c4095d49ad59f1'),
    'asm-util-9.8.jar': ('https://maven.fabricmc.net/org/ow2/asm/asm-util/9.8/asm-util-9.8.jar', '8ba0460ecb28fd0e2980e5f3ef3433a513a457bc077f81a53bdc75b587a08d15'),
    'gson.jar': ('https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.2.4/gson-2.2.4.jar', 'c0328cd07ca9e363a5acd00c1cf4afe8cf554bd6d373834981ba05cebec687fb'),
    'netty.jar': ('https://repo.maven.apache.org/maven2/io/netty/netty-all/4.0.23.Final/netty-all-4.0.23.Final.jar', '50510e9c9874b539b98ef931fe7eeeb002f6b5b1976ea37669b9493426294561'),
    'brigadier-1.0.18.jar': ('https://libraries.minecraft.net/com/mojang/brigadier/1.0.18/brigadier-1.0.18.jar', 'edc4926aa4b49010f6e7ac46efd623fb38f9517344d26f6251d79a26a9738c0b'),
}
SHARED_SOURCES = ('BridgeEngine', 'GameHost', 'BridgeConfig', 'BridgeHttp', 'Protocol', 'Jsons')


def license_entries(root):
    """Keep release notices in new JARs; older source trees may omit them."""
    return {'META-INF/licenses/StarBridge/' + name: (root / name).read_bytes()
            for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md')
            if (root / name).is_file()}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(name, url, expected, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache/name
    if path.is_file() and sha256(path) == expected:
        return path
    for directory in (ROOT.parent/'.tools/fabric', ROOT.parent/'.tools/fabric-new', ROOT.parent/'.tools/legacy-mods', ROOT.parent/'bridge-mods/build/dependencies'):
        source = directory/name
        if source.is_file() and sha256(source) == expected:
            shutil.copyfile(source, path)
            return path
    temporary = path.with_suffix('.download')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'StarBridge-Fabric-Builder/0.1'})
        with urllib.request.urlopen(request, timeout=120) as response:
            temporary.write_bytes(response.read())
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        subprocess.run(['curl.exe' if os.name == 'nt' else 'curl', '--fail', '--location', '--max-time', '120', url, '--output', str(temporary)], check=True)
    if sha256(temporary) != expected:
        raise ValueError(f'Official dependency checksum mismatch: {name}')
    temporary.replace(path)
    return path


def mappings(mc, jar):
    with zipfile.ZipFile(jar) as archive:
        tiny = archive.read('mappings/mappings.tiny').decode('utf-8')
    lines = tiny.splitlines()
    if lines[0] != 'tiny\t2\t0\tintermediary\tnamed':
        raise ValueError('Yarn must use intermediary/named Tiny v2 namespaces')
    classes, methods, fields = {}, [], []
    owner = None
    for line in lines[1:]:
        row = line.split('\t')
        if row[0] == 'c':
            owner = row[2].replace('/', '.')
            classes[owner] = row[1].replace('/', '.')
        elif len(row) >= 5 and row[0] == '' and row[1] in ('m', 'f'):
            if owner is None:
                raise ValueError('Yarn member without an owner')
            target = methods if row[1] == 'm' else fields
            target.append({'owner': owner, 'name': row[4], 'intermediary': row[3], 'descriptor': row[2]})
    if mc in ('1.21.1', '1.21.8', '1.21.11'):
        # Java record canonical constructors are not always named by Tiny v2.
        for name, descriptor in (
            ('CommandExecutionC2SPacket', '(Ljava/lang/String;)V'),
            ('ChatCommandSignedC2SPacket', '(Ljava/lang/String;Ljava/time/Instant;JLnet/minecraft/class_7450;Lnet/minecraft/class_7635$class_7636;)V')):
            owner = 'net.minecraft.network.packet.c2s.play.' + name
            if owner not in classes:
                raise ValueError('Required command packet absent from exact Yarn bindings')
            if not any(row['owner'] == owner and row['name'] == '<init>' and row['descriptor'] == descriptor for row in methods):
                methods.append({'owner': owner, 'name': '<init>', 'intermediary': '<init>', 'descriptor': descriptor})
    return {'mcVersion': mc, 'classes': classes, 'methods': methods, 'fields': fields,
            'packets': {name: intermediary for name, intermediary in classes.items()
                        if name.startswith(('net.minecraft.network.packet.c2s.play.', 'net.minecraft.network.packet.c2s.common.'))}}


def member(document, owner, name, descriptor=None):
    rows = [row for row in document['methods'] if row['owner'] == owner and row['name'] == name
            and (descriptor is None or row['descriptor'] == descriptor)]
    if len(rows) != 1:
        raise ValueError(f'Exact native mixin target unavailable or ambiguous: {owner}#{name}')
    return rows[0]['intermediary'] + rows[0]['descriptor']


def mixin_sources(document):
    classes = document['classes']
    header = ('package cn.starbridge.fabric.mixin;\n'
              'import org.spongepowered.asm.mixin.Mixin;\n'
              'import org.spongepowered.asm.mixin.injection.*;\n'
              'import org.spongepowered.asm.mixin.injection.callback.*;\n'
              'import cn.starbridge.fabric.FabricRuntime;\n'
              'import cn.starbridge.fabric.FabricPacketGate;\n')
    def wrap(owner, name, body):
        return header + '@Mixin(targets="' + classes[owner] + '", remap=false)\npublic abstract class ' + name + ' {\n' + body + '}\n'
    def inject(target, position, parameters, body, *, cancellable=False):
        return (' @Inject(method="' + target + '", at=@At("' + position + '"), remap=false, require=1'
                + (', cancellable=true' if cancellable else '') + ')\n private void starbridge$'
                + ('hook' + hashlib.sha256((target + position).encode()).hexdigest()[:12])
                + '(' + parameters + ') { ' + body + ' }\n')
    server = 'net.minecraft.server.MinecraftServer'
    connection = 'net.minecraft.network.ClientConnection'
    entity = 'net.minecraft.entity.Entity'
    manager = 'net.minecraft.server.command.CommandManager'
    result = {}
    result['ServerMixin'] = wrap(server, 'ServerMixin',
        inject(member(document, server, 'tick', '(Ljava/util/function/BooleanSupplier;)V'), 'HEAD', 'CallbackInfo callback', 'FabricRuntime.tick(this);')
        + inject(member(document, server, 'shutdown', '()V'), 'HEAD', 'CallbackInfo callback', 'FabricRuntime.shutdown(this);'))
    descriptor = '(Lio/netty/channel/ChannelHandlerContext;)V'
    def channel_method(name):
        # 1.16 Yarn omits these unmapped Netty overrides; their native names are external API names.
        return name + descriptor if document['mcVersion'] == '1.16.5' else member(document, connection, name, descriptor)
    result['ConnectionMixin'] = wrap(connection, 'ConnectionMixin',
        inject(channel_method('channelActive'), 'TAIL', 'io.netty.channel.ChannelHandlerContext ctx, CallbackInfo callback', 'FabricPacketGate.install(this, ctx);')
        + inject(channel_method('channelInactive'), 'HEAD', 'io.netty.channel.ChannelHandlerContext ctx, CallbackInfo callback', 'FabricPacketGate.remove(this, ctx);'))
    result['CommandsMixin'] = wrap(manager, 'CommandsMixin',
        inject(member(document, manager, '<init>'), 'TAIL', 'CallbackInfo callback', 'FabricRuntime.registerCommands(this);'))
    if document['mcVersion'] in ('1.16.5', '1.18.2'):
        execution = member(document, manager, 'execute', '(Lnet/minecraft/class_2168;Ljava/lang/String;)I')
        arguments = '@Coerce Object source, String command, CallbackInfoReturnable<Integer> callback'
        check = 'if (!FabricRuntime.allowCommand(source)) callback.setReturnValue(Integer.valueOf(0));'
    else:
        result_type = 'I' if document['mcVersion'] in ('1.19.2', '1.20.1') else 'V'
        execution = member(document, manager, 'execute', '(Lcom/mojang/brigadier/ParseResults;Ljava/lang/String;)' + result_type)
        callback = 'CallbackInfo' if result_type == 'V' else 'CallbackInfoReturnable<Integer>'
        arguments = 'com.mojang.brigadier.ParseResults<?> results, String command, ' + callback + ' callback'
        check = ('if (!FabricRuntime.allowCommand(results.getContext().getSource())) '
                 + ('callback.cancel();' if result_type == 'V' else 'callback.setReturnValue(Integer.valueOf(0));'))
    result['CommandsExecuteMixin'] = wrap(manager, 'CommandsExecuteMixin',
        inject(execution, 'HEAD', arguments, check, cancellable=True))
    result['DamageMixin'] = wrap('net.minecraft.entity.LivingEntity', 'DamageMixin',
        inject(member(document, entity, 'damage'), 'HEAD', 'CallbackInfoReturnable<Boolean> callback',
               'if (FabricRuntime.lockedEntity(this)) callback.setReturnValue(Boolean.FALSE);', cancellable=True))
    result['PickupMixin'] = wrap('net.minecraft.entity.ItemEntity', 'PickupMixin',
        inject(member(document, entity, 'onPlayerCollision'), 'HEAD', '@Coerce Object player, CallbackInfo callback',
               'if (FabricRuntime.lockedEntity(player)) callback.cancel();', cancellable=True))
    player_manager = 'net.minecraft.server.PlayerManager'
    join = member(document, player_manager, 'onPlayerConnect')
    parameters = '@Coerce Object connection, @Coerce Object player, '
    if VERSIONS[document['mcVersion']] >= 21:
        parameters += '@Coerce Object data, '
    result['PlayerJoinMixin'] = wrap(player_manager, 'PlayerJoinMixin',
        inject(join, 'TAIL', parameters + 'CallbackInfo callback', 'FabricRuntime.join(player);'))
    if document['mcVersion'] not in ('1.16.5', '1.18.2'):
        signed_message = classes['net.minecraft.network.message.SignedMessage'].replace('.', '/')
        server_player = classes['net.minecraft.server.network.ServerPlayerEntity'].replace('.', '/')
        prefix = f'(L{signed_message};L{server_player};'
        choices = [row for row in document['methods'] if row['owner'] == player_manager
                   and row['name'] == 'broadcast' and row['descriptor'].startswith(prefix)]
        if len(choices) != 1:
            raise ValueError('Exact signed chat broadcast binding is missing or ambiguous')
        result['PlayerManagerChatMixin'] = wrap('net.minecraft.server.PlayerManager', 'PlayerManagerChatMixin',
            inject(member(document, player_manager, 'broadcast', choices[0]['descriptor']),
                   'HEAD', '@Coerce Object message, @Coerce Object player, @Coerce Object parameters, CallbackInfo callback',
                   'if (!FabricRuntime.allowChat(player, message)) callback.cancel();', cancellable=True))
    return result


def build(mc, jdk, cache):
    libraries = [fetch(name, url, digest, cache) for name, (url, digest) in DEPENDENCIES.items()]
    if mc in YARN:
        yarn_build, digest = YARN[mc]
        coordinate = f'{mc}+build.{yarn_build}'
        yarn = fetch(f'yarn-{mc}-v2.jar', f'https://maven.fabricmc.net/net/fabricmc/yarn/{coordinate}/yarn-{coordinate}-v2.jar', digest, cache)
        document = mappings(mc, yarn)
    else:
        specification = read_specification(ROOT/'bindings'/f'{mc}.json', mc)
        server = specification['server']
        bundled = fetch(f'server-{mc}.jar', server['url'], server['sha256'], cache)
        document = native_bindings(specification, bundled)
    generated = mixin_sources(document)
    directory = ROOT/'build'/mc
    directory.mkdir(parents=True, exist_ok=True)
    javac = jdk/'bin'/('javac.exe' if os.name == 'nt' else 'javac')
    if not javac.is_file():
        raise ValueError('Use a JDK 17 or newer --java-home to compile Java 8 bytecode')
    with tempfile.TemporaryDirectory(prefix='compile-', dir=directory) as temporary:
        staging = Path(temporary)
        output = staging/'classes'
        output.mkdir()
        sources = sorted((ROOT/'common/src/main/java').rglob('*.java'))
        shared = ROOT.parent/'bridge-mods/common/src/main/java/cn/starbridge/mods'
        sources += [shared/(name + '.java') for name in SHARED_SOURCES]
        for name, content in generated.items():
            path = staging/(name + '.java')
            path.write_text(content, encoding='utf-8')
            sources.append(path)
        subprocess.run([str(javac), '-J-Duser.language=en', '--release', '8', '-proc:none', '-encoding', 'UTF-8',
                        '-cp', os.pathsep.join(map(str, libraries)), '-d', str(output), *map(str, sources)], check=True)
        metadata = {'schemaVersion': 1, 'id': 'starbridge', 'version': VERSION, 'name': 'StarBridge', 'license': 'AGPL-3.0-or-later',
                    'description': 'Server-side StarBridge QQ and account integration.', 'environment': 'server',
                    'entrypoints': {'main': ['cn.starbridge.fabric.StarBridgeFabric']}, 'mixins': ['starbridge-fabric.mixins.json'],
                    'depends': {'fabricloader': '>=' + (LOADER if mc in ('1.16.5','1.18.2','1.19.2','1.20.1','1.21.1') else NEW_LOADER),
                                'minecraft': mc, 'java': '>=' + str(VERSIONS[mc])}}
        resources = {'fabric.mod.json': metadata,
                     'starbridge-fabric-mappings.json': document,
                     'starbridge-fabric.mixins.json': {'required': True, 'minVersion': '0.8', 'package': 'cn.starbridge.fabric.mixin',
                         'compatibilityLevel': 'JAVA_8', 'mixins': list(generated), 'injectors': {'defaultRequire': 1}}}
        target = ROOT.parent/'bridge/target'/f'StarBridge-Fabric-{mc}-{VERSION}.jar'
        target.parent.mkdir(parents=True, exist_ok=True)
        files = {path.relative_to(output).as_posix(): path.read_bytes() for path in sorted(output.rglob('*.class'))}
        for name, data in files.items():
            if data[:4] != b'\xca\xfe\xba\xbe' or int.from_bytes(data[6:8], 'big') != 52:
                raise ValueError(f'Fabric adapter must target Java 8: {name}')
        files.update({name: json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8') for name, data in resources.items()})
        files.update(license_entries(ROOT.parent))
        temporary_jar = target.with_suffix('.jar.building')
        with zipfile.ZipFile(temporary_jar, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        temporary_jar.replace(target)
    print(f'Built Fabric {mc}: {target.name}', flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', type=Path, default=Path(os.environ.get('JAVA_HOME', '')))
    parser.add_argument('--version', choices=VERSIONS, help='Omit to build all supported game versions.')
    parser.add_argument('--cache', type=Path, default=ROOT/'build/dependencies')
    args = parser.parse_args()
    for mc in [args.version] if args.version else VERSIONS:
        build(mc, args.java_home, args.cache)


if __name__ == '__main__':
    main()
