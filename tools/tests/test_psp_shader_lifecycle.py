#!/usr/bin/env python3
"""Compare cold/hot shader lookup using the actual frontend and GU shader cache.

Cache construction must leave pending geometry, the frontend's active-program
pointer and live GU state alone. Only the pipeline's explicit shader switch may
submit old geometry and load the next shader.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
GFX = ROOT / "src/port/psp/backend/gfx"
frontend = (GFX / "gfx_fast3d.c").read_text()
backend = (GFX / "gfx_scegu.c").read_text()


def function(source, name):
    start = re.search(r"^static [^\n]*\b" + name + r"\([^;]*?\)\s*\{", source, re.M).start()
    return source[start:source.index("\n}", source.index("{", start)) + 2] + "\n"


start = backend.index("enum MixType {")
declarations = backend[start:backend.index("struct SamplerState {", start)]
start = frontend.index("    if (backend_state_dirty || prg != rendering_state.shader_program)")
switch = frontend[start:frontend.index("    if (backend_state_dirty || alpha_blend", start)]
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include "gfx_cc.h"
''' + declarations + r'''
static struct ShaderProgram shader_program_cache[SHADER_PROGRAM_CACHE_CAPACITY];
static uint16_t shader_program_cache_count;
static struct ShaderProgram *cur_shader,*sAppliedShader;
static struct { struct ShaderProgram* shader_program; } rendering_state;
static unsigned gpuShader,gpuChanges,pending,drawnShader,flushes;
static void gfx_scegu_apply_shader(struct ShaderProgram* shader) {
    assert(shader);gpuShader=shader->shader_id;gpuChanges++;
    sAppliedShader=shader;shader->enabled=true;
}
static void sceIoWrite(int fd,const void* data,size_t size) { (void)fd;(void)data;(void)size;abort(); }
static void gfx_flush(void) {
    flushes++;
    if (pending) { assert(cur_shader && gpuShader==cur_shader->shader_id);drawnShader=gpuShader;pending=0; }
}
'''
for name in ("gfx_scegu_probe_shader_cache", "gfx_scegu_lookup_shader", "gfx_scegu_unload_shader",
             "gfx_scegu_load_shader", "gfx_scegu_create_shader"):
    code += function(backend, name)
code += r'''
static struct {
    struct ShaderProgram* (*lookup_shader)(uint32_t);
    struct ShaderProgram* (*create_shader)(uint32_t);
    void (*unload_shader)(struct ShaderProgram*);
    void (*load_shader)(struct ShaderProgram*);
} api={gfx_scegu_lookup_shader,gfx_scegu_create_shader,gfx_scegu_unload_shader,gfx_scegu_load_shader},*gfx_rapi=&api;
'''
code += function(frontend, "gfx_lookup_or_create_shader_program")
code += "static void prepare(struct ShaderProgram* prg,bool backend_state_dirty) {\n" + switch + "}\n"
code += r'''
int main(void) {
    struct ShaderProgram old={.shader_id=0x100,.cache_valid=true};
    for (unsigned i=1;i<=96;i++) {
        gfx_scegu_load_shader(&old);rendering_state.shader_program=&old;
        pending=3;drawnShader=0;flushes=0;
        unsigned before=gpuChanges;
        uint32_t id=i | (i&1 ? SHADER_OPT_ALPHA : SHADER_OPT_FOG);
        struct ShaderProgram* next=gfx_lookup_or_create_shader_program(id);
        /* This must be identical whether this material's shader was compiled
         * on a previous frame or is being constructed for the first time. */
        assert(next && next->shader_id==id && next->cache_valid);
        assert(pending==3 && drawnShader==0 && flushes==0);
        assert(gpuShader==old.shader_id && gpuChanges==before);
        assert(cur_shader==&old && rendering_state.shader_program==&old);
        assert(gfx_lookup_or_create_shader_program(id)==next);
        assert(gfx_scegu_create_shader(id)==next);
        assert(pending==3 && gpuChanges==before && flushes==0);
        prepare(next,false);
        assert(drawnShader==old.shader_id && pending==0 && gpuShader==id);
        assert(cur_shader==next && rendering_state.shader_program==next);
        before=gpuChanges;prepare(next,false);assert(gpuChanges==before);
    }
    /* Startup precompilation also builds cache entries without selecting an
     * arbitrary active material before the first game display list. */
    gfx_scegu_unload_shader(NULL);rendering_state.shader_program=NULL;
    pending=0;flushes=0;unsigned before=gpuChanges;
    struct ShaderProgram* first=gfx_lookup_or_create_shader_program(0x7123456);
    assert(cur_shader==NULL && rendering_state.shader_program==NULL && gpuChanges==before && flushes==0);
    prepare(first,true);assert(cur_shader==first && rendering_state.shader_program==first);
    assert(shader_program_cache_count==97);
    puts("Shader lifecycle: 96 cold/hot lookups preserve active state; real pipeline switches flush before load; startup remains neutral");
}
'''
with tempfile.TemporaryDirectory(prefix="mm-shader-lifecycle-") as directory:
    path = Path(directory)
    (path / "test.c").write_text(code)
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=undefined", "-I", str(GFX), str(path / "test.c"),
                    str(GFX / "gfx_cc.c"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
