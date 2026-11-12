"""Exercise queued GE blur/capture, feedback pixels and list rollover on the host.

The command model checks ordering and coverage, not PSP rasterization or timing.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
mm = (ROOT / 'src/port/psp/mm_psp_gfx_scegu.c').read_text()
backend = (ROOT / 'src/port/psp/backend/gfx/gfx_scegu.c').read_text()


def function(name):
    start = backend.index('static void ' + name + '(')
    if backend.index(';', start) < backend.index('{', start):
        start = backend.index('static void ' + name + '(', start + 1)
    return backend[start:backend.index('\n}', start) + 2] + '\n'


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
#define GU_LIST_COMMAND_RESERVE 4096
static int sMaxScreenHeight=480,sMaxBufferWidth=768,sColorPixelSize=4;
static int sColorPixelFormat=3;
static int screenWidth=480,screenHeight=272,bufferWidth=512;
#define SCR_WIDTH screenWidth
#define SCR_HEIGHT screenHeight
#define BUF_WIDTH bufferWidth
#define FRAMEBUFFER_SIZE ((size_t)BUF_WIDTH*SCR_HEIGHT*sColorPixelSize)
static size_t sFramebufferCapacity=768*512*4;
static unsigned char frames[3][768*512*4],scene[768*512*4],expected[768*512*4],history[768*512*4];
// Relative GU targets are opaque tokens; transfers must resolve their addresses.
static void* const targets[3]={(void*)0x40000000,(void*)0x40080000,(void*)0x40100000};
static void* sDrawBuffer;
static void* drawTarget;
static bool active,finished,lighting,textureFresh,renderPending,transferPending;
static unsigned restarts,draws,captures,originalCalls,syncs,cacheMaintenance;
static bool enabled[GU_GEQUAL+1];
static int scissor[4],sScissorBounds[4],depthMask;
static unsigned char list[65536] __attribute__((aligned(64)));
static size_t memoryUsed;
struct ShaderProgram { int dummy; } shader;
static struct ShaderProgram* sAppliedShader=&shader;
static int active_texture_tile=1;
static bool sDepthTestEnabled=true,sDepthWriteEnabled=true,gl_blend=true,sAppliedSamplerStateValid;
static uint32_t sTextureEnvColor=0x12345678;
static struct { unsigned tex; } tmu_state[2]={{1},{2}};
static struct { unsigned width,height; } gfx_current_dimensions={480,272};
enum { SCENE,DRAW,COPY,TEX_SYNC,TEX_FLUSH,HUD };
struct Command { int op,count;void* target;const void* source;const void* vertices; };
static struct Command commands[64];
static unsigned commandCount;
static void execute(void);
static void enqueue(struct Command command) {
    assert(active && commandCount<64);commands[commandCount++]=command;
}
static int nextpow2(int value) { int result=1;while(result<value) result*=2;return result; }
static void* gfx_scegu_vram_cpu_addr(const void* target) {
    for (unsigned i=0;i<3;i++) if (target==targets[i]) return frames[i];
    abort();
}
static void sceGuStart(int context,void* buffer) {
    assert(context==GU_DIRECT && buffer==list && !active && !commandCount);
    active=true;finished=false;drawTarget=targets[0];memoryUsed=0;
}
static void gfx_psp_submit_reset(void) { restarts++; }
static void sceGuDrawBufferList(int format,void* target,int width) {
    assert(format==sColorPixelFormat && width==BUF_WIDTH && active);drawTarget=target;
}
static void gfx_scegu_set_lighting(const void* state) { assert(!state);lighting=false; }
static void sceGuFinish(void) { assert(active);active=false;finished=true; }
static void sceGuSync(int a,int b) { (void)a;(void)b;assert(finished);execute();syncs++; }
static int sceGuCheckList(void) { return (int)memoryUsed; }
static void sceGuCopyImage(int format,int sx,int sy,int width,int height,int srcWidth,void* source,
                           int dx,int dy,int dstWidth,void* target) {
    assert(format==sColorPixelFormat && !sx && !sy && !dx && !dy);
    assert(width==SCR_WIDTH && height==SCR_HEIGHT && srcWidth==BUF_WIDTH && dstWidth==BUF_WIDTH);
    assert(source==gfx_scegu_vram_cpu_addr(sDrawBuffer));
    enqueue((struct Command){.op=COPY,.source=source,.target=target});captures++;
}
static void sceGuTexSync(void) { enqueue((struct Command){.op=TEX_SYNC}); }
static void sceGuTexFlush(void) { enqueue((struct Command){.op=TEX_FLUSH}); }
static void sceKernelDcacheWritebackInvalidateRange(void* data,size_t bytes) {
    assert(data && bytes==768*512*4);cacheMaintenance++;
}
static void sceGuPixelMask(unsigned mask) { assert(!mask); }
static void sceGuDisable(int state) { enabled[state]=false; }
static void sceGuEnable(int state) { enabled[state]=true; }
static void sceGuDepthMask(int mask) { depthMask=mask; }
static void sceGuDepthFunc(int function) { assert(function==GU_GEQUAL); }
static void sceGuScissor(int x,int y,int right,int bottom) {
    assert(x>=0 && y>=0 && right<=SCR_WIDTH && bottom<=SCR_HEIGHT);
    scissor[0]=x;scissor[1]=y;scissor[2]=right;scissor[3]=bottom;
}
static void sceGuBlendFunc(int op,int src,int dst,unsigned a,unsigned b) {
    assert(op==GU_ADD && src==GU_SRC_ALPHA && dst==GU_ONE_MINUS_SRC_ALPHA && !a && !b);
}
static void sceGuTexMode(int format,int max,int swizzle,int flag) { assert(format==sColorPixelFormat && !max && !swizzle && !flag); }
static void sceGuTexFunc(int function,int component) { assert(function==GU_TFX_MODULATE && component==GU_TCC_RGB); }
static void sceGuTexFilter(int min,int mag) { assert(min==GU_NEAREST && mag==GU_NEAREST); }
static void sceGuTexWrap(int s,int t) { assert(s==GU_CLAMP && t==GU_CLAMP); }
static void sceGuTexOffset(float s,float t) { assert(s==0 && t==0); }
static void sceGuTexScale(float s,float t) { assert(s==1 && t==1); }
static void sceGuTexEnvColor(unsigned color) { assert(color==sTextureEnvColor); }
static void texman_invalidate_binding(void) {}
static void* sceGuGetMemory(size_t bytes) {
    void* result=list+memoryUsed;memoryUsed+=bytes+8;assert(memoryUsed<sizeof(list));return result;
}
static const void* texture;
static void sceGuTexImage(int level,int width,int height,int stride,const void* data) {
    assert(level==0 && width<=512 && height<=512 && stride==BUF_WIDTH);texture=data;
}
static void sceGuDrawArray(int primitive,int format,int count,const void* indices,const void* vertices);
static void gfx_scegu_apply_shader(struct ShaderProgram* p) { assert(p==&shader);sAppliedShader=p; }
static void gfx_scegu_select_texture(int tile,unsigned id) {
    assert(tile==1 && id==2);active_texture_tile=tile;
}
static void MmPspGfx_ApplyVisMonoOriginal(uint8_t a,uint8_t b,uint8_t c,uint8_t d,uint8_t e,uint8_t f,uint8_t g) {
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;originalCalls++;
}
static void gfx_scegu_start_list(void);
'''
tests = r'''
static uint32_t pixel(const void* data,size_t index) {
    return sColorPixelSize==4 ? ((const uint32_t*)data)[index] : ((const uint16_t*)data)[index];
}
static void put(void* data,size_t index,uint32_t value) {
    if (sColorPixelSize==4) ((uint32_t*)data)[index]=value;else ((uint16_t*)data)[index]=(uint16_t)value;
}
static uint32_t blend(uint32_t old,uint32_t current,unsigned alpha) {
    uint32_t result=0;
    for (unsigned component=0;component<3;component++) {
        unsigned shift=sColorPixelSize==4 ? component*8 : (component==0 ? 0 : component==1 ? 5 : 11);
        unsigned mask=sColorPixelSize==4 ? 255 : (component==1 ? 63 : 31);
        result|=(((((old>>shift)&mask)*alpha+((current>>shift)&mask)*(255-alpha))/255)&mask)<<shift;
    }
    return result;
}
static void sceGuDrawArray(int primitive,int format,int count,const void* indices,const void* data) {
    const MmPspMotionBlurVertex* v=data;
    assert(primitive==GU_SPRITES && format==15 && count>=2 && !(count&1) && !indices);
    assert(active && drawTarget==sDrawBuffer && !lighting);
    for (int i=0;i<count;i+=2) {
        assert(v[i+1].x>v[i].x && v[i+1].x-v[i].x<=32 && v[i+1].y>v[i].y);
        assert(v[i+1].x<=SCR_WIDTH && v[i+1].y<=SCR_HEIGHT);
        assert(v[i].color==v[i+1].color && (v[i].color&0xffffff)==0xffffff);
        assert((const unsigned char*)texture==(const unsigned char*)sMmPspMotionBlurBuffer+(v[i].x-v[i].u)*sColorPixelSize);
        assert(v[i+1].u-v[i].u==v[i+1].x-v[i].x && v[i+1].v-v[i].v==v[i+1].y-v[i].y);
        if (i) assert(v[i].x==v[i-1].x);
    }
    enqueue((struct Command){.op=DRAW,.count=count,.target=gfx_scegu_vram_cpu_addr(drawTarget),.source=texture,.vertices=data});
    draws++;
}
static void execute(void) {
    for (unsigned n=0;n<commandCount;n++) {
        const struct Command* command=&commands[n];
        switch (command->op) {
        case SCENE:
            memcpy(command->target,scene,FRAMEBUFFER_SIZE);renderPending=true;break;
        case DRAW: {
            assert(!transferPending && textureFresh);
            const MmPspMotionBlurVertex* v=command->vertices;
            for (int i=0;i<command->count;i+=2) {
                for (unsigned y=v[i].y;y<v[i+1].y;y++) for (unsigned x=v[i].x;x<v[i+1].x;x++) {
                    size_t dst=(size_t)y*BUF_WIDTH+x;
                    size_t src=(size_t)(y-v[i].y+v[i].v)*BUF_WIDTH+x-v[i].x+v[i].u;
                    put(command->target,dst,blend(pixel(command->source,src),pixel(command->target,dst),v[i].color>>24));
                }
            }
            renderPending=true;break;
        }
        case COPY:
            assert(!renderPending && !transferPending && command->target==sMmPspMotionBlurBuffer);
            // Capture must see the fully blended scene, before the queued HUD.
            for (int y=0;y<SCR_HEIGHT;y++) {
                size_t offset=(size_t)y*BUF_WIDTH*sColorPixelSize,bytes=(size_t)SCR_WIDTH*sColorPixelSize;
                assert(!memcmp((const unsigned char*)command->source+offset,expected+offset,bytes));
                memcpy((unsigned char*)command->target+offset,(const unsigned char*)command->source+offset,bytes);
            }
            transferPending=true;textureFresh=false;break;
        case TEX_SYNC: transferPending=false;renderPending=false;break;
        case TEX_FLUSH: assert(!transferPending);textureFresh=true;break;
        case HUD: put(command->target,0,0xdeadbeef);renderPending=true;break;
        default: abort();
        }
    }
    assert(!transferPending);commandCount=0;renderPending=false;
}
int main(void) {
    unsigned cases=0;
    for (unsigned mode=0;mode<5;mode++) {
        SCR_WIDTH=mode>=2 ? 720 : 480;SCR_HEIGHT=mode>=2 ? 480 : 272;BUF_WIDTH=mode>=2 ? 768 : 512;
        gfx_current_dimensions.width=mode==1 ? 362 : mode==3 ? 643 : mode==4 ? 29 : SCR_WIDTH;
        gfx_current_dimensions.height=mode==3 ? 451 : mode==4 ? 31 : SCR_HEIGHT;
        unsigned buffers=mode>=2 ? 2 : 3;
        bool valid=false;
        for (unsigned frame=0;frame<16;frame++) {
            // Change only the pixel format mid-mode to exercise geometry reset.
            sColorPixelSize=frame<8 ? 4 : 2;sColorPixelFormat=frame<8 ? 3 : 0;
            if (frame==8) valid=false;
            unsigned alpha=frame==5 ? 0 : frame==6 ? 255 : frame==10 ? 1 : 180;
            bool reset=frame==0 || frame==7;
            bool shouldDraw=valid && !reset && alpha;
            sDrawBuffer=targets[(frame+1)%buffers];
            void* target=gfx_scegu_vram_cpu_addr(sDrawBuffer);
            memset(scene,0xcd,FRAMEBUFFER_SIZE);
            for (int y=0;y<SCR_HEIGHT;y++) for (int x=0;x<SCR_WIDTH;x++)
                put(scene,(size_t)y*BUF_WIDTH+x,(uint32_t)(x*12345+y*78901+frame*456789)&0x00ffffff);
            memcpy(expected,scene,FRAMEBUFFER_SIZE);
            int width=(int)gfx_current_dimensions.width,height=(int)gfx_current_dimensions.height;
            int left=(SCR_WIDTH-width)/2,top=(SCR_HEIGHT-height)/2;
            if (shouldDraw) for (int y=top;y<top+height;y++) for (int x=left;x<left+width;x++) {
                size_t index=(size_t)y*BUF_WIDTH+x;
                put(expected,index,blend(pixel(history,index),pixel(scene,index),alpha));
            }
            // A narrower existing scene scissor must survive the effect.
            sScissorBounds[0]=left+1;sScissorBounds[1]=top+1;
            sScissorBounds[2]=left+width-1;sScissorBounds[3]=top+height-1;
            sDepthTestEnabled=(frame&1)!=0;sDepthWriteEnabled=(frame&2)!=0;gl_blend=(frame&4)!=0;
            gfx_scegu_start_list();lighting=true;
            enqueue((struct Command){.op=SCENE,.target=target});
            // Force the real reserve helper to fence once before starting blur.
            bool rollover=frame==9;
            if (rollover) memoryUsed=sizeof(list)-16;
            unsigned beforeDraw=draws,beforeCapture=captures,beforeRestart=restarts,beforeSync=syncs;
            active_texture_tile=1;
            gfx_scegu_apply_vismono(MM_PSP_MOTION_BLUR_PRIM_R,MM_PSP_MOTION_BLUR_PRIM_G,
                MM_PSP_MOTION_BLUR_PRIM_B,alpha,MM_PSP_MOTION_BLUR_ENV_R,
                MM_PSP_MOTION_BLUR_ENV_G,reset ? MM_PSP_MOTION_BLUR_RESET : 0);
            assert(active && drawTarget==sDrawBuffer && captures==beforeCapture+1);
            assert(restarts==beforeRestart+rollover && syncs==beforeSync+rollover);
            unsigned images=left<512 && left+width>512 ? 2 : 1;
            assert(draws==beforeDraw+(shouldDraw ? images : 0));
            if (shouldDraw) {
                assert(enabled[GU_DEPTH_TEST]==sDepthTestEnabled && enabled[GU_BLEND]==gl_blend);
                assert(depthMask==(sDepthWriteEnabled ? GU_FALSE : GU_TRUE));
                assert(!memcmp(scissor,sScissorBounds,sizeof(scissor)));
                assert(sAppliedShader==&shader && active_texture_tile==1 && !sAppliedSamplerStateValid);
            }
            enqueue((struct Command){.op=HUD,.target=target});
            sceGuFinish();sceGuSync(0,0);
            for (int y=0;y<SCR_HEIGHT;y++) {
                size_t offset=(size_t)y*BUF_WIDTH*sColorPixelSize,bytes=(size_t)SCR_WIDTH*sColorPixelSize;
                assert(!memcmp((unsigned char*)sMmPspMotionBlurBuffer+offset,expected+offset,bytes));
            }
            assert(pixel(target,0)==(sColorPixelSize==4 ? 0xdeadbeefU : 0xbeefU));
            memcpy(history,expected,FRAMEBUFFER_SIZE);valid=true;cases++;
        }
    }
    gfx_scegu_apply_vismono(1,2,3,4,5,6,7);assert(originalCalls==1);
    assert(sMmPspMotionBlurBufferSize>=sFramebufferCapacity && cacheMaintenance==1);
    free(sMmPspMotionBlurBuffer);
    printf("MM blur: %u queued LCD/TV/16/32-bit cases; feedback pixels, 32px coverage, pre-HUD capture, resets, state restore and rollover passed; zero normal-path CPU waits/copies\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='mm-motion-blur-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(preamble + constants + '\n' +
                               function('gfx_scegu_start_list') +
                               function('gfx_scegu_reserve_list_memory') + effect + tests)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True,
                   env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
