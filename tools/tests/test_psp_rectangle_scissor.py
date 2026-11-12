#!/usr/bin/env python3
"""Check letterbox clipping and shared HUD/minimap rectangle scaling."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
interpreter = (ROOT / "src/port/psp/backend/gfx/gfx_fast3d.c").read_text()
backend = (ROOT / "src/port/psp/backend/gfx/gfx_scegu.c").read_text()
shrink_window = (ROOT / "src/code/z_shrink_window.c").read_text()



def section(source, start, end):
    offset = source.index(start)
    return source[offset:source.index(end, offset)]


preamble = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#define G_MDSFT_CYCLETYPE 20
#define G_MDSFT_TEXTFILT 12
#define G_CYC_COPY (2U<<20)
#define G_CYC_FILL (3U<<20)
#define G_TF_POINT 0
#define G_SC_NON_INTERLACE 0
#define G_CCMUX_SHADE 4
#define G_ACMUX_SHADE 4
#define Z_CMP 16
#define Z_UPD 32
#define G_ZBUFFER 1
#define HALF_SCREEN_WIDTH 160
#define HALF_SCREEN_HEIGHT 120
static int screenWidth=480,screenHeight=272;
#define SCR_WIDTH screenWidth
#define SCR_HEIGHT screenHeight
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240
#define RATIO_X ((float)gfx_current_dimensions.width/SCREEN_WIDTH)
#define RATIO_Y ((float)gfx_current_dimensions.height/SCREEN_HEIGHT)
#define _UNUSED(x) (void)(x)
struct RGBA { uint8_t r,g,b,a; };
struct XYWidthHeight { uint16_t x,y,width,height; };
struct VertexColor { uint16_t x,y; struct RGBA color; };
static struct { unsigned width,height; } gfx_current_dimensions={480,272};
static struct {
    uint32_t other_mode_h,other_mode_l;
    struct XYWidthHeight viewport,scissor;
    bool viewport_or_scissor_changed;
    uintptr_t color_image_address,z_buf_address;
    struct RGBA fill_color,prim_color;
    uint32_t combine_mode;
    bool combine_color_mul_env,combine_color_mul_prim,combine_two_texture_blend,
         combine_two_texture_multiply,combine_two_texture_blend_uses_prim_lod,
         combine_two_texture_alpha_blend,combine_arrow_glow,combine_alpha_mul_env,
         combine_flame_texture_atlas,combine_texture_tint_uses_prim_lod,
         combine_texture_tint_uses_env_alpha;
} rdp;
static struct { uint32_t geometry_mode; struct VertexColor loaded_vertices_2D[2]; } rsp;
static struct XYWidthHeight drawn_scissor,drawn_viewport;
static int scissor_calls;
static int sScissorBounds[4];
static float hudOffset,aspectScale=1;
static bool rasterize;
static unsigned rows[480];
static struct VertexColor rectangle[2];
static void gfx_scegu_set_viewport(int x,int y,int width,int height);
static void gfx_scegu_set_scissor(int x,int y,int width,int height);
static void sceGuViewport(int x,int y,int w,int h) { (void)x;(void)y;(void)w;(void)h; }
static void sceGuScissor(int x,int y,int r,int b) { (void)x;(void)y;(void)r;(void)b;scissor_calls++; }
static void gfx_mark_tri_pipeline_dirty(void) {}
static float gfx_hud_anchor_offset_pixels(void) { return hudOffset; }
static float gfx_adjust_x_for_aspect_ratio(float x) { return x*aspectScale; }
static bool gfx_hud_anchor_enabled(void) { return false; }
static float gfx_widescreen_margin_pixels(void) { return 0; }
static unsigned color_comb(unsigned a,unsigned b,unsigned c,unsigned d) { return a|(b<<3)|(c<<6)|(d<<9); }
static void gfx_dp_set_combine_mode(unsigned color,unsigned alpha,...) { rdp.combine_mode=color|(alpha<<12); }
static void gfx_sp_tri1_2d(int a,int b,int c) {
    (void)a;(void)b;(void)c;
    drawn_scissor=rdp.scissor;
    drawn_viewport=rdp.viewport;
    memcpy(rectangle,rsp.loaded_vertices_2D,sizeof(rectangle));
    if (rasterize && rectangle[0].color.a) {
        gfx_scegu_set_scissor(rdp.scissor.x,rdp.scissor.y,rdp.scissor.width,rdp.scissor.height);
        gfx_scegu_set_viewport(rdp.viewport.x,rdp.viewport.y,rdp.viewport.width,rdp.viewport.height);
        /* Inspect the center column using the actual GU bounds; every native
         * letterbox rectangle covers its full width. */
        int top=sScissorBounds[1],bottom=sScissorBounds[3];
        for (unsigned y=0;y<gfx_current_dimensions.height;y++) {
            if ((int)y>=top && (int)y<bottom && y>=rectangle[0].y && y<rectangle[1].y)
                rows[y]=(rectangle[0].color.r<<16)|(rectangle[0].color.g<<8)|rectangle[0].color.b;
        }
    }
}
'''
native_bars = r'''
typedef int Gfx;
typedef int GraphicsContext;
typedef int8_t s8;
static struct { s8 letterboxSize,pillarboxSize; } shrink,*sShrinkWindowPtr=&shrink;
static int gScreenWidth=SCREEN_WIDTH,gScreenHeight=SCREEN_HEIGHT;
static Gfx commands[100];
#define OPEN_DISPS(ctx) do { (void)(ctx);Gfx* overlay=commands;
#define CLOSE_DISPS(ctx) } while (0)
#define OVERLAY_DISP overlay
#define GPACK_RGBA5551(r,g,b,a) (a)
#define G_RM_NOOP 0
#define G_RM_NOOP2 0
#define G_RM_XLU_SURF 0
#define G_RM_XLU_SURF2 0
#define G_CYC_1CYCLE 0
#define gDPPipeSync(ptr) ((void)(ptr))
#define gDPSetCycleType(ptr,mode) ((void)(ptr),rdp.other_mode_h=(mode))
#define gDPSetRenderMode(ptr,a,b) ((void)(ptr))
#define gDPSetFillColor(ptr,color) ((void)(ptr),rdp.fill_color=(struct RGBA){0,0,0,255})
#define gDPSetPrimColor(ptr,m,l,r,g,b,a) ((void)(ptr),rdp.prim_color=(struct RGBA){r,g,b,a})
#define gDPFillRectangle(ptr,x0,y0,x1,y1) ((void)(ptr),gfx_dp_fill_rectangle((x0)*4,(y0)*4,(x1)*4,(y1)*4))
''' + shrink_window[shrink_window.index("void ShrinkWindow_Draw("):]
tests = r'''
int main(void) {
    struct XYWidthHeight viewport={10,20,300,200};
    struct XYWidthHeight full={0,0,480,272};
    rdp.viewport=viewport;
    rsp.geometry_mode=0x1234;
    for (unsigned bar=1;bar<=32;bar++) {
        unsigned pixels=(bar*272+239)/240;
        struct XYWidthHeight letterbox={0,pixels,480,272-2*pixels};
        rdp.scissor=letterbox;
        /* Environment_DrawSkyboxFilters fills the screen in one-cycle mode,
         * with the scene's letterbox scissor still active. */
        gfx_draw_rectangle(0,0,319*4,239*4,true,true);
        assert(memcmp(&drawn_scissor,&letterbox,sizeof(letterbox))==0);
        assert(memcmp(&drawn_viewport,&full,sizeof(full))==0);
        assert(memcmp(&rdp.viewport,&viewport,sizeof(viewport))==0);
        assert(memcmp(&rdp.scissor,&letterbox,sizeof(letterbox))==0);
        assert(rsp.geometry_mode==0x1234);
        gfx_scegu_set_scissor(letterbox.x,letterbox.y,letterbox.width,letterbox.height);
        int calls=scissor_calls;
        gfx_scegu_set_viewport(0,0,480,272);
        assert(scissor_calls==calls);
        /* MM's setupBuffers selects a full scissor for OVERLAY_DISP,
         * so the black fill rectangles must be able to cover both bars. */
        rdp.scissor=full;
        gfx_draw_rectangle(0,0,320*4,bar*4,false,true);
        assert(memcmp(&drawn_scissor,&full,sizeof(full))==0);
        gfx_draw_rectangle(0,(240-bar)*4,320*4,240*4,false,true);
        assert(memcmp(&drawn_scissor,&full,sizeof(full))==0);
    }
    /* MM's actual ShrinkWindow_Draw uses inclusive fill-cycle rectangles,
     * then zero-alpha one-cycle edge rectangles. Rasterize those together
     * with the real RDP scissor and fog fill, checking every edge pixel. */
    const unsigned rasterWidths[]={362,480,640,720};
    const unsigned rasterHeights[]={272,272,480,480};
    for (unsigned mode=0;mode<4;mode++) for (unsigned bar=0;bar<=32;bar++) {
        unsigned height=rasterHeights[mode];
        SCR_WIDTH=mode>=2 ? 720 : 480;SCR_HEIGHT=height;
        gfx_current_dimensions.width=rasterWidths[mode];gfx_current_dimensions.height=height;
        rdp.color_image_address=1;rdp.z_buf_address=2;
        rasterize=true;
        for (unsigned y=0;y<height;y++) rows[y]=0xFFFF00; // Uncovered clear color.
        gfx_dp_set_scissor(G_SC_NON_INTERLACE,0,bar*4,SCREEN_WIDTH*4,(SCREEN_HEIGHT-bar)*4);
        rdp.other_mode_h=G_CYC_1CYCLE;rdp.prim_color=(struct RGBA){30,60,90,255};
        gfx_dp_fill_rectangle(0,0,(SCREEN_WIDTH-1)*4,(SCREEN_HEIGHT-1)*4);
        gfx_dp_set_scissor(G_SC_NON_INTERLACE,0,0,SCREEN_WIDTH*4,SCREEN_HEIGHT*4);
        shrink.letterboxSize=bar;ShrinkWindow_Draw(NULL);
        unsigned top=bar*height/SCREEN_HEIGHT,bottom=(SCREEN_HEIGHT-bar)*height/SCREEN_HEIGHT;
        for (unsigned y=0;y<height;y++) {
            unsigned expected=y<top || y>=bottom ? 0 : 0x1E3C5A;
            if (rows[y]!=expected) fprintf(stderr,"Letterbox gap: %ux%u bar=%u row=%u color=%06X expected=%06X\n",
                rasterWidths[mode],height,bar,y,rows[y],expected);
            assert(rows[y]==expected);
        }
        rasterize=false;
    }
    // The gameplay minimap and its markers share the same right-anchored
    // scale as HUD buttons across LCD/TV and both aspect settings.
    const unsigned widths[]={362,480,640,720},heights[]={272,272,480,480};
    for (unsigned mode=0;mode<4;mode++) {
        gfx_current_dimensions.width=widths[mode];gfx_current_dimensions.height=heights[mode];
        float scale=heights[mode]/240.0f;
        aspectScale=(heights[mode]*(4.0f/3))/widths[mode];
        hudOffset=fmaxf(0,(widths[mode]-320*scale)*0.5f);
        float shift=widths[mode]*0.5f-160*scale+hudOffset;
        gfx_draw_rectangle(240*4,150*4,304*4,220*4,false,false);
        assert(fabsf(rectangle[0].x-(240*scale+shift))<1.01f);
        assert(fabsf(rectangle[1].x-rectangle[0].x-64*scale)<1.01f);
        assert(fabsf(rectangle[1].y-rectangle[0].y-70*scale)<1.01f);
        gfx_draw_rectangle(260*4,180*4,268*4,188*4,false,false);
        assert(fabsf(rectangle[0].x-(260*scale+shift))<1.01f);
        assert(fabsf(rectangle[0].y-180*scale)<1.01f);
        // Orthographic compass arrows use centered coordinates; their GU
        // projection must land on the same point as the rectangle marker.
        float arrowX=((260-160)/160.0f*aspectScale+2*hudOffset/widths[mode]+1)*widths[mode]*0.5f;
        assert(fabsf(arrowX-rectangle[0].x)<1.01f);
    }
    puts("MM letterbox edges: no uncovered rows across LCD/TV and all 0..32 bar sizes; scissoring and HUD alignment passed");
}
'''

with tempfile.TemporaryDirectory(prefix="oot-rectangle-scissor-") as directory:
    path = Path(directory)
    (path / "test.c").write_text(
        preamble
        + section(interpreter, "static void gfx_dp_set_scissor(", "static void gfx_dp_set_texture_image(")
        + section(interpreter, "static bool gfx_rectangle_covers_width(", "static void gfx_draw_rectangle(")
        + section(interpreter, "static void gfx_draw_rectangle(", "#if defined(TARGET_PSP)\ntypedef struct GfxRectAxisSegment")
        + section(interpreter, "static void gfx_dp_fill_rectangle(", "static void gfx_dp_set_z_image(")
        + section(backend, "static void gfx_scegu_set_viewport(", "static void gfx_scegu_set_use_alpha(")
        + native_bars
        + tests
    )
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                    str(path / "test.c"), "-lm", "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
