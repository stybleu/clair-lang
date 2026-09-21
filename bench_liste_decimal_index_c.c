#include <stdio.h>

int main(void)
{
    double valeurs[] = {1.5, 2.5, 3.5, 4.5, 5.5};
    double somme = 0.0;

    for (long long i = 0; i < 100000000; ++i) {
        somme += valeurs[i % 5];
    }

    printf("%g\n", somme);

    return 0;
}
