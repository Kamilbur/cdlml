#include <stdio.h>
#include <stdlib.h>


int foo(int n) {
    if (n < 0) {
        return -1;
    }
    if (n == 0) {
        return 0;
    }
    if (n == 1) {
        return 1;
    }

    int *fib = (int *)malloc((n + 1) * sizeof(int));
    if (fib == NULL) {
        return -1;
    }

    fib[0] = 0;
    fib[1] = 1;

    for (int i = 2; i <= n; i++) {
        fib[i] = fib[i - 1] + fib[i - 2];
    }

    int result = fib[n];
    free(fib);
    return result;
}
