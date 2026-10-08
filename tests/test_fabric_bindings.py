"""A game update must not silently bind a similarly named but different JVM API."""
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

BUILDER = Path(__file__).resolve().parents[1] / 'bridge-fabric'
sys.path.insert(0, str(BUILDER))
from bindings import native_bindings, read_specification
from classfile import declarations


def class_fixture():
    """Small JVM declaration with two same-name fields and a typed native method."""
    values = ['net/minecraft/probe/Surface', 'java/lang/Object', 'value', 'I',
              'Ljava/lang/String;', 'read', '()I']
    def u2(value): return value.to_bytes(2, 'big')
    pool = b''.join(b'\x01' + u2(len(s)) + s.encode() for s in values)
    pool += b'\x07' + u2(1) + b'\x07' + u2(2)
    data = b'\xca\xfe\xba\xbe' + u2(0) + u2(69) + u2(10) + pool
    data += u2(33) + u2(8) + u2(9) + u2(0)
    data += u2(2) + u2(1) + u2(3) + u2(4) + u2(0)
    data += u2(1) + u2(3) + u2(5) + u2(0)
    data += u2(1) + u2(257) + u2(6) + u2(7) + u2(0) + u2(0)
    return data


class NativeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundled = Path(self.temporary.name) / 'server.jar'
        game = BytesIO()
        with zipfile.ZipFile(game, 'w') as archive:
            archive.writestr('net/minecraft/probe/Surface.class', class_fixture())
        with zipfile.ZipFile(self.bundled, 'w') as archive:
            archive.writestr('META-INF/versions/26.3/server-26.3.jar', game.getvalue())
        self.spec = {'minecraft': '26.3', 'server': {'entry': 'META-INF/versions/26.3/server-26.3.jar'},
                     'classes': {'probe.Surface': 'net.minecraft.probe.Surface'},
                     'methods': [{'owner': 'probe.Surface', 'name': 'getValue', 'actual': 'read', 'descriptor': '()I'}],
                     'fields': [{'owner': 'probe.Surface', 'name': 'value', 'actual': 'value', 'descriptor': 'I'}],
                     'packets': {}}

    def test_java25_declarations_preserve_same_name_field_descriptors(self):
        row = declarations(class_fixture())
        self.assertEqual(row['major'], 69)
        self.assertEqual([field['descriptor'] for field in row['fields']], ['I', 'Ljava/lang/String;'])
        document = native_bindings(self.spec, self.bundled)
        self.assertEqual(document['namespace'], 'official')
        self.assertEqual(document['methods'][0]['intermediary'], 'read')
        self.assertEqual(document['fields'][0]['descriptor'], 'I')

    def test_changed_return_descriptor_is_rejected(self):
        self.spec['methods'][0]['descriptor'] = '()Ljava/lang/String;'
        with self.assertRaisesRegex(ValueError, 'declaration changed'):
            native_bindings(self.spec, self.bundled)

    def test_renamed_native_member_is_rejected(self):
        self.spec['methods'][0]['actual'] = 'renamedRead'
        with self.assertRaisesRegex(ValueError, 'declaration changed'):
            native_bindings(self.spec, self.bundled)

    def test_duplicate_logical_binding_is_rejected(self):
        self.spec['methods'].append(dict(self.spec['methods'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate native binding'):
            native_bindings(self.spec, self.bundled)

    def test_packet_cannot_refer_to_an_unvalidated_class(self):
        self.spec['packets']['probe.UnknownPacket'] = 'net.minecraft.probe.Unknown'
        with self.assertRaisesRegex(ValueError, 'exact declared class'):
            native_bindings(self.spec, self.bundled)

    def test_wrong_version_specification_is_rejected(self):
        path = Path(self.temporary.name) / 'bindings.json'
        path.write_text(json.dumps(self.spec), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'requested Minecraft version'):
            read_specification(path, '26.2')

    def test_truncated_or_wrong_class_file_is_rejected(self):
        for payload in (b'wrong', class_fixture()[:-1]):
            with self.subTest(length=len(payload)), self.assertRaises(ValueError):
                declarations(payload)
