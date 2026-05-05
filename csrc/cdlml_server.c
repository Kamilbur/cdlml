/*
 * cdlml_server.c — fallback library loader for systems without glibc dlmopen.
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <ffi.h>
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
static void   *(*orig_memmove_)(void *, const void *, size_t);
static void   *(*orig_memset_)(void *, int, size_t);

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
    orig_memmove_ = (void *(*)(void *, const void *, size_t))  libc_sym(libc, "memmove");
    orig_memset_  = (void *(*)(void *, int, size_t))           libc_sym(libc, "memset");
    if (libc) dlclose(libc);
}

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
    *out = (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
    return 0;
}

static int write_u32(int fd, uint32_t v) {
    unsigned char b[4] = { (unsigned char)(v & 0xFF), (unsigned char)((v >> 8) & 0xFF), (unsigned char)((v >> 16) & 0xFF), (unsigned char)((v >> 24) & 0xFF) };
    return write_exact(fd, b, 4);
}

static int read_u64(int fd, uint64_t *out) {
    unsigned char b[8];
    if (read_exact(fd, b, 8) != 0) return -1;
    *out = (uint64_t)b[0] | ((uint64_t)b[1] << 8) | ((uint64_t)b[2] << 16) | ((uint64_t)b[3] << 24) |
           ((uint64_t)b[4] << 32) | ((uint64_t)b[5] << 40) | ((uint64_t)b[6] << 48) | ((uint64_t)b[7] << 56);
    return 0;
}

static int write_u64(int fd, uint64_t v) {
    unsigned char b[8];
    for (int i = 0; i < 8; i++) { b[i] = (unsigned char)(v & 0xFF); v >>= 8; }
    return write_exact(fd, b, 8);
}

static void send_ok(int fd) { unsigned char b = 0; write_exact(fd, &b, 1); }
static void send_ok_u64(int fd, uint64_t v) { send_ok(fd); write_u64(fd, v); }
static void send_err(int fd, const char *msg) {
    unsigned char b = 1; write_exact(fd, &b, 1);
    uint32_t len = (uint32_t)srv_strlen(msg);
    write_u32(fd, len); write_exact(fd, msg, len);
}

#define MAX_LIBS 64
static void *lib_handles[MAX_LIBS];
static int   n_libs = 0;
static void *main_handle = NULL;

#define OP_LOAD_LIB  0x01
#define OP_CALL_FUNC 0x02
#define OP_GET_VAR   0x03
#define OP_SHUTDOWN  0x04
#define OP_MEMMOVE   0x05
#define OP_MEMSET    0x06
#define OP_ALLOC     0x07
#define OP_FREE      0x08
#define OP_READ_MEM  0x09
#define OP_WRITE_MEM 0x0A

#define TYPE_VOID 0x00
#define TYPE_I32  0x01
#define TYPE_I64  0x02
#define TYPE_U32  0x03
#define TYPE_U64  0x04
#define TYPE_F64  0x05
#define TYPE_PTR  0x06
#define TYPE_CSTR 0x07
#define TYPE_F32  0x08

#define MAX_ARGS 32
union arg_storage { int32_t i32; uint32_t u32; int64_t i64; uint64_t u64; float f32; double f64; void *ptr; };
static ffi_type *type_code_to_ffi(uint8_t type) {
    switch (type) {
    case TYPE_I32:  return &ffi_type_sint32;
    case TYPE_U32:  return &ffi_type_uint32;
    case TYPE_I64:  return &ffi_type_sint64;
    case TYPE_U64:  return &ffi_type_uint64;
    case TYPE_F32:  return &ffi_type_float;
    case TYPE_F64:  return &ffi_type_double;
    case TYPE_PTR:  return &ffi_type_pointer;
    case TYPE_CSTR: return &ffi_type_pointer;
    default:        return &ffi_type_void;
    }
}

#define MAX_STR_ARGS 8
static char *str_arg_bufs[MAX_STR_ARGS];
static int   n_str_args = 0;
static void free_str_args(void) { for (int i = 0; i < n_str_args; i++) { orig_free_(str_arg_bufs[i]); str_arg_bufs[i] = 0; } n_str_args = 0; }

static void handle_load_lib(int in_fd, int out_fd) {
    uint32_t path_len; uint8_t is_main;
    if (read_u32(in_fd, &path_len) != 0) orig_exit_(1);
    char *path = (char *)orig_malloc_(path_len + 1);
    if (!path) { send_err(out_fd, "malloc failed"); return; }
    if (read_exact(in_fd, path, path_len) != 0) orig_exit_(1);
    path[path_len] = '\0';
    if (read_exact(in_fd, &is_main, 1) != 0) orig_exit_(1);
    void *h = orig_dlopen_(path, RTLD_NOW | RTLD_GLOBAL);
    orig_free_(path);
    if (!h) { char *err = orig_dlerror_(); send_err(out_fd, err ? err : "dlopen failed"); return; }
    if (is_main) main_handle = h; else if (n_libs < MAX_LIBS) lib_handles[n_libs++] = h;
    send_ok(out_fd);
}

static void handle_call_func(int in_fd, int out_fd) {
    uint32_t name_len; uint8_t ret_type, nargs_byte;
    if (read_u32(in_fd, &name_len) != 0) orig_exit_(1);
    char *name = (char *)orig_malloc_(name_len + 1);
    if (!name) { send_err(out_fd, "malloc failed"); return; }
    if (read_exact(in_fd, name, name_len) != 0) orig_exit_(1);
    name[name_len] = '\0';
    if (read_exact(in_fd, &ret_type, 1) != 0) orig_exit_(1);
    if (read_exact(in_fd, &nargs_byte, 1) != 0) orig_exit_(1);
    int nargs = (int)nargs_byte; if (nargs > MAX_ARGS) nargs = MAX_ARGS;
    union arg_storage arg_vals[MAX_ARGS]; ffi_type *arg_types[MAX_ARGS]; void *arg_ptrs[MAX_ARGS]; n_str_args = 0;
    for (int i = 0; i < nargs; i++) {
        uint8_t type; if (read_exact(in_fd, &type, 1) != 0) orig_exit_(1);
        arg_types[i] = type_code_to_ffi(type); arg_ptrs[i] = &arg_vals[i];
        switch (type) {
        case TYPE_I32: case TYPE_U32: { uint32_t v; if (read_u32(in_fd, &v) != 0) orig_exit_(1); arg_vals[i].u32 = v; break; }
        case TYPE_F32: { uint32_t bits; if (read_u32(in_fd, &bits) != 0) orig_exit_(1); memcpy(&arg_vals[i].f32, &bits, 4); break; }
        case TYPE_I64: case TYPE_U64: case TYPE_PTR: { uint64_t v; if (read_u64(in_fd, &v) != 0) orig_exit_(1); arg_vals[i].u64 = v; break; }
        case TYPE_F64: { uint64_t bits; if (read_u64(in_fd, &bits) != 0) orig_exit_(1); memcpy(&arg_vals[i].f64, &bits, 8); break; }
        case TYPE_CSTR: {
            uint32_t slen; if (read_u32(in_fd, &slen) != 0) orig_exit_(1);
            char *s = (char *)orig_malloc_(slen + 1); if (!s) { send_err(out_fd, "malloc failed"); orig_free_(name); free_str_args(); return; }
            if (read_exact(in_fd, s, slen) != 0) orig_exit_(1);
            s[slen] = '\0';
            if (n_str_args < MAX_STR_ARGS) str_arg_bufs[n_str_args++] = s;
            arg_vals[i].ptr = s;
            break;
        }
        }
    }
    void *sym = orig_dlsym_(RTLD_DEFAULT, name); orig_free_(name);
    if (!sym) { free_str_args(); char *err = orig_dlerror_(); send_err(out_fd, err ? err : "symbol not found"); return; }
    ffi_cif cif; ffi_type *rtype = ret_type == TYPE_VOID ? &ffi_type_void : type_code_to_ffi(ret_type);
    if (ffi_prep_cif(&cif, FFI_DEFAULT_ABI, (unsigned int)nargs, rtype, arg_types) != FFI_OK) { free_str_args(); send_err(out_fd, "ffi_prep_cif failed"); return; }
    union { ffi_arg ival; float fval; double dval; } ret; memset(&ret, 0, sizeof(ret));
    ffi_call(&cif, FFI_FN(sym), &ret, arg_ptrs); free_str_args();
    send_ok(out_fd);
    switch (ret_type) {
    case TYPE_I32: case TYPE_U32: write_u32(out_fd, (uint32_t)ret.ival); break;
    case TYPE_F32: { uint32_t bits; memcpy(&bits, &ret.fval, 4); write_u32(out_fd, bits); break; }
    case TYPE_I64: case TYPE_U64: case TYPE_PTR: case TYPE_CSTR: write_u64(out_fd, (uint64_t)ret.ival); break;
    case TYPE_F64: { uint64_t bits; memcpy(&bits, &ret.dval, 8); write_u64(out_fd, bits); break; }
    }
}

static void handle_get_var(int in_fd, int out_fd) {
    uint32_t len; if (read_u32(in_fd, &len) != 0) orig_exit_(1);
    char *name = (char *)orig_malloc_(len + 1); if (!name) { send_err(out_fd, "malloc failed"); return; }
    if (read_exact(in_fd, name, len) != 0) orig_exit_(1);
    name[len] = '\0';
    void *sym = orig_dlsym_(RTLD_DEFAULT, name); orig_free_(name);
    if (!sym) { char *err = orig_dlerror_(); send_err(out_fd, err ? err : "symbol not found"); return; }
    send_ok_u64(out_fd, (uint64_t)(uintptr_t)sym);
}

static void handle_memmove(int in_fd, int out_fd) {
    uint64_t dst, src, count;
    if (read_u64(in_fd, &dst) != 0) orig_exit_(1);
    if (read_u64(in_fd, &src) != 0) orig_exit_(1);
    if (read_u64(in_fd, &count) != 0) orig_exit_(1);
    if (orig_memmove_) { orig_memmove_((void *)(uintptr_t)dst, (const void *)(uintptr_t)src, (size_t)count); send_ok(out_fd); }
    else send_err(out_fd, "memmove not found");
}

static void handle_memset(int in_fd, int out_fd) {
    uint64_t dst, count; uint8_t val;
    if (read_u64(in_fd, &dst) != 0) orig_exit_(1);
    if (read_exact(in_fd, &val, 1) != 0) orig_exit_(1);
    if (read_u64(in_fd, &count) != 0) orig_exit_(1);
    if (orig_memset_) { orig_memset_((void *)(uintptr_t)dst, (int)val, (size_t)count); send_ok(out_fd); }
    else send_err(out_fd, "memset not found");
}

static void handle_alloc(int in_fd, int out_fd) {
    uint64_t size;
    if (read_u64(in_fd, &size) != 0) orig_exit_(1);
    void *ptr = orig_malloc_ ? orig_malloc_((size_t)size) : NULL;
    if (ptr) send_ok_u64(out_fd, (uint64_t)(uintptr_t)ptr);
    else send_err(out_fd, "malloc failed");
}

static void handle_free(int in_fd, int out_fd) {
    uint64_t addr;
    if (read_u64(in_fd, &addr) != 0) orig_exit_(1);
    if (orig_free_) { orig_free_((void *)(uintptr_t)addr); send_ok(out_fd); }
    else send_err(out_fd, "free not found");
}

static void handle_read_mem(int in_fd, int out_fd) {
    uint64_t addr; uint32_t size;
    if (read_u64(in_fd, &addr) != 0) orig_exit_(1);
    if (read_u32(in_fd, &size) != 0) orig_exit_(1);
    send_ok(out_fd);
    write_exact(out_fd, (const void *)(uintptr_t)addr, (size_t)size);
}

static void handle_write_mem(int in_fd, int out_fd) {
    uint64_t addr; uint32_t size;
    if (read_u64(in_fd, &addr) != 0) orig_exit_(1);
    if (read_u32(in_fd, &size) != 0) orig_exit_(1);
    unsigned char *buf = (unsigned char *)orig_malloc_((size_t)size);
    if (!buf) { send_err(out_fd, "malloc failed for write buffer"); return; }
    if (read_exact(in_fd, buf, size) != 0) { orig_free_(buf); orig_exit_(1); }
    memcpy((void *)(uintptr_t)addr, buf, (size_t)size);
    orig_free_(buf);
    send_ok(out_fd);
}

static void main_loop(int in_fd, int out_fd) {
    uint8_t op;
    while (read_exact(in_fd, &op, 1) == 0) {
        switch (op) {
        case OP_LOAD_LIB:  handle_load_lib(in_fd, out_fd); break;
        case OP_CALL_FUNC: handle_call_func(in_fd, out_fd); break;
        case OP_GET_VAR:   handle_get_var(in_fd, out_fd); break;
        case OP_MEMMOVE:   handle_memmove(in_fd, out_fd); break;
        case OP_MEMSET:    handle_memset(in_fd, out_fd); break;
        case OP_ALLOC:     handle_alloc(in_fd, out_fd); break;
        case OP_FREE:      handle_free(in_fd, out_fd); break;
        case OP_READ_MEM:  handle_read_mem(in_fd, out_fd); break;
        case OP_WRITE_MEM: handle_write_mem(in_fd, out_fd); break;
        case OP_SHUTDOWN:  orig_exit_(0); break;
        default:           orig_exit_(1); break;
        }
    }
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    init_ptrs();
    int in_fd = STDIN_FILENO, out_fd = STDOUT_FILENO;
    if (argc >= 3) { in_fd = atoi(argv[1]); out_fd = atoi(argv[2]); }
    main_loop(in_fd, out_fd);
    return 0;
}
