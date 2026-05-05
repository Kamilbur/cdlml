#define _GNU_SOURCE
#include <dlfcn.h>
#include <stddef.h>
#include <unistd.h>
#include <string.h>
#include <pthread.h>

static void *(*real_malloc)(size_t) = NULL;
static void (*real_free)(void*) = NULL;
static void *(*real_calloc)(size_t,size_t) = NULL;
static void *(*real_realloc)(void*, size_t) = NULL;

static pthread_once_t init_once = PTHREAD_ONCE_INIT;
static __thread int in_hook = 0;


#define WITH_VAR_SET(var, val, code_block) \
    do { \
        (var) = val; \
        code_block; \
        (var) = 0; \
    } while(0)

#define WITH_HOOK(code_block) \
    WITH_VAR_SET(in_hook, 1, code_block)


int mapping_enabled = 1;

static void init_real(void) {
    real_malloc  = dlsym(RTLD_NEXT, "malloc");
    real_free    = dlsym(RTLD_NEXT, "free");
    real_calloc  = dlsym(RTLD_NEXT, "calloc");
    real_realloc = dlsym(RTLD_NEXT, "realloc");
}

char *
my_itoa(size_t val)
{
    static char buffer[20];
    size_t i = 0;
    if (val == 0) {
        return "0";
    }
    if (val < 0) {
        val = -val;
        buffer[i++] = '-';
    }
    char *start = buffer + i;

    while (val > 0) {
        buffer[i++] = (val % 10) + '0';
        val /= 10;
    }
    char *end = buffer + i - 1;
    buffer[i] = '\0';

    while (start < end) {
        char tmp = *start;
        *start++ = *end;
        *end-- = tmp;
    }

    return buffer;
}

size_t
my_strlen(const char *str)
{
    size_t len = 0;
    while (str[len] != '\0') {
        len++;
    }
    return len;
}

static void safe_log(const char* msg) {
    /*
     *  Never call fprintf/printf here (they may malloc)!
     */
    if (!msg) return;
    write(2, msg, my_strlen(msg));
}

void* malloc(size_t size) {
    void *p = NULL;
    pthread_once(&init_once, init_real);
    if (!real_malloc) return NULL;

    if (mapping_enabled == 0) {
        WITH_HOOK(p = real_malloc(size));
        return p;
    }
    if (in_hook) return real_malloc(size);

    char *size_str = my_itoa(size);
    safe_log("[interpose] malloc(size=");
    safe_log(size_str);
    safe_log(")\n");

    WITH_HOOK(p = real_malloc(size));
    return p;
}

void free(void* ptr) {
    pthread_once(&init_once, init_real);
    if (!real_free) return;
    if (mapping_enabled == 0) {
        real_free(ptr);
        return;
    }
    if (in_hook) { real_free(ptr); return; }

    WITH_HOOK(real_free(ptr));
}

void* calloc(size_t n, size_t sz) {
    void *p = NULL;

    pthread_once(&init_once, init_real);
    if (!real_calloc) return NULL;
    if (mapping_enabled == 0) {
        return real_calloc(n, sz);
    }
    if (in_hook) return real_calloc(n, sz);

    WITH_HOOK(p = real_calloc(n, sz));
    return p;
}

void* realloc(void* ptr, size_t sz) {
    void *p = NULL;

    pthread_once(&init_once, init_real);
    if (!real_realloc) return NULL;
    if (mapping_enabled == 0) {
        return real_realloc(ptr, sz);
    }
    if (in_hook) return real_realloc(ptr, sz);

    WITH_HOOK(p = real_realloc(ptr, sz));
    return p;
}

