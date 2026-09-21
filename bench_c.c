#include <stdio.h>
#include <stdint.h>

int main(void)
{
    int64_t x = 1;

    for (int64_t i = 0; i < 10000000; ++i) {
        x = (x * 3 + i) % 1000000007LL;
    }

    printf("%lld\n", (long long)x);
    return 0;
}
