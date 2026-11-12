#!/usr/bin/env python3
"""Check first-boot recipes and placeholder coverage against a private MM reference build.

Requires extracted reference assets. Nothing from the ROM is written to the repository.
"""
from pathlib import Path
import argparse
import ctypes
import csv
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.psp_port_asset_transform import parse_entries
from tools.psp_port_runtime_patches import ElfObject, linked_objects_by_file, linked_symbol_bytes
from tools.tests.test_psp_first_boot import Transforms


def records(path):
    data = path.read_bytes()
    if data[:4] != b'OPR3':
        raise ValueError('unsupported runtime manifest')
    count, permutations = struct.unpack_from('<II', data, 4)
    cursor = 12 + permutations * 8
    for _ in range(count):
        file_len, name_len, vrom, size, payload_size, compressed_size, relocations = struct.unpack_from(
            '<HHIIIII', data, cursor)
        cursor += 24
        source = data[cursor:cursor + file_len].decode()
        cursor += file_len
        name = data[cursor:cursor + name_len].decode()
        cursor += name_len
        payload = zlib.decompress(data[cursor:cursor + compressed_size])
        cursor += compressed_size
        targets = []
        for _ in range(relocations):
            offset, pointer, addend, file_length, name_length = struct.unpack_from('<IIiHH', data, cursor)
            cursor += 16
            target_file = data[cursor:cursor + file_length].decode()
            cursor += file_length
            target_name = data[cursor:cursor + name_length].decode()
            cursor += name_length
            targets.append((offset, pointer, addend, target_file, target_name))
        if len(payload) != payload_size:
            raise ValueError(f'invalid runtime recipe: {source}:{name}')
        yield source, name, vrom, size, payload, targets
    if cursor != len(data):
        raise ValueError('trailing runtime recipe data')


def check_rom(rom_path, extracted, version, transforms):
    rom = rom_path.read_bytes()
    with (ROOT / 'baseroms' / version / 'segments.csv').open() as stream:
        names = [row['Name'] for row in csv.DictReader(stream)]
    count = 0
    for index, name in enumerate(names):
        start, end, rom_start, rom_end = struct.unpack_from('>IIII', rom, 0x1A500 + index * 16)
        if not rom_end or rom_start == 0xFFFFFFFF:
            continue
        output = ctypes.create_string_buffer(end - start)
        encoded = rom[rom_start:rom_end]
        if not transforms.library.decode(encoded, len(encoded), output, end - start):
            raise ValueError(f'Yaz0 decoder rejected {name}')
        if output.raw != (extracted / name).read_bytes():
            raise ValueError(f'Yaz0 decoder differs from reference: {name}')
        count += 1
    print(f'Actual C Yaz0 decoder matches {count} compressed ROM segments.', flush=True)


def check_transforms(reference, extracted, metadata, transforms):
    packed = (reference / 'data/segments/oot_psp_assets.bin').read_bytes()
    entries = parse_entries(reference / 'oot_psp_asset_segments.c')
    data = (metadata / 'asset_transform.z').read_bytes()
    count, permutations = struct.unpack_from('<II', data, 4)
    cursor = 12 + permutations * 8
    converted = 0
    for index, (name, size, flags, offset) in enumerate(entries):
        raw = (extracted / name).read_bytes()
        if flags:
            compressed_size = struct.unpack_from('<I', data, cursor + 12)[0]
            record = data[cursor:cursor + 16 + compressed_size]
            cursor += len(record)
            actual = transforms.asset(raw, index, record)
            converted += 1
        else:
            actual = raw
        if actual != packed[offset:offset + size]:
            raise ValueError(f'first-boot conversion differs from reference: {name}')
    if cursor != len(data) or converted != count:
        raise ValueError('first-boot manifest entry count mismatch')
    print(f'Actual C conversion matches all {len(entries)} packed segments ({converted} native transforms).', flush=True)

    elf = ElfObject(reference / 'mm-psp-port.base.elf')
    objects = linked_objects_by_file(elf)
    by_name = {}
    for (_, name), symbol in objects.items():
        by_name.setdefault(name, []).append(symbol)
    patches = list(records(metadata / 'runtime_patches.z'))
    for source_file, name, vrom, size, payload, _targets in patches:
        matches = [(length, flags, offset) for _, length, flags, offset in entries
                   if 0x20000000 + offset <= vrom and vrom + size <= 0x20000000 + offset + length]
        if len(matches) != 1:
            raise ValueError(f'invalid packed source for {source_file}:{name}')
        source = packed[vrom - 0x20000000:vrom - 0x20000000 + size]
        symbol = objects.get((source_file, name))
        if symbol is None:
            candidates = [candidate for candidate in by_name.get(name, []) if candidate.size == size]
            if len(candidates) != 1:
                raise ValueError(f'ambiguous reference object: {source_file}:{name}')
            symbol = candidates[0]
        if transforms.patch(source, payload) != linked_symbol_bytes(elf, symbol):
            raise ValueError(f'runtime conversion differs from reference: {source_file}:{name}')
    print(f'Actual C runtime conversion reconstructs all {len(patches)} linked objects.', flush=True)
    return elf, {name for _, name, _, _, _, _ in patches}


