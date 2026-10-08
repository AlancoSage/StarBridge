"""Read JVM member declarations without loading Minecraft or running its code."""
from __future__ import annotations

def declarations(data: bytes) -> dict:
    offset = 0

    def take(size):
        nonlocal offset
        if offset + size > len(data):
            raise ValueError('Truncated JVM class file')
        result = data[offset:offset + size]
        offset += size
        return result

    def number(size):
        return int.from_bytes(take(size), 'big')

    if take(4) != b'\xca\xfe\xba\xbe':
        raise ValueError('Invalid JVM class file')
    minor, major = number(2), number(2)
    constants = [None] * number(2)
    index = 1
    while index < len(constants):
        tag = number(1)
        if tag == 1:
            # Only class, method and descriptor names are read, all ASCII in the JVM.
            constants[index] = take(number(2)).decode('utf-8', errors='replace')
        elif tag in (7, 8, 16, 19, 20):
            constants[index] = number(2)
        elif tag in (3, 4):
            take(4)
        elif tag in (5, 6):
            take(8)
            index += 1
        elif tag in (9, 10, 11, 12, 17, 18):
            take(4)
        elif tag == 15:
            take(3)
        else:
            raise ValueError(f'Unsupported JVM constant tag: {tag}')
        index += 1

    def class_name(index):
        return constants[constants[index]].replace('/', '.') if index else None

    access, owner, parent = number(2), class_name(number(2)), class_name(number(2))
    interfaces = [class_name(number(2)) for _ in range(number(2))]

    def attributes():
        values = {}
        for _ in range(number(2)):
            name = constants[number(2)]
            values[name] = take(number(4))
        return values

    def members():
        rows = []
        for _ in range(number(2)):
            flags, name, descriptor = number(2), constants[number(2)], constants[number(2)]
            attributes()
            rows.append({'name': name, 'descriptor': descriptor, 'access': flags})
        return rows

    fields, methods = members(), members()
    extra = attributes()
    if offset != len(data):
        raise ValueError('Unexpected data after JVM class declaration')
    return {'name': owner, 'superclass': parent, 'interfaces': interfaces,
            'major': major, 'minor': minor, 'access': access,
            'fields': fields, 'methods': methods, 'record': 'Record' in extra}
