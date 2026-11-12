This is a work-in-progress port of ***The Legend of Zelda: Majoras Mask*** for the PSP, based on a fork of the [Decompilation of Ocarina of Time](https://github.com/zeldaret/oot).

## PSP builds

The [PSP workflow](https://github.com/z2442/mm-PSP/actions/workflows/psp-build.yml) builds without a ROM and publishes [the latest PSP package](https://github.com/z2442/mm-PSP/releases/tag/latest). Extract `mm-psp-n64-us.zip`, copy `MM_PSP` into `PSP/GAME` on your Memory Stick (`ms0:`) or PSP Go internal storage (`ef0:`), and add your own compressed US ROM as `MM_PSP/data/basrom.z64` before launching. PSP-2000/3000/Go memory is required.

For local builds, first-boot asset generation, controls, and validation, see [the PSP port guide](docs/psp-port.md).
