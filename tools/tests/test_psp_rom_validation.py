"""Run the production ROM validator with synthetic data and real zlib checksums."""
from pathlib import Path
import ctypes
import os
import re
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
MM_US_HEADER = bytes.fromhex('803712400000000f800800000000144b')
ROM_SIZE = 32 * 1024 * 1024
ROM_CRC = 0xB428D8A7


def function(source, name):
    start = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\s*\{', source, re.M).start()
    return source[start:source.index('\n}', start) + 2] + '\n'


class RomValidator:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='mm-rom-validator-')
        directory = Path(self.directory.name)
        builder = (ROOT / 'src/port/psp/mm_psp_asset_builder.c').read_text()
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef int32_t s32;
typedef int SceUID;
typedef int64_t SceOff;
#define PSP_SEEK_SET 0
#define PSP_SEEK_END 2
static const u8* image;
static size_t imageSize, position, readLimit;
static int64_t failAt;
static const char* error;
static SceOff sceIoLseek32(SceUID fd, s32 offset, int whence) {
    assert(fd == 7);
    position = (whence == PSP_SEEK_END ? imageSize : 0) + offset;
    return (SceOff)position;
}
static s32 sceIoRead(SceUID fd, void* output, size_t count) {
    assert(fd == 7);
    if (failAt >= 0 && position >= (uint64_t)failAt) return -1;
    if (count > readLimit) count = readLimit;
    if (position >= imageSize) return 0;
    if (count > imageSize - position) count = imageSize - position;
    memcpy(output, image + position, count); position += count;
    return (s32)count;
}
static void sceKernelDelayThread(unsigned delay) { (void)delay; }
static void OotPspAssetBuilder_ShowError(const char* status) { error = status; }
static void OotPspAssetBuilder_ShowProgress(u32 progress, const char* status) {
    assert(progress <= 100 && status != NULL);
}
'''
        source += '\n'.join(re.findall(r'^#define OOT_PSP_(?:ROM_(?:SIZE|CRC32)|IO_[A-Z_]+)[^\n]+', builder, re.M)) + '\n'
        source += function(builder, 'OotPspAssetBuilder_ReadAt')
        source += function(builder, 'OotPspAssetBuilder_ValidateRom')
        source += r'''
int validate(const u8* data, size_t size, size_t limit, int64_t failure) {
    image=data; imageSize=size; position=0; readLimit=limit; failAt=failure; error=NULL;
    return OotPspAssetBuilder_ValidateRom(7);
}
const char* validation_error(void) { return error; }
'''
        (directory / 'validator.c').write_text(source)
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-shared', '-fPIC', '-O2',
                        '-Wall', '-Wextra', '-Werror', str(directory / 'validator.c'),
                        '-lz', '-o', str(directory / 'validator.so')], check=True)
        self.library = ctypes.CDLL(str(directory / 'validator.so'))
        self.library.validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int64]
        self.library.validation_error.restype = ctypes.c_char_p

    def validate(self, image, read_limit=0x4000, fail_at=-1):
        return bool(self.library.validate(image, len(image), read_limit, fail_at))

    @property
    def error(self):
        return self.library.validation_error()

    def close(self):
        self.directory.cleanup()


def synthetic_rom():
    # No game data: use zeros, the public MM US header, and four CRC correction
    # bytes. Solve the CRC's 32-bit linear map so the real checksum path runs.
    image = bytearray(ROM_SIZE)
    image[:16] = MM_US_HEADER
    base = zlib.crc32(image)
    basis = {}
    for bit in range(32):
        index = len(image) - 4 + bit // 8
        image[index] ^= 1 << (bit % 8)
        value = zlib.crc32(image) ^ base
        image[index] ^= 1 << (bit % 8)
        mask = 1 << bit
        while value:
            pivot = value.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = (value, mask)
                break
            value ^= basis[pivot][0]
            mask ^= basis[pivot][1]
    value, correction = ROM_CRC ^ base, 0
    while value:
        pivot = value.bit_length() - 1
        delta, mask = basis[pivot]
        value ^= delta
        correction ^= mask
    image[-4:] = correction.to_bytes(4, 'little')
    assert zlib.crc32(image) == ROM_CRC
    return bytes(image)


class RomValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = RomValidator()
        cls.image = synthetic_rom()

    @classmethod
    def tearDownClass(cls):
        cls.validator.close()

    def test_mm_us_header_and_checksum_are_accepted(self):
        self.assertTrue(self.validator.validate(self.image), self.validator.error)
        self.assertIsNone(self.validator.error)

    def test_partial_reads(self):
        self.assertTrue(self.validator.validate(self.image, read_limit=4093), self.validator.error)

    def test_oot_header_is_rejected(self):
        image = bytes.fromhex('803712400000000f8000040000001449') + self.image[16:]
        self.assertFalse(self.validator.validate(image))
        self.assertIn(b'Majora', self.validator.error)

    def test_wrong_size_and_byte_order_are_rejected(self):
        self.assertFalse(self.validator.validate(self.image[:-1]))
        self.assertFalse(self.validator.validate(b'\x37\x80\x40\x12' + self.image[4:]))

    def test_corrupt_body_is_rejected_by_checksum(self):
        image = self.image[:20] + b'\x01' + self.image[21:]
        self.assertFalse(self.validator.validate(image))
        self.assertIn(b'checksum', self.validator.error)

    def test_storage_read_failure(self):
        self.assertFalse(self.validator.validate(self.image, fail_at=0x10000))
        self.assertIn(b'Could not read', self.validator.error)


if __name__ == '__main__':
    unittest.main()
