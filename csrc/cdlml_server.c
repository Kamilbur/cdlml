/*
 * cdlml_server.c — fallback library loader for systems without glibc dlmopen.
 *
 * Spawned as a subprocess by FallbackPreloadedCDLL. Loads user libraries
 * globally (RTLD_GLOBAL) so preloaded libs interpose symbols in the main lib.
 * Real libc is discovered at startup via dladdr on probe symbols (_exit,
 * getpid, clock_gettime) that LD_PRELOAD interposers almost never shadow. All
 * orig_*_ pointers are resolved from that handle, bypassing LD_PRELOAD.
 *
 * Usage: cdlml_server [rpc_in_fd rpc_out_fd]
 *   With no args: RPC over stdin/stdout.
 *   With args: RPC over the given file descriptors; stdout and stderr remain
 *   available for loaded library I/O and are forwarded by the parent process.
 *
 * Protocol: little-endian binary.
 *   Request:  [1 byte op] [op-specific payload]
 *   Response: [1 byte status: 0=ok 1=err] [payload]
 *
 * Ops:
 *   0x01 LOAD_LIB:  [u32 path_len][path bytes][u8 is_main]
 *                   -> ok:[]  err:[u32 len][msg]
 *   0x02 CALL_FUNC: [u32 name_len][name][u8 ret_type][u8 n_args]
 *                   [for each arg: u8 type, then value bytes]
 *                   -> ok:[value per ret_type]  err:[u32 len][msg]
 *   0x03 GET_VAR:   [u32 name_len][name bytes]
 *                   -> ok:[u64 addr]  err:[u32 len][msg]
 *   0x04 SHUTDOWN:  (no payload, no response, process exits)
 *
 * Type codes (ret_type / arg type):
 *   0x00 VOID  — no bytes
 *   0x01 I32   — 4 bytes signed
 *   0x02 I64   — 8 bytes signed
 *   0x03 U32   — 4 bytes unsigned
 *   0x04 U64   — 8 bytes unsigned
 *   0x05 F64   — 8 bytes (raw double bits);
 *   0x06 PTR   — 8 bytes (pointer as u64)
 *   0x07 CSTR  — [u32 len][bytes] for args; u64 addr for return
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* ---- Pre-captured libc/libdl function pointers ---- */
static ssize_t (*orig_write_)(int, const void *, size_t);
static ssize_t (*orig_read_)(int, void *, size_t);
static void    (*orig_exit_)(int);
static void   *(*orig_malloc_)(size_t);
static void    (*orig_free_)(void *);
static void   *(*orig_dlopen_)(const char *, int);
static void   *(*orig_dlsym_)(void *, const char *);
static char   *(*orig_dlerror_)(void);

/* Find the real libc by probing symbols that LD_PRELOAD interposers almost
 * never shadow. All probes must resolve to the same library; if they
 * disagree, returns NULL and init_ptrs falls back to RTLD_DEFAULT. */
static void *find_libc_handle(void) {
    static const char * const probes[] = {
        "_exit", "getpid", "clock_gettime", NULL
    };
    const char *found = NULL;

    for (int i = 0; probes[i] != NULL; i++) {
        void *addr = dlsym(RTLD_DEFAULT, probes[i]);
        if (!addr) continue;

        Dl_info info;
        if (!dladdr(addr, &info) || !info.dli_fname || info.dli_fname[0] == '\0')
            continue;

        if (!found) {
            found = info.dli_fname;
            continue;
        }
        if (strcmp(found, info.dli_fname) != 0)
            return NULL;
    }

    return found ? dlopen(found, RTLD_NOLOAD | RTLD_LOCAL) : NULL;
}

/* Resolve symbol from libc handle first; fall back to RTLD_DEFAULT.
 * Fallback handles dlopen/dlsym/dlerror on pre-2.34 glibc where they
 * live in libdl.so.2, not in libc. */
