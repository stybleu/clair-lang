#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *concat(const char *a, const char *b)
{
    size_t la = strlen(a);
    size_t lb = strlen(b);

    char *r = malloc(la + lb + 1);

    if (!r) {
        exit(1);
    }

    memcpy(r, a, la);
    memcpy(r + la, b, lb);
    r[la + lb] = '\0';

    return r;
}

int main(void)
{
    char *nom = concat("Al", "ice");
    char *cible = concat("A", "lice");

    long long compteur = 0;

    for (long long i = 0; i < 50000000; ++i) {
        if (strcmp(nom, cible) == 0) {
            compteur++;
        }
    }

    printf("%lld\n", compteur);

    free(nom);
    free(cible);

    return 0;
}
