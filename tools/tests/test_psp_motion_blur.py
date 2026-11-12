"""Check MM feedback capture and GU state across double/triple framebuffer rotation."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
mm = (ROOT / 'src/port/psp/mm_psp_gfx_scegu.c').read_text()
backend = (ROOT / 'src/port/psp/backend/gfx/gfx_scegu.c').read_text()
start = backend.index('static void gfx_scegu_start_list(void) {')
restart = backend[start:backend.index('\n}', start) + 2]
effect = mm[mm.index('typedef struct MmPspMotionBlurVertex'):]
constants = '\n'.join(re.findall(r'^#define MM_PSP_MOTION_BLUR_[^\n]+',
                                 (ROOT / 'src/port/psp/oot_psp_gfx_ext.h').read_text(), re.M))
preamble = r'''
#define _POSIX_C_SOURCE 200112L
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
enum { GU_DIRECT,GU_DEPTH_TEST,GU_ALPHA_TEST,GU_SCISSOR_TEST,GU_TEXTURE_2D,GU_BLEND,
       GU_ADD,GU_SRC_ALPHA,GU_ONE_MINUS_SRC_ALPHA,GU_TFX_MODULATE,GU_TCC_RGB,
       GU_NEAREST,GU_CLAMP,GU_SPRITES,GU_SYNC_FINISH,GU_SYNC_WHAT_DONE,GU_GEQUAL };
#define GU_TRUE 1
#define GU_FALSE 0
#define GU_TEXTURE_16BIT 1
#define GU_COLOR_8888 2
#define GU_VERTEX_16BIT 4
#define GU_TRANSFORM_2D 8
static int sMaxScreenHeight=480,sMaxBufferWidth=768,sColorPixelSize=4;
static int sColorPixelFormat=3;
static int screenWidth=480,screenHeight=272,bufferWidth=512;
#define SCR_WIDTH screenWidth
#define SCR_HEIGHT screenHeight
#define BUF_WIDTH bufferWidth
#define FRAMEBUFFER_SIZE ((size_t)BUF_WIDTH*SCR_HEIGHT*sColorPixelSize)
static size_t sFramebufferCapacity=768*512*4;
static unsigned char frames[3][768*512*4];
static void* sDrawBuffer;
static void* drawTarget;
static bool active,finished,lighting,textureFresh;
static unsigned restarts,draws,captures,originalCalls;
static char list[65536];
static size_t memoryUsed;
struct ShaderProgram { int dummy; } shader;
static struct ShaderProgram* sAppliedShader=&shader;
static int active_texture_tile=1;
static bool sDepthTestEnabled=true,sDepthWriteEnabled=true,gl_blend=true,sAppliedSamplerStateValid;
static uint32_t sTextureEnvColor=0x12345678;
static struct { unsigned tex; } tmu_state[2]={{1},{2}};
static struct { unsigned width,height; } gfx_current_dimensions={480,272};
static int nextpow2(int value) { int result=1;while(result<value) result*=2;return result; }
static void sceGuStart(int context,void* commands) {
    assert(context==GU_DIRECT && commands==list && !active);
    active=true;finished=false;drawTarget=frames[0];memoryUsed=0;
}
static void gfx_psp_submit_reset(void) { restarts++; }
static void sceGuDrawBufferList(int format,void* target,int width) {
    assert(format==sColorPixelFormat && width==BUF_WIDTH && active);drawTarget=target;
}
static void gfx_scegu_set_lighting(const void* state) { assert(!state);lighting=false; }
static void sceGuFinish(void) { assert(active);active=false;finished=true; }
static void sceGuSync(int a,int b) { (void)a;(void)b;assert(finished); }
static void gfx_scegu_copy_framebuffer_from_vram(void* dst,const void* src) {
    assert(finished && !active && src==sDrawBuffer);
    memcpy(dst,src,FRAMEBUFFER_SIZE);captures++;textureFresh=false;
}
static void sceKernelDcacheWritebackRange(void* data,size_t bytes) { assert(data && bytes); }
static void sceGuPixelMask(unsigned mask) { assert(!mask); }
static void sceGuDisable(int state) { (void)state; }
static void sceGuEnable(int state) { (void)state; }
static void sceGuDepthMask(int mask) { (void)mask; }
static void sceGuDepthFunc(int function) { (void)function; }
static void sceGuScissor(int x,int y,int right,int bottom) { assert(x>=0 && y>=0 && right<=SCR_WIDTH && bottom<=SCR_HEIGHT); }
static void sceGuBlendFunc(int op,int src,int dst,unsigned a,unsigned b) {
    assert(op==GU_ADD && src==GU_SRC_ALPHA && dst==GU_ONE_MINUS_SRC_ALPHA && !a && !b);
}
static void sceGuTexMode(int format,int max,int swizzle,int flag) { (void)max;(void)swizzle;(void)flag;assert(format==sColorPixelFormat); }
static void sceGuTexFunc(int function,int component) { assert(function==GU_TFX_MODULATE && component==GU_TCC_RGB); }
static void sceGuTexFilter(int min,int mag) { assert(min==GU_NEAREST && mag==GU_NEAREST); }
static void sceGuTexWrap(int s,int t) { assert(s==GU_CLAMP && t==GU_CLAMP); }
static void sceGuTexOffset(float s,float t) { assert(s==0 && t==0); }
static void sceGuTexScale(float s,float t) { assert(s==1 && t==1); }
static void sceGuTexFlush(void) { textureFresh=true; }
static void sceGuTexEnvColor(unsigned color) { assert(color==sTextureEnvColor); }
static void texman_invalidate_binding(void) {}
static void* sceGuGetMemory(size_t bytes) { void* result=list+memoryUsed;memoryUsed+=bytes;assert(memoryUsed<sizeof(list));return result; }
static const void* texture;
static void sceGuTexImage(int level,int width,int height,int stride,const void* data) {
    assert(level==0 && width<=512 && height<=512 && stride==BUF_WIDTH);texture=data;
}
static void sceGuDrawArray(int primitive,int format,int count,const void* indices,const void* vertices);
static void gfx_scegu_apply_shader(struct ShaderProgram* p) { assert(p==&shader);sAppliedShader=p; }
static void gfx_scegu_select_texture(int tile,unsigned id) { assert(tile==1 && id==2); }
static void MmPspGfx_ApplyVisMonoOriginal(uint8_t a,uint8_t b,uint8_t c,uint8_t d,uint8_t e,uint8_t f,uint8_t g) {
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;originalCalls++;
}
'''
tests = r'''
static void sceGuDrawArray(int primitive,int format,int count,const void* indices,const void* data) {
    const MmPspMotionBlurVertex* v=data;
    assert(primitive==GU_SPRITES && format==15 && count==2 && !indices);
    assert(active && drawTarget==sDrawBuffer && !lighting && textureFresh);
    assert(v[1].x>v[0].x && v[1].y>v[0].y && v[1].x<=SCR_WIDTH && v[1].y<=SCR_HEIGHT);
    assert(v[0].color==v[1].color && (v[0].color&0xffffff)==0xffffff);
    assert((const unsigned char*)texture==(const unsigned char*)sMmPspMotionBlurBuffer+(v[0].x-v[0].u)*4);
    assert(v[1].u-v[0].u==v[1].x-v[0].x && v[1].v-v[0].v==v[1].y-v[0].y);
    // Record the effect's output in the draw target, then ensure capture uses
    // that completed result, instead of stale/unblended framebuffer data.
    ((uint32_t*)drawTarget)[(size_t)v[0].y*BUF_WIDTH+v[0].x]=0x12345678;
    draws++;
}
int main(void) {
    for (unsigned mode=0;mode<3;mode++) {
        SCR_WIDTH=mode==2 ? 720 : 480;SCR_HEIGHT=mode==2 ? 480 : 272;BUF_WIDTH=mode==2 ? 768 : 512;
        gfx_current_dimensions.width=mode==1 ? 362 : SCR_WIDTH;
        gfx_current_dimensions.height=SCR_HEIGHT;
        unsigned buffers=mode==2 ? 2 : 3;
        for (unsigned frame=0;frame<12;frame++) {
            sDrawBuffer=frames[(frame+1)%buffers];
            memset(sDrawBuffer,frame+10,FRAMEBUFFER_SIZE);
            gfx_scegu_start_list();lighting=true;
            unsigned beforeDraw=draws,beforeCapture=captures,beforeRestart=restarts;
            active_texture_tile=1;
            gfx_scegu_apply_vismono(MM_PSP_MOTION_BLUR_PRIM_R,MM_PSP_MOTION_BLUR_PRIM_G,
                MM_PSP_MOTION_BLUR_PRIM_B,frame==5 ? 0 : 180,MM_PSP_MOTION_BLUR_ENV_R,
                MM_PSP_MOTION_BLUR_ENV_G,frame==0 || frame==7 ? MM_PSP_MOTION_BLUR_RESET : 0);
            assert(active && drawTarget==sDrawBuffer && captures==beforeCapture+1 && restarts>beforeRestart);
            assert(memcmp(sMmPspMotionBlurBuffer,sDrawBuffer,FRAMEBUFFER_SIZE)==0);
            if (frame==0 || frame==5 || frame==7) assert(draws==beforeDraw);
            else assert(draws==beforeDraw+(mode==2 ? 2 : 1));
            sceGuFinish();sceGuSync(0,0);
        }
    }
    gfx_scegu_apply_vismono(1,2,3,4,5,6,7);assert(originalCalls==1);
    assert(sMmPspMotionBlurBufferSize>=sFramebufferCapacity);
    free(sMmPspMotionBlurBuffer);
    puts("MM blur: rotating LCD/TV buffers, 4:3 viewport, unlit sprites, fresh texture, feedback capture and history reset passed");
}
'''
with tempfile.TemporaryDirectory(prefix='mm-motion-blur-') as directory:
    path = Path(directory)
    (path/'test.c').write_text(preamble + constants + '\n' + restart + '\n' + effect + tests)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                    str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
