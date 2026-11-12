#include "mm_psp_path.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static size_t MmPsp_DevicePrefixLength(const char* path) {
    const char* colon = strchr(path, ':');
    const char* slash = strpbrk(path, "/\\");

    return colon != NULL && (slash == NULL || colon < slash) ? (size_t)(colon - path) + 1 : 0;
}

int MmPsp_BuildExecutablePath(const char* argv0, char* output, size_t capacity) {
    char cwd[256];
    size_t deviceLength;
    int written;

    if (output == NULL || capacity == 0) {
        return 0;
    }
    output[0] = '\0';
    if (argv0 == NULL || argv0[0] == '\0') {
        argv0 = "EBOOT.PBP";
    }
    deviceLength = MmPsp_DevicePrefixLength(argv0);
    if (deviceLength != 0) {
        /* Preserve ef0: (Go internal storage), ms0: (Memory Stick), and
         * explicit debugger devices such as host0:. Never guess a device. */
        if (argv0[deviceLength] != '/' && argv0[deviceLength] != '\\') {
            return 0;
        }
        written = snprintf(output, capacity, "%s", argv0);
    } else {
        size_t cwdLength;

        if (getcwd(cwd, sizeof(cwd)) == NULL || cwd[0] == '\0') {
            return 0;
        }
        cwdLength = strlen(cwd);
        if (argv0[0] == '/' || argv0[0] == '\\') {
            /* A root-relative launcher path still needs the active drive. */
            written = snprintf(output, capacity, "%.*s%s", (int)MmPsp_DevicePrefixLength(cwd), cwd, argv0);
        } else {
            const char* slash = strrchr(argv0, '/');
            const char* backslash = strrchr(argv0, '\\');
            const char* basename;

            if (backslash != NULL && (slash == NULL || backslash > slash)) {
                slash = backslash;
            }
            basename = slash != NULL ? slash + 1 : argv0;
            /* PSPSDK's CRT already changes cwd to argv0's directory. Joining
             * that relative directory a second time would duplicate it. */
            written = snprintf(output, capacity, "%s%s%s", cwd,
                               cwd[cwdLength - 1] == '/' || cwd[cwdLength - 1] == '\\' ? "" : "/", basename);
        }
    }
    if (written <= 0 || (size_t)written >= capacity) {
        output[0] = '\0';
        return 0;
    }
    for (size_t i = 0; output[i] != '\0'; i++) {
        if (output[i] == '\\') {
            output[i] = '/';
        }
    }
    if (output[written - 1] == '/') {
        output[0] = '\0';
        return 0;
    }
    return 1;
}
