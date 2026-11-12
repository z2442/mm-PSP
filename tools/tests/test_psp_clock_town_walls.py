"""Check wrapped Clock Town wall tiles through the production UV and size code."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/port/psp/backend/gfx/gfx_fast3d.c').read_text()


def function(name):
    start = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\s*\{', source, re.M).start()
    return source[start:source.index('\n}', source.index('{', start)) + 2] + '\n'


tile = re.search(r'typedef struct TextureTileState \{.*?\} TextureTileState;', source, re.S).group()
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <math.h>
#include <string.h>
#define TARGET_PSP 1
#define G_TEXTURE_IMAGE_FRAC 2
#define G_TX_RENDERTILE 0
#define G_TX_NOMASK 0
#define G_TX_MIRROR 1
#define G_TX_CLAMP 2
''' + tile + r'''
static struct { TextureTileState texture_tile[2];bool textures_changed[2]; } rdp;
struct TriPipelineState { float tex_u_scale[2],tex_v_scale[2],tex_u_bias[2],tex_v_bias[2]; } state;
struct TextureHashmapNode { uint16_t upload_width,upload_height; } textures[2];
static struct { struct TextureHashmapNode* textures[2]; } rendering_state;
static unsigned dirty;
static void gfx_mark_tri_pipeline_dirty(void) { dirty++; }
'''
functions = ['gfx_get_texture_tile','gfx_texture_axis_needs_mirror','gfx_get_render_tile_slot',
             'gfx_texture_tile_width','gfx_texture_tile_height','gfx_texture_shift_scale',
             'gfx_prepare_texture_coord_state','gfx_dp_set_tile_size']
if 'static inline uint32_t gfx_texture_tile_span(' in source:
    functions.insert(1, 'gfx_texture_tile_span')
code += ''.join(function(name) for name in functions)
code += r'''
static void close_to(float actual,float expected) { assert(isfinite(actual) && fabsf(actual-expected)<0.0001f); }
static void configure(void) {
    // Z2_TOWN_room_00DL_003678 uses different shifts and independently wrapped
    // origins for the two wall layers, not one transform shared by both tiles.
    rdp.texture_tile[0]=(TextureTileState){.uls=0xfdb,.ult=0xfb3,.lrs=0x057,.lrt=0x02f,.shifts=15,.masks=5,.maskt=5};
    rdp.texture_tile[1]=(TextureTileState){.uls=0x06d,.ult=0xff2,.lrs=0x0e9,.lrt=0x06e,.shiftt=14,.masks=5,.maskt=5};
    textures[0]=(struct TextureHashmapNode){64,64};
    textures[1]=(struct TextureHashmapNode){64,32};
    rendering_state.textures[0]=&textures[0];rendering_state.textures[1]=&textures[1];
}
int main(int argc,char** argv) {
    assert(argc==2);configure();
    if (strcmp(argv[1],"dimensions")==0) {
        for (unsigned slot=0;slot<2;slot++) {
            assert(gfx_texture_tile_width(slot)==32 && gfx_texture_tile_height(slot)==32);
            const TextureTileState* t=&rdp.texture_tile[slot];
            assert(!gfx_texture_axis_needs_mirror(G_TX_MIRROR|G_TX_CLAMP,5,t->uls,t->lrs));
            assert(gfx_texture_axis_needs_mirror(G_TX_MIRROR,5,t->uls,t->lrs));
        }
    } else if (strcmp(argv[1],"coordinates")==0) {
        for (unsigned slot=0;slot<2;slot++) for (unsigned linear=0;linear<2;linear++) {
            gfx_prepare_texture_coord_state(&state,slot,slot,linear);
            const TextureTileState* t=&rdp.texture_tile[slot];
            for (int uv=-16000;uv<=16000;uv+=125) {
                float expectedU=(uv*(slot==0 ? 2.0f : 1.0f)+(linear ? 16 : 0)-t->uls*8.0f)/(32*textures[slot].upload_width);
                float expectedV=(uv*(slot==0 ? 1.0f : 4.0f)+(linear ? 16 : 0)-t->ult*8.0f)/(32*textures[slot].upload_height);
                close_to(uv*state.tex_u_scale[slot]+state.tex_u_bias[slot],expectedU);
                close_to(uv*state.tex_v_scale[slot]+state.tex_v_bias[slot],expectedV);
            }
        }
    } else {
        for (unsigned slot=0;slot<2;slot++) {
            // A scrolling 32x32 tile retains its allocation while both 12-bit
            // endpoints cross zero. A real size change still requests import.
            rdp.texture_tile[slot]=(TextureTileState){.lrs=124,.lrt=124};
            for (unsigned origin=0;origin<4096;origin++) {
                rdp.textures_changed[slot]=false;
                gfx_dp_set_tile_size(slot,origin,(origin+77)&4095,(origin+124)&4095,(origin+201)&4095);
                assert(!rdp.textures_changed[slot]);
                assert(gfx_texture_tile_width(slot)==32 && gfx_texture_tile_height(slot)==32);
            }
            gfx_dp_set_tile_size(slot,0,0,252,124);
            assert(rdp.textures_changed[slot] && gfx_texture_tile_width(slot)==64);
        }
        assert(dirty);
    }
    printf("Clock Town wrapped wall tiles: %s passed\n",argv[1]);
}
'''
with tempfile.TemporaryDirectory(prefix='mm-clock-town-walls-') as directory:
    path = Path(directory)
    (path/'test.c').write_text(code)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                    '-fsanitize=undefined',str(path/'test.c'),'-lm','-o',str(path/'test')],check=True)
    results = [subprocess.run([str(path/'test'),case]).returncode
               for case in ['dimensions','coordinates','scrolling']]
    if any(results):
        raise SystemExit(1)
