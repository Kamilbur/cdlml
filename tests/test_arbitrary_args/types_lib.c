#include <stdint.h>
#include <string.h>

void     noop(void) {}

int32_t  add_i32(int32_t a, int32_t b)       { return a + b; }
int32_t  negate_i32(int32_t x)               { return -x; }
int32_t  identity_i32(int32_t x)             { return x; }
int32_t  sum3_i32(int32_t a, int32_t b, int32_t c) { return a + b + c; }

int64_t  add_i64(int64_t a, int64_t b)       { return a + b; }
int64_t  identity_i64(int64_t x)             { return x; }

uint32_t add_u32(uint32_t a, uint32_t b)     { return a + b; }
uint64_t add_u64(uint64_t a, uint64_t b)     { return a + b; }

float    add_f32(float a, float b)            { return a + b; }
float    scale_f32(float x, float s)          { return x * s; }
float    identity_f32(float x)                { return x; }
float    f64_to_f32(double x)                 { return (float)x; }

double   add_f64(double a, double b)          { return a + b; }
double   scale_f64(double x, double s)        { return x * s; }
double   identity_f64(double x)               { return x; }
double   sum3_f64(double a, double b, double c) { return a + b + c; }
double   i32_to_f64(int32_t x)               { return (double)x; }

uint32_t str_len(const char *s)              { return (uint32_t)strlen(s); }
