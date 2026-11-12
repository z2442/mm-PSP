"""Compile the actual combiner decoder/material sampler with a mock texture backend.

Run: python3 tools/tests/test_psp_combiner.py
No PSP or ROM is required for the synthetic tests. Extracted Clock Town display
lists are also checked when present.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GFX = ROOT / 'src/port/psp/backend/gfx'


def harness():
    source = (GFX / 'gfx_fast3d.c').read_text()
    gbi = (ROOT / 'include/PR/gbi.h').read_text()
    macros = '\n'.join(line for line in gbi.splitlines() if re.match(
        r'#define (G_CCMUX_|G_ACMUX_|G_MDSFT_(CYCLETYPE|TEXTFILT)|G_CYC_|G_TF_|G_IM_(FMT|SIZ)_|G_TX_(WRAP|MIRROR|CLAMP|NOMASK)|G_TEXTURE_IMAGE_FRAC)', line))
    fields = source[source.index('    uint32_t combine_mode;'):source.index('    struct XYWidthHeight viewport, scissor;', source.index('    uint32_t combine_mode;'))]
    decoder = source[source.index('static uint8_t color_comb_component('):source.index('static void gfx_dp_set_env_color(')]
    dimensions = ''
    for name in ('gfx_texture_tile_span', 'gfx_texture_tile_width', 'gfx_texture_tile_height'):
        start = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\s*\{', source, re.M).start()
        dimensions += source[start:source.index('\n}', start) + 2] + '\n'
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include "gfx_cc.h"
#define TARGET_PSP 1
#define GFX_DL_HANDLER
''' + macros + r'''
struct RGBA { uint8_t r,g,b,a; };
typedef struct TextureTileState {
 uint8_t fmt,siz,palette,cms,cmt,masks,maskt,shifts,shiftt;
 uint16_t uls,ult,lrs,lrt;
 uint32_t line_size_bytes;
} TextureTileState;
static struct {
 uint32_t other_mode_h;
''' + fields + r'''
 TextureTileState texture_tile[2];
 struct { const uint8_t* addr; uint32_t row_stride_bytes; uint8_t source_nibble_offset; } loaded_texture[2];
} rdp;
static void gfx_mark_tri_pipeline_dirty(void) {}
''' + decoder + r'''
static uint32_t sTextureCacheFrameSerial=1, sourceSerial=1;
static struct {uint32_t bound_texture_id;} rendering_state;
typedef int GfxTextureSwapState;
static uint32_t uploads, nextId, dimensionQueries;
static bool runtimeSource;
static struct RGBA uploaded[128*128], texturePixels[128][128*128];
static uint32_t textureSizes[128], selectedId;
static uint8_t pixels[2][64*64*2];
static void gfx_material_texture_reset(void);
static void gfx_flush(void) {}
static void gfx_texture_cache_clear(void) {gfx_material_texture_reset();}
static int texman_vram_space_available(uint32_t bytes) {return 1;}
static int texman_texture_slot_available(void) {return 1;}
static uint32_t new_texture(void) {assert(nextId<127); return ++nextId;}
static void select_texture(int slot, uint32_t id) {
 selectedId=id; memcpy(uploaded,texturePixels[id],textureSizes[id]);
}
static void upload_texture(const uint8_t* data, uint32_t w, uint32_t h, uint32_t fmt) {
 assert(w<=128 && h<=128); memcpy(uploaded,data,w*h*4); uploads++;
 memcpy(texturePixels[selectedId],data,w*h*4); textureSizes[selectedId]=w*h*4;
}
static struct {uint32_t(*new_texture)(void); void(*select_texture)(int,uint32_t);
 void(*upload_texture)(const uint8_t*,uint32_t,uint32_t,uint32_t);
} api={new_texture,select_texture,upload_texture}, *gfx_rapi=&api;
#define GU_PSM_8888 3
#define SCALE_5_8(v) (((v)*255)/31)
static TextureTileState* gfx_get_texture_tile(int i) {return &rdp.texture_tile[i];}
''' + dimensions + r'''
static uint32_t gfx_texture_import_width(int i) {dimensionQueries++; return gfx_texture_tile_width(i);}
static uint32_t gfx_texture_import_height(int i) {dimensionQueries++; return gfx_texture_tile_height(i);}
static bool gfx_is_power_of_two(uint32_t n) {return n && !(n&(n-1));}
static uint32_t gfx_texture_source_span_size(int i) {return 8192;}
static bool OotPsp_IsRuntimeByteRange(const void* p,uint32_t n) {return runtimeSource;}
static uint32_t OotPsp_GetExternalAssetRangeSerial(const void* p,uint32_t n) {return sourceSerial;}
static GfxTextureSwapState gfx_texture_source_swap_state(const void* p,uint32_t n) {return 0;}
static bool gfx_validate_texture_source(int i,const char* ctx) {return true;}
static uint32_t gfx_texture_row_bytes(uint32_t width,uint32_t siz) {return (width<<siz)/2;}
static const uint8_t* gfx_texture_row(int i,uint32_t y,uint32_t fallback) {
 return rdp.loaded_texture[i].addr+y*(rdp.loaded_texture[i].row_stride_bytes ? rdp.loaded_texture[i].row_stride_bytes : fallback);
}
static uint8_t gfx_read_texture_source_u8(const uint8_t* p,uint32_t x,GfxTextureSwapState* s) {return p[x];}
static uint16_t gfx_read_texture_source_be16(const uint8_t* p,uint32_t x,GfxTextureSwapState* s) {return (p[x]<<8)|p[x+1];}
static uint8_t gfx_texture_read_4b(int i,uint32_t x,const uint8_t* row,GfxTextureSwapState* s) {
 x+=rdp.loaded_texture[i].source_nibble_offset;
 return (row[x/2] >> (x%2 ? 0 : 4))&15;
}
static uint8_t gfx_color_mul_channel(uint8_t a,uint8_t b) {return (a*b+127)/255;}
static float gfx_texture_shift_scale(uint8_t shift) {return shift<=10 ? 1.0f/(1<<shift) : (float)(1<<(16-shift));}
#include "gfx_material_texture.inc.c"
static bool prepare_material(void) {
 bool ready=gfx_prepare_material_texture();
 if(ready) select_texture(0,sMaterialTexture->textureId);
 return ready;
}
static struct RGBA gfx_material_texel(int slot, int x, int y, GfxTextureSwapState* swap) {
 return gfx_material_read_texel(slot,x,y,swap,gfx_texture_import_width(slot),gfx_texture_import_height(slot));
}
static void combine(int* q) {
 uint32_t w0=(q[0]&15)<<20|(q[2]&31)<<15|(q[4]&7)<<12|(q[6]&7)<<9|(q[8]&15)<<5|(q[10]&31);
 uint32_t w1=(uint32_t)(q[1]&15)<<28|(q[9]&15)<<24|(q[12]&7)<<21|(q[14]&7)<<18|
 (q[3]&7)<<15|(q[5]&7)<<12|(q[7]&7)<<9|(q[11]&7)<<6|(q[13]&7)<<3|(q[15]&7);
 gfx_dp_set_combine(w0,w1);
}
static int product[16]={2,31,1,31, 2,1,6,1, 0,31,4,31, 0,7,3,7};
static void setup(void) {
 memset(&rdp,0,sizeof(rdp));
 rdp.other_mode_h=G_CYC_2CYCLE;
 rdp.prim_color=(struct RGBA){0,25,25,127}; rdp.prim_lod_frac=255;
 for(int i=0;i<2;i++) {
  rdp.texture_tile[i]=(TextureTileState){.fmt=G_IM_FMT_I,.siz=G_IM_SIZ_8b,.masks=5,.maskt=5,.lrs=124,.lrt=124};
  rdp.loaded_texture[i].addr=pixels[i];
  rdp.loaded_texture[i].row_stride_bytes=32;
 }
 combine(product);
 gfx_material_texture_reset();
}
'''


class CombinerTest(unittest.TestCase):
    def compile_run(self, body):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'test.c'
            path.write_text(harness() + '\nint main(void) {\n' + body + '\nreturn 0;\n}\n')
            subprocess.run(['cc','-std=c11','-Wall','-Werror','-Wno-unused-function',
                            '-fsanitize=undefined','-I',str(GFX),str(path),'-lm','-o',str(path.with_suffix(''))],check=True)
            subprocess.run([str(path.with_suffix(''))],check=True)

    def test_cycle_decode_and_scene_equations(self):
        body = '''
setup();
assert(rdp.combine_two_texture_multiply);
int tinted[16]={1,31,3,31, 0,0,0,1, 0,31,4,31, 0,0,0,0};
combine(tinted);
assert(rdp.combine_color_mul_prim);
assert((rdp.combine_mode&4095)==color_comb(1,31,4,31));
rdp.other_mode_h=G_CYC_1CYCLE;
int single[16]={1,31,3,31, 0,0,0,1, 31,31,31,4, 7,7,7,3};
combine(single);
assert((rdp.combine_mode&4095)==color_comb(31,31,31,4));
assert(!rdp.combine_two_texture_blend && !rdp.combine_color_mul_prim);
rdp.other_mode_h=G_CYC_2CYCLE;
int blend[16]={2,1,14,1, 2,1,6,1, 0,31,4,31, 0,7,3,7};
combine(blend);
assert(rdp.combine_two_texture_blend && !rdp.combine_two_texture_multiply);
assert(rdp.combine_two_texture_blend_uses_prim_lod && rdp.combine_two_texture_alpha_blend);
'''
        # Use the actual equations from both Clock Town scenes, not per-scene special cases.
        count = 0
        for scene in ('Z2_TOWN','Z2_CLOCKTOWER'):
            for path in (ROOT/'extracted/n64-us/assets/scenes'/scene).glob('*room*.c'):
                for match in re.finditer(r'gsDPSetCombineLERP\((.*?)\)', path.read_text(), re.S):
                    tokens = [t.strip() for t in match[1].split(',')]
                    if len(tokens) != 16:
                        continue
                    args = ','.join(('G_ACMUX_' if (i//4)%2 else 'G_CCMUX_')+t for i,t in enumerate(tokens))
                    body += '{int q[16]={' + args + '}; combine(q);'
                    if tokens[:4] == ['TEXEL1','0','TEXEL0','0']:
                        body += 'assert(rdp.combine_two_texture_multiply);'
                    elif tokens[:4] == ['TEXEL0','0','PRIMITIVE','0']:
                        body += 'assert(rdp.combine_color_mul_prim);'
                    body += '}\n'
                    count += 1
        self.compile_run(body)
        print(f'Validated {count} extracted Clock Town combiner commands')

    def test_material_pixels_alpha_scroll_and_cache(self):
        self.compile_run('''
setup();
memset(pixels[0],255,sizeof(pixels[0])); memset(pixels[1],128,sizeof(pixels[1]));
assert(prepare_material());
assert(uploaded[0].r==128 && uploaded[0].a==64);
uint32_t id=sMaterialTexture->textureId, count=uploads;
assert(prepare_material()); assert(uploads==count && sMaterialTexture->textureId==id);
/* New DMA to the same address must invalidate combined pixels. */
sourceSerial++; memset(pixels[1],255,sizeof(pixels[1]));
assert(prepare_material()); assert(sMaterialTexture->textureId!=id);
assert(uploaded[0].r==255 && uploaded[0].a==127);
/* Independently scaled and scrolled tiles use the same original S/T domain. */
sourceSerial++;
for(int y=0;y<32;y++) for(int x=0;x<32;x++) pixels[1][y*32+x]=x*8;
rdp.texture_tile[0].shiftt=15; rdp.texture_tile[1].shifts=15;
rdp.texture_tile[1].uls=4; rdp.texture_tile[1].lrs=128;
assert(prepare_material());
assert(sMaterialTexture->width==64 && sMaterialTexture->height==64);
assert(uploaded[0].r==248 && uploaded[1].r==0 && uploaded[2].r==8);
/* Mirrors include the reflected half, including negative coordinates. */
assert(gfx_material_wrap(-1,32,true)==0 && gfx_material_wrap(32,32,true)==31);
assert(gfx_material_wrap(63,32,true)==0 && gfx_material_wrap(64,32,true)==0);
/* Filtered scrolling and alpha endpoints. */
rdp.other_mode_h |= G_TF_BILERP;
rdp.texture_tile[1].uls=2; rdp.texture_tile[1].lrs=126;
assert(prepare_material()); assert(uploaded[0].r==124);
/* Unsupported/clamped domains retain the ordinary renderer fallback. */
rdp.texture_tile[0].cms=G_TX_CLAMP; assert(!prepare_material());
gfx_material_texture_reset(); assert(sMaterialTexture==NULL && sMaterialTextures[0].textureId==0);
''')

    def test_material_crossfade_and_transparency(self):
        self.compile_run('''
setup();
int blend[16]={2,1,14,1, 2,1,6,1, 0,31,4,31, 0,7,3,7};
combine(blend);
memset(pixels[0],32,sizeof(pixels[0])); memset(pixels[1],224,sizeof(pixels[1]));
rdp.prim_lod_frac=0; assert(prepare_material()); assert(uploaded[0].r==32);
rdp.prim_lod_frac=255; assert(prepare_material()); assert(uploaded[0].r==224);
rdp.prim_lod_frac=128; assert(prepare_material()); assert(uploaded[0].r==128);
assert(uploaded[0].a==64);
/* Water alpha is calculated before framebuffer blending, not applied by
 * multiplying an already blended framebuffer with a second texture. */
int background=200;
int actual=(uploaded[0].r*uploaded[0].a+background*(255-uploaded[0].a)+127)/255;
assert(actual==182);
/* Reversing the RGB crossfade does not reverse its independent alpha. */
blend[0]=1; blend[1]=2; blend[3]=2; combine(blend);
rdp.prim_lod_frac=0; assert(prepare_material());
assert(uploaded[0].r==224 && uploaded[0].a==16);
/* RGB ENV_ALPHA and PRIM_LOD_FRAC must not alias in the cache. */
blend[0]=2; blend[1]=1; blend[3]=1; blend[2]=12;
rdp.env_color.a=255; combine(blend); assert(prepare_material()); assert(uploaded[0].r==224);
blend[2]=14; combine(blend); assert(prepare_material()); assert(uploaded[0].r==32);
''')

    def test_multiple_scrolling_materials_reuse_allocations(self):
        self.compile_run('''
setup();
memset(pixels[0],255,sizeof(pixels[0])); memset(pixels[1],128,sizeof(pixels[1]));
rdp.other_mode_h |= G_TF_BILERP;
rdp.texture_tile[0].shiftt=15; rdp.texture_tile[1].shifts=15;
uint32_t ids[3]={0};
for (int frame=0;frame<120;frame++) {
 sTextureCacheFrameSerial++;
 for (int material=0;material<3;material++) {
  rdp.prim_color.a=80+material*20;
  rdp.texture_tile[0].uls=(frame+material)*4;
  rdp.texture_tile[0].lrs=rdp.texture_tile[0].uls+124;
  uint32_t queries=dimensionQueries;
  assert(prepare_material());
  /* Dimensions are queried per material, never per output texel/tap. */
  assert(dimensionQueries-queries==4);
  ids[material]=sMaterialTexture->textureId;
  for (int prior=0;prior<material;prior++) assert(ids[prior]!=ids[material]);
 }
}
/* Three simultaneously queued variants, no allocation growth while scrolling. */
assert(nextId==3);
uint32_t count=uploads;
rdp.texture_tile[0].uls+=128; rdp.texture_tile[0].lrs+=128;
assert(prepare_material()); assert(uploads==count);
/* ROM/static sources without DMA serials persist; mutable RAM still refreshes. */
setup(); sourceSerial=0; runtimeSource=false;
assert(prepare_material()); count=uploads;
sTextureCacheFrameSerial++; assert(prepare_material()); assert(uploads==count);
runtimeSource=true; assert(prepare_material()); count=uploads;
sTextureCacheFrameSerial++; assert(prepare_material()); assert(uploads==count+1);
''')

    def test_clock_town_wrapped_material_layers(self):
        self.compile_run('''
setup();
rdp.texture_tile[0].shifts=15;
rdp.texture_tile[1].fmt=G_IM_FMT_RGBA; rdp.texture_tile[1].siz=G_IM_SIZ_16b;
rdp.loaded_texture[1].row_stride_bytes=64;
for (int y=0;y<32;y++) for (int x=0;x<32;x++) {
 pixels[0][y*32+x]=x*5+y*3;
 uint16_t color=(x<<11)|(y<<6)|(((x+y)&31)<<1)|1;
 pixels[1][(y*32+x)*2]=color>>8; pixels[1][(y*32+x)*2+1]=color;
}
uint32_t allocation=0;
for (int frame=0;frame<64;frame++) {
 sTextureCacheFrameSerial++;
 int origins[2][2]={{-37+frame*3,-77+frame*2},{109-frame*2,-14-frame}};
 for (int slot=0;slot<2;slot++) {
  TextureTileState* tile=&rdp.texture_tile[slot];
  tile->uls=origins[slot][0]&4095; tile->ult=origins[slot][1]&4095;
  tile->lrs=(tile->uls+124)&4095; tile->lrt=(tile->ult+124)&4095;
 }
 assert(prepare_material());
 assert(sMaterialTexture->width==64 && sMaterialTexture->height==32);
 if (!frame) allocation=sMaterialTexture->textureId;
 assert(sMaterialTexture->textureId==allocation);
 for (int y=0;y<32;y++) for (int x=0;x<64;x++) {
  int x0=(int)floorf(x-origins[0][0]*0.25f)&31;
  int y0=(int)floorf(y-origins[0][1]*0.25f)&31;
  int x1=(int)floorf(x*0.5f-origins[1][0]*0.25f)&31;
  int y1=(int)floorf(y-origins[1][1]*0.25f)&31;
  int intensity=x0*5+y0*3;
  struct RGBA expected={(intensity*SCALE_5_8(x1)+127)/255,
                       (intensity*SCALE_5_8(y1)+127)/255,
                       (intensity*SCALE_5_8((x1+y1)&31)+127)/255,127};
  assert(memcmp(&uploaded[y*64+x],&expected,sizeof(expected))==0);
 }
}
assert(nextId==1); // Crossing zero changes phase, not texture dimensions or allocation.
''')

    def test_texture_formats_and_descending_alpha(self):
        self.compile_run('''
setup();
GfxTextureSwapState swap=0;
/* RGBA16: byte order, all RGB channels, and the one-bit coverage mask. */
rdp.texture_tile[0].fmt=G_IM_FMT_RGBA; rdp.texture_tile[0].siz=G_IM_SIZ_16b;
rdp.loaded_texture[0].row_stride_bytes=64;
pixels[0][0]=0xF8; pixels[0][1]=0x01;
pixels[0][2]=0x07; pixels[0][3]=0xC0;
struct RGBA p=gfx_material_texel(0,0,0,&swap);
assert(p.r==255 && p.g==0 && p.b==0 && p.a==255);
p=gfx_material_texel(0,1,0,&swap);
assert(p.r==0 && p.g==255 && p.b==0 && p.a==0);
memset(pixels[1],255,sizeof(pixels[1]));
rdp.prim_lod_frac=0;
assert(prepare_material());
assert(uploaded[0].r==255 && uploaded[0].a==127 && uploaded[1].a==0);
/* IA8 keeps intensity separate from alpha. */
rdp.texture_tile[0].fmt=G_IM_FMT_IA; rdp.texture_tile[0].siz=G_IM_SIZ_8b;
pixels[0][0]=0xA3;
p=gfx_material_texel(0,0,0,&swap);
assert(p.r==170 && p.g==170 && p.b==170 && p.a==51);
/* I4 loads may start on the low nibble; retain that source offset. */
rdp.texture_tile[0].fmt=G_IM_FMT_I; rdp.texture_tile[0].siz=G_IM_SIZ_4b;
rdp.loaded_texture[0].source_nibble_offset=1;
pixels[0][0]=0xA3; pixels[0][1]=0xC0;
p=gfx_material_texel(0,0,0,&swap); assert(p.r==51 && p.a==51);
p=gfx_material_texel(0,1,0,&swap); assert(p.r==204 && p.a==204);
/* Descending blends must reach zero as well as ascending blends reach 255. */
uint32_t equation=2 | (1<<3) | (6<<6) | (1<<9);
rdp.prim_lod_frac=255; assert(gfx_material_alpha(equation,255,0,0)==0);
rdp.prim_lod_frac=0; assert(gfx_material_alpha(equation,255,0,0)==255);
rdp.prim_lod_frac=128; assert(gfx_material_alpha(equation,255,0,0)==127);
''')

    def test_clock_town_mirrored_wall_requires_two_passes(self):
        self.compile_run('''
setup();
/* Z2_TOWN_room_00DL_003678: the different T shifts require a 256-row
 * common domain, beyond the 128-row material cache. Exercise the fallback
 * deliberately instead of letting fused materials hide its UV stream. */
for (int slot=0;slot<2;slot++) {
 TextureTileState* tile=&rdp.texture_tile[slot];
 tile->fmt=G_IM_FMT_RGBA; tile->siz=G_IM_SIZ_16b;
 tile->cms=G_TX_MIRROR;
 tile->cmt=slot ? G_TX_WRAP : G_TX_MIRROR;
 tile->shifts=slot ? 0 : 15; tile->shiftt=slot ? 14 : 0;
 rdp.loaded_texture[slot].row_stride_bytes=64;
}
rdp.texture_tile[0].uls=0xFDB; rdp.texture_tile[0].ult=0xFB3;
rdp.texture_tile[0].lrs=0x057; rdp.texture_tile[0].lrt=0x02F;
rdp.texture_tile[1].uls=0x06D; rdp.texture_tile[1].ult=0xFF2;
rdp.texture_tile[1].lrs=0x0E9; rdp.texture_tile[1].lrt=0x06E;
assert(rdp.combine_two_texture_blend && rdp.combine_two_texture_multiply);
assert(!prepare_material() && uploads==0);
/* Reducing that domain makes fusion possible, proving why it fell back. */
rdp.texture_tile[1].shiftt=15;
assert(prepare_material());
assert(sMaterialTexture->width==128 && sMaterialTexture->height==128);
''')


if __name__ == '__main__':
    unittest.main()
