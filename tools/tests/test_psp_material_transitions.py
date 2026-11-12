"""Check actual import/bind transitions after uploads, cache hits and shadows."""
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


start = source.index('    for (int i = 0; i < 2; i++) {', source.index('static void gfx_prepare_tri_pipeline_state('))
samplers = source[start:source.index('\n    if (material_texture) {', start)]
start = source.index('    } else if ((active_texture >= 0)', start)
binding = '    if ((active_texture >= 0)' + source[start + len('    } else if ((active_texture >= 0)'):source.index('\n\n    struct TriPipelineState *state', start)]
constants = '\n'.join(line for line in (ROOT / 'include/PR/gbi.h').read_text().splitlines()
                      if re.match(r'#define G_IM_(?:FMT|SIZ)_', line))
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TARGET_PSP 1
''' + constants + r'''
typedef struct { uint8_t fmt,siz;uint32_t cms,cmt,masks,maskt; } TextureTileState;
struct TextureHashmapNode { unsigned texture_id;bool linear_filter;uint32_t cms,cmt,masks,maskt; } nodes[2];
static struct {
    struct TextureHashmapNode* textures[2];
    unsigned bound_texture_id;
    int bound_texture_tile;
} rendering_state;
static struct {
    TextureTileState tiles[2];bool textures_changed[2];
    struct { const uint8_t* addr;const void* shadow; } loaded_texture[2];
} rdp;
static unsigned gpuTexture=1,uploads,selects;
static int cacheMode;
static TextureTileState* gfx_get_texture_tile(int tile) { return &rdp.tiles[tile]; }
static void gfx_flush(void) {}
static void select_texture(int tile,unsigned id) { assert(tile==0 || tile==1);gpuTexture=id;selects++; }
static void set_sampler_parameters(int tile,bool filter,uint32_t s,uint32_t t,uint32_t masks,uint32_t maskt) {
    (void)tile;(void)filter;(void)s;(void)t;(void)masks;(void)maskt;
}
static struct {
    void (*select_texture)(int,unsigned);
    void (*set_sampler_parameters)(int,bool,uint32_t,uint32_t,uint32_t,uint32_t);
} api={select_texture,set_sampler_parameters},*gfx_rapi=&api;
static bool gfx_texture_cache_lookup(int tile,struct TextureHashmapNode** node,const uint8_t* addr,
                                     unsigned fmt,unsigned size,bool allocate,bool* uploadInPlace) {
    assert(addr==rdp.loaded_texture[tile].addr && fmt==G_IM_FMT_I && size==G_IM_SIZ_8b);
    *uploadInPlace=cacheMode==2;
    if (cacheMode==1 || cacheMode==2 || allocate) *node=&nodes[tile];
    if (cacheMode==2) select_texture(tile,nodes[tile].texture_id);
    return cacheMode==1;
}
static void gfx_validate_texture_source(int tile,const char* why) { (void)tile;(void)why; }
static void gfx_validate_texture_tile_dimensions(int tile,const char* why) { (void)tile;(void)why; }
static void uploaded_texture(int tile) {
    // PSP uploads finish by binding their destination, independently of the
    // interpreter's remembered draw texture. This is the real texman contract.
    gpuTexture=nodes[tile].texture_id;uploads++;
}
#define IMPORT(name) static void name(int tile) { uploaded_texture(tile); }
IMPORT(import_texture_rgba16)
IMPORT(import_texture_rgba32)
IMPORT(import_texture_ia4)
IMPORT(import_texture_ia8)
IMPORT(import_texture_ia16)
IMPORT(import_texture_ci4)
IMPORT(import_texture_ci8)
IMPORT(import_texture_i4)
IMPORT(import_texture_i8)
static void gfx_scegu_upload_shadow_mask(int tile,unsigned id,const void* mask) {
    assert(id==nodes[tile].texture_id && mask);uploaded_texture(tile);
}
'''
code += function('import_texture')
code += r'''
static void prepare(int active_texture) {
    const bool backend_state_dirty=false,material_texture=false,flame_texture_atlas=false,linear_filter=false;
    const bool used_textures[2]={true,true};
''' + samplers + binding + r'''
}
int main(void) {
    for (int frame=0;frame<96;frame++) for (int mode=0;mode<4;mode++) {
        nodes[0]=(struct TextureHashmapNode){.texture_id=1};
        nodes[1]=(struct TextureHashmapNode){.texture_id=2+(unsigned)frame};
        for (int tile=0;tile<2;tile++) {
            rdp.tiles[tile]=(TextureTileState){.fmt=G_IM_FMT_I,.siz=G_IM_SIZ_8b};
            rendering_state.textures[tile]=&nodes[tile];rdp.textures_changed[tile]=false;
        }
        rendering_state.bound_texture_id=gpuTexture=1;rendering_state.bound_texture_tile=0;
        cacheMode=mode;rdp.textures_changed[1]=true;
        rdp.loaded_texture[1].shadow=mode==3 ? &frame : NULL;
        prepare(0);
        assert(gpuTexture==1 && rendering_state.bound_texture_id==1 && rendering_state.bound_texture_tile==0);
        // The reverse transition must also rebind a cached TEXEL1-only draw
        // after importing a new image into TEXEL0.
        gpuTexture=rendering_state.bound_texture_id=nodes[1].texture_id;
        rendering_state.bound_texture_tile=1;rdp.textures_changed[0]=true;
        rdp.loaded_texture[1].shadow=NULL;
        prepare(1);
        assert(gpuTexture==nodes[1].texture_id && rendering_state.bound_texture_tile==1);
    }
    assert(uploads && selects);
    puts("Material transitions: fresh, cached, mutable and GPU-shadow imports retain the correct base/secondary draw binding");
}
'''
with tempfile.TemporaryDirectory(prefix='mm-material-transitions-') as directory:
    path = Path(directory)
    (path/'test.c').write_text(code)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                    str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
