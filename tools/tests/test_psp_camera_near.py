"""Keep normal MM cutscene depth precision while allowing foreground aiming."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/code/z_play.c').read_text()
start = source.index('static f32 Play_GetPspPerspectiveNear(')
function = source[start:source.index('\n}', start) + 2]
code = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
typedef float f32;
enum { CS_STATE_IDLE,CS_STATE_RUNNING };
enum { CAM_MODE_NORMAL,CAM_MODE_FIRSTPERSON,CAM_MODE_BOWARROW,CAM_MODE_SLINGSHOT,CAM_MODE_BOWARROWZ,CAM_MODE_DEKUSHOOT };
typedef struct { int mode; } Camera;
typedef struct { Camera* camera;struct { float zNear; } view;struct { int state; } csCtx; } PlayState;
#define GET_ACTIVE_CAM(play) ((play)->camera)
'''
code += function + r'''
int main(void) {
    Camera camera={CAM_MODE_NORMAL};
    PlayState play={.camera=&camera,.view={10},.csCtx={CS_STATE_IDLE}};
    assert(Play_GetPspPerspectiveNear(&play)==10);
    play.csCtx.state=CS_STATE_RUNNING;
    assert(Play_GetPspPerspectiveNear(&play)==10); // Intro trees/ground keep the native depth range.
    play.view.zNear=30;assert(Play_GetPspPerspectiveNear(&play)==30);
    play.camera=NULL;assert(Play_GetPspPerspectiveNear(&play)==30);
    play.camera=&camera;
    for (int mode=CAM_MODE_FIRSTPERSON;mode<=CAM_MODE_DEKUSHOOT;mode++) {
        camera.mode=mode;assert(Play_GetPspPerspectiveNear(&play)==1);
    }
    play.view.zNear=0.5f;assert(Play_GetPspPerspectiveNear(&play)==0.5f);
    puts("Camera near plane: normal/intro depth range, missing camera and foreground aiming passed");
}
'''
with tempfile.TemporaryDirectory(prefix='mm-camera-near-') as directory:
    path = Path(directory)
    (path/'test.c').write_text(code)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                    str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
