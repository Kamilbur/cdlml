#include "cdlml.h"

#ifdef __linux__
# if defined(__GLIBC__)

static Lmid_t _namespace = LM_ID_NEWLM;

int
cdlml_is_supported(void)
{
    return 1;
}

void
cdlml_reset(void)
{
    _namespace = LM_ID_NEWLM;
}

static inline void *
cdlml_open_init(const char *filename)
{
    void *handle = dlmopen(_namespace, filename, RTLD_NOW);
    if (!handle) {
        return NULL;
    }
    if (dlinfo(handle, RTLD_DI_LMID, &_namespace) != 0) {
        cdlml_reset();
        dlclose(handle);
        return NULL;
    }
    return handle;
}

static inline void *
cdlml_open_next(const char *filename)
{
    return dlmopen(_namespace, filename, RTLD_NOW);
}

void *
cdlml_open(const char *filename)
{
    if (_namespace == LM_ID_NEWLM) {
        return cdlml_open_init(filename);
    }
    else {
        return cdlml_open_next(filename);
    }
}
# endif // __GLIBC__
#endif // __linux__

#if !defined(__linux__) || !defined(__GLIBC__)
int
cdlml_is_supported(void)
{
    return 0;
}

void
cdlml_reset(void)
{
}

void *
cdlml_open(const char *filename)
{
    (void)filename;
    return NULL;
}
#endif
