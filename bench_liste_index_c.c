#include <stdio.h>

int main(void)
{
    long long nombres[] = {10, 20, 30, 40, 50};
    long long somme = 0;

    for (long long i = 0; i < 100000000; ++i) {
        somme += nombres[i % 5];
    }

    printf("%lld\n", somme);

    return 0;
}
