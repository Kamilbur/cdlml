#ifndef CDLML_H
#define CDLML_H

#ifndef _GNU_SOURCE
# define _GNU_SOURCE
#endif // _GNU_SOURCE
#include <dlfcn.h>
#include <stddef.h>

void cdlml_reset(void);

void *cdlml_open(const char *filename);

int cdlml_is_supported(void);

#endif // CDLML_H
