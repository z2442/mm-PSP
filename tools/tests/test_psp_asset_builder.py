"""Exercise the complete PSP asset builder with host file I/O and synthetic ROMs."""
from pathlib import Path
import ctypes
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.psp_port_asset_transform import permutation, word_partitions


class AssetBuilder:
    """Compile the production builder, replacing only PSP I/O and progress UI."""

    def __init__(self, table=None, manifest=None):
        self.directory = tempfile.TemporaryDirectory(prefix='mm-asset-builder-')
        directory = Path(self.directory.name)
        backend = ROOT / 'src/port/psp/backend'
        header = (backend / 'oot_psp_asset_loader.h').read_text()
        types = '''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int32_t s32;
typedef int SceUID;
typedef int64_t SceOff;
'''
        types += '\n'.join(re.findall(r'typedef struct OotPsp\w+ \{.*?\} OotPsp\w+;', header, re.S))
        (directory / 'oot_psp_asset_loader.h').write_text('#pragma once\n' + types + '''
extern const OotPspExternalAsset gOotPspExternalAssets[];
extern const size_t gOotPspExternalAssetCount;
const char* OotPsp_ResolveRootPath(const char*, char*, size_t);
''')
        (directory / 'oot_psp_asset_builder.h').write_text('''
#include "oot_psp_asset_loader.h"
s32 OotPspAssetBuilder_Ensure(void);
''')
        (directory / 'oot_psp_renderer.h').write_text('''
#include "oot_psp_asset_loader.h"
void OotPspRenderer_RenderFirstBootProgress(u32, const char*, bool);
''')
        (directory / 'pspiofilemgr.h').write_text('''
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#define PSP_O_RDONLY O_RDONLY
#define PSP_O_WRONLY O_WRONLY
#define PSP_O_CREAT O_CREAT
#define PSP_O_TRUNC O_TRUNC
#define PSP_SEEK_SET SEEK_SET
#define PSP_SEEK_END SEEK_END
#define sceIoOpen open
#define sceIoClose close
static ssize_t sceIoRead(int fd, void* buffer, size_t size) { return read(fd, buffer, size); }
#define sceIoWrite write
#define sceIoLseek32 lseek
#define sceIoRemove unlink
#define sceIoRename rename
#define sceIoMkdir mkdir
''')
        (directory / 'pspkernel.h').write_text('''
static void sceKernelDelayThread(unsigned delay) { (void)delay; }
''')
        if table is None:
            table = (ROOT / 'assets/psp/n64-us/asset_segments.c').read_text()
        (directory / 'table.c').write_text(table)
        if manifest is None:
            manifest = (ROOT / 'assets/psp/n64-us/asset_transform.z').read_bytes()
        (directory / 'manifest.bin').write_bytes(manifest)
        (directory / 'manifest.S').write_text(f'''
.section .rodata
.balign 16
.global gOotPspAssetTransformCompressed
gOotPspAssetTransformCompressed:
.incbin "{directory / 'manifest.bin'}"
.global gOotPspAssetTransformCompressedEnd
gOotPspAssetTransformCompressedEnd:
.section .note.GNU-stack,"",@progbits
''')
        harness = f'#include "{ROOT / "src/port/psp/mm_psp_asset_builder.c"}"\n'
        harness += '''
static const char* root;
static char lastError[128];
static u32 lastProgress;
const char* OotPsp_ResolveRootPath(const char* path, char* buffer, size_t capacity) {
    int written = snprintf(buffer, capacity, "%s/%s", root, path);
    return written > 0 && (size_t)written < capacity ? buffer : path;
}
void OotPspRenderer_RenderFirstBootProgress(u32 progress, const char* status, bool error) {
    lastProgress = progress;
    if (error) snprintf(lastError, sizeof(lastError), "%s", status);
}
int build(const char* rom, const char* output, const char* temporary) {
    SceUID fd = open(rom, O_RDONLY);
    lastError[0] = 0; lastProgress = 0;
    if (fd < 0) return 0;
    int result = OotPspAssetBuilder_Build(fd, output, temporary);
    close(fd); return result;
}
int ensure(const char* directory) {
    root = directory; lastError[0] = 0; lastProgress = 0;
    return OotPspAssetBuilder_Ensure();
}
const char* builder_error(void) { return lastError; }
u32 builder_progress(void) { return lastProgress; }
'''
        (directory / 'builder.c').write_text(harness)
        library = directory / 'builder.so'
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-shared', '-fPIC',
                        '-Wall', '-Wextra', '-Werror', '-DMM_PSP_ROM_INDEPENDENT=1',
                        '-I', str(directory), str(directory / 'builder.c'),
                        str(directory / 'table.c'), str(directory / 'manifest.S'),
                        '-lz', '-o', str(library)], check=True)
        self.library = ctypes.CDLL(str(library))
        self.library.build.argtypes = [ctypes.c_char_p] * 3
        self.library.ensure.argtypes = [ctypes.c_char_p]
        self.library.builder_error.restype = ctypes.c_char_p

    def build(self, rom, output, temporary):
        return bool(self.library.build(os.fsencode(rom), os.fsencode(output), os.fsencode(temporary)))

    def ensure(self, directory):
        return bool(self.library.ensure(os.fsencode(directory)))

    @property
    def error(self):
        return self.library.builder_error().decode()

    def close(self):
        self.directory.cleanup()


class AssetBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = bytes(range(16))
        cls.yaz0 = b'Yaz0' + struct.pack('>I', 24) + bytes(8) + b'\xe0ABC\x00\x02\x03'
        permutations = [permutation(parts) for parts in word_partitions(8)]
        payload = zlib.compress(bytes([0, 0]))
        manifest = (b'OPZ4' + struct.pack('<II', 1, len(permutations)) + b''.join(permutations)
                    + struct.pack('<IIII', 3, 16, 2, len(payload)) + payload)
        table = '''
#include "oot_psp_asset_loader.h"
const OotPspExternalAsset gOotPspExternalAssets[] = {
    {0x20000000,0x20000020,0x100000,0x100020,0,0,"deleted_syms"},
    {0x20000020,0x20000030,0x100020,0x100030,0,32,"raw"},
    {0x20000030,0x20000048,0x100030,0x100048,0,48,"compressed"},
    {0x20000048,0x20000058,0x100048,0x100058,1,72,"native"},
    {0x20000058,0x20000068,0x100058,0x100068,0,88,"deleted_static"},
};
const size_t gOotPspExternalAssetCount=sizeof(gOotPspExternalAssets)/sizeof(gOotPspExternalAssets[0]);
'''
        cls.builder = AssetBuilder(table, manifest)

    @classmethod
    def tearDownClass(cls):
        cls.builder.close()

    def make_rom(self):
        rom = bytearray(0x20800)
        for index, entry in enumerate([
            (0x100000, 0x100020, 0xFFFFFFFF, 0xFFFFFFFF),
            (0x100020, 0x100030, 0x20700, 0),
            (0x100030, 0x100048, 0x20720, 0x20720 + len(self.yaz0)),
            (0x100048, 0x100058, 0x20750, 0),
            (0x100058, 0x100068, 0xFFFFFFFF, 0xFFFFFFFF),
        ]):
            struct.pack_into('>IIII', rom, 0x1A500 + index * 16, *entry)
        rom[0x20700:0x20710] = self.raw
        rom[0x20720:0x20720 + len(self.yaz0)] = self.yaz0
        rom[0x20750:0x20760] = self.raw
        return rom

    def test_full_build_handles_mm_symbol_only_segments(self):
        with tempfile.TemporaryDirectory(prefix='mm-extraction-') as directory:
            root = Path(directory)
            rom, output, temporary = root / 'rom.z64', root / 'pack.bin', root / 'pack.tmp'
            rom.write_bytes(self.make_rom())
            self.assertTrue(self.builder.build(rom, output, temporary), self.builder.error)
            self.assertEqual(output.read_bytes(), bytes(32) + self.raw + b'ABC' * 8
                             + self.raw[:8][::-1] + self.raw[8:][::-1] + bytes(16))
            self.assertFalse(temporary.exists())
            self.assertEqual(self.builder.library.builder_progress(), 1000)

    def test_failed_decode_preserves_existing_pack_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory(prefix='mm-extraction-') as directory:
            root = Path(directory)
            rom, output, temporary = root / 'rom.z64', root / 'pack.bin', root / 'pack.tmp'
            data = self.make_rom()
            data[0x20720] = 0
            rom.write_bytes(data)
            output.write_bytes(b'existing pack')
            self.assertFalse(self.builder.build(rom, output, temporary))
            self.assertEqual(self.builder.error, 'Could not extract compressed')
            self.assertEqual(output.read_bytes(), b'existing pack')
            self.assertFalse(temporary.exists())

    def test_unpaired_missing_rom_marker_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='mm-extraction-') as directory:
            root = Path(directory)
            data = self.make_rom()
            struct.pack_into('>I', data, 0x1A500 + 12, 0)
            rom, output, temporary = root / 'rom.z64', root / 'pack.bin', root / 'pack.tmp'
            rom.write_bytes(data)
            self.assertFalse(self.builder.build(rom, output, temporary))
            self.assertTrue(self.builder.error)
            self.assertFalse(output.exists())
            self.assertFalse(temporary.exists())


if __name__ == '__main__':
    unittest.main()
