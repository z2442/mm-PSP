#!/usr/bin/env python3
"""Generate C interfaces and zero storage; real asset bytes are supplied by PSP at boot."""
from __future__ import annotations
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.psp_port_asset_segments import ElfObject
from tools.psp_port_asset_transform import build_transform

DECL = re.compile(r'^(?P<prefix>(?:(?:static|const|NO_REORDER|ALIGNED\([^\n]*?\))\s+)*)(?P<type>\w+)\s+(?P<name>\w+)(?P<dimensions>(?:\[[^\]\n]*\]\s*)*)\s*=\s*\{', re.M)


def reference_inputs(build, version):
    inputs = {}
    for dep in list((build / 'src').rglob('*.d')) + list((build / 'assets/text').glob('*.d')):
        for token in dep.read_text().replace('\\\n', ' ').split():
            name = token.rstrip(':')
            if name.startswith((f'extracted/{version}/', f'build/{version}/')) and (ROOT / name).is_file():
                inputs.setdefault(name, dep.with_suffix('.o'))
    return inputs


def create(build, extracted, output):
    version = build.name
    inputs = reference_inputs(build, version)
    objects = {}
    def symbols(path):
        if path not in objects:
            elf = ElfObject(path)
            objects[path] = {s.name: s.size for values in elf.symtabs.values() for s in values if s.size and s.info & 15 == 1}
        return objects[path]
    linked = symbols(build / 'mm-psp-port.base.elf')
    result = dict(format=1, version=version, headers={}, units={}, zeros={}, messages={}, schedules=[], word_arrays=[])
    inputs['@/oot_psp_audio_tables.c'] = build / 'oot_psp_audio_tables.o'
    for name, owner in sorted(inputs.items()):
        path = build / name[2:] if name.startswith('@/') else ROOT / name
        text = path.read_text()
        if name.endswith('.schl.inc'):
            result['schedules'].append(name)
        elif name.endswith(('/text/message_data.h', '/text/message_data_staff.h', '/text/message_data.enc.h', '/text/message_data_staff.enc.h')):
            staff = '_staff' if 'staff' in path.name else ''
            result['messages'][name] = [[ident, kind, pos, linked['_message_' + ident + staff]]
                for ident, kind, pos in re.findall(r'DEFINE_MESSAGE\((0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),', text)]
        elif name.endswith('.h'):
            # These are C declarations, typedefs and size macros, never initializers.
            if re.search(r'^\s*(?:static\s+)?(?:const\s+)?\w+\s+\w+\[.*?\]\s*=\s*\{', text, re.M):
                raise ValueError(f'asset initializer in interface header: {name}')
            result['headers'][name] = text
        elif name.endswith(('.inc', '.inc.c')):
            without_comments = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)
            if 'VTX(' in without_comments:
                result['zeros'][name] = ['vertices', len(re.findall(r'\bVTX\(', without_comments))]
            else:
                tokens = [part.strip() for part in without_comments.split(',') if part.strip()]
                if any(not re.fullmatch(r'(?:0x[0-9a-fA-F]+|[0-9]+)[uUlL]*', token) for token in tokens):
                    raise ValueError(f'unsupported initializer shape: {name}')
                result['zeros'][name] = ['scalars', len(tokens)]
        elif name.endswith('.c'):
            sizes = symbols(owner)
            declarations = []
            for match in DECL.finditer(text):
                ident = match['name']
                if ident not in sizes:
                    raise ValueError(f'missing reference declaration size: {name}:{ident}')
                dimensions = match['dimensions'].strip()
                declarations.append([match['prefix'].strip(), match['type'], ident, sizes[ident], dimensions])
                if match['type'] == 'u64':
                    result['word_arrays'].append(ident)
            preamble = [line for line in re.findall(r'^#(?:include|pragma|define|undef)[^\n]*', text, re.M) if not (line.startswith('#include') and re.search(r'\.inc(?:\.c)?[\">]', line))]
            preamble += re.findall(r'typedef struct\b.*?\}\s*\w+;', text, re.S)
            result['units'][name] = dict(preamble=preamble, declarations=declarations)
        else:
            raise ValueError(f'unsupported interface input: {name}')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'build_interfaces.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    shutil.copyfile(build / 'oot_psp_asset_segments.S', output / 'asset_symbols.S')
    shutil.copyfile(build / 'oot_psp_asset_segments.c', output / 'asset_segments.c')
    (output / 'asset_transform.z').write_bytes(build_transform(build, extracted))
    print(f'Wrote interface metadata: {len(result["headers"])} headers, {len(result["units"])} declaration units, no asset initializers.')


def emit(metadata, build):
    data = json.loads((metadata / 'build_interfaces.json').read_text())
    if data['format'] != 1:
        raise ValueError('unsupported build interface format')
    generated = build / 'generated'
    def write(name, text):
        relative = Path(name[2:] if name.startswith('@/') else name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'unsafe interface path: {name}')
        target = (build if name.startswith('@/') else generated) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    for name, text in data['headers'].items():
        write(name, text)
    for name, unit in data['units'].items():
        lines = list(unit['preamble'])
        for prefix, kind, ident, size, dimensions in unit['declarations']:
            if dimensions == '[]':
                dimensions = f'[{size} / sizeof({kind})]'
            section = '.rodata.mm_psp_placeholders' if 'const' in prefix.split() else '.data.mm_psp_placeholders'
            lines.append(f'{prefix} {kind} {ident}{dimensions} __attribute__((used, section("{section}"))) = {{0}};')
            lines.append(f'_Static_assert(sizeof({ident}) == {size}, "PSP interface size: {ident}");')
        write(name, '\n'.join(lines) + '\n')
    for name, (kind, count) in data['zeros'].items():
        write(name, ('{0},\n' if kind == 'vertices' else '0,\n') * count)
    for name, entries in data['messages'].items():
        write(name, ''.join(f'DEFINE_MESSAGE({ident}, {kind}, {pos}, '+
              ('{ [' + str(size - 1) + '] = 0 }' if '.enc.' in name else '0') + ')\n'
              for ident, kind, pos, size in entries))
    for name in data['schedules']:
        source = ROOT / name.removeprefix(f'build/{data["version"]}/').removesuffix('.inc')
        target = generated / name
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(ROOT / 'tools/buildtools/schc.py'), '-o', str(target), str(source)], check=True)
    shutil.copyfile(metadata / 'asset_symbols.S', build / 'oot_psp_asset_segments.S')
    shutil.copyfile(metadata / 'asset_segments.c', build / 'oot_psp_asset_segments.c')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('create')
    make.add_argument('reference_build', type=Path)
    make.add_argument('extracted_dir', type=Path)
    make.add_argument('metadata_dir', type=Path)
    build = sub.add_parser('emit')
    build.add_argument('metadata_dir', type=Path)
    build.add_argument('build_dir', type=Path)
    args = parser.parse_args()
    if args.command == 'create':
        create(args.reference_build, args.extracted_dir, args.metadata_dir)
    else:
        args.build_dir.mkdir(parents=True, exist_ok=True)
        emit(args.metadata_dir, args.build_dir)


if __name__ == '__main__':
    main()
