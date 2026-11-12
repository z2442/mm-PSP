# Vendored OoT PSP backend

Source: [z2442/oot-PSP at d4ad96c045d39e18a80f7a1f5d7f8fdba9621d38](https://github.com/z2442/oot-PSP/tree/d4ad96c045d39e18a80f7a1f5d7f8fdba9621d38/src/port/psp)
(November 10, 2026). Only committed upstream source was imported.

MM retains its two-cycle material cache, per-tile palettes, HUD projection,
8 MiB arena, flash saves, archive handling, 32 kHz synthesis, partition-backed
allocations, and native motion blur. Its additional material passes use the
new 36-byte vertex format and GE upload arena. MM still constructs audio
commands on Allegrex and mixes them on ME.

MM also restores sampler settings after fused material/effect passes and converts
PSP RTC timestamps to N64 counter units for game deadlines. Its flash shim retains
a completed result until MM collects it. The native blur wrapper restarts lists
through the shared framebuffer selector and disables lighting for its sprites.
Tile-size calculations preserve the RDP's 12-bit wrapping for Clock Town wall
layers, scrolling origins, mirror decisions, and texture coordinates.
The final material setup selects its draw texture after secondary-layer and
GPU-shadow uploads; the backend suppresses redundant binding commands. Shader
construction only populates the cache. The pipeline flushes previous geometry
and selects the shader at the same point for both first-use and cached materials.
OoT's Z-focus scissor fix (`580b175c79caab607cce5f15f409aad55c23ad32`)
is retained. MM additionally scales the scene scissor and rectangle endpoints
consistently, preventing uncovered rows between the scene and letterbox bars.

The MM integration in `../mm_psp_*.c` owns startup, scheduling, first-boot ROM
parameters, and game-specific hooks. First-boot metadata, packaging, and the
PSP CI workflow are adapted from the same upstream revision. OoT-only actor,
scene, equipment, and 22.05 kHz synthesis changes are represented by their MM
counterparts where applicable, rather than introducing OoT game data.

See [the MM PSP guide](../../../../docs/psp-port.md) for builds and validation.
