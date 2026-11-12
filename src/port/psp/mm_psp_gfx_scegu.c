#include "oot_psp_gfx_ext.h"

/*
 * Wrap the vendored GU backend's native framebuffer-effect entry point so MM
 * can add its motion blur without duplicating the complete implementation.
 */
#define gfx_scegu_apply_vismono MmPspGfx_ApplyVisMonoOriginal
/* MM ships intraFont; enable the firmware font loader in the shared backend. */
#define OOT_PSP_USE_INTRAFONT 1
#include "gfx/gfx_scegu.c"
#undef gfx_scegu_apply_vismono

typedef struct MmPspMotionBlurVertex {
    uint16_t u;
    uint16_t v;
    uint32_t color;
    uint16_t x;
    uint16_t y;
    uint16_t z;
} __attribute__((aligned(4))) MmPspMotionBlurVertex;

/* Narrow sprites keep linear framebuffer reads friendly to the GE texture
 * cache. Batch all slices sharing a texture image into a single draw. */
#define MM_PSP_MOTION_BLUR_SLICE_WIDTH 32

static void* sMmPspMotionBlurBuffer;
static size_t sMmPspMotionBlurBufferSize;
static bool sMmPspMotionBlurValid;
static int sMmPspMotionBlurBufferWidth;
static int sMmPspMotionBlurScreenWidth;
static int sMmPspMotionBlurScreenHeight;
static int sMmPspMotionBlurPixelFormat;
static bool sMmPspMotionBlurAllocFailed;

static bool MmPspGfx_IsMotionBlurCommand(uint8_t primR, uint8_t primG, uint8_t primB,
                                         uint8_t envR, uint8_t envG) {
    return (primR == MM_PSP_MOTION_BLUR_PRIM_R) &&
           (primG == MM_PSP_MOTION_BLUR_PRIM_G) &&
           (primB == MM_PSP_MOTION_BLUR_PRIM_B) &&
           (envR == MM_PSP_MOTION_BLUR_ENV_R) &&
           (envG == MM_PSP_MOTION_BLUR_ENV_G);
}

static bool MmPspGfx_EnsureMotionBlurBuffer(void) {
    size_t textureHeight;
    size_t size;

    if (sMmPspMotionBlurBuffer != NULL) {
        return true;
    }
    if (sMmPspMotionBlurAllocFailed || (sFramebufferCapacity == 0)) {
        return false;
    }

    /* GU textures are power-of-two and at most 512 pixels high.  Allocate the
     * padding too so its texture prefetch cannot run beyond the history block. */
    textureHeight = (size_t)nextpow2(sMaxScreenHeight);
    size = (size_t)sMaxBufferWidth * textureHeight * (size_t)sColorPixelSize;
    sMmPspMotionBlurBuffer = memalign(64, size);
    if (sMmPspMotionBlurBuffer == NULL) {
        sMmPspMotionBlurAllocFailed = true;
        printf("mm-psp motion blur allocation failed size=%lu\n", (unsigned long)size);
        return false;
    }

    sMmPspMotionBlurBufferSize = size;
    memset(sMmPspMotionBlurBuffer, 0, size);
    /* Publish the padding once, then leave history entirely GE-owned. Dirty
     * CPU cache lines must never overwrite subsequent GPU captures. */
    sceKernelDcacheWritebackInvalidateRange(sMmPspMotionBlurBuffer, size);
    printf("mm-psp motion blur storage addr=%p size=%lu\n", sMmPspMotionBlurBuffer,
           (unsigned long)size);
    return true;
}

static bool MmPspGfx_MotionBlurGeometryChanged(void) {
    return (sMmPspMotionBlurBufferWidth != BUF_WIDTH) ||
           (sMmPspMotionBlurScreenWidth != SCR_WIDTH) ||
           (sMmPspMotionBlurScreenHeight != SCR_HEIGHT) ||
           (sMmPspMotionBlurPixelFormat != sColorPixelFormat);
}

static void MmPspGfx_RecordMotionBlurGeometry(void) {
    sMmPspMotionBlurBufferWidth = BUF_WIDTH;
    sMmPspMotionBlurScreenWidth = SCR_WIDTH;
    sMmPspMotionBlurScreenHeight = SCR_HEIGHT;
    sMmPspMotionBlurPixelFormat = sColorPixelFormat;
}

