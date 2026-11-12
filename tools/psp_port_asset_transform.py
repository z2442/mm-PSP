#!/usr/bin/env python3
"""Payload-free byte-order conversion recipes for the PSP-created asset pack."""
from __future__ import annotations
import mmap
import re
import struct
import zlib
from pathlib import Path
ASSET_ENTRY_RE = re.compile(
    r'\{ (0x[0-9A-F]+), (0x[0-9A-F]+), (0x[0-9A-F]+), (0x[0-9A-F]+), '
    r'(0x[0-9A-F]+), (0x[0-9A-F]+), "([^\"]+)" \}'
)

def word_partitions(size: int) -> list[tuple[int, ...]]:
    result: list[tuple[int, ...]] = []

    def visit(remaining: int, parts: tuple[int, ...]) -> None:
        if remaining == 0:
            result.append(parts)
            return
        for width in (8, 4, 2, 1):
            if width <= remaining:
                visit(remaining - width, parts + (width,))

    visit(size, ())
    return result


def permutation(parts: tuple[int, ...]) -> bytes:
    result: list[int] = []
    offset = 0
    for width in parts:
        result.extend(reversed(range(offset, offset + width)))
        offset += width
    return bytes(result)


def parse_entries(table_path: Path) -> list[tuple[str, int, int, int]]:
    text = table_path.read_text()
    return [
        (name, int(vrom_end, 16) - int(vrom_start, 16), int(flags, 16), int(file_offset, 16))
        for vrom_start, vrom_end, _original_start, _original_end, flags, file_offset, name in ASSET_ENTRY_RE.findall(
            text
        )
    ]


def build_transform(build_dir: Path, extracted_dir: Path, packed_path: Path | None = None) -> bytes:
    entries = parse_entries(build_dir / "oot_psp_asset_segments.c")
    if packed_path is None:
        packed_path = build_dir / "data/segments/oot_psp_assets.bin"
    permutations = [permutation(parts) for parts in word_partitions(8)]
    native_count = sum(flags != 0 for _name, _size, flags, _file_offset in entries)
    output = bytearray(b"OPZ4" + struct.pack("<II", native_count, len(permutations)))

    for mapping in permutations:
        output.extend(mapping)

    with packed_path.open("rb") as packed_file:
        packed = mmap.mmap(packed_file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for asset_index, (name, size, flags, file_offset) in enumerate(entries):
                if flags == 0:
                    continue

                source = (extracted_dir / name).read_bytes()
                selectors = bytearray()
                mappings = bytearray()
                source_positions: dict[int, int] = {}

                for source_offset, value in enumerate(source):
                    source_positions.setdefault(value, source_offset)

                if len(source) != size:
                    raise ValueError(f"unexpected source size for {name}: {len(source)} != {size}")

                for offset in range(0, size, 8):
                    raw_block = source[offset : offset + 8]
                    native_block = packed[file_offset + offset : file_offset + min(offset + 8, size)]
                    selector = len(permutations) + 1  # mapped from the user's ROM

                    if len(raw_block) == 8 and len(native_block) == 8:
                        for index, mapping in enumerate(permutations):
                            if bytes(raw_block[source_index] for source_index in mapping) == native_block:
                                selector = index
                                break
                        else:
                            if native_block == bytes(8):
                                selector = len(permutations)  # zero fill

                    if selector == len(permutations) + 1:
                        for byte_offset, value in enumerate(native_block):
                            original_offset = offset + byte_offset
                            source_offset = source_positions.get(value, original_offset)
                            delta = (value - source[source_offset]) & 0xFF

                            # A mapping is an offset into the user's own extracted
                            # segment plus a byte delta. It never stores an output
                            # byte from the game.
                            mappings.extend(struct.pack("<IB", source_offset, delta))
                    selectors.append(selector)

                payload = selectors + mappings
                compressed = zlib.compress(payload, level=9)
                output.extend(struct.pack("<IIII", asset_index, size, len(payload), len(compressed)))
                output.extend(compressed)
        finally:
            packed.close()

    return bytes(output)

