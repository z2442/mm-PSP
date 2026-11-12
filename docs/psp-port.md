# Majora's Mask PSP port

The PSP port runs MM's native game code with a vendored Allegrex/libultra,
F3DEX2/GU renderer, audio mixer, controls, video output, and HOME menu from
[z2442/oot-PSP](https://github.com/z2442/oot-PSP). The shared backend was updated
through `d4ad96c045d39e18a80f7a1f5d7f8fdba9621d38` (November 10, 2026).
No sibling OoT checkout is needed.

MM requires PSP-2000/3000/Go expanded memory, or PPSSPP with a Slim memory
model. The EBOOT requests `MEMSIZE=1`. Its game arena remains 8 MiB, allocated
at runtime separately from the 1 MiB newlib font/bootstrap heap. PSP-1000 is
unsupported. Renderer storage and temporary conversion/cache allocations use
separate user-partition blocks.

## Build and install

Install PSPSDK, intraFont, and the VME-capable Media Engine library pinned in
[the workflow](../.github/workflows/psp-build.yml). Host tools include GNU Make,
Python 3 with PyYAML, and MIPS binutils. A normal PSP build requires no ROM,
extraction tree, or `make setup`:

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install 'PyYAML>=6.0.1,<7.0.0'
./psp.sh VERSION=n64-us
python3 tools/package_psp.py build/psp-port/n64-us build/mm-psp-n64-us.zip
```

Use `JOBS=8 ./psp.sh` to limit parallelism. `MAKE=gmake` is supported, and macOS
selects `gmake` by default. Builds are incremental; configuration changes
invalidate compiled objects. `make psp-port-clean` removes the selected PSP
build directory.

Keep PSP build output in `build/psp-port/n64-us`; the installer ZIP is
`build/mm-psp-n64-us.zip`. Use a temporary directory outside the checkout for
private reference builds.

Extract the ZIP and copy `MM_PSP` into `PSP/GAME` on either storage device:

- PSP Go internal storage: `ef0:/PSP/GAME/MM_PSP/`
- Memory Stick or PSP Go M2 card: `ms0:/PSP/GAME/MM_PSP/`

The same package works on both. Add your own **compressed,
big-endian US Majora's Mask ROM**, 32 MiB, CRC32 **B428D8A7**, as
`MM_PSP/data/basrom.z64` (`baserom.z64` also works). The installed layout is:

```text
PSP/GAME/MM_PSP/
├── EBOOT.PBP
├── Plugins/dvemgr.prx
├── README.txt
└── data/basrom.z64          # supplied by the user
```

The first launch validates the ROM, displays conversion progress, and creates
`data/segments/oot_psp_assets.bin` through a temporary file. The retained filename
is a backend compatibility detail; every asset comes from MM. Later launches
reuse the pack. Delete it to rebuild. The executable's zero placeholders are
filled from the pack each launch. Message arrays preserve offsets and lengths;
message text is read directly from the pack. The package contains no ROM or converted
assets. Flash saves are stored as `mm-psp-save.bin` beside the EBOOT.
Completed writes are reported to MM's save state machine so name entry and
options return after their normal two-second confirmation delay. Game deadlines
use the N64 counter's time units.

The launch directory determines the storage for the ROM, asset pack, saves,
`controls.ini`, `video.ini`, plugins, and sleep recovery data. A Go internal
installation reads `ef0:/PSP/GAME/MM_PSP/data/basrom.z64`, for example. Startup
resolves bare or relative executable names against the launch working directory;
later working-directory changes do not move storage to another device. Separate
installations keep separate saves and settings. Copy the entire `MM_PSP` folder
when moving between internal storage and a card.

## Rendering and presentation

The backend includes GPU ambient/diffuse lighting, immutable native mesh
caching, batched GE submissions, improved texture stride/mirroring and cache
reuse, decal depth fixes, zero-opacity fog suppression, and effect material
fixes. MM's two-cycle material cache, animated water, per-tile palettes, HUD
projection, and native motion blur are retained. Player silhouette shadows use
the GU stamp path; MM's fractional shadow rows are quantized to pixel rows.

HOME > Video Settings offers 20 FPS (default) and 60 FPS presentation, VSync,
LCD/TV output, and aspect ratio. Save `video.ini` to persist settings. Game logic
keeps MM's original update interval; 60 FPS replays immutable display lists with
matrix interpolation. Frame history resets on state/scene/room/camera changes,
HOME, video mode changes, and sleep. Presentation waits run on a video thread.
The shortened foreground camera plane preserves the original fog curve and
first-person model-selection threshold.
Normal cutscenes retain MM's original near plane for depth precision. Texture
sampler modes are restored when returning from fused materials to cached tree
layers and shadows. Motion blur restarts each GU list on the active draw buffer,
uses unlit sprites, and refreshes its history texture before sampling it.
Clock Town's wrapped tile bounds use 12-bit extents consistently for imports,
mirroring, and both layers' UVs. Scrolling across zero keeps the same texture
dimensions and allocation.
Texture imports invalidate the remembered draw binding because uploads and
GPU shadow generation can select another image internally. The base texture is
rebound after both layers are prepared. Creating a shader submits the previous
material's buffered geometry before changing the live GPU state.

LCD uses triple buffering; TV modes use double buffering to fit VRAM. DVE output
requires supported hardware, a cable, and `Plugins/dvemgr.prx`. The firmware font
`flash0:/font/ltn0.pgf` supplies HOME text through intraFont, with a bitmap fallback.

## Audio and sleep

MM synthesizes at 32 kHz. The Media Engine mixes audio commands by default,
while MM's command-list construction remains on Allegrex. Output uses software
resampling and a normal PSP audio channel. Diagnostic overrides include:

```sh
PSP_AUDIO_MEDIA_ENGINE=0 ./psp.sh
PSP_AUDIO_HARDWARE_SRC=1 ./psp.sh
PSP_AUDIO_DIAGNOSTICS=1 PSP_WAKE_DIAGNOSTICS=1 ./psp.sh
```

The power callback requests coordinated sleep. The game thread drains graphics
and audio, snapshots/releases volatile asset memory, and waits for firmware
resume completion before restoring assets, graphics, clocks, frame pacing, and
the ME worker. Failed restoration stays on a retry/quit screen. MM's 32 kHz
pitch range does not need OoT's 22.05 kHz four-part high-pitch synthesis path.

## CI and validation

The PSP workflow runs on pushes, pull requests, and manual requests. It verifies
pinned toolchain and ME-library downloads, builds, runs host regressions, and
uploads `mm-psp-build` containing `mm-psp-n64-us.zip` for 30 days. Successful
push/manual builds of the default branch update the rolling `latest`
prerelease. An older rerun cannot replace a newer branch-head release.

Run host regressions after building:

```sh
python3 tools/run_psp_tests.py
```

The tests exercise actual renderer/texture/transform code, VFPU instruction
models, frame interpolation and pacing, video workers, sleep recovery,
`ef0:`/`ms0:` storage routing, MM ROM header/checksum validation, and the complete
asset builder with raw, Yaz0, and MM's zero-filled symbol-only segments. Synthetic
ROM fixtures also check temporary-file cleanup after failed extraction. The tests
also cover file-select save completion, two-second deadlines, owl backup writes,
blur across rotating framebuffers, and sampler restoration after material/effect
changes. Clock Town wall tests sweep both tiles across the complete coordinate
wrap and compare scrolling combined-material pixels. Material-transition tests
also cover secondary uploads, cache hits, mutable images, GPU shadow imports,
and cached draw bindings after uploads. Shader lifecycle tests run the real
frontend lookup and GU cache construction, checking that first-use and cached
lookups leave pending geometry and active GPU state identical. Only the final
pipeline switch flushes and selects a shader. Layer tests run clipped triangles
through emission and both draw passes, checking independent UVs and identical
positions/depth bias, including multiply materials too large for the combined
texture cache. VFPU instruction checks also verify interpolated positions and
UVs across all six planes. They do not emulate PSP rasterization.
MM's letterbox regression also runs its native bar-drawing function through the
renderer, checking every row against the scaled scene scissor for all bar sizes
from 0 to 32 on LCD and TV. Both use the same endpoint rounding so Z-targeting
cannot leave clear-color gaps along the black bars.
On hardware,
check Clock Town floors and scrolling water, HUD and pause, aiming, animated
limbs and lighting, state transitions, TV changes, and repeated sleep/wake with
sound. Measure performance on hardware before claiming an FPS improvement.

## Refreshing build interfaces and conversion recipes

The repository contains C interfaces, symbol addresses, array sizes and
source-offset conversion recipes. Compilation emits **zero storage only** for
assets. There is no pre-extracted asset archive or archive restore step.
Every live asset is reconstructed from the PSP-created pack before game code
runs. The build regenerates schedule code from the checked-in schedule scripts.

Maintainers can refresh the interface descriptions and recipes from a private
reference build:

```sh
make setup
make -j8 assets
./psp.sh MM_PSP_ROM_INDEPENDENT=0 PSP_BUILD_DIR=/tmp/mm-psp-reference/n64-us
python3 tools/psp_port_build_interfaces.py create \
    /tmp/mm-psp-reference/n64-us extracted/n64-us/baserom assets/psp/n64-us
python3 tools/psp_port_runtime_patches.py create n64-us \
    /tmp/mm-psp-reference/n64-us/mm-psp-port.base.elf \
    /tmp/mm-psp-reference/n64-us/oot_psp_asset_segments.c \
    extracted/n64-us/baserom assets/psp/n64-us/runtime_patches.z
```

`build_interfaces.json` describes declarations and storage sizes. It contains no
asset initializers; source includes contain only zeros. Runtime pointer targets
are resolved by symbol name so no pointer-bearing asset initializer is needed
at compile time. The linker retains this zero storage for first-boot loading.
Never commit ROMs, extraction trees, reference ELFs, or the converted asset
pack. ROM-independent interfaces currently support `n64-us`.

After a fresh ROM-independent build, validate the metadata against the private
reference (the optional ROM argument also checks the actual C Yaz0 decoder):

```sh
python3 tools/validate_psp_metadata.py \
    /tmp/mm-psp-reference/n64-us build/psp-port/n64-us extracted/n64-us/baserom \
    --rom baseroms/n64-us/baserom.z64
```

This checks packed bytes, runtime conversion recipes, every changed live
initialized object, and linked message sizes and ordering.
