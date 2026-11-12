"""Restore RDP sampler state after fused materials and framebuffer effects."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/port/psp/backend/gfx/gfx_fast3d.c').read_text()
backend = (ROOT / 'src/port/psp/backend/gfx/gfx_scegu.c').read_text()


def function(text, name):
    start = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\s*\{', text, re.M).start()
    return text[start:text.index('\n}', text.index('{', start)) + 2] + '\n'


start = source.index('    for (int i = 0; i < 2; i++) {', source.index('static void gfx_prepare_tri_pipeline_state('))
samplers = source[start:source.index('\n    if (material_texture) {', start)]
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define G_TX_CLAMP 2
#define G_TX_WRAP 0
#define G_TX_NOMASK 0
enum { GU_CLAMP,GU_REPEAT,GU_LINEAR,GU_NEAREST };
struct SamplerState { int min_filter,mag_filter,wrap_s,wrap_t; };
static struct SamplerState tmu_state[2],sAppliedSamplerState;
static bool sAppliedSamplerStateValid;
static int active_texture_tile=0,wrapS,wrapT,minFilter,magFilter;
static unsigned commands,flushes;
static void sceGuTexFilter(int min,int mag) { commands++;minFilter=min;magFilter=mag; }
static void sceGuTexWrap(int s,int t) { commands++;wrapS=s;wrapT=t; }
typedef struct { bool linear_filter;uint32_t cms,cmt,masks,maskt; } TextureTileState;
static TextureTileState cached[2];
static struct { bool textures_changed[2]; TextureTileState tiles[2]; } rdp;
static struct { TextureTileState* textures[2]; } rendering_state;
static TextureTileState* gfx_get_texture_tile(int tile) { return &rdp.tiles[tile]; }
static void gfx_flush(void) { flushes++; }
static void import_texture(int tile) { (void)tile;assert(0); }
'''
code += function(backend, 'gfx_cm_to_opengl')
code += function(backend, 'gfx_scegu_apply_tmu_state')
code += function(backend, 'gfx_scegu_set_sampler_parameters')
code += r'''
static struct { void (*set_sampler_parameters)(int,bool,uint32_t,uint32_t,uint32_t,uint32_t); } api={gfx_scegu_set_sampler_parameters};
static const typeof(api)* gfx_rapi=&api;
static void prepare(bool backend_state_dirty,bool material_texture,bool flame_texture_atlas,bool linear_filter) {
    const bool used_textures[2]={true,true};
''' + samplers + r'''
}
int main(void) {
    cached[0]=(TextureTileState){true,G_TX_CLAMP,G_TX_CLAMP,5,5}; // Tree/horse shadow.
    cached[1]=(TextureTileState){true,G_TX_WRAP,G_TX_CLAMP,5,6};  // Intro tree layer.
    for (unsigned i=0;i<2;i++) { rendering_state.textures[i]=&cached[i];rdp.tiles[i]=cached[i]; }
    prepare(true,false,false,true);
    assert(wrapS==GU_CLAMP && wrapT==GU_CLAMP && minFilter==GU_LINEAR && magFilter==GU_LINEAR);
    unsigned before=commands;
    prepare(false,false,false,true);assert(commands==before);
    // Fused materials bypass rendering_state.textures and install repeating
    // sampling on TMU 0. Returning to a cache hit must restore the RDP clamp.
    gfx_scegu_set_sampler_parameters(0,true,G_TX_WRAP,G_TX_WRAP,1,1);
    assert(wrapS==GU_REPEAT && wrapT==GU_REPEAT);
    prepare(false,false,false,true);
    assert(wrapS==GU_CLAMP && wrapT==GU_CLAMP);
    // A framebuffer effect can also leave the hardware sampler changed while
    // texture allocations and their cached metadata remain identical.
    sceGuTexFilter(GU_NEAREST,GU_NEAREST);sceGuTexWrap(GU_CLAMP,GU_CLAMP);
    sAppliedSamplerStateValid=false;
    active_texture_tile=1;prepare(false,false,false,true);
    assert(wrapS==GU_REPEAT && wrapT==GU_CLAMP && minFilter==GU_LINEAR && magFilter==GU_LINEAR);
    before=commands;prepare(false,false,false,true);assert(commands==before);
    // Shared allocations can be sampled differently by the two RDP tiles.
    rendering_state.textures[1]=rendering_state.textures[0];
    prepare(false,false,false,true);
    assert(wrapS==GU_REPEAT && wrapT==GU_CLAMP);
    assert(tmu_state[0].wrap_s==GU_CLAMP && tmu_state[1].wrap_s==GU_REPEAT);
    puts("Sampler state: cached shadows/intro layers, fused material return, effect restoration and redundant command suppression passed");
}
'''
with tempfile.TemporaryDirectory(prefix='mm-sampler-state-') as directory:
    path = Path(directory)
    (path/'test.c').write_text(code)
    subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                    str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
