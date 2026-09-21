#include <stdio.h>
#include <string.h>

int main(void)
{
    const char *nom = "Alice";
    const char *cible = "Alice";
    long long compteur = 0;

    for (long long i = 0; i < 100000000; ++i) {
        if (strcmp(nom, cible) == 0) {
            compteur++;
        }
    }

    printf("%lld\n", compteur);
    return 0;
}
