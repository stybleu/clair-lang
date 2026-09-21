#include <stdio.h>
#include <stdlib.h>

typedef struct {
    long long *data;
    size_t len;
    size_t cap;
} IntList;

static void ajoute(IntList *l, long long value)
{
    if (l->len >= l->cap) {
        l->cap = l->cap ? l->cap * 2 : 4;

        long long *p = realloc(
            l->data,
            l->cap * sizeof(long long)
        );

        if (!p) {
            exit(1);
        }

        l->data = p;
    }

    l->data[l->len++] = value;
}

int main(void)
{
    IntList nombres = {0};

    ajoute(&nombres, 0);

    for (long long i = 0; i < 1000000; ++i) {
        ajoute(&nombres, 50);
    }

    printf("Longueur : %zu\n", nombres.len);
    printf("Dernier : %lld\n", nombres.data[1000000]);

    free(nombres.data);

    return 0;
}