static void *libc_sym(void *libc, const char *name) {
    void *sym = libc ? dlsym(libc, name) : NULL;
    return sym ? sym : dlsym(RTLD_DEFAULT, name);
}

static void init_ptrs(void) {
    void *libc = find_libc_handle();

    orig_write_   = (ssize_t (*)(int, const void *, size_t))   libc_sym(libc, "write");
    orig_read_    = (ssize_t (*)(int, void *, size_t))         libc_sym(libc, "read");
    orig_exit_    = (void (*)(int))                            libc_sym(libc, "exit");
    orig_malloc_  = (void *(*)(size_t))                        libc_sym(libc, "malloc");
    orig_free_    = (void (*)(void *))                         libc_sym(libc, "free");
    orig_dlopen_  = (void *(*)(const char *, int))             libc_sym(libc, "dlopen");
    orig_dlsym_   = (void *(*)(void *, const char *))          libc_sym(libc, "dlsym");
    orig_dlerror_ = (char *(*)(void))                         libc_sym(libc, "dlerror");

    if (libc) dlclose(libc);
}

/* ---- IO helpers (use only orig_*_ pointers) ---- */

static size_t srv_strlen(const char *s) {
    size_t n = 0;
    while (s[n]) n++;
    return n;
}

static int read_exact(int fd, void *buf, size_t n) {
    size_t got = 0;
    unsigned char *p = (unsigned char *)buf;
    while (got < n) {
        ssize_t r = orig_read_(fd, p + got, n - got);
        if (r == -1 && errno == EINTR) continue;
        if (r <= 0) return -1;
        got += (size_t)r;
    }
    return 0;
}

static int write_exact(int fd, const void *buf, size_t n) {
    size_t sent = 0;
    const unsigned char *p = (const unsigned char *)buf;
    while (sent < n) {
        ssize_t w = orig_write_(fd, p + sent, n - sent);
        if (w == -1 && errno == EINTR) continue;
        if (w <= 0) return -1;
        sent += (size_t)w;
    }
    return 0;
}

static int read_u32(int fd, uint32_t *out) {
    unsigned char b[4];
    if (read_exact(fd, b, 4) != 0) return -1;
    *out = (uint32_t)b[0]
         | ((uint32_t)b[1] << 8)
         | ((uint32_t)b[2] << 16)
         | ((uint32_t)b[3] << 24);
    return 0;
}

static int write_u32(int fd, uint32_t v) {
    unsigned char b[4] = {
        (unsigned char)(v & 0xFF),
        (unsigned char)((v >> 8) & 0xFF),
        (unsigned char)((v >> 16) & 0xFF),
        (unsigned char)((v >> 24) & 0xFF),
    };
    return write_exact(fd, b, 4);
}

static int read_u64(int fd, uint64_t *out) {
    unsigned char b[8];
    if (read_exact(fd, b, 8) != 0) return -1;
    *out = (uint64_t)b[0]
         | ((uint64_t)b[1] << 8)
         | ((uint64_t)b[2] << 16)
         | ((uint64_t)b[3] << 24)
         | ((uint64_t)b[4] << 32)
         | ((uint64_t)b[5] << 40)
         | ((uint64_t)b[6] << 48)
         | ((uint64_t)b[7] << 56);
    return 0;
}

static int write_u64(int fd, uint64_t v) {
    unsigned char b[8];
    for (int i = 0; i < 8; i++) {
        b[i] = (unsigned char)(v & 0xFF);
        v >>= 8;
    }
    return write_exact(fd, b, 8);
}

static void send_ok(int fd) {
    unsigned char b = 0;
    write_exact(fd, &b, 1);
}

static void send_ok_u64(int fd, uint64_t v) {
    send_ok(fd);
    write_u64(fd, v);
}

static void send_err(int fd, const char *msg) {
    unsigned char b = 1;
    write_exact(fd, &b, 1);
    uint32_t len = (uint32_t)srv_strlen(msg);
    write_u32(fd, len);
    write_exact(fd, msg, len);
}

