#include <stdint.h>

int32_t i32_vals[5] = {10, 20, 30, 40, 50};
int32_t *i32_ptr = i32_vals;

int64_t i64_vals[3] = {100, 200, 300};
int64_t *i64_ptr = i64_vals;

float f32_vals[3] = {1.1f, 2.2f, 3.3f};
float *f32_ptr = f32_vals;

double f64_vals[2] = {1.1, 2.2};
double *f64_ptr = f64_vals;

void reset_arrays() {
    i32_vals[0] = 10; i32_vals[1] = 20; i32_vals[2] = 30; i32_vals[3] = 40; i32_vals[4] = 50;
    i64_vals[0] = 100; i64_vals[1] = 200; i64_vals[2] = 300;
    f32_vals[0] = 1.1f; f32_vals[1] = 2.2f; f32_vals[2] = 3.3f;
    f64_vals[0] = 1.1; f64_vals[1] = 2.2;
    
    i32_ptr = i32_vals;
    i64_ptr = i64_vals;
    f32_ptr = f32_vals;
    f64_ptr = f64_vals;
}

int32_t get_i32(int idx) { return i32_vals[idx]; }
int64_t get_i64(int idx) { return i64_vals[idx]; }
float   get_f32(int idx) { return f32_vals[idx]; }
double  get_f64(int idx) { return f64_vals[idx]; }
