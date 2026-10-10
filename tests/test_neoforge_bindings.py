"""Pinned NeoForge bindings must reject changed or mismatched native APIs."""
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    'starbridge_neoforge_bindings_test', ROOT / 'bridge-neoforge' / 'native_bindings.py')
bindings = importlib.util.module_from_spec(loader)
loader.loader.exec_module(bindings)


def declaration_fixture(owner='a', method='b', descriptor='()I'):
    """Build declarations only, with an internal self type and an external override."""
    constants = [owner, 'java/lang/Object', 'c', 'I', method, descriptor,
                 'd', '(L' + owner + ';)L' + owner + ';', 'onResult', '(ZI)V']
    def u2(value):
        return value.to_bytes(2, 'big')
    pool = b''.join(b'\x01' + u2(len(value)) + value.encode() for value in constants)
    pool += b'\x07' + u2(1) + b'\x07' + u2(2)
    data = b'\xca\xfe\xba\xbe' + u2(0) + u2(65) + u2(13) + pool
    data += u2(33) + u2(11) + u2(12) + u2(0)
    data += u2(1) + u2(1) + u2(3) + u2(4) + u2(0)
    data += u2(3)
    for name, signature in ((5, 6), (7, 8), (9, 10)):
        data += u2(257) + u2(name) + u2(signature) + u2(0)
    return data + u2(0)


class NeoForgeBindingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.server = self.directory / 'server.jar'
        self.mapping = self.directory / 'server.txt'
        self.mapping.write_text(
            '# Official mapping fixture\n'
            'net.minecraft.probe.Surface -> a:\n'
            '    int value -> c\n'
            '    5:8:int read():99:103 -> b\n'
            '    net.minecraft.probe.Surface copy(net.minecraft.probe.Surface) -> d\n',
            encoding='utf-8')
        self.write_server(declaration_fixture())
        self.specification = {
            'minecraft': '1.21.11',
            'server': {'entry': 'META-INF/versions/1.21.11/server-1.21.11.jar',
                       'sha256': self.digest(self.server)},
            'mappings': {'sha256': self.digest(self.mapping)},
            'classes': {'logical.Surface': 'net.minecraft.probe.Surface'},
            'methods': [{'owner': 'logical.Surface', 'name': 'getValue', 'actual': 'read', 'descriptor': '()I'},
                        {'owner': 'logical.Surface', 'name': 'copy', 'actual': 'copy',
                         'descriptor': '(Lnet/minecraft/probe/Surface;)Lnet/minecraft/probe/Surface;'},
                        {'owner': 'logical.Surface', 'name': 'onResult', 'actual': 'onResult', 'descriptor': '(ZI)V'}],
            'fields': [{'owner': 'logical.Surface', 'name': 'value', 'actual': 'value', 'descriptor': 'I'}],
            'packets': {},
        }

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_server(self, data):
        game = BytesIO()
        with zipfile.ZipFile(game, 'w') as archive:
            archive.writestr('a.class', data)
        with zipfile.ZipFile(self.server, 'w') as archive:
            archive.writestr('META-INF/versions/1.21.11/server-1.21.11.jar', game.getvalue())

    def validate(self):
        return bindings.native_bindings(self.specification, self.server, self.mapping)

    def test_official_mappings_validate_obfuscated_declared_api(self):
        document = self.validate()
        self.assertEqual(document['namespace'], 'official')
        self.assertEqual(document['methods'][0]['intermediary'], 'read')
        self.assertEqual(document['methods'][1]['descriptor'],
                         '(Lnet/minecraft/probe/Surface;)Lnet/minecraft/probe/Surface;')
        self.assertEqual(document['fields'][0]['intermediary'], 'value')
        self.assertNotIn('mappings', document)
        self.assertNotIn('server', document)

    def test_other_server_bytes_are_rejected_before_mapping(self):
        self.write_server(declaration_fixture(method='changed'))
        with self.assertRaisesRegex(ValueError, 'server SHA-256 mismatch'):
            self.validate()

    def test_other_mapping_bytes_are_rejected(self):
        self.mapping.write_text(self.mapping.read_text() + '# different release\n')
        with self.assertRaisesRegex(ValueError, 'mappings SHA-256 mismatch'):
            self.validate()

    def test_mapping_cannot_invent_a_missing_native_method(self):
        self.write_server(declaration_fixture(method='different'))
        self.specification['server']['sha256'] = self.digest(self.server)
        with self.assertRaisesRegex(ValueError, 'declaration changed'):
            self.validate()

    def test_same_name_with_changed_descriptor_is_rejected(self):
        self.specification['methods'][0]['descriptor'] = '()J'
        with self.assertRaisesRegex(ValueError, 'declaration changed'):
            self.validate()

    def test_obfuscated_spelling_is_not_a_named_runtime_binding(self):
        self.specification['methods'][0]['actual'] = 'b'
        with self.assertRaisesRegex(ValueError, 'declaration changed'):
            self.validate()

    def test_unmapped_external_override_still_needs_exact_declaration(self):
        self.specification['methods'][2]['descriptor'] = '(I)V'
        with self.assertRaisesRegex(ValueError, 'declaration changed'):
            self.validate()

    def test_wrong_declaring_class_is_rejected(self):
        self.write_server(declaration_fixture(owner='other'))
        self.specification['server']['sha256'] = self.digest(self.server)
        with self.assertRaisesRegex(ValueError, 'class owner mismatch'):
            self.validate()

    def test_duplicate_binding_and_unvalidated_packet_are_rejected(self):
        self.specification['methods'].append(dict(self.specification['methods'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate native binding'):
            self.validate()
        self.specification['methods'].pop()
        self.specification['packets']['logical.Other'] = 'net.minecraft.probe.Other'
        with self.assertRaisesRegex(ValueError, 'exact declared class'):
            self.validate()

    def test_missing_mapping_and_missing_digest_pin_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'matching official mappings'):
            bindings.native_bindings(self.specification, self.server)
        self.specification['server']['sha256'] = ''
        with self.assertRaisesRegex(ValueError, 'pin is missing or invalid'):
            self.validate()

    def test_requested_release_cannot_use_another_specification(self):
        path = self.directory / 'bindings.json'
        path.write_text(json.dumps(self.specification), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'requested Minecraft version'):
            bindings.read_specification(path, '26.2')

    def test_unobfuscated_release_validates_without_official_mapping(self):
        self.write_server(declaration_fixture())
        del self.specification['mappings']
        self.specification['server']['sha256'] = self.digest(self.server)
        self.specification['classes'] = {'logical.Surface': 'a'}
        self.specification['methods'] = [{'owner': 'logical.Surface', 'name': 'read', 'actual': 'b', 'descriptor': '()I'}]
        self.specification['fields'] = [{'owner': 'logical.Surface', 'name': 'value', 'actual': 'c', 'descriptor': 'I'}]
        document = bindings.native_bindings(self.specification, self.server)
        self.assertEqual(document['methods'][0]['intermediary'], 'b')


if __name__ == '__main__':
    unittest.main()
