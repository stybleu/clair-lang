#include <stdio.h>

int main(void)
{
    double x = 1.25;

    for (long long i = 0; i < 10000000; ++i) {
        x = (x + 0.000001) * 1.0000001;
    }

    printf("%.17g\n", x);

    return 0;
}