static void MmPspGfx_CaptureMotionBlurFrame(void) {
    /* Keep capture after scene/blend commands and before the HUD in the same
     * list. Use the full VRAM address: sDrawBuffer may be a relative GU pointer.
     * Copy visible columns only; framebuffer stride padding is never sampled. */
    sceGuTexSync();
    sceGuCopyImage(sColorPixelFormat, 0, 0, SCR_WIDTH, SCR_HEIGHT, BUF_WIDTH,
                   gfx_scegu_vram_cpu_addr(sDrawBuffer), 0, 0, BUF_WIDTH, sMmPspMotionBlurBuffer);
    sceGuTexSync();
    sceGuTexFlush();
}

static void MmPspGfx_DrawMotionBlurHistory(uint8_t alpha) {
    struct ShaderProgram* restoreShader = sAppliedShader;
    int restoreTextureTile = active_texture_tile;
    int originX;
    int originY;
    int viewportWidth;
    int viewportHeight;
    int tileStart;
    uint32_t color;

    viewportWidth = (int)gfx_current_dimensions.width;
    viewportHeight = (int)gfx_current_dimensions.height;
    if ((viewportWidth <= 0) || (viewportWidth > SCR_WIDTH)) {
        viewportWidth = SCR_WIDTH;
    }
    if ((viewportHeight <= 0) || (viewportHeight > SCR_HEIGHT)) {
        viewportHeight = SCR_HEIGHT;
    }
    originX = (SCR_WIDTH - viewportWidth) / 2;
    originY = (SCR_HEIGHT - viewportHeight) / 2;
    color = ((uint32_t)alpha << 24) | 0x00FFFFFFU;

    /* The GU accepts textures up to 512 pixels wide. LCD uses one image;
     * the 720-wide TV framebuffer uses 512-pixel and 256-pixel images. */
    gfx_scegu_set_lighting(NULL);
    sceGuPixelMask(0);
    sceGuDisable(GU_DEPTH_TEST);
    sceGuDepthMask(GU_TRUE);
    sceGuDisable(GU_ALPHA_TEST);
    sceGuEnable(GU_SCISSOR_TEST);
    sceGuScissor(originX, originY, originX + viewportWidth, originY + viewportHeight);
    sceGuEnable(GU_TEXTURE_2D);
    sceGuEnable(GU_BLEND);
    sceGuBlendFunc(GU_ADD, GU_SRC_ALPHA, GU_ONE_MINUS_SRC_ALPHA, 0, 0);
    sceGuTexMode(sColorPixelFormat, 0, 0, GU_FALSE);
    sceGuTexFunc(GU_TFX_MODULATE, GU_TCC_RGB);
    sceGuTexFilter(GU_NEAREST, GU_NEAREST);
    sceGuTexWrap(GU_CLAMP, GU_CLAMP);
    sceGuTexOffset(0.0f, 0.0f);
    sceGuTexScale(1.0f, 1.0f);
    sceGuTexFlush();

    texman_invalidate_binding();
    for (tileStart = 0; tileStart < SCR_WIDTH; tileStart += 512) {
        const int tileEnd = (tileStart + 512 < SCR_WIDTH) ? tileStart + 512 : SCR_WIDTH;
        const int drawLeft = (originX > tileStart) ? originX : tileStart;
        const int viewportRight = originX + viewportWidth;
        const int drawRight = (viewportRight < tileEnd) ? viewportRight : tileEnd;
        const int tileWidth = nextpow2(tileEnd - tileStart);
        const int textureHeight = nextpow2(SCR_HEIGHT);
        const size_t pixelOffset = (size_t)tileStart * (size_t)sColorPixelSize;
        MmPspMotionBlurVertex* vertices;
        int vertexCount;
        int sliceStart;
        int i;

        if (drawRight <= drawLeft) {
            continue;
        }

        vertexCount = ((drawRight - drawLeft + MM_PSP_MOTION_BLUR_SLICE_WIDTH - 1) /
                       MM_PSP_MOTION_BLUR_SLICE_WIDTH) * 2;
        vertices = (MmPspMotionBlurVertex*)sceGuGetMemory(sizeof(*vertices) * vertexCount);
        for (sliceStart = drawLeft, i = 0; sliceStart < drawRight;
             sliceStart += MM_PSP_MOTION_BLUR_SLICE_WIDTH, i += 2) {
            const int sliceRight = (sliceStart + MM_PSP_MOTION_BLUR_SLICE_WIDTH < drawRight)
                                       ? sliceStart + MM_PSP_MOTION_BLUR_SLICE_WIDTH : drawRight;

            vertices[i].u = (uint16_t)(sliceStart - tileStart);
            vertices[i].v = (uint16_t)originY;
            vertices[i].color = color;
            vertices[i].x = (uint16_t)sliceStart;
            vertices[i].y = (uint16_t)originY;
            vertices[i].z = 0;
            vertices[i + 1].u = (uint16_t)(sliceRight - tileStart);
            vertices[i + 1].v = (uint16_t)(originY + viewportHeight);
            vertices[i + 1].color = color;
            vertices[i + 1].x = (uint16_t)sliceRight;
            vertices[i + 1].y = (uint16_t)(originY + viewportHeight);
            vertices[i + 1].z = 0;
        }

        sceGuTexImage(0, tileWidth, textureHeight, BUF_WIDTH,
                      (uint8_t*)sMmPspMotionBlurBuffer + pixelOffset);
        sceGuDrawArray(GU_SPRITES,
                       GU_TEXTURE_16BIT | GU_COLOR_8888 | GU_VERTEX_16BIT | GU_TRANSFORM_2D,
                       vertexCount, NULL, vertices);
    }

    /* Preserve MM's feedback behavior: the blended output, rather than only
     * the unblurred scene, is the history texture for the following frame. */
    MmPspGfx_CaptureMotionBlurFrame();

    /* Continue the original display list with the renderer state it had at
     * the marker. Rebinding is required because the history images bypassed
     * the normal texture manager. */
    sceGuDepthFunc(GU_GEQUAL);
    if (sDepthTestEnabled) {
        sceGuEnable(GU_DEPTH_TEST);
    } else {
        sceGuDisable(GU_DEPTH_TEST);
    }
    sceGuDepthMask(sDepthWriteEnabled ? GU_FALSE : GU_TRUE);
    sceGuScissor(sScissorBounds[0], sScissorBounds[1], sScissorBounds[2], sScissorBounds[3]);
    sceGuEnable(GU_SCISSOR_TEST);
    sceGuTexEnvColor(sTextureEnvColor);
    sceGuTexOffset(0.0f, 0.0f);
    sceGuTexScale(1.0f, 1.0f);

    sAppliedShader = NULL;
    if (restoreShader != NULL) {
        gfx_scegu_apply_shader(restoreShader);
    }
    texman_invalidate_binding();
    active_texture_tile = -1;
    sAppliedSamplerStateValid = false;
    if ((restoreTextureTile >= 0) && (restoreTextureTile < 2) &&
        (tmu_state[restoreTextureTile].tex != 0)) {
        gfx_scegu_select_texture(restoreTextureTile, tmu_state[restoreTextureTile].tex);
    }
    if (gl_blend) {
        sceGuEnable(GU_BLEND);
    } else {
        sceGuDisable(GU_BLEND);
    }
}

