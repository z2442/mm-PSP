"""Exercise PSP Go/Memory Stick launch paths through the real storage consumers."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / 'src/port/psp'
BACKEND = PORT / 'backend'


def function(source, name):
    start = re.search(r'^(?:static )?[^\n]*\b' + name + r'\([^;]*?\)\s*\{', source, re.M).start()
    return source[start:source.index('\n}', source.index('{', start)) + 2] + '\n'


loader = (BACKEND / 'oot_psp_asset_loader.c').read_text()
builder = (PORT / 'mm_psp_asset_builder.c').read_text()
preamble = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
typedef int s32;
typedef int SceUID;
static const char* cwd;
static char* storage_getcwd(char* output, size_t capacity) {
    if (cwd == NULL || strlen(cwd) >= capacity) return NULL;
    strcpy(output, cwd); return output;
}
#define getcwd storage_getcwd
#include "mm_psp_path.c"
#undef getcwd
static char sOotPspAssetRoot[256];
static s32 sOotPspPackedAssetUnavailable;
static unsigned ensures, opens, builds, mkdirs;
static bool packExists, fallbackRom;
static const char* expectedRoot;
static void expect(const char* path, const char* suffix) {
    char expected[384]; snprintf(expected,sizeof(expected),"%s%s",expectedRoot,suffix);
    assert(strcmp(path,expected)==0);
}
const char* OotPsp_ResolveRootPath(const char*,char*,size_t);
s32 OotPspAssetBuilder_Ensure(void);
static void OotPsp_ClosePackedAssetFile(void) {}
static void OotPsp_ClearPackedAssetCache(void) {}
static void OotPsp_InitAssetSema(void) {}
static void OotPsp_PreloadPersistentAssets(void) {}
static void OotPsp_InitPackedAssetCache(void) {}
#define MM_PSP_ROM_INDEPENDENT 1
#define PSP_O_RDONLY 1
static const size_t gOotPspExternalAssetCount=1;
static const struct { uintptr_t vromStart,vromEnd,fileOffset; } gOotPspExternalAssets[]={{0,32,0}};
static unsigned sOotPspAssetBuilderProgress;
static s32 sOotPspAssetBuilderErrorShown;
static int sceIoOpen(const char* path,int flags,int mode) {
    (void)mode;assert(flags==PSP_O_RDONLY);opens++;
    if (fallbackRom && opens==1) { expect(path,"data/basrom.z64");return -1; }
    expect(path,fallbackRom ? "data/baserom.z64" : "data/basrom.z64");return 7;
}
static void sceIoClose(int fd) { assert(fd==7); }
static void sceIoMkdir(const char* path,int mode) {
    assert(mode==0777);expect(path,mkdirs++ ? "data/segments" : "data");
}
static void sceKernelDelayThread(unsigned delay) { (void)delay; }
static bool OotPspAssetBuilder_FileHasSize(const char* path,size_t size) {
    expect(path,"data/segments/oot_psp_assets.bin");assert(size==32);ensures++;return packExists;
}
static bool OotPspAssetBuilder_ValidateRom(int fd) { assert(fd==7);return true; }
static bool OotPspAssetBuilder_Build(int fd,const char* output,const char* temp) {
    assert(fd==7);expect(output,"data/segments/oot_psp_assets.bin");
    expect(temp,"data/segments/oot_psp_assets.tmp");builds++;return true;
}
static void OotPspAssetBuilder_ShowProgress(unsigned progress,const char* status) {
    assert(progress<=1000 && status!=NULL);sOotPspAssetBuilderProgress=progress;
}
static void OotPspAssetBuilder_ShowError(const char* status) { (void)status;sOotPspAssetBuilderErrorShown=true; }
#define OOT_PSP_CONTROLS_INI_PATH "controls.ini"
#define OOT_PSP_VIDEO_INI_PATH "video.ini"
#define OOT_PSP_DVE_MODULE_PATH "Plugins/dvemgr.prx"
#define MM_PSP_SAVE_PATH "mm-psp-save.bin"
static char sOotPspVideoPath[384];
'''
constants = '\n'.join(re.findall(r'^#define OOT_PSP_(?:INPUT_ROM(?:_FALLBACK)?|PACKED_ASSET(?:_TEMP)?)_PATH[^\n]+', builder, re.M)) + '\n'
code = preamble + constants
for name in ('OotPsp_IsAbsolutePath', 'OotPsp_ResolveRootPath'):
    code += function(loader, name)
code += function(builder, 'OotPspAssetBuilder_OpenRom')
code += function(builder, 'OotPspAssetBuilder_Ensure')
code += function(loader, 'OotPsp_AssetInit')
code += function((BACKEND / 'oot_psp_controls.c').read_text(), 'OotPspControls_Path')
code += function((BACKEND / 'oot_psp_video.c').read_text(), 'OotPspVideo_BuildPath')
code += function((BACKEND / 'oot_psp_dve.c').read_text(), 'OotPspDve_BuildModulePath')
code += function((PORT / 'mm_psp_game.c').read_text(), 'MmPsp_GetSavePath')
code += r'''
static void check_launch(const char* argv0,const char* working,const char* expected) {
    char path[256];cwd=working;
    assert(MmPsp_BuildExecutablePath(argv0,path,sizeof(path)));
    assert(strcmp(path,expected)==0);
}
static void check_storage(const char* drive) {
    char root[128],argv0[256],launch[256],buffer[384],module[512];
    snprintf(root,sizeof(root),"%s:/PSP/GAME/MM_PSP/",drive);
    snprintf(argv0,sizeof(argv0),"%sEBOOT.PBP",root);expectedRoot=root;
    cwd=root;
    assert(MmPsp_BuildExecutablePath("EBOOT.PBP",launch,sizeof(launch)));
    assert(strcmp(argv0,launch)==0);
    for (unsigned mode=0;mode<3;mode++) {
        packExists=mode==2;fallbackRom=mode==1;ensures=opens=builds=mkdirs=0;
        assert(OotPsp_AssetInit(launch));
        assert(ensures==1 && opens==(mode==2 ? 0 : mode==1 ? 2 : 1));
        assert(builds==(mode!=2) && mkdirs==(mode==2 ? 0 : 2));
    }
    // All later I/O remains on the launch device even if a plugin changes cwd.
    cwd=strcmp(drive,"ef0")==0 ? "ms0:/" : "ef0:/";
    expect(MmPsp_GetSavePath(buffer,sizeof(buffer)),"mm-psp-save.bin");
    expect(OotPspControls_Path(buffer,sizeof(buffer)),"controls.ini");
    OotPspVideo_BuildPath(launch);expect(sOotPspVideoPath,"video.ini");
    assert(OotPspDve_BuildModulePath(launch,module,sizeof(module)));
    expect(module,"Plugins/dvemgr.prx");
    expect(OotPsp_ResolveRootPath("data/segments/oot_psp_suspend.bin",buffer,sizeof(buffer)),"data/segments/oot_psp_suspend.bin");
    expect(OotPsp_ResolveRootPath("data/segments/oot_psp_assets.bin",buffer,sizeof(buffer)),"data/segments/oot_psp_assets.bin");
    assert(strcmp(OotPsp_ResolveRootPath("flash0:/font/ltn0.pgf",buffer,sizeof(buffer)),"flash0:/font/ltn0.pgf")==0);
}
int main(void) {
    check_launch("ef0:/PSP/GAME/MM_PSP/EBOOT.PBP","ms0:/","ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("ef0:\\PSP\\GAME\\MM_PSP\\EBOOT.PBP",NULL,"ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("host0:/build/mm.prx","ef0:/","host0:/build/mm.prx");
    check_launch("EBOOT.PBP","ef0:/PSP/GAME/MM_PSP","ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("PSP/GAME/MM_PSP/EBOOT.PBP","ef0:/PSP/GAME/MM_PSP/","ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("./mm.prx","ef0:/PSP/GAME/MM_PSP/","ef0:/PSP/GAME/MM_PSP/mm.prx");
    check_launch(NULL,"ef0:/PSP/GAME/MM_PSP/","ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("","ef0:/PSP/GAME/MM_PSP/","ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("/PSP/GAME/MM_PSP/EBOOT.PBP","ef0:/","ef0:/PSP/GAME/MM_PSP/EBOOT.PBP");
    check_launch("/tmp/mm/EBOOT.PBP","/tmp/mm/","/tmp/mm/EBOOT.PBP");
    check_launch("EBOOT.PBP","ef0:/PSP/GAME/MM internal/","ef0:/PSP/GAME/MM internal/EBOOT.PBP");
    check_storage("ef0");check_storage("ms0");
    char buffer[256],longPath[512];
    cwd=NULL;assert(!MmPsp_BuildExecutablePath("EBOOT.PBP",buffer,sizeof(buffer)) && buffer[0]==0);
    cwd="";assert(!MmPsp_BuildExecutablePath(NULL,buffer,sizeof(buffer)));
    cwd="ef0:/";assert(!MmPsp_BuildExecutablePath("ms0:EBOOT.PBP",buffer,sizeof(buffer)));
    assert(!MmPsp_BuildExecutablePath("ef0:/PSP/GAME/MM_PSP/",buffer,sizeof(buffer)));
    assert(!MmPsp_BuildExecutablePath("ef0:/EBOOT.PBP",buffer,4) && buffer[0]==0);
    assert(!MmPsp_BuildExecutablePath("ef0:/EBOOT.PBP",NULL,0));
    memset(longPath,'x',sizeof(longPath));memcpy(longPath,"ef0:/",5);
    memcpy(longPath+sizeof(longPath)-11,"/EBOOT.PBP",11);
    assert(!OotPsp_AssetInit(longPath) && sOotPspAssetRoot[0]==0);
    puts("Storage paths: Go ef0, Memory Stick ms0, launch-directory fallback, first-boot/cache, saves, settings, plugins and resume paths passed");
}
'''
with tempfile.TemporaryDirectory(prefix='mm-storage-paths-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(code)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(PORT), str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
