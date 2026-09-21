#include <stdio.h>

static inline long long addition_int(long long a, long long b)
{
    return a + b;
}

static inline double addition_double(double a, double b)
{
    return a + b;
}

static inline double addition_mixte(long long a, double b)
{
    return (double)a + b;
}

int main(void)
{
    long long entier_resultat = 0;
    double decimal_resultat = 0.0;
    double mixte_resultat = 0.0;

    for (long long i = 0; i < 10000000; ++i) {
        entier_resultat = addition_int(entier_resultat, 1);
        decimal_resultat =
            addition_double(decimal_resultat, 0.000001);
        mixte_resultat = addition_mixte(i, 0.5);
    }

    printf("%lld\n", entier_resultat);
    printf("%g\n", decimal_resultat);
    printf("%g\n", mixte_resultat);

    return 0;
}
