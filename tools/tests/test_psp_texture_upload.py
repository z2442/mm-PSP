"""Exercise the real texture manager's upload/bind state with mock GU calls.

Only PSP address validation and VFPU copying are replaced for host execution.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GFX = ROOT / 'src/port/psp/backend/gfx'


class TextureUploadTest(unittest.TestCase):
    def test_upload_sets_format_and_refreshes_existing_binding(self):
        source = (GFX / 'psp_texture_manager.c').read_text()
        source = re.sub(r'#include [<"](?:psp\w+\.h|oot_psp_memory\.h)[>"]', '', source)
        start = source.index('static int texman_buffer_is_readable(')
        end = source.index('static unsigned int texman_active_texture_id(', start)
        source = source[:start] + '''
static int texman_buffer_is_readable(const void* p, unsigned int size) {return p && size;}
''' + source[end:]
        start = source.index('static void swizzle_fast(')
        end = source.index('int texman_inited(', start)
        source = source[:start] + '''
static void swizzle_fast(unsigned char* dst, const unsigned char* src, unsigned int w, unsigned int h) {
 memcpy(dst,src,w*h);
}
''' + source[end:]
        mock = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "psp_texture_manager.h"
#define GU_PSM_5650 0
#define GU_PSM_5551 1
#define GU_PSM_4444 2
#define GU_PSM_8888 3
#define GU_PSM_T4 4
#define GU_PSM_T8 5
#define GU_PSM_T16 6
#define GU_PSM_T32 7
#define GU_TRUE 1
#define GU_FALSE 0
#define OotPsp_MemcpyVfpu memcpy
static unsigned int mode, texWidth, texHeight, modeCalls, flushes;
static const void* texAddress;
static void sceKernelDcacheWritebackRange(void* p, unsigned int size) {}
static void sceKernelDcacheWritebackInvalidateRange(void* p, unsigned int size) {}
static void sceGuTexFlush(void) {flushes++;}
static void sceGuClutMode(int a,int b,int c,int d) {}
static void sceGuClutLoad(int a,const void* p) {}
static void sceGuTexMode(unsigned int type,int a,int b,int swizzle) {mode=type; modeCalls++;}
static void sceGuTexImage(int level,int w,int h,int stride,const void* p) {
 assert(w>0 && h>0); texWidth=w; texHeight=h; texAddress=p;
}
'''
        body = r'''
int main(void) {
 static uint8_t vram[65536] __attribute__((aligned(16)));
 static uint32_t water[64*64] __attribute__((aligned(16)));
 for(int i=0;i<64*64;i++) water[i]=0x7F191900;
 texman_reset(vram,sizeof(vram));
 unsigned int id=texman_create();
 /* This is the material path: select a new ID before uploading its pixels. */
 texman_bind_tex(id);
 assert(modeCalls==0);
 texman_upload_swizzle(64,64,GU_PSM_8888,water);
 assert(mode==GU_PSM_8888 && texWidth==64 && texHeight==64);
 assert(modeCalls==1 && flushes==1);
 assert(*(const uint32_t*)texAddress==0x7F191900);
 const void* firstAllocation=texAddress;
 /* Completed-frame reuse retains memory but refreshes GU texture cache. */
 water[0]=0x501B1B00;
 texman_bind_tex(id);
 texman_upload_swizzle(64,64,GU_PSM_8888,water);
 assert(texAddress==firstAllocation && *(const uint32_t*)texAddress==0x501B1B00);
 assert(modeCalls==2 && flushes==2);
 /* Plain uploads must also replace a previously bound format. */
 texman_upload(8,8,GU_PSM_4444,water);
 assert(mode==GU_PSM_4444 && texWidth==8 && texHeight==8 && modeCalls==3);
 assert(flushes==3);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.c'
            path.write_text(mock + source + body)
            executable = path.with_suffix('')
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-fsanitize=undefined',
                            '-I', str(GFX), str(path), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
