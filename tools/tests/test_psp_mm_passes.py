"""Check MM's extra material passes with the newer 36-byte GU vertex stream."""
from pathlib import Path
import re
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/port/psp/backend/gfx/gfx_scegu.c').read_text()


def function(name):
    start = re.search(r'^static [^\n]*\b' + name + r'\([^;]*?\)\s*\{', source, re.M).start()
    return source[start:source.index('\n}', start) + 2] + '\n'


start = source.index('typedef struct Vertex {')
vertex = source[start:source.index('typedef struct FogVertex', start)]
preamble = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
enum { GU_TRIANGLES,GU_TEXTURE_2D,GU_ALPHA_TEST,GU_EQUAL,GU_GEQUAL,GU_BLEND,
       GU_ADD,GU_OTHER_COLOR,GU_FIX,GU_SRC_ALPHA,GU_ONE_MINUS_SRC_ALPHA,
       GU_TFX_REPLACE,GU_TFX_BLEND,GU_TCC_RGB,GU_TCC_RGBA };
#define GU_TEXTURE_32BITF 1
#define GU_COLOR_8888 2
#define GU_NORMAL_32BITF 4
#define GU_VERTEX_32BITF 8
#define GU_TRANSFORM_3D 16
#define GU_TRUE 1
#define GU_FALSE 0
struct ShaderProgram {int dummy;} shader;
static struct ShaderProgram* sAppliedShader=&shader;
static bool sDepthTestEnabled=true,sDepthWriteEnabled=true,gl_blend=true,lighting=true;
static unsigned sTextureEnvColor=0x12345678,draws,writebacks,uploads;
static uint8_t storage[4096] __attribute__((aligned(64)));
static size_t used;
static void* lastVertices;
static void* gfx_scegu_upload_vertices(const void* p,size_t bytes) {
    used=(used+63)&~63U;assert(used+bytes<=sizeof(storage));void* out=storage+used;
    memcpy(out,p,bytes);used+=bytes;uploads++;return out;
}
static void gfx_psp_submit_writeback_vertices(void* p,size_t bytes) {
    assert(p && bytes==108);writebacks++;
}
static void gfx_scegu_set_lighting(const void* p) {assert(p==NULL);lighting=false;}
static void gfx_scegu_apply_shader(struct ShaderProgram* p) {assert(p==&shader);sAppliedShader=p;}
static void sceGuEnable(unsigned s) {(void)s;}
static void sceGuDisable(unsigned s) {(void)s;}
static void sceGuTexFunc(unsigned f,unsigned c) {(void)f;(void)c;}
static void sceGuDepthMask(unsigned m) {(void)m;}
static void sceGuDepthFunc(unsigned f) {(void)f;}
static void sceGuBlendFunc(unsigned a,unsigned b,unsigned c,unsigned d,unsigned e) {
    (void)a;(void)b;(void)c;(void)d;(void)e;
}
static void sceGuTexEnvColor(unsigned c) {(void)c;}
static void sceGuDrawArray(unsigned primitive,unsigned format,unsigned count,const void* indices,const void* vertices) {
    assert(primitive==GU_TRIANGLES && format==31 && count==3 && indices==NULL && !lighting);
    lastVertices=(void*)vertices;draws++;
}
'''
tests = r'''
int main(void) {
    Vertex input[3]={0};
    for(unsigned i=0;i<3;i++) {
        input[i].x=10+i;input[i].y=20+i;input[i].z=30+i;
        input[i].normal[0]=90+i;input[i].normal[1]=100+i;input[i].normal[2]=110+i;
        input[i].color=(0x20U+i)<<24|0xabcdef;
    }
    gfx_scegu_draw_texture_multiply_triangles((float*)input,sizeof(input),1);
    assert(memcmp(lastVertices,input,sizeof(input))==0);
    void* multiply=lastVertices;
    for(unsigned alpha=0;alpha<2;alpha++) {
        lighting=true;
        gfx_scegu_draw_color_add_triangles((float*)input,sizeof(input),1,10,20,30,alpha);
        Vertex* result=lastVertices;
        for(unsigned i=0;i<3;i++) {
            assert(result[i].x==input[i].x && result[i].y==input[i].y && result[i].z==input[i].z);
            assert(memcmp(result[i].normal,input[i].normal,sizeof(input[i].normal))==0);
            assert(result[i].color==(0x1e140aU|(alpha ? input[i].color&0xff000000U : 0xff000000U)));
            assert(input[i].color==((0x20U+i)<<24|0xabcdef));
        }
        assert(memcmp(multiply,input,sizeof(input))==0);
    }
    assert(draws==3 && uploads==3 && writebacks==2);
    puts("MM material passes: vertex stride, unlit addition/multiplication, alpha, cache writeback and immutable uploads passed");
}
'''
with tempfile.TemporaryDirectory(prefix='mm-material-passes-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(preamble + vertex + function('gfx_scegu_draw_texture_multiply_triangles') +
                               function('gfx_scegu_draw_color_add_triangles') + tests)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined,address',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
