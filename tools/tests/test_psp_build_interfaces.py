"""Build interfaces must compile to zero storage without an extracted asset archive."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.psp_port_build_interfaces import emit


class BuildInterfacesTest(unittest.TestCase):
    def test_repository_has_no_asset_archive(self):
        self.assertEqual(list((ROOT / 'assets/psp').rglob('*.zip')), [])

    def test_emit_produces_zero_declarations_and_includes(self):
        with tempfile.TemporaryDirectory(prefix='mm-interfaces-') as directory:
            root = Path(directory)
            metadata, build = root / 'metadata', root / 'build'
            metadata.mkdir()
            build.mkdir()
            data = dict(format=1, version='n64-us',
                        headers={'include/assets.h': '#include <stdint.h>\ntypedef uint32_t u32;\n'},
                        units={'unit.c': dict(preamble=['#include "include/assets.h"'], declarations=[
                            ['', 'u32', 'gValues', 16, '[]'], ['const', 'u32', 'gTexture', 32, '[]']])},
                        zeros={'texture.inc.c': ['scalars', 4], 'vertices.inc': ['vertices', 2]},
                        messages={}, schedules=[], word_arrays=[])
            (metadata / 'build_interfaces.json').write_text(json.dumps(data))
            (metadata / 'asset_symbols.S').write_text('')
            (metadata / 'asset_segments.c').write_text('')
            emit(metadata, build)
            generated = build / 'generated'
            self.assertEqual((generated / 'texture.inc.c').read_text(), '0,\n' * 4)
            self.assertEqual((generated / 'vertices.inc').read_text(), '{0},\n' * 2)
            source = (generated / 'unit.c').read_text()
            self.assertEqual(source.count(' = {0};'), 2)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(generated),
                            '-c', str(generated / 'unit.c'), '-o', str(root / 'unit.o')], check=True)


if __name__ == '__main__':
    unittest.main()
