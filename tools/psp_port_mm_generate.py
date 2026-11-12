#!/usr/bin/env python3

"""Run the vendored PSP metadata generators against the MM repository."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from buildtools import dmadata as mm_dmadata
from version import version_config as mm_version_config


ROOT = Path(__file__).resolve().parents[1]


class MmVersionConfigAdapter:
    @staticmethod
    def load_version_config(version: str):
        config = mm_version_config.load_version_config(version)
        # MM US is an NTSC English build. The OoT generator uses this only to
        # select optional message-table metadata; MM does not publish those
        # table addresses in config.yml, so the lists remain empty.
        config.text_lang = "NTSC"
        return config


def load_backend_tool(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mm_psp_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load vendored PSP generator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    if hasattr(module, "version_config"):
        module.version_config = MmVersionConfigAdapter
    if hasattr(module, "dmadata"):
        module.dmadata = mm_dmadata
    if name == "psp_port_asset_segments":
        original_build_entries = module.build_entries

        def mm_build_entries(version):
            entries = original_build_entries(version)
            # MM's linked GfxPrint fonts come from boot, outside code. Append
            # its raw source without renumbering existing packed VROM handles.
            source = ROOT / "extracted" / version / "baserom" / "boot"
            ranges = module.read_original_vrom_ranges(version)
            start = module.align(entries[-1]["vrom_end"], module.EXTERNAL_VROM_ALIGN)
            original_start, original_end = ranges["boot"]
            entries.append(dict(name="boot", source=source, size=source.stat().st_size,
                                vrom_start=start, vrom_end=start + source.stat().st_size,
                                original_vrom_start=original_start, original_vrom_end=original_end))
            return entries

        module.build_entries = mm_build_entries
        original_load_xml_offsets = module.NativeAssetContext._load_xml_offsets
        original_discover_native_objects = module.NativeAssetContext._discover_native_objects
        original_asset_kind = module.NativeAssetContext._asset_kind_for_object_path
        original_build_native_segment = module.NativeAssetContext.build_native_segment
        original_offset_from_name = module.NativeAssetContext._symbol_offset_from_name
        original_resolve_relocation = module.NativeAssetContext._resolve_relocation_symbol

        def mm_load_xml_offsets(self):
            original_load_xml_offsets(self)
            self.mm_archive_segment_names = set()
            xml_roots = [
                ROOT / "assets" / "xml" / kind
                for kind in ("archives", "boot", "code", "interface")
            ]
            for xml_root in xml_roots:
                if not xml_root.exists():
                    continue
                for xml_path in xml_root.glob("**/*.xml"):
                    if not self._should_use_xml(xml_path):
                        continue
                    try:
                        tree_root = module.ET.parse(xml_path).getroot()
                    except module.ET.ParseError as exc:
                        raise ValueError(f"failed to parse {xml_path}: {exc}") from exc

                    for file_elem in tree_root.iter("File"):
                        segment_name = file_elem.attrib.get("Name")
                        segment_text = file_elem.attrib.get("Segment")
                        if not segment_name:
                            continue
                        if segment_name.endswith(".unarchive"):
                            segment_name = segment_name.removesuffix(".unarchive")
                        self.mm_archive_segment_names.add(segment_name)
                        if segment_text is not None:
                            self.segment_ids[segment_name] = int(segment_text, 0)

                        offsets = self.xml_symbol_offsets.setdefault(segment_name, {})
                        offsets.setdefault(segment_name, 0)
                        for elem in file_elem.iter():
                            if elem.tag == "Texture":
                                format_text = elem.attrib.get("Format")
                                width_text = elem.attrib.get("Width")
                                height_text = elem.attrib.get("Height")
                                offset_text = elem.attrib.get("Offset")
                                if all(value is not None for value in (format_text, width_text, height_text, offset_text)):
                                    texture_size = module.texture_size_bytes(
                                        format_text, int(width_text, 0), int(height_text, 0)
                                    )
                                    if texture_size is not None:
                                        self._add_texture_range(
                                            segment_name, module.parse_xml_int(offset_text), texture_size
                                        )

                                tlut_offset_text = elem.attrib.get("TlutOffset")
                                if (format_text is not None) and (tlut_offset_text is not None):
                                    tlut_size = module.TEXTURE_TLUT_BYTES.get(format_text.lower())
                                    if tlut_size is not None:
                                        self._add_texture_range(
                                            segment_name, module.parse_xml_int(tlut_offset_text), tlut_size
                                        )

                            symbol_name = elem.attrib.get("Name")
                            offset_text = elem.attrib.get("Offset")
                            if (symbol_name is not None) and (offset_text is not None):
                                offsets[symbol_name] = module.parse_xml_int(offset_text)

        def mm_discover_native_objects(self):
            original_discover_native_objects(self)
            for segment_name in self.entries_by_name:
                existing = list(self.segment_object_paths.get(segment_name, []))
                extra = []
                for kind in ("archives", "boot", "code", "interface"):
                    for pattern in (
                        f"assets/{kind}/{segment_name}/*.o",
                        f"extracted/{self.version}/assets/{kind}/{segment_name}/*.o",
                    ):
                        extra.extend(path for path in sorted(self.build_root.glob(pattern)) if path.is_file())
                for pattern in (
                    f"assets/archives/*/{segment_name}.o",
                    f"extracted/{self.version}/assets/archives/*/{segment_name}.o",
                    f"assets/scenes/*/{segment_name}.o",
                    f"extracted/{self.version}/assets/scenes/*/{segment_name}.o",
                    f"assets/misc/*/{segment_name}.o",
                    f"extracted/{self.version}/assets/misc/*/{segment_name}.o",
                    f"assets/text/{segment_name}.o",
                ):
                    extra.extend(path for path in sorted(self.build_root.glob(pattern)) if path.is_file())
                paths = list(dict.fromkeys(existing + extra))
                if paths:
                    self.segment_object_paths[segment_name] = paths

        def mm_asset_kind(self, path):
            kind = original_asset_kind(self, path)
            if kind is not None:
                return kind
            try:
                parts = path.relative_to(self.build_root).parts
            except ValueError:
                return None
            for index in range(len(parts) - 1):
                if parts[index] == "assets" and parts[index + 1] in {
                    "archives", "boot", "code", "interface", "text"
                }:
                    return "textures"
            return None

        def mm_build_native_segment(self, entry):
            # YAR archives stay compressed in the packed image. Their C/XML
            # metadata is used only to emit segmented offsets for code that
            # indexes the decompressed archive at runtime.
            if str(entry["name"]) in self.mm_archive_segment_names:
                return None
            return original_build_native_segment(self, entry)

        module.NativeAssetContext._load_xml_offsets = mm_load_xml_offsets
        module.NativeAssetContext._discover_native_objects = mm_discover_native_objects
        module.NativeAssetContext._asset_kind_for_object_path = mm_asset_kind
        module.NativeAssetContext.build_native_segment = mm_build_native_segment

        def mm_offset_from_name(self, segment_id, segment_size, symbol_name):
            matches = list(module.OFFSET_TOKEN_RE.finditer(symbol_name))
            # MM's extractor names animation arrays and skeleton limb-pointer
            # arrays after their parent header (for example *Skel_003A20Limbs).
            # Let source-order inference place those arrays before the known
            # XML header instead of treating the parent's offset as their own.
            # Some asset prefixes themselves contain six consecutive hex
            # digits (for example REDEADCollision -> EDEADC).  Only the final
            # token can be the extractor's offset, so do not require it to be
            # the sole regex match when deciding whether it names a parent.
            if matches and (
                matches[-1].end() != len(symbol_name) or "_KeyFrameLimbs_" in symbol_name
            ):
                return None
            return original_offset_from_name(self, segment_id, segment_size, symbol_name)

        module.NativeAssetContext._symbol_offset_from_name = mm_offset_from_name

        def mm_resolve_relocation(self, current_segment, symbol, addend):
            # Yukimura's snowball model branches to the game's global empty
            # display list. Packed assets cannot contain native code/data
            # pointers, so branch to this display list's own EndDL command.
            # The command is the fourth entry of DL_000890 (0x890 + 3 * 8).
            if current_segment == "object_yukimura_obj" and symbol.name == "D_801AEFA0":
                return (0x060008A8 + addend) & 0xFFFFFFFF
            return original_resolve_relocation(self, current_segment, symbol, addend)

        module.NativeAssetContext._resolve_relocation_symbol = mm_resolve_relocation
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MM metadata for the vendored PSP backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    segments = subparsers.add_parser("segments")
    segments.add_argument("version")
    segments.add_argument("asm_output", type=Path)
    segments.add_argument("table_output", type=Path)
    segments.add_argument("data_dir", type=Path)
    segments.add_argument("--build-root", type=Path, default=None)

    audio = subparsers.add_parser("audio")
    audio.add_argument("version")
    audio.add_argument("output", type=Path)

    args = parser.parse_args()
    if args.command == "segments":
        tool = load_backend_tool("psp_port_asset_segments")
        tool.emit(args.version, args.asm_output, args.table_output, args.data_dir, args.build_root)
        # MM addresses the current master display-list and framebuffer through
        # N64 segments 0x0E and 0x0F.  Keep these as absolute symbols in the
        # same assembly file as generated asset addresses so the PRX relocation
        # stripping pass protects them from module-base relocation too.
        with args.asm_output.open("a", encoding="utf-8") as output:
            output.write(
                "\n.global D_0E000000\n"
                ".equ D_0E000000, 0x0E000000\n"
                ".global D_0F000000\n"
                ".equ D_0F000000, 0x0F000000\n"
            )
    else:
        tool = load_backend_tool("psp_port_audio_tables")
        tool.generate(args.version, args.output)


if __name__ == "__main__":
    main()
