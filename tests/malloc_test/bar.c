#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>


int bar(int n) {
    if (n < 0) {
        return -1;
    }
    uint64_t *fact = malloc((size_t)(n + 1) * sizeof(*fact));

    fact[0] = 1ULL;
    for (uint64_t i = 1; i <= n; i++) {
        fact[i] = fact[i - 1] * i;
    }

    int result = (int) fact[n];
    free(fact);
    return result;

}
