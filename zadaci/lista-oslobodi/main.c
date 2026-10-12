#include <stdio.h>
#include <stdlib.h>

typedef struct Vozlisce {
    int podatek;
    struct Vozlisce *naslednje;
} Vozlisce;

Vozlisce *dodaj(Vozlisce *glava, int x) {
    Vozlisce *novo = malloc(sizeof(Vozlisce));
    novo->podatek = x;
    novo->naslednje = NULL;
    if (glava == NULL) {
        return novo;
    }
    Vozlisce *tren = glava;
    while (tren->naslednje != NULL) {
        tren = tren->naslednje;
    }
    tren->naslednje = novo;
    return glava;
}

void izpisi(Vozlisce *glava) {
    Vozlisce *tren = glava;
    while (tren != NULL) {
        printf("%d", tren->podatek);
        if (tren->naslednje != NULL) {
            printf(" ");
        }
        tren = tren->naslednje;
    }
    printf("\n");
}

void sprosti(Vozlisce *glava) {
    Vozlisce *tren = glava;
    while (tren != NULL) {
        Vozlisce *next = tren->naslednje;
        free(tren);
        tren = next;
    }
}

int main(void) {
    int n;
    scanf("%d", &n);
    Vozlisce *glava = NULL;
    for (int i = 0; i < n; i++) {
        int x;
        scanf("%d", &x);
        glava = dodaj(glava, x);
    }
    izpisi(glava);

    return 0;
}