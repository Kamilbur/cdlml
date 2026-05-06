#include <stdint.h>
#include <string.h>

int32_t global_i32 = 42;
char global_buf[32] = "initial";

void reset_compat() {
    global_i32 = 42;
    strcpy(global_buf, "initial");
}

int32_t get_global_i32() {
    return global_i32;
}

const char* get_global_buf() {
    return global_buf;
}

typedef struct {
    int32_t a;
    double b;
    char c[16];
} test_struct_t;

test_struct_t global_struct = {1, 2.0, "struct"};

void reset_struct() {
    global_struct.a = 1;
    global_struct.b = 2.0;
    strcpy(global_struct.c, "struct");
}

int32_t sum_struct(test_struct_t *s) {
    if (!s) return -1;
    return s->a + (int32_t)s->b;
}

void set_i32_ptr(int32_t *p, int32_t value) {
    if (p) *p = value;
}

void write_byte_ptr(char *p, int32_t value) {
    if (p) *p = (char)value;
}

int32_t read_i32_ptr(int32_t *p) {
    if (!p) return -1;
    return *p;
}

typedef struct {
    int32_t x;
    int32_t y;
} point_t;

typedef struct {
    point_t top_left;
    point_t bottom_right;
} rect_t;

typedef union {
    int32_t i;
    float f;
    char bytes[4];
} data_union_t;

typedef struct {
    rect_t rects[2];
    data_union_t u;
} complex_t;

complex_t global_complex = {
    .rects = {{{0,0}, {10,10}}, {{20,20}, {30,30}}},
    .u = {.i = 12345}
};

void reset_complex() {
    global_complex.rects[0].top_left.x = 0;
    global_complex.rects[0].top_left.y = 0;
    global_complex.rects[0].bottom_right.x = 10;
    global_complex.rects[0].bottom_right.y = 10;
    global_complex.rects[1].top_left.x = 20;
    global_complex.rects[1].top_left.y = 20;
    global_complex.rects[1].bottom_right.x = 30;
    global_complex.rects[1].bottom_right.y = 30;
    global_complex.u.i = 12345;
}

int32_t get_rect_area(rect_t *r) {
    if (!r) return -1;
    return (r->bottom_right.x - r->top_left.x) * (r->bottom_right.y - r->top_left.y);
}

char global_large_buf[1024];

void reset_large_buf() {
    for (int i = 0; i < 1024; i++) global_large_buf[i] = (char)(i & 0xFF);
}

data_union_t get_complex_union() {
    return global_complex.u;
}