static void MmPspGfx_ApplyMotionBlur(uint8_t alpha, bool resetHistory) {
    if (!MmPspGfx_EnsureMotionBlurBuffer()) {
        return;
    }

    if (MmPspGfx_MotionBlurGeometryChanged()) {
        sMmPspMotionBlurValid = false;
        MmPspGfx_RecordMotionBlurGeometry();
    }
    if (resetHistory) {
        sMmPspMotionBlurValid = false;
    }

    /* Reserve the entire effect before emitting any of it. Only list exhaustion
     * needs a CPU fence; normal blur frames stay in the current command list. */
    gfx_scegu_reserve_list_memory(((SCR_WIDTH + MM_PSP_MOTION_BLUR_SLICE_WIDTH - 1) /
                                 MM_PSP_MOTION_BLUR_SLICE_WIDTH) * 2 * sizeof(MmPspMotionBlurVertex));

    if (!sMmPspMotionBlurValid || (alpha == 0)) {
        MmPspGfx_CaptureMotionBlurFrame();
        sMmPspMotionBlurValid = true;
        return;
    }

    MmPspGfx_DrawMotionBlurHistory(alpha);
}

void gfx_scegu_apply_vismono(uint8_t primR, uint8_t primG, uint8_t primB, uint8_t alpha,
                             uint8_t envR, uint8_t envG, uint8_t envB) {
    if (MmPspGfx_IsMotionBlurCommand(primR, primG, primB, envR, envG)) {
        MmPspGfx_ApplyMotionBlur(alpha, (envB & MM_PSP_MOTION_BLUR_RESET) != 0);
        return;
    }

    MmPspGfx_ApplyVisMonoOriginal(primR, primG, primB, alpha, envR, envG, envB);
}
