"""Validate declared unobfuscated bindings against a pinned official server JAR."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import zipfile

from classfile import declarations


def native_bindings(specification: dict, bundled: Path) -> dict:
    """Return only Myrinbot's declared API surface; never include game bytecode."""
    with zipfile.ZipFile(bundled) as bundle:
        game_bytes = bundle.read(specification['server']['entry'])
    with zipfile.ZipFile(BytesIO(game_bytes)) as game:
        classes = specification['classes']
        loaded = {}
        for actual in classes.values():
            if actual in loaded:
                continue
            row = declarations(game.read(actual.replace('.', '/') + '.class'))
            if row['name'] != actual:
                raise ValueError(f'Official native class owner mismatch: {actual}')
            loaded[actual] = row
        members = {}
        for kind in ('methods', 'fields'):
            members[kind] = []
            seen = set()
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
        raise ValueError('Unobfuscated native bindings do not match the requested Minecraft version')
    return document
