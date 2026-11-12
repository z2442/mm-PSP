#!/usr/bin/env python3
"""Exercise clipping, UV emission and both real frontend draw passes together.

An affine UV field on a plane stays continuous after clipping and tessellation.
Check it independently from the emitted vertices, including poisoned old batches,
and require bit-identical positions/depth bias for the two texture layers.
The PSP VFPU implementation is checked separately by test_psp_vertex_pipeline.py.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
GFX = ROOT / "src/port/psp/backend/gfx"
source = (GFX / "gfx_fast3d.c").read_text()


def section(start, end):
    offset = source.index(start)
    return source[offset:source.index(end, offset)]


def function(name):
    start = re.search(r"^static [^\n]*\b" + name + r"\([^;]*?\)\s*\{", source, re.M).start()
    return source[start:source.index("\n}", source.index("{", start)) + 2] + "\n"


preamble = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#define GFX_DL_HANDLER
#define MAX_BUFFERED 16
#define G_TX_NOMASK 0
#define CC_PRIM 3
#define CC_SHADE 4
#define CC_ENV 5
#define CC_LOD 6
#define SHADER_OPT_DEPTH_ONLY (1U<<31)
'''
declarations = section("struct RGBA {", "struct XYWidthHeight {")
declarations += section("struct LoadedVertex {", "#if defined(TARGET_PSP)\ntypedef char LoadedVertex")
declarations += section("struct ColorCombiner {", "#define COLOR_COMBINER_CACHE_SET_COUNT")
declarations += section("struct TriPipelineState {", "static struct RSP {")
clipping = section("// Bits for clipping", "static inline float vec3_dot(")
clipping += section("static inline float vec4_dot(", "static struct LoadedVertex temp_a[12];")
clipping += section("static struct LoadedVertex temp_a[12];", "static void gfx_flush(void) {")
# Select the portable clipper above, then compile the production PSP emit/flush.
buffers = "#define TARGET_PSP 1\n" + section("typedef struct psp_fast_t {", "static inline __attribute__((always_inline)) void gfx_two_texture_blend_pass_alphas(")
state = r'''
#include "gfx_psp_lighting.h"
static struct GfxPspLighting sBatchLighting;
static bool sBatchUsesLighting,sBatchHasVisibleFog;
static unsigned sBatchDepthBias,sTextureCacheFrameSerial=1;
static size_t buf_num_vert,buf_vbo_len,buf_vbo_num_tris;
static const struct RGBA white_color={255,255,255,255};
struct TextureHashmapNode { unsigned texture_id,last_used_frame; uint16_t upload_width,upload_height; };
static struct TextureHashmapNode textures[2]={{.texture_id=10},{.texture_id=20}};
static struct {
    struct TriPipelineState tri_pipeline;
    struct TextureHashmapNode* textures[2];
    bool alpha_blend;
    unsigned color_combiner_id,bound_texture_id;
    int bound_texture_tile;
} rendering_state;
static struct {
    TextureTileState texture_tile[2];
    struct RGBA prim_color,env_color,fog_color;
    uint8_t prim_lod_frac;
} rdp;
static TextureTileState* gfx_get_texture_tile(int slot) { return &rdp.texture_tile[slot]; }
void gfx_scegu_set_lighting(const struct GfxPspLighting* lighting) { (void)lighting; }
static psp_fast_t captured[2][MAX_BUFFERED*3];
static size_t counts[2];
static unsigned calls,selected,appliedBias,biases[2],multiplyCalls;
static void draw(float* data,size_t bytes,size_t tris) {
    assert(calls<2 && bytes==tris*3*sizeof(psp_fast_t));
    assert(selected==textures[calls].texture_id);
    counts[calls]=tris*3;biases[calls]=appliedBias;
    memcpy(captured[calls++],data,bytes);
}
static void multiply(float* data,size_t bytes,size_t tris) { multiplyCalls++;draw(data,bytes,tris); }
static void select_texture(int slot,unsigned id) { assert(id==textures[slot].texture_id);selected=id; }
static void set_alpha(bool enabled) { (void)enabled; }
static void set_bias(unsigned bias) { appliedBias=bias; }
static void fog(float* a,size_t b,size_t c,bool d,bool e) { (void)a;(void)b;(void)c;(void)d;(void)e;assert(false); }
static void add(float* a,size_t b,size_t c,uint8_t d,uint8_t e,uint8_t f,bool g) {
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;assert(false);
}
static struct {
    void (*draw_triangles)(float*,size_t,size_t);
    void (*set_use_alpha)(bool);
    void (*select_texture)(int,unsigned);
    void (*draw_fog_triangles)(float*,size_t,size_t,bool,bool);
    void (*set_depth_bias)(unsigned);
    void (*draw_texture_multiply_triangles)(float*,size_t,size_t);
    void (*draw_color_add_triangles)(float*,size_t,size_t,uint8_t,uint8_t,uint8_t,bool);
} api={draw,set_alpha,select_texture,fog,set_bias,multiply,add},*gfx_rapi=&api;
'''
preparation = section("static inline uint32_t gfx_texture_tile_span(",
                      "static inline bool gfx_texture_axis_needs_mirror(")
preparation += section("static inline float gfx_texture_shift_scale(",
                       "#if defined(TARGET_PSP)\nstatic void gfx_prepare_flame_atlas_coord_state(")
emission = "".join(function(name) for name in (
    "gfx_get_vertex_color", "gfx_color_mul_channel", "gfx_arrow_shimmer_alpha",
    "gfx_color_mul_env", "gfx_color_mul_prim", "gfx_two_texture_blend_pass_alphas",
    "gfx_get_vertex_rgba", "gfx_get_constant_vertex_rgba", "gfx_initialize_fog_prefix",
    "gfx_emit_general_vertices", "gfx_flush"))
classify = "static void classify(struct LoadedVertex* d) {\nfloat x=d->_x,y=d->_y,z=d->_z,w=d->_w;\n"
classify += section("        uint32_t clipRej = 0;", "\n#if !defined(TARGET_PSP)\n        d->x = model_vec[0];") + "}\n"
tests = r'''
static float nearPlane;
static unsigned rejectedPlanes;
static float original_u(float x,float y,float z) { return 3*x-2*y+z+17; }
static float original_v(float x,float y,float z) { return x+4*y-2*z-31; }
static void project(struct LoadedVertex* v) {
    v->_x=v->x*0.9f;v->_y=v->y*1.7f;
    v->_z=v->z*(-(4000+nearPlane)/(4000-nearPlane))-2*4000*nearPlane/(4000-nearPlane);
    v->_w=v->w=-v->z;
    classify(v);
    v->u=original_u(v->x,v->y,v->z);v->v=original_v(v->x,v->y,v->z);
    v->color=(struct RGBA){100,150,200,255};
}
static void close_to(float actual,float expected,float tolerance) {
    float epsilon=tolerance+0.000001f*fabsf(expected);
    if (!(isfinite(actual) && fabsf(actual-expected)<=epsilon))
        fprintf(stderr,"layer mismatch: actual=%g expected=%g\n",actual,expected);
    assert(isfinite(actual) && fabsf(actual-expected)<=epsilon);
}
static void check_batch(unsigned expectedMultiply,unsigned expectedBias) {
    if (!buf_num_vert) return;
    buf_vbo_num_tris=buf_num_vert/3;
    selected=textures[0].texture_id;calls=multiplyCalls=0;sBatchDepthBias=expectedBias;
    gfx_flush();
    assert(calls==2 && counts[0]==counts[1] && multiplyCalls==expectedMultiply);
    assert(biases[0]==expectedBias && biases[1]==expectedBias);
    for (size_t i=0;i<counts[0];i++) {
        const psp_fast_t* a=&captured[0][i],*b=&captured[1][i];
        assert(memcmp(&a->x,&b->x,3*sizeof(float))==0);
        assert(memcmp(a->normal,b->normal,sizeof(a->normal))==0);
        for (unsigned slot=0;slot<2;slot++) {
            const psp_fast_t* output=&captured[slot][i];
            const TextureTileState* tile=&rdp.texture_tile[slot];
            /* Independent S10.5 -> normalized UV calculation for the fixture's
             * 32x32 tiles, quarter-texel origins and N64 shift convention. */
            float shiftS=tile->shifts>10 ? (float)(1U<<(16-tile->shifts)) : 1.0f/(1U<<tile->shifts);
            float shiftT=tile->shiftt>10 ? (float)(1U<<(16-tile->shiftt)) : 1.0f/(1U<<tile->shiftt);
            close_to(output->u,(original_u(a->x,a->y,a->z)*shiftS+16-tile->uls*8)/1024,0.00002f);
            close_to(output->v,(original_v(a->x,a->y,a->z)*shiftT+16-tile->ult*8)/1024,0.00002f);
        }
    }
    assert(buf_num_vert==0 && buf_vbo_len==0 && sBatchDepthBias==0);
}
int main(void) {
    struct ColorCombiner comb={.vertex_color_source={CC_SHADE,CC_SHADE}};
    struct TriPipelineState* state=&rendering_state.tri_pipeline;
    *state=(struct TriPipelineState){.comb=&comb,.use_texture=true,.two_texture_blend=true};
    rendering_state.textures[0]=&textures[0];rendering_state.textures[1]=&textures[1];
    rdp.prim_lod_frac=rdp.env_color.a=128;
    unsigned batches=0,clipped=0;
    for (unsigned multiplyMode=0;multiplyMode<2;multiplyMode++)
    for (unsigned nearMode=0;nearMode<2;nearMode++)
    for (unsigned pose=0;pose<3;pose++)
    for (int pan=-1000;pan<=1000;pan+=20) {
        nearPlane=nearMode ? 10 : 1;state->two_texture_multiply=multiplyMode;
        for (unsigned slot=0;slot<2;slot++) {
            unsigned low=(4090+pan+slot*37)&4095;
            rdp.texture_tile[slot]=(TextureTileState){.uls=low,.ult=low,
                .lrs=(low+124)&4095,.lrt=(low+124)&4095,
                .shifts=slot ? 0 : 15,.shiftt=slot ? 14 : 0};
            gfx_prepare_texture_coord_state(state,slot,slot,true);
        }
        struct LoadedVertex quad[4]={
            {.x=pan-400,.y=-90,.z=pose==0 ? -100 : (pose==1 ? -5 : 20)},
            {.x=pan+400,.y=-90,.z=pose==0 ? -100 : (pose==1 ? -5 : 20)},
            {.x=pan+400,.y=600,.z=pose==0 ? -500 : -5000},
            {.x=pan-400,.y=600,.z=pose==0 ? -500 : -5000}};
        for (unsigned i=0;i<4;i++) project(&quad[i]);
        buf_num_vert=buf_vbo_len=0;
        memset(buf_vbo_tex1,0x7f,sizeof(buf_vbo_tex1));
        for (unsigned triangle=0;triangle<2;triangle++) {
            struct LoadedVertex* input[]={&quad[0],&quad[triangle+1],&quad[triangle+2]};
            unsigned flags=input[0]->clip_rej|input[1]->clip_rej|input[2]->clip_rej;
            rejectedPlanes|=flags;
            struct LoadedVertex result[21],*vertices[21];size_t count;
            gfx_clip_single_vert(result,&count,input,flags);
            assert(buf_num_vert+count<=MAX_BUFFERED*3);
            for (size_t i=0;i<count;i++) {
                assert(result[i]._w>0);
                float epsilon=result[i]._w*0.00002f;
                assert(fabsf(result[i]._x)<=result[i]._w+epsilon);
                assert(fabsf(result[i]._y)<=result[i]._w+epsilon);
                assert(fabsf(result[i]._z)<=result[i]._w+epsilon);
                /* Sub-texel tolerance in the source's S10.5 units, allowing
                 * float cancellation when large coordinates cross zero. */
                close_to(result[i].u,original_u(result[i].x,result[i].y,result[i].z),0.02f);
                close_to(result[i].v,original_v(result[i].x,result[i].y,result[i].z),0.02f);
                vertices[i]=&result[i];
            }
            gfx_emit_general_vertices(vertices,count,state);
            clipped+=flags && count>3;
        }
        check_batch(multiplyMode,pose==2 ? 32 : 0);batches++;
    }
    assert(rejectedPlanes==CLIP_TEST_FLAGS && clipped>0);
    printf("Layer clipping: %u batches, %u retessellated triangles; continuous UVs and identical layer positions/depth bias\n",
           batches,clipped);
}
'''

with tempfile.TemporaryDirectory(prefix="mm-layer-clipping-") as directory:
    path = Path(directory)
    (path / "test.c").write_text(preamble + declarations + clipping + buffers + state +
                                 preparation + emission + classify + tests)
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                    "-Werror", "-Wno-unused-function", "-Wno-unused-variable",
                    "-I", str(GFX), "-fsanitize=undefined", str(path / "test.c"),
                    "-lm", "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
