#ifndef MM_PSP_PATH_H
#define MM_PSP_PATH_H

#include <stddef.h>

/* Resolve the launch device before any EBOOT-relative storage is opened. */
int MmPsp_BuildExecutablePath(const char* argv0, char* output, size_t capacity);

#endif