def check_symbolic_pointers(clean, metadata):
    elf = ElfObject(clean / 'mm-psp-port.elf')
    symbols = linked_objects_by_file(elf, include_functions=True)
    by_name = {}
    for (_file, name), symbol in symbols.items():
        if not any(candidate.value == symbol.value for candidate in by_name.setdefault(name, [])):
            by_name[name].append(symbol)
    blob = (clean / 'oot_psp_runtime_patches.bin').read_bytes()
    if blob[:4] != b'OPB2':
        raise ValueError('unsupported resolved runtime blob')
    count, permutations = struct.unpack_from('<II', blob, 4)
    cursor = 12 + permutations * 8
    total = 0
    patches = list(records(metadata / 'runtime_patches.z'))
    if count != len(patches):
        raise ValueError('resolved runtime blob entry count mismatch')
    for source, name, vrom, size, _payload, targets in patches:
        destination, source_vrom, resolved_size, _payload_size, compressed_size, relocations, _flags = struct.unpack_from('<IIIIIII', blob, cursor)
        cursor += 28 + compressed_size
        target_object = symbols.get((source, name))
        if target_object is None:
            target_object, = by_name[name]
        if target_object.value != destination or source_vrom != vrom or resolved_size != size or relocations != len(targets):
            raise ValueError(f'invalid runtime destination: {source}:{name}')
        for offset, original, addend, target_file, target_name in targets:
            resolved_offset, adjustment = struct.unpack_from('<Ii', blob, cursor)
            cursor += 8
            target = symbols.get((target_file, target_name))
            if target is None:
                target, = by_name[target_name]
            if resolved_offset != offset or original + adjustment != target.value + addend:
                raise ValueError(f'incorrect symbolic pointer: {source}:{name}+{offset}')
            total += 1
    if cursor != len(blob):
        raise ValueError('trailing resolved runtime blob data')
    storage = [section for section in elf.sections if section.name == '.mm_psp_placeholders']
    if len(storage) != 1 or any(elf.section_data[elf.sections.index(storage[0])]):
        raise ValueError('compile-time asset storage must contain only zero bytes')
    print(f'All {total} symbolic pointers match the linked image; compiled asset storage is entirely zero.', flush=True)


def initialized_objects(elf):
    return {symbol.name: symbol for symbols in elf.symtabs.values() for symbol in symbols
            if symbol.info & 15 == 1 and symbol.size and 0 < symbol.shndx < len(elf.sections)}


def object_bytes(elf, symbol):
    if elf.sections[symbol.shndx].type == 8:
        return bytes(symbol.size)
    return elf.section_data[symbol.shndx][symbol.value:symbol.value + symbol.size]


def check_coverage(reference, clean, linked_elf, patched):
    live_names = {symbol.name for symbols in linked_elf.symtabs.values() for symbol in symbols if symbol.size}
    changed = messages = 0
    paths = list((clean / 'src').rglob('*.o')) + list((clean / 'assets/text').glob('*.o'))
    if not paths:
        raise ValueError('no compiled clean-build objects found')
    errors = []
    for path in paths:
        relative = path.relative_to(clean)
        other = reference / relative
        if not other.is_file() or str(relative).startswith('src/port/psp/'):
            continue
        left_elf, right_elf = ElfObject(other), ElfObject(path)
        left, right = initialized_objects(left_elf), initialized_objects(right_elf)
        for name, original in left.items():
            if name not in live_names:
                continue
            placeholder = right.get(name)
            if placeholder is None:
                errors.append(f'{relative}:{name} has no placeholder')
                continue
            if name.startswith('_message_'):
                if original.size != placeholder.size or original.value != placeholder.value:
                    errors.append(f'{relative}:{name} changes the message layout')
                messages += 1
            elif object_bytes(left_elf, original) != object_bytes(right_elf, placeholder):
                changed += 1
                if name not in patched:
                    errors.append(f'{relative}:{name} has no runtime recipe')
    if errors:
        raise ValueError('\n'.join(errors))
    print(f'All {changed} changed live objects have recipes; {messages} message layouts match.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference_build', type=Path)
    parser.add_argument('clean_build', type=Path)
    parser.add_argument('extracted_dir', type=Path)
    parser.add_argument('--rom', type=Path)
    args = parser.parse_args()
    transforms = Transforms()
    try:
        metadata = ROOT / 'assets/psp' / args.reference_build.name
        if args.rom:
            check_rom(args.rom, args.extracted_dir, args.reference_build.name, transforms)
        elf, patched = check_transforms(args.reference_build, args.extracted_dir, metadata, transforms)
        check_coverage(args.reference_build, args.clean_build, elf, patched)
        check_symbolic_pointers(args.clean_build, metadata)
    finally:
        transforms.close()


if __name__ == '__main__':
    main()