/* ---- Library handle tracking ---- */
#define MAX_LIBS 64
static void *lib_handles[MAX_LIBS];
static int   n_libs = 0;
static void *main_handle = NULL;

/* ---- Op constants ---- */
#define OP_LOAD_LIB  0x01
#define OP_CALL_FUNC 0x02
#define OP_GET_VAR   0x03
#define OP_SHUTDOWN  0x04

#define TYPE_VOID 0x00
#define TYPE_I32  0x01
#define TYPE_I64  0x02
#define TYPE_U32  0x03
#define TYPE_U64  0x04
#define TYPE_F64  0x05
#define TYPE_PTR  0x06
#define TYPE_CSTR 0x07

/* ---- Function call trampolines ----
 * Only integer/pointer args supported (x86-64 integer registers). */
typedef uint64_t (*fn0_t)(void);
typedef uint64_t (*fn1_t)(uint64_t);
typedef uint64_t (*fn2_t)(uint64_t, uint64_t);
typedef uint64_t (*fn3_t)(uint64_t, uint64_t, uint64_t);
typedef uint64_t (*fn4_t)(uint64_t, uint64_t, uint64_t, uint64_t);
typedef uint64_t (*fn5_t)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
typedef uint64_t (*fn6_t)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

static uint64_t dispatch_call(void *fn, int nargs, uint64_t *args) {
    switch (nargs) {
    case 0: return ((fn0_t)fn)();
    case 1: return ((fn1_t)fn)(args[0]);
    case 2: return ((fn2_t)fn)(args[0], args[1]);
    case 3: return ((fn3_t)fn)(args[0], args[1], args[2]);
    case 4: return ((fn4_t)fn)(args[0], args[1], args[2], args[3]);
    case 5: return ((fn5_t)fn)(args[0], args[1], args[2], args[3], args[4]);
    case 6: return ((fn6_t)fn)(args[0], args[1], args[2], args[3], args[4], args[5]);
    default: return 0;
    }
}

#define MAX_STR_ARGS 8
static char *str_arg_bufs[MAX_STR_ARGS];
static int   n_str_args = 0;

static void free_str_args(void) {
    for (int i = 0; i < n_str_args; i++) {
        orig_free_(str_arg_bufs[i]);
        str_arg_bufs[i] = 0;
    }
    n_str_args = 0;
}

/* ---- Op handlers ---- */

static void handle_load_lib(int in_fd, int out_fd) {
    uint32_t path_len;
    uint8_t is_main;

    if (read_u32(in_fd, &path_len) != 0) orig_exit_(1);

    char *path = (char *)orig_malloc_(path_len + 1);
    if (!path) { send_err(out_fd, "malloc failed"); return; }

    if (read_exact(in_fd, path, path_len) != 0) orig_exit_(1);
    path[path_len] = '\0';

    if (read_exact(in_fd, &is_main, 1) != 0) orig_exit_(1);

    void *h = orig_dlopen_(path, RTLD_NOW | RTLD_GLOBAL);
    orig_free_(path);

    if (!h) {
        char *err = orig_dlerror_();
        send_err(out_fd, err ? err : "dlopen failed");
        return;
    }

    if (is_main) {
        main_handle = h;
    } else {
        if (n_libs < MAX_LIBS)
            lib_handles[n_libs++] = h;
    }
    send_ok(out_fd);
}

