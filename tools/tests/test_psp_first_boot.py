"""Exercise the actual first-boot and runtime byte transforms on the host."""
from pathlib import Path
import ctypes
import re
import struct
import subprocess
import tempfile
import unittest
import zlib
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.psp_port_asset_transform import permutation, word_partitions
from tools.psp_port_runtime_patches import build_payload


def function(source, name):
    start = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\s*\{', source, re.M).start()
    return source[start:source.index('\n}', start) + 2] + '\n'


class Transforms:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mm-first-boot-')
        directory = Path(self.directory.name)
        builder = (ROOT / 'src/port/psp/mm_psp_asset_builder.c').read_text()
        runtime = (ROOT / 'src/port/psp/backend/oot_psp_runtime_patch.c').read_text()
        source = '''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef int32_t s32;
#define OOT_PSP_TRANSFORM_ZERO_SELECTOR 56
#define OOT_PSP_TRANSFORM_MAPPED_SELECTOR 57
#define OOT_PSP_PATCH_ZERO_SELECTOR 56
#define OOT_PSP_PATCH_MAPPED_SELECTOR 57
'''
        source += ''.join(function(builder, name) for name in (
            'OotPspAssetBuilder_ReadLe32', 'OotPspAssetBuilder_ReadBe32',
            'OotPspAssetBuilder_DecompressYaz0', 'OotPspAssetBuilder_TransformAsset'))
        source += ''.join(function(runtime, name) for name in (
            'OotPspRuntimePatch_ReadLe32', 'OotPspRuntimePatch_Transform'))
        source += '''
int asset(u8* data, size_t size, size_t index, const u8* record, size_t length, const u8* permutations) {
    const u8* cursor = record;
    return OotPspAssetBuilder_TransformAsset(data, size, index, &cursor, record + length, permutations, 56)
        && cursor == record + length;
}
int patch(u8* data, size_t size, const u8* payload, size_t length, const u8* permutations) {
    return OotPspRuntimePatch_Transform(data, size, payload, length, permutations, 56);
}
int decode(const u8* input, size_t length, u8* output, size_t size) {
    return OotPspAssetBuilder_DecompressYaz0(input, length, output, size);
}
'''
        (directory / 'transforms.c').write_text(source)
        subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(directory / 'transforms.c'), '-lz', '-o', str(directory / 'transforms.so')], check=True)
        self.library = ctypes.CDLL(str(directory / 'transforms.so'))
        self.library.asset.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,
                                      ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
        self.library.patch.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.c_void_p]
        self.library.decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        self.permutations = [permutation(parts) for parts in word_partitions(8)]
        self.mapping = b''.join(self.permutations)

    def asset(self, source, index, record):
        output = ctypes.create_string_buffer(source, len(source))
        if not self.library.asset(output, len(source), index, record, len(record), self.mapping):
            raise ValueError('asset transform rejected the recipe')
        return output.raw

    def patch(self, source, payload):
        output = ctypes.create_string_buffer(source, len(source))
        if not self.library.patch(output, len(source), bytes(payload), len(payload), self.mapping):
            raise ValueError('runtime transform rejected the recipe')
        return output.raw

    def close(self):
        self.directory.cleanup()


class FirstBootTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transforms = Transforms()

    @classmethod
    def tearDownClass(cls):
        cls.transforms.close()

    def test_byte_order_zero_fill_and_mapped_bytes(self):
        source = bytes(range(64))
        target = source[:8][::-1] + bytes(8) + bytes((value * 3 + 7) & 255 for value in source[16:])
        payload = build_payload(source, target, self.transforms.permutations)
        compressed = zlib.compress(payload)
        record = struct.pack('<IIII', 9, len(source), len(payload), len(compressed)) + compressed
        self.assertEqual(self.transforms.asset(source, 9, record), target)
        self.assertEqual(self.transforms.patch(source, payload), target)
        with self.assertRaises(ValueError):
            self.transforms.asset(source, 10, record)
        with self.assertRaises(ValueError):
            self.transforms.asset(source, 9, record[:-1])
        with self.assertRaises(ValueError):
            self.transforms.patch(source, payload[:-1])

    def test_yaz0_literals_backreferences_and_truncation(self):
        # Literal ABC, followed by a 21-byte copy with overlapping source/output.
        encoded = b'Yaz0' + struct.pack('>I', 24) + bytes(8) + b'\xe0ABC\x00\x02\x03'
        output = ctypes.create_string_buffer(24)
        self.assertTrue(self.transforms.library.decode(encoded, len(encoded), output, 24))
        self.assertEqual(output.raw, b'ABC' * 8)
        self.assertFalse(self.transforms.library.decode(encoded, len(encoded) - 1, output, 24))


if __name__ == '__main__':
    unittest.main()
