#include <stdio.h>
#include <stdlib.h>

typedef struct Vozlisce {
    int podatek;
    struct Vozlisce *naslednje;
} Vozlisce;

/* Doda element na konec seznama, vrne (morda novo) glavo. */
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

/* Odstrani vse sode elemente, vrne novo glavo. */
Vozlisce *odstraniSode(Vozlisce *glava) {
    Vozlisce *prev = NULL;
    Vozlisce *tren = glava;
    while (tren != NULL) {
        if (tren->podatek % 2 == 0) {
            Vozlisce *next = tren->naslednje;
            if (prev == NULL) {
                glava = next;
            } else {
                prev->naslednje = next;
            }
            free(tren);
            tren = next;
        } else {
            prev = tren;
            tren = tren->naslednje;
        }
    }
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
    glava = odstraniSode(glava);
    izpisi(glava);
    sprosti(glava);
    return 0;
}
