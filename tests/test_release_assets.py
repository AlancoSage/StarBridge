"""Reject mismatched game-end artifacts before a private release can be published."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import release
from scripts.release import FABRIC_CORE, FABRIC_MIXINS, NEOFORGE_CORE, NEOFORGE_MIXINS, native_assets, native_filename, validate_native_mod
from starbridge.game_bridges import GAME_BRIDGES


class NativeReleaseAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'starbridge').mkdir()
        (self.root/'bridge/target').mkdir(parents=True)
        (self.root/'starbridge/__init__.py').write_text('__version__="0.6.7"\n__forge_version__="0.1.0"\n', encoding='utf-8')

    def artifact(self, item, *, override=None, binding_override=None, missing_core=False, missing_resource=False,
                 missing_mixin=False, mixin_override=None, metadata_transform=None, major=None, prefix='StarBridge'):
        path = self.root/'bridge/target'/native_filename(item, '0.1.0', prefix)
        legacy = item['platform'] == 'forge' and item['version'] in ('1.7.10', '1.12.2', '1.16.5')
        core = ['cn/starbridge/mods/BridgeEngine.class', 'cn/starbridge/mods/LegacyMod.class'] if legacy else [
            'cn/starbridge/forge/StarBridge.class', 'cn/starbridge/forge/GameLogin.class']
        if item['platform'] == 'fabric':
            metadata = {'id': 'starbridge', 'version': '0.1.0', 'environment': 'server', 'depends': {'minecraft': item['version'], 'java': '>=' + str(item['java'])},
                        'entrypoints': {'main': ['cn.starbridge.fabric.StarBridgeFabric']}, 'mixins': ['starbridge-fabric.mixins.json']}
            if item.get('loader_version'):
                metadata['depends']['fabricloader'] = '>=' + item['loader_version']
            metadata.update(override or {})
            name, content = 'fabric.mod.json', json.dumps(metadata)
            mixins = list(FABRIC_MIXINS)
            if item['version'] not in ('1.16.5', '1.18.2'):
                mixins.append('PlayerManagerChatMixin')
            core = list(FABRIC_CORE) + ['cn/starbridge/fabric/mixin/' + name + '.class' for name in mixins]
        elif item['platform'] == 'neoforge' and item.get('config') == 'properties':
            name = 'META-INF/' + ('mods.toml' if item['version'] == '1.20.4' else 'neoforge.mods.toml')
            required = 'mandatory=true' if item['version'] == '1.20.4' else 'type="required"'
            content = ('modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="starbridge"\nversion="0.1.0"\n'
                       f'[features.starbridge]\njavaVersion="[{item["java"]},)"\n'
                       f'[[dependencies.starbridge]]\nmodId="minecraft"\n{required}\nversionRange="[{item["version"]}]"\nside="SERVER"\n'
                       f'[[dependencies.starbridge]]\nmodId="neoforge"\n{required}\nversionRange="[{item["loader_version"]},)"\nside="SERVER"\n'
                       '[[mixins]]\nconfig="starbridge-neoforge.mixins.json"\n')
            mixins = list(NEOFORGE_MIXINS)
            core = list(NEOFORGE_CORE) + ['cn/starbridge/neoforge/mixin/' + name + '.class' for name in mixins]
        elif item['version'] in ('1.7.10', '1.12.2'):
            name = 'mcmod.info'
            content = json.dumps([{'modid': 'starbridge', 'version': '0.1.0', 'mcversion': item['version']}])
        else:
            name = 'META-INF/' + ('neoforge.mods.toml' if item['platform'] == 'neoforge' else 'mods.toml')
            content = f'[[mods]]\nmodId="starbridge"\nversion="0.1.0"\n[[dependencies.starbridge]]\nmodId="minecraft"\nversionRange="[{item["version"]}]"\n'
        if metadata_transform:
            content = metadata_transform(content)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(name, content)
            if (item['platform'] == 'fabric' or item['platform'] == 'neoforge' and item.get('config') == 'properties') and not missing_resource:
                platform = item['platform']
                config = {'required': not missing_mixin, 'package': f'cn.starbridge.{platform}.mixin',
                          'mixins': mixins, 'injectors': {'defaultRequire': 1}}
                config.update(mixin_override or {})
                archive.writestr(f'starbridge-{platform}.mixins.json', json.dumps(config))
                bindings = {'mcVersion': item['version']}
                if item['version'].startswith('26.') or platform == 'neoforge':
                    bindings['namespace'] = 'official'
                if platform == 'neoforge':
                    bindings['neoForgeVersion'] = item['loader_version']
                bindings.update(binding_override or {})
                archive.writestr(f'starbridge-{platform}-mappings.json', json.dumps(bindings))
            for class_name in core[1:] if missing_core else core:
                archive.writestr(class_name, b'\xca\xfe\xba\xbe\x00\x00' + (major or item['java'] + 44).to_bytes(2, 'big'))
        return path

    def catalog(self, items):
        (self.root/'starbridge/game_bridges.py').write_text('GAME_BRIDGES = '+repr(tuple(items)), encoding='utf-8')

    def test_all_twenty_four_native_assets_are_required_with_distinct_loader_names(self):
        self.catalog(GAME_BRIDGES)
        for item in GAME_BRIDGES:
            self.artifact(item)
        assets = native_assets(self.root)
        self.assertEqual(len(assets), 24)
        self.assertEqual(len(set(path.name for path in assets)), 24)
        self.assertEqual({path.name for path in assets if path.name.startswith('StarBridge-Fabric-')}, {
            f'StarBridge-Fabric-{version}-0.1.0.jar' for version in ('1.16.5', '1.18.2', '1.19.2', '1.20.1', '1.21.1', '1.21.8', '1.21.11', '26.1', '26.2', '26.3')})
        self.assertEqual({path.name for path in assets if path.name.startswith('StarBridge-NeoForge-')}, {
            f'StarBridge-NeoForge-{version}-0.1.0.jar' for version in ('1.20.4', '1.20.6', '1.21.1', '1.21.4', '1.21.8', '1.21.11', '26.1.2', '26.2')})
        (self.root/'bridge/target/StarBridge-Fabric-26.3-0.1.0.jar').unlink()
        with self.assertRaisesRegex(ValueError, '缺少游戏端构建'):
            native_assets(self.root)

    def test_fabric_rejects_wrong_identity_version_side_and_minecraft_range(self):
        item = {'platform': 'fabric', 'version': '1.20.1', 'java': 17}
        for override in ({'id': 'other'}, {'version': '0.0.9'}, {'environment': '*'}, {'environment': 'client'},
                         {'depends': {'minecraft': '>=1.20'}}, {'depends': {'minecraft': ['1.20.1']}},
                         {'depends': {'minecraft': '1.19.2'}}, {'depends': None}, {'entrypoints': {}}, {'mixins': []}):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, '元数据不一致'):
                    validate_native_mod(self.artifact(item, override=override), item, '0.1.0')

    def test_fabric_requires_engine_and_a_compatible_class_version(self):
        item = {'platform': 'fabric', 'version': '1.16.5', 'java': 8}
        with self.assertRaisesRegex(ValueError, '缺少核心类'):
            validate_native_mod(self.artifact(item, missing_core=True), item, '0.1.0')
        with self.assertRaisesRegex(ValueError, '缺少必要资源'):
            validate_native_mod(self.artifact(item, missing_resource=True), item, '0.1.0')
        with self.assertRaisesRegex(ValueError, '登录保护注入不完整'):
            validate_native_mod(self.artifact(item, missing_mixin=True), item, '0.1.0')
        with self.assertRaisesRegex(ValueError, 'Java 要求不一致'):
            validate_native_mod(self.artifact(item, major=61), item, '0.1.0')
        validate_native_mod(self.artifact(item, major=52), item, '0.1.0')

    def test_fabric_26_requires_official_names_and_preserves_java_25_limit(self):
        item = {'platform': 'fabric', 'version': '26.3', 'java': 25}
        validate_native_mod(self.artifact(item, major=52), item, '0.1.0')
        validate_native_mod(self.artifact(item, major=69), item, '0.1.0')
        with self.assertRaisesRegex(ValueError, 'Java 要求不一致'):
            validate_native_mod(self.artifact(item, major=70), item, '0.1.0')
        with self.assertRaisesRegex(ValueError, '命名空间不一致'):
            validate_native_mod(self.artifact(item, binding_override={'namespace': 'intermediary'}), item, '0.1.0')
        item = {'platform': 'fabric', 'version': '1.21.11', 'java': 21}
        with self.assertRaisesRegex(ValueError, '命名空间不一致'):
            validate_native_mod(self.artifact(item, binding_override={'namespace': 'official'}), item, '0.1.0')

    def test_fabric_loader_and_java_dependencies_match_panel_requirements(self):
        item = {'platform': 'fabric', 'version': '26.3', 'java': 25, 'loader_version': '0.19.5'}
        validate_native_mod(self.artifact(item), item, '0.1.0')
        for dependencies in ({'minecraft': '26.3', 'java': '>=21', 'fabricloader': '>=0.19.5'},
                             {'minecraft': '26.3', 'java': '>=25', 'fabricloader': '>=0.16.14'}):
            with self.subTest(dependencies=dependencies):
                with self.assertRaisesRegex(ValueError, '元数据不一致'):
                    validate_native_mod(self.artifact(item, override={'depends': dependencies}), item, '0.1.0')

    def test_neoforge_requires_exact_game_loader_java_and_server_side_metadata(self):
        for version in ('1.20.4', '1.20.6', '26.2'):
            item = next(item for item in GAME_BRIDGES if item['platform'] == 'neoforge' and item['version'] == version)
            validate_native_mod(self.artifact(item), item, '0.1.0')
            replacements = (
                ('modId="starbridge"', 'modId="other"'), ('version="0.1.0"', 'version="0.0.9"'),
                ('modLoader="javafml"', 'modLoader="other"'), ('loaderVersion="[1,)"', 'loaderVersion="[2,)"'),
                (f'javaVersion="[{item["java"]},)"', 'javaVersion="[8,)"'),
                (f'versionRange="[{version}]"', f'versionRange="[{version},)"'),
                (f'versionRange="[{item["loader_version"]},)"', 'versionRange="[0,)"'),
                ('side="SERVER"', 'side="BOTH"'),
                ('mandatory=true', 'mandatory=false') if version == '1.20.4' else ('type="required"', 'type="optional"'),
                ('config="starbridge-neoforge.mixins.json"', 'config="other.mixins.json"'),
            )
            for old, new in replacements:
                with self.subTest(version=version, change=(old, new)):
                    with self.assertRaisesRegex(ValueError, '元数据不一致'):
                        validate_native_mod(self.artifact(item, metadata_transform=lambda text: text.replace(old, new)), item, '0.1.0')

    def test_neoforge_requires_all_login_guards_and_official_version_bindings(self):
        item = next(item for item in GAME_BRIDGES if item['platform'] == 'neoforge' and item['version'] == '1.21.11')
        for kwargs, message in (({'missing_core': True}, '缺少核心类'),
                                ({'missing_resource': True}, '缺少必要资源'),
                                ({'missing_mixin': True}, '登录保护注入不完整'),
                                ({'mixin_override': {'injectors': {'defaultRequire': 0}}}, '登录保护注入不完整'),
                                ({'mixin_override': {'mixins': list(NEOFORGE_MIXINS[:-1])}}, '登录保护注入不完整'),
                                ({'binding_override': {'namespace': 'intermediary'}}, '命名空间不一致'),
                                ({'binding_override': {'mcVersion': '1.21.8'}}, '映射版本不一致'),
                                ({'binding_override': {'neoForgeVersion': '21.11.1'}}, '映射版本不一致'),
                                ({'major': 69}, 'Java 要求不一致')):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, message):
                    validate_native_mod(self.artifact(item, **kwargs), item, '0.1.0')
        item = next(item for item in GAME_BRIDGES if item['platform'] == 'neoforge' and item['version'] == '26.2')
        validate_native_mod(self.artifact(item, major=52), item, '0.1.0')
        validate_native_mod(self.artifact(item, major=69), item, '0.1.0')
        with self.assertRaisesRegex(ValueError, 'Java 要求不一致'):
            validate_native_mod(self.artifact(item, major=70), item, '0.1.0')

    def test_064_source_catalog_requires_only_its_twelve_native_assets(self):
        versions = ('1.16.5', '1.18.2', '1.19.2', '1.20.1', '1.21.1')
        historical = tuple(item for item in GAME_BRIDGES
                           if (item['platform'] != 'fabric' or item['version'] in versions)
                           and (item['platform'] != 'neoforge' or item['version'] == '1.21.1'))
        self.catalog(historical)
        (self.root/'starbridge/__init__.py').write_text('__version__="0.6.4"\n__forge_version__="0.1.0"\n', encoding='utf-8')
        for item in historical:
            self.artifact(item)
        self.assertEqual(len(native_assets(self.root)), 12)

    def test_065_source_catalog_requires_only_its_seventeen_native_assets(self):
        historical = tuple(item for item in GAME_BRIDGES if item['platform'] != 'neoforge' or item['version'] == '1.21.1')
        self.catalog(historical)
        (self.root/'starbridge/__init__.py').write_text('__version__="0.6.5"\n__forge_version__="0.1.0"\n', encoding='utf-8')
        for item in historical:
            self.artifact(item)
        self.assertEqual(len(native_assets(self.root)), 17)

    def test_066_source_catalog_keeps_twenty_three_assets_even_with_newer_artifact_present(self):
        historical = tuple(item for item in GAME_BRIDGES if not (item['platform'] == 'neoforge' and item['version'] == '1.20.6'))
        self.catalog(historical)
        (self.root/'starbridge/__init__.py').write_text('__version__="0.6.6"\n__forge_version__="0.1.0"\n', encoding='utf-8')
        for item in GAME_BRIDGES:
            self.artifact(item)
        assets = native_assets(self.root)
        self.assertEqual(len(assets), 23)
        self.assertNotIn('StarBridge-NeoForge-1.20.6-0.1.0.jar', [path.name for path in assets])

    def test_historical_catalog_and_single_forge_release_do_not_require_fabric(self):
        historical = tuple(item for item in GAME_BRIDGES if item['platform'] != 'fabric'
                           and (item['platform'] != 'neoforge' or item['version'] == '1.21.1'))
        self.catalog(historical)
        for item in historical:
            self.artifact(item)
        self.assertEqual(len(native_assets(self.root)), 7)
        (self.root/'starbridge/game_bridges.py').unlink()
        (self.root/'bridge-forge').mkdir()
        (self.root/'bridge-forge/gradle.properties').write_text('mod_version=0.1.0\n', encoding='utf-8')
        self.assertEqual([path.name for path in native_assets(self.root)], ['StarBridge-Forge-1.20.1-0.1.0.jar'])

    def test_unknown_loader_and_duplicate_catalog_cannot_publish_other_assets(self):
        with self.assertRaisesRegex(ValueError, '不支持的游戏端'):
            native_filename({'platform': 'quilt', 'version': '1.20.1', 'java': 17}, '0.1.0')
        with self.assertRaisesRegex(ValueError, '不支持的游戏端'):
            native_filename({'platform': 'fabric', 'version': '../secret', 'java': 17}, '0.1.0')
        item = {'platform': 'fabric', 'version': '1.20.1', 'java': 17}
        self.artifact(item)
        self.catalog((item, item))
        with self.assertRaisesRegex(ValueError, '重复版本'):
            native_assets(self.root)

    def test_current_brand_requires_current_artifacts_and_keeps_runtime_identity(self):
        item = {'platform': 'fabric', 'version': '1.20.1', 'java': 17}
        self.catalog((item,))
        (self.root / 'starbridge/branding.py').write_text("ARTIFACT_PREFIX = 'Myrinbot'\n", encoding='utf-8')
        legacy = self.artifact(item)
        current = self.artifact(item, prefix='Myrinbot')
        self.assertEqual(native_assets(self.root), [current])
        validate_native_mod(current, item, '0.1.0', prefix='Myrinbot')
        with self.assertRaisesRegex(ValueError, '文件名不一致'):
            validate_native_mod(legacy, item, '0.1.0', prefix='Myrinbot')
        current.unlink()
        with self.assertRaisesRegex(ValueError, '缺少游戏端构建'):
            native_assets(self.root)
        (self.root / 'starbridge/branding.py').write_text("ARTIFACT_PREFIX = '../other'\n", encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '产物名称错误'):
            native_assets(self.root)

    def test_release_build_includes_identical_legacy_aliases_and_checksums(self):
        item = {'platform': 'fabric', 'version': '1.20.1', 'java': 17}
        self.catalog((item,))
        (self.root / 'starbridge/branding.py').write_text("ARTIFACT_PREFIX = 'Myrinbot'\n", encoding='utf-8')
        self.artifact(item, prefix='Myrinbot')
        (self.root / 'bridge/pom.xml').write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><version>0.5.2</version></project>', encoding='utf-8')
        with zipfile.ZipFile(self.root / 'bridge/target/Myrinbot-0.5.2.jar', 'w') as archive:
            archive.writestr('plugin.yml', 'name: StarBridge\nversion: 0.5.2\n')
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/update_runtime.py').write_text('stable supervisor', encoding='utf-8')
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            output = Path(args[args.index('--output') + 1])
            output.write_bytes(b'website package' if 'website' in output.name else b'Bot package')

        with patch.object(release.subprocess, 'run', side_effect=run):
            version, assets = release.build(self.root)
        self.assertEqual(version, '0.6.7')
        self.assertEqual(len(calls), 2)
        primary = [path for path in assets if path.name.startswith('Myrinbot-')]
        self.assertEqual({path.name for path in primary}, {
            'Myrinbot-Windows-0.6.7.zip', 'Myrinbot-website.zip', 'Myrinbot-0.5.2.jar',
            'Myrinbot-Fabric-1.20.1-0.1.0.jar'})
        for path in primary:
            alias = path.with_name(path.name.replace('Myrinbot-', 'StarBridge-', 1))
            self.assertIn(alias, assets)
            self.assertEqual(path.read_bytes(), alias.read_bytes())
        checksums = assets[-1].read_text('utf-8').splitlines()
        self.assertEqual(len(checksums), 8)
        self.assertEqual({line.split()[1] for line in checksums}, {path.name for path in assets[:-1]})
        for path in assets[:-1]:
            self.assertIn(release.digest(path) + '  ' + path.name, checksums)
