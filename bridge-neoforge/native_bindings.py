"""Verify NeoForge's named API against pinned Mojang JVM declarations.

The obfuscated 1.x server is read without executing Minecraft. Its declarations
are translated by the matching official mappings, then compared by exact owner,
member name and descriptor. Only the API used by Myrinbot enters the mod.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import re
import zipfile

_reader = importlib.util.spec_from_file_location(
    'starbridge_neoforge_classfile', Path(__file__).resolve().parents[1] / 'bridge-fabric' / 'classfile.py')
_module = importlib.util.module_from_spec(_reader)
_reader.loader.exec_module(_module)
declarations = _module.declarations

_PRIMITIVES = {'void': 'V', 'boolean': 'Z', 'byte': 'B', 'char': 'C',
               'short': 'S', 'int': 'I', 'long': 'J', 'float': 'F', 'double': 'D'}


def remap_descriptor(descriptor: str, classes: dict[str, str]) -> str:
    """Translate internal JVM class names, retaining external library types."""
    return re.sub(r'L([^;]+);', lambda match: 'L' + classes.get(match[1], match[1]) + ';', descriptor)


def _type_descriptor(name: str) -> str:
    dimensions = 0
    while name.endswith('[]'):
        dimensions += 1
        name = name[:-2]
    return '[' * dimensions + _PRIMITIVES.get(name, 'L' + name.replace('.', '/') + ';')


def official_mappings(path: Path) -> tuple[dict[str, str], list[dict]]:
    """Read ProGuard named-to-obfuscated mappings without retaining source text."""
    classes, members, owner = {}, [], None
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' '):
            if not line.endswith(':') or ' -> ' not in line:
                raise ValueError('Malformed official class mapping')
            named, obfuscated = line[:-1].split(' -> ')
            owner = named.replace('.', '/')
            if owner in classes and classes[owner] != obfuscated.replace('.', '/'):
                raise ValueError('Conflicting official class mapping')
            classes[owner] = obfuscated.replace('.', '/')
            continue
        if owner is None or ' -> ' not in line:
            raise ValueError('Malformed official member mapping')
        declaration, obfuscated = line.strip().split(' -> ')
        declaration = re.sub(r'^\d+:\d+:', '', declaration)
        declaration = re.sub(r':\d+(?::\d+)?$', '', declaration)
        return_type, name = declaration.split(' ', 1)
        if '(' in name:
            match = re.fullmatch(r'([^()]*)\(([^()]*)\)', name)
            if match is None:
                raise ValueError('Malformed official method mapping')
            name, arguments = match.groups()
            descriptor = '(' + ''.join(_type_descriptor(value) for value in arguments.split(',') if value) + ')'
            descriptor += _type_descriptor(return_type)
            kind = 'methods'
        else:
            descriptor, kind = _type_descriptor(return_type), 'fields'
        members.append({'kind': kind, 'owner': owner, 'name': name,
                        'obfuscated': obfuscated, 'descriptor': descriptor})
    if not classes:
        raise ValueError('Official mappings contain no classes')
    return classes, members


def _verify_digest(path: Path, expected: str, label: str) -> None:
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError(f'{label} SHA-256 pin is missing or invalid')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected:
        raise ValueError(f'{label} SHA-256 mismatch')


def native_bindings(specification: dict, bundled: Path, mapping_path: Path | None = None) -> dict:
    """Validate every declared binding; no game classes or full mappings are emitted."""
    _verify_digest(bundled, specification['server']['sha256'], 'Official server')
    mapping = specification.get('mappings')
    if mapping is not None:
        if mapping_path is None:
            raise ValueError('The matching official mappings are required')
        _verify_digest(mapping_path, mapping['sha256'], 'Official mappings')
        named_to_obfuscated, mapped_members = official_mappings(mapping_path)
        obfuscated_to_named = {value: key for key, value in named_to_obfuscated.items()}
        if len(obfuscated_to_named) != len(named_to_obfuscated):
            raise ValueError('Conflicting official obfuscated class mapping')
        renamed = {}
        for row in mapped_members:
            key = (row['kind'], named_to_obfuscated[row['owner']], row['obfuscated'],
                   remap_descriptor(row['descriptor'], named_to_obfuscated))
            # Inline source mappings may repeat the same declaration. Exact native
            # declarations are selected below, so keep every distinct named alias.
            renamed.setdefault(key, set()).add((row['name'], row['descriptor']))
    else:
        if mapping_path is not None:
            raise ValueError('Mappings are not declared for this server')
        named_to_obfuscated, obfuscated_to_named, renamed = {}, {}, {}
    with zipfile.ZipFile(bundled) as bundle:
        game_bytes = bundle.read(specification['server']['entry'])
    classes, loaded = specification['classes'], {}
    with zipfile.ZipFile(BytesIO(game_bytes)) as game:
        for actual in classes.values():
            if actual in loaded:
                continue
            internal = actual.replace('.', '/')
            if mapping is not None and internal not in named_to_obfuscated:
                raise ValueError(f'Official class mapping is missing: {actual}')
            original = named_to_obfuscated.get(internal, internal)
            raw = declarations(game.read(original + '.class'))
            if raw['name'].replace('.', '/') != original:
                raise ValueError(f'Official native class owner mismatch: {actual}')
            translated = {'methods': [], 'fields': []}
            for kind in translated:
                for member in raw[kind]:
                    descriptor = remap_descriptor(member['descriptor'], obfuscated_to_named)
                    key = (kind, original, member['name'], member['descriptor'])
                    names = renamed.get(key)
                    if names:
                        for name, declared_descriptor in names:
                            if descriptor != declared_descriptor:
                                raise ValueError('Official mapping descriptor mismatch')
                            translated[kind].append({'name': name, 'descriptor': descriptor})
                    else:
                        # Constructors and external overrides have their unchanged
                        # names in the real class file. This is still an exact JVM
                        # declaration comparison, never a guessed member binding.
                        translated[kind].append({'name': member['name'], 'descriptor': descriptor})
            loaded[actual] = translated
    members = {}
    for kind in ('methods', 'fields'):
        members[kind], seen = [], set()
        for expected in specification[kind]:
            owner, name, descriptor = expected['owner'], expected['actual'], expected['descriptor']
            identity = (owner, expected['name'], descriptor)
            if identity in seen:
                raise ValueError(f'Duplicate native binding: {owner}#{expected["name"]}')
            seen.add(identity)
            if owner not in classes:
                raise ValueError(f'Native binding owner missing: {owner}')
            choices = loaded[classes[owner]][kind]
            if sum(row['name'] == name and row['descriptor'] == descriptor for row in choices) != 1:
                raise ValueError(f'Official native declaration changed: {owner}#{name}{descriptor}')
            members[kind].append({'owner': owner, 'name': expected['name'],
                                  'intermediary': name, 'descriptor': descriptor})
    packets = specification['packets']
    for logical, actual in packets.items():
        if classes.get(logical) != actual:
            raise ValueError(f'Native packet is not an exact declared class: {logical}')
    return {'mcVersion': specification['minecraft'], 'namespace': 'official',
            'classes': classes, **members, 'packets': packets}


def read_specification(path: Path, version: str) -> dict:
    document = json.loads(path.read_text(encoding='utf-8'))
    if document['minecraft'] != version:
        raise ValueError('Native bindings do not match the requested Minecraft version')
    return document