static void handle_call_func(int in_fd, int out_fd) {
    uint32_t name_len;
    uint8_t ret_type, nargs_byte;

    if (read_u32(in_fd, &name_len) != 0) orig_exit_(1);

    char *name = (char *)orig_malloc_(name_len + 1);
    if (!name) { send_err(out_fd, "malloc failed"); return; }

    if (read_exact(in_fd, name, name_len) != 0) orig_exit_(1);
    name[name_len] = '\0';

    if (read_exact(in_fd, &ret_type, 1) != 0) orig_exit_(1);
    if (read_exact(in_fd, &nargs_byte, 1) != 0) orig_exit_(1);

    int nargs = (int)nargs_byte;
    if (nargs > 6) nargs = 6;

    uint64_t args[6];
    n_str_args = 0;

    for (int i = 0; i < nargs; i++) {
        uint8_t type;
        if (read_exact(in_fd, &type, 1) != 0) orig_exit_(1);

        switch (type) {
        case TYPE_I32:
        case TYPE_U32: {
            uint32_t v;
            if (read_u32(in_fd, &v) != 0) orig_exit_(1);
            args[i] = (uint64_t)v;
            break;
        }
        case TYPE_I64:
        case TYPE_U64:
        case TYPE_PTR:
        case TYPE_F64: {
            if (read_u64(in_fd, &args[i]) != 0) orig_exit_(1);
            break;
        }
        case TYPE_CSTR: {
            uint32_t slen;
            if (read_u32(in_fd, &slen) != 0) orig_exit_(1);
            char *s = (char *)orig_malloc_(slen + 1);
            if (!s) {
                send_err(out_fd, "malloc failed");
                orig_free_(name);
                free_str_args();
                return;
            }
            if (read_exact(in_fd, s, slen) != 0) orig_exit_(1);
            s[slen] = '\0';
            if (n_str_args < MAX_STR_ARGS)
                str_arg_bufs[n_str_args++] = s;
            args[i] = (uint64_t)(uintptr_t)s;
            break;
        }
        default:
            args[i] = 0;
            break;
        }
    }

    void *sym = orig_dlsym_(RTLD_DEFAULT, name);
    orig_free_(name);

    if (!sym) {
        free_str_args();
        char *err = orig_dlerror_();
        send_err(out_fd, err ? err : "symbol not found");
        return;
    }

    uint64_t result = dispatch_call(sym, nargs, args);
    free_str_args();

    send_ok(out_fd);

    switch (ret_type) {
    case TYPE_VOID:
        break;
    case TYPE_I32:
    case TYPE_U32:
        write_u32(out_fd, (uint32_t)result);
        break;
    case TYPE_I64:
    case TYPE_U64:
    case TYPE_PTR:
    case TYPE_F64:
    case TYPE_CSTR:
        write_u64(out_fd, result);
        break;
    default:
        break;
    }
}

static void handle_get_var(int in_fd, int out_fd) {
    uint32_t name_len;
    if (read_u32(in_fd, &name_len) != 0) orig_exit_(1);

    char *name = (char *)orig_malloc_(name_len + 1);
    if (!name) { send_err(out_fd, "malloc failed"); return; }

    if (read_exact(in_fd, name, name_len) != 0) orig_exit_(1);
    name[name_len] = '\0';

    void *sym = orig_dlsym_(RTLD_DEFAULT, name);
    orig_free_(name);

    if (!sym) {
        char *err = orig_dlerror_();
        send_err(out_fd, err ? err : "symbol not found");
        return;
    }

    send_ok_u64(out_fd, (uint64_t)(uintptr_t)sym);
}

static void main_loop(int in_fd, int out_fd) {
    uint8_t op;
    while (read_exact(in_fd, &op, 1) == 0) {
        switch (op) {
        case OP_LOAD_LIB:
            handle_load_lib(in_fd, out_fd);
            break;
        case OP_CALL_FUNC:
            handle_call_func(in_fd, out_fd);
            break;
        case OP_GET_VAR:
            handle_get_var(in_fd, out_fd);
            break;
        case OP_SHUTDOWN:
            orig_exit_(0);
            break;
        default:
            orig_exit_(1);
            break;
        }
    }
    orig_exit_(0);
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    init_ptrs();

    int in_fd  = STDIN_FILENO;
    int out_fd = STDOUT_FILENO;

    if (argc >= 3) {
        in_fd  = atoi(argv[1]);
        out_fd = atoi(argv[2]);
    }

    main_loop(in_fd, out_fd);
    return 0;
}
