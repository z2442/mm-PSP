# MM US PSP interfaces and conversion recipes

All game asset bytes come from the asset pack created on the PSP from the user's
ROM. The build emits declarations and zero storage only. No extracted asset
archive is stored or restored.

- `build_interfaces.json`: C declarations, array/storage sizes, message layouts,
  zero-include counts and headers; no asset initializers.
- `asset_symbols.S` and `asset_segments.c`: symbol addresses and packed VROM metadata.
- `asset_transform.z`: byte-order/source-offset instructions for the PSP converter.
- `runtime_patches.z`: OPR3 source-offset and symbolic-pointer recipes that fill
  linked zero storage from the PSP-created pack. Messages are read through DMA.

See [the PSP port guide](../../../docs/psp-port.md) for maintainer validation.
