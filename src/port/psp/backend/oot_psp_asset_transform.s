.section .rodata
.balign 16

.global gOotPspAssetTransformCompressed
gOotPspAssetTransformCompressed:
#if MM_PSP_ROM_INDEPENDENT
.incbin "assets/psp/n64-us/asset_transform.z"
#endif

.global gOotPspAssetTransformCompressedEnd
gOotPspAssetTransformCompressedEnd:

